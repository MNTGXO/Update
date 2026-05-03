import asyncio
import logging

from pyrogram import Client, filters, enums
from pyrogram.types import Message

from config import ADMIN_ID, CHAT_ID
from database import get_subscribers
from utils import get_new_releases, format_item_message, format_item_keyboard

logger = logging.getLogger("OTTBot.broadcast")


# ─── Admin filter ────────────────────────────────────────────────────────────

def _is_admin(_, __, message: Message) -> bool:
    if not ADMIN_ID:
        return False
    try:
        return bool(message.from_user and message.from_user.id == int(ADMIN_ID))
    except (ValueError, TypeError):
        return False


admin_only = filters.create(_is_admin)


# ─── /broadcast ───────────────────────────────────────────────────────────────

@Client.on_message(filters.command("broadcast") & admin_only)
async def broadcast(client: Client, message: Message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.reply_text(
            "Usage: /broadcast <code>&lt;message&gt;</code>\n\n"
            "Example:\n<code>/broadcast Netflix just dropped something big! 🔥</code>",
            parse_mode=enums.ParseMode.HTML,
        )
        return

    msg_text = parts[1]
    subs = await get_subscribers()
    if not subs:
        await message.reply_text("⚠️ No subscribers to broadcast to.")
        return

    status = await message.reply_text(f"📢 Broadcasting to <b>{len(subs)}</b> subscriber(s)…",
                                      parse_mode=enums.ParseMode.HTML)
    success = failed = 0
    for cid in subs:
        try:
            await client.send_message(
                cid,
                f"📢 <b>Announcement</b>\n\n{msg_text}",
                parse_mode=enums.ParseMode.HTML,
                disable_web_page_preview=True,
            )
            success += 1
            await asyncio.sleep(0.05)
        except Exception as exc:
            failed += 1
            logger.warning(f"Broadcast failed → {cid}: {exc}")

    await status.edit_text(
        f"✅ <b>Broadcast complete.</b>\n\n"
        f"• Delivered: <b>{success}</b>\n"
        f"• Failed:    <b>{failed}</b>",
        parse_mode=enums.ParseMode.HTML,
    )


# ─── /sendnow ─────────────────────────────────────────────────────────────────

@Client.on_message(filters.command("sendnow") & admin_only)
async def sendnow(client: Client, message: Message):
    status = await message.reply_text("⚡ Forcing update check now…")
    items  = await get_new_releases(days_back=7)

    if not items:
        await status.edit_text("ℹ️ No new releases found right now.")
        return

    chat_ids: set[int | str] = set()
    if CHAT_ID:
        for raw in str(CHAT_ID).split(","):
            cid = raw.strip()
            if not cid:
                continue
            if cid.startswith("@"):
                chat_ids.add(cid)
                continue
            try:
                chat_ids.add(int(cid))
            except ValueError:
                logger.warning(f"Invalid CHAT_ID value skipped: {cid}")

    chat_ids.update(await get_subscribers())

    if not chat_ids:
        await status.edit_text("⚠️ No subscribers or CHAT_ID configured.")
        return

    sent = 0
    for cid in chat_ids:
        for item in items:
            try:
                text   = format_item_message(item)
                poster = item.get("poster", "")
                if poster:
                    try:
                        await client.send_photo(cid, poster, caption=text,
                                                parse_mode=enums.ParseMode.HTML,
                                                reply_markup=format_item_keyboard(item))
                    except Exception:
                        await client.send_message(cid, text,
                                                  parse_mode=enums.ParseMode.HTML,
                                                  reply_markup=format_item_keyboard(item))
                else:
                    await client.send_message(cid, text,
                                              parse_mode=enums.ParseMode.HTML,
                                              reply_markup=format_item_keyboard(item))
                sent += 1
                await asyncio.sleep(0.5)
            except Exception as exc:
                logger.warning(f"sendnow failed → {cid}: {exc}")

    await status.edit_text(
        f"✅ Sent <b>{sent}</b> message(s) to <b>{len(chat_ids)}</b> chat(s).",
        parse_mode=enums.ParseMode.HTML,
    )
