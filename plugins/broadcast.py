import asyncio
import logging

from pyrogram import Client, filters
from pyrogram.types import Message

from config import ADMIN_ID
from database import get_subscribers

logger = logging.getLogger("OTTBot.broadcast")


def _is_admin(_, __, message: Message) -> bool:
    if not ADMIN_ID:
        return False
    try:
        return message.from_user and message.from_user.id == int(ADMIN_ID)
    except (ValueError, TypeError):
        return False


admin_filter = filters.create(_is_admin)


@Client.on_message(filters.command("broadcast") & admin_filter)
async def broadcast(client: Client, message: Message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.reply_text("Usage: /broadcast `<message>`\n\nExample:\n/broadcast Netflix just dropped something big! 🔥")
        return

    msg_text = parts[1]
    subs = get_subscribers()

    if not subs:
        await message.reply_text("⚠️ No subscribers to broadcast to.")
        return

    status = await message.reply_text(f"📢 Broadcasting to {len(subs)} subscriber(s)…")

    success, failed = 0, 0
    for cid in subs:
        try:
            await client.send_message(
                cid,
                f"📢 **Announcement**\n\n{msg_text}",
                disable_web_page_preview=True,
            )
            success += 1
            await asyncio.sleep(0.05)   # ~20 msg/s — within Telegram limits
        except Exception as exc:
            failed += 1
            logger.warning(f"Broadcast failed → {cid}: {exc}")

    await status.edit_text(
        f"✅ Broadcast complete.\n\n"
        f"• Delivered: **{success}**\n"
        f"• Failed: **{failed}**"
    )


@Client.on_message(filters.command("sendnow") & admin_filter)
async def sendnow(client: Client, message: Message):
    """Force an immediate update check (admin only)."""
    from utils import get_new_releases, format_item_message
    from config import CHAT_ID

    status = await message.reply_text("⚡ Forcing update check now…")
    items = await get_new_releases(days_back=7)

    if not items:
        await status.edit_text("No new releases found right now.")
        return

    chat_ids: set[int] = set()
    if CHAT_ID:
        for cid in str(CHAT_ID).split(","):
            cid = cid.strip()
            if cid:
                chat_ids.add(int(cid))
    else:
        chat_ids.update(get_subscribers())

    sent = 0
    for cid in chat_ids:
        for item in items:
            try:
                await client.send_message(cid, format_item_message(item), disable_web_page_preview=False)
                sent += 1
                await asyncio.sleep(0.5)
            except Exception as exc:
                logger.warning(f"sendnow failed → {cid}: {exc}")

    await status.edit_text(f"✅ Sent **{sent}** message(s) to **{len(chat_ids)}** chat(s).")
