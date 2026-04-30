from pyrogram import Client, filters, enums
from pyrogram.types import Message, CallbackQuery
from config import CHAT_ID
from database import add_subscriber, is_subscriber


@Client.on_message(filters.command("subscribe"))
async def subscribe_cmd(client: Client, message: Message):
    user = message.from_user
    await _subscribe(message.chat.id,
                     getattr(user, "username", "") or "",
                     message.reply_text)


@Client.on_callback_query(filters.regex("^subscribe$"))
async def subscribe_cb(client: Client, cb: CallbackQuery):
    await cb.answer()
    user = cb.from_user
    await _subscribe(cb.message.chat.id,
                     getattr(user, "username", "") or "",
                     cb.message.reply_text)


async def _subscribe(chat_id: int, username: str, reply_fn):
    if CHAT_ID:
        await reply_fn(
            "ℹ️ This bot is in channel-broadcast mode.\n"
            "Individual subscriptions are disabled.",
            parse_mode=enums.ParseMode.HTML,
        )
        return
    if await is_subscriber(chat_id):
        await reply_fn(
            "✅ You're <b>already subscribed!</b>\n"
            "You'll receive updates automatically.\n\n"
            "Use /unsubscribe to stop.",
            parse_mode=enums.ParseMode.HTML,
        )
        return
    await add_subscriber(chat_id, username)
    await reply_fn(
        "✅ <b>Subscribed!</b>\n\n"
        "You'll be notified whenever new content lands on OTT platforms.\n\n"
        "Use /unsubscribe to stop at any time.",
        parse_mode=enums.ParseMode.HTML,
    )
