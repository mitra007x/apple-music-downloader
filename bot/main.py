import os
import asyncio
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters
from pyrogram import Client

import bot.state as state
from bot.config import BOT_TOKEN, API_ID, API_HASH, SESSION_NAME, MAX_CONCURRENT_DOWNLOADS

# Added interactive_menu_callback to your existing imports
from bot.handlers import cmd_start, cmd_status, cmd_authg, cmd_autht, cmd_approve, cmd_revoke, cmd_cancel, cmd_amdl, upload_mode_callback, cmd_restart, interactive_menu_callback
from bot.status import status_page_callback, status_updater_task
from bot.downloader import queue_processor

async def post_shutdown_setup(app: Application):
    if state.pyrogram_client and state.pyrogram_client.is_connected:
        print("Stopping Pyrogram...")
        await state.pyrogram_client.stop()
        print("Pyrogram stopped cleanly.")

async def post_init_setup(app: Application):
    state.download_semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)
    state.upload_semaphore = asyncio.Semaphore(1)
    
    state.available_slots = asyncio.Queue()
    for i in range(1, MAX_CONCURRENT_DOWNLOADS + 1): 
        await state.available_slots.put(i)
    
    print("Initializing Pyrogram...")
    state.pyrogram_client = Client(SESSION_NAME, api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
    await state.pyrogram_client.start()
    
    asyncio.create_task(queue_processor(app, state.pyrogram_client))
    asyncio.create_task(status_updater_task(app))

    # Check if we just restarted, and send a fresh notification
    if os.path.exists("restart_info.txt"):
        try:
            with open("restart_info.txt", "r") as f:
                data = f.read().strip()
                
            if data:
                # Handle both old error format (chat_id,msg_id) and new format (chat_id) safely
                chat_id_str = data.split(",")[0] if "," in data else data
                chat_id = int(chat_id_str)
                
                await app.bot.send_message(
                    chat_id=chat_id,
                    text="✅ <b>Restarted Successfully!</b>\n<i>I'm back online and ready to accept downloads.</i>",
                    parse_mode="HTML"
                )
            os.remove("restart_info.txt")
        except Exception as e:
            print(f"Failed to send restart notification: {e}")
            if os.path.exists("restart_info.txt"):
                os.remove("restart_info.txt")

def main():
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init_setup)
        .post_shutdown(post_shutdown_setup)
        .build()
    )

    app.add_handler(CommandHandler(["start", "help"], cmd_start))
    app.add_handler(CommandHandler(["status", "s"], cmd_status))
    app.add_handler(CommandHandler("authg", cmd_authg))
    app.add_handler(CommandHandler("autht", cmd_autht))
    app.add_handler(CommandHandler("approve", cmd_approve))
    app.add_handler(CommandHandler("revoke", cmd_revoke))
    app.add_handler(CommandHandler("amdl", cmd_amdl))
    app.add_handler(CommandHandler("restart", cmd_restart))
    
    app.add_handler(MessageHandler(filters.Regex(r'^/cancel_([a-f0-9]{8})(?:@\w+)?$'), cmd_cancel))
    app.add_handler(CallbackQueryHandler(upload_mode_callback, pattern=r"^upmode_"))
    app.add_handler(CallbackQueryHandler(status_page_callback, pattern=r"^status_page_"))
    
    # 🆕 Added the new interactive menu callback handler
    app.add_handler(CallbackQueryHandler(interactive_menu_callback, pattern=r"^menu_"))

    print("Apple Music Bot Polling Started...")
    app.run_polling()

if __name__ == "__main__":
    main()