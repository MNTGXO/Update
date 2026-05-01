"""
plugins/ott.py — OTT Daily Releases Browser + Movie/Series Search

Commands:
  /ott              — Today's OTT releases (inline buttons → detail)
  /ott DD-MM-YYYY   — Specific date's releases
  /setchannel       — Add a channel/group for auto-updates
  /removechannel    — Remove a channel/group
  /mychannels       — List registered channels

PM text (non-command):
  Any message → search TMDB → paginated results → tap for detail + OTT info
"""

import asyncio
import logging
from datetime import date, timedelta, datetime
from typing import Optional

import aiohttp
from pyrogram import Client, filters, enums
from pyrogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
)

from config import TMDB_API_KEY, JUSTWATCH_COUNTRY
from database import add_subscriber, remove_subscriber, set_auto_send

logger = logging.getLogger("OTTBot.ott")

# ─── Constants ────────────────────────────────────────────────────────────────
TMDB_BASE  = "https://api.themoviedb.org/3"
TMDB_IMG_W = "https://image.tmdb.org/t/p/w500"

RESULTS_PER_PAGE = 5     # search results shown per page
DAY_LIST_LIMIT   = 20    # max items in day view
CACHE_TTL        = 300   # seconds (5 min)

# ─── In-memory state ──────────────────────────────────────────────────────────
# search sessions per user  →  {user_id: {query, results, page, tmdb_page, tmdb_total}}
_sessions: dict[int, dict] = {}
# simple response cache  →  {cache_key: (data, expires)}
_cache: dict[str, tuple] = {}


# ═══════════════════════════════════════════════════════════════════════════════
#  TMDB helpers
# ═══════════════════════════════════════════════════════════════════════════════

async def _tmdb(path: str, params: dict | None = None) -> Optional[dict]:
    """GET from TMDB with simple TTL cache.  Returns None on failure."""
    if not TMDB_API_KEY:
        logger.warning("TMDB_API_KEY not set — OTT plugin disabled.")
        return None

    p = dict(params or {})
    p["api_key"] = TMDB_API_KEY

    cache_key = path + "|" + "&".join(f"{k}={v}" for k, v in sorted(p.items()) if k != "api_key")
    now = asyncio.get_event_loop().time()
    if cache_key in _cache:
        data, exp = _cache[cache_key]
        if now < exp:
            return data

    url = f"{TMDB_BASE}{path}"
    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.get(url, params=p, timeout=aiohttp.ClientTimeout(total=12)) as r:
                if r.status == 200:
                    data = await r.json()
                    _cache[cache_key] = (data, now + CACHE_TTL)
                    return data
                logger.warning(f"TMDB {path} → HTTP {r.status}")
    except asyncio.TimeoutError:
        logger.warning(f"TMDB {path} timed out")
    except Exception as exc:
        logger.error(f"TMDB {path} error: {exc}")
    return None


def _poster(path: str | None) -> str:
    return f"{TMDB_IMG_W}{path}" if path else ""


# ─── Fetch day releases ───────────────────────────────────────────────────────

async def fetch_day_releases(for_date: date) -> list[dict]:
    """Discover movies + TV with a primary/first-air date on for_date."""
    iso     = for_date.isoformat()
    country = (JUSTWATCH_COUNTRY or "IN").upper()
    base    = {
        "sort_by":                         "popularity.desc",
        "watch_region":                    country,
        "with_watch_monetization_types":   "flatrate",
        "page":                            1,
    }

    movies_raw, tv_raw = await asyncio.gather(
        _tmdb("/discover/movie", {**base,
               "primary_release_date.gte": iso,
               "primary_release_date.lte": iso}),
        _tmdb("/discover/tv",    {**base,
               "first_air_date.gte": iso,
               "first_air_date.lte": iso}),
    )

    items: list[dict] = []
    for m in (movies_raw or {}).get("results", []):
        items.append({
            "id":    m["id"],
            "type":  "movie",
            "title": m.get("title", "Unknown"),
            "year":  (m.get("primary_release_date") or "")[:4],
            "rating": round(m.get("vote_average", 0), 1),
            "poster": _poster(m.get("poster_path")),
        })
    for t in (tv_raw or {}).get("results", []):
        items.append({
            "id":    t["id"],
            "type":  "tv",
            "title": t.get("name", "Unknown"),
            "year":  (t.get("first_air_date") or "")[:4],
            "rating": round(t.get("vote_average", 0), 1),
            "poster": _poster(t.get("poster_path")),
        })

    items.sort(key=lambda x: -x["rating"])
    return items


# ─── Fetch item detail (movie or TV) ─────────────────────────────────────────

async def fetch_detail(item_type: str, item_id: int) -> Optional[dict]:
    country = (JUSTWATCH_COUNTRY or "IN").upper()
    path    = f"/movie/{item_id}" if item_type == "movie" else f"/tv/{item_id}"
    raw     = await _tmdb(path, {"append_to_response": "watch/providers,credits"})
    if not raw:
        return None

    # streaming providers
    prov_data = raw.get("watch/providers", {}).get("results", {})
    country_prov = prov_data.get(country, {})
    flatrate     = country_prov.get("flatrate", [])
    providers    = [p["provider_name"] for p in flatrate]

    # Also check rent/buy if no flatrate
    available_rent = [p["provider_name"] for p in country_prov.get("rent", [])]
    available_buy  = [p["provider_name"] for p in country_prov.get("buy",  [])]

    # cast
    cast = [c["name"] for c in raw.get("credits", {}).get("cast", [])[:5]]

    title   = raw.get("title") or raw.get("name", "Unknown")
    release = raw.get("release_date") or raw.get("first_air_date", "")
    year    = release[:4] if release else ""

    return {
        "id":            item_id,
        "type":          item_type,
        "title":         title,
        "year":          year,
        "release_date":  release,
        "status":        raw.get("status", ""),
        "rating":        round(raw.get("vote_average", 0), 1),
        "vote_count":    raw.get("vote_count", 0),
        "poster":        _poster(raw.get("poster_path")),
        "overview":      raw.get("overview", ""),
        "genres":        [g["name"] for g in raw.get("genres", [])],
        "cast":          cast,
        "runtime":       raw.get("runtime") or (raw.get("episode_run_time") or [None])[0],
        "seasons":       raw.get("number_of_seasons"),
        "episodes":      raw.get("number_of_episodes"),
        "providers":     providers,       # subscription streaming
        "rent":          available_rent,
        "buy":           available_buy,
        "tmdb_url":      f"https://www.themoviedb.org/{'movie' if item_type=='movie' else 'tv'}/{item_id}",
    }


# ─── Search ───────────────────────────────────────────────────────────────────

async def search_tmdb(query: str, page: int = 1) -> tuple[list[dict], int]:
    """Multi-search TMDB. Returns (results, total_pages)."""
    raw = await _tmdb("/search/multi", {"query": query, "page": page, "include_adult": "false"})
    if not raw:
        return [], 0
    results = []
    for r in raw.get("results", []):
        mt = r.get("media_type")
        if mt not in ("movie", "tv"):
            continue
        title    = r.get("title") or r.get("name", "Unknown")
        year_raw = r.get("release_date") or r.get("first_air_date", "")
        results.append({
            "id":     r["id"],
            "type":   mt,
            "title":  title,
            "year":   year_raw[:4] if year_raw else "N/A",
            "rating": round(r.get("vote_average", 0), 1),
            "poster": _poster(r.get("poster_path")),
        })
    return results, raw.get("total_pages", 1)


# ═══════════════════════════════════════════════════════════════════════════════
#  Formatting helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _fmt_date_label(d: date) -> str:
    today = date.today()
    if d == today:
        return f"📅 Today  —  {d.strftime('%d %b %Y')}"
    if d == today - timedelta(days=1):
        return f"📅 Yesterday  —  {d.strftime('%d %b %Y')}"
    if d == today + timedelta(days=1):
        return f"📅 Tomorrow  —  {d.strftime('%d %b %Y')}"
    return f"📅 {d.strftime('%d %b %Y')}"


def _parse_user_date(s: str) -> Optional[date]:
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            pass
    return None


def _icon(item_type: str) -> str:
    return "🎬" if item_type == "movie" else "📺"


def _format_detail_text(d: dict) -> str:
    lines = [f"{_icon(d['type'])} <b>{d['title']}</b>"]

    if d.get("release_date"):
        lines.append(f"📅 <b>{'Release' if d['type']=='movie' else 'First Air'}:</b> {d['release_date']}")

    if d.get("rating"):
        bar = "★" * round(d["rating"] / 2) + "☆" * (5 - round(d["rating"] / 2))
        lines.append(f"⭐ <b>Rating:</b> {d['rating']}/10  <code>{bar}</code>  ({d['vote_count']:,} votes)")

    if d.get("genres"):
        lines.append(f"🎭 <b>Genres:</b> {' · '.join(d['genres'])}")

    if d.get("runtime"):
        h, m = divmod(d["runtime"], 60)
        rt = f"{h}h {m}m" if h else f"{m}m"
        lines.append(f"⏱ <b>Runtime:</b> {rt}")

    if d.get("seasons"):
        lines.append(f"📺 <b>Seasons:</b> {d['seasons']}  |  <b>Episodes:</b> {d.get('episodes','?')}")

    if d.get("status"):
        lines.append(f"🔖 <b>Status:</b> {d['status']}")

    if d.get("cast"):
        lines.append(f"🎭 <b>Cast:</b> {', '.join(d['cast'])}")

    lines.append("")  # blank line before OTT section

    # ── OTT availability ──────────────────────────────────────────────────
    if d.get("providers"):
        provider_str = "  ·  ".join(d["providers"])
        lines.append(f"✅ <b>Streaming on:</b>  {provider_str}")
    elif d.get("rent") or d.get("buy"):
        rent_str = "  ·  ".join((d.get("rent") or []) + (d.get("buy") or []))
        lines.append(f"🛒 <b>Rent/Buy on:</b>  {rent_str}")
        lines.append("❌ Not on subscription streaming in your region.")
    else:
        year = int(d.get("year") or 0)
        if year and year < 2024:
            lines.append("❌ <b>OTT:</b> Not currently available for streaming in your region.")
        else:
            lines.append("❌ <b>OTT:</b> Not yet released on any streaming platform.")

    lines.append("")
    if d.get("overview"):
        ov = d["overview"]
        if len(ov) > 600:
            ov = ov[:597] + "…"
        lines.append(f"📝 <i>{ov}</i>")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
#  Keyboard builders
# ═══════════════════════════════════════════════════════════════════════════════

def _day_keyboard(items: list[dict], for_date: date) -> InlineKeyboardMarkup:
    rows = []
    iso = for_date.isoformat()

    for item in items[:DAY_LIST_LIMIT]:
        t   = "m" if item["type"] == "movie" else "t"
        cb  = f"ott_it|{t}|{item['id']}|{iso}"       # max ~30 chars ✓
        lbl = f"{_icon(item['type'])} {item['title']}"
        if item.get("year"):
            lbl += f" ({item['year']})"
        if item.get("rating"):
            lbl += f" ⭐{item['rating']}"
        rows.append([InlineKeyboardButton(lbl[:60], callback_data=cb)])

    # navigation
    prev_iso = (for_date - timedelta(days=1)).isoformat()
    next_iso = (for_date + timedelta(days=1)).isoformat()
    rows.append([
        InlineKeyboardButton("⬅️ Prev Day", callback_data=f"ott_nav|{prev_iso}"),
        InlineKeyboardButton("Next Day ➡️", callback_data=f"ott_nav|{next_iso}"),
    ])
    return InlineKeyboardMarkup(rows)


def _detail_keyboard(item_type: str, item_id: int,
                     back_date: str = "", from_search: bool = False,
                     uid: int = 0) -> InlineKeyboardMarkup:
    t = "m" if item_type == "movie" else "t"
    rows = []
    if back_date:
        rows.append([InlineKeyboardButton(
            "⬅️ Back to List", callback_data=f"ott_nav|{back_date}"
        )])
    if from_search and uid:
        rows.append([InlineKeyboardButton(
            "🔙 Back to Search", callback_data=f"ott_sr|{uid}"
        )])
    rows.append([InlineKeyboardButton(
        "🔄 Refresh", callback_data=f"ott_pk|{t}|{item_id}|{'s' if from_search else 'd'}|{uid}"
    )])
    return InlineKeyboardMarkup(rows)


def _search_keyboard(uid: int, session: dict) -> InlineKeyboardMarkup:
    results  = session["results"]
    page     = session["page"]
    per_page = RESULTS_PER_PAGE
    start    = page * per_page
    end      = min(start + per_page, len(results))
    total_pg = max(1, -(-len(results) // per_page))   # ceiling division

    rows = []
    for item in results[start:end]:
        t   = "m" if item["type"] == "movie" else "t"
        cb  = f"ott_pk|{t}|{item['id']}|s|{uid}"
        lbl = f"{_icon(item['type'])} {item['title']} ({item['year']})"
        if item.get("rating"):
            lbl += f" ⭐{item['rating']}"
        rows.append([InlineKeyboardButton(lbl[:60], callback_data=cb)])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"ott_sp|{uid}|prev"))
    nav.append(InlineKeyboardButton(f"📄 {page+1}/{total_pg}", callback_data="ott_noop"))
    if end < len(results) or session.get("tmdb_page", 1) < session.get("tmdb_total", 1):
        nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"ott_sp|{uid}|next"))
    if nav:
        rows.append(nav)

    return InlineKeyboardMarkup(rows)


# ═══════════════════════════════════════════════════════════════════════════════
#  Shared send helpers
# ═══════════════════════════════════════════════════════════════════════════════

async def _send_day(client: Client, target, for_date: date, edit: bool):
    """Send or edit the day-release list message."""
    items = await fetch_day_releases(for_date)
    label = _fmt_date_label(for_date)

    mc = sum(1 for i in items if i["type"] == "movie")
    tc = sum(1 for i in items if i["type"] == "tv")

    if not items:
        text = f"{label}\n\n😔 No OTT releases found for this date."
    else:
        text = (
            f"{label}\n"
            f"🎬 {mc} Movies  ·  📺 {tc} Series\n\n"
            f"Tap a title for full details:"
        )

    kb = _day_keyboard(items, for_date)

    if edit:
        try:
            await target.edit_message_text(text, reply_markup=kb, parse_mode=enums.ParseMode.HTML)
        except Exception:
            await target.message.reply(text, reply_markup=kb, parse_mode=enums.ParseMode.HTML)
    else:
        await target.reply(text, reply_markup=kb, parse_mode=enums.ParseMode.HTML)


async def _send_detail(client: Client, target, detail: dict,
                       kb: InlineKeyboardMarkup, edit: bool):
    """Send detail as photo+caption if poster available, else plain text."""
    text = _format_detail_text(detail)

    if detail.get("poster"):
        try:
            if edit:
                # delete old message and send new photo
                try:
                    await target.message.delete()
                except Exception:
                    pass
                await client.send_photo(
                    target.message.chat.id,
                    photo=detail["poster"],
                    caption=text[:1024],
                    parse_mode=enums.ParseMode.HTML,
                    reply_markup=kb,
                )
            else:
                await target.reply_photo(
                    photo=detail["poster"],
                    caption=text[:1024],
                    parse_mode=enums.ParseMode.HTML,
                    reply_markup=kb,
                )
            return
        except Exception as exc:
            logger.warning(f"Photo send failed, falling back to text: {exc}")

    # fallback: text only
    if edit:
        try:
            await target.edit_message_text(text, reply_markup=kb, parse_mode=enums.ParseMode.HTML)
            return
        except Exception:
            pass
    await (target.message if hasattr(target, "message") else target).reply(
        text, reply_markup=kb, parse_mode=enums.ParseMode.HTML
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  COMMAND HANDLERS
# ═══════════════════════════════════════════════════════════════════════════════

@Client.on_message(filters.command("ott"))
async def cmd_ott(client: Client, message: Message):
    """/ott [DD-MM-YYYY]  — show OTT releases for a date (default: today)."""
    if not TMDB_API_KEY:
        await message.reply("❌ TMDB_API_KEY is not configured. Ask the admin to add it.")
        return

    args = message.command[1:]
    if args:
        for_date = _parse_user_date(args[0])
        if not for_date:
            await message.reply(
                "❌ <b>Invalid date format.</b>\n"
                "Use: <code>/ott DD-MM-YYYY</code>\n"
                "Example: <code>/ott 13-05-2025</code>",
                parse_mode=enums.ParseMode.HTML,
            )
            return
    else:
        for_date = date.today()

    loading = await message.reply("⏳ Fetching releases…")
    try:
        await _send_day(client, loading, for_date, edit=True)
    except Exception as exc:
        logger.error(f"cmd_ott error: {exc}")
        await loading.edit_text("❌ Something went wrong. Please try again.")


# ─── Channel management ───────────────────────────────────────────────────────

@Client.on_message(filters.command("setchannel") & filters.private)
async def cmd_set_channel(client: Client, message: Message):
    """
    /setchannel @username  or  /setchannel -100xxxxxxxxxx
    The bot must already be an admin of that channel/group.
    """
    args = message.command[1:]
    if not args:
        await message.reply(
            "📢 <b>Add Auto-Update Channel / Group</b>\n\n"
            "Usage:\n"
            "  <code>/setchannel @yourchannel</code>\n"
            "  <code>/setchannel -1001234567890</code>\n\n"
            "⚠️ The bot must be an <b>admin</b> of the channel/group first.",
            parse_mode=enums.ParseMode.HTML,
        )
        return

    target_id = args[0].strip()
    try:
        chat = await client.get_chat(target_id)
    except Exception as exc:
        await message.reply(f"❌ Cannot find that chat:\n<code>{exc}</code>", parse_mode=enums.ParseMode.HTML)
        return

    # Verify bot is an admin
    try:
        me     = await client.get_me()
        member = await client.get_chat_member(chat.id, me.id)
        if member.status not in (enums.ChatMemberStatus.ADMINISTRATOR,
                                 enums.ChatMemberStatus.OWNER):
            await message.reply(
                f"❌ I'm not an admin in <b>{chat.title}</b>.\n"
                "Please promote me as admin and try again.",
                parse_mode=enums.ParseMode.HTML,
            )
            return
    except Exception as exc:
        await message.reply(f"❌ Could not verify admin status:\n<code>{exc}</code>", parse_mode=enums.ParseMode.HTML)
        return

    added = await add_subscriber(chat.id, username=chat.username or "")
    await set_auto_send(chat.id, True)
    verb = "added" if added else "already registered"

    await message.reply(
        f"✅ <b>{chat.title}</b> has been {verb} for auto-updates.\n"
        f"🆔 Chat ID: <code>{chat.id}</code>",
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command("removechannel") & filters.private)
async def cmd_remove_channel(client: Client, message: Message):
    """/removechannel @username  or  /removechannel -100xxxxxxxxxx"""
    args = message.command[1:]
    if not args:
        await message.reply(
            "Usage: <code>/removechannel @yourchannel</code>",
            parse_mode=enums.ParseMode.HTML,
        )
        return

    target_id = args[0].strip()
    try:
        chat = await client.get_chat(target_id)
    except Exception as exc:
        await message.reply(f"❌ Cannot find that chat:\n<code>{exc}</code>", parse_mode=enums.ParseMode.HTML)
        return

    removed = await remove_subscriber(chat.id)
    if removed:
        await message.reply(
            f"✅ <b>{chat.title}</b> removed from auto-update targets.",
            parse_mode=enums.ParseMode.HTML,
        )
    else:
        await message.reply(
            f"ℹ️ <b>{chat.title}</b> was not in the list.",
            parse_mode=enums.ParseMode.HTML,
        )


@Client.on_message(filters.command("mychannels") & filters.private)
async def cmd_my_channels(client: Client, message: Message):
    """List all registered auto-update channels/groups."""
    from database import get_auto_send_subscribers
    ids = await get_auto_send_subscribers()
    if not ids:
        await message.reply("📭 No channels or groups registered for auto-updates yet.")
        return
    lines = ["📢 <b>Registered Auto-Update Targets:</b>\n"]
    for cid in ids:
        try:
            chat = await client.get_chat(cid)
            handle = f"@{chat.username}" if chat.username else f"ID: <code>{cid}</code>"
            lines.append(f"• {chat.title}  ({handle})")
        except Exception:
            lines.append(f"• Unknown  (<code>{cid}</code>)")
    lines.append(f"\nTotal: {len(ids)}")
    await message.reply("\n".join(lines), parse_mode=enums.ParseMode.HTML)


# ─── PM text → movie/series search ───────────────────────────────────────────

# All commands that should NOT trigger the search handler
_CMD_LIST = [
    "ott", "start", "help", "subscribe", "unsubscribe", "latest",
    "platforms", "stats", "about", "setchannel", "removechannel", "mychannels",
]

@Client.on_message(
    filters.private
    & filters.text
    & ~filters.command(_CMD_LIST)
)
async def pm_search(client: Client, message: Message):
    """Any PM text → search TMDB and show paginated results."""
    if not TMDB_API_KEY:
        return

    query_str = message.text.strip()
    if len(query_str) < 2:
        return

    loading = await message.reply(f"🔍 Searching for <b>{query_str}</b>…", parse_mode=enums.ParseMode.HTML)

    results, total_pages = await search_tmdb(query_str, page=1)

    if not results:
        await loading.edit_text(
            f"❌ No results found for <b>{query_str}</b>.\n"
            "Try a different spelling or include the release year.",
            parse_mode=enums.ParseMode.HTML,
        )
        return

    uid = message.from_user.id
    _sessions[uid] = {
        "query":      query_str,
        "results":    results,
        "page":       0,
        "tmdb_page":  1,
        "tmdb_total": total_pages,
    }

    text, kb = _build_search_msg(uid)
    await loading.edit_text(text, reply_markup=kb, parse_mode=enums.ParseMode.HTML)


def _build_search_msg(uid: int) -> tuple[str, InlineKeyboardMarkup]:
    session  = _sessions[uid]
    q        = session["query"]
    total    = len(session["results"])
    page     = session["page"]
    start    = page * RESULTS_PER_PAGE
    end      = min(start + RESULTS_PER_PAGE, total)
    text = (
        f"🔍 <b>Results for:</b>  <code>{q}</code>\n"
        f"Showing <b>{start+1}–{end}</b> of {total}+ results\n\n"
        f"Tap a title to see OTT info:"
    )
    return text, _search_keyboard(uid, session)


# ═══════════════════════════════════════════════════════════════════════════════
#  CALLBACK QUERY HANDLERS
# ═══════════════════════════════════════════════════════════════════════════════

@Client.on_callback_query(filters.regex(r"^ott_nav\|"))
async def cb_nav(client: Client, query: CallbackQuery):
    """Navigate to a different day's list."""
    iso = query.data.split("|", 1)[1]
    try:
        for_date = date.fromisoformat(iso)
    except ValueError:
        await query.answer("❌ Invalid date.", show_alert=True)
        return
    await query.answer()
    await _send_day(client, query, for_date, edit=True)


@Client.on_callback_query(filters.regex(r"^ott_it\|"))
async def cb_item(client: Client, query: CallbackQuery):
    """Show detail for an item from the day list."""
    # format: ott_it|{type}|{id}|{back_iso}
    parts = query.data.split("|")
    t, item_id_s, back_iso = parts[1], parts[2], parts[3]
    item_type = "movie" if t == "m" else "tv"

    await query.answer("⏳ Loading…")
    detail = await fetch_detail(item_type, int(item_id_s))
    if not detail:
        await query.answer("❌ Failed to fetch details.", show_alert=True)
        return

    kb = _detail_keyboard(item_type, detail["id"], back_date=back_iso)
    await _send_detail(client, query, detail, kb, edit=True)


@Client.on_callback_query(filters.regex(r"^ott_pk\|"))
async def cb_pick(client: Client, query: CallbackQuery):
    """User picked an item from search results, or Refresh was tapped."""
    # format: ott_pk|{type}|{id}|{source: s=search/d=day}|{uid}
    parts = query.data.split("|")
    t, item_id_s = parts[1], parts[2]
    source = parts[3] if len(parts) > 3 else "d"
    uid    = int(parts[4]) if len(parts) > 4 else query.from_user.id

    item_type = "movie" if t == "m" else "tv"

    await query.answer("⏳ Loading…")
    detail = await fetch_detail(item_type, int(item_id_s))
    if not detail:
        await query.answer("❌ Failed to fetch details.", show_alert=True)
        return

    from_search = (source == "s")
    kb = _detail_keyboard(item_type, detail["id"], from_search=from_search, uid=uid)
    await _send_detail(client, query, detail, kb, edit=True)


@Client.on_callback_query(filters.regex(r"^ott_sr\|"))
async def cb_search_restore(client: Client, query: CallbackQuery):
    """Back to Search — restore previous results page."""
    uid = int(query.data.split("|", 1)[1])
    session = _sessions.get(uid)
    if not session:
        await query.answer("⏳ Session expired. Please search again.", show_alert=True)
        return
    await query.answer()
    text, kb = _build_search_msg(uid)
    await query.edit_message_text(text, reply_markup=kb, parse_mode=enums.ParseMode.HTML)


@Client.on_callback_query(filters.regex(r"^ott_sp\|"))
async def cb_search_page(client: Client, query: CallbackQuery):
    """Paginate through search results (next / prev)."""
    # format: ott_sp|{uid}|{next|prev}
    parts     = query.data.split("|")
    uid       = int(parts[1])
    direction = parts[2]

    session = _sessions.get(uid)
    if not session:
        await query.answer("⏳ Session expired. Please search again.", show_alert=True)
        return

    results  = session["results"]
    cur_page = session["page"]
    max_local_page = max(0, -(-len(results) // RESULTS_PER_PAGE) - 1)  # last full page

    if direction == "next":
        new_page = cur_page + 1
        # If we've exhausted local results, fetch the next TMDB page
        if new_page * RESULTS_PER_PAGE >= len(results):
            next_tmdb = session["tmdb_page"] + 1
            if next_tmdb <= session["tmdb_total"]:
                await query.answer("⏳ Loading more…")
                more, _ = await search_tmdb(session["query"], page=next_tmdb)
                if more:
                    session["results"].extend(more)
                    session["tmdb_page"] = next_tmdb
            else:
                await query.answer("No more results.", show_alert=False)
                return
        session["page"] = min(new_page, -(-len(session["results"]) // RESULTS_PER_PAGE) - 1)

    elif direction == "prev":
        if cur_page == 0:
            await query.answer()
            return
        session["page"] = cur_page - 1

    await query.answer()
    text, kb = _build_search_msg(uid)
    try:
        await query.edit_message_text(text, reply_markup=kb, parse_mode=enums.ParseMode.HTML)
    except Exception:
        pass  # no change in text is fine


@Client.on_callback_query(filters.regex(r"^ott_noop$"))
async def cb_noop(client: Client, query: CallbackQuery):
    """Page-indicator button — does nothing."""
    await query.answer()
