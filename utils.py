"""
utils.py – Fetches new OTT releases using the TMDB API.

Why TMDB instead of simplejustwatchapi?
  • simplejustwatchapi's public GraphQL endpoint breaks silently (empty title
    search returns nothing; attribute names changed across versions).
  • TMDB v3 is free, well-documented, stable, and returns watch-provider data
    (Netflix, Prime, Hotstar, etc.) via /movie/{id}/watch/providers.
  • One free API key from https://www.themoviedb.org/settings/api is all you need.
  • If no TMDB_API_KEY is set the bot falls back to JustWatch scraping.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import aiohttp

from config import JUSTWATCH_COUNTRY, TMDB_API_KEY
from database import is_item_sent, mark_item_sent

logger = logging.getLogger("OTTBot.utils")

TMDB_BASE   = "https://api.themoviedb.org/3"
TMDB_IMAGE  = "https://image.tmdb.org/t/p/w500"

# OTT provider IDs we care about (TMDB numbering)
OTT_PROVIDER_IDS = {
    8:   "Netflix",
    9:   "Amazon Prime",
    337: "Disney+",
    122: "Hotstar",
    2:   "Apple TV+",
    384: "HBO Max",
    386: "Peacock",
    531: "Paramount+",
    283: "Crunchyroll",
    11:  "MUBI",
    350: "Apple TV",
    15:  "Hulu",
    103: "MX Player",
    220: "ZEE5",
    232: "SonyLIV",
}


# ─── TMDB helpers ─────────────────────────────────────────────────────────────

async def _tmdb_get(session: aiohttp.ClientSession, path: str, params: dict) -> Optional[dict]:
    params["api_key"] = TMDB_API_KEY
    url = f"{TMDB_BASE}{path}"
    try:
        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as r:
            if r.status == 200:
                return await r.json()
            logger.warning(f"TMDB {path} → HTTP {r.status}")
    except Exception as exc:
        logger.error(f"TMDB request failed ({path}): {exc}")
    return None


async def _get_watch_providers(session: aiohttp.ClientSession, media_type: str, tmdb_id: int) -> List[str]:
    """Return list of OTT platform names available in JUSTWATCH_COUNTRY."""
    data = await _tmdb_get(session, f"/{media_type}/{tmdb_id}/watch/providers", {})
    if not data:
        return []
    country_data = data.get("results", {}).get(JUSTWATCH_COUNTRY, {})
    providers: List[str] = []
    for category in ("flatrate", "free", "ads", "rent", "buy"):
        for p in country_data.get(category, []):
            pid  = p.get("provider_id")
            name = OTT_PROVIDER_IDS.get(pid) or p.get("provider_name", "")
            if name and name not in providers:
                providers.append(name)
    return providers


async def _fetch_tmdb_releases(days_back: int) -> List[Dict[str, Any]]:
    """
    Pull movies + TV shows that were added to TMDB within the last `days_back` days
    AND have watch providers in the target country.
    """
    since = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    today = datetime.utcnow().strftime("%Y-%m-%d")
    results: List[Dict[str, Any]] = []

    async with aiohttp.ClientSession() as session:
        for media_type in ("movie", "tv"):
            date_field = "primary_release_date" if media_type == "movie" else "first_air_date"
            params = {
                "language":           "en-US",
                "sort_by":            "popularity.desc",
                "with_watch_monetization_types": "flatrate|free|ads",
                "watch_region":       JUSTWATCH_COUNTRY,
                f"{date_field}.gte":  since,
                f"{date_field}.lte":  today,
                "page": 1,
            }
            data = await _tmdb_get(session, f"/discover/{media_type}", params)
            if not data:
                continue

            items = data.get("results", [])[:30]
            logger.info(f"TMDB /discover/{media_type}: {len(items)} items")

            provider_tasks = [
                _get_watch_providers(session, media_type, item["id"])
                for item in items
            ]
            provider_lists = await asyncio.gather(*provider_tasks, return_exceptions=True)

            for item, providers in zip(items, provider_lists):
                if isinstance(providers, Exception):
                    providers = []

                # Only report items with actual OTT availability
                if not providers:
                    continue

                item_id = f"{media_type}_{item['id']}"
                if is_item_sent(item_id):
                    continue

                title        = item.get("title") or item.get("name") or "Unknown"
                release_date = item.get("release_date") or item.get("first_air_date") or ""
                overview     = (item.get("overview") or "No description available.")[:600]
                poster_path  = item.get("poster_path", "")
                vote_avg     = item.get("vote_average", 0)
                genres_ids   = item.get("genre_ids", [])

                mark_item_sent(item_id, title)
                results.append({
                    "id":           item["id"],
                    "item_id":      item_id,
                    "type":         media_type,
                    "title":        title,
                    "release_date": release_date,
                    "overview":     overview,
                    "providers":    providers,
                    "poster":       f"{TMDB_IMAGE}{poster_path}" if poster_path else "",
                    "rating":       round(vote_avg, 1),
                    "genre_ids":    genres_ids,
                })

    return results


# ─── JustWatch fallback (no API key needed) ───────────────────────────────────

async def _fetch_justwatch_releases(days_back: int) -> List[Dict[str, Any]]:
    """
    Minimal scrape of JustWatch new-additions page.
    Uses the public (undocumented) content API — no key required.
    """
    since  = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    today  = datetime.utcnow().strftime("%Y-%m-%d")
    results: List[Dict[str, Any]] = []
    country = JUSTWATCH_COUNTRY.lower()

    url = "https://apis.justwatch.com/contentpartner/v2/content/offers/by_title"
    headers = {"User-Agent": "Mozilla/5.0 (compatible; OTTBot/2.0)"}

    # JustWatch new-content endpoint
    jw_url = f"https://apis.justwatch.com/content/titles/{country}/new"
    params = {
        "language": "en",
        "body":     '{"content_types":["movie","show"],"page_size":40,"page":1}',
    }

    async with aiohttp.ClientSession(headers=headers) as session:
        try:
            async with session.get(
                jw_url,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as r:
                if r.status != 200:
                    logger.warning(f"JustWatch fallback HTTP {r.status}")
                    return []
                data = await r.json()
        except Exception as exc:
            logger.error(f"JustWatch fallback error: {exc}")
            return []

    for item in data.get("items", [])[:30]:
        item_id = f"jw_{item.get('id', '')}"
        if is_item_sent(item_id):
            continue

        title    = item.get("title", "Unknown")
        rel_date = item.get("original_release_year", "")
        overview = (item.get("short_description") or "No description.")[:500]
        obj_type = item.get("object_type", "movie")

        # Extract provider names
        providers = []
        for offer in item.get("offers", []):
            pname = offer.get("package_short_name") or offer.get("monetization_type", "")
            if pname and pname not in providers:
                providers.append(pname.upper())

        if not providers:
            continue

        mark_item_sent(item_id, title)
        results.append({
            "id":           item.get("id", ""),
            "item_id":      item_id,
            "type":         "movie" if obj_type == "movie" else "tv",
            "title":        title,
            "release_date": str(rel_date),
            "overview":     overview,
            "providers":    providers[:6],
            "poster":       "",
            "rating":       0,
            "genre_ids":    [],
        })

    return results


# ─── Public API ───────────────────────────────────────────────────────────────

async def get_new_releases(days_back: int = 7) -> List[Dict[str, Any]]:
    """
    Returns new OTT releases.  Uses TMDB if API key is configured,
    otherwise falls back to JustWatch scraping.
    """
    if TMDB_API_KEY:
        logger.info("Using TMDB for new releases")
        items = await _fetch_tmdb_releases(days_back)
    else:
        logger.info("No TMDB_API_KEY – using JustWatch fallback")
        items = await _fetch_justwatch_releases(days_back)

    logger.info(f"get_new_releases → {len(items)} new item(s)")
    return items


# ─── Message formatter ────────────────────────────────────────────────────────

GENRE_MAP = {
    28: "Action", 12: "Adventure", 16: "Animation", 35: "Comedy",
    80: "Crime", 99: "Documentary", 18: "Drama", 10751: "Family",
    14: "Fantasy", 36: "History", 27: "Horror", 10402: "Music",
    9648: "Mystery", 10749: "Romance", 878: "Sci-Fi", 53: "Thriller",
    10752: "War", 37: "Western",
    # TV genres
    10759: "Action & Adventure", 10762: "Kids", 10763: "News",
    10764: "Reality", 10765: "Sci-Fi & Fantasy", 10766: "Soap",
    10767: "Talk", 10768: "War & Politics",
}

STAR_RATINGS = {9: "⭐⭐⭐⭐⭐", 7: "⭐⭐⭐⭐", 5: "⭐⭐⭐", 3: "⭐⭐", 0: "⭐"}


def _stars(rating: float) -> str:
    for threshold, stars in sorted(STAR_RATINGS.items(), reverse=True):
        if rating >= threshold:
            return stars
    return ""


def format_item_message(item: Dict[str, Any]) -> str:
    media_emoji = "🎬" if item["type"] == "movie" else "📺"
    kind        = "Movie" if item["type"] == "movie" else "TV Series"
    title       = item["title"]
    rel_date    = item["release_date"] or "N/A"
    overview    = item["overview"]
    providers   = " • ".join(item.get("providers", [])) or "Check JustWatch"
    rating      = item.get("rating", 0)
    stars       = _stars(rating) if rating else ""

    genres = [GENRE_MAP[g] for g in item.get("genre_ids", []) if g in GENRE_MAP]
    genre_str = " | ".join(genres[:3]) if genres else ""

    # TMDB watch link
    tmdb_id    = item.get("id", "")
    media_path = "movie" if item["type"] == "movie" else "tv"
    tmdb_url   = f"https://www.themoviedb.org/{media_path}/{tmdb_id}" if tmdb_id else ""
    jw_url     = f"https://www.justwatch.com/{JUSTWATCH_COUNTRY.lower()}/{media_path}/{tmdb_id}"

    lines = [
        f"{media_emoji} **{title}** `[{kind}]`",
        f"📅 **Released:** {rel_date}",
    ]
    if rating:
        lines.append(f"⭐ **Rating:** {rating}/10  {stars}")
    if genre_str:
        lines.append(f"🎭 **Genre:** {genre_str}")
    lines.append(f"📡 **Available on:** {providers}")
    lines.append("")
    lines.append(overview)
    if tmdb_url:
        lines.append("")
        lines.append(f"[📖 TMDB]({tmdb_url})  |  [🍿 JustWatch]({jw_url})")

    return "\n".join(lines)
