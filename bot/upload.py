import os
import time
import asyncio
import aiohttp
import ssl
import certifi
import glob
from bot.config import GOFILE_TOKEN, DOWN_DIR
from bot.state import download_registry, download_tasks_lock
from bot.utils import format_bytes


async def upload_to_gofile_curl(file_path: str, dl_id: str, user_cancelled: asyncio.Event) -> str:
    """
    Uploads file to GoFile (Singapore server) using aiohttp for maximum speed.
    (Function name kept as upload_to_gofile_curl for backward compatibility)
    """
    if not os.path.exists(file_path):
        return ""

    total_size = os.path.getsize(file_path)
    upload_progress = {"bytes_sent": 0, "total_size": total_size}
    stop_monitor = asyncio.Event()

    # Start progress monitor
    monitor_task = asyncio.create_task(
        _monitor_upload_progress(upload_progress, stop_monitor, dl_id)
    )

    upload_url = "https://upload.gofile.io/uploadFile"

    try:
        async def file_sender():
            chunk_size = 4 * 1024 * 1024  # 4MB - best for speed
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

        form_data = aiohttp.FormData()
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
            timeout=aiohttp.ClientTimeout(total=1800),   # 30 min timeout
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
    """Internal progress monitor for GoFile upload"""
    last_bytes = 0
    start_time = time.time()
    
    while not stop_event.is_set():
        try:
            current = progress.get("bytes_sent", 0)
            total = progress.get("total_size", 1)

            if current > last_bytes + (128 * 1024):  # Update only on meaningful progress
                elapsed = time.time() - start_time
                speed = current / elapsed if elapsed > 0 else 0
                pct = (current / total) * 100 if total > 0 else 0

                async with download_tasks_lock:
                    if dl_id in download_registry:
                        download_registry[dl_id]['status'] = 'uploading'
                        download_registry[dl_id]['progress_stats'] = (
                            f"GoFile | {pct:.1f}% ({format_bytes(current)} / {format_bytes(total)})"
                        )
                        download_registry[dl_id]['progress_speed'] = f"{format_bytes(speed)}/s"

                last_bytes = current

        except Exception:
            pass

        await asyncio.sleep(1.0)


# ==================== Your other helper functions (unchanged) ====================

async def progress_tracker(current, total, dl_id, task_type, start_time):
    async with download_tasks_lock:
        if dl_id in download_registry:
            if download_registry[dl_id]['user_cancelled'].is_set():
                raise asyncio.CancelledError("Upload cancelled by user.")
            elapsed = time.time() - start_time
            speed = current / elapsed if elapsed > 0 else 0
            pct = (current / total) * 100 if total > 0 else 0
            download_registry[dl_id]['status'] = 'uploading'
            download_registry[dl_id]['progress_stats'] = f"{task_type} | {pct:.1f}% ({format_bytes(current)} / {format_bytes(total)})"
            download_registry[dl_id]['progress_speed'] = f"{format_bytes(speed)}/s"


async def monitor_zip_file(zip_path, total_size, dl_id, done_event, part_num=None):
    start_time = time.time()
    while not done_event.is_set():
        if os.path.exists(zip_path):
            current_size = os.path.getsize(zip_path)
            elapsed = time.time() - start_time
            speed = current_size / elapsed if elapsed > 0 else 0
            pct = (current_size / total_size) * 100 if total_size > 0 else 0
            async with download_tasks_lock:
                if dl_id in download_registry:
                    download_registry[dl_id]['status'] = 'zipping'
                    prt_txt = f" Part {part_num} | " if part_num else ""
                    download_registry[dl_id]['progress_stats'] = f"{prt_txt}{pct:.1f}% ({format_bytes(current_size)})"
                    download_registry[dl_id]['progress_speed'] = f"{format_bytes(speed)}/s"
        await asyncio.sleep(1.5)


async def monitor_down_folder_size(dl_id, folder_done_event):
    while not folder_done_event.is_set():
        try:
            total_size = sum(os.path.getsize(f) for f in glob.glob(os.path.join(DOWN_DIR, '**', '*'), recursive=True) if os.path.isfile(f))
            async with download_tasks_lock:
                if dl_id in download_registry:
                    download_registry[dl_id]['down_folder_size'] = format_bytes(total_size)
        except:
            pass
        await asyncio.sleep(1.5)
