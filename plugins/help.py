from pyrogram import Client, filters
from pyrogram.types import Message

HELP_TEXT = (
    "🎬 **OTT Updates Bot — Help**\n\n"
    "**User commands**\n"
    "/start — welcome message\n"
    "/subscribe — subscribe to automatic OTT updates\n"
    "/unsubscribe — unsubscribe\n"
    "/latest — manually fetch the latest new releases\n"
    "/platforms — list supported streaming services\n"
    "/stats — show bot uptime & subscriber count\n"
    "/about — data sources & credits\n"
    "/help — show this message\n\n"
    "**Admin commands** _(set ADMIN\\_ID in .env)_\n"
    "/broadcast `<message>` — send a message to all subscribers\n"
    "/sendnow — force an immediate update check"
)


@Client.on_message(filters.command("help"))
async def help_cmd(client: Client, message: Message):
    await message.reply_text(HELP_TEXT)
