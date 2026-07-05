# 🎬 OTT Updates Bot

A Telegram bot that automatically notifies you when new movies and TV shows land on Netflix, Amazon Prime, Hotstar, Disney+, and 10+ other streaming platforms.

---

## Features

- 🔔 **Auto-updates** on a configurable schedule (default every 6 hours)
- 🎬 **Movie posters** sent with each notification
- ⭐ **Ratings & genres** from TMDB
- 📡 **14+ platforms** — Netflix, Prime, Hotstar, Disney+, Apple TV+, SonyLIV, ZEE5, and more
- 🌍 **Multi-region** support (IN, US, GB, AU, CA, …)
- 📢 **Channel/group mode** — push to a channel automatically
- 👤 **Per-user subscriptions** — users subscribe individually
- 🔧 **Admin commands** — broadcast messages, force update checks

---

## Setup

### 1. Get credentials

| Credential | Where to get it |
|---|---|
| `BOT_TOKEN` | [@BotFather](https://t.me/BotFather) → `/newbot` |
| `API_ID` / `API_HASH` | https://my.telegram.org/apps |

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env and fill in your values
```

### 3. Run

**With Docker (recommended):**
```bash
docker-compose up -d
```

**Manually:**
```bash
pip install -r requirements.txt
python bot.py
```

---

## Bot Commands

| Command | Description |
|---|---|
| `/start` | Welcome message with quick-action buttons |
| `/subscribe` | Subscribe to automatic OTT updates |
| `/unsubscribe` | Stop receiving updates |
| `/latest` | Manually fetch latest new releases now |
| `/platforms` | List all supported streaming services |
| `/stats` | Bot uptime, subscriber count, releases sent |
| `/about` | About this bot and data sources |
| `/help` | Show all commands |

### Admin Commands *(requires `ADMIN_ID` in .env)*

| Command | Description |
|---|---|
| `/broadcast <msg>` | Send a message to all subscribers |
| `/sendnow` | Force an immediate update check |

---

## Configuration

All settings live in `.env`:

```ini
# Required
BOT_TOKEN=...
API_ID=...
API_HASH=...

# Recommended
TMDB_API_KEY=...

# Optional
CHAT_ID=-100123456789        # Push to a channel (leave blank for per-user subs)
ADMIN_ID=123456789           # Your Telegram user ID
UPDATE_INTERVAL_HOURS=6      # How often to check (default: 6)
JUSTWATCH_COUNTRY=IN         # Country code: IN, US, GB, AU, CA, etc.
PORT=8080                    # Health-check port
```

---

## Deployment

### Koyeb / Railway / Render

1. Push this repo to GitHub
2. Connect your GitHub repo to the platform
3. Set all environment variables from `.env.example`
4. Deploy — the health-check endpoint at `/health` is ready

### VPS / Server

```bash
git clone <your-repo>
cd ott-updater-bot
cp .env.example .env && nano .env
docker-compose up -d
docker-compose logs -f      # Watch logs
```

---

## Data Sources

- **Primary:** [TMDB API v3](https://developers.themoviedb.org/3) — free, reliable, includes watch provider data
- **Fallback:** [JustWatch](https://www.justwatch.com) — scraped, no key needed

---

## Troubleshooting

**Bot starts but sends no updates**
- Check `TMDB_API_KEY` is valid
- Verify `JUSTWATCH_COUNTRY` is correct (e.g. `IN` not `India`)
- Try `/latest` to test manually

**"Missing API_ID / API_HASH" error**
- Both are required. Get them from https://my.telegram.org/apps

**Admin commands not working**
- Set `ADMIN_ID` to your numeric Telegram user ID (message @userinfobot to find it)

**No results for my country**
- TMDB watch providers vary widely. Try `US` or `IN` which have the most data.
