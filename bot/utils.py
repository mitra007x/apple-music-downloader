import os
import re
import json
import glob
import asyncio
import subprocess
from typing import List, Tuple, Optional

import mutagen
from mutagen.flac import FLAC
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4
from mutagen import File

from telegram import Message
from bot.config import TELEGRAPH_TOKEN_FILE

try:
    from html_telegraph_poster import TelegraphPoster
except ImportError:
    TelegraphPoster = None
    print("⚠️ WARNING: 'html_telegraph_poster' or 'lxml_html_clean' is missing/broken.")
    print("Tracklist URL generation is temporarily disabled. To fix, run: pip install lxml_html_clean")

def escape_markdown_v2(text: str) -> str:
    if not text: return ""
    escape_chars = r"_*[]()~`>#+-=|{}.!"
    return re.sub(f"([{re.escape(escape_chars)}])", r"\\\1", str(text))

def format_bytes(size: float) -> str:
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0: return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} PB"

def sanitize_filename(name):
    name = str(name)
    name = re.sub(r'[<>:"/\\|?*]', '_', name)
    name = name.strip().strip('.')
    return re.sub(r'\s+', ' ', name) if name else "Unknown"

def format_track_list_grammar(numbers: List[int]) -> Tuple[str, str]:
    if not numbers: return "", ""
    unique_nums = sorted(list(set(numbers)))
    if len(unique_nums) == 1: return str(unique_nums[0]), "is"
    str_nums = [str(n) for n in unique_nums]
    return ", ".join(str_nums[:-1]) + " & " + str_nums[-1], "are"

async def delete_message_after(message: Message, seconds: int):
    await asyncio.sleep(seconds)
    try: await message.delete()
    except Exception: pass

def replace_prefix(path, old_prefix, new_prefix):
    return os.path.join(new_prefix, os.path.relpath(path, old_prefix))

# --- Telegraph Logic ---
def get_or_create_telegraph_account():
    if TelegraphPoster is None: return None
    if os.path.exists(TELEGRAPH_TOKEN_FILE):
        try:
            with open(TELEGRAPH_TOKEN_FILE, 'r') as f:
                data = json.load(f)
                return TelegraphPoster(access_token=data['access_token'])
        except: pass
    t = TelegraphPoster(use_api=True)
    try:
        auth_info = t.create_api_token('AppleMusicBot', 'MusicBot', 'https://t.me/MusicBot')
        with open(TELEGRAPH_TOKEN_FILE, 'w') as f: json.dump(auth_info, f)
        return t
    except Exception as e:
        print(f"Telegraph Init Error: {e}")
        return None

def create_tracklist_page(album_title, tracklist_html):
    try:
        t = get_or_create_telegraph_account()
        if not t: return None
        page = t.post(title=f"Tracklist: {album_title}"[:100], author="LosslessDL", text=tracklist_html)
        return page['url']
    except Exception as e:
        print(f"Telegraph Post Error: {e}")
        return None

def get_extended_track_details(file_path):
    try:
        size_bytes = os.path.getsize(file_path)
        size_mb = size_bytes / (1024 * 1024)
        size_str = f"{size_mb:.1f}MB" if size_mb >= 1.0 else f"{int(size_bytes / 1024)}KB"

        cmd = ["mediainfo", "--Output=JSON", file_path]
        result = subprocess.run(cmd, capture_output=True, text=True)
        data = json.loads(result.stdout)
        
        tracks = data.get('media', {}).get('track', [])
        general_track = next((t for t in tracks if t.get('@type') == 'General'), {})
        audio_track = next((t for t in tracks if t.get('@type') == 'Audio'), {})
        text_track = next((t for t in tracks if t.get('@type') == 'Text'), None)

        has_lyrics = bool(text_track)
        if not has_lyrics:
            extra = general_track.get('extra', {})
            if any(k.lower() in ['lyrics', 'unsyncedlyrics', 'sylt', 'uslt'] for k in extra.keys()):
                has_lyrics = True
            elif 'Lyrics' in general_track or 'LYRICS' in general_track:
                has_lyrics = True

        format_name = audio_track.get('Format', 'Unknown').upper()
        codec_str = format_name
        if 'ALAC' in format_name: codec_str = 'ALAC'
        elif 'AC-3' in format_name or 'E-AC-3' in format_name or 'AC-4' in format_name: codec_str = 'ATMOS'
        elif 'MPEG AUDIO' in format_name: codec_str = 'MP3'
        elif 'PCM' in format_name or 'WAVE' in format_name: codec_str = 'WAV'
        elif 'AAC' in format_name: codec_str = 'AAC'

        sr = audio_track.get('SamplingRate')
        sr_str = f"{float(sr)/1000:g}kHz" if sr else ""
        bd = audio_track.get('BitDepth')
        if not bd and codec_str in ['FLAC', 'ALAC', 'WAV']: bd = 16 
        bd_str = f"{bd}bit" if bd else ""

        duration = audio_track.get('Duration') or general_track.get('Duration')
        dur_str, dur_sec = "0m:00s", 0.0
        if duration:
            try:
                dur_sec = float(duration)
                if dur_sec > 5000: dur_sec /= 1000 
                m, s = divmod(int(dur_sec), 60)
                dur_str = f"{m}m:{s:02d}s"
            except: pass

        bitrate = audio_track.get('BitRate')
        kbps_str = "?kbps"
        if bitrate:
            kbps_str = f"{int(float(bitrate) / 1000)}kbps"
        else:
            stream_size = audio_track.get('StreamSize')
            if stream_size and dur_sec > 0:
                try: kbps_str = f"{int((float(stream_size) * 8) / dur_sec / 1000)}kbps"
                except: pass

        parts = []
        if bd_str: parts.append(bd_str)
        if sr_str: parts.append(sr_str)
        if codec_str and codec_str != "UNKNOWN": parts.append(codec_str)
        if kbps_str != "?kbps": parts.append(kbps_str)
        parts.append(dur_str)
        parts.append(size_str)
        
        return " | ".join(parts), has_lyrics
    except Exception:
        return "Unknown Specs", False

def generate_tracklist_link(folder_path, album_title, max_tracks):
    files, detected_year = [], None
    for root, _, filenames in os.walk(folder_path):
        for f in filenames:
            if os.path.splitext(f)[1].lower() in ['.flac', '.mp3', '.m4a', '.wav', '.ogg', '.opus']:
                path = os.path.join(root, f)
                try:
                    audio = mutagen.File(path)
                    if not audio: continue
                    track_num, title, artist, year = 0, f, "Unknown", None
                    if isinstance(audio, FLAC):
                        tn = audio.get('tracknumber', [0])[0]
                        track_num = int(str(tn).split('/')[0]) if tn else 0
                        title, artist, year = audio.get('title', [f])[0], audio.get('artist', ['Unknown'])[0], audio.get('date', [''])[0]
                    elif isinstance(audio, MP3):
                        tags = getattr(audio, 'tags', {})
                        if tags:
                            trck = tags.get('TRCK')
                            if trck: track_num = int(str(trck).split('/')[0])
                            title, artist, year = str(tags.get('TIT2', f)), str(tags.get('TPE1', 'Unknown')), str(tags.get('TDRC', tags.get('TYER', '')))
                    elif isinstance(audio, MP4):
                        trkn = audio.get('trkn')
                        if trkn: track_num = int(trkn[0][0])
                        title, artist, year = audio.get('©nam', [f])[0], audio.get('©ART', ['Unknown'])[0], audio.get('©day', [''])[0]
                    
                    if track_num == 0:
                        try:
                            possible_num = re.match(r'^(\d+)', f)
                            if possible_num: track_num = int(possible_num.group(1))
                        except: pass

                    if not detected_year and year: detected_year = str(year)[:4]
                    details, has_lyrics = get_extended_track_details(path)
                    files.append({'num': track_num, 'title': title, 'artist': artist, 'details': details, 'lyrics': has_lyrics})
                except: pass

    if not files: return None
    files.sort(key=lambda x: x['num'])
    max_t = files[-1]['num'] if files else 0
    if max_t == 0: 
        max_t = len(files)
        for i, f in enumerate(files): f['num'] = i + 1
    if max_tracks and max_tracks > max_t: max_t = max_tracks

    display_title = album_title
    if detected_year and str(detected_year) not in album_title: display_title = f"{album_title} [{detected_year}]"

    final_list = []
    file_map = {f['num']: f for f in files}
    for i in range(1, max_t + 1):
        if i in file_map:
            t = file_map[i]
            lyrics_emoji = "🅻 | " if t.get('lyrics') else ""
            final_list.append(f"<b>{i}. {t['title']}</b> - {t['artist']}<br><blockquote><i>{lyrics_emoji}{t['details']}</i></blockquote>")
        else:
            final_list.append(f"<b>{i}.</b> Missing ❌")

    html_content = f"<h4>Tracklist: {display_title}</h4><hr><br><br>" + "<br><br>".join(final_list)
    return create_tracklist_page(display_title, html_content)

# --- Media Info Fetchers ---
def get_audio_info(file_path: str):
    title, performer, duration = None, None, 0
    try:
        audio = File(file_path)
        if audio:
            duration = int(audio.info.length) if hasattr(audio.info, 'length') else 0
            file_ext = file_path.lower().rsplit('.', 1)[-1]
            if file_ext in ['m4a', 'mp4']:
                tags = MP4(file_path)
                title = tags.get('\xa9nam', [None])[0]
                performer = tags.get('\xa9ART', [None])[0] or tags.get('aART', [None])[0]
    except Exception: pass
    if not title: title = os.path.basename(file_path).rsplit('.', 1)[0]
    if not performer: performer = "Unknown Artist"
    return str(title), str(performer), duration

def get_cover_art(folder_path: str):
    for ext in ['*.jpg', '*.png', '*.jpeg']:
        covers = glob.glob(os.path.join(folder_path, '**', ext), recursive=True)
        if covers: return covers[0]
    return None

def extract_base_meta(audio_files: list):
    track_name, album_name, album_year, artist, album_artist = None, "Unknown Album", "Unknown", "Unknown Artist", "Unknown Artist"
    if audio_files:
        try:
            tags = MP4(audio_files[0])
            album_name = tags.get('\xa9alb', [album_name])[0]
            track_name = tags.get('\xa9nam', [None])[0] if len(audio_files) == 1 else None
            artist = tags.get('\xa9ART', [tags.get('aART', [artist])[0]])[0]
            album_artist = tags.get('aART', [artist])[0]
            year_raw = tags.get('\xa9day', ['Unknown'])[0]
            if str(year_raw) != 'Unknown':
                ym = re.search(r'\d{4}', str(year_raw))
                if ym: album_year = ym.group(0)
        except Exception:
            track_name = os.path.basename(audio_files[0]).rsplit('.', 1)[0] if len(audio_files) == 1 else None
    return {'track': track_name, 'album': album_name, 'year': album_year, 'artist': artist, 'album_artist': album_artist}

def get_video_quality(file_path: str) -> str:
    try:
        cmd = ["mediainfo", "--Output=JSON", file_path]
        res = subprocess.run(cmd, capture_output=True, text=True)
        data = json.loads(res.stdout)
        
        tracks = data.get('media', {}).get('track', [])
        v_track = next((t for t in tracks if t.get('@type') == 'Video'), {})
        a_track = next((t for t in tracks if t.get('@type') == 'Audio'), {})
        
        height = v_track.get('Height', '')
        res_str = f"{height}p" if height else "1080p"
        
        acodec = a_track.get('Format', 'AAC')
        channels = a_track.get('Channels', '2')
        if channels == '6': channels = '5.1'
        elif channels == '2': channels = '2.0'
        
        bitrate = a_track.get('BitRate') or a_track.get('Maximum_BitRate')
        kbps_str = f"{int(float(bitrate)/1000)}kbps" if bitrate else "256kbps"
        
        return f"{res_str} - {acodec} {channels} ({kbps_str})"
    except Exception:
        return "1080p - AAC 2.0 (256kbps)"

async def extract_video_info(video_path: str) -> Tuple[Optional[str], int, int, int]:
    thumb_path = video_path.rsplit('.', 1)[0] + "_thumb.jpg"
    duration, w, h = 0, 0, 0
    try:
        cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", video_path]
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE)
        stdout, _ = await proc.communicate()
        duration = int(float(stdout.decode().strip()))
    except: pass
    
    try:
        cmd = ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", video_path]
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE)
        stdout, _ = await proc.communicate()
        dims = stdout.decode().strip().split('x')
        if len(dims) == 2:
            w, h = int(dims[0]), int(dims[1])
    except: pass
    
    try:
        cmd = ["ffmpeg", "-y", "-i", video_path, "-ss", "00:00:01", "-vframes", "1", thumb_path]
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        await proc.wait()
        if not os.path.exists(thumb_path): thumb_path = None
    except: thumb_path = None
    
    return thumb_path, duration, w, h

def generate_final_caption(
    url: str,
    total_folder_size: int,
    detected_qualities: set,
    download_type: str,
    first_meta: dict,
    num_files: int,
    progress_data: dict,
    quality_mismatch_tracks: list,
    download_path: str,
    is_atmos_request: bool = False,
    video_quality_str: str = ""
) -> Tuple[str, str, str, str]:
    
    ptb_content_parts, pyro_content_parts = [], []

    if download_type == 'playlist':
        s_entity_name = sanitize_filename(first_meta.get('playlist_name', 'Playlist'))
        ptb_content_parts.append(f"*Playlist:* _{escape_markdown_v2(s_entity_name)}_")
        pyro_content_parts.append(f"**Playlist:** __{s_entity_name}__")
    
    elif download_type == 'video':
        vid_year = f" [{first_meta['year']}]" if first_meta.get('year') and first_meta['year'] != 'Unknown' else ""
        vid_base = f"{first_meta['track'] or 'Video'}{vid_year} by"
        ptb_content_parts.append(f"*Video:* _{escape_markdown_v2(vid_base)}_ _*{escape_markdown_v2(first_meta['artist'])}*_")
        pyro_content_parts.append(f"**Video:** __{vid_base}__ **__{first_meta['artist']}__**")
    
    elif download_type == 'single':
        alb_year = f" [{first_meta['year']}]" if first_meta.get('year') and first_meta['year'] != 'Unknown' else ""
        album_base = f"{first_meta['album']}{alb_year} by"
        ptb_content_parts.extend([
            f"*Album:* _{escape_markdown_v2(album_base)}_ _*{escape_markdown_v2(first_meta['album_artist'])}*_", 
            f"*Track:* _{escape_markdown_v2(first_meta['track'])}_"
        ])
        pyro_content_parts.extend([
            f"**Album:** __{album_base}__ **__{first_meta['album_artist']}__**", 
            f"**Track:** __{first_meta['track']}__"
        ])
    
    else: # Album
        alb_year = f" [{first_meta['year']}]" if first_meta.get('year') and first_meta['year'] != 'Unknown' else ""
        album_base = f"{first_meta['album']}{alb_year} by"
        ptb_content_parts.append(f"*Album:* _{escape_markdown_v2(album_base)}_ _*{escape_markdown_v2(first_meta['album_artist'])}*_")
        pyro_content_parts.append(f"**Album:** __{album_base}__ **__{first_meta['album_artist']}__**")

    ptb_platform_display = f"[{escape_markdown_v2('Apple Music')}]({escape_markdown_v2(url)})"
    pyro_platform_display = f"[Apple Music]({url})"
    
    if download_type == 'video' and video_quality_str:
        final_quality_display_str = video_quality_str
    elif is_atmos_request:
        final_quality_display_str = "Dolby Atmos"
    else:
        final_quality_display_str = " | ".join(sorted(list(detected_qualities), reverse=True))
        if not final_quality_display_str: final_quality_display_str = "256kbps AAC"
    
    display_tracks_count = progress_data.get('total_tracks', num_files) if progress_data.get('total_tracks', 0) > 0 else num_files
    
    tracklist_url = None
    if download_type not in ['video', 'single'] and (num_files > 1 or download_type == 'playlist'):
        header_title = first_meta['album'] if download_type != 'playlist' else s_entity_name
        if first_meta['album_artist'] and first_meta['album_artist'] != 'Unknown Artist' and download_type != 'playlist': 
            header_title = f"{first_meta['album_artist']} - {header_title}"
        tracklist_url = generate_tracklist_link(download_path, header_title, display_tracks_count)

    if tracklist_url:
        tracks_str_ptb = f"_{display_tracks_count}_ _[{escape_markdown_v2('[Tracklist]')}]({escape_markdown_v2(tracklist_url)})_"
        tracks_str_pyro = f"__{display_tracks_count}__ __[[Tracklist]]({tracklist_url})__"
    else:
        tracks_str_ptb = f"_{display_tracks_count}_"
        tracks_str_pyro = f"__{display_tracks_count}__"

    ptb_final_list, pyro_final_list = list(ptb_content_parts), list(pyro_content_parts)
    ptb_final_list.append(f"*Quality:* _{escape_markdown_v2(final_quality_display_str)}_")
    pyro_final_list.append(f"**Quality:** __{final_quality_display_str}__")

    if download_type not in ['single', 'video']:
        ptb_final_list.append(f"*Total Tracks:* {tracks_str_ptb}")
        pyro_final_list.append(f"**Total Tracks:** {tracks_str_pyro}")

    ptb_final_list.append(f"*File Size:* _{escape_markdown_v2(format_bytes(total_folder_size))}_")
    pyro_final_list.append(f"**File Size:** __{format_bytes(total_folder_size)}__")
    ptb_final_list.append(f"*Platform:* _{ptb_platform_display}_")
    pyro_final_list.append(f"**Platform:** __{pyro_platform_display}__")

    notes = []
    
    failed_atmos = sorted(list(set(progress_data.get("failed_atmos_tracks", []))))
    if failed_atmos:
        nums_str, verb = format_track_list_grammar(failed_atmos)
        is_are_not = "isn't" if verb == "is" else "aren't"
        notes.append(f"Track no. {nums_str} {is_are_not} available in Dolby Atmos quality.")

    missing_list = sorted(list(set(progress_data.get("failed_tracks", []))))
    if missing_list:
        nums_str, verb = format_track_list_grammar(missing_list)
        notes.append(f"Track no. {nums_str} {verb} Non Streamable / Failed")
    
    quality_mismatch_list = sorted(list(set(quality_mismatch_tracks)))
    if quality_mismatch_list:
        nums_str, verb = format_track_list_grammar(quality_mismatch_list)
        notes.append(f"Track no. {nums_str} {verb} available only in 256kbps AAC")
        
    stalled_err = progress_data.get("stalled_error")
    if stalled_err:
        notes.append(f"Downloader crashed partially: {stalled_err}")

    formatted_note_pyro, formatted_note_ptb = "", ""
    if notes:
        formatted_note_pyro = f"\n\n**Note:**\n" + "\n".join([f"• __{line}__" for line in notes])
        safe_lines = [f"• _{escape_markdown_v2(line)}_" for line in notes]
        formatted_note_ptb = f"\n\n*Note:*\n" + "\n".join(safe_lines)

    return "\n".join(ptb_final_list), "\n".join(pyro_final_list), formatted_note_ptb, formatted_note_pyro