"""Scraper de exemplo: MangaDex (usa a API JSON oficial).

Serve de MODELO para os demais sites. Os outros (que sao HTML) devem usar
requests + BeautifulSoup/lxml dentro dos mesmos 3 metodos.

NOTE: implementacao parcial/ilustrativa. Ajuste paginacao, rate-limit e
parsing conforme a necessidade real. MangaDex pede respeitar o rate-limit
(~5 req/s) e nao serve as imagens direto sem o endpoint /at-home.
"""

from __future__ import annotations

import logging
import re
from typing import Iterator

from .base import BaseScraper, ChapterRef, MangaRef, PageRef
from . import register

logger = logging.getLogger(__name__)

API = "https://api.mangadex.org"
_UUID_RE = re.compile(r"/manga/([0-9a-fA-F-]{36})")


@register
class MangaDexScraper(BaseScraper):
    name = "MangaDex"

    def iter_mangas(self) -> Iterator[MangaRef]:
        # Exemplo: top mangas por relevancia. Pagine com limit/offset conforme precisar.
        resp = self.session.get(
            f"{API}/manga",
            params={"limit": 10, "order[followedCount]": "desc"},
            timeout=30,
        )
        resp.raise_for_status()
        for entry in resp.json().get("data", []):
            attrs = entry.get("attributes", {})
            titles = attrs.get("title", {})
            name = titles.get("en") or titles.get("ja-ro") or next(iter(titles.values()), "Unknown")
            yield MangaRef(name=name, url=f"{API}/manga/{entry['id']}", extra={"id": entry["id"]})

    def iter_chapters(self, manga: MangaRef) -> Iterator[ChapterRef]:
        # Suporta --manga-url: deriva o id da URL se nao veio do iter_mangas.
        manga_id = manga.extra.get("id")
        if not manga_id:
            m = _UUID_RE.search(manga.url)
            manga_id = m.group(1) if m else (manga.url.strip().rstrip("/").rsplit("/", 1)[-1] or None)
        if not manga_id:
            raise ValueError(f"id do MangaDex nao encontrado em {manga.url!r}")
        resp = self.session.get(
            f"{API}/manga/{manga_id}/feed",
            params={"translatedLanguage[]": "pt-br", "order[chapter]": "asc", "limit": 100},
            timeout=30,
        )
        resp.raise_for_status()
        for entry in resp.json().get("data", []):
            attrs = entry.get("attributes", {})
            chapter_num = attrs.get("chapter") or "0"
            yield ChapterRef(
                manga=manga,
                chapter=str(chapter_num),
                url=f"{API}/chapter/{entry['id']}",
                extra={"id": entry["id"]},
            )

    def iter_pages(self, chapter: ChapterRef) -> Iterator[PageRef]:
        chapter_id = chapter.extra["id"]
        # MangaDex serve as imagens via servidor /at-home.
        resp = self.session.get(f"{API}/at-home/server/{chapter_id}", timeout=30)
        resp.raise_for_status()
        payload = resp.json()
        base = payload["baseUrl"]
        chap = payload["chapter"]
        hash_ = chap["hash"]
        for idx, filename in enumerate(chap.get("data", []), start=1):
            image_url = f"{base}/data/{hash_}/{filename}"
            yield PageRef(
                chapter=chapter,
                page_number=idx,
                image_url=image_url,
                headers={"Referer": "https://mangadex.org/"},
            )
