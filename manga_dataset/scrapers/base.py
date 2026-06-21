"""Contrato base dos scrapers + download temporario de imagem.

Cada site vira uma subclasse de BaseScraper implementando:
    - iter_mangas()             -> rende MangaRef
    - iter_chapters(manga)      -> rende ChapterRef
    - iter_pages(chapter)       -> rende PageRef (com a URL DIRETA da imagem)

O crawler so conhece essa interface; a logica de HTML fica isolada por site.
"""

from __future__ import annotations

import abc
import logging
import mimetypes
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

import requests

from config import REQUEST_TIMEOUT, TEMP_DIR, USER_AGENT

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MangaRef:
    name: str
    url: str
    extra: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ChapterRef:
    manga: MangaRef
    chapter: str          # "1050", "105.5", "Extra" ...
    url: str
    extra: dict = field(default_factory=dict)


@dataclass(frozen=True)
class PageRef:
    chapter: ChapterRef
    page_number: int
    image_url: str        # URL DIRETA da imagem na fonte
    headers: dict = field(default_factory=dict)  # ex: Referer especifico do site


class DownloadError(RuntimeError):
    """Falha ao baixar a imagem da pagina."""


class BaseScraper(abc.ABC):
    """Interface comum. `name` aparece na coluna `source` do banco."""

    name: str = "base"

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})

    # --- a implementar por site --------------------------------------------
    @abc.abstractmethod
    def iter_mangas(self) -> Iterator[MangaRef]:
        ...

    @abc.abstractmethod
    def iter_chapters(self, manga: MangaRef) -> Iterator[ChapterRef]:
        ...

    @abc.abstractmethod
    def iter_pages(self, chapter: ChapterRef) -> Iterator[PageRef]:
        ...

    # --- util compartilhado -------------------------------------------------
    def download_to_temp(self, page: PageRef) -> Path:
        """Baixa a imagem para um arquivo TEMPORARIO e devolve o caminho.

        O chamador (crawler) e responsavel por DELETAR o arquivo depois do
        upload. Nunca acumula em disco.
        """
        TEMP_DIR.mkdir(parents=True, exist_ok=True)
        headers = {**self.session.headers, **(page.headers or {})}
        try:
            resp = self.session.get(
                page.image_url, headers=headers, timeout=REQUEST_TIMEOUT, stream=True
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise DownloadError(f"GET falhou {page.image_url}: {exc}") from exc

        extension = self._guess_extension(page.image_url, resp.headers.get("Content-Type"))
        fd, tmp_name = tempfile.mkstemp(suffix=extension, dir=TEMP_DIR)
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=64 * 1024):
                    if chunk:
                        fh.write(chunk)
        except OSError as exc:
            tmp_path.unlink(missing_ok=True)
            raise DownloadError(f"Falha ao gravar temp {tmp_path}: {exc}") from exc

        if tmp_path.stat().st_size == 0:
            tmp_path.unlink(missing_ok=True)
            raise DownloadError(f"Imagem vazia: {page.image_url}")
        return tmp_path

    @staticmethod
    def _guess_extension(url: str, content_type: str | None) -> str:
        # 1) extensao explicita na URL (mais confiavel p/ CDNs).
        path = url.lower().split("?", 1)[0]
        for known in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"):
            if path.endswith(known):
                return ".jpg" if known == ".jpeg" else known
        # 2) content-type, so se for image/* (ignora octet-stream -> evita .bin).
        ctype = (content_type or "").split(";", 1)[0].strip().lower()
        if ctype.startswith("image/"):
            ext = mimetypes.guess_extension(ctype)
            if ext and ext not in (".bin", ".a", ".obj"):
                return ".jpg" if ext == ".jpe" else ext
        # 3) padrao: imagem de mangá -> jpg.
        return ".jpg"
