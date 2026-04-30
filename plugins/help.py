from pyrogram import Client, filters, enums
from pyrogram.types import Message

HELP = (
    "🎬 <b>OTT Updates Bot — Help</b>\n\n"
    "<b>User commands</b>\n"
    "/start — welcome + quick buttons\n"
    "/subscribe — subscribe to auto OTT updates\n"
    "/unsubscribe — unsubscribe\n"
    "/latest — fetch latest new releases now\n"
    "/platforms — list supported streaming services\n"
    "/stats — uptime &amp; subscriber count\n"
    "/about — data sources &amp; credits\n"
    "/help — this message\n\n"
    "<b>Admin commands</b> <i>(requires ADMIN_ID in .env)</i>\n"
    "/broadcast &lt;message&gt; — send to all subscribers\n"
    "/sendnow — force an immediate update check"
)


@Client.on_message(filters.command("help"))
async def help_cmd(client: Client, message: Message):
    await message.reply_text(HELP, parse_mode=enums.ParseMode.HTML)
