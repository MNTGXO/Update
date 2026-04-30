import os
import time

# Bot boot timestamp (used by /stats)
BOT_START_TIME: float = time.time()

# ── MongoDB ───────────────────────────────────────────────────────────────────
MONGO_URI:     str = os.getenv("MONGO_URI", "")
MONGO_DB_NAME: str = os.getenv("MONGO_DB_NAME", "ott_bot")

# ── Scheduler ─────────────────────────────────────────────────────────────────
UPDATE_INTERVAL_HOURS: int = int(os.getenv("UPDATE_INTERVAL_HOURS", "6"))

# ── Region ────────────────────────────────────────────────────────────────────
JUSTWATCH_COUNTRY: str  = os.getenv("JUSTWATCH_COUNTRY", "IN").upper()
JUSTWATCH_LANGUAGE: str = os.getenv("JUSTWATCH_LANGUAGE", "en")

# ── TMDB ──────────────────────────────────────────────────────────────────────
TMDB_API_KEY: str = os.getenv("TMDB_API_KEY", "")

# ── Telegram ──────────────────────────────────────────────────────────────────
# Comma-separated channel/group IDs for channel-mode broadcasting
CHAT_ID:  str = os.getenv("CHAT_ID", "")
ADMIN_ID: str = os.getenv("ADMIN_ID", "")
