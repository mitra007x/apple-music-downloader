import asyncio
from typing import Dict, List, Tuple, Optional
from telegram import Message
from pyrogram import Client

# --- Globals & Shared State ---
pyrogram_client: Optional[Client] = None
pyrogram_clients: List[Client] = []
_client_idx: int = 0

def get_worker_client(index: int = None) -> Client:
    global _client_idx, pyrogram_clients, pyrogram_client
    if not pyrogram_clients:
        return pyrogram_client
    if index is not None:
        return pyrogram_clients[index % len(pyrogram_clients)]
    _client_idx = (_client_idx + 1) % len(pyrogram_clients)
    return pyrogram_clients[_client_idx]

async def prime_user_peer(user):
    if not pyrogram_clients: return
    try:
        if hasattr(user, 'username') and user.username:
            username_target = f"@{user.username}"
            for client in pyrogram_clients:
                try: await client.get_users(username_target)
                except: pass
    except Exception:
        pass

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