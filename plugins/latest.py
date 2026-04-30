import asyncio
import logging

from pyrogram import Client, filters, enums
from pyrogram.types import Message, CallbackQuery

from utils import get_new_releases, format_item_message, format_item_keyboard

logger = logging.getLogger("OTTBot.latest")


@Client.on_message(filters.command("latest"))
async def latest_cmd(client: Client, message: Message):
    await _latest(client, message.chat.id, message.reply_text)


@Client.on_callback_query(filters.regex("^latest$"))
async def latest_cb(client: Client, cb: CallbackQuery):
    await cb.answer("Checking for new releases…")
    await _latest(client, cb.message.chat.id, cb.message.reply_text)


async def _latest(client: Client, chat_id: int, reply_fn):
    status = await reply_fn("🔍 Fetching latest OTT releases…")

    try:
        items = await get_new_releases(days_back=7)
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

    await status.delete()

    sent = 0
    for item in items[:10]:   # max 10 per manual fetch
        try:
            text   = format_item_message(item)
            poster = item.get("poster", "")
            if poster:
                try:
                    await client.send_photo(chat_id, poster, caption=text,
                                            parse_mode=enums.ParseMode.HTML,
                                            reply_markup=format_item_keyboard(item))
                except Exception:
                    await client.send_message(chat_id, text,
                                              parse_mode=enums.ParseMode.HTML,
                                              disable_web_page_preview=False,
                                              reply_markup=format_item_keyboard(item))
            else:
                await client.send_message(chat_id, text,
                                          parse_mode=enums.ParseMode.HTML,
                                          disable_web_page_preview=False,
                                          reply_markup=format_item_keyboard(item))
            sent += 1
            await asyncio.sleep(0.6)
        except Exception as exc:
            logger.warning(f"Failed to send item: {exc}")

    await client.send_message(
        chat_id,
        f"✅ Done! Showing <b>{sent}</b> new release(s) from the last 7 days.",
        parse_mode=enums.ParseMode.HTML,
    )
