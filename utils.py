"""
utils.py — Fetch new OTT releases.

Priority:
  1. TMDB API  (set TMDB_API_KEY in .env — free at themoviedb.org)
  2. JustWatch GraphQL  (no key needed — uses their public API)
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import aiohttp
from bs4 import BeautifulSoup
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from config import JUSTWATCH_COUNTRY, TMDB_API_KEY
from database import is_item_sent, mark_item_sent

logger = logging.getLogger("OTTBot.utils")

TMDB_BASE  = "https://api.themoviedb.org/3"
TMDB_IMG   = "https://image.tmdb.org/t/p/w500"

# TMDB watch-provider IDs → friendly names
OTT_PROVIDERS = {
    8:   "Netflix",        9:   "Amazon Prime",   337: "Disney+",
    122: "Hotstar",        2:   "Apple TV+",       384: "Max",
    386: "Peacock",       531: "Paramount+",      283: "Crunchyroll",
    11:  "MUBI",          15:  "Hulu",            103: "MX Player",
    220: "ZEE5",          232: "SonyLIV",          31: "HBO",
    350: "Apple TV",      43:  "Starz",
}

GENRE_MAP = {
    28:"Action", 12:"Adventure", 16:"Animation", 35:"Comedy",
    80:"Crime", 99:"Documentary", 18:"Drama", 10751:"Family",
    14:"Fantasy", 36:"History", 27:"Horror", 10402:"Music",
    9648:"Mystery", 10749:"Romance", 878:"Sci-Fi", 53:"Thriller",
    10752:"War", 37:"Western",
    10759:"Action & Adventure", 10762:"Kids", 10763:"News",
    10764:"Reality", 10765:"Sci-Fi & Fantasy", 10766:"Soap",
    10767:"Talk", 10768:"War & Politics",
}


# ─── TMDB ─────────────────────────────────────────────────────────────────────

async def _tmdb(session: aiohttp.ClientSession, path: str, params: dict) -> Optional[dict]:
    params["api_key"] = TMDB_API_KEY
    try:
        async with session.get(
            f"{TMDB_BASE}{path}", params=params,
            timeout=aiohttp.ClientTimeout(total=15)
        ) as r:
            if r.status == 200:
                return await r.json()
            logger.warning(f"TMDB {path} → {r.status}")
    except Exception as e:
        logger.error(f"TMDB error ({path}): {e}")
    return None


async def _tmdb_providers(session: aiohttp.ClientSession,
                          media_type: str, tmdb_id: int) -> List[str]:
    data = await _tmdb(session, f"/{media_type}/{tmdb_id}/watch/providers", {})
    if not data:
        return []
    region = data.get("results", {}).get(JUSTWATCH_COUNTRY, {})
    seen: list[str] = []
    for cat in ("flatrate", "free", "ads"):
        for p in region.get(cat, []):
            name = OTT_PROVIDERS.get(p.get("provider_id", 0)) or p.get("provider_name", "")
            if name and name not in seen:
                seen.append(name)
    return seen


async def _fetch_tmdb(days_back: int, dedup: bool = True) -> List[Dict[str, Any]]:
    since = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%d")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    results = []

    async with aiohttp.ClientSession() as session:
        for mt in ("movie", "tv"):
            date_field = "primary_release_date" if mt == "movie" else "first_air_date"
            data = await _tmdb(session, f"/discover/{mt}", {
                "language":                       "en-US",
                "sort_by":                        "popularity.desc",
                "with_watch_monetization_types":  "flatrate|free|ads",
                "watch_region":                   JUSTWATCH_COUNTRY,
                f"{date_field}.gte":              since,
                f"{date_field}.lte":              today,
                "page": 1,
            })
            if not data:
                continue

            items = data.get("results", [])[:25]
            logger.info(f"TMDB /discover/{mt} → {len(items)} item(s)")

            provider_results = await asyncio.gather(
                *[_tmdb_providers(session, mt, it["id"]) for it in items],
                return_exceptions=True,
            )

            for item, providers in zip(items, provider_results):
                if isinstance(providers, Exception) or not providers:
                    continue
                item_id = f"tmdb_{mt}_{item['id']}"
                if dedup and await is_item_sent(item_id):
                    continue

                title    = item.get("title") or item.get("name") or "Unknown"
                rel_date = item.get("release_date") or item.get("first_air_date") or ""
                overview = (item.get("overview") or "No description.")[:600]
                poster   = item.get("poster_path", "")
                rating   = round(item.get("vote_average", 0), 1)

                if dedup:
                    await mark_item_sent(item_id, title)
                results.append({
                    "id":           item["id"],
                    "item_id":      item_id,
                    "type":         mt,
                    "title":        title,
                    "release_date": rel_date,
                    "overview":     overview,
                    "providers":    providers,
                    "poster":       f"{TMDB_IMG}{poster}" if poster else "",
                    "rating":       rating,
                    "genre_ids":    item.get("genre_ids", []),
                })

    return results


# ─── JustWatch GraphQL fallback ───────────────────────────────────────────────

JW_GQL_URL = "https://apis.justwatch.com/graphql"

JW_QUERY_POPULAR = """
query GetPopularTitles($country: Country!, $language: Language!) {
  popularTitles(
    country: $country
    first: 40
    sortBy: POPULAR
    filter: {
      objectTypes: [MOVIE, SHOW]
      monetizationTypes: [FLATRATE, FREE, ADS]
    }
  ) {
    edges {
      node {
        id
        objectType
        content(country: $country, language: $language) {
          title
          shortDescription
          originalReleaseYear
          posterUrl
        }
        offers(
          country: $country
          platform: WEB
          filter: { monetizationTypes: [FLATRATE, FREE, ADS] }
        ) {
          package { clearName shortName }
        }
      }
    }
  }
}
"""


async def _fetch_justwatch(days_back: int, dedup: bool = True) -> List[Dict[str, Any]]:
    results = []
    country_code = JUSTWATCH_COUNTRY.upper()   # e.g. "IN"

    headers = {
        "Content-Type":  "application/json",
        "User-Agent":    "Mozilla/5.0 (compatible; OTTBot/3.0)",
        "Accept":        "application/json",
    }
    payload = {
        "query":     JW_QUERY_POPULAR,
        "variables": {
            "country":  country_code,
            "language": "en",
        },
    }

    async with aiohttp.ClientSession(headers=headers) as session:
        try:
            async with session.post(
                JW_GQL_URL,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as r:
                if r.status != 200:
                    text = await r.text()
                    logger.warning(f"JustWatch GraphQL HTTP {r.status}: {text[:200]}")
                    return []
                data = await r.json()
        except Exception as exc:
            logger.error(f"JustWatch GraphQL error: {exc}")
            return []

    if data.get("errors"):
        logger.warning(f"JustWatch GraphQL errors: {json.dumps(data['errors'])[:300]}")
        return []

    edges = data.get("data", {}).get("popularTitles", {}).get("edges", [])
    logger.info(f"JustWatch GraphQL → {len(edges)} edge(s)")

    for edge in edges:
        node    = edge.get("node", {})
        content = node.get("content", {}) or {}

        # Collect unique platform names from all offers
        providers: list[str] = []
        for offer in (node.get("offers") or []):
            pkg  = offer.get("package") or {}
            name = pkg.get("clearName") or pkg.get("shortName") or ""
            if name and name not in providers:
                providers.append(name)

        if not providers:
            continue

        obj_type = node.get("objectType", "MOVIE")
        mt       = "movie" if obj_type == "MOVIE" else "tv"
        jw_id    = node.get("id", "")
        item_id  = f"jw_{jw_id}"

        if dedup and await is_item_sent(item_id):
            continue

        title    = content.get("title") or "Unknown"
        year     = content.get("originalReleaseYear") or ""
        overview = (content.get("shortDescription") or "No description.")[:500]
        poster   = content.get("posterUrl") or ""
        # JustWatch poster URL template
        if poster and "{profile}" in poster:
            poster = poster.replace("{profile}", "s592").replace("{format}", "jpg")
        if poster.startswith("/"):
            poster = f"https://images.justwatch.com{poster}"

        if dedup:
            await mark_item_sent(item_id, title)
        results.append({
            "id":           jw_id,
            "item_id":      item_id,
            "type":         mt,
            "title":        title,
            "release_date": str(year),
            "overview":     overview,
            "providers":    providers[:6],
            "poster":       poster,
            "rating":       0,
            "genre_ids":    [],
        })

    return results


async def _fetch_justwatch_web(dedup: bool = True) -> List[Dict[str, Any]]:
    """Scrape JustWatch /new page as fallback source."""
    url = f"https://www.justwatch.com/{JUSTWATCH_COUNTRY.lower()}/new"
    headers = {"User-Agent": "Mozilla/5.0 (compatible; OTTBot/3.0)"}
    results: List[Dict[str, Any]] = []

    async with aiohttp.ClientSession(headers=headers) as session:
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as r:
                if r.status != 200:
                    logger.warning(f"JustWatch web scrape HTTP {r.status}")
                    return []
                html = await r.text()
        except Exception as exc:
            logger.error(f"JustWatch web scrape error: {exc}")
            return []

    def _parse(raw: str):
        parsed = []
        soup = BeautifulSoup(raw, "html.parser")
        for block in soup.select("div.timeline__provider-block"):
            logo = block.select_one(".provider-timeline__logo img")
            provider = (logo.get("alt", "") if logo else "").strip() or "Unknown"
            for item in block.select(".horizontal-title-list__item"):
                a = item.select_one("a[href]")
                img = item.select_one(".title-poster__image img")
                if not a or not img:
                    continue
                parsed.append((a.get("href", ""), (img.get("alt", "") or "Unknown").strip(), (img.get("src", "") or "").strip(), provider))
        return parsed

    parsed_items = await asyncio.to_thread(_parse, html)
    for href, title, poster, provider in parsed_items[:40]:
        item_id = f"jw_web_{href}"
        if dedup and await is_item_sent(item_id):
            continue
        if dedup:
            await mark_item_sent(item_id, title)

        results.append({
            "id": href,
            "item_id": item_id,
            "type": "tv" if "/tv-show/" in href else "movie",
            "title": title,
            "release_date": "Today",
            "overview": f"New on {provider}",
            "providers": [provider],
            "poster": poster,
            "rating": 0,
            "genre_ids": [],
        })

    logger.info(f"JustWatch web scrape → {len(results)} item(s)")
    return results


# ─── Public API ───────────────────────────────────────────────────────────────

async def get_new_releases(days_back: int = 7, dedup: bool = True) -> List[Dict[str, Any]]:
    if TMDB_API_KEY:
        logger.info("Fetching via TMDB API …")
        items = await _fetch_tmdb(days_back, dedup=dedup)
    else:
        logger.info("No TMDB_API_KEY — using JustWatch web/GraphQL fallback …")
        items = await _fetch_justwatch_web(dedup=dedup)
        if not items:
            items = await _fetch_justwatch(days_back, dedup=dedup)

    logger.info(f"get_new_releases → {len(items)} new item(s)")
    return items


# ─── Message formatter (HTML) ─────────────────────────────────────────────────

def _stars(r: float) -> str:
    if r >= 8: return "⭐⭐⭐⭐⭐"
    if r >= 6: return "⭐⭐⭐⭐"
    if r >= 4: return "⭐⭐⭐"
    if r >= 2: return "⭐⭐"
    return "⭐"


def format_item_message(item: Dict[str, Any]) -> str:
    """Return an HTML-formatted message for one OTT item."""
    emoji   = "🎬" if item["type"] == "movie" else "📺"
    kind    = "Movie" if item["type"] == "movie" else "TV Series"
    title   = item["title"]
    rel     = item.get("release_date") or "N/A"
    overview= item.get("overview", "")
    rating  = item.get("rating", 0)
    provs   = " • ".join(item.get("providers", [])) or "Check JustWatch"

    genres  = [GENRE_MAP[g] for g in item.get("genre_ids", []) if g in GENRE_MAP]
    genre_s = " | ".join(genres[:3]) if genres else ""

    tmdb_id = item.get("id", "")
    mpath   = "movie" if item["type"] == "movie" else "tv"
    country = JUSTWATCH_COUNTRY.lower()
    tmdb_url = f"https://www.themoviedb.org/{mpath}/{tmdb_id}" if tmdb_id else ""
    jw_url   = f"https://www.justwatch.com/{country}/{mpath}"

    lines = [
        f"{emoji} <b>{title}</b>  <code>[{kind}]</code>",
        f"📅 <b>Released:</b> {rel}",
    ]
    if rating:
        lines.append(f"⭐ <b>Rating:</b> {rating}/10  {_stars(rating)}")
    if genre_s:
        lines.append(f"🎭 <b>Genre:</b> {genre_s}")
    lines.append(f"📡 <b>Available on:</b> {provs}")
    lines.append("")
    lines.append(overview)
    if tmdb_url:
        lines.append("")
        lines.append(f'<a href="{tmdb_url}">📖 TMDB</a>  |  <a href="{jw_url}">🍿 JustWatch</a>')

    return "\n".join(lines)


def format_item_keyboard(item: Dict[str, Any]) -> InlineKeyboardMarkup:
    mpath = "movie" if item["type"] == "movie" else "tv"
    country = JUSTWATCH_COUNTRY.lower()
    tmdb_id = item.get("id", "")
    tmdb_url = f"https://www.themoviedb.org/{mpath}/{tmdb_id}" if tmdb_id else None
    jw_url = f"https://www.justwatch.com/{country}/{mpath}"

    buttons = [[InlineKeyboardButton("▶️ Open JustWatch", url=jw_url)]]
    if tmdb_url:
        buttons.append([InlineKeyboardButton("🎬 Open TMDB", url=tmdb_url)])
    return InlineKeyboardMarkup(buttons)
