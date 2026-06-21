"""Scraper do MangaKatana (HTML, via requests + BeautifulSoup).

Segundo modelo concreto (o 1o, MangaDex, e API JSON; este e HTML puro).

Estrutura observada do site:
    - Diretorio:   https://mangakatana.com/manga            (lista paginada)
    - Mangá:       https://mangakatana.com/manga/<slug>.<id>
    - Capitulo:    https://mangakatana.com/manga/<slug>.<id>/c<num>   (ex: c202.5, c44-v2)
    - Leitor:      imgs lazy em  #imgs .wrapper-img img[data-src]
                   (fallback: URLs num array JS inline -> regex)

NOTE: seletores podem mudar; ha fallback por regex p/ as imagens. As imagens do
CDN exigem Referer da pagina do capitulo (setado em PageRef.headers).
"""

from __future__ import annotations

import logging
import re
from typing import Iterator
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from config import REQUEST_TIMEOUT
from .base import BaseScraper, ChapterRef, MangaRef, PageRef
from . import register

logger = logging.getLogger(__name__)

BASE = "https://mangakatana.com"

# Numero do capitulo a partir da URL: /c202.5 -> "202.5", /c44-v2 -> "44".
_CHAPTER_NUM_RE = re.compile(r"/c([0-9]+(?:\.[0-9]+)?)", re.IGNORECASE)

# Fallback: URLs de imagem dentro de <script> (array JS ofuscado).
_IMG_URL_RE = re.compile(
    r"""['"](https?://[^'"\\\s]+?\.(?:jpe?g|png|webp|gif)(?:\?[^'"\\\s]*)?)['"]""",
    re.IGNORECASE,
)

# Lixo a ignorar (logo, ads, avatar, etc.) na extracao de paginas.
_SKIP_HINTS = ("logo", "banner", "/ads", "avatar", "favicon", "icon", "/static/", "cover", "thumb")


@register
class MangaKatanaScraper(BaseScraper):
    name = "MangaKatana"

    def __init__(self) -> None:
        super().__init__()
        # bs4 usa lxml se instalado; senao cai p/ o parser embutido.
        try:
            import lxml  # noqa: F401
            self._parser = "lxml"
        except ImportError:
            self._parser = "html.parser"

    # --- HTTP ---------------------------------------------------------------
    def _get_soup(self, url: str) -> tuple[BeautifulSoup, str]:
        resp = self.session.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        html = resp.text
        return BeautifulSoup(html, self._parser), html

    # --- 1) mangas ----------------------------------------------------------
    def iter_mangas(self, max_pages: int = 1) -> Iterator[MangaRef]:
        """Percorre o diretorio. `max_pages` limita as paginas do listing."""
        for page in range(1, max_pages + 1):
            url = f"{BASE}/manga/page/{page}" if page > 1 else f"{BASE}/manga"
            try:
                soup, _ = self._get_soup(url)
            except Exception as exc:
                logger.error("falha no diretorio %s: %s", url, exc)
                break

            items = soup.select("#book_list .item")
            if not items:  # fallback: qualquer link p/ /manga/<slug>.<id>
                items = soup.select('a[href*="/manga/"]')
            seen: set[str] = set()
            for node in items:
                link = node.select_one("h3.title a, .title a, a") if node.name != "a" else node
                if not link or not link.get("href"):
                    continue
                href = urljoin(BASE, link["href"])
                # so paginas de obra (…/manga/slug.id), nao capitulos (…/cN)
                if "/manga/" not in href or _CHAPTER_NUM_RE.search(href):
                    continue
                if href in seen:
                    continue
                seen.add(href)
                name = link.get_text(strip=True) or link.get("title") or href.rsplit("/", 1)[-1]
                yield MangaRef(name=name, url=href)

    # --- 2) capitulos -------------------------------------------------------
    def iter_chapters(self, manga: MangaRef) -> Iterator[ChapterRef]:
        soup, _ = self._get_soup(manga.url)
        # nome canonico da obra, se disponivel
        heading = soup.select_one("h1.heading")
        manga_name = heading.get_text(strip=True) if heading else manga.name
        manga = MangaRef(name=manga_name, url=manga.url, extra=manga.extra)

        links = soup.select(".chapters .chapter a, .chapters a[href*='/c']")
        if not links:
            links = [a for a in soup.select('a[href*="/manga/"]') if _CHAPTER_NUM_RE.search(a.get("href", ""))]

        seen: set[str] = set()
        chapters: list[ChapterRef] = []
        for a in links:
            href = urljoin(BASE, a.get("href", ""))
            m = _CHAPTER_NUM_RE.search(href)
            if not m or href in seen:
                continue
            seen.add(href)
            chapters.append(
                ChapterRef(manga=manga, chapter=m.group(1), url=href,
                           extra={"title": a.get_text(strip=True)})
            )
        # site lista do mais novo p/ o mais antigo -> inverte p/ ordem crescente
        for chapter in reversed(chapters):
            yield chapter

    # --- 3) paginas ---------------------------------------------------------
    def iter_pages(self, chapter: ChapterRef) -> Iterator[PageRef]:
        soup, html = self._get_soup(chapter.url)

        # 1) <img data-src> reais (alguns layouts). Ignora placeholders "#".
        raw_urls: list[str] = []
        container = soup.select_one("#imgs") or soup
        for img in container.select(".wrapper-img img, .wrap_img img, #imgs img, img.b-lazy"):
            src = (img.get("data-src") or img.get("src") or "").strip()
            if src and src != "#" and not src.startswith("data:"):
                raw_urls.append(urljoin(chapter.url, src))

        # 2) fallback (caso comum no MangaKatana): array JS `var thzq=[...]`.
        if not raw_urls:
            raw_urls = self._image_urls_from_scripts(html)

        seen: set[str] = set()
        page_no = 0
        for url in raw_urls:
            low = url.lower()
            if url in seen or any(hint in low for hint in _SKIP_HINTS):
                continue
            seen.add(url)
            page_no += 1
            yield PageRef(
                chapter=chapter,
                page_number=page_no,
                image_url=url,
                headers={"Referer": chapter.url},
            )

    @staticmethod
    def _image_urls_from_scripts(html: str) -> list[str]:
        """Extrai as URLs das paginas do array JS do leitor.

        O MangaKatana guarda as imagens em `var thzq=[...]` (servidor 1) e
        `var ytaw=[...]` (servidor alternativo). Pegamos UM array (thzq primeiro)
        p/ nao misturar servidores. Fallback final: regex generico de imagens.
        """
        for var in ("thzq", "ytaw"):
            m = re.search(rf"var\s+{var}\s*=\s*\[(.*?)\]", html, re.DOTALL)
            if not m:
                continue
            urls = [u for u in re.findall(r"""['"]([^'"]+)['"]""", m.group(1)) if u.startswith("http")]
            if urls:
                return urls
        return [m.group(1) for m in _IMG_URL_RE.finditer(html)]
