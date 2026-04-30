import os
import time

# Bot boot timestamp (used by /stats)
BOT_START_TIME: float = time.time()

# How often to broadcast new releases (hours)
UPDATE_INTERVAL_HOURS: int = int(os.getenv("UPDATE_INTERVAL_HOURS", "6"))

# JustWatch / TMDB region settings
JUSTWATCH_COUNTRY: str  = os.getenv("JUSTWATCH_COUNTRY", "IN").upper()
JUSTWATCH_LANGUAGE: str = os.getenv("JUSTWATCH_LANGUAGE", "en")

# TMDB API key (free at https://www.themoviedb.org/settings/api)
TMDB_API_KEY: str = os.getenv("TMDB_API_KEY", "")

# Optional: comma-separated channel/group IDs to push updates to
CHAT_ID: str = os.getenv("CHAT_ID", "")

# Admin Telegram user ID (for /broadcast)
ADMIN_ID: str = os.getenv("ADMIN_ID", "")
