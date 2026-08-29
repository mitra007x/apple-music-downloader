import os
import re
import time
import asyncio
import shutil
import glob
import zipfile
import signal
import traceback
from mutagen import File

from pyrogram import Client
from pyrogram.errors import FloodWait

import bot.state as state
from bot.config import BASE_DIR, DOWN_DIR, STAGE_BASE_DIR, ADMIN_ID, MAX_PLAYLIST_TRACKS, DUMP_CHANNEL_ID
from bot.utils import replace_prefix, get_video_quality, extract_video_info, extract_base_meta, sanitize_filename, get_cover_art, get_audio_info, generate_final_caption, format_bytes, escape_markdown_v2
from bot.upload import upload_to_gofile_curl, progress_tracker, monitor_zip_file, monitor_down_folder_size

async def wait_and_process(bot, pyro_app, dl_id):
    try:
        async with state.download_tasks_lock:
            if dl_id not in state.download_registry: return
            task_info = state.download_registry[dl_id]
            user_cancelled = task_info['user_cancelled']
        
        semaphore_task = asyncio.create_task(state.download_semaphore.acquire())
        cancel_task = asyncio.create_task(user_cancelled.wait())
        
        done, pending = await asyncio.wait(
            [semaphore_task, cancel_task],
            return_when=asyncio.FIRST_COMPLETED
        )
        
        if cancel_task in done:
            if semaphore_task in done: state.download_semaphore.release()
            else: semaphore_task.cancel()
            
            async with state.download_tasks_lock:
                if dl_id in state.download_registry: del state.download_registry[dl_id]
            async with state.queue_lock:
                uid = task_info.get('user_id')
                if uid in state.user_requests:
                    state.user_requests[uid] = [r for r in state.user_requests[uid] if r['dl_id'] != dl_id]
            
            state.FORCE_NEW_STATUS = True
            return
        
        cancel_task.cancel()
        slot_number = await state.available_slots.get()
        await download_worker(bot, pyro_app, dl_id, slot_number)
    except Exception as e:
        if not isinstance(e, asyncio.CancelledError):
            print(f"Queue processor error: {e}")

async def download_worker(bot, pyro_app: Client, dl_id: str, slot_number: int):
    task_info = {}
    zip_paths = []
    
    dl_lock_released = False
    ul_lock_acquired = False
    stage_dir = os.path.join(STAGE_BASE_DIR, dl_id)
    
    try:
        async with state.download_tasks_lock:
            if dl_id not in state.download_registry: return
            task_info = state.download_registry[dl_id]
            if task_info["user_cancelled"].is_set(): raise Exception("Cancelled by user.")
            
            task_info["status"] = "processing"
            task_info["progress_stats"] = "Initializing Downloader..."
            task_info["start_time"] = time.time()
            task_info["current_track_str"] = ""
            task_info["fallback_tracks"] = []
            task_info["failed_tracks"] = []
            task_info["failed_atmos_tracks"] = []
            task_info["current_track_num"] = 0
            task_info["total_tracks"] = 0
            
        url = task_info['url']
        is_video = '/music-video/' in url
        is_single = '?i=' in url or '/song/' in url
        is_playlist = '/playlist/' in url
        
        if is_video: download_type = 'video'
        elif is_playlist: download_type = 'playlist'
        elif is_single: download_type = 'single'
        else: download_type = 'album'

        try: shutil.rmtree(DOWN_DIR, ignore_errors=True)
        except Exception: pass
        os.makedirs(DOWN_DIR, exist_ok=True)

        cmd = ['go', 'run', 'main.go']
        if is_single: cmd.append('--song')
        
        is_aac_request = task_info.get('quality_flag') == 'aac'
        is_atmos_request = task_info.get('quality_flag') == 'atmos'
        
        if not is_video:
            if is_aac_request: cmd.append('--aac')
            elif is_atmos_request: cmd.append('--atmos')
            
        cmd.append(url)
        
        async with state.download_tasks_lock: state.download_registry[dl_id]['progress_stats'] = "Downloading..."
        
        process = await asyncio.create_subprocess_exec(
            *cmd, cwd=BASE_DIR,
            stdin=asyncio.subprocess.DEVNULL, 
            stdout=asyncio.subprocess.PIPE, 
            stderr=asyncio.subprocess.STDOUT, 
            preexec_fn=os.setsid 
        )
        
        async with state.download_tasks_lock: state.download_registry[dl_id]['process'] = process

        folder_done_event = asyncio.Event()
        folder_monitor_task = asyncio.create_task(monitor_down_folder_size(dl_id, folder_done_event))

        async def monitor_stdout(stdout, cancel_event, user_cancel):
            buffer = b""
            ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
            line_history = []
            
            while not cancel_event.is_set() and not user_cancel.is_set():
                try:
                    chunk = await asyncio.wait_for(stdout.read(2048), timeout=1.0)
                    if not chunk: break
                    buffer += chunk
                    while b'\r' in buffer or b'\n' in buffer:
                        if b'\r' in buffer and (b'\n' not in buffer or buffer.find(b'\r') < buffer.find(b'\n')):
                            line, buffer = buffer.split(b'\r', 1)
                        else:
                            line, buffer = buffer.split(b'\n', 1)
                        
                        line_str = ansi_escape.sub('', line.decode('utf-8', errors='ignore').strip())
                        if not line_str: continue
                        
                        line_history.append(line_str)
                        if len(line_history) > 10:
                            line_history.pop(0)
                        
                        lower_line = line_str.lower()
                        
                        if "video:" in lower_line:
                            async with state.download_tasks_lock:
                                if dl_id in state.download_registry: state.download_registry[dl_id]['current_track_str'] = "Video | "
                        elif "audio:" in lower_line:
                            async with state.download_tasks_lock:
                                if dl_id in state.download_registry: state.download_registry[dl_id]['current_track_str'] = "Audio | "
                        
                        if any(err in lower_line for err in [
                            "404 not found", "failed to get album response", "error getting album response", 
                            "failed to rip album", "failed to get playlist", "error getting playlist",
                            "failed to rip playlist", "failed to get song", "error getting song",
                            "failed to get video", "error getting video",
                            "failed to dl mv", "api error details: unavailable", "press enter to try again"
                        ]):
                            task_info['custom_error'] = "❌ Item is Unavailable or Region Blocked."
                            try: os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                            except: process.kill()
                            break

                        if "error reading response" in lower_line:
                            task_info['stalled_error'] = line_str
                            try: os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                            except: process.kill()
                            break
                        
                        async with state.download_tasks_lock:
                            if dl_id in state.download_registry:
                                m_track_1 = re.search(r'^(?:Track|Item)\s+(\d+)\s+(?:of|/)\s+(\d+)', line_str, re.IGNORECASE)
                                m_track_2 = re.search(r'^\[(\d+)/(\d+)\]', line_str)
                                
                                if m_track_1 or m_track_2:
                                    m = m_track_1 if m_track_1 else m_track_2
                                    t_num = int(m.group(1))
                                    t_tot = int(m.group(2))
                                    state.download_registry[dl_id]['current_track_num'] = t_num
                                    state.download_registry[dl_id]['total_tracks'] = t_tot
                                    state.download_registry[dl_id]['current_track_str'] = f"Track {t_num}/{t_tot} | "
                                    
                                    if is_playlist and not task_info.get('playlist_name'):
                                        for past_line in reversed(line_history[:-1]):
                                            if past_line and past_line.strip() not in ["Apple Music", "songs"] and not past_line.startswith("Queue") and not past_line.startswith("Track"):
                                                task_info['playlist_name'] = past_line.strip()
                                                break
                                    
                                    if task_info['user_id'] != ADMIN_ID and t_tot > MAX_PLAYLIST_TRACKS:
                                        task_info['custom_error'] = f"LimitExceeded: ❌ Playlists are limited to {MAX_PLAYLIST_TRACKS} tracks\\. This one has {t_tot}\\."
                                        try: os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                                        except: process.kill()
                                        break

                                curr_track_num = state.download_registry[dl_id].get('current_track_num', 0)

                                if "failed to extract info from manifest: no codec found" in lower_line and curr_track_num:
                                    if curr_track_num not in state.download_registry[dl_id]['failed_atmos_tracks']:
                                        state.download_registry[dl_id]['failed_atmos_tracks'].append(curr_track_num)
                                        if is_single:
                                            task_info['custom_error'] = "❌ Not available in Dolby Atmos quality."
                                            try: os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                                            except: process.kill()
                                            break

                                if "trying to dl aac" in lower_line and curr_track_num:
                                    if curr_track_num not in state.download_registry[dl_id]['fallback_tracks']:
                                        state.download_registry[dl_id]['fallback_tracks'].append(curr_track_num)
                                
                                if ("failed to dl" in lower_line or "unavailable" in lower_line) and "trying to" not in lower_line and curr_track_num:
                                    if curr_track_num not in state.download_registry[dl_id]['failed_tracks']:
                                        state.download_registry[dl_id]['failed_tracks'].append(curr_track_num)

                                curr_track = state.download_registry[dl_id].get('current_track_str', '')
                                
                                if "Downloading" in line_str and "(" in line_str and "MB/s" in line_str:
                                    try:
                                        inner = line_str.split('(')[1].split(')')[0]
                                        parts = inner.split(',')
                                        if len(parts) == 2:
                                            prog_size = parts[0].strip()
                                            speed = parts[1].strip()
                                            state.download_registry[dl_id]['status'] = 'downloading'
                                            state.download_registry[dl_id]['progress_stats'] = f"{curr_track}{prog_size}"
                                            state.download_registry[dl_id]['progress_speed'] = speed
                                            continue
                                    except: pass

                                match_std = re.search(r'(\d+(?:\.\d+)?)%\s*\(([^,]+)(?:,\s*([^)]+))?\)', line_str)
                                if match_std:
                                    pct = match_std.group(1) + "%"
                                    prog_size = match_std.group(2).strip()
                                    speed = match_std.group(3).strip() if match_std.group(3) else "-"
                                    state.download_registry[dl_id]['status'] = 'downloading'
                                    state.download_registry[dl_id]['progress_stats'] = f"{curr_track}{pct} ({prog_size})"
                                    state.download_registry[dl_id]['progress_speed'] = speed
                                elif "Downloading" in line_str or "Processing" in line_str:
                                    if not re.search(r'^(?:Track|Item)\s+\d+\s+(?:of|/)\s+\d+', line_str, re.IGNORECASE):
                                        state.download_registry[dl_id]['status'] = 'downloading'
                                        clean_line = re.sub(r'^\[.*?\]\s*', '', line_str)[:40]
                                        state.download_registry[dl_id]['progress_stats'] = f"{curr_track}{clean_line}"
                                        state.download_registry[dl_id]['progress_speed'] = "-"
                except asyncio.TimeoutError: continue
                except Exception: break

        monitor_task = asyncio.create_task(monitor_stdout(process.stdout, task_info.get('cancel_event', asyncio.Event()), task_info['user_cancelled']))

        while process.returncode is None:
            if task_info['user_cancelled'].is_set():
                try: os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                except:
                    try: process.kill()
                    except: pass
                break
            try: await asyncio.wait_for(process.wait(), timeout=1.0)
            except asyncio.TimeoutError: pass
            
        await monitor_task
        folder_done_event.set()
        try: await folder_monitor_task
        except: pass
        
        if task_info['user_cancelled'].is_set(): raise Exception("Cancelled by user.")

        all_files = []
        for ext in ['*.m4a', '*.mp3', '*.aac', '*.flac', '*.wav', '*.mp4', '*.jpg', '*.png', '*.jpeg']:
            all_files.extend(glob.glob(os.path.join(DOWN_DIR, '**', ext), recursive=True))
        
        media_files = [f for f in all_files if not f.lower().endswith(('.jpg', '.jpeg', '.png'))]
        
        if not media_files: 
            if task_info.get('custom_error'): 
                raise Exception(task_info['custom_error'])
            
            failed_atmos = task_info.get('failed_atmos_tracks', [])
            total_t = task_info.get('total_tracks', 0)
            if is_atmos_request and failed_atmos and (total_t == 0 or len(failed_atmos) == total_t or len(failed_atmos) > 0):
                raise Exception("❌ Not available in Dolby Atmos quality.")

            if task_info.get('stalled_error'): raise Exception(f"Downloader Crash: {task_info['stalled_error']}")
            if task_info.get('failed_tracks'): raise Exception("❌ Not available in the configured account region.")
            raise Exception("❌ Error: No media files found after download. Check if the go script is outputting to 'down' folder.")

        video_quality_str = ""
        vid_thumb, vid_duration, vid_w, vid_h = None, 0, 0, 0
        if is_video and media_files:
            video_quality_str = get_video_quality(media_files[0])
            vid_thumb, vid_duration, vid_w, vid_h = await extract_video_info(media_files[0])
            if vid_thumb:
                all_files.append(vid_thumb)

        os.makedirs(stage_dir, exist_ok=True)
        for item in os.listdir(DOWN_DIR):
            shutil.move(os.path.join(DOWN_DIR, item), os.path.join(stage_dir, item))
            
        media_files = [replace_prefix(f, DOWN_DIR, stage_dir) for f in media_files]
        all_files = [replace_prefix(f, DOWN_DIR, stage_dir) for f in all_files]

        if vid_thumb:
            vid_thumb = replace_prefix(vid_thumb, DOWN_DIR, stage_dir)

        dl_lock_released = True
        state.download_semaphore.release()
        await state.available_slots.put(slot_number)

        try:
            await asyncio.wait_for(state.upload_semaphore.acquire(), timeout=0.1)
            ul_lock_acquired = True
        except asyncio.TimeoutError:
            async with state.download_tasks_lock:
                if dl_id in state.download_registry:
                    state.download_registry[dl_id]['status'] = "waiting for upload"
            
            cancel_task = asyncio.create_task(task_info['user_cancelled'].wait())
            ul_task = asyncio.create_task(state.upload_semaphore.acquire())
            done, pending = await asyncio.wait([ul_task, cancel_task], return_when=asyncio.FIRST_COMPLETED)
            if cancel_task in done:
                if ul_task in done: state.upload_semaphore.release()
                else: ul_task.cancel()
                raise Exception("Cancelled by user.")
            ul_lock_acquired = True

        upload_to_telegram_flag = task_info.get('upload_to_telegram_flag', False)
        unzip_flag = task_info.get('unzip_flag', False)
        force_zip_flag = task_info.get('force_zip_flag', False)

        async with state.download_tasks_lock:
            if dl_id in state.download_registry:
                next_stat = "zipping" if force_zip_flag or not upload_to_telegram_flag else "uploading"
                state.download_registry[dl_id]['status'] = next_stat

        fallback_tracks = [t for t in task_info.get('fallback_tracks', []) if t not in task_info.get('failed_tracks', [])]
        failed_tracks = task_info.get('failed_tracks', [])
        
        detected_qualities = set()
        for f in media_files:
            if is_aac_request:
                detected_qualities.add("256kbps AAC")
            else:
                try:
                    audio = File(f)
                    bd = getattr(audio.info, 'bits_per_sample', 16)
                    sr = getattr(audio.info, 'sample_rate', 44100)
                    sr_fmt = f"{sr/1000:g}kHz"
                    file_ext = f.lower().rsplit('.', 1)[-1]
                    codec = "ALAC" if file_ext == 'm4a' and 'alac' in getattr(audio.info, 'codec_description', '').lower() else file_ext.upper()
                    if codec == 'M4A' or codec == 'MP4': codec = 'AAC'
                    if codec == 'AAC': detected_qualities.add("256kbps AAC")
                    else: detected_qualities.add(f"{bd}bit-{sr_fmt} {codec}")
                except: detected_qualities.add("256kbps AAC")
                
        base_meta = extract_base_meta(media_files)
        base_meta['playlist_name'] = task_info.get('playlist_name', 'Playlist')
        total_uncompressed_size = sum(os.path.getsize(f) for f in all_files)

        if not (upload_to_telegram_flag and unzip_flag) or force_zip_flag:
            if is_atmos_request: final_q_str = "Dolby Atmos"
            else: final_q_str = " | ".join(sorted(list(detected_qualities), reverse=True)) or "256kbps AAC"
            
            zip_q_str = final_q_str.replace("kbps", "K").replace("bit-", "B-").replace(" | ", ", ")
            
            s_entity = sanitize_filename(base_meta['album'])
            n_files = len(media_files)
            if is_playlist:
                s_entity = sanitize_filename(task_info.get('playlist_name', 'Playlist'))
                zip_base_name = f"{s_entity} ({zip_q_str})(AM)[{n_files}]"
            elif is_video: zip_base_name = f"{sanitize_filename(base_meta['track'] or 'Video')} ({zip_q_str})(AM)"
            elif is_single: zip_base_name = f"{sanitize_filename(base_meta['track'] or base_meta['album'])} ({zip_q_str})(AM)"
            else:
                ys = f" [{base_meta['year']}]" if base_meta['year'] != 'Unknown' else ""
                zip_base_name = f"{s_entity}{ys} ({zip_q_str})(AM)[{n_files}]"

            file_batches = []
            MAX_BATCH_SIZE = 1.9 * 1024 * 1024 * 1024
            
            if (upload_to_telegram_flag and force_zip_flag) and total_uncompressed_size > MAX_BATCH_SIZE:
                cur_batch, cur_size = [], 0
                for f in sorted(all_files, key=lambda x: os.path.basename(x)):
                    fsz = os.path.getsize(f)
                    if cur_batch and cur_size + fsz > MAX_BATCH_SIZE:
                        file_batches.append(cur_batch)
                        cur_batch, cur_size = [], 0
                    cur_batch.append(f)
                    cur_size += fsz
                if cur_batch: file_batches.append(cur_batch)
            else:
                file_batches = [all_files]

            for i, batch in enumerate(file_batches):
                if len(file_batches) > 1: part_name = f"{zip_base_name} - Part {i+1} of {len(file_batches)}.zip"
                else: part_name = f"{zip_base_name}.zip"
                    
                z_path = os.path.join(stage_dir, part_name)
                zip_paths.append(z_path)
                
                zip_monitor_done = asyncio.Event()
                batch_size = sum(os.path.getsize(f) for f in batch)
                monitor_task = asyncio.create_task(monitor_zip_file(z_path, batch_size, dl_id, zip_monitor_done, part_num=i+1 if len(file_batches)>1 else None))
                
                def create_zip(target_path, files_to_zip, cancel_event):
                    with zipfile.ZipFile(target_path, 'w', zipfile.ZIP_STORED) as z:
                        for f in files_to_zip:
                            if cancel_event.is_set():
                                raise Exception("Cancelled by user.")
                            z.write(f, os.path.relpath(f, stage_dir))
                
                try:
                    await asyncio.to_thread(create_zip, z_path, batch, task_info['user_cancelled'])
                finally:
                    zip_monitor_done.set()
                    try: await monitor_task
                    except: pass

        if task_info['user_cancelled'].is_set(): raise Exception("Cancelled by user.")

        chat_id = task_info['chat_id']
        reply_id = task_info['reply_to_message_id']
        
        async with state.download_tasks_lock: state.download_registry[dl_id]['status'] = "uploading"
            
        if not upload_to_telegram_flag:
            gl = await upload_to_gofile_curl(zip_paths[0], dl_id, task_info['user_cancelled'])
            if gl:
                ptb_cap, pyro_cap, n_ptb, n_pyro = generate_final_caption(
                    url, os.path.getsize(zip_paths[0]), detected_qualities, download_type, base_meta, len(media_files), 
                    {"failed_tracks": failed_tracks, "total_tracks": task_info.get('total_tracks', 0), "failed_atmos_tracks": task_info.get('failed_atmos_tracks', []), "stalled_error": task_info.get('stalled_error')}, 
                    fallback_tracks, stage_dir, is_atmos_request, video_quality_str
                )
                dl_link_str = f"\n*Download Link*: [*_{escape_markdown_v2(os.path.basename(zip_paths[0]))}_*]({escape_markdown_v2(gl)})"
                final_msg_text = f"✅ *Upload Complete\\!*\n\n{ptb_cap}{dl_link_str}{n_ptb}"
                
                if DUMP_CHANNEL_ID:
                    try:
                        d_msg = await bot.send_message(chat_id=DUMP_CHANNEL_ID, text=final_msg_text, parse_mode='MarkdownV2', disable_web_page_preview=True)
                        await bot.copy_message(chat_id, DUMP_CHANNEL_ID, d_msg.message_id, reply_to_message_id=reply_id)
                    except: await bot.send_message(chat_id=chat_id, message_thread_id=task_info['thread_id'], text=final_msg_text, parse_mode='MarkdownV2', reply_to_message_id=reply_id, disable_web_page_preview=True)
                else:
                    await bot.send_message(chat_id=chat_id, message_thread_id=task_info['thread_id'], text=final_msg_text, parse_mode='MarkdownV2', reply_to_message_id=reply_id, disable_web_page_preview=True)
            else: raise Exception("GoFile Upload Failed.")

        else:
            ptb_cap, pyro_cap, n_ptb, n_pyro = generate_final_caption(
                url, total_uncompressed_size if unzip_flag and not force_zip_flag else sum(os.path.getsize(z) for z in zip_paths), detected_qualities, download_type, base_meta, len(media_files), 
                {"failed_tracks": failed_tracks, "total_tracks": task_info.get('total_tracks', 0), "failed_atmos_tracks": task_info.get('failed_atmos_tracks', []), "stalled_error": task_info.get('stalled_error')}, 
                fallback_tracks, stage_dir, is_atmos_request, video_quality_str
            )
            
            if unzip_flag:
                cover_path = get_cover_art(stage_dir)
                pyro_cap_audio = pyro_cap + n_pyro
                
                if download_type in ['album', 'playlist'] and cover_path and os.path.exists(cover_path):
                    for attempt in range(5):
                        try:
                            if DUMP_CHANNEL_ID:
                                d_msg = await pyro_app.send_photo(DUMP_CHANNEL_ID, cover_path, caption=pyro_cap_audio)
                                await d_msg.copy(chat_id, reply_to_message_id=reply_id)
                            else:
                                await pyro_app.send_photo(chat_id, cover_path, caption=pyro_cap_audio, reply_to_message_id=reply_id)
                            pyro_cap_audio = "" 
                            break
                        except FloodWait as e:
                            await asyncio.sleep(e.value + 1)
                        except Exception:
                            break 

                for idx, file_path in enumerate(sorted(media_files)):
                    if task_info['user_cancelled'].is_set(): raise Exception("Cancelled by user.")
                    up_time = time.time()
                    t_title, t_perf, t_dur = get_audio_info(file_path)
                    
                    try:
                        for attempt in range(10):
                            try:
                                if is_video:
                                    if DUMP_CHANNEL_ID:
                                        d_msg = await pyro_app.send_video(DUMP_CHANNEL_ID, file_path, caption=pyro_cap_audio if idx == 0 else "", thumb=vid_thumb, duration=vid_duration, width=vid_w, height=vid_h, progress=progress_tracker, progress_args=(dl_id, f"Track {idx+1}/{len(media_files)}" if len(media_files)>1 else "Uploading", up_time))
                                        await d_msg.copy(chat_id, reply_to_message_id=reply_id)
                                    else:
                                        await pyro_app.send_video(chat_id, file_path, caption=pyro_cap_audio if idx == 0 else "", reply_to_message_id=reply_id, thumb=vid_thumb, duration=vid_duration, width=vid_w, height=vid_h, progress=progress_tracker, progress_args=(dl_id, f"Track {idx+1}/{len(media_files)}" if len(media_files)>1 else "Uploading", up_time))
                                else:
                                    if DUMP_CHANNEL_ID:
                                        d_msg = await pyro_app.send_audio(DUMP_CHANNEL_ID, file_path, title=t_title, performer=t_perf, duration=t_dur, thumb=cover_path, caption=pyro_cap_audio if idx == 0 else "", progress=progress_tracker, progress_args=(dl_id, f"Track {idx+1}/{len(media_files)}" if len(media_files)>1 else "Uploading", up_time))
                                        await d_msg.copy(chat_id, reply_to_message_id=reply_id)
                                    else:
                                        await pyro_app.send_audio(chat_id, file_path, title=t_title, performer=t_perf, duration=t_dur, thumb=cover_path, caption=pyro_cap_audio if idx == 0 else "", reply_to_message_id=reply_id, progress=progress_tracker, progress_args=(dl_id, f"Track {idx+1}/{len(media_files)}" if len(media_files)>1 else "Uploading", up_time))
                                break 
                            except FloodWait as e:
                                if attempt < 9:
                                    async with state.download_tasks_lock:
                                        if dl_id in state.download_registry:
                                            state.download_registry[dl_id]['progress_stats'] = f"Sleeping {e.value}s (Rate Limit)"
                                    await asyncio.sleep(e.value + 1)
                                    if task_info['user_cancelled'].is_set(): raise Exception("Cancelled by user.")
                                else:
                                    raise e
                    except asyncio.CancelledError: raise Exception("Cancelled by user.")
                
                if len(media_files) > 1 and not force_zip_flag:
                    await bot.send_message(chat_id=chat_id, message_thread_id=task_info['thread_id'], text=f"✅ *Finished*", parse_mode='MarkdownV2', reply_to_message_id=reply_id, disable_web_page_preview=True)

            if force_zip_flag and zip_paths:
                for i, z_path in enumerate(zip_paths):
                    if task_info['user_cancelled'].is_set(): raise Exception("Cancelled by user.")
                    up_time = time.time()
                    cover_path = vid_thumb if is_video else get_cover_art(stage_dir)
                    
                    p_ext = f"\n\n📦 **This is Part {i+1} of {len(zip_paths)}**" if len(zip_paths) > 1 else ""
                    try: 
                        prog_title = f"Uploading Part {i+1}" if len(zip_paths) > 1 else "Uploading"
                        
                        for attempt in range(10):
                            try:
                                if DUMP_CHANNEL_ID:
                                    d_msg = await pyro_app.send_document(DUMP_CHANNEL_ID, z_path, caption=pyro_cap + n_pyro + p_ext, thumb=cover_path, progress=progress_tracker, progress_args=(dl_id, prog_title, up_time))
                                    await d_msg.copy(chat_id, reply_to_message_id=reply_id)
                                else:
                                    await pyro_app.send_document(chat_id, z_path, caption=pyro_cap + n_pyro + p_ext, reply_to_message_id=reply_id, thumb=cover_path, progress=progress_tracker, progress_args=(dl_id, prog_title, up_time))
                                break
                            except FloodWait as e:
                                if attempt < 9:
                                    async with state.download_tasks_lock:
                                        if dl_id in state.download_registry:
                                            state.download_registry[dl_id]['progress_stats'] = f"Sleeping {e.value}s (Rate Limit)"
                                    await asyncio.sleep(e.value + 1)
                                    if task_info['user_cancelled'].is_set(): raise Exception("Cancelled by user.")
                                else:
                                    raise e
                    except asyncio.CancelledError: raise Exception("Cancelled by user.")

    except Exception as e:
        if not isinstance(e, asyncio.CancelledError):
            traceback.print_exc()
            if task_info:
                err_msg = str(e)
                if "LimitExceeded" in err_msg: final_text = err_msg.replace("LimitExceeded: ", "")
                elif "Cancelled by user" in err_msg: final_text = "❌ *Task Cancelled by User\\.*"
                elif "region" in err_msg.lower(): final_text = "❌ *Not available in the configured account region*"
                elif "❌" in err_msg: final_text = escape_markdown_v2(err_msg)
                else: final_text = f"❌ *Error:* {escape_markdown_v2(err_msg[:500])}"
                try: await bot.send_message(chat_id=task_info['chat_id'], message_thread_id=task_info['thread_id'], text=final_text, parse_mode='MarkdownV2', reply_to_message_id=task_info.get('reply_to_message_id'))
                except: pass
    finally:
        if not dl_lock_released:
            try: shutil.rmtree(DOWN_DIR, ignore_errors=True)
            except: pass
            state.download_semaphore.release()
            await state.available_slots.put(slot_number)
            
        try: shutil.rmtree(stage_dir, ignore_errors=True)
        except: pass

        if ul_lock_acquired:
            state.upload_semaphore.release()

        async with state.download_tasks_lock:
            if dl_id in state.download_registry: del state.download_registry[dl_id]
        async with state.queue_lock:
            uid = task_info.get('user_id')
            if uid in state.user_requests: state.user_requests[uid] = [r for r in state.user_requests[uid] if r['dl_id'] != dl_id]
            
        state.FORCE_NEW_STATUS = True

async def queue_processor(app, pyro_app: Client):
    while True:
        dl_id = await state.download_queue.get()
        asyncio.create_task(wait_and_process(app.bot, pyro_app, dl_id))