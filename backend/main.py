from __future__ import annotations

import time
import mimetypes
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from types import SimpleNamespace
from urllib.parse import quote, unquote, urlparse

import requests
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from reader_server import MangaReader, fuzzy_match_score, normalize_match_text


CATALOG_CACHE_TTL_SECONDS = 30 * 60
SEARCH_CACHE_TTL_SECONDS = 5 * 60
SOURCE_RESOLUTION_CACHE_TTL_SECONDS = 10 * 60
IMAGE_CACHE_TTL_SECONDS = 15 * 60
IMAGE_CACHE_MAX_ITEMS = 300
ANILIST_CACHE_TTL_SECONDS = 12 * 60 * 60
DEFAULT_LIMIT = 80

MANGADEX_GENRES = {
    "Acao": "Action",
    "Aventura": "Adventure",
    "Comedia": "Comedy",
    "Drama": "Drama",
    "Fantasia": "Fantasy",
    "Gore": "Gore",
    "Thriller": "Thriller",
    "Sobrenatural": "Supernatural",
    "Misterio": "Mystery",
    "Psicologico": "Psychological",
    "Romance": "Romance",
    "Terror": "Horror",
    "Isekai": "Isekai",
    "Sci-Fi": "Sci-Fi",
    "Slice of Life": "Slice of Life",
}

SOURCE_LABELS = {
    "mangadex": "MangaDex",
    "mangalivre": "MangaLivre",
    "mangasbrasuka": "MangasBrasuka",
    "pieceproject": "One Piece Project",
    "toomics": "Toomics",
    "anilist": "AniList",
}

SEARCH_SOURCES = ["mangasbrasuka", "mangalivre", "mangadex", "toomics"]
PT_COMPLETE_SOURCES = ["mangasbrasuka", "mangalivre", "toomics"]

SOURCE_RELIABILITY = {
    "mangalivre": 0.94,
    "mangasbrasuka": 0.92,
    "toomics": 0.78,
    "mangadex": 0.72,
}

SPARSE_CHAPTER_THRESHOLD = 8
MIN_SOURCE_RELEVANCE = 0.45

CURATED_CATALOG = [
    {
        "title": "Tensei Shitara Slime Datta Ken",
        "aliases": [
            "Tensei Shitara Slime Datta Ken",
            "Tensei Shitara Slime Datta Ken Manga",
            "That Time I Got Reincarnated as a Slime",
            "Slime Datta Ken",
            "Tensei Slime",
        ],
        "url": "https://mangasbrasuka.com.br/manga/tensei-shitara-slime-datta-ken/",
        "provider": "mangasbrasuka",
        "section": "Fantasia",
        "genres": ["Aventura", "Fantasia", "Comedia"],
    },
    {
        "title": "Soul Eater",
        "aliases": ["Soul Eater"],
        "query": "Soul Eater",
        "provider": "mangalivre",
        "section": "Acao",
        "genres": ["Acao", "Fantasia", "Comedia"],
    },
    {
        "title": "One Piece",
        "aliases": ["One Piece"],
        "url": "pieceproject://one-piece",
        "provider": "pieceproject",
        "section": "Aventura",
        "genres": ["Acao", "Aventura", "Comedia"],
    },
]


@dataclass
class CacheEntry:
    saved_at: float
    data: dict


@dataclass
class ImageCacheEntry:
    saved_at: float
    content: bytes
    media_type: str


reader = MangaReader(
    SimpleNamespace(
        librewolf_path=None,
        show_browser=False,
        timeout=35,
        readfull_api_url="https://readfullapi.herokuapp.com",
        dragontea_browser="edge",
    )
)
catalog_cache: CacheEntry | None = None
search_cache: dict[str, CacheEntry] = {}
source_resolution_cache: dict[str, CacheEntry] = {}
anilist_cache: dict[str, CacheEntry] = {}
image_cache: dict[str, ImageCacheEntry] = {}


app = FastAPI(
    title="MangaTemp API",
    version="0.2.0",
    description="API REST local com fontes reais para alimentar o front-end React do MangaTemp.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "tauri://localhost",
    ],
    allow_methods=["GET"],
    allow_headers=["*"],
)


def _cache_is_fresh(entry: CacheEntry | None, ttl: int) -> bool:
    return bool(entry and time.time() - entry.saved_at < ttl)


def _slug(value: str) -> str:
    normalized = normalize_match_text(value)
    return "-".join(part for part in normalized.split() if part)


def _source_label(provider: str | None) -> str:
    provider = str(provider or "").lower()
    return SOURCE_LABELS.get(provider, provider.title() if provider else "Fonte")


def _is_remote_image_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _proxy_image_url(url: str) -> str:
    url = str(url or "").strip()
    if not _is_remote_image_url(url):
        return ""
    return f"/api/image?url={quote(url, safe='')}"


def _guess_provider(item: dict) -> str:
    provider = str(item.get("provider") or item.get("source") or "").lower()
    url = str(item.get("url") or "")
    if provider:
        return provider
    if "mangasbrasuka" in url:
        return "mangasbrasuka"
    if "mangalivre" in url:
        return "mangalivre"
    if "toomics" in url:
        return "toomics"
    if "mangadex" in url:
        return "mangadex"
    if url.startswith("pieceproject://"):
        return "pieceproject"
    return "mangadex"


def _normalize_manga_item(item: dict, *, section: str = "") -> dict | None:
    title = str(item.get("title") or "").strip()
    source_url = str(item.get("url") or item.get("source_url") or "").strip()
    if not title or not source_url:
        return None

    provider = _guess_provider(item)
    poster_original = str(item.get("poster") or item.get("cover_url") or "").strip()
    fallback_originals = [
        str(url).strip()
        for url in (item.get("poster_fallbacks") or [])
        if str(url or "").strip()
    ]
    genres = [
        str(genre).strip()
        for genre in (item.get("genres") or [])
        if str(genre or "").strip()
    ]
    content_rating = str(item.get("content_rating") or item.get("contentRating") or "").lower()
    if content_rating in {"erotica", "pornographic"}:
        return None

    return {
        "id": str(item.get("id") or _slug(title) or source_url),
        "title": title,
        "slug": _slug(title),
        "source_url": source_url,
        "provider": provider,
        "source": _source_label(provider),
        "section": section or str(item.get("section") or ""),
        "cover_url": _proxy_image_url(poster_original),
        "cover_original_url": poster_original,
        "cover_fallbacks": [_proxy_image_url(url) for url in fallback_originals if _proxy_image_url(url)],
        "cover_original_fallbacks": fallback_originals,
        "genres": genres[:8],
        "description": item.get("description") or "",
        "authors": item.get("authors") or [],
        "chapter_count": item.get("chapter_count"),
        "rating": item.get("rating"),
        "status": item.get("status") or "",
        "language": item.get("language") or "pt-br",
        "alternative_titles": item.get("alternative_titles") or [],
    }


def _provider_preference_score(item: dict) -> tuple[int, float, float]:
    chapter_count = int(item.get("chapter_count") or 0)
    reliability = SOURCE_RELIABILITY.get(str(item.get("provider") or "").lower(), 0.5)
    relevance = float(item.get("relevance") or 0)
    return chapter_count, reliability, relevance


def _merge_duplicate(existing: dict, candidate: dict) -> dict:
    preferred = (
        candidate
        if _provider_preference_score(candidate) > _provider_preference_score(existing)
        else existing
    )
    secondary = existing if preferred is candidate else candidate
    merged = dict(preferred)
    for key in ("cover_url", "cover_original_url", "description", "authors", "chapter_count", "rating", "status"):
        if not merged.get(key) and secondary.get(key):
            merged[key] = secondary[key]
        elif key == "chapter_count":
            existing_count = int(merged.get("chapter_count") or 0)
            secondary_count = int(secondary.get("chapter_count") or 0)
            if secondary_count > existing_count:
                merged["chapter_count"] = secondary_count
    merged["cover_fallbacks"] = list(
        dict.fromkeys([
            *(merged.get("cover_fallbacks") or []),
            *(secondary.get("cover_fallbacks") or []),
        ])
    )
    merged["genres"] = list(
        dict.fromkeys([
            *(merged.get("genres") or []),
            *(secondary.get("genres") or []),
        ])
    )[:8]
    return merged


def _dedupe(items: list[dict]) -> list[dict]:
    by_identity: dict[str, int] = {}
    result: list[dict] = []
    for item in items:
        title_key = normalize_match_text(str(item.get("title") or ""))
        url_key = str(item.get("source_url") or item.get("id") or "")
        identity = title_key or url_key
        if not identity:
            continue
        if identity in by_identity:
            index = by_identity[identity]
            result[index] = _merge_duplicate(result[index], item)
            continue
        by_identity[identity] = len(result)
        if url_key:
            by_identity.setdefault(url_key, len(result))
        result.append(item)
    return result


def _build_sections_from_items(items: list[dict], per_section: int = 18) -> list[dict]:
    """Fallback: group items by their 'section' field when catalog sections are empty."""
    grouped: dict[str, list[dict]] = {}
    for item in items:
        sec = str(item.get("section") or "Destaques").strip() or "Destaques"
        grouped.setdefault(sec, []).append(item)
    sections = []
    for title, sec_items in grouped.items():
        if sec_items:
            sections.append({"title": title, "items": sec_items[:per_section]})
    return sections


def _chapter_count_for_source(source_url: str) -> int:
    try:
        payload = reader.list_chapters(source_url)
        return int(payload.get("count") or 0)
    except Exception:
        return 0


def _curated_match_score(query: str, raw: dict) -> float:
    query_norm = normalize_match_text(query)
    if not query_norm:
        return 0.0
    candidates = [
        str(raw.get("title") or ""),
        *[str(alias) for alias in raw.get("aliases") or []],
    ]
    best = 0.0
    for candidate in candidates:
        candidate_norm = normalize_match_text(candidate)
        if not candidate_norm:
            continue
        if query_norm == candidate_norm:
            return 1.0
        if len(query_norm) >= 10 and (query_norm in candidate_norm or candidate_norm in query_norm):
            best = max(best, 0.96)
        best = max(best, fuzzy_match_score(query, candidate))
    return best


def _curated_override_for_title(title: str) -> dict | None:
    matches = [
        (_curated_match_score(title, raw), raw)
        for raw in CURATED_CATALOG
    ]
    matches.sort(key=lambda item: item[0], reverse=True)
    if not matches or matches[0][0] < 0.78:
        return None
    return matches[0][1]


def _enrich_curated_item(raw: dict) -> dict | None:
    payload = dict(raw)
    if not payload.get("url") and payload.get("query"):
        provider = str(payload.get("provider") or "")
        query = str(payload.get("query") or "")
        search_payload = _search_source(provider, query, limit=4) if provider else []
        if search_payload:
            payload.update(
                {
                    "url": search_payload[0].get("source_url"),
                    "poster": search_payload[0].get("cover_original_url"),
                    "description": search_payload[0].get("description"),
                    "authors": search_payload[0].get("authors"),
                }
            )
    item = _normalize_manga_item(payload, section=str(payload.get("section") or "Destaques"))
    if not item:
        return None
    source_url = str(item.get("source_url") or "")
    if source_url:
        try:
            metadata = reader.manga_metadata(source_url, include_chapters=True)
            manga = metadata.get("manga") or {}
            item["chapter_count"] = metadata.get("chapter_count") or item.get("chapter_count")
            if manga.get("description") and not item.get("description"):
                item["description"] = manga["description"]
            if manga.get("authors") and not item.get("authors"):
                item["authors"] = manga["authors"]
            if manga.get("genres"):
                item["genres"] = list(dict.fromkeys([*(item.get("genres") or []), *manga["genres"]]))[:8]
            poster = str(manga.get("poster") or "").strip()
            if poster and not item.get("cover_url"):
                item["cover_url"] = _proxy_image_url(poster)
                item["cover_original_url"] = poster
            if manga.get("rating", {}).get("score") and not item.get("rating"):
                item["rating"] = float(manga["rating"]["score"])
            if manga.get("status") and not item.get("status"):
                item["status"] = manga["status"]
            alt_titles = manga.get("alternative_titles") or []
            if isinstance(alt_titles, list):
                item["alternative_titles"] = alt_titles
        except Exception:
            count = _chapter_count_for_source(source_url)
            if count:
                item["chapter_count"] = count
    return item


def _curated_catalog_items() -> list[dict]:
    items: list[dict] = []
    for raw in CURATED_CATALOG:
        item = _enrich_curated_item(raw)
        if item:
            items.append(item)
    return _dedupe(items)


def _apply_curated_source_overrides(items: list[dict], query: str) -> list[dict]:
    """Substitui obras curadas por fontes preferidas quando a busca bate com o titulo."""
    updated = list(items)
    for raw in CURATED_CATALOG:
        source_url = str(raw.get("url") or "").strip()
        if not source_url:
            continue
        title = str(raw.get("title") or "").strip()
        if _curated_match_score(query, raw) < 0.78:
            continue
        curated = _enrich_curated_item({**raw, "section": "Busca"})
        if not curated:
            continue
        aliases = [title, *[str(alias) for alias in raw.get("aliases") or []]]
        updated = [
            item
            for item in updated
            if max(
                fuzzy_match_score(alias, str(item.get("title") or ""))
                for alias in aliases
            ) < 0.92
        ]
        curated["relevance"] = max(
            float(curated.get("relevance") or 0),
            max((float(item.get("relevance") or 0) for item in items), default=0.0),
            1.0 if _curated_match_score(query, raw) >= 0.98 else 0.95,
        )
        updated.insert(0, curated)
    return updated


def _resolve_best_sources(items: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = {}
    for item in items:
        identity = normalize_match_text(str(item.get("title") or "")) or str(item.get("source_url") or "")
        grouped.setdefault(identity, []).append(item)

    resolved: list[dict] = []
    to_race: list[list[dict]] = []
    for group in grouped.values():
        providers = {str(item.get("provider") or "") for item in group}
        if len(group) == 1 or len(providers) == 1:
            resolved.append(group[0])
            continue
        to_race.append(group)

    if not to_race:
        return resolved

    def score_group(group: list[dict]) -> dict:
        scored: list[tuple[tuple[int, float, float], dict]] = []
        for item in group:
            source_url = str(item.get("source_url") or "")
            chapter_count = int(item.get("chapter_count") or 0)
            if source_url and chapter_count <= 0:
                chapter_count = _chapter_count_for_source(source_url)
                if chapter_count:
                    item = dict(item)
                    item["chapter_count"] = chapter_count
            provider = str(item.get("provider") or "").lower()
            if provider == "mangadex" and chapter_count < SPARSE_CHAPTER_THRESHOLD:
                chapter_count = 0
            scored.append(
                (
                    (
                        chapter_count,
                        SOURCE_RELIABILITY.get(provider, 0.5),
                        float(item.get("relevance") or 0),
                    ),
                    item,
                )
            )
        scored.sort(reverse=True)
        return scored[0][1]

    max_workers = min(6, len(to_race))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(score_group, group) for group in to_race]
        for future in as_completed(futures):
            try:
                resolved.append(future.result())
            except Exception:
                continue
    return resolved


def _catalog_sections_from_mangadex(limit: int) -> tuple[list[dict], list[dict]]:
    all_items: list[dict] = []
    sections: list[dict] = []

    curated_items = _curated_catalog_items()
    if curated_items:
        sections.append({"title": "Destaques", "items": curated_items})
        all_items.extend(curated_items)

    trending = reader.trending_mangadex(limit=min(max(limit, 24), 100))
    trending_items: list[dict] = []
    for raw in trending.get("results") or []:
        item = _normalize_manga_item(raw, section="Em alta")
        if item:
            trending_items.append(item)
    trending_items = _dedupe(trending_items)[:18]
    if trending_items:
        sections.append({"title": "Em alta", "items": trending_items})
        all_items.extend(trending_items)

    per_genre = max(8, min(18, limit // max(1, len(MANGADEX_GENRES) // 2)))
    # Use no language filter so we get covers even for manga not yet translated to pt-br
    catalog = reader.catalog_mangadex(MANGADEX_GENRES, limit_per_genre=per_genre, lang="")
    for section, section_items in (catalog.get("sections") or {}).items():
        normalized_items: list[dict] = []
        for raw in section_items or []:
            item = _normalize_manga_item(raw, section=section)
            if item:
                normalized_items.append(item)
        normalized_items = _dedupe(normalized_items)[:per_genre]
        if normalized_items:
            sections.append({"title": section, "items": normalized_items})
            all_items.extend(normalized_items)

    # If genre sections came back empty, use the trending items split into a generic section
    if len(sections) <= 1 and all_items:
        sections = _build_sections_from_items(all_items, per_section=per_genre)

    return _dedupe(all_items), sections


def _build_catalog(limit: int) -> dict:
    global catalog_cache
    if _cache_is_fresh(catalog_cache, CATALOG_CACHE_TTL_SECONDS):
        data = dict(catalog_cache.data)
        data["items"] = data["items"][:limit]
        data["limit"] = limit
        return data

    items, sections = _catalog_sections_from_mangadex(max(limit, DEFAULT_LIMIT))
    _enrich_items_from_anilist(items[:10], max_workers=4)

    # Last-resort: if sections still empty but items exist, build sections from item metadata
    if not sections and items:
        sections = _build_sections_from_items(items)

    data = {
        "items": items,
        "sections": sections,
        "total": len(items),
        "limit": limit,
        "offset": 0,
        "sources": ["MangaDex", "MangasBrasuka", "MangaLivre"],
        "cached": False,
    }
    catalog_cache = CacheEntry(time.time(), data)
    data = dict(data)
    data["items"] = data["items"][:limit]
    return data


def _search_source(name: str, query: str, limit: int) -> list[dict]:
    if name == "mangadex":
        payload = reader.search_mangadex(query, limit=limit)
    elif name == "mangalivre":
        payload = reader.search_mangalivre(query, limit=limit)
    elif name == "toomics":
        payload = reader.search_toomics(query, limit=limit, lang="pt-br")
    elif name == "mangasbrasuka":
        payload = reader.search_mangasbrasuka(query, limit=limit)
    else:
        return []

    items = []
    for raw in payload.get("results") or []:
        item = _normalize_manga_item(raw, section="Busca")
        if item:
            items.append(item)
    return items


def _copy_with_chapter_count(item: dict) -> dict:
    copied = dict(item)
    count = int(copied.get("chapter_count") or 0)
    source_url = str(copied.get("source_url") or "")
    if source_url and count <= 0:
        count = _chapter_count_for_source(source_url)
        if count:
            copied["chapter_count"] = count
    return copied


def _source_score_tuple(item: dict) -> tuple[int, float, float]:
    provider = str(item.get("provider") or "").lower()
    chapter_count = int(item.get("chapter_count") or 0)
    if provider == "mangadex" and chapter_count < SPARSE_CHAPTER_THRESHOLD:
        chapter_count = 0
    return (
        chapter_count,
        SOURCE_RELIABILITY.get(provider, 0.5),
        float(item.get("relevance") or 0),
    )


def _current_source_item(title: str, source_url: str) -> dict | None:
    if not source_url:
        return None
    return _normalize_manga_item(
        {
            "title": title or source_url,
            "url": source_url,
            "provider": _guess_provider({"url": source_url}),
        },
        section="Fonte atual",
    )


def _resolve_best_source_for_title(title: str, current_source_url: str, lang: str = "pt-br") -> dict | None:
    title = title.strip()
    current_source_url = current_source_url.strip()
    if not title and not current_source_url:
        return None

    cache_key = f"{normalize_match_text(title)}|{current_source_url}|{normalize_match_text(lang)}"
    cached = source_resolution_cache.get(cache_key)
    if _cache_is_fresh(cached, SOURCE_RESOLUTION_CACHE_TTL_SECONDS):
        return dict(cached.data.get("item") or {})

    current = _current_source_item(title, current_source_url)
    if current:
        current = _copy_with_chapter_count(current)

    curated_raw = _curated_override_for_title(title)
    if curated_raw:
        curated = _enrich_curated_item({**curated_raw, "section": "Fonte completa"})
        if curated:
            source_resolution_cache[cache_key] = CacheEntry(time.time(), {"item": curated})
            return curated

    if not title:
        return current

    candidates: list[dict] = []
    with ThreadPoolExecutor(max_workers=len(PT_COMPLETE_SOURCES)) as executor:
        futures = {
            executor.submit(_search_source, source, title, 5): source
            for source in PT_COMPLETE_SOURCES
        }
        for future in as_completed(futures):
            try:
                candidates.extend(future.result())
            except Exception:
                continue

    scored_candidates: list[dict] = []
    for item in candidates:
        relevance = _search_match_score(title, item)
        if relevance < MIN_SOURCE_RELEVANCE:
            continue
        item = dict(item)
        item["relevance"] = round(relevance, 4)
        item = _copy_with_chapter_count(item)
        if int(item.get("chapter_count") or 0) <= 0:
            continue
        scored_candidates.append(item)

    all_items = [*scored_candidates]
    if current:
        all_items.append(current)
    if not all_items:
        return None

    all_items.sort(key=_source_score_tuple, reverse=True)
    best = all_items[0]
    if current and best.get("source_url") == current.get("source_url"):
        source_resolution_cache[cache_key] = CacheEntry(time.time(), {"item": current})
        return current

    current_count = int((current or {}).get("chapter_count") or 0)
    best_count = int(best.get("chapter_count") or 0)
    current_provider = str((current or {}).get("provider") or "").lower()
    should_swap = (
        not current
        or best_count > current_count
        or (current_provider == "mangadex" and best_count > 0)
    )
    resolved = best if should_swap else current
    source_resolution_cache[cache_key] = CacheEntry(time.time(), {"item": resolved})
    return resolved


def _search_match_score(query: str, item: dict) -> float:
    alternative_titles = item.get("alternative_titles") or []
    if not isinstance(alternative_titles, list):
        alternative_titles = [str(alternative_titles)]
    title_candidates = [
        str(item.get("title") or ""),
        *[str(title) for title in alternative_titles],
    ]
    searchable = normalize_match_text(" ".join(title_candidates))
    query_norm = normalize_match_text(query)
    query_tokens = [token for token in query_norm.split() if len(token) >= 2]
    searchable_tokens = set(searchable.split())
    if query_norm and query_norm in searchable:
        return 1.0
    if query_tokens:
        token_hits = sum(
            1 for token in query_tokens
            if token in searchable_tokens or token in searchable
        )
        required_hits = len(query_tokens) if len(query_tokens) <= 2 else max(2, round(len(query_tokens) * 0.65))
        if token_hits < required_hits:
            return 0.0
    return fuzzy_match_score(query, *title_candidates)


def _anilist_metadata(title: str) -> dict:
    key = normalize_match_text(title)
    cached = anilist_cache.get(key)
    if _cache_is_fresh(cached, ANILIST_CACHE_TTL_SECONDS):
        return dict(cached.data)
    metadata = reader.anilist_metadata(title)
    anilist_cache[key] = CacheEntry(time.time(), metadata)
    return dict(metadata)


def _apply_anilist_metadata(item: dict, metadata: dict) -> None:
    cover = str(metadata.get("poster") or "").strip()
    if cover and not item.get("cover_url"):
        item["cover_url"] = _proxy_image_url(cover)
        item["cover_original_url"] = cover
        item["cover_fallbacks"] = [
            _proxy_image_url(str(url).strip())
            for url in metadata.get("poster_fallbacks") or []
            if _proxy_image_url(str(url or "").strip())
        ]
        item["cover_original_fallbacks"] = [
            str(url).strip()
            for url in metadata.get("poster_fallbacks") or []
            if str(url or "").strip()
        ]
    if metadata.get("average_score") and not item.get("rating"):
        item["rating"] = round(float(metadata["average_score"]) / 10, 1)
    if metadata.get("description") and not item.get("description"):
        item["description"] = metadata["description"]
    if metadata.get("authors") and not item.get("authors"):
        item["authors"] = metadata["authors"]
    if metadata.get("status") and not item.get("status"):
        item["status"] = metadata["status"]
    if metadata.get("genres") and not item.get("genres"):
        item["genres"] = metadata["genres"]
    item["anilist_url"] = metadata.get("url") or item.get("anilist_url") or ""


def _enrich_items_from_anilist(items: list[dict], max_workers: int = 4) -> None:
    candidates = [
        item for item in items
        if item.get("title")
        and (
            not item.get("rating")
            or not item.get("authors")
            or not item.get("description")
            or not item.get("cover_url")
        )
    ]
    if not candidates:
        return
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_anilist_metadata, str(item.get("title") or "")): item
            for item in candidates
        }
        for future in as_completed(futures):
            item = futures[future]
            try:
                _apply_anilist_metadata(item, future.result())
            except Exception:
                continue


def _fill_missing_cover_from_anilist(items: list[dict], limit: int = 4) -> None:
    _enrich_items_from_anilist(items[:limit], max_workers=4)


def _image_referer(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if "mangadex.org" in host:
        return "https://mangadex.org/"
    if "mugiverso.com" in host or "mangasbrasuka" in host:
        return "https://mangasbrasuka.com.br/"
    if "anilist.co" in host or "anilistcdn" in host:
        return "https://anilist.co/"
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}/"


def _guess_image_media_type(url: str, content: bytes, fallback: str) -> str:
    guessed = mimetypes.guess_type(urlparse(url).path)[0]
    if guessed and guessed.startswith("image/"):
        return guessed
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"GIF87a") or content.startswith(b"GIF89a"):
        return "image/gif"
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    return fallback


def _prune_image_cache() -> None:
    if len(image_cache) <= IMAGE_CACHE_MAX_ITEMS:
        return
    expired_before = time.time() - IMAGE_CACHE_TTL_SECONDS
    for key, entry in list(image_cache.items()):
        if entry.saved_at < expired_before:
            image_cache.pop(key, None)
    if len(image_cache) <= IMAGE_CACHE_MAX_ITEMS:
        return
    for key, _entry in sorted(image_cache.items(), key=lambda pair: pair[1].saved_at)[
        : len(image_cache) - IMAGE_CACHE_MAX_ITEMS
    ]:
        image_cache.pop(key, None)


def _fetch_image(url: str) -> ImageCacheEntry:
    cached = image_cache.get(url)
    if cached and time.time() - cached.saved_at < IMAGE_CACHE_TTL_SECONDS:
        return cached

    response = requests.get(
        url,
        timeout=20,
        headers={
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            "User-Agent": "Mozilla/5.0",
            "Referer": _image_referer(url),
        },
    )
    response.raise_for_status()
    media_type = response.headers.get("content-type", "image/jpeg").split(";")[0].strip()
    if not media_type.startswith("image/"):
        guessed_type = _guess_image_media_type(url, response.content, media_type)
        if not guessed_type.startswith("image/"):
            raise RuntimeError(f"URL nao retornou imagem: {media_type}")
        media_type = guessed_type

    entry = ImageCacheEntry(
        saved_at=time.time(),
        content=response.content,
        media_type=media_type,
    )
    image_cache[url] = entry
    _prune_image_cache()
    return entry


def _prefetch_cover_images(items: list[dict], limit: int = 48) -> None:
    urls: list[str] = []
    for item in items:
        for url in [
            item.get("cover_original_url"),
            *(item.get("cover_original_fallbacks") or []),
        ]:
            url = str(url or "").strip()
            if url and url not in urls and _is_remote_image_url(url):
                urls.append(url)
                break
        if len(urls) >= limit:
            break
    if not urls:
        return
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(_fetch_image, url) for url in urls]
        for future in as_completed(futures):
            try:
                future.result()
            except Exception:
                continue


def _search_mangas(query: str, limit: int) -> dict:
    cache_key = f"{normalize_match_text(query)}:{limit}"
    cached = search_cache.get(cache_key)
    if _cache_is_fresh(cached, SEARCH_CACHE_TTL_SECONDS):
        return {**cached.data, "cached": True}

    sources = SEARCH_SOURCES
    items: list[dict] = []
    errors: list[str] = []
    with ThreadPoolExecutor(max_workers=len(sources)) as executor:
        futures = {
            executor.submit(_search_source, source, query, limit): source
            for source in sources
        }
        for future in as_completed(futures):
            source = futures[future]
            try:
                items.extend(future.result())
            except Exception as exc:
                errors.append(f"{_source_label(source)}: {exc}")

    normalized_query = normalize_match_text(query)
    items = _resolve_best_sources(items)
    items = _dedupe(items)
    items = _apply_curated_source_overrides(items, query)
    items = _dedupe(items)
    relevant_items = []
    for item in items:
        score = _search_match_score(query, item)
        title_norm = normalize_match_text(str(item.get("title") or ""))
        query_tokens = [token for token in normalized_query.split() if len(token) >= 2]
        title_has_query_token = any(token in title_norm for token in query_tokens)
        if len(query_tokens) > 1 and not title_has_query_token and normalized_query not in title_norm:
            score = 0.0
        if score >= 0.45:
            item["relevance"] = round(score, 4)
            relevant_items.append(item)
    items = relevant_items
    items.sort(
        key=lambda item: (
            0 if normalize_match_text(item["title"]) == normalized_query else 1,
            -int(item.get("chapter_count") or 0),
            -SOURCE_RELIABILITY.get(str(item.get("provider") or "").lower(), 0.5),
            -float(item.get("relevance") or 0),
            item["title"].lower(),
        )
    )
    _fill_missing_cover_from_anilist(items[:limit])
    data = {
        "items": items[:limit],
        "sections": [{"title": "Resultados", "items": items[:limit]}],
        "total": len(items),
        "limit": limit,
        "offset": 0,
        "sources": [_source_label(source) for source in sources],
        "errors": errors,
        "cached": False,
    }
    search_cache[cache_key] = CacheEntry(time.time(), data)
    return data


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/mangas")
def list_mangas(
    background_tasks: BackgroundTasks,
    q: str = Query(default="", description="Busca por titulo em fontes reais."),
    genre: str = Query(default="", description="Filtro local por genero."),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    query = q.strip()
    if query:
        data = _search_mangas(query, limit=max(limit + offset, limit))
    else:
        data = _build_catalog(limit=max(limit + offset, limit))

    items = data.get("items") or []
    sections = data.get("sections") or [{"title": "Resultados", "items": items}]
    genre_filter = normalize_match_text(genre)
    if genre_filter:
        items = [
            item
            for item in items
            if any(normalize_match_text(genre_name) == genre_filter for genre_name in item.get("genres") or [])
        ]
        sections = [
            {
                "title": section.get("title"),
                "items": [
                    item for item in section.get("items") or []
                    if any(normalize_match_text(genre_name) == genre_filter for genre_name in item.get("genres") or [])
                ],
            }
            for section in sections
        ]
        sections = [section for section in sections if section["items"]]
    paged = items[offset : offset + limit]
    prefetch_candidates = []
    for section in sections:
        prefetch_candidates.extend((section.get("items") or [])[:8])
    prefetch_candidates.extend(paged[:24])
    background_tasks.add_task(_prefetch_cover_images, _dedupe(prefetch_candidates), 64)
    return {
        **data,
        "items": paged,
        "sections": sections,
        "total": len(items),
        "limit": limit,
        "offset": offset,
    }


@app.get("/api/chapters")
def list_chapters(
    source_url: str = Query(..., description="URL ou source id da obra."),
    title: str = Query(default="", description="Titulo usado para escolher fonte mais completa."),
    lang: str = Query(default="pt-br"),
    auto_source: bool = Query(default=True, description="Troca MangaDex por fonte com mais capitulos quando possivel."),
) -> dict:
    requested_source = unquote(source_url).strip()
    source = requested_source
    if not source:
        raise HTTPException(status_code=400, detail="source_url vazio.")
    resolved_item = None
    if auto_source and title.strip():
        resolved_item = _resolve_best_source_for_title(title, source, lang)
        resolved_url = str((resolved_item or {}).get("source_url") or "").strip()
        if resolved_url:
            source = resolved_url
    try:
        payload = reader.list_chapters(source, lang=lang)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    payload["requested_source_url"] = requested_source
    payload["resolved_source_url"] = source
    if resolved_item:
        payload["resolved_manga"] = resolved_item
        payload["resolved_source"] = _source_label(payload.get("provider") or resolved_item.get("provider"))
    return payload


def _reader_image_url(index: int) -> str:
    return f"/api/reader-image/{index}?v={int(time.time())}"


@app.get("/api/chapter")
def open_chapter(
    source_url: str = Query(..., description="URL do capitulo."),
    lang: str = Query(default="pt-br"),
) -> dict:
    source = unquote(source_url).strip()
    if not source:
        raise HTTPException(status_code=400, detail="source_url vazio.")
    try:
        payload = reader.chapter_metadata(
            source,
            cache_pages=False,
            include_source_urls=True,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    images = []
    for image in payload.get("images") or []:
        image = dict(image)
        source_image_url = str(image.get("source_url") or "").strip()
        if _is_remote_image_url(source_image_url):
            image["src"] = _proxy_image_url(source_image_url)
        else:
            image["src"] = _reader_image_url(int(image.get("index") or len(images) + 1))
        images.append(image)

    payload["images"] = images
    payload["count"] = len(images)
    payload["language"] = payload.get("language") or lang
    return payload


@app.get("/api/reader-image/{index}")
def reader_image(index: int) -> FileResponse:
    try:
        path, content_type = reader.get_image(index)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(path, media_type=content_type)


@app.get("/api/image")
def proxy_image(url: str = Query(..., description="URL remota da imagem.")) -> Response:
    remote_url = unquote(url).strip()
    if not _is_remote_image_url(remote_url):
        raise HTTPException(status_code=400, detail="URL de imagem invalida.")
    try:
        image = _fetch_image(remote_url)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return Response(
        content=image.content,
        media_type=image.media_type,
        headers={
            "Cache-Control": "no-store",
            "X-MangaTemp-Image-Cache": "memory",
        },
    )
