"""Scraper do Toomics (global.toomics.com, webtoon de rolagem vertical).

Quinto modelo: webtoon. Cada episodio = uma LISTA de imagens verticais (tiras),
capturadas de uma vez. Logica portada da producao (reader_server.py).

Estrutura:
    - toon_id:   .../webtoon/episode/toon/<toon_id>
    - Episodios: POST .../{lang}/webtoon/episode/toon/<toon_id>  (load_contents=Y, XHR)
    - Capitulo:  .../{lang}/webtoon/detail/code/<art_id>/ep/<ep>/toon/<toon_id>
    - Imagens:   <img id="set_image_..."> (class viewer/lazy/last_image) data-src

NOTE: episodios VIP/pagos nao retornam imagens (login/coin wall) -> iter_pages
devolve lista vazia e o crawler ignora. Free episodes funcionam.
"""

from __future__ import annotations

import logging
import re
from html import unescape
from typing import Iterator
from urllib.parse import urljoin

import requests

from config import REQUEST_TIMEOUT, USER_AGENT
from .base import BaseScraper, ChapterRef, MangaRef, PageRef
from . import register

logger = logging.getLogger(__name__)

BASE = "https://global.toomics.com"
_TAG_RE = re.compile(r"<[^>]+>")
_TOON_ID_RE = re.compile(r"/toon/(\d+)", re.IGNORECASE)
_DETAIL_RE = re.compile(r"/webtoon/detail/code/(\d+)/ep/(\d+(?:\.\d+)?)/toon/(\d+)", re.IGNORECASE)

_LANG_ALIASES = {"pt": "por", "pt-br": "por", "br": "por", "es": "esp", "en": "en", "en-us": "en"}


def _lang_path(lang: str | None) -> str:
    return _LANG_ALIASES.get((lang or "en").lower(), "en")


def _attrs(tag: str) -> dict[str, str]:
    return {
        k.lower(): unescape(v)
        for k, _q, v in re.findall(r'([a-zA-Z_:][-.\w:]*)\s*=\s*(["\'])(.*?)\2', tag, re.DOTALL)
    }


@register
class ToomicsScraper(BaseScraper):
    name = "Toomics"

    def __init__(self, lang: str = "en") -> None:
        super().__init__()
        self.lang = _lang_path(lang)

    def _headers(self, referer: str | None = None, ajax: bool = False) -> dict:
        h = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/html, */*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,pt;q=0.8",
            "Referer": referer or f"{BASE}/{self.lang}/webtoon/search_v2",
        }
        if ajax:
            h["X-Requested-With"] = "XMLHttpRequest"
        return h

    def _toon_id(self, url: str) -> str | None:
        m = _TOON_ID_RE.search(url)
        return m.group(1) if m else (url.strip() if url.strip().isdigit() else None)

    def _manga_url(self, toon_id: str) -> str:
        return f"{BASE}/{self.lang}/webtoon/episode/toon/{toon_id}"

    def _chapter_url(self, toon_id: str, art_id: str, episode: str) -> str:
        return f"{BASE}/{self.lang}/webtoon/detail/code/{art_id}/ep/{episode}/toon/{toon_id}"

    # --- 1) mangas (best-effort: pagina de listagem) ------------------------
    def iter_mangas(self) -> Iterator[MangaRef]:
        url = f"{BASE}/{self.lang}/webtoon/ranking"
        try:
            html = self.session.get(url, headers=self._headers(), timeout=REQUEST_TIMEOUT).text
        except Exception as exc:
            logger.error("falha na listagem Toomics %s: %s", url, exc)
            return
        seen: set[str] = set()
        for tag, inner in re.findall(
            r'(<a\b[^>]*href=["\'][^"\']*?/webtoon/episode/toon/\d+[^"\']*["\'][^>]*>)(.*?)</a>',
            html, re.IGNORECASE | re.DOTALL,
        ):
            href = urljoin(url, _attrs(tag).get("href", ""))
            tid = self._toon_id(href)
            if not tid or tid in seen:
                continue
            seen.add(tid)
            name = _TAG_RE.sub("", inner).strip()
            yield MangaRef(name=name or f"toon-{tid}", url=self._manga_url(tid), extra={"toon_id": tid})

    # --- 2) capitulos (episodios) -------------------------------------------
    def iter_chapters(self, manga: MangaRef, max_pages: int = 30) -> Iterator[ChapterRef]:
        toon_id = manga.extra.get("toon_id") or self._toon_id(manga.url)
        if not toon_id:
            logger.error("toon_id nao encontrado em %s", manga.url)
            return
        manga_url = self._manga_url(toon_id)

        # nome canonico via GET da pagina da obra (<title> limpo)
        name = manga.name
        try:
            page_html = self.session.get(manga_url, headers=self._headers(manga_url), timeout=REQUEST_TIMEOUT).text
            t = re.search(r"<title[^>]*>(.*?)</title>", page_html, re.IGNORECASE | re.DOTALL)
            if t:
                cand = _TAG_RE.sub("", unescape(t.group(1))).strip()
                cand = re.sub(r"\s*[-|]\s*Toomics\s*$", "", cand, flags=re.IGNORECASE)
                cand = re.sub(r"\s+EP\.?\s*\d+(?:\.\d+)?\s*$", "", cand, flags=re.IGNORECASE)
                cand = re.sub(r"\s+Episode\s+\d+.*$", "", cand, flags=re.IGNORECASE).strip()
                if cand and cand.lower() != "toomics":
                    name = cand
        except Exception:
            pass
        manga = MangaRef(name=name, url=manga_url, extra={"toon_id": toon_id})

        seen: set[str] = set()
        chapters: list[ChapterRef] = []
        for page in range(1, max_pages + 1):
            try:
                resp = self.session.post(
                    manga_url, data={"page": str(page), "load_contents": "Y"},
                    headers=self._headers(manga_url, ajax=True), timeout=REQUEST_TIMEOUT,
                )
                resp.raise_for_status()
                html = resp.text
            except requests.RequestException as exc:
                logger.warning("falha na pagina %d de episodios: %s", page, exc)
                break

            blocks = re.findall(r'<li\b[^>]*class=["\'][^"\']*normal_ep[^"\']*["\'][^>]*>[\s\S]*?</li>', html, re.IGNORECASE)
            if not blocks:
                blocks = re.findall(r"<a\b[^>]*>[\s\S]*?</a>", html, re.IGNORECASE)
            new = 0
            for block in blocks:
                m = _DETAIL_RE.search(block)
                if not m:
                    continue
                art_id, episode, found = m.groups()
                if str(found) != str(toon_id) or art_id in seen:
                    continue
                seen.add(art_id)
                new += 1
                vip = bool(re.search(r"VIP\s*ONLY|modal-login|coin-type", block, re.IGNORECASE))
                chapters.append(ChapterRef(
                    manga=manga, chapter=str(episode),
                    url=self._chapter_url(toon_id, art_id, episode),
                    extra={"art_id": art_id, "vip": vip},
                ))
            if new == 0:  # sem episodios novos -> fim da paginacao
                break

        chapters.sort(key=lambda c: (_to_float(c.chapter), c.url))
        for chapter in chapters:
            yield chapter

    # --- 3) paginas (lista vertical de tiras) -------------------------------
    def iter_pages(self, chapter: ChapterRef) -> Iterator[PageRef]:
        try:
            html = self.session.get(chapter.url, headers=self._headers(chapter.url), timeout=REQUEST_TIMEOUT).text
        except requests.RequestException as exc:
            logger.warning("falha GET capitulo %s: %s", chapter.url, exc)
            return

        seen: set[str] = set()
        page_no = 0
        for tag in re.findall(r"<img\b[^>]*>", html, re.IGNORECASE | re.DOTALL):
            if not re.search(r'id=["\']set_image_|class=["\'][^"\']*(?:viewer|lazy|last_image)', tag, re.IGNORECASE):
                continue
            attrs = _attrs(tag)
            raw = attrs.get("data-src") or attrs.get("data-original") or attrs.get("src")
            if not raw or raw.startswith("data:"):
                continue
            url = urljoin(BASE + "/", raw.strip())
            if url in seen:
                continue
            seen.add(url)
            page_no += 1
            yield PageRef(
                chapter=chapter, page_number=page_no, image_url=url,
                headers={"Referer": chapter.url},
            )
        if page_no == 0 and chapter.extra.get("vip"):
            logger.info("ep %s VIP/pago -> sem imagens (login/coin wall).", chapter.chapter)


def _to_float(value: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
