"""Scraper do DragonTea (dragontea.ink) — EXCECAO que usa navegador headless.

Sexta arquitetura: WordPress/Madara atras de Cloudflare AGRESSIVO (403 em
requests/curl_cffi) + imagens lazy via JS. Por isso herda de PlaywrightScraper
(browser headless isolado). O motor e os outros 5 scrapers seguem 100% HTTP.

Estrutura:
    - Diretorio: https://dragontea.ink/manga/
    - Mangá:     https://dragontea.ink/manga/<slug>/
    - Capitulo:  https://dragontea.ink/manga/<slug>/chapter-<n>/ (ou capitulo-<n>)
    - Leitor:    .reading-content .page-break img  (lazy -> scroll p/ carregar)
"""

from __future__ import annotations

import logging
import re
from typing import Iterator
from urllib.parse import unquote, urlparse

from .base import ChapterRef, MangaRef, PageRef
from .browser_base import PlaywrightScraper
from . import register

logger = logging.getLogger(__name__)

BASE = "https://dragontea.ink"
IMAGE_SELECTOR = ".reading-content .page-break img, .reading-content img"
_CHAPTER_NUM_RE = re.compile(r"(?:chapter|capitulo|cap)[-/_.\s]*(\d+(?:\.\d+)?)", re.IGNORECASE)


def _chapter_number(url: str) -> str | None:
    raw = unquote(f"{urlparse(url).path} {urlparse(url).query}")
    m = _CHAPTER_NUM_RE.search(raw)
    if m:
        return m.group(1)
    nums = re.findall(r"\d+(?:\.\d+)?", raw)
    return nums[-1] if nums else None


@register
class DragonTeaScraper(PlaywrightScraper):
    name = "DragonTea"
    # Cloudflare nao resolve em headless -> janela visivel + perfil PERSISTENTE.
    # 1a execucao: resolva o "Just a moment" na janela; o cf_clearance fica salvo
    # no perfil e as proximas execucoes passam direto.
    headless = False
    profile_dir = ".dragontea-profile"

    # --- 1) mangas ----------------------------------------------------------
    def iter_mangas(self) -> Iterator[MangaRef]:
        page = self.render(f"{BASE}/manga/", wait_selector="a[href*='/manga/']", wait_ms=2500)
        hrefs = page.evaluate(
            "() => Array.from(document.querySelectorAll('a[href*=\"/manga/\"]')).map(a => a.href)"
        ) or []
        seen: set[str] = set()
        for href in hrefs:
            m = re.search(r"/manga/([^/]+)/?$", urlparse(href).path)
            if not m:
                continue
            url = f"{BASE}/manga/{m.group(1)}/"
            if url in seen:
                continue
            seen.add(url)
            yield MangaRef(name=m.group(1), url=url)

    # --- 2) capitulos -------------------------------------------------------
    def iter_chapters(self, manga: MangaRef) -> Iterator[ChapterRef]:
        manga_url = manga.url.rstrip("/") + "/"
        page = self.render(manga_url, wait_selector=".wp-manga-chapter, .listing-chapters_wrap", wait_ms=2000)

        # nome canonico (titulo Madara)
        name = manga.name
        try:
            t = page.evaluate(
                "() => { const e = document.querySelector('.post-title h1, .post-title h3, h1'); "
                "return e ? e.textContent.trim() : ''; }"
            )
            if t:
                name = t.strip()
        except Exception:
            pass
        manga = MangaRef(name=name, url=manga_url, extra=manga.extra)

        hrefs = page.evaluate(
            "() => Array.from(document.querySelectorAll('.wp-manga-chapter a, .listing-chapters_wrap a'))"
            ".map(a => a.href)"
        ) or []

        base = manga_url.rstrip("/")
        seen: set[str] = set()
        chapters: list[ChapterRef] = []
        for href in hrefs:
            if not href or not href.rstrip("/").startswith(base) or href in seen:
                continue
            num = _chapter_number(href)
            if not num:
                continue
            seen.add(href)
            chapters.append(ChapterRef(manga=manga, chapter=num, url=href))

        chapters.sort(key=lambda c: (_to_float(c.chapter), c.url))  # ordem crescente
        for chapter in chapters:
            yield chapter

    # --- 3) paginas (lazy -> scroll p/ carregar tudo) -----------------------
    def iter_pages(self, chapter: ChapterRef) -> Iterator[PageRef]:
        page = self.render(chapter.url, wait_selector=".reading-content", wait_ms=1500)
        urls = self.scroll_collect_images(page, IMAGE_SELECTOR)
        page_no = 0
        for url in urls:
            if url.startswith("data:"):
                continue
            page_no += 1
            yield PageRef(
                chapter=chapter, page_number=page_no, image_url=url,
                headers={"Referer": chapter.url},
            )


def _to_float(value: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
