from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery
from config import CHAT_ID
from database import add_subscriber, is_subscriber


@Client.on_message(filters.command("subscribe"))
async def subscribe_cmd(client: Client, message: Message):
    await _subscribe(client, message.chat.id, message.from_user, reply=message.reply_text)


@Client.on_callback_query(filters.regex("^subscribe$"))
async def subscribe_cb(client: Client, cb: CallbackQuery):
    await cb.answer()
    await _subscribe(client, cb.message.chat.id, cb.from_user, reply=cb.message.reply_text)


async def _subscribe(client, chat_id: int, user, reply):
    if CHAT_ID:
        await reply("ℹ️ This bot broadcasts to a fixed channel. Individual subscriptions are disabled.")
        return
    username = getattr(user, "username", "") or ""
    if is_subscriber(chat_id):
        await reply("✅ You're already subscribed! You'll receive updates automatically.")
        return
    add_subscriber(chat_id, username)
    await reply(
        "✅ **Subscribed!**\n\n"
        "You'll receive notifications when new movies or shows are available on OTT platforms.\n\n"
        "Use /unsubscribe to stop at any time."
    )
