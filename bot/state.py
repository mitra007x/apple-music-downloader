import asyncio
from typing import Dict, List, Tuple, Optional
from telegram import Message
from pyrogram import Client

# --- Globals & Shared State ---
pyrogram_client: Optional[Client] = None
chat_status_messages: Dict[Tuple[int, int], Message] = {}
chat_pages: Dict[Tuple[int, int], int] = {}

status_updater_lock = asyncio.Lock()
download_queue = asyncio.Queue()
queue_lock = asyncio.Lock()
download_tasks_lock = asyncio.Lock()

user_requests: Dict[int, List[Dict[str, str]]] = {}
download_registry: Dict[str, Dict] = {}
pending_upload_selections: Dict[str, dict] = {}

download_semaphore: asyncio.Semaphore = None
upload_semaphore: asyncio.Semaphore = None
available_slots: asyncio.Queue = None

FORCE_NEW_STATUS = False