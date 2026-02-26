# ---------------------------------------------------
# File Name: monitor.py
# Author: MyselfNeon
# GitHub: https://github.com/MyselfNeon/
# Telegram: https://t.me/MyelfNeon
# ---------------------------------------------------

import asyncio
import aiohttp
import time
from pyrogram import Client
from .db import db

# Cache states in memory
state_cache = {}

async def smart_check(session, url):
    """
    Strategy: HEAD -> If Error -> GET
    Returns: (is_up, status_code/error, latency_ms)
    """
    timeout = aiohttp.ClientTimeout(total=10) # Explicit 10s timeout
    start = time.perf_counter()
    
    try:
        # 1. Try HEAD first (Faster, lighter)
        async with session.head(url, timeout=timeout, allow_redirects=True) as response:
            latency = int((time.perf_counter() - start) * 1000)
            status = response.status
            
            if status == 429:
                return True, 429, latency # Treat 429 as "Up but throttling"
            
            # If Method Not Allowed (405) or other 4xx/5xx, verify with GET
            # Some servers block HEAD but allow GET.
            if status >= 400:
                raise ValueError("Force GET") # Trigger fallback
                
            return True, status, latency

    except (ValueError, aiohttp.ClientError, asyncio.TimeoutError):
        # 2. Fallback to GET if HEAD fails or returns suspicious error
        try:
            # Reset timer for the GET attempt (optional, or accumulative)
            # We'll measure just the GET latency here
            start_get = time.perf_counter()
            async with session.get(url, timeout=timeout) as response:
                latency = int((time.perf_counter() - start_get) * 1000)
                status = response.status
                
                if status == 429:
                    return True, 429, latency
                
                if 200 <= status < 400:
                    return True, status, latency
                else:
                    return False, status, latency
                    
        except asyncio.TimeoutError:
            return False, "Timeout", 0
        except aiohttp.ClientConnectorError:
            return False, "DNS/Connection Error", 0
        except Exception as e:
            return False, "Error", 0
    except Exception as e:
         return False, "Unknown Error", 0

async def process_entry(app, session, entry):
    user_id = entry['user_id']
    url = entry['url']
    name = entry.get('name') or url
    entry_id = entry['_id']
    
    is_up, code, latency = await smart_check(session, url)
    
    # Retry logic only if actually DOWN (not for 429 or Slow)
    if not is_up:
        await asyncio.sleep(1)
        is_up, code, latency = await smart_check(session, url)

    result_data = {
        'is_up': is_up,
        'latency': latency,
        'code': code,
        'consecutive_failures': entry.get('consecutive_failures', 0),
        'check_interval': entry.get('check_interval', 60)
    }

    new_status = await db.update_adaptive_result(entry_id, result_data)

    # State Change Alert
    unique_key = f"{user_id}|{url}"
    prev_status = state_cache.get(unique_key, "PENDING")
    
    if new_status != prev_status:
        state_cache[unique_key] = new_status
        if entry.get('alert_mode') != "SILENT":
            await send_alert(app, user_id, name, url, new_status, code, latency)

async def send_alert(app, user_id, name, url, status, code, latency):
    icon = {
        "ONLINE": "🟢", "SLOW": "🟡", "DOWN": "🔴", 
        "PAUSED": "⛔️", "RATE-LIMITED": "⚠️"
    }.get(status, "❓")
    
    msg_title = "Service Rate Limited" if status == "RATE-LIMITED" else f"Monitor Alert: {status}"
    
    text = (
        f"{icon} **{msg_title}**\n\n"
        f"🏷 **Monitor:** `{name}`\n"
        f"📝 **Info:** `{code}`\n"
        f"⚡ **Latency:** `{latency}ms`\n"
    )
    
    if status == "PAUSED":
        text += "\n💀 **Monitoring paused due to 20 consecutive failures.**"
    elif status == "RATE-LIMITED":
        text += "\n⏳ **Backing off checks to prevent block.**"

    try:
        await app.send_message(user_id, text, disable_web_page_preview=True)
    except Exception:
        pass 

async def monitor_task(app: Client):
    print("🧠 Starting Intelligent Monitor (HEAD + GET fallback)...")
    
    # Initialize DB Indexes on startup
    await db.ensure_indexes()
    
    async with aiohttp.ClientSession() as session:
        while True:
            due_urls = await db.get_due_urls()
            if due_urls:
                tasks = [process_entry(app, session, entry) for entry in due_urls]
                await asyncio.gather(*tasks)
            await asyncio.sleep(5)