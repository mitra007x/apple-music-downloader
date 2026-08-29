import os
import sys
import asyncio
import secrets
import requests
from telegram import Update, InlineKeyboardMarkup as PTBInlineKeyboardMarkup, InlineKeyboardButton as PTBInlineKeyboardButton
from telegram.ext import ContextTypes

# Import Pyrogram ButtonStyle to extract the exact color codes your custom API needs!
from pyrogram.enums import ButtonStyle

def get_style(style_enum):
    """Helper to extract the exact internal value (int/str) from Pyrogram's ButtonStyle"""
    return style_enum.value if hasattr(style_enum, 'value') else style_enum

import bot.state as state
from bot.config import ADMIN_ID, USER_REQUEST_LIMIT, BLOCK_ARTIST_LINKS, BOT_TOKEN
from bot.auth import is_chat_approved, load_approved_groups, save_approved_groups, load_approved_topics, save_approved_topics
from bot.status import update_status_board
from bot.utils import delete_message_after

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    start_html = (
        "<h1><tg-emoji custom_emoji_id=\"6158673735969677027\">🍎</tg-emoji> Apple Music Downloader</h1>\n"
        "<aside>The ultimate lossless audio extraction engine natively integrated into Telegram.</aside>\n"
        "<hr/>\n"
        "<p><i>Select an option below to explore features, settings, or get help.</i></p>"
    )
    
    # Main menu keyboard with the new red Close button
    keyboard_dict = {
        "inline_keyboard": [
            [
                {"text": "🎵 Download Mode", "callback_data": "menu_dl", "style": get_style(ButtonStyle.PRIMARY)},
                {"text": "⚙️ Settings", "callback_data": "menu_settings", "style": get_style(ButtonStyle.PRIMARY)}
            ],
            [
                {"text": "📖 Full Help & Examples", "callback_data": "menu_help", "style": get_style(ButtonStyle.SUCCESS)}
            ],
            [
                {"text": "Close ❌", "callback_data": "menu_close", "style": get_style(ButtonStyle.DANGER)}
            ]
        ]
    }

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendRichMessage"
    payload = {
        "chat_id": update.effective_chat.id,
        "rich_message": {"html": start_html},
        "reply_markup": keyboard_dict 
    }
    
    if update.effective_message.is_topic_message:
        payload["message_thread_id"] = update.effective_message.message_thread_id

    try:
        response = await asyncio.to_thread(requests.post, url, json=payload)
        data = response.json()
        if not data.get('ok'):
            error_desc = data.get('description', 'Unknown Error')
            await update.effective_message.reply_text(f"⚠️ <b>Rich HTML Payload Rejected:</b> {error_desc}", parse_mode="HTML")
    except Exception as e:
        await update.effective_message.reply_text(f"⚠️ Network/Request failed: {e}")

# ==========================================
# Button Click Handler Engine
# ==========================================
async def interactive_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer() 
    data = query.data
    
    chat_id = query.message.chat.id
    message_id = query.message.message_id
    
    if not data.startswith("menu_"): return

    # ❌ Action: Close the panel
    if data == "menu_close":
        try:
            await query.message.delete()
        except Exception as e:
            print(f"Failed to delete menu message: {e}")
        return

    html_content = ""
    keyboard_dict = {"inline_keyboard": []}

    # 🔙 Action: Return to Main Menu
    if data == "menu_main":
        html_content = (
            "<h1><tg-emoji custom_emoji_id=\"6158673735969677027\">🍎</tg-emoji> Apple Music Downloader</h1>\n"
            "<aside>The ultimate lossless audio extraction engine natively integrated into Telegram.</aside>\n"
            "<hr/>\n"
            "<p><i>Select an option below to explore features, settings, or get help.</i></p>"
        )
        keyboard_dict["inline_keyboard"] = [
            [
                {"text": "🎵 Download Mode", "callback_data": "menu_dl", "style": get_style(ButtonStyle.PRIMARY)},
                {"text": "⚙️ Settings", "callback_data": "menu_settings", "style": get_style(ButtonStyle.PRIMARY)}
            ],
            [
                {"text": "📖 Full Help & Examples", "callback_data": "menu_help", "style": get_style(ButtonStyle.SUCCESS)}
            ],
            [
                {"text": "Close ❌", "callback_data": "menu_close", "style": get_style(ButtonStyle.DANGER)}
            ]
        ]

    # 🎵 Action: Download Instructions
    elif data == "menu_dl":
        html_content = (
            "<h2>🎵 How to Download</h2>\n"
            "<p>To start a download, simply send your Apple Music link with the <code>/amdl</code> command.</p>\n"
            "<blockquote expandable>👉 <b>Example:</b> <code>/amdl https://music.apple.com/...</code></blockquote>\n"
            "<br/>\n"
            "<p><b>Supported Link Types:</b></p>\n"
            "<ul>\n"
            "<li><b>Tracks, Albums, and Playlists</b> (up to 100 tracks) are fully supported.</li>\n"
            "</ul>\n"
        )
        keyboard_dict["inline_keyboard"] = [
            [{"text": "🔙 Back to Main Menu", "callback_data": "menu_main", "style": get_style(ButtonStyle.PRIMARY)}],
            [{"text": "Close ❌", "callback_data": "menu_close", "style": get_style(ButtonStyle.DANGER)}]
        ]

    # ⚙️ Action: Settings Menu
    elif data == "menu_settings":
        html_content = (
            "<h2>⚙️ User Settings</h2>\n"
            "<p><i>Advanced settings configuration is currently under construction.</i></p>\n"
            "<p>Default Quality Protocol: <b>ALAC Lossless 24-bit</b></p>\n"
        )
        keyboard_dict["inline_keyboard"] = [
            [{"text": "🔙 Back to Main Menu", "callback_data": "menu_main", "style": get_style(ButtonStyle.PRIMARY)}],
            [{"text": "Close ❌", "callback_data": "menu_close", "style": get_style(ButtonStyle.DANGER)}]
        ]

    # 📖 Action: The Full Detailed Help Table
    elif data == "menu_help":
        html_content = (
            "<h1><tg-emoji custom_emoji_id=\"6158673735969677027\">🍎</tg-emoji> Help & Commands</h1>\n"
            "<hr/>\n"
            "<h2>💎 Extraction Quality</h2>\n"
            "<p>By default, the engine extracts raw <b>ALAC Lossless</b> data. Append flags to your URL to override the format parameters:</p>\n"
            "<table bordered striped>\n"
            "<tr><th align=\"left\">Flag</th><th align=\"left\">Behavior & Specification</th></tr>\n"
            "<tr><td><i>(None)</i></td><td><b>ALAC Lossless:</b> Studio-grade audio (up to 24-bit/192kHz).</td></tr>\n"
            "<tr><td><code>#aac</code></td><td><b>Standard AAC:</b> Forces a 256kbps lossy download.</td></tr>\n"
            "<tr><td><code>#atmos</code></td><td><b>Spatial Audio:</b> Immersive Dolby Atmos stream.</td></tr>\n"
            "</table>\n"
            "<br/>\n"
            
            "<details open>\n"
            "<summary>📖 <b>Detailed Usage Examples</b></summary>\n"
            "<br/>\n"
            "<table bordered striped>\n"
            "<tr><th align=\"left\">Target</th><th align=\"left\">Command Syntax</th></tr>\n"
            "<tr><td><b>Album</b></td><td><code>/amdl .../album/123</code></td></tr>\n"
            "<tr><td><b>Playlist</b></td><td><code>/amdl .../playlist/456</code></td></tr>\n"
            "<tr><td><b>Single Track</b></td><td><code>/amdl .../song/789</code></td></tr>\n"
            "<tr><td><b>Force AAC</b></td><td><code>/amdl .../song/789 #aac</code></td></tr>\n"
            "<tr><td><b>Atmos</b></td><td><code>/amdl .../album/123 #atmos</code></td></tr>\n"
            "<tr><td><b>Video</b></td><td><code>/amdl .../video/99</code></td></tr>\n"
            "</table>\n"
            "</details>\n"
            "<br/>\n"
            
            "<details>\n"
            "<summary>⚙️ <b>System Commands & Admins</b></summary>\n"
            "<br/>\n"
            "<table bordered striped>\n"
            "<tr><th align=\"left\">Command</th><th align=\"left\">Action</th></tr>\n"
            "<tr><td><code>/status</code></td><td>Monitor live downloads</td></tr>\n"
            "<tr><td><code>/cancel_&lt;ID&gt;</code></td><td>Terminate active task</td></tr>\n"
            "<tr><td><code>/authg</code></td><td><b>[Admin]</b> Authorize group</td></tr>\n"
            "<tr><td><code>/autht</code></td><td><b>[Admin]</b> Authorize topic</td></tr>\n"
            "<tr><td><code>/restart</code></td><td><b>[Admin]</b> Reboot system</td></tr>\n"
            "</table>\n"
            "</details>\n"
        )
        keyboard_dict["inline_keyboard"] = [
            [{"text": "🔙 Back to Main Menu", "callback_data": "menu_main", "style": get_style(ButtonStyle.PRIMARY)}],
            [{"text": "Close ❌", "callback_data": "menu_close", "style": get_style(ButtonStyle.DANGER)}]
        ]
    
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText"
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "rich_message": {"html": html_content},
        "reply_markup": keyboard_dict
    }
    
    try:
        await asyncio.to_thread(requests.post, url, json=payload)
    except Exception as e:
        print(f"Failed to edit rich menu: {e}")

# ==========================================
# REST OF THE BOT FUNCTIONS
# ==========================================
async def cmd_restart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    msg = await update.effective_message.reply_text("🔄 <b>Restarting bot...</b>\n<i>The bot will be back online in a few seconds.</i>", parse_mode="HTML")
    with open("restart_info.txt", "w") as f: f.write(str(update.effective_chat.id))
    await asyncio.sleep(1)
    os.execl(sys.executable, sys.executable, '-m', 'bot.main')

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    thread_id = update.effective_message.message_thread_id if update.effective_message.is_topic_message else None
    
    async with state.download_tasks_lock:
        tasks_exist = any(t['chat_id'] == chat_id for t in state.download_registry.values())
    
    if not tasks_exist:
        msg = await update.effective_message.reply_text("😁 No active tasks at the moment.")
        asyncio.create_task(delete_message_after(msg, 10))
        try: await update.effective_message.delete()
        except: pass
        return
        
    async with state.status_updater_lock:
        key = (chat_id, thread_id)
        if key in state.chat_status_messages:
            try: await state.chat_status_messages[key].delete()
            except: pass
            del state.chat_status_messages[key]
            
    await update_status_board(chat_id, thread_id, context.bot, is_new_task=True)
    try: await update.effective_message.delete()
    except: pass

async def cmd_authg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    chat_id = update.effective_chat.id
    ag = load_approved_groups()
    if chat_id in ag: await update.effective_message.reply_text("Group already approved.")
    else: 
        ag.append(chat_id); save_approved_groups(ag)
        await update.effective_message.reply_text("Group approved.")

async def cmd_autht(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    msg = update.effective_message
    if not msg.is_topic_message: return await msg.reply_text("Must be used in a topic.")
    chat_id, thread_id = str(update.effective_chat.id), msg.message_thread_id
    at = load_approved_topics()
    if chat_id not in at: at[chat_id] = []
    if thread_id in at[chat_id]: await msg.reply_text("Topic already approved.")
    else:
        at[chat_id].append(thread_id); save_approved_topics(at)
        await msg.reply_text("Topic approved.")

# Dummy placeholders to prevent import errors in main.py
async def cmd_approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pass
async def cmd_revoke(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pass

async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import signal
    dl_id = context.matches[0].group(1)
    user_id = update.effective_user.id
    
    async with state.download_tasks_lock:
        if dl_id not in state.download_registry:
            msg = await update.effective_message.reply_text("❌ Task not found or already completed.")
            asyncio.create_task(delete_message_after(msg, 5))
            return
            
        task = state.download_registry[dl_id]
        if user_id != ADMIN_ID and user_id != task['user_id']:
            msg = await update.effective_message.reply_text("⛔ You are not authorized to cancel this task.")
            asyncio.create_task(delete_message_after(msg, 5))
            return
            
        task['user_cancelled'].set()
        if 'process' in task and task['process'] and task['process'].returncode is None:
            try: os.killpg(os.getpgid(task['process'].pid), signal.SIGKILL)
            except:
                try: task['process'].kill()
                except: pass
            
    msg = await update.effective_message.reply_text(f"✅ Cancellation signal sent for `{dl_id}`.", parse_mode="Markdown")
    asyncio.create_task(delete_message_after(msg, 5))
    try: await update.effective_message.delete()
    except: pass

async def upload_mode_timeout(dl_id: str, chat_id: int, message_id: int, bot):
    await asyncio.sleep(30)
    if dl_id in state.pending_upload_selections:
        state.pending_upload_selections.pop(dl_id, None)
        try:
            await bot.edit_message_text(
                chat_id=chat_id, message_id=message_id,
                text="⏳ *Timeout:* No upload mode selected\\. Task cancelled\\.",
                parse_mode='MarkdownV2'
            )
        except Exception: pass

async def cmd_amdl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not is_chat_approved(update, ADMIN_ID):
        return await msg.reply_text("This chat/topic/user is not approved for use.")
        
    if not context.args:
        return await msg.reply_text("Usage: `/amdl <URL> [#aac|#atmos]`", parse_mode='Markdown')

    url = context.args[0]
    if "music.apple.com" not in url: return await msg.reply_text("❌ Invalid Apple Music URL.")
        
    if BLOCK_ARTIST_LINKS and ('/artist/' in url.lower() or '/interpreter/' in url.lower()) and update.effective_user.id != ADMIN_ID:
        return await msg.reply_text("❌ Artist/Discography Links are not allowed.")

    flags = [a.lower() for a in context.args[1:]]
    quality = 'alac'
    if '#aac' in flags: quality = 'aac'
    elif '#atmos' in flags: quality = 'atmos'

    user_id = update.effective_user.id
    dl_id = secrets.token_hex(4)

    async with state.queue_lock:
        reqs = state.user_requests.get(user_id, [])
        if user_id != ADMIN_ID and len(reqs) >= USER_REQUEST_LIMIT:
            return await msg.reply_text("⏳ Request limit reached. Wait for tasks to finish.")

    payload = {
        "user_id": user_id, "user_name": update.effective_user.username,
        "chat_id": msg.chat_id, "thread_id": msg.message_thread_id,
        "url": url, "quality_flag": quality, "user_cancelled": asyncio.Event(),
        "reply_to_message_id": msg.message_id, "status": "pending_menu"
    }
    
    state.pending_upload_selections[dl_id] = payload

    # ==============================================================
    # ORPHEUS PYROGRAM FALLBACK (FOR COLORED BUTTONS IN UPLOAD MODE)
    # ==============================================================
    if state.pyrogram_client and state.pyrogram_client.is_connected:
        try:
            from pyrogram.enums import ButtonStyle, ParseMode
            from pyrogram.types import InlineKeyboardMarkup as PyroInlineKeyboardMarkup, InlineKeyboardButton as PyroInlineKeyboardButton
            
            keyboard = PyroInlineKeyboardMarkup([
                [PyroInlineKeyboardButton("Gofile (Zip)", callback_data=f"upmode_gofile_{dl_id}", style=ButtonStyle.SUCCESS)],
                [PyroInlineKeyboardButton("Telegram (Zip)", callback_data=f"upmode_tgzip_{dl_id}", style=ButtonStyle.PRIMARY)],
                [PyroInlineKeyboardButton("Telegram (unZip)", callback_data=f"upmode_tgunzip_{dl_id}", style=ButtonStyle.PRIMARY)],
                [PyroInlineKeyboardButton("TG (Zip + unZip)", callback_data=f"upmode_tgboth_{dl_id}", style=ButtonStyle.PRIMARY)],
                [PyroInlineKeyboardButton("Cancel ❌", callback_data=f"upmode_cancel_{dl_id}", style=ButtonStyle.DANGER)]
            ])
            
            sent_msg = await state.pyrogram_client.send_message(
                chat_id=msg.chat_id,
                text="> 📤 **Select an Upload Mode:**\n> __You have 30 seconds to choose.__",
                reply_to_message_id=msg.message_id,
                reply_markup=keyboard,
                parse_mode=ParseMode.MARKDOWN
            )
            asyncio.create_task(upload_mode_timeout(dl_id, msg.chat_id, sent_msg.id, context.bot))
            return
        except Exception as e:
            print(f"Pyrogram colored keyboard failed, falling back to PTB: {e}")

    # Standard PTB Fallback (No Colors) if Pyrogram is down
    keyboard = [
        [PTBInlineKeyboardButton("Gofile (Zip)", callback_data=f"upmode_gofile_{dl_id}")],
        [PTBInlineKeyboardButton("Telegram (Zip)", callback_data=f"upmode_tgzip_{dl_id}")],
        [PTBInlineKeyboardButton("Telegram (unZip)", callback_data=f"upmode_tgunzip_{dl_id}")],
        [PTBInlineKeyboardButton("TG (Zip + unZip)", callback_data=f"upmode_tgboth_{dl_id}")],
        [PTBInlineKeyboardButton("Cancel ❌", callback_data=f"upmode_cancel_{dl_id}")]
    ]
    
    sent_msg = await msg.reply_text(
        "> 📤 *Select an Upload Mode:*\n> _You have 30 seconds to choose\\._",
        reply_markup=PTBInlineKeyboardMarkup(keyboard),
        parse_mode='MarkdownV2'
    )
    asyncio.create_task(upload_mode_timeout(dl_id, msg.chat_id, sent_msg.message_id, context.bot))

async def upload_mode_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    
    if not data.startswith("upmode_"): return
    
    await query.answer()
    parts = data.split("_")
    mode, dl_id = parts[1], parts[2]
    
    if dl_id not in state.pending_upload_selections:
        try: await query.edit_message_text("❌ Task expired or already processed.")
        except: pass
        return
        
    payload = state.pending_upload_selections.pop(dl_id)
    
    if mode == "cancel":
        return await query.edit_message_text("❌ Task cancelled by user.")
    
    payload["upload_to_telegram_flag"] = mode in ["tgzip", "tgunzip", "tgboth"]
    payload["unzip_flag"] = mode in ["tgunzip", "tgboth"]
    payload["force_zip_flag"] = mode in ["tgzip", "tgboth"]
    payload["status"] = "queued"
    
    async with state.queue_lock:
        async with state.download_tasks_lock: state.download_registry[dl_id] = payload
        if payload["user_id"] not in state.user_requests: state.user_requests[payload["user_id"]] = []
        state.user_requests[payload["user_id"]].append({"dl_id": dl_id})

    await query.edit_message_text("✅ Request added to queue.")
    asyncio.create_task(delete_message_after(query.message, 5))
    
    await state.download_queue.put(dl_id)
    state.FORCE_NEW_STATUS = True