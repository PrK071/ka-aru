"""Scraper do MangasBrasuka (WordPress + tema Madara, HTML nacional).

Terceiro modelo: variacao nacional. Logica portada do scraper-debug ja validado
do projeto (tools/debug/mangasbrasuka_scraper.py), adaptada a interface modular.

Estrutura:
    - Diretorio: https://mangasbrasuka.com.br/manga/
    - Mangá:     https://mangasbrasuka.com.br/manga/<slug>/
    - Capitulo:  https://mangasbrasuka.com.br/manga/<slug>/capitulo-<n>/   (n float)
    - Leitor:    <img> dentro de .reading-content (data-src/lazy/src/srcset);
                 CDN cdn.mugiverso.com/mangasbrasuka/manga[_/]...
    - Lista de caps: links no HTML; fallback AJAX admin-ajax (manga_get_chapters).

Madara serve as imagens com Referer da pagina -> setado em PageRef.headers.
"""

from __future__ import annotations

import logging
import re
from html import unescape
from typing import Iterator
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import requests

from config import REQUEST_TIMEOUT
from .base import BaseScraper, ChapterRef, MangaRef, PageRef
from . import register

logger = logging.getLogger(__name__)

BASE = "https://mangasbrasuka.com.br"

_TAG_RE = re.compile(r"<[^>]+>")
_CHAPTER_SLUG_RE = re.compile(r"capitulo-(\d+(?:\.\d+)?)/?$", re.IGNORECASE)
_IMG_EXT_RE = re.compile(r"\.(?:avif|gif|jpe?g|png|webp)$", re.IGNORECASE)


# --------------------------------------------------------------------------- #
# Helpers de parsing (regex; robusto p/ o HTML do Madara)
# --------------------------------------------------------------------------- #
def _normalize_url(raw_url: str | None, base_url: str = "") -> str:
    """Resolve URL absoluta + desembrulha proxies (?a=<url-real>)."""
    url = unescape(str(raw_url or "")).strip()
    if not url or url == "#" or url.startswith("data:"):
        return ""
    url = urljoin(base_url, url)
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    params = parse_qs(parsed.query)
    for key in ("a", "url", "u", "img", "image"):
        candidate = params.get(key, [None])[0]
        if candidate and re.match(r"^https?://", candidate, re.IGNORECASE):
            nested = _normalize_url(candidate)
            if nested:
                return nested
    return parsed._replace(fragment="").geturl()


def _attrs_from_tag(tag: str) -> dict[str, str]:
    return {
        key.lower(): unescape(value)
        for key, _q, value in re.findall(
            r'([a-zA-Z_:][-.\w:]*)\s*=\s*(["\'])(.*?)\2', tag, re.DOTALL
        )
    }


def _srcset_urls(srcset: str | None) -> list[str]:
    out: list[str] = []
    for item in (srcset or "").split(","):
        first = item.strip().split()[0] if item.strip() else ""
        if first:
            out.append(first)
    return out


def _reader_scope(html: str) -> str:
    """Recorta o trecho do container .reading-content (onde ficam as paginas)."""
    for div in re.finditer(r"<div\b[^>]*>", html, re.IGNORECASE | re.DOTALL):
        classes = set(str(_attrs_from_tag(div.group(0)).get("class") or "").split())
        if "reading-content" not in classes:
            continue
        tail = html[div.start():]
        end = re.search(
            r'(?=<div\b[^>]*class=["\'][^"\']*(?:nav-links|wp-manga-nav|comments-area)'
            r"|<footer\b|</main>|</body>)",
            tail, re.IGNORECASE,
        )
        return tail[: end.start()] if end else tail
    return html


def _looks_like_page_image(url: str) -> bool:
    path = unquote(urlparse(url).path)
    if not _IMG_EXT_RE.search(path):
        return False
    low = url.lower()
    return "/mangasbrasuka/manga_" in low or "/mangasbrasuka/manga/" in low


def _extract_reader_images(html: str, page_url: str) -> list[str]:
    scope = _reader_scope(html)
    candidates: list[str] = []
    for tag in re.findall(r"<img\b[^>]*>", scope, re.IGNORECASE | re.DOTALL):
        attrs = _attrs_from_tag(tag)
        for attr in ("data-src", "data-original", "data-lazy-src", "src"):
            candidates.append(_normalize_url(attrs.get(attr), page_url))
        candidates.extend(_normalize_url(u, page_url) for u in _srcset_urls(attrs.get("srcset")))
        candidates.extend(_normalize_url(u, page_url) for u in _srcset_urls(attrs.get("data-srcset")))
    candidates.extend(
        _normalize_url(m, page_url)
        for m in re.findall(
            r'https?://cdn\.mugiverso\.com/mangasbrasuka/manga[_/][^\s"\'<>]+\.(?:jpg|jpeg|png|webp)',
            scope, re.IGNORECASE,
        )
    )
    # dedupe preservando ordem + filtra so paginas reais
    seen: set[str] = set()
    out: list[str] = []
    for url in candidates:
        if url and url not in seen and _looks_like_page_image(url):
            seen.add(url)
            out.append(url)
    return out


def _chapter_number(url: str) -> str | None:
    slug = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
    m = _CHAPTER_SLUG_RE.search(slug)
    return m.group(1) if m else None


@register
class MangasBrasukaScraper(BaseScraper):
    name = "MangasBrasuka"

    def __init__(self) -> None:
        super().__init__()
        self.session.headers.update({
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
            "Referer": BASE + "/",
        })

    def _get_html(self, url: str, referer: str | None = None) -> str:
        headers = {"Referer": referer} if referer else {}
        resp = self.session.get(url, headers=headers, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        resp.raise_for_status()
        return resp.text

    # --- 1) mangas ----------------------------------------------------------
    def iter_mangas(self, max_pages: int = 1) -> Iterator[MangaRef]:
        for page in range(1, max_pages + 1):
            url = f"{BASE}/manga/page/{page}/" if page > 1 else f"{BASE}/manga/"
            try:
                html = self._get_html(url)
            except Exception as exc:
                logger.error("falha no diretorio %s: %s", url, exc)
                break
            seen: set[str] = set()
            # ancoras p/ /manga/<slug>/ (exclui capitulos)
            for tag, inner in re.findall(
                r'(<a\b[^>]*href=["\'][^"\']*?/manga/[^"\']+["\'][^>]*>)(.*?)</a>',
                html, re.IGNORECASE | re.DOTALL,
            ):
                href = _normalize_url(_attrs_from_tag(tag).get("href"), url)
                if not href or "/capitulo-" in href:
                    continue
                m = re.search(r"/manga/([^/]+)/?$", urlparse(href).path)
                if not m:
                    continue
                href = f"{BASE}/manga/{m.group(1)}/"
                if href in seen:
                    continue
                seen.add(href)
                name = _TAG_RE.sub("", inner).strip() or m.group(1)
                yield MangaRef(name=name, url=href)

    # --- 2) capitulos -------------------------------------------------------
    def iter_chapters(self, manga: MangaRef) -> Iterator[ChapterRef]:
        manga_url = manga.url.rstrip("/") + "/"
        html = self._get_html(manga_url)

        # nome canonico (titulo da pagina), se houver
        title_m = re.search(r'<div class="post-title">.*?<h1[^>]*>(.*?)</h1>', html, re.IGNORECASE | re.DOTALL)
        if title_m:
            name = _TAG_RE.sub("", title_m.group(1)).strip()
            manga = MangaRef(name=name or manga.name, url=manga_url, extra=manga.extra)

        chapters = self._parse_chapters(html, manga_url, manga)

        # Madara: o HTML estatico traz so 1o+ultimo cap. A lista COMPLETA vem do
        # endpoint AJAX `<manga_url>ajax/chapters/` (inclui decimais). Pega a maior.
        try:
            ajax = self._fetch_chapters_ajax(manga_url, manga, html)
            if len(ajax) > len(chapters):
                chapters = ajax
        except requests.RequestException as exc:
            logger.warning("AJAX de capitulos falhou: %s", exc)

        # ultimo fallback: monta o range pelos limites (so inteiros).
        bounds = self._chapter_bounds(html, manga_url)
        if bounds:
            low, high = bounds
            if len(chapters) < (high - low + 1):
                chapters = self._build_chapter_range(manga_url, manga, low, high)

        if not chapters:
            logger.warning("nenhum capitulo encontrado em %s", manga_url)
        # ordem crescente
        for chapter in chapters:
            yield chapter

    @staticmethod
    def _chapter_bounds(html: str, manga_url: str) -> tuple[int, int] | None:
        base = manga_url.rstrip("/")
        nums: list[int] = []
        for href in re.findall(r'href=["\']([^"\']+)["\']', html, re.IGNORECASE | re.DOTALL):
            url = _normalize_url(href, manga_url).rstrip("/") + "/"
            if not url.startswith(base + "/capitulo-"):
                continue
            num = _chapter_number(url)
            if num and float(num).is_integer():
                nums.append(int(float(num)))
        return (min(nums), max(nums)) if nums else None

    @staticmethod
    def _build_chapter_range(manga_url: str, manga: MangaRef, low: int, high: int) -> list[ChapterRef]:
        if low > high:
            low, high = high, low
        base = manga_url.rstrip("/")
        out: list[ChapterRef] = []
        for n in range(low, high + 1):
            out.append(ChapterRef(
                manga=manga, chapter=str(n),
                url=f"{base}/capitulo-{n}/", extra={"label": f"capitulo-{n}"},
            ))
        return out

    def _parse_chapters(self, html: str, manga_url: str, manga: MangaRef) -> list[ChapterRef]:
        base = manga_url.rstrip("/")
        found: dict[str, ChapterRef] = {}
        for href in re.findall(r'<a\b[^>]+href=["\']([^"\']+)["\']', html, re.IGNORECASE | re.DOTALL):
            url = _normalize_url(href, manga_url).rstrip("/") + "/"
            if not url.startswith(base + "/capitulo-"):
                continue
            num = _chapter_number(url)
            if not num:
                continue
            found[url] = ChapterRef(manga=manga, chapter=num, url=url, extra={"label": f"capitulo-{num}"})
        return sorted(found.values(), key=lambda c: (float(c.chapter), c.url))

    def _fetch_chapters_ajax(self, manga_url: str, manga: MangaRef, manga_html: str = "") -> list[ChapterRef]:
        """Lista completa via Madara. Tenta `<manga_url>ajax/chapters/` (sem id),
        depois admin-ajax `manga_get_chapters` (com id extraido do HTML).
        """
        ajax_headers = {
            "Referer": manga_url,
            "X-Requested-With": "XMLHttpRequest",
            "Origin": BASE,
        }
        # 1) endpoint REST-style (mais novo, nao precisa de id)
        try:
            resp = self.session.post(manga_url.rstrip("/") + "/ajax/chapters/",
                                     headers=ajax_headers, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 200:
                parsed = self._parse_chapters(resp.text, manga_url, manga)
                if parsed:
                    return parsed
        except requests.RequestException as exc:
            logger.debug("ajax/chapters falhou: %s", exc)

        # 2) admin-ajax com manga_id
        mid = (
            re.search(r'"manga_id":"(\d+)"', manga_html)
            or re.search(r'id=["\']manga-chapters-holder["\'][^>]*data-id=["\'](\d+)["\']', manga_html)
            or re.search(r'data-id=["\'](\d+)["\']', manga_html)
        )
        if mid:
            resp = self.session.post(
                BASE + "/wp-admin/admin-ajax.php",
                data={"action": "manga_get_chapters", "manga": mid.group(1)},
                headers={**ajax_headers, "Content-Type": "application/x-www-form-urlencoded"},
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            return self._parse_chapters(resp.text, manga_url, manga)
        return []

    # --- 3) paginas ---------------------------------------------------------
    def iter_pages(self, chapter: ChapterRef) -> Iterator[PageRef]:
        html = self._get_html(chapter.url, referer=chapter.manga.url)
        images = _extract_reader_images(html, chapter.url)
        for idx, url in enumerate(images, start=1):
            yield PageRef(
                chapter=chapter,
                page_number=idx,
                image_url=url,
                headers={
                    "Referer": chapter.url,
                    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                },
            )
