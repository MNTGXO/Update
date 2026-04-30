from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery
from config import CHAT_ID
from database import remove_subscriber, is_subscriber


@Client.on_message(filters.command("unsubscribe"))
async def unsubscribe_cmd(client: Client, message: Message):
    await _unsubscribe(client, message.chat.id, reply=message.reply_text)


@Client.on_callback_query(filters.regex("^unsubscribe$"))
async def unsubscribe_cb(client: Client, cb: CallbackQuery):
    await cb.answer()
    await _unsubscribe(client, cb.message.chat.id, reply=cb.message.reply_text)


async def _unsubscribe(client, chat_id: int, reply):
    if CHAT_ID:
        await reply("ℹ️ This bot broadcasts to a fixed channel. Individual subscriptions are disabled.")
        return
    if not is_subscriber(chat_id):
        await reply("ℹ️ You are not subscribed.")
        return
    remove_subscriber(chat_id)
    await reply(
        "❌ **Unsubscribed.**\n\n"
        "You won't receive automatic updates anymore.\n"
        "Use /subscribe to re-enable at any time."
    )
