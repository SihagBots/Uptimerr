# ---------------------------------------------------
# File Name: database.py
# Author: MyselfNeon
# GitHub: https://github.com/MyselfNeon/
# Telegram: https://t.me/MyelfNeon
# ---------------------------------------------------

import motor.motor_asyncio
import time
from info import DB_URI, DB_NAME

class Database:
    def __init__(self, uri, database_name):
        self._client = motor.motor_asyncio.AsyncIOMotorClient(uri)
        self.db = self._client[database_name]
        self.col = self.db.urls
        self.config = self.db.config

    async def ensure_indexes(self):
        """Create indices for scaling."""
        # Index for fetching due URLs quickly
        await self.col.create_index([("next_check", 1), ("status", 1)])
        # Index for user lookups and pagination
        await self.col.create_index([("user_id", 1)])

    def new_url(self, user_id, url, name):
        return dict(
            user_id=user_id,
            name=name,
            url=url,
            status="PENDING",     # ONLINE, DOWN, SLOW, PAUSED, RATE-LIMITED
            last_code="200",
            response_time=0,
            uptime_count=0,
            total_checks=0,
            consecutive_failures=0,
            next_check=time.time(),
            check_interval=60,
            alert_mode="ON",
            added_at=time.time()
        )

    async def add_url(self, user_id, url, name):
        # Limit check removed here. It is handled in commands.py
        url_dict = self.new_url(user_id, url, name)
        await self.col.insert_one(url_dict)
        return True, "Added"

    async def remove_url(self, user_id, url):
        await self.col.delete_one({"user_id": user_id, "url": url})

    async def is_url_exist(self, user_id, url):
        found = await self.col.find_one({"user_id": user_id, "url": url})
        return bool(found)

    async def get_urls_paginated(self, user_id, page=1, limit=6):
        skip = (page - 1) * limit
        cursor = self.col.find({"user_id": user_id}).skip(skip).limit(limit)
        urls = await cursor.to_list(length=limit)
        total_count = await self.col.count_documents({"user_id": user_id})
        return urls, total_count

    async def get_due_urls(self):
        now = time.time()
        return await self.col.find({
            "next_check": {"$lte": now}, 
            "status": {"$ne": "PAUSED"}
        }).to_list(length=None)

    async def update_adaptive_result(self, _id, result_data):
        now = time.time()
        
        is_up = result_data['is_up']
        latency = result_data['latency']
        code = result_data['code']
        current_fails = result_data['consecutive_failures']
        current_interval = result_data['check_interval']

        update_query = {
            "$set": {
                "last_code": str(code),
                "response_time": latency,
                "last_checked": now,
            },
            "$inc": {"total_checks": 1}
        }

        # --- Adaptive Logic ---
        if code == 429:
            # RATE LIMITED HANDLING
            new_status = "RATE-LIMITED"
            # Do NOT reset uptime, do NOT increment failures
            # Backoff: Double interval (Max 10 mins) to let it cool down
            new_interval = min(current_interval * 2, 600)
            update_query["$set"]["check_interval"] = int(new_interval)
            update_query["$set"]["status"] = new_status
            
        elif is_up:
            # ONLINE
            new_status = "SLOW" if latency > 1500 else "ONLINE"
            update_query["$set"]["consecutive_failures"] = 0
            update_query["$inc"]["uptime_count"] = 1
            
            # Gradually increase interval if stable (Max 5 mins)
            new_interval = min(current_interval * 1.5, 300) 
            if current_interval < 60: new_interval = 60
            
            update_query["$set"]["check_interval"] = int(new_interval)
            update_query["$set"]["status"] = new_status
            
        else:
            # DOWN or DEGRADED
            new_fails = current_fails + 1
            update_query["$set"]["consecutive_failures"] = new_fails
            
            if new_fails >= 20:
                update_query["$set"]["status"] = "PAUSED"
                update_query["$set"]["check_interval"] = 0
            else:
                update_query["$set"]["status"] = "DOWN"
                # Speed up checks to catch recovery (Min 30s)
                new_interval = max(current_interval / 2, 30)
                update_query["$set"]["check_interval"] = int(new_interval)

        # Schedule Next Check (Unless Paused)
        if update_query["$set"]["status"] != "PAUSED":
            update_query["$set"]["next_check"] = now + update_query["$set"]["check_interval"]

        await self.col.update_one({"_id": _id}, update_query)
        return update_query["$set"]["status"]

db = Database(DB_URI, DB_NAME)
