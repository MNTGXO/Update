import asyncio
import logging

from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery

from utils import get_new_releases, format_item_message

logger = logging.getLogger("OTTBot.latest")


@Client.on_message(filters.command("latest"))
async def latest_cmd(client: Client, message: Message):
    await _latest(client, message.chat.id, reply=message.reply_text)


@Client.on_callback_query(filters.regex("^latest$"))
async def latest_cb(client: Client, cb: CallbackQuery):
    await cb.answer("Checking for new releases…")
    await _latest(client, cb.message.chat.id, reply=cb.message.reply_text)


async def _latest(client, chat_id: int, reply):
    status = await reply("🔍 Fetching latest OTT releases…")

    try:
        items = await get_new_releases(days_back=7)
    except Exception as exc:
        logger.error(f"/latest error: {exc}", exc_info=True)
        await status.edit_text("❌ Could not fetch releases. Please try again later.")
        return

    if not items:
        await status.edit_text(
            "😔 No new OTT releases found in the last 7 days.\n\n"
            "Try again later or check [JustWatch](https://www.justwatch.com) directly.",
            disable_web_page_preview=True,
        )
        return

    await status.delete()

    sent = 0
    for item in items[:10]:   # Cap at 10 items per manual check
        try:
            text = format_item_message(item)
            poster_url = item.get("poster", "")
            if poster_url:
                try:
                    await client.send_photo(chat_id, poster_url, caption=text)
                except Exception:
                    await client.send_message(chat_id, text, disable_web_page_preview=False)
            else:
                await client.send_message(chat_id, text, disable_web_page_preview=False)
            sent += 1
            await asyncio.sleep(0.6)
        except Exception as exc:
            logger.warning(f"Failed to send item: {exc}")

    await client.send_message(
        chat_id,
        f"✅ Done! Showing **{sent}** new release(s) from the last 7 days.",
    )
