# ---------------------------------------------------
# File Name: commands.py
# Author: MyselfNeon
# GitHub: https://github.com/MyselfNeon/
# Telegram: https://t.me/MyelfNeon
# ---------------------------------------------------

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, BotCommand
from .db import db
from info import ADMIN
import asyncio

# --- Helper: Generate Dashboard UI ---
async def get_dashboard(user_id, page=1):
    limit = 6
    urls, total_count = await db.get_urls_paginated(user_id, page, limit)
    
    # --- Empty State ---
    if not urls and page == 1:
        return "📂 **__List is Empty!__**\n__Use__ `/add https://site.com MySite` __to start.__", None
    
    text = f"📊 **__Dashboard (Page {page})__**\n__Total Monitors: {total_count}__\n\n"
    
    # --- Generate List Text ---
    for i, data in enumerate(urls):
        idx = (page - 1) * limit + i + 1
        status = data.get('status', 'PENDING')
        display_name = data.get('name') or data.get('url')
        
        # Icons
        s_icon = {
            "ONLINE": "🟢", "DOWN": "🔴", "SLOW": "🟡", 
            "PAUSED": "⛔️", "PENDING": "⏳", "RATE-LIMITED": "⚠️"
        }.get(status, "❓")
        
        resp = data.get('response_time', 0)
        uptime_pct = 0
        if data.get('total_checks', 0) > 0:
            uptime_pct = round((data['uptime_count'] / data['total_checks']) * 100, 1)

        # Styled List Item
        text += (
            f"**__{idx}. {display_name}__**\n"
            f"   **╚** {s_icon} __**{status}** ⚡ {resp}ms 📈 {uptime_pct}%__\n\n"
        )
    
    # --- Button Logic (Emoji Only) ---
    buttons = []
    nav_row = []

    # 1. Back Button (⬅️) - Only if not on Page 1
    if page > 1:
        nav_row.append(InlineKeyboardButton("⬅️", callback_data=f"list_page_{page-1}"))
    
    # 2. Force Refresh Button (🔄) - Always Present
    nav_row.append(InlineKeyboardButton("🔄", callback_data=f"force_refresh_{page}"))
    
    # 3. Next Button (➡️) - Only if more pages exist
    if (page * limit) < total_count:
        nav_row.append(InlineKeyboardButton("➡️", callback_data=f"list_page_{page+1}"))
            
    # Add the navigation row if it has buttons
    if nav_row:
        buttons.append(nav_row)
    
    # "Close" button has been removed as requested
    
    return text, InlineKeyboardMarkup(buttons)

# --- Commands ---
@Client.on_message(filters.command("start") & filters.private)
async def start_cmd(client, message):
    text = (
        "👋 **__Professional Uptime Monitor__**\n\n"
        "**__I use Adaptive Intelligence ( Head & Get ) to Monitor your Websites.__**\n"
        "**__Created By @MyselfNeon__**\n\n"
        "**__Commands:__**\n"
        "__/add {url} {name} – Monitor a new URL__\n"
        "__/del {url} – Remove an URL__\n"
        "__/list – View URLs Dashboard__"
    )
    await message.reply_text(text)

@Client.on_message(filters.command("add") & filters.private)
async def add_cmd(client, message):
    if len(message.command) < 3:
        return await message.reply_text("⚠️ **__Usage:** /add https://google.com Google__")
    
    user_id = message.chat.id
    url = message.command[1].strip()
    name = " ".join(message.command[2:]).strip()

    # --- 1. Check URL Limit (Max 5 for Users, Infinite for Admin) ---
    # We fetch only 1 item just to get the 'total_count' efficiently
    _, total_count = await db.get_urls_paginated(user_id, 1, 1)
    
    admin_ids = ADMIN if isinstance(ADMIN, list) else [ADMIN]
    
    # If user is NOT admin AND has 5 or more URLs
    if user_id not in admin_ids and total_count >= 5:
        return await message.reply_text(
            "⛔️ **__Limit Reached!__**\n\n"
            "__Free users are limited to 5 URLs.__\n"
            "__Please remove a URL or contact Admin.__"
        )

    if not url.startswith(("http://", "https://")):
        return await message.reply_text("⛔️ **__URL must start with http/https__**")
        
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

@Client.on_message(filters.command("del") & filters.private)
async def del_cmd(client, message):
    if len(message.command) < 2:
        return await message.reply_text("⚠️ **__Usage:** /del https://google.com__")
        
    await db.remove_url(message.chat.id, message.command[1])
    await message.reply_text("🗑 **__URL Deleted.__**")

@Client.on_message(filters.command(["list", "check", "stats"]) & filters.private)
async def list_cmd(client, message):
    text, markup = await get_dashboard(message.chat.id, 1)
    await message.reply_text(text, reply_markup=markup, disable_web_page_preview=True)

# --- Callbacks ---
@Client.on_callback_query(filters.regex(r"^list_page_(\d+)"))
async def page_callback(client, query):
    # Standard navigation (Just switch page)
    page = int(query.matches[0].group(1))
    text, markup = await get_dashboard(query.message.chat.id, page)
    
    try:
        await query.edit_message_text(text, reply_markup=markup, disable_web_page_preview=True)
    except:
        await query.answer("Loaded!")

@Client.on_callback_query(filters.regex(r"^force_refresh_(\d+)"))
async def force_refresh_callback(client, query):
    page = int(query.matches[0].group(1))
    user_id = query.from_user.id
    
    # 1. Show feedback immediately
    await query.answer("🔄 Force Checking all URLs...", show_alert=False)
    
    # 2. Force Check Logic
    # We set 'next_check' to 0 so the monitor loop picks them up immediately
    await db.col.update_many(
        {"user_id": user_id},
        {"$set": {"next_check": 0}}
    )
    
    # 3. Wait a moment for the background worker (monitor.py runs every 5s)
    await asyncio.sleep(2)
    
    # 4. Reload the dashboard with new stats
    text, markup = await get_dashboard(user_id, page)
    try:
        await query.edit_message_text(text, reply_markup=markup, disable_web_page_preview=True)
    except:
        pass

# --- Edit Commands ---
COMMANDS_TEXT = """
start - 🚀 𝘊𝘩𝘦𝘤𝘬 𝘉𝘰𝘵 𝘈𝘭𝘪𝘷𝘦
add - ✅ 𝘈𝘥𝘥 𝘜𝘙𝘓 + 𝘕𝘢𝘮𝘦
del - 🚫 𝘋𝘦𝘭𝘦𝘵𝘦 𝘢𝘯 𝘜𝘙𝘓
stats - ⁉️ 𝘊𝘩𝘦𝘤𝘬 𝘚𝘵𝘢𝘵𝘶𝘴 𝘰𝘧 𝘜𝘙𝘓𝘴
"""

@Client.on_message(filters.command("setcmd") & filters.user(ADMIN))
async def set_commands(client, message):
    commands = []
    
    # Parse the text block line by line
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
