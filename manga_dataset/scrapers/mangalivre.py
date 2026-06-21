"""Scraper do MangaLivre (mangalivre.blog, WordPress nacional, atras de Cloudflare).

Quarto modelo: site nacional protegido por Cloudflare -> usa curl_cffi com
impersonate="chrome" (igual a producao do projeto). Fallback p/ requests se
curl_cffi nao estiver instalado (pode tomar 403).

Estrutura:
    - Diretorio: https://mangalivre.blog/manga/
    - Mangá:     https://mangalivre.blog/manga/<slug>/
    - Capitulo:  https://mangalivre.blog/capitulo/<chapter-slug>/
    - Caps:      ancoras <a href=".../capitulo/..."> no HTML da obra
    - Leitor:    <img class="chapter-image"> (ou alt "pagina N") em /wp-content/uploads/
"""

from __future__ import annotations

import logging
import re
from html import unescape
from typing import Iterator
from urllib.parse import urljoin, urlparse

import requests

from config import REQUEST_TIMEOUT, USER_AGENT
from .base import BaseScraper, ChapterRef, MangaRef, PageRef
from . import register

logger = logging.getLogger(__name__)

try:  # Cloudflare: curl_cffi imita o TLS/JA3 do Chrome.
    from curl_cffi import requests as curl_requests
except ImportError:
    curl_requests = None

BASE = "https://mangalivre.blog"
_TAG_RE = re.compile(r"<[^>]+>")
_CHAPTER_NUM_RE = re.compile(r"(?:^|-)capitulo-(\d+)(?:-(\d+)(?=-))?", re.IGNORECASE)


def _attrs(tag: str) -> dict[str, str]:
    return {
        k.lower(): unescape(v)
        for k, _q, v in re.findall(r'([a-zA-Z_:][-.\w:]*)\s*=\s*(["\'])(.*?)\2', tag, re.DOTALL)
    }


def _chapter_slug(url: str) -> str | None:
    m = re.search(r"/capitulo/([^/?#]+)", url, re.IGNORECASE)
    return m.group(1).strip("/") if m else None


def _chapter_number(slug: str | None) -> str | None:
    if not slug:
        return None
    m = _CHAPTER_NUM_RE.search(slug)
    if not m:
        return None
    return f"{m.group(1)}.{m.group(2)}" if m.group(2) else m.group(1)


@register
class MangaLivreScraper(BaseScraper):
    name = "MangaLivre"

    def __init__(self) -> None:
        super().__init__()
        self._headers = {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
            "Referer": BASE + "/",
        }
        if curl_requests is None:
            logger.warning("curl_cffi ausente: MangaLivre pode tomar 403 do Cloudflare. "
                           "Instale com `pip install curl_cffi`.")

    # --- HTTP (Cloudflare via curl_cffi quando disponivel) ------------------
    def _get_html(self, url: str, referer: str | None = None) -> str:
        headers = {**self._headers, "Referer": referer or self._headers["Referer"]}
        if curl_requests is not None:
            resp = curl_requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT, impersonate="chrome")
        else:
            resp = self.session.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.text

    def download_to_temp(self, page: PageRef):
        """Usa curl_cffi p/ baixar a imagem (Cloudflare) quando disponivel."""
        if curl_requests is None:
            return super().download_to_temp(page)
        import os
        import tempfile
        from pathlib import Path
        from config import TEMP_DIR
        from .base import DownloadError

        TEMP_DIR.mkdir(parents=True, exist_ok=True)
        headers = {**self._headers, **(page.headers or {})}
        try:
            resp = curl_requests.get(page.image_url, headers=headers,
                                     timeout=REQUEST_TIMEOUT, impersonate="chrome")
            resp.raise_for_status()
            content = resp.content
        except Exception as exc:  # noqa: BLE001
            raise DownloadError(f"GET falhou {page.image_url}: {exc}") from exc
        if not content:
            raise DownloadError(f"Imagem vazia: {page.image_url}")
        ext = self._guess_extension(page.image_url, resp.headers.get("Content-Type"))
        fd, name = tempfile.mkstemp(suffix=ext, dir=TEMP_DIR)
        with os.fdopen(fd, "wb") as fh:
            fh.write(content)
        return Path(name)

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
            for tag, inner in re.findall(
                r'(<a\b[^>]*href=["\'][^"\']*?/manga/[^"\']+["\'][^>]*>)(.*?)</a>',
                html, re.IGNORECASE | re.DOTALL,
            ):
                href = urljoin(url, _attrs(tag).get("href", ""))
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

        # nome canonico: og:title -> <title> (sem sufixo do site) -> slug
        name = manga.name
        og = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)', html, re.IGNORECASE)
        if og and _TAG_RE.sub("", unescape(og.group(1))).strip():
            name = _TAG_RE.sub("", unescape(og.group(1))).strip()
        else:
            t = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
            if t:
                clean = _TAG_RE.sub("", unescape(t.group(1))).strip()
                clean = re.split(r"\s+[-–|]\s+", clean)[0].strip()  # corta " - MangaLivre" etc.
                clean = re.sub(r"\s+mang[aá]$", "", clean, flags=re.IGNORECASE).strip()
                if clean:
                    name = clean
        manga = MangaRef(name=name, url=manga_url, extra=manga.extra)

        seen: set[str] = set()
        chapters: list[ChapterRef] = []
        for href, body in re.findall(
            r'<a\b[^>]+href=["\']([^"\']*/capitulo/[^"\']+)["\'][^>]*>(.*?)</a>',
            html, re.IGNORECASE | re.DOTALL,
        ):
            url = urljoin(manga_url, unescape(href))
            slug = _chapter_slug(url)
            if not slug or slug in seen:
                continue
            seen.add(slug)
            label = _TAG_RE.sub("", body).strip()
            number = _chapter_number(slug)
            # tenta refinar pelo rotulo "Capitulo N(.D)"
            mlabel = re.search(r"cap[ií]tulo\s+(\d+(?:[.,]\d+)?)", label, re.IGNORECASE)
            if mlabel:
                number = mlabel.group(1).replace(",", ".")
            if number is None:
                continue
            chapters.append(ChapterRef(
                manga=manga, chapter=number,
                url=f"{BASE}/capitulo/{slug}/", extra={"slug": slug, "label": label},
            ))

        chapters.sort(key=lambda c: (float(c.chapter) if _is_float(c.chapter) else 0.0, c.url))
        for chapter in chapters:
            yield chapter

    # --- 3) paginas ---------------------------------------------------------
    def iter_pages(self, chapter: ChapterRef) -> Iterator[PageRef]:
        html = self._get_html(chapter.url, referer=chapter.manga.url)
        preferred: list[str] = []
        fallback: list[str] = []
        for tag in re.findall(r"<img\b[^>]*>", html, re.IGNORECASE | re.DOTALL):
            attrs = _attrs(tag)
            raw = attrs.get("data-src") or attrs.get("data-original") or attrs.get("src")
            if not raw or raw.startswith("data:") or "flagcdn.com" in raw:
                continue
            url = urljoin(chapter.url, raw.strip())
            cls = attrs.get("class", "")
            alt = attrs.get("alt", "")
            if "chapter-image" in cls or re.search(r"p[aá]gina\s+\d+", alt, re.IGNORECASE):
                preferred.append(url)
            elif "/wp-content/uploads/" in url:
                fallback.append(url)

        seen: set[str] = set()
        page_no = 0
        for url in (preferred or fallback):
            if url in seen:
                continue
            seen.add(url)
            page_no += 1
            yield PageRef(
                chapter=chapter, page_number=page_no, image_url=url,
                headers={"Referer": chapter.url},
            )


def _is_float(value: str) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False
