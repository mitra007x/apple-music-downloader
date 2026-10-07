import os
import time
import asyncio
import aiohttp
import ssl
import certifi
import glob
import math
import json
import re
from typing import Optional, Dict, List
from pyrogram import Client, enums
from pyrogram.errors import FloodWait, PeerIdInvalid, UserAlreadyParticipant
from pyrogram.types import InputMediaAudio as PyroInputMediaAudio
from telegram import InputMediaAudio as PTBInputMediaAudio

import bot.state as state
from bot.config import GOFILE_TOKEN, DOWN_DIR, DUMP_CHANNEL_ID
from bot.utils import (
    format_bytes, get_cover_art, get_audio_info, create_tracklist_page,
    get_extended_track_details, generate_tracklist_link, get_video_quality, extract_video_info
)


class DownloadCancelledError(Exception):
    pass


def format_speed(speed_bytes_per_sec: float) -> str:
    return f"{format_bytes(speed_bytes_per_sec)}/s"


def sanitize_cover_art(cover_path: str) -> str:
    return cover_path


async def get_metadata_robust(file_path: str):
    year, album, artist, title = "", "Unknown Album", "Unknown Artist", "Unknown Title"
    
    try:
        ext = file_path.lower().split('.')[-1]
        if ext == 'flac':
            from mutagen.flac import FLAC
            audio = FLAC(file_path)
            title = audio.get('title', [title])[0]
            artist = audio.get('albumartist', audio.get('artist', [artist]))[0]
            album = audio.get('album', [album])[0]
            year = audio.get('date', audio.get('year', [year]))[0]
        elif ext == 'mp3':
            from mutagen.easyid3 import EasyID3
            audio = EasyID3(file_path)
            title = audio.get('title', [title])[0]
            artist = audio.get('albumartist', audio.get('artist', [artist]))[0]
            album = audio.get('album', [album])[0]
            year = audio.get('date', audio.get('year', [year]))[0]
        elif ext == 'm4a':
            from mutagen.easymp4 import EasyMP4
            audio = EasyMP4(file_path)
            title = audio.get('title', [title])[0]
            artist = audio.get('albumartist', audio.get('artist', [artist]))[0]
            album = audio.get('album', [album])[0]
            year = audio.get('date', audio.get('year', [year]))[0]
    except Exception:
        pass

    if "Unknown" in title or "Unknown" in artist or "Unknown" in album:
        try:
            cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", file_path]
            process = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            stdout, _ = await process.communicate()
            data = json.loads(stdout)
            tags = data.get('format', {}).get('tags', {})
            if not tags:
                for stream in data.get('streams', []):
                    if stream.get('codec_type') == 'audio':
                        tags = stream.get('tags', {})
                        break
                        
            def get_tag(keys, default):
                for k in keys:
                    for tag_k, tag_v in tags.items():
                        if tag_k.lower() == k.lower(): return tag_v
                return default

            if "Unknown" in title: title = get_tag(['title', 'name', 'song'], title)
            if "Unknown" in artist: artist = get_tag(['album_artist', 'artist', 'performer', 'author'], artist)
            if "Unknown" in album: album = get_tag(['album', 'album_title'], album)
            if not year: year = get_tag(['date', 'year', 'originaldate', 'creation_time', 'tyer'], year)
        except Exception:
            pass

    def clean_str(s):
        if not s: return ""
        s = str(s)
        s = s.replace('\\n', ' ').replace('\n', ' ').replace('\\r', ' ').replace('\r', ' ')
        s = re.sub(r'[\r\n\t]+', ' ', s)
        return ' '.join(s.split())

    return clean_str(year), clean_str(album), clean_str(artist), clean_str(title)


async def get_duration_robust(file_path: str) -> int:
    try:
        cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", file_path]
        process = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, _ = await process.communicate()
        data = json.loads(stdout)
        duration = data.get('format', {}).get('duration')
        if not duration:
            for stream in data.get('streams', []):
                if stream.get('codec_type') == 'audio':
                    duration = stream.get('duration')
                    break
        return int(float(duration)) if duration else 0
    except Exception:
        return 0


async def upload_to_gofile_curl(file_path: str, dl_id: str, user_cancelled: asyncio.Event) -> str:
    if not os.path.exists(file_path):
        return ""

    total_size = os.path.getsize(file_path)
    upload_progress = {"bytes_sent": 0, "total_size": total_size}
    stop_monitor = asyncio.Event()

    monitor_task = asyncio.create_task(
        _monitor_upload_progress(upload_progress, stop_monitor, dl_id)
    )

    upload_url = "https://upload.gofile.io/uploadFile"

    try:
        async def file_sender():
            chunk_size = 4 * 1024 * 1024  
            with open(file_path, 'rb') as f:
                while True:
                    if user_cancelled.is_set():
                        raise asyncio.CancelledError("Upload cancelled by user")
                    
                    chunk = f.read(chunk_size)
                    if not chunk:
                        break
                    upload_progress["bytes_sent"] += len(chunk)
                    yield chunk

        ssl_context = ssl.create_default_context(cafile=certifi.where())
        form_data = aiohttp.FormData(quote_fields=False)
        headers = {}

        if GOFILE_TOKEN:
            form_data.add_field('token', GOFILE_TOKEN)
            headers['Authorization'] = f'Bearer {GOFILE_TOKEN}'

        form_data.add_field(
            'file',
            file_sender(),
            filename=os.path.basename(file_path),
            content_type='application/zip'
        )

        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=1800),
            connector=aiohttp.TCPConnector(ssl=ssl_context)
        ) as session:
            
            async with session.post(upload_url, data=form_data, headers=headers) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    print(f"GoFile upload failed [{resp.status}]: {text[:300]}")
                    return ""

                json_response = await resp.json()

                if json_response.get('status') == 'ok':
                    download_page = json_response['data'].get('downloadPage')
                    print(f"✅ GoFile upload successful: {download_page}")
                    return download_page
                else:
                    print(f"GoFile API error: {json_response}")
                    return ""

    except asyncio.CancelledError:
        print(f"Upload {dl_id} was cancelled")
        return ""
    except Exception as e:
        print(f"GoFile Upload Error: {e}")
        return ""
    finally:
        if not stop_monitor.is_set():
            stop_monitor.set()
        try:
            await monitor_task
        except asyncio.CancelledError:
            pass


async def _monitor_upload_progress(progress: dict, stop_event: asyncio.Event, dl_id: str):
    last_bytes = 0
    start_time = time.time()
    
    while not stop_event.is_set():
        try:
            current = progress.get("bytes_sent", 0)
            total = progress.get("total_size", 1)

            if current > last_bytes + (128 * 1024):
                elapsed = time.time() - start_time
                speed = current / elapsed if elapsed > 0 else 0
                pct = (current / total) * 100 if total > 0 else 0

                async with state.download_tasks_lock:
                    if dl_id in state.download_registry:
                        state.download_registry[dl_id]['status'] = 'uploading'
                        state.download_registry[dl_id]['progress_stats'] = (
                            f"GoFile | {pct:.1f}% ({format_bytes(current)} / {format_bytes(total)})"
                        )
                        state.download_registry[dl_id]['progress_speed'] = f"{format_bytes(speed)}/s"

                last_bytes = current

        except Exception:
            pass

        await asyncio.sleep(1.0)


async def progress_tracker(current, total, dl_id, task_type, start_time):
    async with state.download_tasks_lock:
        if dl_id in state.download_registry:
            if state.download_registry[dl_id]['user_cancelled'].is_set():
                raise asyncio.CancelledError("Upload cancelled by user.")
            elapsed = time.time() - start_time
            speed = current / elapsed if elapsed > 0 else 0
            pct = (current / total) * 100 if total > 0 else 0
            state.download_registry[dl_id]['status'] = 'uploading'
            state.download_registry[dl_id]['progress_stats'] = f"{task_type} | {pct:.1f}% ({format_bytes(current)} / {format_bytes(total)})"
            state.download_registry[dl_id]['progress_speed'] = f"{format_bytes(speed)}/s"


async def monitor_zip_file(zip_path, total_size, dl_id, done_event, part_num=None):
    start_time = time.time()
    while not done_event.is_set():
        if os.path.exists(zip_path):
            current_size = os.path.getsize(zip_path)
            elapsed = time.time() - start_time
            speed = current_size / elapsed if elapsed > 0 else 0
            pct = (current_size / total_size) * 100 if total_size > 0 else 0
            async with state.download_tasks_lock:
                if dl_id in state.download_registry:
                    state.download_registry[dl_id]['status'] = 'zipping'
                    prt_txt = f" Part {part_num} | " if part_num else ""
                    state.download_registry[dl_id]['progress_stats'] = f"{prt_txt}{pct:.1f}% ({format_bytes(current_size)})"
                    state.download_registry[dl_id]['progress_speed'] = f"{format_bytes(speed)}/s"
        await asyncio.sleep(1.5)


async def monitor_down_folder_size(dl_id, folder_done_event):
    while not folder_done_event.is_set():
        try:
            total_size = sum(os.path.getsize(f) for f in glob.glob(os.path.join(DOWN_DIR, '**', '*'), recursive=True) if os.path.isfile(f))
            async with state.download_tasks_lock:
                if dl_id in state.download_registry:
                    state.download_registry[dl_id]['down_folder_size'] = format_bytes(total_size)
        except Exception:
            pass
        await asyncio.sleep(1.5)


def _get_local_quality(file_list):
    qualities = set()
    for f in file_list:
        try:
            ext = os.path.splitext(f)[1].lower()
            if ext in [".flac", ".wav", ".aiff", ".alac"]:
                qualities.add(f"Lossless {ext.replace('.', '').upper()}")
            else:
                c_disp = "AAC" if ext == ".m4a" else ("MP3" if ext == ".mp3" else ext.replace(".", "").upper())
                qualities.add(f"256kbps {c_disp}")
        except Exception:
            pass
    return " | ".join(sorted(list(qualities), reverse=True)) if qualities else "256kbps AAC"


async def upload_unzipped_to_telegram(
    ptb_bot, pyrogram_app: Client, chat_id: int, thread_id: int, reply_to_message_id: int,
    caption: str, pyro_caption: str, cover_path: Optional[str], audio_files: List[str],
    dl_id: str, num_audio_files: int, cancel_event: asyncio.Event,
    download_tasks_lock, download_registry: Dict, TELEGRAM_UPLOAD_SPEED_LIMIT_MBPS: float,
    dump_channel_id: str = DUMP_CHANNEL_ID,
    url: str = "",
    download_type: str = "album"
):
    try:
        async with download_tasks_lock:
            if dl_id in download_registry:
                download_registry[dl_id]['status'] = 'uploading'
        
        worker_clients = state.pyrogram_clients if state.pyrogram_clients else [pyrogram_app]
        main_client = state.pyrogram_client if state.pyrogram_client else pyrogram_app

        is_single_item = (download_type == 'single') or (download_type == 'video' and num_audio_files == 1)

        # 1. Send Cover Photo / Header Caption to main chat (ONLY for non-single downloads)
        sent_header = None
        if not is_single_item:
            if cover_path and os.path.exists(cover_path):
                if ptb_bot:
                    try:
                        with open(cover_path, 'rb') as pf:
                            sent_header = await ptb_bot.send_photo(
                                chat_id=chat_id, photo=pf, caption=caption,
                                parse_mode='MarkdownV2', reply_to_message_id=reply_to_message_id
                            )
                    except Exception as pe:
                        print(f"PTB send_photo error: {pe}")

                if not sent_header:
                    try:
                        sent_header = await main_client.send_photo(
                            chat_id=chat_id, photo=cover_path, caption=pyro_caption,
                            parse_mode=enums.ParseMode.MARKDOWN, reply_to_message_id=reply_to_message_id
                        )
                    except Exception as pe:
                        print(f"Pyrogram send_photo error: {pe}")

                if dump_channel_id and sent_header:
                    h_mid = sent_header.message_id if hasattr(sent_header, 'message_id') else getattr(sent_header, 'id', None)
                    if h_mid:
                        try: await ptb_bot.copy_message(chat_id=dump_channel_id, from_chat_id=chat_id, message_id=h_mid)
                        except Exception: pass
            else:
                if ptb_bot:
                    try:
                        sent_header = await ptb_bot.send_message(
                            chat_id=chat_id, text=caption, parse_mode='MarkdownV2',
                            reply_to_message_id=reply_to_message_id, disable_web_page_preview=True
                        )
                    except Exception as pe:
                        print(f"PTB send_message error: {pe}")

                if not sent_header:
                    try:
                        sent_header = await main_client.send_message(
                            chat_id=chat_id, text=pyro_caption, parse_mode=enums.ParseMode.MARKDOWN,
                            reply_to_message_id=reply_to_message_id, disable_web_page_preview=True
                        )
                    except Exception as pe:
                        print(f"Pyrogram send_message error: {pe}")

                if dump_channel_id and sent_header:
                    h_mid = sent_header.message_id if hasattr(sent_header, 'message_id') else getattr(sent_header, 'id', None)
                    if h_mid:
                        try: await ptb_bot.copy_message(chat_id=dump_channel_id, from_chat_id=chat_id, message_id=h_mid)
                        except Exception: pass

        # 2. Upload tracks in groups of 10
        group_size = 10
        total_tracks = len(audio_files)
        total_groups = math.ceil(total_tracks / group_size)
        groups = [audio_files[i:i + group_size] for i in range(0, total_tracks, group_size)]

        target_dump_or_chat = dump_channel_id if dump_channel_id else chat_id

        for group_idx, chunk_files in enumerate(groups, 1):
            if cancel_event.is_set():
                raise DownloadCancelledError(f"Upload `{dl_id}` cancelled.")

            async with download_tasks_lock:
                if dl_id in download_registry:
                    download_registry[dl_id]['progress_stats'] = f"Uploading group {group_idx}/{total_groups}"

            # Parallel upload the 10 tracks of this group to dump channel (or chat)
            async def upload_single_track(idx_in_group: int, file_path: str):
                worker_client = state.get_worker_client((group_idx - 1) * group_size + idx_in_group)
                ext = os.path.splitext(file_path)[1].lower()
                is_video_file = ext in ['.mp4', '.mkv', '.webm', '.mov', '.avi']

                if is_video_file:
                    vid_thumb, vid_duration, vid_w, vid_h = await extract_video_info(file_path)
                    year, album, artist, title = await get_metadata_robust(file_path)
                    
                    try:
                        from mutagen.mp4 import MP4
                        v_tags = MP4(file_path)
                        v_artist = v_tags.get('©ART', [None])[0] or v_tags.get('artist', [None])[0] or v_tags.get('\xa9ART', [None])[0]
                        if v_artist: artist = str(v_artist)
                    except: pass

                    if not title or title == "Unknown Title":
                        title = os.path.basename(file_path).rsplit('.', 1)[0]
                    
                    v_quality = get_video_quality(file_path)
                    vid_year = f" [{year}]" if year and year != 'Unknown' else ""
                    plat_url = url if url else 'https://music.apple.com'
                    vid_cap = pyro_caption if is_single_item else (
                        f"**Video:** __{title}{vid_year} by__ **__{artist}__**\n"
                        f"**Quality:** __{v_quality}__\n"
                        f"**File Size:** __{format_bytes(os.path.getsize(file_path))}__\n"
                        f"**Platform:** __[Apple Music]({plat_url})__"
                    )

                    t_path = vid_thumb if (vid_thumb and os.path.exists(vid_thumb)) else (cover_path if (cover_path and os.path.exists(cover_path)) else None)

                    for attempt in range(5):
                        try:
                            sent = await worker_client.send_video(
                                chat_id=target_dump_or_chat,
                                video=file_path,
                                caption=vid_cap,
                                parse_mode=enums.ParseMode.MARKDOWN,
                                duration=int(vid_duration),
                                width=vid_w,
                                height=vid_h,
                                thumb=t_path,
                                supports_streaming=True,
                                reply_to_message_id=reply_to_message_id if not dump_channel_id else None
                            )
                            return idx_in_group, sent, True
                        except FloodWait as e:
                            await asyncio.sleep(e.value + 1)
                        except Exception as e:
                            print(f"Video {file_path} upload attempt {attempt} error: {e}")
                            await asyncio.sleep(2)
                    return idx_in_group, None, True
                else:
                    title, performer, duration = get_audio_info(file_path)
                    if not duration or duration == 0:
                        duration = await get_duration_robust(file_path)

                    track_caption = pyro_caption if download_type == 'single' else None

                    for attempt in range(5):
                        try:
                            sent = await worker_client.send_audio(
                                chat_id=target_dump_or_chat,
                                audio=file_path,
                                caption=track_caption,
                                parse_mode=enums.ParseMode.MARKDOWN if track_caption else None,
                                title=title or os.path.basename(file_path),
                                performer=performer,
                                duration=int(duration),
                                thumb=cover_path if cover_path and os.path.exists(cover_path) else None,
                                reply_to_message_id=reply_to_message_id if not dump_channel_id else None
                            )
                            return idx_in_group, sent, False
                        except FloodWait as e:
                            await asyncio.sleep(e.value + 1)
                        except Exception as e:
                            print(f"Track {file_path} upload attempt {attempt} error: {e}")
                            await asyncio.sleep(2)
                    return idx_in_group, None, False

            tasks = [upload_single_track(i, f) for i, f in enumerate(chunk_files)]
            group_results = await asyncio.gather(*tasks)
            group_results.sort(key=lambda x: x[0])

            is_video_group = any(item[2] for item in group_results if len(item) > 2)

            if dump_channel_id:
                if is_video_group or is_single_item:
                    for _, sent, _ in group_results:
                        if sent is not None:
                            try:
                                await ptb_bot.copy_message(
                                    chat_id=chat_id,
                                    from_chat_id=dump_channel_id,
                                    message_id=sent.id,
                                    reply_to_message_id=reply_to_message_id
                                )
                            except Exception as cp_err:
                                print(f"Copy message error for msg {getattr(sent, 'id', None)}: {cp_err}")
                else:
                    file_ids_in_order = []
                    msg_ids_in_order = []
                    for _, sent, _ in group_results:
                        if sent is not None:
                            msg_ids_in_order.append(sent.id)
                            if hasattr(sent, 'audio') and sent.audio:
                                file_ids_in_order.append(sent.audio.file_id)
                            elif hasattr(sent, 'document') and sent.document:
                                file_ids_in_order.append(sent.document.file_id)

                    if file_ids_in_order:
                        sent_group_ok = False
                        for attempt in range(5):
                            try:
                                ptb_media_group = [PTBInputMediaAudio(media=fid) for fid in file_ids_in_order]
                                await ptb_bot.send_media_group(
                                    chat_id=chat_id,
                                    media=ptb_media_group,
                                    reply_to_message_id=reply_to_message_id
                                )
                                sent_group_ok = True
                                break
                            except Exception as mg_err:
                                err_txt = str(mg_err).lower()
                                print(f"ptb_bot.send_media_group attempt {attempt+1} error: {mg_err}")
                                if "retry after" in err_txt or "flood" in err_txt:
                                    m_sec = re.search(r'retry in (\d+)', err_txt)
                                    sec = int(m_sec.group(1)) + 1 if m_sec else 5
                                    await asyncio.sleep(sec)
                                else:
                                    await asyncio.sleep(2)

                        if not sent_group_ok:
                            try:
                                pyro_media = [PyroInputMediaAudio(media=fid) for fid in file_ids_in_order]
                                await main_client.send_media_group(
                                    chat_id=chat_id,
                                    media=pyro_media,
                                    reply_to_message_id=reply_to_message_id
                                )
                                sent_group_ok = True
                            except Exception as p_err:
                                print(f"Pyrogram send_media_group retry error: {p_err}")

                        if not sent_group_ok:
                            print("send_media_group failed after retries, falling back to message copy...")
                            for mid in msg_ids_in_order:
                                try:
                                    await ptb_bot.copy_message(chat_id=chat_id, from_chat_id=dump_channel_id, message_id=mid, reply_to_message_id=reply_to_message_id)
                                except Exception as cp_err:
                                    print(f"Copy fallback error for msg {mid}: {cp_err}")

        return True

    except Exception as e:
        print(f"Upload unzipped exception: {e}")
        return False
