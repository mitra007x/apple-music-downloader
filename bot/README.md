# 🍏🎧 Apple Music DL Bot
A robust, modular Telegram Bot built to download tracks, albums, playlists, and music videos directly from Apple Music in ultimate lossless quality (ALAC) and Dolby Atmos.
This bot features a completely modular codebase, real-time download progress tracking, Telegram/GoFile upload routing, and utilizes **Telegram Bot API 10.1 Rich Messages** for a beautiful, highly-structured UI.
## 🛠 Prerequisites
Before installing the Python packages, your system **must** have the following external tools installed, as the bot relies on them for downloading and parsing media:
 1. **Go (Golang)**: Required to run the Apple Music downloader backend (main.go).
 2. **FFmpeg & FFprobe**: Required for video thumbnail extraction and duration mapping.
 3. **MediaInfo**: Required for extracting advanced audio bitrates and codecs (mediainfo command).
*(On Debian/Ubuntu, you can install the media tools via: sudo apt install ffmpeg mediainfo)*
## 📦 Installation
 1. **Clone or Setup your Directory:**
   Ensure your main project folder contains the bot/ directory with all the modular python files, alongside your main.go Apple Music ripper script.
 2. **Install Python Dependencies:**
   It is highly recommended to use a virtual environment.
   ```bash
   pip install -r requirements.txt
   
   ```
 3. **Configure the Bot:**
   Open bot/config.py and input your essential credentials:
   * BOT_TOKEN: Your Telegram Bot token from @BotFather.
   * API_ID & API_HASH: Your Pyrogram API keys from my.telegram.org.
   * ADMIN_ID: Your personal Telegram User ID.
   * GOFILE_TOKEN: (Optional) For external GoFile uploads.
   * DUMP_CHANNEL_ID: (Optional) ID of a channel to log all downloads.
## 🚀 Running the Bot
Because the project is structured as a Python module, run the bot from the root directory using the -m flag:
```bash
python3 -m bot.main

```
## 📁 Project Structure
```text
apple_music_bot/
│
├── main.go               # Your Golang Apple Music ripper
├── requirements.txt      # Python dependencies
├── README.md             # This file
│
└── bot/                  # Core Python Module
    ├── __init__.py       
    ├── config.py         # Tokens, IDs, and Path configurations
    ├── state.py          # Shared memory (queues, active tasks)
    ├── auth.py           # User/Group approval logic
    ├── utils.py          # Telegraph API, Media formatting, string escapes
    ├── upload.py         # GoFile & Telegram Zip logic
    ├── status.py         # Dynamic /status message updating
    ├── downloader.py     # Subprocess manager for the Go script
    ├── handlers.py       # User commands (/start, /amdl, /cancel)
    └── main.py           # Application builder & polling startup

```
## ✨ Features
 * **Rich HTML UI:** Utilizes native Telegram tags (<h1>, <details>, <table>, <tg-emoji>) for beautiful /start and /help menus.
 * **Granular Approvals:** Lock the bot to specific Users, Groups, or specific Topics inside a group.
 * **Lossless / Atmos:** Full support for ALAC and Dolby Atmos flags.
 * **Upload Flexibility:** Send files directly to Telegram (Zipped or unZipped) or upload them externally to GoFile.
