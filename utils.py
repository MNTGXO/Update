import asyncio
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any
import os

JUSTWATCH_COUNTRY = os.getenv("JUSTWATCH_COUNTRY", "US")
JUSTWATCH_LANGUAGE = os.getenv("JUSTWATCH_LANGUAGE", "en")
logger = logging.getLogger(__name__)

from database import is_item_sent, mark_item_sent

async def get_new_releases(days_back: int = 7) -> List[Dict[str, Any]]:
    cutoff_date = datetime.now() - timedelta(days=days_back)
    new_items = []
    try:
        from simplejustwatchapi.justwatch import search as justwatch_search
        
        for content_type in ["movie", "show"]:
            try:
                loop = asyncio.get_event_loop()
                results = await loop.run_in_executor(
                    None,
                    lambda: justwatch_search(
                        title="",
                        country=JUSTWATCH_COUNTRY,
                        language=JUSTWATCH_LANGUAGE,
                        count=30
                    )
                )
                logger.info(f"Fetched {len(results)} {content_type}s")
                for item in results:
                    item_type = getattr(item, 'object_type', '').lower()
                    if content_type == "movie" and item_type != "movie":
                        continue
                    if content_type == "show" and item_type not in ["show", "tv_show"]:
                        continue
                    
                    release_date = getattr(item, 'release_date', None)
                    if not release_date:
                        continue
                    
                    try:
                        rel_date = datetime.strptime(release_date, "%Y-%m-%d")
                        if rel_date < cutoff_date:
                            continue
                    except:
                        continue
                    
                    item_id = f"{content_type}_{getattr(item, 'object_id', '')}"
                    if not is_item_sent(item_id):
                        platforms = []
                        for offer in getattr(item, 'offers', []):
                            platform_name = getattr(offer, 'name', None)
                            if platform_name and platform_name not in platforms:
                                platforms.append(platform_name)
                        
                        new_items.append({
                            "type": content_type,
                            "id": getattr(item, 'object_id', ''),
                            "title": getattr(item, 'title', 'Unknown'),
                            "release_date": release_date,
                            "overview": getattr(item, 'short_description', 'No description.'),
                            "offers": platforms[:5]
                        })
                        mark_item_sent(item_id)
            except Exception as e:
                logger.error(f"Error fetching {content_type}s: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"JustWatch error: {e}", exc_info=True)
    return new_items

def format_item_message(item: Dict[str, Any]) -> str:
    media_type = "🎬 Movie" if item["type"] == "movie" else "📺 TV Series"
    title = item["title"]
    release_date = item["release_date"]
    year = release_date[:4] if release_date else "?"
    overview = item["overview"][:500]
    platforms = ", ".join(item.get("offers", [])) if item.get("offers") else "Check JustWatch"
    return (
        f"*{media_type}: {title} ({year})*\n"
        f"📅 *Release:* {release_date}\n"
        f"📺 *Watch on:* {platforms}\n\n"
        f"{overview}\n\n"
        f"[More info](https://www.justwatch.com/{JUSTWATCH_COUNTRY}/{item['type']}/{item['id']})"
    )
