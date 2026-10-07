import asyncio
from telegram import InlineKeyboardMarkup as PTBInlineKeyboardMarkup, InlineKeyboardButton as PTBInlineKeyboardButton, Update
from telegram.ext import ContextTypes

import bot.state as state
from bot.utils import escape_markdown_v2

async def update_status_board(chat_id: int, thread_id: int, bot, is_new_task: bool = False):
    async with state.status_updater_lock:
        message_key = (chat_id, thread_id)
        active_tasks = []
        async with state.download_tasks_lock:
            for dl_id, task in state.download_registry.items():
                active_tasks.append((dl_id, task))
        
        total_tasks = len(active_tasks)
        final_text = ""
        reply_markup = None
        
        if total_tasks > 0:
            header = "*🍎 Apple Music DL Status 🍎*"
            body = []
            
            page = state.chat_pages.get(message_key, 1)
            max_pages = max(1, (total_tasks + 4) // 5)
            if page > max_pages: page = max_pages
            if page < 1: page = 1
            state.chat_pages[message_key] = page
            
            start_idx = (page - 1) * 5
            page_tasks = active_tasks[start_idx : start_idx + 5]
            
            for idx, (dl_id, task) in enumerate(page_tasks, start_idx + 1):
                user_mention = escape_markdown_v2(f"@{task['user_name']}" if task.get('user_name') else f"ID: {task['user_id']}")
                
                status_val_lower = task['status'].lower()
                if status_val_lower == "downloading": status_icon = "📥"
                elif status_val_lower == "processing": status_icon = "⚙️"
                elif "upload" in status_val_lower: status_icon = "📤"
                elif "zip" in status_val_lower: status_icon = "🗜️"
                else: status_icon = "⏳"
                
                status_val = escape_markdown_v2(task['status'].title())
                
                is_tg = task.get('upload_to_telegram_flag', False)
                is_unzip = task.get('unzip_flag', False)
                is_force_zip = task.get('force_zip_flag', False)
                
                upload_mode = "Gofile"
                if is_tg:
                    if is_unzip and is_force_zip: upload_mode = "TG (Zip + unZip)"
                    elif is_unzip: upload_mode = "TG (unZip)"
                    else: upload_mode = "TG (Zip)"
                
                if task['status'] in ['queued', 'pending_menu', 'waiting for upload']:
                    body.append(
                        f"> *{idx}*\\. {status_icon} *Task ID:* `{dl_id}` \\(by {user_mention}\\)\n"
                        f"> ╭ *Status:* _{status_val}_\n"
                        f"> ╰ *Upload Mode:* _{escape_markdown_v2(upload_mode)}_\n"
                        f"> ❌ *Cancel:* _/cancel\\_{dl_id}_"
                    )
                else:
                    prog_stats = escape_markdown_v2(task.get('progress_stats', '-'))
                    prog_spd = escape_markdown_v2(task.get('progress_speed', '-'))
                    folder_size = task.get('down_folder_size')
                    if folder_size and task['status'] == 'downloading':
                        prog_stats += f" \\| {escape_markdown_v2(folder_size)}"

                    body.append(
                        f"> *{idx}*\\. {status_icon} *Task ID:* `{dl_id}` \\(by {user_mention}\\)\n"
                        f"> ╭ *Status:* _{status_val}_\n"
                        f"> ├ *Progress:* _{prog_stats}_\n"
                        f"> ├ *Speed:* _{prog_spd}_\n"
                        f"> ╰ *Upload Mode:* _{escape_markdown_v2(upload_mode)}_\n"
                        f"> ❌ *Cancel:* _/cancel\\_{dl_id}_"
                    )
            
            final_text = header + "\n\n" + "\n\n".join(body)
            
            if max_pages > 1:
                buttons = []
                if page > 1:
                    buttons.append(PTBInlineKeyboardButton("⬅️ Prev", callback_data=f"status_page_{page-1}"))
                if page < max_pages:
                    buttons.append(PTBInlineKeyboardButton("Next ➡️", callback_data=f"status_page_{page+1}"))
                reply_markup = PTBInlineKeyboardMarkup([buttons])

        existing_message = state.chat_status_messages.get(message_key)
        
        if not final_text:
            if existing_message:
                try: await existing_message.delete()
                except: pass
                state.chat_status_messages.pop(message_key, None)
            return

        if is_new_task or not existing_message:
            if existing_message:
                try: await existing_message.delete()
                except: pass
            try:
                new_msg = await bot.send_message(chat_id=chat_id, message_thread_id=thread_id, text=final_text, parse_mode='MarkdownV2', disable_web_page_preview=True, reply_markup=reply_markup)
                state.chat_status_messages[message_key] = new_msg
            except: pass
        else:
            try: await existing_message.edit_text(text=final_text, parse_mode='MarkdownV2', disable_web_page_preview=True, reply_markup=reply_markup)
            except: pass

async def status_updater_task(app):
    while True:
        await asyncio.sleep(4)
        is_new = state.FORCE_NEW_STATUS
        state.FORCE_NEW_STATUS = False
        
        active_chats = set(state.chat_status_messages.keys())
        async with state.download_tasks_lock:
            for task in state.download_registry.values():
                active_chats.add((task['chat_id'], task['thread_id']))
        for chat_id, thread_id in active_chats:
            await update_status_board(chat_id, thread_id, app.bot, is_new_task=is_new)

async def status_page_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    page = int(query.data.split("_")[2])
    
    chat_id = update.effective_chat.id
    thread_id = update.effective_message.message_thread_id if update.effective_message.is_topic_message else None
    
    state.chat_pages[(chat_id, thread_id)] = page
    await update_status_board(chat_id, thread_id, context.bot, is_new_task=False)