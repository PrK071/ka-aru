"""Template de scraper (MODELO publico, nao aponta p/ nenhuma fonte real).

Copie este arquivo para `scrapers/<sua_fonte>.py`, implemente os 3 metodos e
decore com @register. O loader (scrapers/__init__.py) acha sozinho.

Para fontes que exigem navegador (Cloudflare/JS pesado), herde de
`PlaywrightScraper` (em browser_base.py) no lugar de BaseScraper.
"""

from __future__ import annotations

from typing import Iterator

from .base import BaseScraper, ChapterRef, MangaRef, PageRef
from . import register

BASE = "https://example.com"  # troque pela base da sua fonte


@register
class ExampleSource(BaseScraper):
    name = "ExampleSource"  # vira a coluna `source` no banco

    def iter_mangas(self) -> Iterator[MangaRef]:
        # Liste as obras do diretorio da fonte.
        # Ex.: GET {BASE}/lista -> parse -> yield MangaRef(name=..., url=...)
        return iter(())  # template: nada

    def iter_chapters(self, manga: MangaRef) -> Iterator[ChapterRef]:
        # GET manga.url -> parse capitulos -> yield ChapterRef(...)
        return iter(())

    def iter_pages(self, chapter: ChapterRef) -> Iterator[PageRef]:
        # GET chapter.url -> parse imagens -> yield PageRef(image_url=..., page_number=...)
        # Use PageRef.headers={"Referer": chapter.url} se o CDN exigir.
        return iter(())
