import os
import json
from telegram import Update
from bot.config import APPROVED_GROUPS_FILE, APPROVED_TOPICS_FILE, APPROVED_USERS_FILE

def load_approved_groups() -> list:
    if os.path.exists(APPROVED_GROUPS_FILE):
        try:
            with open(APPROVED_GROUPS_FILE, "r") as f: return json.load(f)
        except Exception: pass
    return []

def save_approved_groups(groups: list):
    with open(APPROVED_GROUPS_FILE, "w") as f: json.dump(groups, f)

def load_approved_topics() -> dict:
    if os.path.exists(APPROVED_TOPICS_FILE):
        try:
            with open(APPROVED_TOPICS_FILE, "r") as f: return json.load(f)
        except Exception: pass
    return {}

def save_approved_topics(topics: dict):
    with open(APPROVED_TOPICS_FILE, "w") as f: json.dump(topics, f)

def load_approved_users() -> list:
    if os.path.exists(APPROVED_USERS_FILE):
        try:
            with open(APPROVED_USERS_FILE, "r") as f: return json.load(f)
        except Exception: pass
    return []

def save_approved_users(users: list):
    with open(APPROVED_USERS_FILE, "w") as f: json.dump(users, f)

def is_chat_approved(update: Update, admin_id: int) -> bool:
    user_id = update.effective_user.id
    if user_id == admin_id: return True
    if user_id in load_approved_users(): return True
    
    chat_id = update.effective_chat.id
    thread_id = update.effective_message.message_thread_id if update.effective_message.is_topic_message else None
    
    if chat_id > 0: return False
    
    if chat_id in load_approved_groups(): return True
    approved_topics = load_approved_topics()
    if str(chat_id) in approved_topics and thread_id in approved_topics[str(chat_id)]: return True
    return False