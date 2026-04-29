from pyrogram import Client, filters
from pyrogram.types import Message
import asyncio
from config import ADMIN_ID
from database import get_subscribers

@Client.on_message(filters.command("broadcast") & filters.user(int(ADMIN_ID)) if ADMIN_ID else filters.command("broadcast"))
async def broadcast(client: Client, message: Message):
    if not ADMIN_ID:
        await message.reply_text("Admin not configured.")
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.reply_text("Usage: /broadcast <message>")
        return
    msg_text = parts[1]
    subs = get_subscribers()
    if not subs:
        await message.reply_text("No subscribers.")
        return
    success = 0
    for cid in subs:
        try:
            await client.send_message(cid, f"📢 *Announcement*\n\n{msg_text}", parse_mode="Markdown")
            success += 1
            await asyncio.sleep(0.1)
        except Exception as e:
            print(f"Failed to send to {cid}: {e}")
    await message.reply_text(f"Sent to {success}/{len(subs)} subscribers.")
