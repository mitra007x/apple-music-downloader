import os

# --- Configuration ---
BOT_TOKEN = "8891762925:AAG7fXZ1m9WVa72pY78NRyx0UZLNXoVv-a8" # INPUT YOUR BOT TOKEN
ADMIN_ID = 731336143
USER_REQUEST_LIMIT = 2
GOFILE_TOKEN = "wxWEuqKbUj1mZ2PTJMr49Ec03WrgwevV"
DUMP_CHANNEL_ID = "@mudump7"

# --- User Limits ---
MAX_PLAYLIST_TRACKS = 100
BLOCK_ARTIST_LINKS = True

# Pyrogram Config
API_ID = 28442919
API_HASH = "e881fe0b8d9ae8eeec10d9457e8e23e1"
SESSION_NAME = "amdl_pyrogram_session"

# Directory Setup
BASE_DIR = os.path.expanduser('~/mitra/amdl/downloader')
DOWN_DIR = os.path.join(BASE_DIR, 'down')
STAGE_BASE_DIR = os.path.join(BASE_DIR, 'stage')
ZIP_DIR = os.path.join(BASE_DIR, 'zips')
CONFIG_DIR = os.path.join(BASE_DIR, 'config')

APPROVED_GROUPS_FILE = os.path.join(CONFIG_DIR, 'approved_groups.json')
APPROVED_TOPICS_FILE = os.path.join(CONFIG_DIR, 'approved_topics.json')
APPROVED_USERS_FILE = os.path.join(CONFIG_DIR, 'approved_users.json')
TELEGRAPH_TOKEN_FILE = os.path.join(CONFIG_DIR, "telegraph_token.json")

MAX_CONCURRENT_DOWNLOADS = 1

# Ensure directories exist
os.makedirs(DOWN_DIR, exist_ok=True)
os.makedirs(STAGE_BASE_DIR, exist_ok=True)
os.makedirs(ZIP_DIR, exist_ok=True)
os.makedirs(CONFIG_DIR, exist_ok=True)