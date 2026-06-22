from __future__ import annotations

import time
import mimetypes
import json
import logging
import random
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed, wait
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, quote, unquote, urlparse

import requests
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from schemas import (
    HomeResponse,
    MangaHomeItem,
    MangaSearchItem,
    SearchResponse,
)

from reader_server import (
    DEFAULT_HEADERS,
    MangaReader,
    fuzzy_match_score,
    normalize_match_text,
)


CATALOG_CACHE_TTL_SECONDS = 30 * 60
SEARCH_CACHE_TTL_SECONDS = 5 * 60
SOURCE_RESOLUTION_CACHE_TTL_SECONDS = 10 * 60
CHAPTER_COUNT_CACHE_TTL_SECONDS = 20 * 60
CHAPTERS_CACHE_TTL_SECONDS = 10 * 60
IMAGE_CACHE_TTL_SECONDS = 15 * 60
IMAGE_CACHE_MAX_ITEMS = 1000
ANILIST_CACHE_TTL_SECONDS = 12 * 60 * 60
KITSU_CACHE_TTL_SECONDS = 12 * 60 * 60
TRANSLATION_CACHE_TTL_SECONDS = 24 * 60 * 60
DEFAULT_LIMIT = 80
SOURCE_SEARCH_TIMEOUT_SECONDS = 8.0
SOURCE_RESOLUTION_TIMEOUT_SECONDS = 5.0
CATALOG_SNAPSHOT_TTL_SECONDS = 6 * 60 * 60
CATALOG_SNAPSHOT_PATH = Path(__file__).resolve().parent / ".cache" / "catalog.json"

# Capitulos basicos cacheados em disco (id/numero/titulo/lingua) -> rota local,
# sem fetch externo a cada clique. TTL longo; sobrevive a restart.
CHAPTERS_DISK_TTL_SECONDS = 24 * 60 * 60
CHAPTERS_SNAPSHOT_PATH = Path(__file__).resolve().parent / ".cache" / "chapters.json"

# Resiliencia da busca de capitulos: retry com backoff exponencial + rotacao de UA.
CHAPTERS_FETCH_ATTEMPTS = 4          # 4 tentativas
CHAPTERS_BACKOFF_BASE = 2.0          # espera 1s, 2s, 4s entre tentativas
CHAPTERS_BACKOFF_START = 1.0

logger = logging.getLogger("mangatemp")

# User-Agents reais p/ rotacionar e fugir de filtros antibot/rate-limit.
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
]

# Arquivos estaticos servidos pelo FastAPI (capas baixadas na raspagem ficam aqui,
# eliminando o proxy de imagem em tempo de execucao na home).
STATIC_DIR = Path(__file__).resolve().parent / "static"
COVERS_DIR = STATIC_DIR / "covers"
COVERS_DIR.mkdir(parents=True, exist_ok=True)

# Placeholder "Sem Capa" servido quando a obra nao tem capa local valida.
# Fica em static/ (fora de covers/) p/ nao ser limpo junto com o cache de capas.
PLACEHOLDER_PATH = STATIC_DIR / "placeholder.svg"
PLACEHOLDER_URL = "/static/placeholder.svg"
_PLACEHOLDER_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="320" height="460" viewBox="0 0 320 460">
  <defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#27272a"/><stop offset="1" stop-color="#161618"/></linearGradient></defs>
  <rect width="320" height="460" fill="url(#g)"/>
  <g fill="none" stroke="#52525b" stroke-width="6" stroke-linecap="round" stroke-linejoin="round">
    <rect x="100" y="140" width="120" height="160" rx="12"/>
    <path d="M130 140 V300 M170 140 V300"/>
  </g>
  <text x="160" y="360" text-anchor="middle" font-family="Segoe UI, Arial, sans-serif"
        font-size="30" font-weight="700" fill="#a1a1aa">Sem Capa</text>
</svg>
"""


def _ensure_placeholder() -> None:
    try:
        if not PLACEHOLDER_PATH.exists():
            PLACEHOLDER_PATH.write_text(_PLACEHOLDER_SVG, encoding="utf-8")
    except Exception:
        pass


_ensure_placeholder()

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
    "yumo": "YomuMangas",
    "sakura": "Sakura Mangas",
}

SEARCH_SOURCES = ["sakura", "yumo", "mangasbrasuka", "mangalivre", "mangadex"]
PT_COMPLETE_SOURCES = ["sakura", "yumo", "mangasbrasuka", "mangalivre"]

SOURCE_RELIABILITY = {
    "sakura": 0.98,
    "yumo": 0.96,
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
        "poster": "https://cdn.mugiverso.com/mangasbrasuka/wp-content/uploads/2026/02/that-time-i-got-reincarnated-as-a-slime-22-capa.webp",
        "provider": "mangasbrasuka",
        "section": "Fantasia",
        "genres": ["Aventura", "Fantasia", "Comedia"],
    },
    {
        "title": "Soul Eater",
        "aliases": ["Soul Eater"],
        "url": "https://mangalivre.blog/manga/soul-eater/",
        "poster": "https://mangalivre.blog/wp-content/uploads/2025/04/ae5b4ce8-a50d-4bbb-9cd6-7456b97fdecd.jpg.512.jpg",
        "provider": "mangalivre",
        "section": "Acao",
        "genres": ["Acao", "Fantasia", "Comedia"],
    },
    {
        "title": "Moby Dick",
        "aliases": ["Moby Dick", "Moby-Dick"],
        "url": "https://mangasbrasuka.com.br/manga/moby-dick/",
        "poster": "https://cdn.mugiverso.com/mangasbrasuka/wp-content/uploads/2026/02/Moby-Dick.webp",
        "provider": "mangasbrasuka",
        "section": "Drama",
        "genres": ["Drama", "Acao", "Manhwa"],
    },
    {
        "title": "One Piece",
        "aliases": ["One Piece"],
        "url": "pieceproject://one-piece",
        "poster": "https://i.ibb.co/NnFxkGJ/manga1130.jpg",
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
catalog_refresh_lock = threading.Lock()
catalog_refreshing = False
search_cache: dict[str, CacheEntry] = {}
source_resolution_cache: dict[str, CacheEntry] = {}
chapter_count_cache: dict[str, CacheEntry] = {}
chapters_cache: dict[str, CacheEntry] = {}
anilist_cache: dict[str, CacheEntry] = {}
kitsu_cache: dict[str, CacheEntry] = {}
translation_cache: dict[str, CacheEntry] = {}
image_cache: dict[str, ImageCacheEntry] = {}

_chapters_disk_lock = threading.Lock()


def _load_chapters_snapshot() -> None:
    """Carrega o cache de capitulos do disco p/ a memoria no startup."""
    try:
        if not CHAPTERS_SNAPSHOT_PATH.exists():
            return
        raw = json.loads(CHAPTERS_SNAPSHOT_PATH.read_text(encoding="utf-8"))
        for key, entry in (raw or {}).items():
            if isinstance(entry, dict) and isinstance(entry.get("data"), dict):
                chapters_cache[key] = CacheEntry(float(entry.get("saved_at") or 0), entry["data"])
    except Exception:
        pass


def _save_chapters_snapshot() -> None:
    """Persiste o cache de capitulos no disco (.cache/chapters.json)."""
    try:
        CHAPTERS_SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _chapters_disk_lock:
            payload = {
                key: {"saved_at": entry.saved_at, "data": entry.data}
                for key, entry in chapters_cache.items()
            }
        CHAPTERS_SNAPSHOT_PATH.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


_load_chapters_snapshot()


def _rotate_headers(attempt: int) -> None:
    """Rotaciona User-Agent + headers reais (mutando o DEFAULT_HEADERS que os
    fetchers do reader_server reaproveitam). O self.lock do reader serializa as
    chamadas, entao a mutacao e segura entre tentativas.
    """
    DEFAULT_HEADERS["User-Agent"] = USER_AGENTS[attempt % len(USER_AGENTS)]
    DEFAULT_HEADERS["Accept-Language"] = "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7"
    DEFAULT_HEADERS["Accept"] = (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    )


def _resilient_list_chapters(source: str, lang: str) -> dict:
    """Busca capitulos com RETRY + backoff exponencial + rotacao de UA.

    Tenta CHAPTERS_FETCH_ATTEMPTS vezes (espera 1s, 2s, 4s...). So levanta
    excecao se TODAS falharem — o chamador decide o fallback (cache stale).
    """
    last_exc: Exception | None = None
    for attempt in range(CHAPTERS_FETCH_ATTEMPTS):
        try:
            _rotate_headers(attempt)
            return reader.list_chapters(source, lang=lang)
        except Exception as exc:  # noqa: BLE001 (rede/HTTP/timeout/parse)
            last_exc = exc
            if attempt < CHAPTERS_FETCH_ATTEMPTS - 1:
                wait = CHAPTERS_BACKOFF_START * (CHAPTERS_BACKOFF_BASE ** attempt)
                logger.warning(
                    "list_chapters tentativa %d/%d falhou p/ %s (%s); retry em %.1fs",
                    attempt + 1, CHAPTERS_FETCH_ATTEMPTS, source, exc, wait,
                )
                time.sleep(wait)
    raise last_exc if last_exc else RuntimeError("Falha desconhecida ao buscar capitulos.")


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
    ],
    allow_methods=["GET"],
    allow_headers=["*"],
)

# Capas baixadas viram arquivo estatico: GET /static/covers/<manga_id>.<ext>
# Cache-Control agressivo: o navegador guarda a capa "para sempre" e nem
# revalida (immutable). Como o nome do arquivo e estavel por manga_id, isso e
# seguro; se um dia precisar trocar a capa de um id, versione o nome do arquivo.
class CachedStaticFiles(StaticFiles):
    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


app.mount("/static", CachedStaticFiles(directory=str(STATIC_DIR)), name="static")


class MangaHomeSchema(BaseModel):
    """Payload da home — campos que o card (MangaCard.jsx) realmente renderiza.

    Mais enxuto que o item completo do catalogo (sem descriptions_map,
    alternative_titles, cover_original_* nem lista de capitulos), mas COMPLETO o
    bastante p/ o card: capa (com cadeia de fallback), sinopse, generos, autores,
    nota e contagem de capitulos. `cover_path` aponta p/ o arquivo LOCAL em
    /static/covers; `cover_url`/`cover_fallbacks` sao a rede de seguranca quando o
    arquivo local ainda nao esta pronto (evita o card preto).
    """

    id: str
    title: str
    cover_path: str = ""
    cover_url: str = ""
    cover_fallbacks: list[str] = Field(default_factory=list)
    source: str = ""
    description: str = ""
    genres: list[str] = Field(default_factory=list)
    authors: list[str] = Field(default_factory=list)
    rating: float | None = None
    chapter_count: int | None = None
    latest_chapter: str = ""
    updated_at: str = ""
    source_url: str = ""


def _home_has_real_cover(item: dict) -> bool:
    """Capa REAL FISICA no disco. Placeholder ou capa so-remota nao contam:
    a obra so entra na home com arquivo local existente em /static/covers.
    """
    cover_path = str(item.get("cover_path") or "")
    return bool(cover_path) and cover_path != PLACEHOLDER_URL and _cover_file_exists(cover_path)


def _home_has_chapters(item: dict) -> bool:
    """Tem capitulos associados (evita 'null caps' poluindo a home)."""
    count = item.get("chapter_count")
    try:
        if count not in (None, "") and int(count) > 0:
            return True
    except (TypeError, ValueError):
        pass
    return bool(str(item.get("latest_chapter") or "").strip())


def _is_home_ready(item: dict) -> bool:
    """Obra pronta p/ a linha de frente: tem capa real E capitulos."""
    return _home_has_real_cover(item) and _home_has_chapters(item)


def _home_item(item: dict) -> dict:
    """Mapeia um item completo do catalogo -> dict da home p/ o card.

    Mantem a capa local (cover_path) + cadeia de fallback (cover_url/fallbacks) e
    os metadados que o card exibe (sinopse, generos, autores, nota, n de caps).
    """
    def _to_int(value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _to_float(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    return MangaHomeSchema(
        id=str(item.get("id") or item.get("slug") or item.get("source_url") or ""),
        title=str(item.get("title") or ""),
        cover_path=str(item.get("cover_path") or item.get("cover_url") or PLACEHOLDER_URL),
        cover_url=str(item.get("cover_url") or ""),
        cover_fallbacks=[str(u) for u in (item.get("cover_fallbacks") or []) if str(u or "").strip()],
        source=str(item.get("source") or ""),
        description=str(item.get("description") or ""),
        genres=[str(g) for g in (item.get("genres") or []) if str(g or "").strip()],
        authors=[str(a) for a in (item.get("authors") or []) if str(a or "").strip()],
        rating=_to_float(item.get("rating")),
        chapter_count=_to_int(item.get("chapter_count")),
        latest_chapter=str(item.get("latest_chapter") or ""),
        updated_at=str(item.get("updated_at") or ""),
        source_url=str(item.get("source_url") or item.get("url") or ""),
    ).model_dump()


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


def _unproxy_image_url(url: str) -> str:
    url = str(url or "").strip()
    if not url.startswith("/api/image?"):
        return url
    values = parse_qs(urlparse(url).query).get("url") or []
    return unquote(values[0]).strip() if values else ""


def _is_mangadex_image_url(url: str) -> bool:
    host = urlparse(str(url or "")).netloc.lower()
    return host == "uploads.mangadex.org" or host.endswith(".mangadex.org")


def _cover_urls(primary: str, fallbacks: list[str]) -> tuple[str, list[str]]:
    originals = []
    for url in [primary, *fallbacks]:
        url = _unproxy_image_url(url)
        url = str(url or "").strip()
        if _is_remote_image_url(url) and url not in originals:
            originals.append(url)
    if not originals:
        return "", []

    # Proxy SEMPRE o primary: backend injeta Referer correto -> evita 403 de hotlink
    # (mugiverso/mangasbrasuka/mangalivre bloqueiam carga direta sem referer).
    primary_proxy = _proxy_image_url(originals[0]) or originals[0]
    fallback_urls: list[str] = []
    for url in originals[1:]:
        proxy = _proxy_image_url(url)
        if proxy and proxy not in fallback_urls:
            fallback_urls.append(proxy)
    # ultima cartada: urls cruas (caso o proxy caia)
    for url in originals:
        if url not in fallback_urls:
            fallback_urls.append(url)
    return primary_proxy, fallback_urls


def _refresh_cover_fields(item: dict) -> dict:
    merged = dict(item)
    originals: list[str] = []
    for url in [
        merged.get("cover_original_url"),
        merged.get("cover_url"),
        *(merged.get("cover_original_fallbacks") or []),
        *(merged.get("cover_fallbacks") or []),
    ]:
        clean_url = _unproxy_image_url(str(url or "").strip())
        if _is_remote_image_url(clean_url) and clean_url not in originals:
            originals.append(clean_url)
    if not originals:
        return merged
    cover_url, cover_fallbacks = _cover_urls(originals[0], originals[1:])
    merged["cover_url"] = cover_url
    merged["cover_original_url"] = originals[0]
    merged["cover_fallbacks"] = cover_fallbacks
    merged["cover_original_fallbacks"] = originals[1:]
    return merged


def _guess_provider(item: dict) -> str:
    provider = str(item.get("provider") or item.get("source") or "").lower()
    url = str(item.get("url") or "")
    if provider:
        return provider
    if "yomumangas" in url or "yumomangas" in url or url.startswith("yumo://"):
        return "yumo"
    if "mangasbrasuka" in url:
        return "mangasbrasuka"
    if "mangalivre" in url:
        return "mangalivre"
    if "toomics" in url:
        return "toomics"
    if "sakuramangas" in url or url.startswith("sakura://"):
        return "sakura"
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
    cover_url, cover_fallbacks = _cover_urls(poster_original, fallback_originals)
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
        "cover_url": cover_url,
        "cover_original_url": poster_original,
        "cover_fallbacks": cover_fallbacks,
        "cover_original_fallbacks": fallback_originals,
        "genres": genres[:8],
        "description": item.get("description") or "",
        "descriptions_map": item.get("descriptions") or {},
        "latest_chapter": str(item.get("latest_chapter") or ""),
        "updated_at": str(item.get("updated_at") or ""),
        "chapter_languages": [
            str(l).lower() for l in (item.get("available_translated_languages") or []) if l
        ],
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
    cache_key = source_url.strip()
    cached = chapter_count_cache.get(cache_key)
    if _cache_is_fresh(cached, CHAPTER_COUNT_CACHE_TTL_SECONDS):
        return int(cached.data.get("count") or 0)
    try:
        if _guess_provider({"url": source_url}) == "mangadex":
            count = int(reader.mangadex_chapter_total(source_url))  # barato, sem conteudo
        else:
            payload = reader.list_chapters(source_url)
            count = int(payload.get("count") or 0)
    except Exception:
        count = 0
    chapter_count_cache[cache_key] = CacheEntry(time.time(), {"count": count})
    return count


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
            metadata = reader.manga_metadata(source_url, include_chapters=False)
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
                item["cover_original_url"] = poster
                item["cover_original_fallbacks"] = [
                    *(item.get("cover_original_fallbacks") or []),
                ]
                item.update(_refresh_cover_fields(item))
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


def _fast_curated_catalog_items() -> list[dict]:
    items: list[dict] = []
    for raw in CURATED_CATALOG:
        payload = dict(raw)
        if not payload.get("url"):
            continue
        item = _normalize_manga_item(payload, section=str(payload.get("section") or "Destaques"))
        if item:
            items.append(item)
    return _dedupe(items)


def _snapshot_payload(data: dict, limit: int | None = None) -> dict:
    payload = _apply_fast_curated_fields(dict(data))
    items = list(payload.get("items") or [])
    if limit is not None:
        payload["items"] = items[:limit]
        payload["limit"] = limit
    payload["sections"] = list(payload.get("sections") or [])
    return payload


def _apply_fast_curated_fields(data: dict) -> dict:
    seeds = {
        normalize_match_text(str(item.get("title") or "")): item
        for item in _fast_curated_catalog_items()
    }
    if not seeds:
        return data

    def merge(item: dict) -> dict:
        key = normalize_match_text(str(item.get("title") or ""))
        seed = seeds.get(key)
        if not seed:
            return _refresh_cover_fields(item)
        merged = dict(item)
        for field in ("cover_url", "cover_original_url", "cover_fallbacks", "cover_original_fallbacks"):
            if not merged.get(field) and seed.get(field):
                merged[field] = seed[field]
        return _refresh_cover_fields(merged)

    data["items"] = [merge(dict(item)) for item in data.get("items") or []]
    data["sections"] = [
        {**section, "items": [merge(dict(item)) for item in section.get("items") or []]}
        for section in data.get("sections") or []
    ]
    return data


def _read_catalog_snapshot() -> dict | None:
    try:
        if not CATALOG_SNAPSHOT_PATH.exists():
            return None
        payload = json.loads(CATALOG_SNAPSHOT_PATH.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not payload.get("items"):
            return None
        return payload
    except Exception:
        return None


def _write_catalog_snapshot(data: dict) -> None:
    try:
        CATALOG_SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = CATALOG_SNAPSHOT_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(CATALOG_SNAPSHOT_PATH)
    except Exception:
        return


def _catalog_snapshot_age() -> float | None:
    try:
        return time.time() - CATALOG_SNAPSHOT_PATH.stat().st_mtime
    except OSError:
        return None


def _fast_catalog_seed(limit: int) -> dict:
    items = _fast_curated_catalog_items()
    sections = _build_sections_from_items(items, per_section=12) if items else []
    data = {
        "items": items[:limit],
        "sections": sections,
        "total": len(items),
        "limit": limit,
        "offset": 0,
        "sources": ["MangaDex", "MangasBrasuka", "MangaLivre"],
        "cached": True,
        "refreshing": True,
    }
    return data


def _refresh_catalog_cache(limit: int = DEFAULT_LIMIT) -> None:
    global catalog_cache, catalog_refreshing
    try:
        items, sections = _catalog_sections_from_mangadex(min(max(limit, 24), 80))
        # enrich items + section items (dedup por identidade, cap p/ nao estourar rate-limit)
        seen_ids: set[int] = set()
        bucket: list[dict] = []
        for collection in [items, *[sec.get("items") or [] for sec in sections]]:
            for it in collection:
                if id(it) not in seen_ids:
                    seen_ids.add(id(it))
                    bucket.append(it)
        _enrich_items_metadata(bucket[:60], max_workers=4)
        _fill_chapter_counts(bucket[:60], max_workers=6)
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
            "refreshing": False,
        }
        catalog_cache = CacheEntry(time.time(), data)
        _write_catalog_snapshot(data)
        # Baixa as capas p/ static/covers (define item['cover_path']) e re-grava o
        # snapshot ja com os caminhos locais -> home serve estatico, sem proxy.
        _download_covers_to_disk(bucket, limit=300)
        # Capa falhou? tenta fonte alternativa (MangaDex/AniList por titulo);
        # so marca placeholder (incompleta) se nem assim achar.
        for it in bucket:
            if _cover_file_exists(it.get("cover_path") or ""):
                continue
            if not _recover_and_store_cover(it):
                it["cover_path"] = PLACEHOLDER_URL
        catalog_cache = CacheEntry(time.time(), data)
        _write_catalog_snapshot(data)
        # Pre-aquece a lista de capitulos das obras (1x) -> 1o clique ja vem local.
        _prewarm_chapters(bucket, limit=40)
    finally:
        with catalog_refresh_lock:
            catalog_refreshing = False


def _schedule_catalog_refresh(limit: int = DEFAULT_LIMIT) -> None:
    global catalog_refreshing
    with catalog_refresh_lock:
        if catalog_refreshing:
            return
        catalog_refreshing = True
    thread = threading.Thread(target=_refresh_catalog_cache, args=(limit,), daemon=True)
    thread.start()


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
        item = _normalize_manga_item(raw, section="Lancamentos recentes")
        if item:
            trending_items.append(item)
    trending_items = _dedupe(trending_items)[:24]
    if trending_items:
        sections.append({"title": "Lancamentos recentes", "items": trending_items})
        all_items.extend(trending_items)

    # gêneros mais ricos: minimo 12, ate 18 por seção
    per_genre = max(12, min(18, limit // 4))
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

    # Carrossel "Em alta": trending real (AniList+Kitsu) cruzado com o catalogo, no topo
    highlights = _trending_highlights(all_items, limit=20)
    if highlights:
        sections.insert(0, {"title": "Em alta", "items": highlights, "layout": "carousel"})

    # Carrossel "Recém-lançados" por fonte (logo abaixo de Em alta)
    latest_pos = 1 if highlights else 0
    for sec in _latest_release_sections():
        sections.insert(latest_pos, sec)
        all_items.extend(sec["items"])
        latest_pos += 1

    return _dedupe(all_items), sections


def _build_catalog(limit: int) -> dict:
    global catalog_cache
    if _cache_is_fresh(catalog_cache, CATALOG_CACHE_TTL_SECONDS):
        return _snapshot_payload(catalog_cache.data, limit)

    snapshot = _read_catalog_snapshot()
    if snapshot:
        catalog_cache = CacheEntry(time.time(), snapshot)
        age = _catalog_snapshot_age()
        if age is None or age > CATALOG_SNAPSHOT_TTL_SECONDS:
            _schedule_catalog_refresh(max(limit, DEFAULT_LIMIT))
            snapshot = {**snapshot, "refreshing": True, "cached": True}
        return _snapshot_payload(snapshot, limit)

    data = _fast_catalog_seed(limit)
    _schedule_catalog_refresh(max(limit, DEFAULT_LIMIT))
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
    elif name == "sakura":
        payload = reader.search_sakura(query, limit=limit)
    elif name == "yumo":
        payload = reader.search_yumo(query, limit=limit)
    else:
        return []

    items = []
    for raw in payload.get("results") or []:
        item = _normalize_manga_item(raw, section="Busca")
        if item:
            items.append(item)
    return items


def _search_sources_with_timeout(
    sources: list[str],
    query: str,
    limit: int,
    *,
    timeout: float = SOURCE_SEARCH_TIMEOUT_SECONDS,
) -> tuple[list[dict], list[str]]:
    if not sources:
        return [], []

    items: list[dict] = []
    errors: list[str] = []
    executor = ThreadPoolExecutor(max_workers=len(sources))
    futures = {
        executor.submit(_search_source, source, query, limit): source
        for source in sources
    }
    try:
        done, pending = wait(futures, timeout=timeout)
        for future in done:
            source = futures[future]
            try:
                items.extend(future.result())
            except Exception as exc:
                errors.append(f"{_source_label(source)}: {exc}")
        for future in pending:
            source = futures[future]
            future.cancel()
            errors.append(f"{_source_label(source)}: timeout")
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
    return items, errors


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
    current_provider = str((current or {}).get("provider") or "").lower()
    if current and current_provider in PT_COMPLETE_SOURCES:
        source_resolution_cache[cache_key] = CacheEntry(time.time(), {"item": current})
        return current

    curated_raw = _curated_override_for_title(title)
    if curated_raw:
        curated = _enrich_curated_item({**curated_raw, "section": "Fonte completa"})
        if curated:
            source_resolution_cache[cache_key] = CacheEntry(time.time(), {"item": curated})
            return curated

    if not title:
        return current

    candidates, _errors = _search_sources_with_timeout(
        PT_COMPLETE_SOURCES,
        title,
        5,
        timeout=SOURCE_RESOLUTION_TIMEOUT_SECONDS,
    )

    exact_hits: list[tuple[int, float, dict]] = []
    for hit in candidates:
        score = _search_match_score(title, hit)
        if score < 0.92:
            continue
        provider = str(hit.get("provider") or "").lower()
        source_order = PT_COMPLETE_SOURCES.index(provider) if provider in PT_COMPLETE_SOURCES else len(PT_COMPLETE_SOURCES)
        exact_hits.append((source_order, score, hit))
    if exact_hits:
        exact_hits.sort(key=lambda pair: (pair[0], -pair[1]))
        candidate = dict(exact_hits[0][2])
        candidate["relevance"] = round(exact_hits[0][1], 4)
        source_resolution_cache[cache_key] = CacheEntry(time.time(), {"item": candidate})
        return candidate

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
        all_items.append(_copy_with_chapter_count(current))
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
        item["cover_original_url"] = cover
        item["cover_original_fallbacks"] = [
            str(url).strip()
            for url in metadata.get("poster_fallbacks") or []
            if str(url or "").strip()
        ]
        item.update(_refresh_cover_fields(item))
    if metadata.get("average_score") and not _has_rating(item):
        item["rating"] = round(float(metadata["average_score"]) / 10, 1)
    if metadata.get("description") and not item.get("description"):
        item["description"] = metadata["description"]
    if metadata.get("description"):
        _add_desc_lang(item, "en", metadata["description"])
    if metadata.get("authors") and not item.get("authors"):
        item["authors"] = metadata["authors"]
    if metadata.get("status") and not item.get("status"):
        item["status"] = metadata["status"]
    if metadata.get("genres") and not item.get("genres"):
        item["genres"] = metadata["genres"]
    item["anilist_url"] = metadata.get("url") or item.get("anilist_url") or ""


def _has_rating(item: dict) -> bool:
    try:
        return float(item.get("rating")) > 0
    except (TypeError, ValueError):
        return False


def _kitsu_metadata(title: str) -> dict:
    key = normalize_match_text(title)
    cached = kitsu_cache.get(key)
    if _cache_is_fresh(cached, KITSU_CACHE_TTL_SECONDS):
        return dict(cached.data)
    data: dict = {}
    try:
        response = requests.get(
            "https://kitsu.app/api/edge/manga",
            params={"filter[text]": title, "page[limit]": 1},
            headers={"Accept": "application/vnd.api+json", "User-Agent": "Mozilla/5.0"},
            timeout=8,
        )
        response.raise_for_status()
        entries = response.json().get("data") or []
        if entries:
            attrs = entries[0].get("attributes") or {}
            poster = attrs.get("posterImage") or {}
            avg = attrs.get("averageRating")
            try:
                rating = round(float(avg) / 10, 1) if avg else None  # kitsu 0-100 -> 0-10
            except (TypeError, ValueError):
                rating = None
            data = {
                "rating": rating,
                "description": str(attrs.get("synopsis") or attrs.get("description") or "").strip(),
                "poster": str(
                    poster.get("large") or poster.get("medium") or poster.get("original") or ""
                ).strip(),
                "poster_fallbacks": [
                    str(url).strip()
                    for url in [poster.get("medium"), poster.get("small"), poster.get("original")]
                    if str(url or "").strip()
                ],
                "url": f"https://kitsu.app/manga/{entries[0].get('id')}" if entries[0].get("id") else "",
            }
    except Exception:
        data = {}
    kitsu_cache[key] = CacheEntry(time.time(), data)
    return dict(data)


def _apply_kitsu_metadata(item: dict, metadata: dict) -> None:
    cover = str(metadata.get("poster") or "").strip()
    if cover and not item.get("cover_url"):
        item["cover_original_url"] = cover
        item["cover_original_fallbacks"] = [
            str(url).strip()
            for url in metadata.get("poster_fallbacks") or []
            if str(url or "").strip()
        ]
        item.update(_refresh_cover_fields(item))
    rating = metadata.get("rating")
    if rating and not _has_rating(item):
        item["rating"] = rating
    if metadata.get("description") and not item.get("description"):
        item["description"] = metadata["description"]
    if metadata.get("description"):
        _add_desc_lang(item, "en", metadata["description"])
    item["kitsu_url"] = metadata.get("url") or item.get("kitsu_url") or ""


def _kitsu_trending_raw(limit: int = 20) -> list[dict]:
    """Trending manga 'da semana' direto do Kitsu, com poster/rating/sinopse."""
    try:
        response = requests.get(
            "https://kitsu.app/api/edge/trending/manga",
            params={"page[limit]": min(max(limit, 1), 20)},
            headers={"Accept": "application/vnd.api+json", "User-Agent": "Mozilla/5.0"},
            timeout=8,
        )
        response.raise_for_status()
        entries = response.json().get("data") or []
    except Exception:
        return []
    out: list[dict] = []
    for entry in entries:
        attrs = entry.get("attributes") or {}
        title = str(attrs.get("canonicalTitle") or "").strip()
        if not title:
            continue
        poster = attrs.get("posterImage") or {}
        avg = attrs.get("averageRating")
        try:
            rating = round(float(avg) / 10, 1) if avg else None
        except (TypeError, ValueError):
            rating = None
        aliases = [str(v).strip() for v in (attrs.get("titles") or {}).values() if str(v or "").strip()]
        out.append(
            {
                "title": title,
                "aliases": aliases,
                "meta": {
                    "poster": str(
                        poster.get("large") or poster.get("medium") or poster.get("original") or ""
                    ).strip(),
                    "poster_fallbacks": [
                        str(u).strip()
                        for u in [poster.get("medium"), poster.get("small"), poster.get("original")]
                        if str(u or "").strip()
                    ],
                    "rating": rating,
                    "description": str(attrs.get("synopsis") or attrs.get("description") or "").strip(),
                    "url": f"https://kitsu.app/manga/{entry.get('id')}" if entry.get("id") else "",
                },
            }
        )
    return out


def _kitsu_trending_items(limit: int = 20) -> list[dict]:
    """Resolve cada trending do Kitsu a uma fonte legivel (MangaDex), mantendo a ordem do Kitsu."""
    raw = _kitsu_trending_raw(limit)
    if not raw:
        return []

    def resolve(entry: dict) -> dict | None:
        names = [entry["title"], *entry["aliases"][:3]]
        best: dict | None = None
        best_score = 0.0
        for name in names:
            try:
                payload = reader.search_mangadex(name, limit=5)
            except Exception:
                continue
            for raw_item in payload.get("results") or []:
                cand = _normalize_manga_item(raw_item, section="Em alta")
                if not cand:
                    continue
                score = max(
                    fuzzy_match_score(n, str(cand.get("title") or ""))
                    for n in names
                )
                if score > best_score:
                    best_score, best = score, cand
            if best_score >= 0.92:
                break
        if not best or best_score < 0.6:
            return None
        _apply_kitsu_metadata(best, entry["meta"])
        if entry["meta"].get("rating") and not best.get("rating"):
            best["rating"] = entry["meta"]["rating"]
        return best

    out: list[dict] = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        for it in executor.map(resolve, raw):
            if it:
                out.append(it)
    return _dedupe(out)[:limit]


def _kitsu_trending_titles(limit: int = 40) -> list[str]:
    titles: list[str] = []
    for entry in _kitsu_trending_raw(limit):
        titles.append(entry["title"])
        titles.extend(entry["aliases"])
    return titles


def _latest_release_sections() -> list[dict]:
    """Carrossel 'Recém-lançados' por fonte. Hoje: MangaDex (feed real de ultimo cap)."""
    sections: list[dict] = []
    try:
        payload = reader.latest_mangadex(limit=24, lang="")
    except Exception:
        payload = {}
    items: list[dict] = []
    for raw in payload.get("results") or []:
        item = _normalize_manga_item(raw, section="Recem-lancados")
        if item:
            items.append(item)
    items = _dedupe(items)[:20]
    if items:
        sections.append(
            {"title": "Recém-lançados · MangaDex", "items": items, "layout": "carousel"}
        )
    # mangasbrasuka / mangalivre: sem scraper de feed de lancamentos ainda (so busca).
    return sections


def _trending_highlights(catalog_items: list[dict], limit: int = 20) -> list[dict]:
    """Carrossel 'Em alta da semana': trending real do Kitsu resolvido a fontes legiveis.
    Kitsu primeiro (ordem do Kitsu), completa com AniList x catalogo. Nunca usa curated."""
    picked: list[dict] = []
    seen: set[str] = set()

    def add(item: dict) -> None:
        key = str(item.get("id") or item.get("source_url") or item.get("title"))
        if key and key not in seen:
            seen.add(key)
            picked.append(item)

    # 1) Kitsu trending da semana (fonte de verdade do carrossel)
    for item in _kitsu_trending_items(limit):
        add(item)

    # 2) completa com AniList trending cruzado com o catalogo ja carregado
    if len(picked) < limit:
        titles: list[str] = []
        try:
            titles += reader.anilist_trending_titles(40)
        except Exception:
            pass
        index: dict[str, dict] = {}
        for item in catalog_items:
            for name in [item.get("title"), *(item.get("alternative_titles") or [])]:
                norm = normalize_match_text(str(name or ""))
                if norm:
                    index.setdefault(norm, item)
        for title in titles:
            item = index.get(normalize_match_text(title))
            if item:
                add(item)
            if len(picked) >= limit:
                break

    # 3) fallback final: itens do catalogo COM capa, EXCETO curated ("Destaques")
    if len(picked) < 8:
        for item in catalog_items:
            if str(item.get("section") or "") == "Destaques":
                continue
            if not item.get("cover_url"):
                continue
            add(item)
            if len(picked) >= 12:
                break

    return picked[:limit]


def _fill_chapter_counts(items: list[dict], max_workers: int = 6, cap: int = 60) -> None:
    """Conta capitulos (barato, mangadex /aggregate) p/ mostrar 'X caps' no card."""
    targets = [
        item for item in items
        if _guess_provider(item) == "mangadex"
        and int(item.get("chapter_count") or 0) <= 0
        and str(item.get("source_url") or "")
    ][:cap]
    if not targets:
        return

    def fill(item: dict) -> None:
        try:
            count = reader.mangadex_chapter_total(str(item.get("source_url") or ""))
            if count:
                item["chapter_count"] = count
        except Exception:
            pass

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        list(executor.map(fill, targets))


def _enrich_items_metadata(items: list[dict], max_workers: int = 6) -> None:
    """Preenche rating/autor/sinopse/capa: AniList primario, Kitsu fallback."""
    candidates = [
        item for item in items
        if item.get("title")
        and (
            not _has_rating(item)
            or not item.get("authors")
            or not item.get("description")
            or not item.get("cover_url")
        )
    ]
    if not candidates:
        return

    def enrich(item: dict) -> None:
        title = str(item.get("title") or "")
        try:
            _apply_anilist_metadata(item, _anilist_metadata(title))
        except Exception:
            pass
        if not _has_rating(item) or not item.get("description") or not item.get("cover_url"):
            try:
                _apply_kitsu_metadata(item, _kitsu_metadata(title))
            except Exception:
                pass

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        list(executor.map(enrich, candidates))


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


_PT_HINTS = (
    "ção", "ã", "õ", "á", "ç", "í", "ú", "ê", "ô",
    " não ", " que ", " uma ", " com ", " para ", " é ", " dos ", " das ",
    " ele ", " ela ", " você ", " mais ", " seu ", " sua ", " mas ", " são ",
)
_EN_HINTS = (
    " the ", " and ", " of ", " is ", " to ", " his ", " her ", " with ",
    " was ", " that ", " they ", " when ", " who ", " from ", " after ",
)


def _looks_english(text: str) -> bool:
    """Heuristica barata: provavelmente ingles (sem tracos PT, com stopwords EN)."""
    t = f" {str(text or '').lower()} "
    if len(t) < 12:
        return False
    if any(hint in t for hint in _PT_HINTS):
        return False
    return any(hint in t for hint in _EN_HINTS)


def _looks_portuguese(text: str) -> bool:
    t = f" {str(text or '').lower()} "
    return any(hint in t for hint in _PT_HINTS)


def _translate_to_pt(text: str) -> str:
    """Traduz QUALQUER idioma -> PT (sl=auto). Ja-PT ou falha -> texto original."""
    original = str(text or "").strip()
    if not original or _looks_portuguese(original):
        return original
    cached = translation_cache.get(original)
    if _cache_is_fresh(cached, TRANSLATION_CACHE_TTL_SECONDS):
        return str(cached.data.get("text") or original)
    translated = original
    try:
        response = requests.get(
            "https://translate.googleapis.com/translate_a/single",
            params={"client": "gtx", "sl": "auto", "tl": "pt", "dt": "t", "q": original},
            timeout=6,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        response.raise_for_status()
        segments = response.json()[0] or []
        joined = "".join(seg[0] for seg in segments if seg and seg[0]).strip()
        translated = joined or original
    except Exception:
        translated = original
    translation_cache[original] = CacheEntry(time.time(), {"text": translated})
    return translated


def _add_desc_lang(item: dict, lang: str, text: str) -> None:
    text = str(text or "").strip()
    if not text:
        return
    item.setdefault("descriptions_map", {}).setdefault(lang, text)


def _finalize_descriptions(item: dict) -> None:
    """Lista ordenada de sinopses (PT topo -> EN -> resto) + define description default."""
    raw = item.get("descriptions_map") or {}
    norm: dict[str, str] = {}
    for lang, text in raw.items():
        text = str(text or "").strip()
        if text:
            norm[str(lang or "").lower()] = text
    # sem map, mas tem description solta -> classifica por idioma
    if not norm and str(item.get("description") or "").strip():
        d = str(item["description"]).strip()
        norm["pt-br" if _looks_portuguese(d) else "en"] = d

    pt = norm.get("pt-br") or norm.get("pt")
    en = norm.get("en")
    rest = sorted(k for k in norm if k not in ("pt-br", "pt", "en"))

    ordered: list[dict] = []
    if pt:
        ordered.append({"lang": "pt-br", "text": pt})
    elif en:
        ordered.append({"lang": "pt-br", "text": _translate_to_pt(en), "auto": True})
    elif rest:
        ordered.append({"lang": "pt-br", "text": _translate_to_pt(norm[rest[0]]), "auto": True})
    if en:
        ordered.append({"lang": "en", "text": en})
    for k in rest:
        ordered.append({"lang": k, "text": norm[k]})

    item.pop("descriptions_map", None)
    if ordered:
        item["descriptions"] = ordered
        item["description"] = ordered[0]["text"]


def _strip_descriptions_map(item: dict) -> None:
    raw = item.pop("descriptions_map", None)
    if item.get("descriptions"):
        return
    if raw:
        ordered = []
        for lang, text in raw.items():
            text = str(text or "").strip()
            if text:
                ordered.append({"lang": str(lang or "").lower(), "text": text})
        if ordered:
            item["descriptions"] = ordered
    elif item.get("description"):
        d = str(item["description"])
        item["descriptions"] = [
            {"lang": "pt-br" if _looks_portuguese(d) else "en", "text": d}
        ]


def _finalize_payload_descriptions(data: dict, max_workers: int = 6, cap: int = 200) -> None:
    seen: set[int] = set()
    bucket: list[dict] = []

    def collect(item: dict) -> None:
        if not isinstance(item, dict) or id(item) in seen:
            return
        seen.add(id(item))
        bucket.append(item)

    for item in data.get("items") or []:
        collect(item)
    for section in data.get("sections") or []:
        for item in section.get("items") or []:
            collect(item)
    if not bucket:
        return
    head = bucket[:cap]
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        list(executor.map(_finalize_descriptions, head))
    for item in bucket[cap:]:  # tail: sem traduzir, so normaliza/limpa
        _strip_descriptions_map(item)


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

    headers = {
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/138.0.0.0 Safari/537.36"
        ),
        "Referer": _image_referer(url),
    }
    if _is_mangadex_image_url(url):
        headers["Accept"] = "*/*"
        headers["User-Agent"] = "python-requests/2.32.5"

    response = requests.get(
        url,
        timeout=20,
        headers=headers,
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


def _cover_extension(media_type: str, url: str) -> str:
    mt = (media_type or "").split(";", 1)[0].strip().lower()
    by_mime = {
        "image/webp": ".webp", "image/jpeg": ".jpg", "image/jpg": ".jpg",
        "image/png": ".png", "image/gif": ".gif", "image/avif": ".avif",
    }
    if mt in by_mime:
        return by_mime[mt]
    path = urlparse(url).path.lower()
    for ext in (".webp", ".jpg", ".jpeg", ".png", ".gif", ".avif"):
        if path.endswith(ext):
            return ".jpg" if ext == ".jpeg" else ext
    return ".jpg"


def _cover_file_exists(cover_path: str) -> bool:
    """True se o cover_path /static/... aponta para um arquivo que existe no disco."""
    cover_path = str(cover_path or "")
    if not cover_path.startswith("/static/"):
        return False
    try:
        return (STATIC_DIR / cover_path[len("/static/"):]).is_file()
    except Exception:
        return False


def _cover_key(item: dict) -> str:
    """Chave estavel p/ o nome do arquivo da capa (manga_id, fallback slug)."""
    raw = str(item.get("id") or "").strip() or str(item.get("slug") or "") or str(item.get("title") or "")
    return _slug(raw) or "cover"


def _store_cover_local(item: dict) -> None:
    """Baixa a capa 1x para static/covers/<manga_id>.<ext> e grava item['cover_path'].

    Reusa _fetch_image (Referer correto + cache em memoria). Idempotente: se o
    arquivo ja existe, so reusa o caminho.
    """
    src = str(item.get("cover_original_url") or "").strip() or _unproxy_image_url(item.get("cover_url") or "")
    if not _is_remote_image_url(src):
        return
    key = _cover_key(item)
    try:
        existing = next(COVERS_DIR.glob(f"{key}.*"), None)
        if existing and existing.stat().st_size > 0:
            item["cover_path"] = f"/static/covers/{existing.name}"
            return
        entry = _fetch_image(src)
        filename = f"{key}{_cover_extension(entry.media_type, src)}"
        (COVERS_DIR / filename).write_bytes(entry.content)
        item["cover_path"] = f"/static/covers/{filename}"
    except Exception:
        return  # falha de capa nao pode derrubar a raspagem


def _download_covers_to_disk(items: list[dict], limit: int = 80, max_workers: int = 8) -> None:
    targets = [
        it for it in items
        if str(it.get("cover_original_url") or it.get("cover_url") or "").strip()
    ][:limit]
    if not targets:
        return
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        list(executor.map(_store_cover_local, targets))


def _mangadex_cover_url(title: str) -> str:
    """Capa via API MangaDex buscando por titulo (1o resultado)."""
    title = str(title or "").strip()
    if not title:
        return ""
    try:
        resp = requests.get(
            "https://api.mangadex.org/manga",
            params={
                "title": title,
                "limit": 1,
                "includes[]": "cover_art",
                "contentRating[]": ["safe", "suggestive", "erotica"],
                "order[relevance]": "desc",
            },
            timeout=15,
            headers={"User-Agent": "python-requests/2.32.5"},
        )
        resp.raise_for_status()
        data = resp.json().get("data") or []
        if not data:
            return ""
        entry = data[0]
        manga_id = entry.get("id")
        file_name = next(
            (
                rel.get("attributes", {}).get("fileName")
                for rel in entry.get("relationships") or []
                if rel.get("type") == "cover_art" and rel.get("attributes")
            ),
            None,
        )
        if manga_id and file_name:
            return f"https://uploads.mangadex.org/covers/{manga_id}/{file_name}"
    except Exception:
        return ""
    return ""


def _recover_cover_url(title: str) -> str:
    """Tenta achar uma capa por TITULO: MangaDex -> AniList. '' se nada."""
    url = _mangadex_cover_url(title)
    if _is_remote_image_url(url):
        return url
    try:
        poster = str(_anilist_metadata(title).get("poster") or "").strip()
        return poster if _is_remote_image_url(poster) else ""
    except Exception:
        return ""


def _recover_and_store_cover(item: dict) -> bool:
    """Recupera a capa por titulo numa fonte alternativa e salva local.

    Retorna True se conseguiu (cover_path setado p/ arquivo existente).
    """
    url = _recover_cover_url(str(item.get("title") or ""))
    if not _is_remote_image_url(url):
        return False
    key = _cover_key(item)
    try:
        entry = _fetch_image(url)
        filename = f"{key}{_cover_extension(entry.media_type, url)}"
        (COVERS_DIR / filename).write_bytes(entry.content)
        item["cover_path"] = f"/static/covers/{filename}"
        item.setdefault("cover_original_url", url)
        return _cover_file_exists(item["cover_path"])
    except Exception:
        return False


def _prewarm_chapters(items: list[dict], limit: int = 40, max_workers: int = 4) -> None:
    """Pre-busca a lista de capitulos das obras do catalogo (1x) e persiste em
    disco, para o PRIMEIRO clique do usuario ja vir do cache local (sem fetch).
    """
    def warm(item: dict) -> None:
        source_url = str(item.get("source_url") or "").strip()
        if not source_url:
            return
        lang = str(item.get("language") or "pt-br")
        key = f"{source_url}|{normalize_match_text(lang)}"
        if _cache_is_fresh(chapters_cache.get(key), CHAPTERS_DISK_TTL_SECONDS):
            return
        try:
            payload = reader.list_chapters(source_url, lang=lang)
            chapters_cache[key] = CacheEntry(time.time(), dict(payload))
        except Exception:
            pass  # falha de uma obra nao derruba o prewarm

    targets = [it for it in items if it.get("source_url")][:limit]
    if not targets:
        return
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        list(executor.map(warm, targets))
    _save_chapters_snapshot()


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
    items, errors = _search_sources_with_timeout(
        sources,
        query,
        limit,
        timeout=SOURCE_SEARCH_TIMEOUT_SECONDS,
    )

    normalized_query = normalize_match_text(query)
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
    _enrich_items_metadata(items[:limit], max_workers=6)
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
    """Compat: rota legada. Delega p/ a busca (com q) ou a home (sem q).

    Mantida para nao quebrar clientes antigos; as rotas novas e TIPADAS sao
    /api/search e /api/home.
    """
    if q.strip():
        return _build_search_payload(q, genre, limit, offset)
    return _build_home_payload(genre, limit, offset)


@app.get("/api/search", response_model=SearchResponse)
def search_mangas(
    q: str = Query(..., description="Termo de busca por titulo em fontes reais."),
    genre: str = Query(default="", description="Filtro local por genero."),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> SearchResponse:
    """Busca tipada: retorna MangaSearchItem (sinopse, generos, autores, etc.)."""
    return SearchResponse(**_build_search_payload(q, genre, limit, offset))


@app.get("/api/home", response_model=HomeResponse)
def home_catalog(
    genre: str = Query(default="", description="Filtro local por genero."),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> HomeResponse:
    """Home tipada: obras PRONTAS (capa real + capitulos) como MangaHomeItem."""
    return HomeResponse(**_build_home_payload(genre, limit, offset))


def _matches_genre_factory(genre: str):
    genre_filter = normalize_match_text(genre)

    def _matches(item: dict) -> bool:
        if not genre_filter:
            return True
        return any(
            normalize_match_text(g) == genre_filter for g in (item.get("genres") or [])
        )

    return _matches


def _build_search_payload(q: str, genre: str, limit: int, offset: int) -> dict:
    """Logica de BUSCA: payload completo (poucos itens), com traducao."""
    query = q.strip()
    _matches_genre = _matches_genre_factory(genre)

    data = _search_mangas(query, limit=max(limit + offset, limit))
    items = [it for it in (data.get("items") or []) if _matches_genre(it)]
    sections = [
        {"title": sec.get("title"), "layout": sec.get("layout", ""),
         "items": [it for it in (sec.get("items") or []) if _matches_genre(it)]}
        for sec in (data.get("sections") or [{"title": "Resultados", "items": items}])
    ]
    sections = [sec for sec in sections if sec["items"]]
    paged = items[offset : offset + limit]
    result = {**data, "items": paged, "sections": sections,
              "total": len(items), "limit": limit, "offset": offset}
    _finalize_payload_descriptions(result)  # traducao so na busca
    return result


def _build_home_payload(genre: str, limit: int, offset: int) -> dict:
    """Logica da HOME: payload p/ o card, so obras PRONTAS (capa real + caps)."""
    _matches_genre = _matches_genre_factory(genre)

    data = _build_catalog(limit=max(limit + offset, limit))
    items = [it for it in (data.get("items") or []) if _matches_genre(it) and _is_home_ready(it)]
    sections_src = data.get("sections") or [{"title": "Destaques", "items": items}]

    paged = items[offset : offset + limit]
    slim_items = [_home_item(it) for it in paged]
    slim_sections = []
    for sec in sections_src:
        sec_items = [
            _home_item(it) for it in (sec.get("items") or [])
            if _matches_genre(it) and _is_home_ready(it)
        ]
        if sec_items:
            slim_sections.append({
                "title": sec.get("title"),
                "layout": sec.get("layout", ""),  # preserva 'carousel' do hero "Em alta"
                "items": sec_items,
            })

    return {
        "items": slim_items,
        "sections": slim_sections,
        "total": len(items),
        "limit": limit,
        "offset": offset,
        "sources": data.get("sources") or [],
        "cached": data.get("cached", False),
        "refreshing": data.get("refreshing", False),
    }


def _find_catalog_item(source_url: str) -> dict | None:
    """Acha o item completo do catalogo (com descriptions_map/genres/autores) pelo source_url."""
    source_url = str(source_url or "").strip()
    if not source_url or catalog_cache is None:
        return None
    data = catalog_cache.data or {}
    pools = [data.get("items") or []]
    for section in data.get("sections") or []:
        pools.append(section.get("items") or [])
    for pool in pools:
        for item in pool:
            if str(item.get("source_url") or "") == source_url:
                return item
    return None


def _build_manga_meta(item: dict | None, source_url: str) -> dict:
    """Metadados ricos p/ o painel de detalhe: sinopse multi-idioma, generos,
    autores, status, rating e idiomas de capitulo. Vem do catalogo (preferido)
    ou, em ultimo caso, de uma consulta de metadata externa best-effort.
    """
    enriched: dict | None = None
    if item:
        enriched = dict(item)
        _finalize_descriptions(enriched)  # descriptions_map -> descriptions[] (PT/EN/...) + traducao
    else:
        try:
            md = reader.manga_metadata(source_url, include_chapters=False) or {}
            mg = md.get("manga") or {}
            rating = mg.get("rating")
            if isinstance(rating, dict):
                rating = rating.get("score")
            enriched = {
                "description": mg.get("description") or "",
                "descriptions_map": mg.get("descriptions") or {},
                "genres": mg.get("genres") or [],
                "authors": mg.get("authors") or [],
                "status": mg.get("status") or "",
                "rating": rating,
                "chapter_languages": [str(l).lower() for l in (md.get("available_translated_languages") or [])],
                "alternative_titles": mg.get("alternative_titles") or [],
            }
            _finalize_descriptions(enriched)
        except Exception:
            return {}
    return {
        "description": enriched.get("description") or "",
        "descriptions": enriched.get("descriptions") or [],
        "genres": enriched.get("genres") or [],
        "authors": enriched.get("authors") or [],
        "status": enriched.get("status") or "",
        "rating": enriched.get("rating"),
        "chapter_languages": enriched.get("chapter_languages") or [],
        "alternative_titles": enriched.get("alternative_titles") or [],
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
    requested_lang = (lang or "").strip().lower()
    # Auto-troca pra fonte PT-completa SÓ quando o usuario quer pt-br.
    # Pra EN/JP/etc, mantem a fonte (MangaDex) e puxa capitulos naquele idioma.
    if auto_source and title.strip() and requested_lang in ("", "pt-br", "pt"):
        resolved_item = _resolve_best_source_for_title(title, source, lang)
        resolved_url = str((resolved_item or {}).get("source_url") or "").strip()
        if resolved_url:
            source = resolved_url

    cache_key = f"{source}|{normalize_match_text(lang)}"
    cached = chapters_cache.get(cache_key)
    if _cache_is_fresh(cached, CHAPTERS_DISK_TTL_SECONDS):
        payload = dict(cached.data)
        payload["cached"] = True
    else:
        # MISS: tenta a fonte externa com RETRY+backoff+UA rotation.
        try:
            payload = _resilient_list_chapters(source, lang)
            chapters_cache[cache_key] = CacheEntry(time.time(), dict(payload))
            _save_chapters_snapshot()
            payload["cached"] = False
        except Exception as exc:
            # ULTIMO RECURSO: se existe cache local (mesmo VELHO), serve ele e
            # nao trava o front. So estoura 502 se nunca tivermos cacheado.
            if cached is not None and isinstance(cached.data, dict) and cached.data:
                logger.warning(
                    "Fonte externa indisponivel p/ %s apos %d tentativas (%s); "
                    "servindo cache STALE.", source, CHAPTERS_FETCH_ATTEMPTS, exc,
                )
                payload = dict(cached.data)
                payload["cached"] = True
                payload["stale"] = True
            else:
                raise HTTPException(status_code=502, detail=str(exc)) from exc
    payload["requested_source_url"] = requested_source
    payload["resolved_source_url"] = source
    if resolved_item:
        payload["resolved_source"] = _source_label(payload.get("provider") or resolved_item.get("provider"))

    # Metadados completos da obra (sinopse multi-idioma, generos, autores, status,
    # idiomas de capitulo) p/ o painel de detalhe — sem inchar a LISTA da home.
    meta_item = resolved_item or _find_catalog_item(source) or _find_catalog_item(requested_source)
    payload["manga"] = _build_manga_meta(meta_item, source)
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
            "Cache-Control": "public, max-age=86400",
            "X-MangaTemp-Image-Cache": "memory",
        },
    )
