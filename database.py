"""
database.py — MongoDB backend for OTT Updates Bot.

Collections:
  subscribers  – { chat_id, username, subscribed_at }
  sent_items   – { item_id, title, sent_at }
"""

import logging
from datetime import datetime, timezone
from typing import List

from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ASCENDING

from config import MONGO_URI, MONGO_DB_NAME

logger = logging.getLogger("OTTBot.db")

_client: AsyncIOMotorClient | None = None
_db = None


def get_db():
    return _db


async def init_db() -> None:
    """Connect to MongoDB and ensure indexes exist."""
    global _client, _db
    _client = AsyncIOMotorClient(MONGO_URI)
    _db = _client[MONGO_DB_NAME]

    # Ensure indexes
    await _db.subscribers.create_index("chat_id", unique=True)
    await _db.sent_items.create_index("item_id", unique=True)
    await _db.sent_items.create_index(
        [("sent_at", ASCENDING)],
        expireAfterSeconds=30 * 24 * 3600,   # auto-purge sent_items after 30 days
    )

    # Ping to verify connection
    await _client.admin.command("ping")
    logger.info(f"✅ MongoDB connected → {MONGO_DB_NAME}")


async def close_db() -> None:
    if _client:
        _client.close()


# ─── Subscribers ──────────────────────────────────────────────────────────────

async def add_subscriber(chat_id: int, username: str = "") -> bool:
    """Insert subscriber. Returns True if newly added, False if already existed."""
    try:
        result = await _db.subscribers.update_one(
            {"chat_id": chat_id},
            {"$setOnInsert": {
                "chat_id":       chat_id,
                "username":      username or "",
                "subscribed_at": datetime.now(timezone.utc),
            }},
            upsert=True,
        )
        return result.upserted_id is not None   # True only on fresh insert
    except Exception as exc:
        logger.error(f"add_subscriber error: {exc}")
        return False


async def remove_subscriber(chat_id: int) -> bool:
    """Returns True if found and removed."""
    result = await _db.subscribers.delete_one({"chat_id": chat_id})
    return result.deleted_count > 0


async def get_subscribers() -> List[int]:
    cursor = _db.subscribers.find({}, {"chat_id": 1, "_id": 0})
    return [doc["chat_id"] async for doc in cursor]


async def set_auto_send(chat_id: int, enabled: bool) -> None:
    await _db.subscribers.update_one(
        {"chat_id": chat_id},
        {"$set": {"auto_send": enabled}},
        upsert=True,
    )


async def get_auto_send_subscribers() -> List[int]:
    cursor = _db.subscribers.find(
        {"$or": [{"auto_send": {"$exists": False}}, {"auto_send": True}]},
        {"chat_id": 1, "_id": 0},
    )
    return [doc["chat_id"] async for doc in cursor]


async def get_subscriber_count() -> int:
    return await _db.subscribers.count_documents({})


async def is_subscriber(chat_id: int) -> bool:
    doc = await _db.subscribers.find_one({"chat_id": chat_id}, {"_id": 1})
    return doc is not None


# ─── Sent-items dedup ─────────────────────────────────────────────────────────

async def is_item_sent(item_id: str) -> bool:
    doc = await _db.sent_items.find_one({"item_id": item_id}, {"_id": 1})
    return doc is not None


async def mark_item_sent(item_id: str, title: str = "") -> None:
    await _db.sent_items.update_one(
        {"item_id": item_id},
        {"$setOnInsert": {
            "item_id": item_id,
            "title":   title,
            "sent_at": datetime.now(timezone.utc),
        }},
        upsert=True,
    )


async def get_sent_count() -> int:
    return await _db.sent_items.count_documents({})
