import logging
import secrets
import time

from pyrogram import Client, filters, enums
from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from utils import get_new_releases, format_item_message, format_item_keyboard

logger = logging.getLogger("OTTBot.latest")

_PAGE_SIZE = 10
_SESSION_TTL = 15 * 60
_latest_sessions: dict[str, dict] = {}


def _prune_sessions() -> None:
    now = time.time()
    stale = [k for k, v in _latest_sessions.items() if v.get("exp", 0) < now]
    for key in stale:
        _latest_sessions.pop(key, None)


def _build_latest_keyboard(session_key: str, page: int) -> InlineKeyboardMarkup:
    session = _latest_sessions[session_key]
    items = session["items"]
    total = len(items)
    total_pages = max(1, -(-total // _PAGE_SIZE))
    page = max(0, min(page, total_pages - 1))

    start = page * _PAGE_SIZE
    end = min(start + _PAGE_SIZE, total)

    rows = []
    for idx in range(start, end):
        item = items[idx]
        kind = "🎬" if item.get("type") == "movie" else "📺"
        rows.append([
            InlineKeyboardButton(
                f"{kind} {item.get('title', 'Unknown')[:42]}",
                callback_data=f"latest_it|{session_key}|{idx}",
            )
        ])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"latest_pg|{session_key}|{page-1}"))
    nav.append(InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="latest_noop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"latest_pg|{session_key}|{page+1}"))
    rows.append(nav)

    return InlineKeyboardMarkup(rows)


def _build_latest_text(items: list[dict], page: int) -> str:
    total = len(items)
    start = page * _PAGE_SIZE
    end = min(start + _PAGE_SIZE, total)
    return (
        "🍿 <b>Latest OTT Releases</b>\n"
        f"Showing <b>{start+1}-{end}</b> of <b>{total}</b>.\n\n"
        "Tap a movie/series to view full information:"
    )


@Client.on_message(filters.command("latest"))
async def latest_cmd(client: Client, message: Message):
    await _latest(client, message.chat.id, message.reply_text)


@Client.on_message(filters.private & filters.regex(r"(?i)^latest$"))
async def latest_text_trigger(client: Client, message: Message):
    await _latest(client, message.chat.id, message.reply_text)


@Client.on_callback_query(filters.regex("^latest$"))
async def latest_cb(client: Client, cb: CallbackQuery):
    await cb.answer("Checking for new releases…")
    await _latest(client, cb.message.chat.id, cb.message.reply_text)


async def _latest(client: Client, chat_id: int, reply_fn):
    status = await reply_fn("🔍 Fetching latest OTT releases…")
    _prune_sessions()

    try:
        items = await get_new_releases(days_back=7, dedup=False)
    except Exception as exc:
        logger.error(f"/latest error: {exc}", exc_info=True)
        await status.edit_text("❌ Could not fetch releases. Please try again later.")
        return

    if not items:
        await status.edit_text(
            "😔 <b>No new OTT releases found in the last 7 days.</b>\n\n"
            "Everything recent has already been sent, or there's nothing new yet.\n"
            'Check <a href="https://www.justwatch.com">JustWatch</a> directly for more.',
            parse_mode=enums.ParseMode.HTML,
            disable_web_page_preview=True,
        )
        return

    session_key = secrets.token_hex(4)
    _latest_sessions[session_key] = {
        "items": items,
        "exp": time.time() + _SESSION_TTL,
    }

    await status.edit_text(
        _build_latest_text(items, 0),
        parse_mode=enums.ParseMode.HTML,
        reply_markup=_build_latest_keyboard(session_key, 0),
    )


@Client.on_callback_query(filters.regex(r"^latest_pg\|"))
async def latest_page_cb(client: Client, cb: CallbackQuery):
    _, session_key, page_s = cb.data.split("|")
    session = _latest_sessions.get(session_key)
    if not session:
        await cb.answer("Session expired. Send latest again.", show_alert=True)
        return

    page = int(page_s)
    await cb.answer()
    await cb.edit_message_text(
        _build_latest_text(session["items"], page),
        parse_mode=enums.ParseMode.HTML,
        reply_markup=_build_latest_keyboard(session_key, page),
    )


@Client.on_callback_query(filters.regex(r"^latest_it\|"))
async def latest_item_cb(client: Client, cb: CallbackQuery):
    _, session_key, idx_s = cb.data.split("|")
    session = _latest_sessions.get(session_key)
    if not session:
        await cb.answer("Session expired. Send latest again.", show_alert=True)
        return

    idx = int(idx_s)
    items = session["items"]
    if idx < 0 or idx >= len(items):
        await cb.answer("Invalid selection.", show_alert=True)
        return

    item = items[idx]
    text = format_item_message(item)
    await cb.answer("Loading details…")
    await cb.message.reply_text(
        text,
        parse_mode=enums.ParseMode.HTML,
        disable_web_page_preview=False,
        reply_markup=format_item_keyboard(item),
    )


@Client.on_callback_query(filters.regex(r"^latest_noop$"))
async def latest_noop_cb(client: Client, cb: CallbackQuery):
    await cb.answer()
