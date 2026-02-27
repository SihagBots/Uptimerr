# ---------------------------------------------------
# File Name: commands.py
# Author: MyselfNeon
# GitHub: https://github.com/MyselfNeon/
# Telegram: https://t.me/MyelfNeon
# ---------------------------------------------------

from datetime import datetime
import asyncio

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, BotCommand

from .db import db
from info import ADMIN


def _admin_ids():
    return ADMIN if isinstance(ADMIN, list) else [ADMIN]


def _format_last_check(ts):
    if not ts:
        return "Not checked yet"
    dt = datetime.fromtimestamp(ts)
    return dt.strftime("%d %b %I:%M %p").replace("AM", "am").replace("PM", "pm")


def _normalize_name(name, url):
    cleaned = (name or "").strip()
    if cleaned:
        return cleaned
    return url


def _parse_add_args(command):
    """Supports both:
    1) /add <url> <name>
    2) /add <name> <url>
    """
    if len(command) < 3:
        return None, None

    arg1 = command[1].strip()
    arg2_plus = " ".join(command[2:]).strip()

    if arg1.startswith(("http://", "https://")):
        return arg1, arg2_plus

    last = command[-1].strip()
    if last.startswith(("http://", "https://")):
        return last, " ".join(command[1:-1]).strip()

    return None, None


async def get_dashboard(user_id, page=1, owner_id=None):
    limit = 6
    owner_id = owner_id or user_id
    urls, total_count = await db.get_urls_paginated(owner_id, page, limit)

    if not urls and page == 1:
        return "📂 **__List is Empty!__**\n__Use__ `/add https://site.com MySite` __to start.__", None

    latest_check = max((item.get("last_checked", 0) for item in urls), default=0)
    text = (
        "⏰ **UpTimer Bot**\n"
        f"🕒 **Last check:** `{_format_last_check(latest_check)}`\n"
        f"📦 **Total Monitors:** `{total_count}`\n\n"
    )

    status_map = {
        "ONLINE": "🟢 Active ✅",
        "SLOW": "🟡 Slow Response",
        "DOWN": "🔴 Down ❌",
        "PAUSED": "⛔ Paused",
        "PENDING": "⏳ Pending",
        "RATE-LIMITED": "⚠️ Rate Limited",
    }

    for data in urls:
        status = data.get("status", "PENDING")
        display_name = _normalize_name(data.get("name"), data.get("url"))
        if not display_name.startswith("@") and display_name.replace("_", "").isalnum() and " " not in display_name:
            bot_label = f"@{display_name}"
        else:
            bot_label = display_name

        resp = data.get("response_time", 0)
        status_text = status_map.get(status, f"❓ {status}")

        text += (
            f"╰┈➤ **Bot :** {bot_label}\n"
            f"╰┈➤ **Ping :** {resp} ms\n"
            f"╰┈➤ **Status :** {status_text}.\n\n"
        )

    buttons = []
    nav_row = []

    if page > 1:
        nav_row.append(InlineKeyboardButton("⬅️", callback_data=f"list_page_{page-1}_{owner_id}"))

    nav_row.append(InlineKeyboardButton("🔄 Refresh", callback_data=f"force_refresh_{page}_{owner_id}"))

    if (page * limit) < total_count:
        nav_row.append(InlineKeyboardButton("➡️", callback_data=f"list_page_{page+1}_{owner_id}"))

    if nav_row:
        buttons.append(nav_row)

    return text, InlineKeyboardMarkup(buttons)


@Client.on_message(filters.command("start") & filters.private)
async def start_cmd(client, message):
    text = (
        "👋 **__Professional Uptime Monitor__**\n\n"
        "**__Commands:__**\n"
        "__/add {url} {name} – Add monitor__\n"
        "__/del {url} – Remove monitor__\n"
        "__/list – Show dashboard__\n"
        "__/add_channel {channel_id} – Send admin dashboard to channel__"
    )
    await message.reply_text(text)


@Client.on_message(filters.command("add") & filters.private)
async def add_cmd(client, message):
    url, name = _parse_add_args(message.command)
    if not url:
        return await message.reply_text(
            "⚠️ **__Usage:__**\n"
            "`/add https://google.com Google`\n"
            "`/add Google https://google.com`"
        )

    user_id = message.chat.id
    name = _normalize_name(name, url)

    _, total_count = await db.get_urls_paginated(user_id, 1, 1)
    if user_id not in _admin_ids() and total_count >= 5:
        return await message.reply_text(
            "⛔️ **__Limit Reached!__**\n\n"
            "__Free users are limited to 5 URLs.__\n"
            "__Please remove a URL or contact Admin.__"
        )

    if await db.is_url_exist(user_id, url):
        return await message.reply_text("⚠️ **__URL already exists.__**")

    success, msg = await db.add_url(user_id, url, name)
    if success:
        await message.reply_text(
            f"✅ **__Added:__** __{name}__\n"
            f"🔗 **__URL Saved:__** `{url}`\n"
            "**__State: Pending__**"
        )
    else:
        await message.reply_text(f"❌ **__Error:__** __{msg}__")


@Client.on_message(filters.command("add_channel") & filters.private & filters.user(ADMIN))
async def add_channel_cmd(client, message):
    if len(message.command) < 2:
        return await message.reply_text("⚠️ **__Usage:** /add_channel -1001234567890__")

    try:
        channel_id = int(message.command[1].strip())
    except ValueError:
        return await message.reply_text("❌ **__Invalid channel id.__**")

    await db.set_dashboard_channel(message.chat.id, channel_id)
    await message.reply_text(f"✅ **__Channel saved:__** `{channel_id}`")


@Client.on_message(filters.command("del") & filters.private)
async def del_cmd(client, message):
    if len(message.command) < 2:
        return await message.reply_text("⚠️ **__Usage:** /del https://google.com__")

    await db.remove_url(message.chat.id, message.command[1])
    await message.reply_text("🗑 **__URL Deleted.__**")


@Client.on_message(filters.command(["list", "check", "stats"]) & filters.private)
async def list_cmd(client, message):
    owner_id = message.chat.id
    text, markup = await get_dashboard(owner_id, 1, owner_id)
    await message.reply_text(text, reply_markup=markup, disable_web_page_preview=True)

    if owner_id in _admin_ids():
        channel_id = await db.get_dashboard_channel(owner_id)
        if channel_id:
            try:
                await client.send_message(channel_id, text, reply_markup=markup, disable_web_page_preview=True)
            except Exception as e:
                await message.reply_text(f"⚠️ Channel send failed: `{e}`")


@Client.on_callback_query(filters.regex(r"^list_page_(\d+)_(\-?\d+)$"))
async def page_callback(client, query):
    page = int(query.matches[0].group(1))
    owner_id = int(query.matches[0].group(2))
    text, markup = await get_dashboard(query.message.chat.id, page, owner_id)

    try:
        await query.edit_message_text(text, reply_markup=markup, disable_web_page_preview=True)
    except Exception:
        await query.answer("Loaded!")


@Client.on_callback_query(filters.regex(r"^force_refresh_(\d+)_(\-?\d+)$"))
async def force_refresh_callback(client, query):
    page = int(query.matches[0].group(1))
    owner_id = int(query.matches[0].group(2))

    await query.answer("🔄 Force Checking all URLs...", show_alert=False)

    await db.col.update_many({"user_id": owner_id}, {"$set": {"next_check": 0}})
    await asyncio.sleep(2)

    text, markup = await get_dashboard(query.message.chat.id, page, owner_id)
    try:
        await query.edit_message_text(text, reply_markup=markup, disable_web_page_preview=True)
    except Exception:
        pass


COMMANDS_TEXT = """
start - 🚀 𝘊𝘩𝘦𝘤𝘬 𝘉𝘰𝘵 𝘈𝘭𝘪𝘷𝘦
add - ✅ 𝘈𝘥𝘥 𝘜𝘙𝘓 + 𝘕𝘢𝘮𝘦
del - 🚫 𝘋𝘦𝘭𝘦𝘵𝘦 𝘢𝘯 𝘜𝘙𝘓
stats - ⁉️ 𝘊𝘩𝘦𝘤𝘬 𝘚𝘵𝘢𝘵𝘶𝘴 𝘰𝘧 𝘜𝘙𝘓𝘴
add_channel - 📢 𝘚𝘦𝘵 𝘋𝘢𝘴𝘩𝘣𝘰𝘢𝘳𝘥 𝘊𝘩𝘢𝘯𝘯𝘦𝘭
"""


@Client.on_message(filters.command("setcmd") & filters.user(ADMIN))
async def set_commands(client, message):
    commands = []

    for line in COMMANDS_TEXT.strip().split("\n"):
        if "-" in line:
            cmd, desc = line.split("-", 1)
            commands.append(BotCommand(cmd.strip(), desc.strip()))

    if not commands:
        return await message.reply_text("❌ No commands found in the configuration list.")

    try:
        await client.set_bot_commands(commands)
        await message.reply_text(f"✅ **__Success!** Updated {len(commands)} commands__.")
    except Exception as e:
        await message.reply_text(f"❌ **Error:** `{e}`")
