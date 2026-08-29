import os

# --- Configuration ---
# Pulling credentials securely from Dokploy Environment Variables
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID")) # Defaults to your ID if not set
USER_REQUEST_LIMIT = int(os.getenv("USER_REQUEST_LIMIT"))
GOFILE_TOKEN = os.getenv("GOFILE_TOKEN")
DUMP_CHANNEL_ID = os.getenv("DUMP_CHANNEL_ID")

# --- User Limits ---
MAX_PLAYLIST_TRACKS = 100
BLOCK_ARTIST_LINKS = True

# Pyrogram Config
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH")
SESSION_NAME = "amdl_pyrogram_session"

# Directory Setup
BASE_DIR = os.path.expanduser('~/amdl/downloader')
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
