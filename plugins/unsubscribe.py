from pyrogram import Client, filters, enums
from pyrogram.types import Message, CallbackQuery
from database import remove_subscriber, is_subscriber


@Client.on_message(filters.command("unsubscribe"))
async def unsubscribe_cmd(client: Client, message: Message):
    await _unsubscribe(message.chat.id, message.reply_text)


@Client.on_callback_query(filters.regex("^unsubscribe$"))
async def unsubscribe_cb(client: Client, cb: CallbackQuery):
    await cb.answer()
    await _unsubscribe(cb.message.chat.id, cb.message.reply_text)


async def _unsubscribe(chat_id: int, reply_fn):
    if not await is_subscriber(chat_id):
        await reply_fn(
            "ℹ️ You are <b>not subscribed</b>.\n"
            "Use /subscribe to start.",
            parse_mode=enums.ParseMode.HTML,
        )
        return
    await remove_subscriber(chat_id)
    await reply_fn(
        "❌ <b>Unsubscribed.</b>\n\n"
        "You won't receive automatic updates anymore.\n"
        "Use /subscribe to re-enable at any time.",
        parse_mode=enums.ParseMode.HTML,
    )
