from __future__ import annotations

import argparse
import atexit
import asyncio
import base64
import difflib
import io
import json
import mimetypes
import os
import re
import shutil
import tempfile
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from html import unescape
from html.parser import HTMLParser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, quote, unquote, urljoin, urlparse

import cloudscraper
import requests
from PIL import Image
try:
    from curl_cffi import requests as curl_requests
except Exception:
    curl_requests = None

try:
    from playwright.sync_api import (
        Error as PlaywrightError,
        TimeoutError as PlaywrightTimeoutError,
        sync_playwright,
    )
except Exception:
    PlaywrightError = RuntimeError
    PlaywrightTimeoutError = TimeoutError
    sync_playwright = None

from mangafire_scraper import (
    Chapter,
    BASE_URL,
    DEFAULT_HEADERS,
    build_driver,
    chapter_images_api_url,
    chapter_list_api_url,
    chapter_url_from_number,
    chapter_number_from_url,
    chapter_number_text_from_url,
    clean_filename,
    clear_resource_timings,
    create_cloudscraper,
    extract_chapters_from_payload,
    extract_image_urls,
    fetch_chapter_images_http,
    fetch_chapters_http,
    filename_from_url,
    format_chapter_number,
    is_chapter_list_api,
    is_image_list_api,
    manga_page_url,
    normalize_lang,
    request_json,
    resource_urls,
    session_from_driver,
    session_from_scraper,
    slug_from_url,
    wait_for_resource_url,
)
from mangafire_vrf import generate_vrf

MANGADEX_API_URL = "https://api.mangadex.org"
MANGADEX_UPLOADS_URL = "https://uploads.mangadex.org"
ANILIST_GRAPHQL_URL = "https://graphql.anilist.co"
DEFAULT_READFULL_API_URL = "https://readfullapi.herokuapp.com"
DEFAULT_NOVELTOON_BASE_URL = "https://noveltoon.mobi"
DEFAULT_PIECEPROJECT_URL = "https://scan.onepieceproject.com.br/"
DEFAULT_DRAGONTEA_BASE_URL = "https://dragontea.ink"
DEFAULT_TOOMICS_BASE_URL = "https://global.toomics.com"
DEFAULT_MANGAKATANA_BASE_URL = "https://mangakatana.com"
DEFAULT_MANGALIVRE_BASE_URL = "https://mangalivre.blog"
MANGALIVRE_CACHE_SECONDS = 900
DRAGONTEA_IMAGE_SELECTOR = ".reading-content .page-break img"
TOOMICS_IMAGE_SELECTOR = "#viewer-img img, .viewer-imgs img"
TOOMICS_COMPOSITE_IMAGES_PER_CHUNK = 16
UUID_PATTERN = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
SEARCH_GOOD_SCORE = 0.86
SEARCH_TIMEOUT_SECONDS = 12
SEARCH_TOTAL_TIMEOUT_SECONDS = 20
SEARCH_BROWSER_TIMEOUT_SECONDS = 18
MAX_FUZZY_SEARCH_TERMS = 5
MANGADEX_SPARSE_LANGUAGE_THRESHOLD = 8

DRAGONTEA_RESTORE_IMAGES_JS = r"""
(selector) => {
  const result = {
    restored: false,
    decryptorFound: Boolean(window.CryptoJSAesJson && window.CryptoJSAesJson.decrypt),
    imageCount: document.querySelectorAll(selector).length,
    errors: [],
  };

  if (!window.CryptoJSAesJson || typeof window.CryptoJSAesJson.decrypt !== "function") {
    result.errors.push("CryptoJSAesJson.decrypt nao existe na pagina.");
    return result;
  }

  const countImages = () => document.querySelectorAll(selector).length;
  const decrypt = (data, key) => window.CryptoJSAesJson.decrypt(data, key);

  function getHeaderDataId() {
    const header = document.querySelector(".entry-header.header");
    if (!header) return 0;
    return Number.parseInt(header.getAttribute("data-id"), 10) || 0;
  }

  const VARIABLE_1 = 3;
  const VARIABLE_2 = 5;
  const VARIABLE_3 = 13;
  const VARIABLE_4 = "07";
  let VARIABLE_5 = "";
  let VARIABLE_6 = "";
  const VARIABLE_7 = 1;
  const VARIABLE_8 = 6;
  const VARIABLE_9 = 1;
  const VARIABLE_10 = 5;
  const VARIABLE_11 = 2;
  const VARIABLE_12 = 8;
  const VARIABLE_13 = 8;

  const combineNumbers = (num1, num2) => Number.parseInt(num1.toString() + num2.toString(), 10);
  const stringifyNumbers = (...numbers) => numbers.reduce((acc, num) => acc + num.toString(), "");

  const calculateKey1 = () => {
    const cipher1 = Number.parseInt(
      (getHeaderDataId() + combineNumbers(VARIABLE_3, VARIABLE_4)) * VARIABLE_1 - countImages(),
      10,
    );
    const cipher2 = VARIABLE_2 * 2 + 1;
    return combineNumbers(cipher2, cipher1).toString();
  };

  const calculateKey2 = () => {
    const cipher1 = Number.parseInt(
      (getHeaderDataId() + combineNumbers(VARIABLE_12, VARIABLE_13)) * (VARIABLE_7 * 2)
        - countImages()
        - (VARIABLE_7 * 2 * 2 + 1),
      10,
    );
    const cipher2 = VARIABLE_8 * 2 + VARIABLE_9 + VARIABLE_9 + 1;
    return stringifyNumbers(cipher2, VARIABLE_5, cipher1);
  };

  const calculateKey3 = () => {
    const cipher1 = getHeaderDataId() + VARIABLE_10 * 2 * 2;
    const cipher3 = countImages() * (VARIABLE_11 * 2);
    return stringifyNumbers(cipher1, VARIABLE_6, cipher3);
  };

  const decryptSafe = (label, data, key) => {
    if (!data) return "";
    try {
      return decrypt(data, key) || "";
    } catch (error) {
      result.errors.push(`${label}: ${error && error.message ? error.message : error}`);
      return "";
    }
  };

  let images = document.querySelectorAll(selector);
  images.forEach((image) => {
    const decryptedId = decryptSafe("id", image.getAttribute("id"), calculateKey1());
    if (decryptedId) image.setAttribute("id", decryptedId);
  });

  images = document.querySelectorAll(selector);
  images.forEach((image) => {
    const id = image.getAttribute("id");
    if (!id) return;
    const index = Number.parseInt(id.replace(/image-(\d+)[a-z]+/i, "$1"), 10);
    const pageBreak = document.querySelectorAll(".reading-content .page-break")[index];
    if (pageBreak) pageBreak.appendChild(image);
  });

  images = document.querySelectorAll(selector);
  images.forEach((image) => {
    const id = image.getAttribute("id");
    if (!id) return;
    VARIABLE_5 += id.slice(-1);
    image.setAttribute("id", id.slice(0, -1));
  });

  images = document.querySelectorAll(selector);
  images.forEach((image) => {
    const decryptedData = decryptSafe("dta", image.getAttribute("dta"), calculateKey2());
    if (decryptedData) image.setAttribute("dta", decryptedData);
  });

  images = document.querySelectorAll(selector);
  images.forEach((image) => {
    const data = image.getAttribute("dta");
    if (!data) return;
    VARIABLE_6 += data.slice(-2);
    image.removeAttribute("dta");
  });

  images = document.querySelectorAll(selector);
  images.forEach((image) => {
    const decryptedDataSrc = decryptSafe("data-src", image.getAttribute("data-src"), calculateKey3());
    if (decryptedDataSrc) image.setAttribute("data-src", decryptedDataSrc);
    image.classList.add("wp-manga-chapter-img", "img-responsive", "lazyload", "effect-fade");
  });

  result.restored = true;
  result.imageCount = document.querySelectorAll(selector).length;
  return result;
}
"""

DRAGONTEA_COLLECT_IMAGE_URLS_JS = r"""
({ selector, attrs }) => {
  const urls = [];
  const seen = new Set();

  const add = (value) => {
    if (!value || typeof value !== "string") return;
    const trimmed = value.trim();
    if (!trimmed || trimmed === "#" || trimmed.startsWith("data:")) return;

    let url;
    try {
      url = new URL(trimmed, document.baseURI).href;
    } catch {
      return;
    }

    if (!url.startsWith("http://") && !url.startsWith("https://")) return;
    if (seen.has(url)) return;
    seen.add(url);
    urls.push(url);
  };

  const pickFromSrcset = (srcset) => {
    if (!srcset || typeof srcset !== "string") return null;
    let bestUrl = null;
    let bestScore = -1;
    for (const item of srcset.split(",")) {
      const parts = item.trim().split(/\s+/);
      if (!parts[0]) continue;
      let score = 0;
      const descriptor = parts[1] || "";
      if (descriptor.endsWith("w")) {
        score = Number.parseInt(descriptor.slice(0, -1), 10) || 0;
      } else if (descriptor.endsWith("x")) {
        score = (Number.parseFloat(descriptor.slice(0, -1)) || 0) * 1000;
      }
      if (score > bestScore) {
        bestScore = score;
        bestUrl = parts[0];
      }
    }
    return bestUrl;
  };

  document.querySelectorAll(selector).forEach((image) => {
    for (const attr of attrs) {
      add(image[attr]);
      add(image.getAttribute(attr));
    }
    add(pickFromSrcset(image.getAttribute("srcset")));
    add(pickFromSrcset(image.getAttribute("data-srcset")));
  });
  return urls;
}
"""

INDEX_HTML = r"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>MangaTemp Reader</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #07111f;
      --panel: #101b2b;
      --panel-strong: #17263b;
      --text: #edf4ff;
      --muted: #9fb1c9;
      --accent: #4da3ff;
      --danger: #ff6b6b;
      --line: #263850;
    }

    * {
      box-sizing: border-box;
    }

    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: Arial, Helvetica, sans-serif;
      letter-spacing: 0;
    }

    button,
    input,
    select {
      font: inherit;
    }

    .topbar {
      position: sticky;
      top: 0;
      z-index: 20;
      display: grid;
      grid-template-columns: minmax(260px, 1fr) 82px 98px auto minmax(170px, 0.55fr) auto auto auto auto;
      gap: 8px;
      align-items: center;
      padding: 10px 12px;
      background: rgba(7, 17, 31, 0.96);
      border-bottom: 1px solid var(--line);
    }

    .url-input,
    .small-input,
    .chapter-select {
      width: 100%;
      min-width: 0;
      height: 38px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: var(--panel);
      color: var(--text);
      padding: 0 12px;
      outline: none;
    }

    .small-input {
      text-align: center;
    }

    .chapter-select {
      cursor: pointer;
    }

    .url-input:focus,
    .small-input:focus,
    .chapter-select:focus {
      border-color: var(--accent);
    }

    .button {
      height: 38px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: var(--panel-strong);
      color: var(--text);
      padding: 0 14px;
      cursor: pointer;
      white-space: nowrap;
    }

    .button:hover {
      border-color: var(--accent);
    }

    .button:disabled {
      cursor: not-allowed;
      opacity: 0.45;
    }

    .button.danger {
      color: #ffd8d8;
      border-color: #65313a;
      background: #321821;
    }

    .meta {
      display: flex;
      gap: 10px;
      align-items: center;
      min-height: 42px;
      padding: 8px 14px;
      color: var(--muted);
      border-bottom: 1px solid var(--line);
      background: #0a1423;
      font-size: 14px;
      overflow: hidden;
    }

    .meta strong {
      color: var(--text);
      font-weight: 600;
    }

    .progress {
      position: fixed;
      left: 0;
      right: 0;
      bottom: 0;
      z-index: 25;
      height: 4px;
      background: rgba(255, 255, 255, 0.08);
    }

    .progress > div {
      width: 0%;
      height: 100%;
      background: var(--accent);
      transition: width 160ms linear;
    }

    .reader {
      max-width: min(100vw, 980px);
      margin: 0 auto;
      padding: 16px 10px 28px;
    }

    .empty {
      display: grid;
      place-items: center;
      min-height: calc(100vh - 100px);
      color: var(--muted);
      text-align: center;
      padding: 24px;
    }

    .page {
      display: block;
      width: 100%;
      min-height: 140px;
      margin: 0 auto 12px;
      background: #fff;
      border: 0;
    }

    .reader.fit-original .page {
      width: auto;
      max-width: 100%;
    }

    .status-error {
      color: var(--danger);
    }

    @media (max-width: 760px) {
      .topbar {
        grid-template-columns: 1fr 1fr;
      }

      .url-input,
      .chapter-select {
        grid-column: 1 / -1;
      }

      .button {
        padding: 0 10px;
      }

      .meta {
        align-items: flex-start;
        flex-direction: column;
        gap: 4px;
      }
    }
  </style>
</head>
<body>
  <header class="topbar">
    <input id="urlInput" class="url-input" placeholder="URL do manga ou capitulo" autocomplete="off">
    <input id="langInput" class="small-input" value="pt-br" autocomplete="off" title="Idioma">
    <input id="chapterInput" class="small-input" placeholder="Capitulo" autocomplete="off" title="Capitulo">
    <button id="chaptersBtn" class="button">Capitulos</button>
    <select id="chapterSelect" class="chapter-select" disabled>
      <option value="">Nenhum capitulo</option>
    </select>
    <button id="loadBtn" class="button">Abrir</button>
    <button id="prevBtn" class="button" disabled>Anterior</button>
    <button id="nextBtn" class="button" disabled>Proximo</button>
    <button id="fitBtn" class="button">Largura</button>
    <button id="clearBtn" class="button danger">Sair do capitulo</button>
    <button id="shutdownBtn" class="button danger">Fechar leitor</button>
  </header>

  <section class="meta">
    <span id="titleText"><strong>Nenhum capitulo aberto</strong></span>
    <span id="countText"></span>
    <span id="cacheText"></span>
  </section>

  <main id="reader" class="reader">
    <div class="empty">Abra um capitulo para ler em cache temporaria.</div>
  </main>

  <div class="progress"><div id="progressBar"></div></div>

  <script>
    const urlInput = document.getElementById("urlInput");
    const langInput = document.getElementById("langInput");
    const chapterInput = document.getElementById("chapterInput");
    const chaptersBtn = document.getElementById("chaptersBtn");
    const chapterSelect = document.getElementById("chapterSelect");
    const loadBtn = document.getElementById("loadBtn");
    const prevBtn = document.getElementById("prevBtn");
    const nextBtn = document.getElementById("nextBtn");
    const fitBtn = document.getElementById("fitBtn");
    const clearBtn = document.getElementById("clearBtn");
    const shutdownBtn = document.getElementById("shutdownBtn");
    const reader = document.getElementById("reader");
    const titleText = document.getElementById("titleText");
    const countText = document.getElementById("countText");
    const cacheText = document.getElementById("cacheText");
    const progressBar = document.getElementById("progressBar");

    let current = { url: "", previous: null, next: null };
    let availableChapters = [];
    let fitOriginal = false;

    function setBusy(isBusy, label = "Carregando...") {
      urlInput.disabled = isBusy;
      langInput.disabled = isBusy;
      chapterInput.disabled = isBusy;
      chaptersBtn.disabled = isBusy;
      chapterSelect.disabled = isBusy || availableChapters.length === 0;
      loadBtn.disabled = isBusy;
      prevBtn.disabled = isBusy || !current.previous;
      nextBtn.disabled = isBusy || !current.next;
      clearBtn.disabled = isBusy;
      shutdownBtn.disabled = isBusy;
      loadBtn.textContent = isBusy ? label : "Abrir";
    }

    function setStatus(message, isError = false) {
      cacheText.textContent = message;
      cacheText.classList.toggle("status-error", isError);
    }

    function setTitle(value) {
      titleText.innerHTML = "";
      const strong = document.createElement("strong");
      strong.textContent = value;
      titleText.appendChild(strong);
    }

    function fillChapterSelect(chapters, selectedUrl) {
      availableChapters = chapters;
      chapterSelect.innerHTML = "";

      if (chapters.length === 0) {
        const option = document.createElement("option");
        option.value = "";
        option.textContent = "Nenhum capitulo";
        chapterSelect.appendChild(option);
        chapterSelect.disabled = true;
        return;
      }

      for (const chapter of chapters) {
        const option = document.createElement("option");
        option.value = chapter.url;
        option.textContent = chapter.title
          ? `${chapter.label} - ${chapter.title}`
          : chapter.label;
        chapterSelect.appendChild(option);
      }

      chapterSelect.value = selectedUrl || chapters[0].url;
      chapterSelect.disabled = false;
    }

    function updateProgress() {
      const pages = Array.from(reader.querySelectorAll("img.page"));
      if (pages.length === 0) {
        progressBar.style.width = "0%";
        return;
      }

      let currentIndex = 0;
      let bestDistance = Number.POSITIVE_INFINITY;
      for (let i = 0; i < pages.length; i++) {
        const distance = Math.abs(pages[i].getBoundingClientRect().top - 80);
        if (distance < bestDistance) {
          bestDistance = distance;
          currentIndex = i;
        }
      }

      const progress = ((currentIndex + 1) / pages.length) * 100;
      progressBar.style.width = `${progress}%`;
      countText.textContent = `Pagina ${currentIndex + 1}/${pages.length}`;
    }

    function renderChapter(data) {
      current = {
        url: data.url,
        previous: data.previous,
        next: data.next,
      };

      urlInput.value = data.url;
      if (Array.from(chapterSelect.options).some((option) => option.value === data.url)) {
        chapterSelect.value = data.url;
      }
      setTitle(data.title || data.label);
      countText.textContent = data.mode === "text" ? "Texto" : `${data.count} paginas`;
      setStatus("Cache temporaria ativa");

      reader.innerHTML = "";
      reader.classList.toggle("fit-original", fitOriginal);

      if (data.mode === "text") {
        const article = document.createElement("article");
        article.style.maxWidth = "860px";
        article.style.margin = "0 auto";
        article.style.lineHeight = "1.75";
        article.style.fontSize = "18px";
        article.style.whiteSpace = "pre-wrap";
        article.textContent = data.content || "";
        reader.appendChild(article);
      } else {
        for (const image of data.images) {
          const img = document.createElement("img");
          img.className = "page";
          img.loading = "lazy";
          img.decoding = "async";
          img.alt = `Pagina ${image.index}`;
          img.src = image.src;
          img.addEventListener("load", updateProgress);
          reader.appendChild(img);
        }
      }

      prevBtn.disabled = !current.previous;
      nextBtn.disabled = !current.next;
      window.scrollTo(0, 0);
      updateProgress();
    }

    function selectedChapterUrl() {
      return chapterSelect.disabled ? "" : chapterSelect.value;
    }

    async function loadChapters(autoOpen = false) {
      const source = urlInput.value.trim();
      if (!source) return;

      const lang = (langInput.value || "pt-br").trim();
      const chapter = chapterInput.value.trim();
      const params = new URLSearchParams({ url: source, lang });
      if (chapter) params.set("chapter", chapter);

      setBusy(true, "Buscando...");
      setStatus("Buscando capitulos...");

      try {
        const response = await fetch(`/api/chapters?${params.toString()}`);
        const data = await response.json();
        if (!response.ok || !data.ok) {
          throw new Error(data.error || "Nao foi possivel buscar capitulos.");
        }

        fillChapterSelect(data.chapters, data.selected_url);
        setStatus(`${data.count} capitulos encontrados`);

        if (autoOpen) {
          await loadChapter(selectedChapterUrl());
        }
      } catch (error) {
        fillChapterSelect([], "");
        setStatus(error.message, true);
      } finally {
        setBusy(false);
      }
    }

    async function loadChapter(url) {
      let target = (url || selectedChapterUrl() || urlInput.value).trim();
      if (!target) return;

      const lang = (langInput.value || "pt-br").trim();
      const chapter = chapterInput.value.trim();

      if (!target.includes("/chapter-") && !selectedChapterUrl()) {
        await loadChapters(true);
        return;
      }

      setBusy(true, "Abrindo...");
      setStatus("Buscando paginas e preparando cache...");
      reader.innerHTML = '<div class="empty">Preparando leitor temporario...</div>';

      try {
        const params = new URLSearchParams({ url: target, lang });
        if (chapter) params.set("chapter", chapter);
        const response = await fetch(`/api/load?${params.toString()}`);
        const data = await response.json();
        if (!response.ok || !data.ok) {
          throw new Error(data.error || "Nao foi possivel abrir o capitulo.");
        }
        renderChapter(data);
      } catch (error) {
        current = { url: "", previous: null, next: null };
        setTitle("Nenhum capitulo aberto");
        countText.textContent = "";
        reader.innerHTML = `<div class="empty">${error.message}</div>`;
        setStatus(error.message, true);
      } finally {
        setBusy(false);
      }
    }

    async function clearChapter() {
      try {
        await fetch("/api/close", { method: "POST" });
      } catch {
        // The process may already be closing.
      }

      current = { url: "", previous: null, next: null };
      setTitle("Nenhum capitulo aberto");
      countText.textContent = "";
      setStatus("Cache apagada");
      reader.innerHTML = '<div class="empty">Cache removida. Abra outro capitulo quando quiser.</div>';
      prevBtn.disabled = true;
      nextBtn.disabled = true;
      progressBar.style.width = "0%";
    }

    async function shutdownReader() {
      try {
        await fetch("/api/shutdown", { method: "POST" });
      } catch {
        // The server may close before the browser observes the response.
      }

      current = { url: "", previous: null, next: null };
      setTitle("Leitor fechado");
      countText.textContent = "";
      setStatus("Servidor fechado e cache apagada");
      reader.innerHTML = '<div class="empty">O leitor foi fechado. Rode python reader_server.py para abrir de novo.</div>';
      loadBtn.disabled = true;
      prevBtn.disabled = true;
      nextBtn.disabled = true;
      clearBtn.disabled = true;
      shutdownBtn.disabled = true;
      progressBar.style.width = "0%";
    }

    chaptersBtn.addEventListener("click", () => loadChapters(false));
    loadBtn.addEventListener("click", () => loadChapter());
    prevBtn.addEventListener("click", () => current.previous && loadChapter(current.previous));
    nextBtn.addEventListener("click", () => current.next && loadChapter(current.next));
    chapterSelect.addEventListener("change", () => {
      if (chapterSelect.value) loadChapter(chapterSelect.value);
    });
    clearBtn.addEventListener("click", clearChapter);
    shutdownBtn.addEventListener("click", shutdownReader);
    fitBtn.addEventListener("click", () => {
      fitOriginal = !fitOriginal;
      reader.classList.toggle("fit-original", fitOriginal);
      fitBtn.textContent = fitOriginal ? "Original" : "Largura";
    });

    urlInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter") loadChapter();
    });

    urlInput.addEventListener("input", () => {
      fillChapterSelect([], "");
    });

    chapterInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter") loadChapter();
    });

    window.addEventListener("scroll", updateProgress, { passive: true });
    window.addEventListener("resize", updateProgress);
    window.addEventListener("beforeunload", () => {
      navigator.sendBeacon("/api/close", "");
    });

    const params = new URLSearchParams(window.location.search);
    const initialUrl = params.get("url");
    if (initialUrl) {
      urlInput.value = initialUrl;
      const initialLang = params.get("lang");
      const initialChapter = params.get("chapter");
      if (initialLang) langInput.value = initialLang;
      if (initialChapter) chapterInput.value = initialChapter;
      loadChapter(initialUrl);
    }
  </script>
</body>
</html>
"""


@dataclass
class ImageCacheEntry:
    path: Path
    content_type: str


@dataclass
class ChapterState:
    url: str
    label: str
    image_urls: list[str]
    cache_dir: Path
    session: requests.Session
    previous_url: str | None = None
    next_url: str | None = None
    image_cache: dict[int, ImageCacheEntry] = field(default_factory=dict)
    source_image_chunks: list[list[str]] = field(default_factory=list)


class MangaSearchParser(HTMLParser):
    def __init__(self, limit: int = 12) -> None:
        super().__init__(convert_charrefs=True)
        self.limit = limit
        self.results: list[dict] = []
        self._seen: set[str] = set()
        self._current: dict | None = None
        self._text: list[str] = []
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_name = tag.lower()
        if self._current is not None and tag_name in {"h3", "h4", "h5", "h6"}:
            self._in_title = True
            return

        if self._current is not None and tag_name == "img":
            data = {name.lower(): value for name, value in attrs if value is not None}
            self._current["title"] = self._current["title"] or data.get("alt") or ""
            return

        if tag_name != "a" or len(self.results) >= self.limit:
            return

        data = {name.lower(): value for name, value in attrs if value is not None}
        href = data.get("href") or ""
        if "/manga/" not in href:
            return

        url = urljoin(BASE_URL, href)
        if url in self._seen:
            return

        self._current = {
            "url": url,
            "title": data.get("title") or "",
        }
        self._text = []
        self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._current is not None:
            text = data.strip()
            if text:
                if self._in_title and not self._current["title"]:
                    self._current["title"] = text
                self._text.append(text)

    def handle_endtag(self, tag: str) -> None:
        tag_name = tag.lower()
        if tag_name in {"h3", "h4", "h5", "h6"}:
            self._in_title = False
            return

        if tag_name != "a" or self._current is None:
            return

        text = " ".join(self._text).strip()
        title = self._current["title"] or text
        url = self._current["url"]
        self._current = None
        self._text = []
        self._in_title = False

        if not title or url in self._seen:
            return

        self._seen.add(url)
        self.results.append({"title": title, "url": url})


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style"}:
            self.skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style"} and self.skip_depth:
            self.skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        text = data.strip()
        if text:
            self.parts.append(text)

    def text(self) -> str:
        return normalize_text(" ".join(self.parts))


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", unescape(value)).strip()


def normalize_match_text(value: str) -> str:
    value = unicodedata.normalize("NFKD", normalize_text(value))
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = re.sub(r"[^a-zA-Z0-9]+", " ", value).lower()
    return re.sub(r"\s+", " ", value).strip()


def fuzzy_match_score(query: str, *values: str | None) -> float:
    needle = normalize_match_text(query)
    haystack = normalize_match_text(" ".join(value or "" for value in values))
    if not needle or not haystack:
        return 0.0
    if needle == haystack:
        return 1.0
    if needle in haystack:
        return 0.95

    needle_tokens = needle.split()
    haystack_tokens = haystack.split()
    if needle_tokens and all(token in haystack_tokens for token in needle_tokens):
        return 0.9

    acronym = "".join(token[0] for token in haystack_tokens if token)
    scores = [
        difflib.SequenceMatcher(None, needle, haystack).ratio(),
        difflib.SequenceMatcher(None, needle, acronym).ratio() if acronym else 0.0,
    ]
    for token in haystack_tokens:
        scores.append(difflib.SequenceMatcher(None, needle, token).ratio())
    return max(scores)


def text_from_html(fragment: str) -> str:
    parser = TextExtractor()
    parser.feed(fragment or "")
    return parser.text()


def parse_float(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def first_localized_text(value, preferred: tuple[str, ...] = ("pt-br", "en")) -> str | None:
    if isinstance(value, str):
        return normalize_text(value) or None
    if not isinstance(value, dict):
        return None

    for key in preferred:
        text = value.get(key)
        if isinstance(text, str) and text.strip():
            return normalize_text(text)

    for text in value.values():
        if isinstance(text, str) and text.strip():
            return normalize_text(text)
    return None


def first_match(pattern: str, text: str, flags: int = re.IGNORECASE | re.DOTALL) -> str | None:
    match = re.search(pattern, text, flags)
    return match.group(1) if match else None


class TemporaryChapterCache:
    def __init__(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="mangafire-reader-"))
        self.current_dir: Path | None = None

    def new_chapter_dir(self, label: str) -> Path:
        self.clear_current()
        target = self.root / clean_filename(label, fallback="chapter")
        target.mkdir(parents=True, exist_ok=True)
        self.current_dir = target
        return target

    def clear_current(self) -> None:
        if self.current_dir and self.current_dir.exists():
            shutil.rmtree(self.current_dir, ignore_errors=True)
        self.current_dir = None

    def cleanup_all(self) -> None:
        if self.root.exists():
            shutil.rmtree(self.root, ignore_errors=True)
        self.current_dir = None

    def contains(self, path: Path) -> bool:
        try:
            path.resolve().relative_to(self.root.resolve())
            return True
        except ValueError:
            return False


class MangaFireReader:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.cache = TemporaryChapterCache()
        self.driver = None
        self.state: ChapterState | None = None
        self.lock = threading.RLock()
        self.api_base_url = ""
        self.readfull_api_base_url = (
            getattr(args, "readfull_api_url", None)
            or os.environ.get("READFULL_API_URL")
            or DEFAULT_READFULL_API_URL
        ).rstrip("/")
        self.noveltoon_base_url = (
            getattr(args, "noveltoon_base_url", None)
            or os.environ.get("NOVELTOON_BASE_URL")
            or DEFAULT_NOVELTOON_BASE_URL
        ).rstrip("/")
        self.toomics_base_url = (
            getattr(args, "toomics_base_url", None)
            or os.environ.get("TOOMICS_BASE_URL")
            or DEFAULT_TOOMICS_BASE_URL
        ).rstrip("/")
        self.mangakatana_base_url = (
            getattr(args, "mangakatana_base_url", None)
            or os.environ.get("MANGAKATANA_BASE_URL")
            or DEFAULT_MANGAKATANA_BASE_URL
        ).rstrip("/")
        self.mangalivre_base_url = (
            getattr(args, "mangalivre_base_url", None)
            or os.environ.get("MANGALIVRE_BASE_URL")
            or DEFAULT_MANGALIVRE_BASE_URL
        ).rstrip("/")
        self.use_api = False
        self.api_chapter_ids_by_url: dict[str, str] = {}
        self._pieceproject_cache: tuple[float, list[dict]] | None = None
        self._toomics_chapters_cache: dict[tuple[str, str, str], tuple[float, list[Chapter], dict]] = {}
        self._mangalivre_chapters_cache: dict[str, tuple[float, list[Chapter]]] = {}
        self._mangasbrasuka_page_images_cache: dict[str, tuple[float, list[str]]] = {}
        self._mangadex_tag_ids_cache: dict[str, str] | None = None
        self._cloudscraper: cloudscraper.CloudScraper | None = None
        self._last_mangafire_chapters_provider: str | None = None
        atexit.register(self.close)

    def _mangadex_get(self, path: str, params: dict | None = None):
        response = requests.get(
            f"{MANGADEX_API_URL}{path}",
            params=params,
            timeout=self.args.timeout,
            headers={
                "Accept": "application/json",
                "User-Agent": DEFAULT_HEADERS["User-Agent"],
            },
        )
        response.raise_for_status()
        return response.json()

    def _is_mangadex_source(self, source_url: str) -> bool:
        return bool(
            re.search(r"(?:mangadex\.org/(?:title|chapter)/|mangadex://)", source_url, re.IGNORECASE)
            or re.fullmatch(UUID_PATTERN, source_url.strip())
        )

    def _mangadex_manga_id_from_source(self, source_url: str) -> str | None:
        match = re.search(rf"(?:mangadex\.org/title/|mangadex://title/)({UUID_PATTERN})", source_url, re.IGNORECASE)
        if match:
            return match.group(1)
        raw = source_url.strip()
        if re.fullmatch(UUID_PATTERN, raw):
            return raw
        return None

    def _mangadex_chapter_id_from_source(self, source_url: str) -> str | None:
        match = re.search(rf"(?:mangadex\.org/chapter/|mangadex://chapter/)({UUID_PATTERN})", source_url, re.IGNORECASE)
        if match:
            return match.group(1)
        return None

    def _mangadex_manga_url(self, manga_id: str) -> str:
        return f"https://mangadex.org/title/{manga_id}"

    def _mangadex_chapter_url(self, chapter_id: str) -> str:
        return f"https://mangadex.org/chapter/{chapter_id}"

    def _is_dragontea_source(self, source_url: str) -> bool:
        return bool(re.search(r"dragontea\.ink", source_url or "", re.IGNORECASE))

    def _dragontea_chapter_number_from_source(self, source_url: str) -> str | None:
        parsed = urlparse(source_url)
        raw = unquote(f"{parsed.path} {parsed.query}")
        match = re.search(r"(?:chapter|capitulo|cap)[-/_.\s]*(\d+(?:\.\d+)?)", raw, re.IGNORECASE)
        if match:
            return match.group(1)
        numbers = re.findall(r"\d+(?:\.\d+)?", raw)
        return numbers[-1] if numbers else None

    def _dragontea_label_from_url(self, url: str, title: str | None = None) -> str:
        if title:
            title = re.sub(r"\s*[-|]\s*Dragon\s*Tea.*$", "", title, flags=re.IGNORECASE).strip()
        if title:
            return clean_filename(title, fallback="dragontea-chapter")

        parsed = urlparse(url)
        slug = Path(unquote(parsed.path.rstrip("/") or "chapter")).name
        number = self._dragontea_chapter_number_from_source(url)
        if number:
            return clean_filename(f"dragontea-chapter-{number}", fallback="dragontea-chapter")
        return clean_filename(f"dragontea-{slug}", fallback="dragontea-chapter")

    def _fetch_dragontea_chapters(
        self,
        source_url: str,
        preferred_chapter: str | None = None,
    ) -> list[Chapter]:
        if not self._is_dragontea_source(source_url):
            raise ValueError("Informe uma URL do DragonTea.")

        number_text = self._dragontea_chapter_number_from_source(source_url) or preferred_chapter
        title = f"Capitulo {number_text}" if number_text else "Capitulo DragonTea"
        return [
            Chapter(
                url=source_url.strip(),
                number=parse_float(number_text),
                number_text=number_text,
                chapter_id=source_url.strip(),
                title=title,
            )
        ]

    def _launch_dragontea_browser(self, playwright):
        show_browser = bool(getattr(self.args, "show_browser", False))
        headless = not show_browser
        browser_name = str(getattr(self.args, "dragontea_browser", "edge") or "edge").lower()

        launchers = []
        if browser_name == "chrome":
            launchers.append(lambda: playwright.chromium.launch(channel="chrome", headless=headless))
        elif browser_name == "chromium":
            launchers.append(lambda: playwright.chromium.launch(headless=headless))
        elif browser_name == "firefox":
            launchers.append(lambda: playwright.firefox.launch(headless=headless))
        else:
            launchers.append(lambda: playwright.chromium.launch(channel="msedge", headless=headless))
            launchers.append(lambda: playwright.chromium.launch(headless=headless))

        last_error: Exception | None = None
        for launch in launchers:
            try:
                return launch()
            except Exception as exc:
                last_error = exc
        raise RuntimeError(f"Nao consegui abrir o navegador para DragonTea: {last_error}")

    def _session_from_playwright_context(self, cookies: list[dict], referer: str) -> requests.Session:
        session = requests.Session()
        session.headers.update(
            {
                **DEFAULT_HEADERS,
                "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                "Referer": referer,
            }
        )

        for cookie in cookies:
            kwargs = {"path": cookie.get("path", "/")}
            if cookie.get("domain"):
                kwargs["domain"] = cookie["domain"]
            session.cookies.set(cookie["name"], cookie["value"], **kwargs)
        return session

    def _dragontea_collect_urls(self, page) -> list[str]:
        attrs = [
            "data-src",
            "data-original",
            "data-lazy-src",
            "data-url",
            "currentSrc",
            "src",
        ]
        urls = page.evaluate(
            DRAGONTEA_COLLECT_IMAGE_URLS_JS,
            {"selector": DRAGONTEA_IMAGE_SELECTOR, "attrs": attrs},
        )
        return [url for url in urls if isinstance(url, str)]

    def _dragontea_scroll_to_collect_urls(self, page) -> list[str]:
        stable_count = 0
        last_count = -1
        last_height = -1
        current_y = 0

        for _ in range(80):
            urls = self._dragontea_collect_urls(page)
            height = int(
                page.evaluate(
                    "() => Math.max(document.body.scrollHeight, document.documentElement.scrollHeight)"
                )
                or 0
            )
            viewport = int(page.evaluate("() => window.innerHeight") or 900)
            at_bottom = current_y + viewport >= height

            if len(urls) == last_count and height == last_height and at_bottom:
                stable_count += 1
            else:
                stable_count = 0
            if stable_count >= 3:
                break

            last_count = len(urls)
            last_height = height
            current_y = min(current_y + max(300, int(viewport * 0.85)), height)
            page.evaluate("(y) => window.scrollTo(0, y)", current_y)
            page.wait_for_timeout(700)

        page.wait_for_timeout(700)
        return self._dragontea_collect_urls(page)

    def _load_dragontea_chapter(self, url: str) -> dict:
        if sync_playwright is None:
            raise RuntimeError(
                "Playwright nao esta instalado. Rode: python -m pip install -r requirements.txt"
            )

        with self.lock:
            if not self._is_dragontea_source(url):
                raise ValueError("Informe uma URL de capitulo do DragonTea.")

            try:
                with sync_playwright() as playwright:
                    browser = self._launch_dragontea_browser(playwright)
                    context = browser.new_context(
                        user_agent=DEFAULT_HEADERS["User-Agent"],
                        viewport={"width": 1280, "height": 1800},
                    )
                    page = context.new_page()
                    try:
                        timeout_ms = int(self.args.timeout) * 1000
                        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                        page.wait_for_selector(
                            DRAGONTEA_IMAGE_SELECTOR,
                            state="attached",
                            timeout=timeout_ms,
                        )
                        try:
                            page.wait_for_function(
                                "() => window.CryptoJSAesJson && typeof window.CryptoJSAesJson.decrypt === 'function'",
                                timeout=min(timeout_ms, 10000),
                            )
                        except PlaywrightTimeoutError:
                            pass

                        restore_status = page.evaluate(
                            DRAGONTEA_RESTORE_IMAGES_JS,
                            DRAGONTEA_IMAGE_SELECTOR,
                        )
                        image_urls = self._dragontea_scroll_to_collect_urls(page)
                        title = normalize_text(page.title() or "")
                        session = self._session_from_playwright_context(context.cookies(), url)
                    finally:
                        context.close()
                        browser.close()
            except PlaywrightError as exc:
                raise RuntimeError(f"Falha ao controlar o navegador no DragonTea: {exc}") from exc

            if not image_urls:
                detail = ""
                if isinstance(restore_status, dict) and restore_status.get("errors"):
                    detail = " " + "; ".join(str(item) for item in restore_status["errors"])
                raise RuntimeError(f"O DragonTea nao retornou imagens para este capitulo.{detail}")

            number_text = self._dragontea_chapter_number_from_source(url)
            label = self._dragontea_label_from_url(url, title)
            cache_dir = self.cache.new_chapter_dir(label)
            chapters = self._fetch_dragontea_chapters(url)
            previous_url, next_url = self._find_neighbors(chapters, url)
            self.state = ChapterState(
                url=url,
                label=label,
                image_urls=image_urls,
                cache_dir=cache_dir,
                session=session,
                previous_url=previous_url,
                next_url=next_url,
            )

            return {
                "ok": True,
                "provider": "dragontea",
                "url": url,
                "source_url": url,
                "chapter_id": url,
                "label": label,
                "title": title or None,
                "number": parse_float(number_text),
                "number_text": number_text,
                "language": "pt-br",
                "count": len(image_urls),
                "previous": previous_url,
                "next": next_url,
                "images": [
                    {"index": index, "src": f"/api/image/{index}?v={int(time.time())}"}
                    for index in range(1, len(image_urls) + 1)
                ],
            }

    def _toomics_lang_path(self, lang: str | None = None) -> str:
        value = normalize_lang(lang or "en")
        aliases = {
            "pt-br": "por",
            "pt-pt": "por",
            "pt": "por",
            "br": "por",
            "por": "por",
            "en-us": "en",
            "en-gb": "en",
            "es": "esp",
            "es-es": "esp",
            "es-mx": "esp",
            "it-it": "it",
            "de-de": "de",
            "fr-fr": "fr",
            "ja-jp": "ja",
            "zh-cn": "sc",
            "zh-tw": "tc",
        }
        value = aliases.get(value, value)
        value = re.sub(r"[^a-z]", "", value)
        return value or "en"

    def _toomics_lang_from_source(self, source_url: str, lang: str | None = None) -> str:
        match = re.search(r"toomics\.com/([^/]+)/webtoon/", source_url, re.IGNORECASE)
        if match:
            return self._toomics_lang_path(match.group(1))
        match = re.search(r"toomics://(?:manga|chapter)/([^/]+)/", source_url, re.IGNORECASE)
        if match:
            return self._toomics_lang_path(match.group(1))
        return self._toomics_lang_path(lang)

    def _toomics_base_url_from_source(self, source_url: str | None = None) -> str:
        match = re.search(r"https?://(?:global\.)?toomics\.com", source_url or "", re.IGNORECASE)
        if match:
            return match.group(0).rstrip("/")
        return self.toomics_base_url

    def _toomics_decode_b64(self, value: str | None) -> str:
        if not value:
            return ""
        padded = value + ("=" * (-len(value) % 4))
        return base64.b64decode(padded).decode("utf-8")

    def _toomics_headers(self, referer: str | None = None, ajax: bool = False) -> dict:
        headers = {
            **DEFAULT_HEADERS,
            "Accept": "application/json, text/html, */*;q=0.8",
            "Referer": referer or f"{self.toomics_base_url}/en/webtoon/search_v2",
        }
        if ajax:
            headers["X-Requested-With"] = "XMLHttpRequest"
        return headers

    def _is_toomics_source(self, source_url: str) -> bool:
        return bool(
            source_url.startswith("toomics://")
            or re.search(r"(?:^https?://)?(?:global\.)?toomics\.com/", source_url or "", re.IGNORECASE)
        )

    def _toomics_toon_id_from_source(self, source_url: str) -> str | None:
        for pattern in (
            r"toomics://manga/[^/]+/(\d+)",
            r"toomics://chapter/[^/]+/(\d+)/\d+/\d+",
            r"/toon/(\d+)(?:[/?#]|$)",
        ):
            match = re.search(pattern, source_url, re.IGNORECASE)
            if match:
                return match.group(1)
        raw = source_url.strip()
        return raw if raw.isdigit() else None

    def _toomics_chapter_parts(self, source_url: str) -> tuple[str, str, str, str] | None:
        match = re.search(r"toomics://chapter/([^/]+)/(\d+)/(\d+)/(\d+)", source_url, re.IGNORECASE)
        if match:
            return (
                self._toomics_lang_path(match.group(1)),
                match.group(2),
                match.group(3),
                match.group(4),
            )

        match = re.search(
            r"toomics\.com/([^/]+)/webtoon/detail/code/(\d+)/ep/(\d+(?:\.\d+)?)/toon/(\d+)",
            source_url,
            re.IGNORECASE,
        )
        if match:
            return (
                self._toomics_lang_path(match.group(1)),
                match.group(4),
                match.group(2),
                match.group(3),
            )

        match = re.search(
            r"/webtoon/detail/code/(\d+)/ep/(\d+(?:\.\d+)?)/toon/(\d+)",
            source_url,
            re.IGNORECASE,
        )
        if match:
            return ("en", match.group(3), match.group(1), match.group(2))
        return None

    def _toomics_manga_url(
        self,
        toon_id: str | int,
        lang: str | None = None,
        base_url: str | None = None,
    ) -> str:
        return f"{(base_url or self.toomics_base_url).rstrip('/')}/{self._toomics_lang_path(lang)}/webtoon/episode/toon/{toon_id}"

    def _toomics_internal_manga_url(self, toon_id: str | int, lang: str | None = None) -> str:
        return f"toomics://manga/{self._toomics_lang_path(lang)}/{toon_id}"

    def _toomics_chapter_url(
        self,
        toon_id: str | int,
        art_id: str | int,
        episode: str | int,
        lang: str | None = None,
        base_url: str | None = None,
    ) -> str:
        return (
            f"{(base_url or self.toomics_base_url).rstrip('/')}/{self._toomics_lang_path(lang)}"
            f"/webtoon/detail/code/{art_id}/ep/{episode}/toon/{toon_id}"
        )

    def _toomics_internal_chapter_url(
        self,
        toon_id: str | int,
        art_id: str | int,
        episode: str | int,
        lang: str | None = None,
    ) -> str:
        return f"toomics://chapter/{self._toomics_lang_path(lang)}/{toon_id}/{art_id}/{episode}"

    def _toomics_get_manga_html(self, toon_id: str, lang_path: str, base_url: str | None = None) -> str:
        url = self._toomics_manga_url(toon_id, lang_path, base_url)
        session = requests.Session()
        response = session.post(
            url,
            data={"page": "1", "load_contents": "Y"},
            timeout=self.args.timeout,
            headers=self._toomics_headers(url, ajax=True),
        )
        response.raise_for_status()
        return response.text

    def _toomics_get_chapter_html(self, chapter_url: str) -> str:
        response = requests.get(
            chapter_url,
            timeout=self.args.timeout,
            headers=self._toomics_headers(chapter_url),
        )
        response.raise_for_status()
        return response.text

    def _toomics_extract_metadata_from_html(self, html: str, toon_id: str, lang_path: str) -> dict:
        title = text_from_html(
            first_match(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)', html)
            or first_match(r"<title[^>]*>(.*?)</title>", html)
            or ""
        )
        title = re.sub(r"^\s*Toomics\s*-\s*", "", title, flags=re.IGNORECASE).strip()
        title = re.sub(r"\s*-\s*Toomics\s*$", "", title, flags=re.IGNORECASE).strip()
        description = text_from_html(
            first_match(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)', html)
            or first_match(r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)', html)
            or ""
        )
        poster = first_match(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', html)
        keywords = text_from_html(
            first_match(r'<meta[^>]+property=["\']keywords["\'][^>]+content=["\']([^"\']+)', html)
            or first_match(r'<meta[^>]+name=["\']keywords["\'][^>]+content=["\']([^"\']+)', html)
            or ""
        )
        genres = [
            item.strip()
            for item in keywords.split(",")
            if item.strip() and item.strip().lower() not in {title.lower(), "toomics"}
        ]
        return {
            "slug": toon_id,
            "url": self._toomics_manga_url(toon_id, lang_path),
            "title": title or f"Toomics {toon_id}",
            "alternative_title": None,
            "status": None,
            "type": "Toomics",
            "poster": poster,
            "description": description,
            "latest_chapter": None,
            "authors": [],
            "genres": genres,
            "magazines": [],
            "published": None,
            "rating": {},
        }

    def _toomics_clean_episode_title(self, raw_title: str, episode: str) -> str | None:
        title = normalize_text(raw_title)
        if not title:
            return None
        episode_pattern = re.escape(str(episode))
        title = re.sub(
            rf"^\s*(?:EP|Episode|Chapter|Capitulo)\s*{episode_pattern}\s*[-:.]?\s*",
            "",
            title,
            flags=re.IGNORECASE,
        ).strip()
        title = re.sub(r"\s*(?:VIP ONLY|ONLY|FREE)\s*$", "", title, flags=re.IGNORECASE).strip()
        return title or None

    def _toomics_parse_chapters(
        self,
        html: str,
        toon_id: str,
        lang_path: str,
        base_url: str | None = None,
    ) -> list[Chapter]:
        chapters: list[Chapter] = []
        seen: set[str] = set()
        blocks = re.findall(
            r'<li\b[^>]*class=["\'][^"\']*normal_ep[^"\']*["\'][^>]*>[\s\S]*?</li>',
            html,
            re.IGNORECASE,
        )
        if not blocks:
            blocks = re.findall(
                r'<a\b[^>]*(?:data-c=["\']\w+={0,2}["\'])[^>]*>[\s\S]*?</a>',
                html,
                re.IGNORECASE,
            )

        for block in blocks:
            match = re.search(
                r"/webtoon/detail/code/(\d+)/ep/(\d+(?:\.\d+)?)/toon/(\d+)",
                block,
                re.IGNORECASE,
            )
            if not match:
                continue
            art_id, episode, found_toon_id = match.groups()
            if str(found_toon_id) != str(toon_id) or art_id in seen:
                continue
            seen.add(art_id)

            title_html = first_match(
                r'<div[^>]+class=["\'][^"\']*(?:cell-title|title)[^"\']*["\'][^>]*>(.*?)</div>',
                block,
            )
            title = self._toomics_clean_episode_title(text_from_html(title_html or ""), episode)
            if not title:
                title = self._toomics_clean_episode_title(text_from_html(block), episode)
            if re.search(r"VIP\s*ONLY|modal-login|coin-type", block, re.IGNORECASE):
                suffix = "VIP ONLY"
                title = f"{title} ({suffix})" if title else suffix

            chapters.append(
                Chapter(
                    url=self._toomics_chapter_url(toon_id, art_id, episode, lang_path, base_url),
                    number=parse_float(episode),
                    number_text=str(episode),
                    chapter_id=f"toomics:{toon_id}:{art_id}:{episode}",
                    title=title,
                )
            )

        chapters.sort(
            key=lambda chapter: (
                chapter.number is None,
                chapter.number if chapter.number is not None else 0.0,
            )
        )
        return chapters

    def _fetch_toomics_chapters(
        self,
        source_url: str,
        lang: str | None = None,
        preferred_chapter: str | None = None,
    ) -> list[Chapter]:
        toon_id = self._toomics_toon_id_from_source(source_url)
        chapter_parts = self._toomics_chapter_parts(source_url)
        if not toon_id and chapter_parts:
            toon_id = chapter_parts[1]
        if not toon_id:
            raise ValueError("Informe uma URL/ID de manga do Toomics.")

        lang_path = self._toomics_lang_from_source(source_url, lang)
        base_url = self._toomics_base_url_from_source(source_url)
        cache_key = (base_url, lang_path, str(toon_id))
        cached = self._toomics_chapters_cache.get(cache_key)
        if cached and time.time() - cached[0] < 600:
            return cached[1]

        html = self._toomics_get_manga_html(str(toon_id), lang_path, base_url)
        chapters = self._toomics_parse_chapters(html, str(toon_id), lang_path, base_url)
        metadata = self._toomics_extract_metadata_from_html(html, str(toon_id), lang_path)
        if chapters:
            metadata["latest_chapter"] = chapters[-1].number_text
            self._toomics_chapters_cache[cache_key] = (time.time(), chapters, metadata)
            return chapters

        if chapter_parts:
            part_lang, part_toon_id, art_id, episode = chapter_parts
            chapter = Chapter(
                url=self._toomics_chapter_url(part_toon_id, art_id, episode, part_lang, base_url),
                number=parse_float(episode),
                number_text=str(episode),
                chapter_id=f"toomics:{part_toon_id}:{art_id}:{episode}",
                title=f"EP {episode}",
            )
            return [chapter]
        raise RuntimeError("Nao encontrei a lista de episodios do Toomics.")

    def _toomics_cached_metadata(self, source_url: str, lang: str | None = None) -> tuple[str, str, dict]:
        toon_id = self._toomics_toon_id_from_source(source_url)
        chapter_parts = self._toomics_chapter_parts(source_url)
        if not toon_id and chapter_parts:
            toon_id = chapter_parts[1]
        if not toon_id:
            raise ValueError("Informe uma URL/ID de manga do Toomics.")

        lang_path = self._toomics_lang_from_source(source_url, lang)
        base_url = self._toomics_base_url_from_source(source_url)
        cache_key = (base_url, lang_path, str(toon_id))
        cached = self._toomics_chapters_cache.get(cache_key)
        if not cached or time.time() - cached[0] >= 600:
            self._fetch_toomics_chapters(source_url, lang)
            cached = self._toomics_chapters_cache.get(cache_key)
        if cached:
            return str(toon_id), lang_path, dict(cached[2])

        html = self._toomics_get_manga_html(str(toon_id), lang_path, base_url)
        return str(toon_id), lang_path, self._toomics_extract_metadata_from_html(html, str(toon_id), lang_path)

    def search_toomics(self, keyword: str, limit: int = 12, lang: str = "en") -> dict:
        keyword = keyword.strip()
        if not keyword:
            raise ValueError("Digite o nome do manga para buscar.")

        lang_path = self._toomics_lang_path(lang)
        search_url = f"{self.toomics_base_url}/{lang_path}/webtoon/get_search_data_v2"
        referer = f"{self.toomics_base_url}/{lang_path}/webtoon/search_v2"
        response = requests.get(
            search_url,
            params={"keyword": keyword, "page": 1},
            timeout=self.args.timeout,
            headers=self._toomics_headers(referer, ajax=True),
        )
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, str):
            payload = json.loads(payload)
        if not isinstance(payload, dict) or not payload.get("sEsQuery"):
            raise RuntimeError("O Toomics nao retornou dados de busca validos.")

        endpoint = self._toomics_decode_b64(payload.get("sEsEndpoint"))
        index = self._toomics_decode_b64(payload.get("sEsIndex"))
        credentials = self._toomics_decode_b64(payload.get("sEsCredentials"))
        query = json.loads(payload["sEsQuery"])
        auth = base64.b64encode(credentials.encode("utf-8")).decode("ascii")
        es_response = requests.post(
            f"{endpoint.rstrip('/')}/{index.lstrip('/')}",
            json=query,
            timeout=self.args.timeout,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": f"Basic {auth}",
                "User-Agent": DEFAULT_HEADERS["User-Agent"],
                "Referer": referer,
            },
        )
        es_response.raise_for_status()
        es_payload = es_response.json()

        results: list[dict] = []
        seen: set[str] = set()
        hits = ((es_payload.get("hits") or {}).get("hits") or []) if isinstance(es_payload, dict) else []
        for hit in hits:
            source = (hit or {}).get("_source") or {}
            toon_id = source.get("toon_idx") or source.get("toon_id") or source.get("id")
            title = self._first_text(source, "title", "name")
            if not toon_id or not title:
                continue
            toon_id = str(toon_id)
            if toon_id in seen:
                continue
            seen.add(toon_id)

            images = source.get("image") if isinstance(source.get("image"), dict) else {}
            poster = (
                images.get("general_thumbnail")
                or images.get("adult_thumbnail")
                or images.get("thumbnail")
                or images.get("main_thumbnail")
            )
            author = source.get("author") if isinstance(source.get("author"), dict) else {}
            authors = [
                value
                for value in (author.get("writer"), author.get("painter"))
                if isinstance(value, str) and value.strip()
            ]
            genres = source.get("genre") if isinstance(source.get("genre"), list) else []
            results.append(
                {
                    "title": title,
                    "url": self._toomics_manga_url(toon_id, lang_path),
                    "id": toon_id,
                    "poster": poster,
                    "description": text_from_html(str(source.get("summary") or "")),
                    "authors": authors,
                    "genres": [str(item) for item in genres if str(item).strip()],
                    "adult": source.get("adult_yn") == "Y",
                }
            )

        results = self._rank_search_results(keyword, results, limit)
        return {
            "ok": True,
            "provider": "toomics",
            "api_url": self.toomics_base_url,
            "keyword": keyword,
            "count": len(results),
            "results": results,
        }

    def _toomics_image_urls_from_html(self, html: str, base_url: str | None = None) -> list[str]:
        urls: list[str] = []
        seen: set[str] = set()
        for tag in re.findall(r"<img\b[^>]*>", html, re.IGNORECASE | re.DOTALL):
            if not re.search(r'id=["\']set_image_|class=["\'][^"\']*(?:viewer|lazy|last_image)', tag, re.IGNORECASE):
                continue
            attrs = {
                key.lower(): unescape(value)
                for key, _quote, value in re.findall(
                    r'([a-zA-Z_:][-.\w:]*)\s*=\s*(["\'])(.*?)\2',
                    tag,
                    re.DOTALL,
                )
            }
            raw_url = attrs.get("data-src") or attrs.get("data-original") or attrs.get("src")
            if not raw_url or raw_url.startswith("data:"):
                continue
            image_url = urljoin((base_url or self.toomics_base_url).rstrip("/") + "/", raw_url)
            if image_url not in seen:
                seen.add(image_url)
                urls.append(image_url)
        return urls

    def _toomics_image_chunks(self, image_urls: list[str]) -> list[list[str]]:
        chunk_size = max(1, TOOMICS_COMPOSITE_IMAGES_PER_CHUNK)
        return [
            image_urls[index : index + chunk_size]
            for index in range(0, len(image_urls), chunk_size)
        ]

    def _toomics_estimated_chunk_aspect(self, chunks: list[list[str]]) -> float:
        if not chunks:
            return 0.97
        return max(1.0, min(18.0, len(chunks[0]) * 0.92))

    def _toomics_chapter_label(self, url: str, title: str | None = None) -> str:
        parts = self._toomics_chapter_parts(url)
        if parts:
            _, toon_id, art_id, episode = parts
            return clean_filename(f"toomics-{toon_id}-ep-{episode}-{art_id}", fallback="toomics-chapter")
        if title:
            return clean_filename(title, fallback="toomics-chapter")
        return clean_filename(f"toomics-{int(time.time())}", fallback="toomics-chapter")

    def _load_toomics_chapter(self, url: str) -> dict:
        with self.lock:
            parts = self._toomics_chapter_parts(url)
            if not parts:
                chapters = self._fetch_toomics_chapters(url)
                selected = self._select_chapter(chapters, url)
                if not selected:
                    raise RuntimeError("Nenhum episodio do Toomics foi selecionado automaticamente.")
                url = selected.url
                parts = self._toomics_chapter_parts(url)
            if not parts:
                raise ValueError("Informe uma URL de episodio do Toomics.")

            lang_path, toon_id, art_id, episode = parts
            base_url = self._toomics_base_url_from_source(url)
            chapter_url = self._toomics_chapter_url(toon_id, art_id, episode, lang_path, base_url)
            html = self._toomics_get_chapter_html(chapter_url)
            image_urls = self._toomics_image_urls_from_html(html, base_url)
            if not image_urls:
                if re.search(r"modal-login|VIP\s*ONLY|payment_guide|use_coin", html, re.IGNORECASE):
                    raise RuntimeError(
                        "Este episodio do Toomics parece exigir login, VIP ou moedas; "
                        "o leitor so carrega episodios que a pagina publica entrega."
                    )
                raise RuntimeError("O Toomics nao retornou imagens para este episodio.")

            title = text_from_html(
                first_match(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)', html)
                or first_match(r"<title[^>]*>(.*?)</title>", html)
                or ""
            )
            title = re.sub(r"\s*-\s*Toomics\s*$", "", title, flags=re.IGNORECASE).strip() or None

            chapters: list[Chapter] = []
            previous_url: str | None = None
            next_url: str | None = None
            try:
                chapters = self._fetch_toomics_chapters(
                    self._toomics_manga_url(toon_id, lang_path, base_url),
                    lang_path,
                )
                previous_url, next_url = self._find_neighbors(chapters, chapter_url)
            except Exception:
                previous_url, next_url = None, None

            session = requests.Session()
            session.headers.update(self._toomics_headers(chapter_url))
            label = self._toomics_chapter_label(chapter_url, title)
            cache_dir = self.cache.new_chapter_dir(label)
            image_chunks = self._toomics_image_chunks(image_urls)
            composite_urls = [
                f"toomics-composite://{index}"
                for index in range(1, len(image_chunks) + 1)
            ]
            self.state = ChapterState(
                url=chapter_url,
                label=label,
                image_urls=composite_urls,
                cache_dir=cache_dir,
                session=session,
                previous_url=previous_url,
                next_url=next_url,
                source_image_chunks=image_chunks,
            )
            page_count = len(image_chunks)

            return {
                "ok": True,
                "provider": "toomics",
                "api_url": self.toomics_base_url,
                "url": chapter_url,
                "source_url": chapter_url,
                "chapter_id": f"toomics:{toon_id}:{art_id}:{episode}",
                "label": label,
                "title": title,
                "number": parse_float(episode),
                "number_text": str(episode),
                "language": lang_path,
                "count": page_count,
                "source_image_count": len(image_urls),
                "continuous": True,
                "preload_all": True,
                "image_gap": 0,
                "estimated_aspect": self._toomics_estimated_chunk_aspect(image_chunks),
                "previous": previous_url,
                "next": next_url,
                "images": [
                    {"index": index, "src": f"/api/image/{index}?v={int(time.time())}"}
                    for index in range(1, page_count + 1)
                ],
            }

    def _mangalivre_headers(self, referer: str | None = None) -> dict:
        return {
            **DEFAULT_HEADERS,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": referer or f"{self.mangalivre_base_url}/",
        }

    def _mangalivre_get_html(self, url: str, referer: str | None = None) -> str:
        headers = self._mangalivre_headers(referer)
        if curl_requests is not None:
            response = curl_requests.get(
                url,
                timeout=self.args.timeout,
                headers=headers,
                impersonate="chrome",
            )
        else:
            response = requests.get(url, timeout=self.args.timeout, headers=headers)
        response.raise_for_status()
        return response.text

    def _mangalivre_get_json(self, url: str, referer: str | None = None):
        headers = {
            **self._mangalivre_headers(referer),
            "Accept": "application/json,text/plain,*/*",
        }
        if curl_requests is not None:
            response = curl_requests.get(
                url,
                timeout=self.args.timeout,
                headers=headers,
                impersonate="chrome",
            )
        else:
            response = requests.get(url, timeout=self.args.timeout, headers=headers)
        response.raise_for_status()
        return response.json()

    def _is_mangalivre_source(self, source_url: str) -> bool:
        return bool(
            source_url.startswith("mangalivre://")
            or re.search(r"(?:^https?://)?(?:www\.)?mangalivre\.blog/", source_url or "", re.IGNORECASE)
        )

    def _mangalivre_slugify(self, value: str) -> str:
        normalized = unicodedata.normalize("NFKD", value or "")
        normalized = normalized.encode("ascii", "ignore").decode("ascii")
        normalized = re.sub(r"[^a-zA-Z0-9]+", "-", normalized.lower()).strip("-")
        return normalized

    def _mangalivre_chapter_slug_from_source(self, source_url: str) -> str | None:
        match = re.search(r"mangalivre://chapter/([^/?#]+)", source_url, re.IGNORECASE)
        if match:
            return unquote(match.group(1)).strip("/")
        match = re.search(r"mangalivre\.blog/capitulo/([^/?#]+)", source_url, re.IGNORECASE)
        return unquote(match.group(1)).strip("/") if match else None

    def _mangalivre_manga_slug_from_source(self, source_url: str) -> str | None:
        match = re.search(r"mangalivre://manga/([^/?#]+)", source_url, re.IGNORECASE)
        if match:
            return unquote(match.group(1)).strip("/")
        match = re.search(r"mangalivre\.blog/manga/([^/?#]+)", source_url, re.IGNORECASE)
        if match:
            return unquote(match.group(1)).strip("/")
        chapter_slug = self._mangalivre_chapter_slug_from_source(source_url)
        if chapter_slug:
            match = re.match(r"(.+?)-capitulo-", chapter_slug, re.IGNORECASE)
            if match:
                return match.group(1)
        return None

    def _mangalivre_manga_url(self, slug: str) -> str:
        return f"{self.mangalivre_base_url}/manga/{slug.strip('/')}/"

    def _mangalivre_chapter_url(self, chapter_slug: str) -> str:
        return f"{self.mangalivre_base_url}/capitulo/{chapter_slug.strip('/')}/"

    def _mangalivre_chapter_number_from_slug(self, chapter_slug: str | None) -> str | None:
        if not chapter_slug:
            return None
        match = re.search(r"(?:^|-)capitulo-(\d+)(?:-(\d+)(?=-))?", chapter_slug, re.IGNORECASE)
        if not match:
            return None
        number = match.group(1)
        decimal = match.group(2)
        return f"{number}.{decimal}" if decimal else number

    def _mangalivre_chapter_number_from_source(self, source_url: str) -> str | None:
        return self._mangalivre_chapter_number_from_slug(
            self._mangalivre_chapter_slug_from_source(source_url)
        )

    def _mangalivre_manga_title_from_chapter_title(self, title: str) -> str | None:
        title = normalize_text(text_from_html(title or ""))
        if not title:
            return None
        def clean_title(value: str) -> str:
            value = re.sub(r"\s+[\W_]+$", "", value).strip()
            return re.sub(r"\s+manga$", "", value, flags=re.IGNORECASE).strip()

        match = re.match(r"(.+?)\s*[-:|]\s*Cap.tulo\b", title, re.IGNORECASE)
        if match:
            return clean_title(match.group(1))
        match = re.match(r"(.+?)\s+Cap.tulo\b", title, re.IGNORECASE)
        return clean_title(match.group(1)) if match else None

    def search_mangalivre(self, keyword: str, limit: int = 12) -> dict:
        keyword = keyword.strip()
        if not keyword:
            raise ValueError("Digite o nome do manga para buscar.")

        per_page = min(max(limit * 8, 10), 50)
        payload = self._mangalivre_get_json(
            f"{self.mangalivre_base_url}/wp-json/wp/v2/search"
            f"?search={quote(keyword)}&subtype=chapter&per_page={per_page}",
            self.mangalivre_base_url,
        )
        results: list[dict] = []
        seen: set[str] = set()
        for item in payload if isinstance(payload, list) else []:
            if not isinstance(item, dict):
                continue
            raw_title = item.get("title") or ""
            title = self._mangalivre_manga_title_from_chapter_title(str(raw_title))
            url = str(item.get("url") or item.get("link") or "")
            if not title:
                chapter_slug = self._mangalivre_chapter_slug_from_source(url)
                if chapter_slug:
                    manga_slug = self._mangalivre_manga_slug_from_source(url)
                    title = normalize_text((manga_slug or "").replace("-", " ")).title()
            if not title:
                continue
            slug = self._mangalivre_slugify(title)
            if not slug or slug in seen:
                continue
            seen.add(slug)
            results.append(
                {
                    "title": title,
                    "url": self._mangalivre_manga_url(slug),
                    "id": slug,
                    "source": "mangalivre",
                    "language": "pt-br",
                }
            )

        results = self._rank_search_results(keyword, results, limit)
        return {
            "ok": True,
            "provider": "mangalivre",
            "api_url": self.mangalivre_base_url,
            "keyword": keyword,
            "count": len(results),
            "results": results,
        }

    def _mangalivre_extract_metadata(self, source_url: str, html: str) -> dict:
        slug = self._mangalivre_manga_slug_from_source(source_url) or slug_from_url(source_url) or "mangalivre"
        title = text_from_html(
            first_match(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)', html)
            or first_match(r"<title[^>]*>(.*?)</title>", html)
            or slug
        )
        title = re.sub(r"\s*-\s*MangaLivre.*$", "", title, flags=re.IGNORECASE).strip()
        poster = first_match(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', html)
        description = text_from_html(
            first_match(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)', html)
            or first_match(r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)', html)
            or ""
        )
        return {
            "slug": slug,
            "url": self._mangalivre_manga_url(slug),
            "title": title or slug,
            "alternative_title": None,
            "status": None,
            "type": "MangaLivre",
            "poster": poster,
            "description": description,
            "latest_chapter": None,
            "authors": [],
            "genres": [],
            "magazines": [],
            "published": None,
            "rating": {},
        }

    def _mangalivre_clean_chapter_title(self, label: str, number_text: str | None) -> str | None:
        title = normalize_text(label or "")
        if not title:
            return None
        if number_text:
            integer, _, decimal = number_text.partition(".")
            number_pattern = re.escape(integer)
            if decimal:
                number_pattern = f"{number_pattern}(?:[.-]{re.escape(decimal)})?"
            title = re.sub(
                rf"^\s*Cap.tulo\s+{number_pattern}\s*[-:.,]?\s*",
                "",
                title,
                flags=re.IGNORECASE,
            ).strip()
        title = re.sub(r"\s+ha\s+\d+.*$", "", title, flags=re.IGNORECASE).strip()
        return title or None

    def _mangalivre_parse_chapters(self, html: str) -> list[Chapter]:
        chapters: list[Chapter] = []
        seen: set[str] = set()
        for href, body in re.findall(
            r'<a\b[^>]+href=["\']([^"\']*/capitulo/[^"\']+)["\'][^>]*>(.*?)</a>',
            html,
            re.IGNORECASE | re.DOTALL,
        ):
            url = urljoin(self.mangalivre_base_url, unescape(href))
            chapter_slug = self._mangalivre_chapter_slug_from_source(url)
            if not chapter_slug or chapter_slug in seen:
                continue
            label = text_from_html(body)
            label_ascii = unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode("ascii")
            if label and not re.search(r"\bCapitulo\b|\bCap\.?\b", label_ascii, re.IGNORECASE):
                continue
            number_text = self._mangalivre_chapter_number_from_slug(chapter_slug)
            if label_ascii:
                number_text = first_match(r"\bCapitulo\s+(\d+(?:[.,]\d+)?)", label_ascii) or number_text
            if number_text:
                number_text = number_text.replace(",", ".")
            chapters.append(
                Chapter(
                    url=self._mangalivre_chapter_url(chapter_slug),
                    number=parse_float(number_text),
                    number_text=number_text,
                    chapter_id=f"mangalivre:{chapter_slug}",
                    title=self._mangalivre_clean_chapter_title(label, number_text),
                )
            )
            seen.add(chapter_slug)

        chapters.sort(
            key=lambda chapter: (
                chapter.number is None,
                chapter.number if chapter.number is not None else 0.0,
                chapter.chapter_id or "",
            )
        )
        return chapters

    def _mangalivre_cache_key(self, source_url: str) -> str | None:
        slug = self._mangalivre_manga_slug_from_source(source_url)
        if slug:
            return slug
        chapter_slug = self._mangalivre_chapter_slug_from_source(source_url)
        if chapter_slug:
            match = re.match(r"(.+?)-capitulo-", chapter_slug, re.IGNORECASE)
            if match:
                return match.group(1)
        return None

    def _mangalivre_cache_key_from_chapters(self, chapters: list[Chapter]) -> str | None:
        prefixes: dict[str, int] = {}
        for chapter in chapters:
            chapter_slug = self._mangalivre_chapter_slug_from_source(chapter.url)
            if not chapter_slug:
                continue
            match = re.match(r"(.+?)-capitulo-", chapter_slug, re.IGNORECASE)
            if match:
                prefix = match.group(1)
                prefixes[prefix] = prefixes.get(prefix, 0) + 1
        if not prefixes:
            return None
        return max(prefixes, key=prefixes.get)

    def _fetch_mangalivre_chapters(
        self,
        source_url: str,
        preferred_chapter: str | None = None,
    ) -> list[Chapter]:
        slug = self._mangalivre_manga_slug_from_source(source_url)
        cache_key = self._mangalivre_cache_key(source_url)
        if cache_key:
            cached = self._mangalivre_chapters_cache.get(cache_key)
            if cached and time.time() - cached[0] < MANGALIVRE_CACHE_SECONDS:
                return cached[1]

        html = ""
        if slug:
            try:
                html = self._mangalivre_get_html(
                    self._mangalivre_manga_url(slug),
                    self.mangalivre_base_url,
                )
            except Exception:
                html = ""
        if not html:
            html = self._mangalivre_get_html(source_url, self.mangalivre_base_url)
        chapters = self._mangalivre_parse_chapters(html)
        if not chapters:
            raise RuntimeError("Nao encontrei capitulos no MangaLivre.")
        cache_key = cache_key or self._mangalivre_cache_key_from_chapters(chapters)
        if cache_key:
            self._mangalivre_chapters_cache[cache_key] = (time.time(), chapters)
        return chapters

    def _mangalivre_image_urls_from_html(self, html: str) -> list[str]:
        preferred: list[str] = []
        fallback: list[str] = []
        for tag in re.findall(r"<img\b[^>]*>", html, re.IGNORECASE | re.DOTALL):
            attrs = {
                key.lower(): unescape(value)
                for key, _quote, value in re.findall(
                    r'([a-zA-Z_:][-.\w:]*)\s*=\s*(["\'])(.*?)\2',
                    tag,
                    re.DOTALL,
                )
            }
            raw_url = attrs.get("data-src") or attrs.get("data-original") or attrs.get("src")
            if not raw_url or raw_url.startswith("data:") or "flagcdn.com" in raw_url:
                continue
            url = urljoin(self.mangalivre_base_url, raw_url)
            class_name = attrs.get("class", "")
            alt_text = attrs.get("alt", "")
            if "chapter-image" in class_name or re.search(r"pagina\s+\d+", alt_text, re.IGNORECASE):
                preferred.append(url)
            elif "/wp-content/uploads/" in url:
                fallback.append(url)

        urls = preferred or fallback
        unique: list[str] = []
        seen: set[str] = set()
        for url in urls:
            if url in seen:
                continue
            seen.add(url)
            unique.append(url)
        return unique

    def _mangalivre_chapter_label(self, url: str, title: str | None = None) -> str:
        chapter_slug = self._mangalivre_chapter_slug_from_source(url)
        if chapter_slug:
            number = self._mangalivre_chapter_number_from_slug(chapter_slug) or chapter_slug
            manga_slug = self._mangalivre_manga_slug_from_source(url) or "mangalivre"
            return clean_filename(f"mangalivre-{manga_slug}-chapter-{number}", fallback="mangalivre-chapter")
        if title:
            return clean_filename(title, fallback="mangalivre-chapter")
        return clean_filename(f"mangalivre-{int(time.time())}", fallback="mangalivre-chapter")

    def _load_mangalivre_chapter(self, url: str) -> dict:
        with self.lock:
            chapter_slug = self._mangalivre_chapter_slug_from_source(url)
            if not chapter_slug:
                chapters = self._fetch_mangalivre_chapters(url)
                selected = self._select_chapter(chapters, url)
                if not selected:
                    raise RuntimeError("Nenhum capitulo do MangaLivre foi selecionado automaticamente.")
                url = selected.url
                chapter_slug = self._mangalivre_chapter_slug_from_source(url)
            if not chapter_slug:
                raise ValueError("Informe uma URL de capitulo do MangaLivre.")

            chapter_url = self._mangalivre_chapter_url(chapter_slug)
            manga_slug = self._mangalivre_manga_slug_from_source(chapter_url) or "mangalivre"
            html = self._mangalivre_get_html(chapter_url, self._mangalivre_manga_url(manga_slug))
            image_urls = self._mangalivre_image_urls_from_html(html)
            if not image_urls:
                raise RuntimeError("O MangaLivre nao retornou imagens para este capitulo.")

            title = text_from_html(first_match(r"<title[^>]*>(.*?)</title>", html) or "")
            title = re.sub(r"\s*-\s*MangaLivre.*$", "", title, flags=re.IGNORECASE).strip() or None
            previous_url: str | None = None
            next_url: str | None = None
            try:
                chapters = self._fetch_mangalivre_chapters(chapter_url)
                previous_url, next_url = self._find_neighbors(chapters, chapter_url)
            except Exception:
                previous_url, next_url = None, None

            session = requests.Session()
            session.headers.update(self._mangalivre_headers(chapter_url))
            number_text = self._mangalivre_chapter_number_from_slug(chapter_slug)
            label = self._mangalivre_chapter_label(chapter_url, title)
            cache_dir = self.cache.new_chapter_dir(label)
            self.state = ChapterState(
                url=chapter_url,
                label=label,
                image_urls=image_urls,
                cache_dir=cache_dir,
                session=session,
                previous_url=previous_url,
                next_url=next_url,
            )

            return {
                "ok": True,
                "provider": "mangalivre",
                "api_url": self.mangalivre_base_url,
                "url": chapter_url,
                "source_url": chapter_url,
                "chapter_id": f"mangalivre:{chapter_slug}",
                "label": label,
                "title": title,
                "number": parse_float(number_text),
                "number_text": number_text,
                "language": "pt-br",
                "count": len(image_urls),
                "previous": previous_url,
                "next": next_url,
                "images": [
                    {"index": index, "src": f"/api/image/{index}?v={int(time.time())}"}
                    for index in range(1, len(image_urls) + 1)
                ],
            }

    def _mangakatana_headers(self, referer: str | None = None) -> dict:
        return {
            **DEFAULT_HEADERS,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": referer or f"{self.mangakatana_base_url}/",
        }

    def _mangakatana_get_html(self, url: str, referer: str | None = None) -> str:
        response = requests.get(
            url,
            timeout=self.args.timeout,
            headers=self._mangakatana_headers(referer),
        )
        response.raise_for_status()
        return response.text

    def _is_mangakatana_source(self, source_url: str) -> bool:
        return bool(
            source_url.startswith("mangakatana://")
            or re.search(r"(?:^https?://)?(?:www\.)?mangakatana\.com/", source_url or "", re.IGNORECASE)
        )

    def _mangakatana_slug_from_source(self, source_url: str) -> str | None:
        match = re.search(r"mangakatana://manga/([^/?#]+)", source_url, re.IGNORECASE)
        if match:
            return match.group(1)
        match = re.search(r"mangakatana://chapter/([^/]+)/[^/?#]+", source_url, re.IGNORECASE)
        if match:
            return match.group(1)
        match = re.search(r"mangakatana\.com/manga/([^/?#]+)", source_url, re.IGNORECASE)
        return match.group(1) if match else None

    def _mangakatana_chapter_parts(self, source_url: str) -> tuple[str, str] | None:
        match = re.search(r"mangakatana://chapter/([^/]+)/([^/?#]+)", source_url, re.IGNORECASE)
        if match:
            return match.group(1), match.group(2)
        match = re.search(r"mangakatana\.com/manga/([^/?#]+)/([^/?#]+)", source_url, re.IGNORECASE)
        if match and re.fullmatch(r"(?:c[\d.]+|fc)", match.group(2), re.IGNORECASE):
            return match.group(1), match.group(2)
        return None

    def _mangakatana_manga_url(self, slug: str) -> str:
        return f"{self.mangakatana_base_url}/manga/{slug}"

    def _mangakatana_chapter_url(self, slug: str, chapter_id: str) -> str:
        return f"{self.mangakatana_base_url}/manga/{slug}/{chapter_id}"

    def _mangakatana_chapter_number_from_id(self, chapter_id: str | None) -> str | None:
        if not chapter_id:
            return None
        if chapter_id.lower() == "fc":
            return "1"
        match = re.search(r"c(\d+(?:\.\d+)?)", chapter_id, re.IGNORECASE)
        return match.group(1) if match else None

    def search_mangakatana(self, keyword: str, limit: int = 12) -> dict:
        keyword = keyword.strip()
        if not keyword:
            raise ValueError("Digite o nome do manga para buscar.")

        html = self._mangakatana_get_html(
            f"{self.mangakatana_base_url}/?search={quote(keyword)}",
            self.mangakatana_base_url,
        )
        results: list[dict] = []
        seen: set[str] = set()
        for href, body in re.findall(
            r'<a\b[^>]+href=["\'](https?://(?:www\.)?mangakatana\.com/manga/[^"\']+\.\d+)["\'][^>]*>(.*?)</a>',
            html,
            re.IGNORECASE | re.DOTALL,
        ):
            if "/c" in urlparse(href).path.rsplit("/", 1)[-1].lower():
                continue
            slug = self._mangakatana_slug_from_source(href)
            title = text_from_html(body)
            if not slug or not title or slug in seen:
                continue
            seen.add(slug)
            results.append(
                {
                    "title": title,
                    "url": self._mangakatana_manga_url(slug),
                    "id": slug,
                    "source": "mangakatana",
                }
            )

        results = self._rank_search_results(keyword, results, limit)
        return {
            "ok": True,
            "provider": "mangakatana",
            "api_url": self.mangakatana_base_url,
            "keyword": keyword,
            "count": len(results),
            "results": results,
        }

    def _mangakatana_extract_metadata(self, source_url: str, html: str) -> dict:
        slug = self._mangakatana_slug_from_source(source_url) or slug_from_url(source_url) or "mangakatana"
        title = text_from_html(
            first_match(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)', html)
            or first_match(r"<title[^>]*>(.*?)</title>", html)
            or slug
        )
        title = re.sub(r"\s*-\s*MangaKatana\s*$", "", title, flags=re.IGNORECASE).strip()
        poster = first_match(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', html)
        description = text_from_html(
            first_match(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)', html)
            or first_match(r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)', html)
            or ""
        )
        return {
            "slug": slug,
            "url": self._mangakatana_manga_url(slug),
            "title": title or slug,
            "alternative_title": None,
            "status": None,
            "type": "MangaKatana",
            "poster": poster,
            "description": description,
            "latest_chapter": None,
            "authors": [],
            "genres": [],
            "magazines": [],
            "published": None,
            "rating": {},
        }

    def _fetch_mangakatana_chapters(
        self,
        source_url: str,
        preferred_chapter: str | None = None,
    ) -> list[Chapter]:
        slug = self._mangakatana_slug_from_source(source_url)
        chapter_parts = self._mangakatana_chapter_parts(source_url)
        if not slug and chapter_parts:
            slug = chapter_parts[0]
        if not slug:
            raise ValueError("Informe uma URL/slug do MangaKatana.")

        manga_url = self._mangakatana_manga_url(slug)
        html = self._mangakatana_get_html(manga_url, self.mangakatana_base_url)
        chapters: list[Chapter] = []
        seen: set[str] = set()
        path_prefix = f"/manga/{slug}/"
        for href, body in re.findall(
            r'<a\b[^>]+href=["\'](https?://(?:www\.)?mangakatana\.com/manga/[^"\']+)["\'][^>]*>(.*?)</a>',
            html,
            re.IGNORECASE | re.DOTALL,
        ):
            parsed = urlparse(href)
            if not parsed.path.startswith(path_prefix):
                continue
            chapter_id = parsed.path.rstrip("/").rsplit("/", 1)[-1]
            if not re.fullmatch(r"(?:c[\d.]+|fc)", chapter_id, re.IGNORECASE):
                continue
            if chapter_id in seen:
                continue
            seen.add(chapter_id)
            label_text = text_from_html(body)
            number_text = self._mangakatana_chapter_number_from_id(chapter_id)
            if label_text and chapter_id.lower() != "fc":
                number_text = first_match(r"Chapter\s+(\d+(?:\.\d+)?)", label_text) or number_text
            title = re.sub(r"^\s*Chapter\s+\d+(?:\.\d+)?\s*:?\s*", "", label_text, flags=re.IGNORECASE).strip()
            if chapter_id.lower() == "fc" and title.lower() == "first chapter":
                title = "First Chapter"
            chapters.append(
                Chapter(
                    url=self._mangakatana_chapter_url(slug, chapter_id),
                    number=parse_float(number_text),
                    number_text=number_text,
                    chapter_id=f"mangakatana:{slug}:{chapter_id}",
                    title=title or None,
                )
            )

        chapters.sort(
            key=lambda chapter: (
                chapter.number is None,
                chapter.number if chapter.number is not None else 0.0,
                chapter.chapter_id or "",
            )
        )
        return chapters

    def _mangakatana_image_urls_from_html(self, html: str) -> list[str]:
        match = re.search(r"var\s+thzq\s*=\s*(\[[\s\S]*?\])\s*;", html, re.IGNORECASE)
        urls: list[str] = []
        if match:
            urls.extend(re.findall(r"['\"](https?://[^'\"]+)['\"]", match.group(1)))
        if not urls:
            for tag in re.findall(r"<img\b[^>]*>", html, re.IGNORECASE | re.DOTALL):
                attrs = {
                    key.lower(): unescape(value)
                    for key, _quote, value in re.findall(
                        r'([a-zA-Z_:][-.\w:]*)\s*=\s*(["\'])(.*?)\2',
                        tag,
                        re.DOTALL,
                    )
                }
                raw_url = attrs.get("data-src") or attrs.get("src")
                if raw_url and raw_url not in {"#", ""} and not raw_url.startswith("data:"):
                    urls.append(urljoin(self.mangakatana_base_url, raw_url))

        unique: list[str] = []
        seen: set[str] = set()
        for url in urls:
            if url in seen:
                continue
            seen.add(url)
            unique.append(url)
        return unique

    def _mangakatana_chapter_label(self, url: str, title: str | None = None) -> str:
        parts = self._mangakatana_chapter_parts(url)
        if parts:
            slug, chapter_id = parts
            number = self._mangakatana_chapter_number_from_id(chapter_id) or chapter_id
            return clean_filename(f"mangakatana-{slug}-chapter-{number}", fallback="mangakatana-chapter")
        if title:
            return clean_filename(title, fallback="mangakatana-chapter")
        return clean_filename(f"mangakatana-{int(time.time())}", fallback="mangakatana-chapter")

    def _load_mangakatana_chapter(self, url: str) -> dict:
        with self.lock:
            parts = self._mangakatana_chapter_parts(url)
            if not parts:
                chapters = self._fetch_mangakatana_chapters(url)
                selected = self._select_chapter(chapters, url)
                if not selected:
                    raise RuntimeError("Nenhum capitulo do MangaKatana foi selecionado automaticamente.")
                url = selected.url
                parts = self._mangakatana_chapter_parts(url)
            if not parts:
                raise ValueError("Informe uma URL de capitulo do MangaKatana.")

            slug, chapter_id = parts
            chapter_url = self._mangakatana_chapter_url(slug, chapter_id)
            html = self._mangakatana_get_html(chapter_url, self._mangakatana_manga_url(slug))
            image_urls = self._mangakatana_image_urls_from_html(html)
            if not image_urls:
                raise RuntimeError("O MangaKatana nao retornou imagens para este capitulo.")

            title = text_from_html(first_match(r"<title[^>]*>(.*?)</title>", html) or "")
            title = re.sub(r"\s*-\s*[^-]+$", "", title).strip() or None
            chapters: list[Chapter] = []
            previous_url: str | None = None
            next_url: str | None = None
            try:
                chapters = self._fetch_mangakatana_chapters(self._mangakatana_manga_url(slug))
                previous_url, next_url = self._find_neighbors(chapters, chapter_url)
            except Exception:
                previous_url, next_url = None, None

            session = requests.Session()
            session.headers.update(self._mangakatana_headers(chapter_url))
            label = self._mangakatana_chapter_label(chapter_url, title)
            cache_dir = self.cache.new_chapter_dir(label)
            number_text = self._mangakatana_chapter_number_from_id(chapter_id)
            self.state = ChapterState(
                url=chapter_url,
                label=label,
                image_urls=image_urls,
                cache_dir=cache_dir,
                session=session,
                previous_url=previous_url,
                next_url=next_url,
            )

            return {
                "ok": True,
                "provider": "mangakatana",
                "api_url": self.mangakatana_base_url,
                "url": chapter_url,
                "source_url": chapter_url,
                "chapter_id": f"mangakatana:{slug}:{chapter_id}",
                "label": label,
                "title": title,
                "number": parse_float(number_text),
                "number_text": number_text,
                "language": "en",
                "count": len(image_urls),
                "previous": previous_url,
                "next": next_url,
                "images": [
                    {"index": index, "src": f"/api/image/{index}?v={int(time.time())}"}
                    for index in range(1, len(image_urls) + 1)
                ],
            }

    def _readfull_get(self, path: str, params: dict | None = None):
        url = path if path.startswith(("http://", "https://")) else f"{self.readfull_api_base_url}{path}"
        response = requests.get(
            url,
            params=params,
            timeout=self.args.timeout,
            headers={
                "Accept": "application/json",
                "User-Agent": DEFAULT_HEADERS["User-Agent"],
            },
        )
        response.raise_for_status()
        return response.json()

    def _readfull_list(self, payload) -> list:
        if isinstance(payload, list):
            return payload
        if not isinstance(payload, dict):
            return []
        for key in ("results", "data", "novels", "chapters", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
        return []

    def _readfull_paginated(self, path: str, max_pages: int = 12) -> list:
        items: list = []
        next_path: str | None = path
        pages = 0

        while next_path and pages < max_pages:
            payload = self._readfull_get(next_path)
            items.extend(self._readfull_list(payload))
            pages += 1
            next_path = payload.get("next") if isinstance(payload, dict) else None

        return items

    def _is_readfull_source(self, source_url: str) -> bool:
        return bool(
            source_url.startswith("readfull://")
            or re.search(r"/novels/\d+(?:/chapters/\d+)?/?$", source_url)
        )

    def _readfull_novel_id_from_source(self, source_url: str) -> str | None:
        match = re.search(r"readfull://novel/(\d+)", source_url)
        if match:
            return match.group(1)
        match = re.search(r"readfull://chapter/(\d+)/\d+", source_url)
        if match:
            return match.group(1)
        match = re.search(r"/novels/(\d+)(?:/|$)", source_url)
        return match.group(1) if match else None

    def _readfull_chapter_parts(self, source_url: str) -> tuple[str, str] | None:
        match = re.search(r"readfull://chapter/(\d+)/(\d+)", source_url)
        if match:
            return match.group(1), match.group(2)
        match = re.search(r"/novels/(\d+)/chapters/(\d+)/?$", source_url)
        if match:
            return match.group(1), match.group(2)
        return None

    def _readfull_novel_url(self, novel_id: str | int) -> str:
        return f"readfull://novel/{novel_id}"

    def _readfull_chapter_url(self, novel_id: str | int, chapter_no: str | int) -> str:
        return f"readfull://chapter/{novel_id}/{chapter_no}"

    # ------------------------------------------------------------------
    # MangasBrasuka (mangasbrasuka.com.br) — WordPress Madara
    # Cada "capitulo" no site = 1 pagina do manga.
    # Imagens ficam no HTML dentro de um link de tracking:
    #   <a href="https://redenovax.com/jump/...?a=<URL_REAL>&...">
    # ------------------------------------------------------------------

    MANGASBRASUKA_BASE = "https://mangasbrasuka.com.br"

    def _is_mangasbrasuka_source(self, source_url: str) -> bool:
        return bool(
            source_url.startswith("mangasbrasuka://")
            or re.search(r"(?:^https?://)?(?:www\.)?mangasbrasuka\.com\.br/", source_url or "", re.IGNORECASE)
        )

    def _mangasbrasuka_headers(self, referer: str | None = None) -> dict:
        return {
            **DEFAULT_HEADERS,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
            "Referer": referer or self.MANGASBRASUKA_BASE + "/",
        }

    def _mangasbrasuka_get_html(self, url: str, referer: str | None = None) -> str:
        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                response = requests.get(
                    url,
                    timeout=self.args.timeout,
                    headers=self._mangasbrasuka_headers(referer),
                    allow_redirects=True,
                )
                if response.status_code in {429, 500, 502, 503, 504} and attempt < 3:
                    time.sleep(0.6 * attempt)
                    continue
                response.raise_for_status()
                return response.text
            except requests.RequestException as exc:
                last_error = exc
                if attempt < 3:
                    time.sleep(0.6 * attempt)
                    continue
                raise
        raise RuntimeError(f"Falha ao carregar HTML do MangasBrasuka: {last_error}")

    def _mangasbrasuka_manga_slug_from_source(self, source_url: str) -> str | None:
        """Extrai o slug do manga da URL. Ex: /manga/tensei-shitara-slime-datta-ken/"""
        match = re.search(r"mangasbrasuka://manga/([^/?#]+)", source_url, re.IGNORECASE)
        if match:
            return match.group(1)
        match = re.search(r"mangasbrasuka\.com\.br/manga/([^/?#]+)", source_url, re.IGNORECASE)
        return match.group(1) if match else None

    def _mangasbrasuka_chapter_parts(self, source_url: str) -> tuple[str, str] | None:
        """Retorna (manga_slug, chapter_slug) se a URL for de um capitulo."""
        match = re.search(r"mangasbrasuka://chapter/([^/]+)/([^/?#]+)", source_url, re.IGNORECASE)
        if match:
            return match.group(1), match.group(2)
        match = re.search(
            r"mangasbrasuka\.com\.br/manga/([^/?#]+)/(capitulo-[\d.]+)/?",
            source_url,
            re.IGNORECASE,
        )
        return (match.group(1), match.group(2)) if match else None

    def _mangasbrasuka_manga_url(self, slug: str) -> str:
        return f"{self.MANGASBRASUKA_BASE}/manga/{slug.strip('/')}/"

    def _mangasbrasuka_chapter_url(self, manga_slug: str, chapter_slug: str) -> str:
        return f"{self.MANGASBRASUKA_BASE}/manga/{manga_slug.strip('/')}/{chapter_slug.strip('/')}/"

    def _mangasbrasuka_chapter_number(self, chapter_slug: str) -> str | None:
        match = re.search(r"(\d+(?:\.\d+)?)$", chapter_slug)
        return match.group(1) if match else None

    def _mangasbrasuka_image_from_html(self, html: str) -> str | None:
        """
        Extrai a URL real da imagem da pagina.
        O site usa: <a href="https://redenovax.com/jump/...?a=<URL_REAL>&...">
        """
        # Redirect de tracking — URL real fica no parametro 'a'
        m = re.search(
            r'href=["\']https?://redenovax\.com/jump/[^\s"\'<>]+["\']',
            html,
            re.IGNORECASE,
        )
        if m:
            href = m.group(0)[6:-1]  # remove href=" e "
            params = parse_qs(urlparse(href).query)
            real_url = params.get("a", [None])[0]
            if real_url and ("manga_" in real_url or "mangasbrasuka" in real_url.lower()):
                return real_url

        # Fallback: imagem direta do cdn.mugiverso com padrao de manga
        m2 = re.search(
            r'https?://cdn\.mugiverso\.com/mangasbrasuka/manga[_/][^\s"\'<>]+\.(?:jpg|jpeg|png|webp)',
            html,
            re.IGNORECASE,
        )
        return m2.group(0) if m2 else None

    def _mangasbrasuka_fetch_chapter_list_ajax(self, manga_url: str, manga_id: str) -> list[Chapter]:
        """Busca lista completa de capitulos via AJAX do Madara (manga_get_chapters)."""
        ajax_url = self.MANGASBRASUKA_BASE + "/wp-admin/admin-ajax.php"
        headers = {
            **self._mangasbrasuka_headers(manga_url),
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": self.MANGASBRASUKA_BASE,
        }
        try:
            response = requests.post(
                ajax_url,
                data={"action": "manga_get_chapters", "manga": manga_id},
                headers=headers,
                timeout=self.args.timeout,
            )
            response.raise_for_status()
            return self._mangasbrasuka_parse_chapters(response.text, manga_url)
        except Exception:
            return []

    def _mangasbrasuka_parse_chapters(self, html: str, manga_url: str) -> list[Chapter]:
        """Parseia a lista de capitulos de um fragmento HTML do Madara."""
        base = manga_url.rstrip("/")
        slug = self._mangasbrasuka_manga_slug_from_source(manga_url) or ""
        seen: set[str] = set()
        chapters: list[Chapter] = []
        for href in re.findall(
            r'href=["\'](' + re.escape(base) + r'/capitulo-[\d.]+/)["\']',
            html,
            re.IGNORECASE,
        ):
            if href in seen:
                continue
            seen.add(href)
            chapter_slug = href.rstrip("/").rsplit("/", 1)[-1]
            number_text = self._mangasbrasuka_chapter_number(chapter_slug)
            chapters.append(
                Chapter(
                    url=href,
                    number=parse_float(number_text),
                    number_text=number_text,
                    chapter_id=f"mangasbrasuka:{slug}:{chapter_slug}",
                    title=None,
                )
            )
        chapters.sort(key=lambda c: (c.number is None, c.number or 0.0))
        return chapters

    def _mangasbrasuka_chapter_bounds_from_html(self, html: str, manga_url: str) -> tuple[float, float] | None:
        """Descobre o intervalo completo de capitulos quando o Madara carrega a lista via JS."""
        base = manga_url.rstrip("/")
        first_num: float | None = None
        last_num: float | None = None

        for btn_id, assign in (("btn-read-last", "first"), ("btn-read-first", "last")):
            match = re.search(
                rf'href=["\']({re.escape(base)}/capitulo-[\d.]+/)["\'][^>]*\bid=["\']{btn_id}["\']',
                html,
                re.IGNORECASE,
            )
            if not match:
                match = re.search(
                    rf'\bid=["\']{btn_id}["\'][^>]*href=["\']({re.escape(base)}/capitulo-[\d.]+/)["\']',
                    html,
                    re.IGNORECASE,
                )
            if not match:
                continue
            chapter_slug = match.group(1).rstrip("/").rsplit("/", 1)[-1]
            number_text = self._mangasbrasuka_chapter_number(chapter_slug)
            number = parse_float(number_text)
            if number is None:
                continue
            if assign == "first":
                first_num = number
            else:
                last_num = number

        page_numbers: list[float] = []
        for href in re.findall(
            r'href=["\'](' + re.escape(base) + r'/capitulo-[\d.]+/)["\']',
            html,
            re.IGNORECASE,
        ):
            chapter_slug = href.rstrip("/").rsplit("/", 1)[-1]
            number = parse_float(self._mangasbrasuka_chapter_number(chapter_slug))
            if number is not None:
                page_numbers.append(number)

        if first_num is None and page_numbers:
            first_num = min(page_numbers)
        if last_num is None and page_numbers:
            last_num = max(page_numbers)
        if first_num is None or last_num is None:
            return None
        return min(first_num, last_num), max(first_num, last_num)

    def _mangasbrasuka_build_chapter_range(
        self,
        slug: str,
        low: float,
        high: float,
    ) -> list[Chapter]:
        start = int(low)
        end = int(high)
        if start > end:
            start, end = end, start
        chapters: list[Chapter] = []
        for number in range(start, end + 1):
            chapter_slug = f"capitulo-{number}"
            chapters.append(
                Chapter(
                    url=self._mangasbrasuka_chapter_url(slug, chapter_slug),
                    number=float(number),
                    number_text=str(number),
                    chapter_id=f"mangasbrasuka:{slug}:{chapter_slug}",
                    title=None,
                )
            )
        return chapters

    def _fetch_mangasbrasuka_chapters(
        self,
        source_url: str,
        preferred_chapter: str | None = None,
    ) -> list[Chapter]:
        slug = self._mangasbrasuka_manga_slug_from_source(source_url)
        if not slug:
            parts = self._mangasbrasuka_chapter_parts(source_url)
            if parts:
                slug = parts[0]
        if not slug:
            raise ValueError("Informe uma URL do MangasBrasuka.")

        manga_url = self._mangasbrasuka_manga_url(slug)
        html = self._mangasbrasuka_get_html(manga_url)

        # Tenta via AJAX (lista completa)
        manga_id_m = re.search(r'"manga_id":"(\d+)"', html)
        chapters: list[Chapter] = []
        if manga_id_m:
            chapters = self._mangasbrasuka_fetch_chapter_list_ajax(manga_url, manga_id_m.group(1))

        # Fallback: extrai do HTML estático
        if not chapters:
            chapters = self._mangasbrasuka_parse_chapters(html, manga_url)

        bounds = self._mangasbrasuka_chapter_bounds_from_html(html, manga_url)
        if bounds:
            low, high = bounds
            expected = int(high) - int(low) + 1
            if len(chapters) < expected:
                chapters = self._mangasbrasuka_build_chapter_range(slug, low, high)

        if not chapters:
            raise RuntimeError("Nao encontrei capitulos no MangasBrasuka.")
        return chapters

    def _mangasbrasuka_extract_metadata(self, source_url: str, html: str) -> dict:
        slug = self._mangasbrasuka_manga_slug_from_source(source_url) or slug_from_url(source_url) or "mangasbrasuka"
        title = text_from_html(
            first_match(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)', html)
            or first_match(r"<h1[^>]*>(.*?)</h1>", html, re.DOTALL)
            or slug
        )
        title = re.sub(r"\s*-\s*Mangas Brasuka.*$", "", title, flags=re.IGNORECASE).strip()
        poster = first_match(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', html)
        description = text_from_html(
            first_match(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)', html)
            or first_match(r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)', html)
            or ""
        )
        alt_match = re.search(
            r"Alternative\s*</h5>\s*</div>\s*<div class=\"summary-content\">\s*([^<]+)",
            html,
            re.IGNORECASE | re.DOTALL,
        )
        alternative_titles = []
        if alt_match:
            alternative_titles = [
                part.strip()
                for part in re.split(r",|/|;", alt_match.group(1))
                if part.strip()
            ]
        rating_match = re.search(r'property="ratingValue"[^>]*>\s*([\d.]+)', html)
        authors = [
            text_from_html(name)
            for name in re.findall(r'manga-author/[^"]+/"[^>]*>([^<]+)<', html, re.IGNORECASE)
            if text_from_html(name)
        ]
        genres = [
            text_from_html(name)
            for name in re.findall(r'manga-genre/[^"]+/"[^>]*>([^<]+)<', html, re.IGNORECASE)
            if text_from_html(name)
        ]
        status_match = re.search(
            r"Status\s*</h5>\s*</div>\s*<div class=\"summary-content\">\s*([^<]+)",
            html,
            re.IGNORECASE | re.DOTALL,
        )
        return {
            "slug": slug,
            "url": self._mangasbrasuka_manga_url(slug),
            "title": title or slug,
            "alternative_title": ", ".join(alternative_titles) if alternative_titles else None,
            "alternative_titles": alternative_titles,
            "status": text_from_html(status_match.group(1)) if status_match else None,
            "type": "MangasBrasuka",
            "poster": poster,
            "description": description,
            "latest_chapter": None,
            "authors": authors,
            "genres": genres,
            "magazines": [],
            "published": None,
            "rating": {"score": float(rating_match.group(1))} if rating_match else {},
        }

    def search_mangasbrasuka(self, keyword: str, limit: int = 12) -> dict:
        keyword = keyword.strip()
        if not keyword:
            raise ValueError("Digite o nome do manga para buscar.")

        response = requests.post(
            f"{self.MANGASBRASUKA_BASE}/wp-admin/admin-ajax.php",
            data={"action": "wp-manga-search-manga", "title": keyword},
            headers={
                **self._mangasbrasuka_headers(),
                "X-Requested-With": "XMLHttpRequest",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            timeout=self.args.timeout,
        )
        response.raise_for_status()
        payload = response.json() if response.text else {}
        results: list[dict] = []
        seen: set[str] = set()
        for item in payload.get("data") or []:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            url = str(item.get("url") or "").strip()
            slug = self._mangasbrasuka_manga_slug_from_source(url) or ""
            if not title or not url or slug in seen:
                continue
            seen.add(slug)
            results.append(
                {
                    "title": title,
                    "url": url,
                    "id": slug,
                    "source": "mangasbrasuka",
                    "provider": "mangasbrasuka",
                    "language": "pt-br",
                }
            )

        results = self._rank_search_results(keyword, results, limit)
        return {
            "ok": True,
            "provider": "mangasbrasuka",
            "api_url": self.MANGASBRASUKA_BASE,
            "keyword": keyword,
            "count": len(results),
            "results": results,
        }

    def _mangasbrasuka_chapter_label(self, manga_slug: str, chapter_slug: str) -> str:
        number = self._mangasbrasuka_chapter_number(chapter_slug) or chapter_slug
        return clean_filename(f"mangasbrasuka-{manga_slug}-capitulo-{number}", fallback="mangasbrasuka-chapter")

    def _mangasbrasuka_page_images_from_chapters(
        self,
        chapters: list[Chapter],
        manga_url: str,
    ) -> list[str]:
        """MangasBrasuka stores one manga page per /capitulo-N/. Collect all page images."""
        ordered = sorted(chapters, key=lambda chapter: (chapter.number is None, chapter.number or 0.0))
        if not ordered:
            return []
        cache_key = manga_url.rstrip("/") + "/"
        cached = self._mangasbrasuka_page_images_cache.get(cache_key)
        if cached and time.time() - cached[0] < MANGALIVRE_CACHE_SECONDS:
            return list(cached[1])

        def fetch_page(chapter: Chapter) -> tuple[str, str | None]:
            try:
                html = self._mangasbrasuka_get_html(chapter.url, manga_url)
                return chapter.url, self._mangasbrasuka_image_from_html(html)
            except Exception:
                return chapter.url, None

        images_by_url: dict[str, str] = {}
        max_workers = min(4, max(1, len(ordered)))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(fetch_page, chapter) for chapter in ordered]
            for future in as_completed(futures):
                chapter_url, image_url = future.result()
                if image_url:
                    images_by_url[chapter_url] = image_url

        return [
            image_url
            for chapter in ordered
            for image_url in [images_by_url.get(chapter.url)]
            if image_url
        ]

    def _load_mangasbrasuka_chapter(self, url: str) -> dict:
        with self.lock:
            parts = self._mangasbrasuka_chapter_parts(url)
            if not parts:
                chapters = self._fetch_mangasbrasuka_chapters(url)
                selected = self._select_chapter(chapters, url)
                if not selected:
                    raise RuntimeError("Nenhum capitulo do MangasBrasuka foi selecionado automaticamente.")
                url = selected.url
                parts = self._mangasbrasuka_chapter_parts(url)
            if not parts:
                raise ValueError("Informe uma URL de capitulo do MangasBrasuka.")

            manga_slug, chapter_slug = parts
            chapter_url = self._mangasbrasuka_chapter_url(manga_slug, chapter_slug)
            manga_url = self._mangasbrasuka_manga_url(manga_slug)

            html = ""
            img_url: str | None = None
            try:
                html = self._mangasbrasuka_get_html(chapter_url, manga_url)
                img_url = self._mangasbrasuka_image_from_html(html)
            except Exception:
                html = ""

            title_raw = first_match(r"<title[^>]*>(.*?)</title>", html) or ""
            title = text_from_html(title_raw)
            title = re.sub(r"\s*[-–|].*$", "", title).strip() or None

            chapters: list[Chapter] = []
            previous_url: str | None = None
            next_url: str | None = None
            try:
                chapters = self._fetch_mangasbrasuka_chapters(manga_url)
                previous_url, next_url = self._find_neighbors(chapters, chapter_url)
            except Exception:
                pass

            if not img_url:
                raise RuntimeError("O MangasBrasuka nao retornou imagens para este capitulo.")
            image_urls = [img_url]

            number_text = self._mangasbrasuka_chapter_number(chapter_slug)
            label = self._mangasbrasuka_chapter_label(manga_slug, chapter_slug)

            session = requests.Session()
            session.headers.update({
                **DEFAULT_HEADERS,
                "Referer": manga_url,
            })
            cache_dir = self.cache.new_chapter_dir(label)
            self.state = ChapterState(
                url=chapter_url,
                label=label,
                image_urls=image_urls,
                cache_dir=cache_dir,
                session=session,
                previous_url=previous_url,
                next_url=next_url,
            )

            return {
                "ok": True,
                "provider": "mangasbrasuka",
                "api_url": self.MANGASBRASUKA_BASE,
                "url": chapter_url,
                "source_url": chapter_url,
                "chapter_id": f"mangasbrasuka:{manga_slug}:{chapter_slug}",
                "label": label,
                "title": title,
                "number": parse_float(number_text),
                "number_text": number_text,
                "language": "pt-br",
                "count": len(image_urls),
                "previous": previous_url,
                "next": next_url,
                "images": [
                    {"index": index, "src": f"/api/image/{index}?v={int(time.time())}"}
                    for index in range(1, len(image_urls) + 1)
                ],
            }

    def _is_pieceproject_source(self, source_url: str) -> bool:
        source_url = source_url.strip()
        return bool(
            source_url.startswith("pieceproject://")
            or re.search(r"(?:scan\.)?onepieceproject\.com\.br", source_url, re.IGNORECASE)
        )

    def _pieceproject_manga_url(self) -> str:
        return "pieceproject://one-piece"

    def _pieceproject_chapter_url(self, number: str | int) -> str:
        return f"pieceproject://chapter/{number}"

    def _pieceproject_web_chapter_url(self, number: str | int) -> str:
        return f"{DEFAULT_PIECEPROJECT_URL}?Capitulo={number}"

    def _pieceproject_chapter_number_from_source(self, source_url: str) -> str | None:
        match = re.search(r"pieceproject://chapter/(\d+)", source_url, re.IGNORECASE)
        if match:
            return match.group(1)

        parsed = urlparse(source_url)
        query = parse_qs(parsed.query)
        for key, value in query.items():
            if key.lower() == "capitulo" and value:
                number = str(value[0]).strip()
                return number if number.isdigit() else None
        return None

    def _pieceproject_get_html(self) -> str:
        response = requests.get(
            DEFAULT_PIECEPROJECT_URL,
            timeout=self.args.timeout,
            headers={
                **DEFAULT_HEADERS,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Referer": "https://www.pieceproject.xyz/",
            },
        )
        response.raise_for_status()
        response.encoding = "utf-8"
        return response.text

    def _pieceproject_clean_chapter_title(self, number: str | int, title: str | None) -> str | None:
        title = normalize_text(title or "")
        if not title:
            return None
        number_pattern = re.escape(str(number))
        title = re.sub(
            rf"^\s*Cap\S*tulo\s+{number_pattern}\s*[-.]?\s*",
            "",
            title,
            flags=re.IGNORECASE,
        ).strip()
        return title or None

    def _pieceproject_chapters_from_html(self, html: str) -> list[dict]:
        script_match = re.search(
            r"const\s+chapters\s*=\s*\{(.*?)^\s*\};",
            html,
            re.IGNORECASE | re.DOTALL | re.MULTILINE,
        )
        if not script_match:
            raise RuntimeError("Nao encontrei o objeto chapters na pagina do piecePROJECT.")

        script = script_match.group(1)
        starts = list(re.finditer(r"^\s*(\d+)\s*:\s*\{", script, re.MULTILINE))
        chapters: list[dict] = []

        for index, start in enumerate(starts):
            number = start.group(1)
            end = starts[index + 1].start() if index + 1 < len(starts) else len(script)
            body = script[start.end():end]
            title = text_from_html(first_match(r"title\s*:\s*[\"']([^\"']+)", body) or "")
            pages_match = re.search(r"pages\s*:\s*\[(.*?)\]", body, re.IGNORECASE | re.DOTALL)
            if not pages_match:
                continue
            pages = [
                normalize_text(url).strip()
                for url in re.findall(r"[\"'](https?://[^\"']+)[\"']", pages_match.group(1))
            ]
            pages = [page for page in pages if page.startswith(("http://", "https://"))]
            if not pages:
                continue
            chapters.append(
                {
                    "number": number,
                    "title": self._pieceproject_clean_chapter_title(number, title) or f"Capitulo {number}",
                    "raw_title": title,
                    "pages": pages,
                }
            )

        chapters.sort(key=lambda item: int(item["number"]), reverse=True)
        if not chapters:
            raise RuntimeError("Nao encontrei paginas de capitulos no piecePROJECT.")
        return chapters

    def _pieceproject_catalog(self, force: bool = False) -> list[dict]:
        now = time.time()
        if not force and self._pieceproject_cache and now - self._pieceproject_cache[0] < 600:
            return self._pieceproject_cache[1]

        chapters = self._pieceproject_chapters_from_html(self._pieceproject_get_html())
        self._pieceproject_cache = (now, chapters)
        return chapters

    def search_pieceproject(self, keyword: str, limit: int = 12) -> dict:
        keyword = keyword.strip()
        if not keyword:
            raise ValueError("Digite o nome do manga para buscar.")

        score = fuzzy_match_score(
            keyword,
            "One Piece",
            "OnePiece",
            "piecePROJECT",
            "scan.onepieceproject.com.br",
            "Luffy",
        )
        results: list[dict] = []
        if score >= 0.55:
            description = "Capitulos de One Piece em portugues pelo piecePROJECT."
            poster = "https://i.ibb.co/NnFxkGJ/manga1130.jpg"
            try:
                latest = self._pieceproject_catalog()[0]
                description = f"{description} Ultimo capitulo no catalogo: {latest['number']}."
            except Exception:
                pass
            results.append(
                {
                    "title": "One Piece - piecePROJECT",
                    "url": self._pieceproject_manga_url(),
                    "id": "one-piece",
                    "poster": poster,
                    "description": description,
                }
            )

        return {
            "ok": True,
            "provider": "pieceproject",
            "api_url": DEFAULT_PIECEPROJECT_URL,
            "keyword": keyword,
            "count": min(len(results), limit),
            "results": results[:limit],
        }

    def _fetch_pieceproject_chapters(
        self,
        source_url: str,
        preferred_chapter: str | None = None,
    ) -> list[Chapter]:
        chapters: list[Chapter] = []
        for item in self._pieceproject_catalog():
            number_text = str(item["number"])
            chapters.append(
                Chapter(
                    url=self._pieceproject_chapter_url(number_text),
                    number=parse_float(number_text),
                    number_text=number_text,
                    chapter_id=f"pieceproject:{number_text}",
                    title=item.get("title"),
                )
            )

        chapters.sort(
            key=lambda chapter: (
                chapter.number is None,
                chapter.number if chapter.number is not None else 0.0,
            )
        )
        return chapters

    def _noveltoon_lang_path(self, lang: str | None = None) -> str:
        value = normalize_lang(lang or "en")
        aliases = {
            "pt-br": "pt",
            "pt-pt": "pt",
            "por": "pt",
            "br": "pt",
            "en-us": "en",
            "en-gb": "en",
            "es-es": "es",
            "es-mx": "es",
            "id": "id",
            "indonesia": "id",
            "vi": "vi",
            "vn": "vi",
            "fr-fr": "fr",
            "de-de": "de",
            "it-it": "it",
        }
        value = aliases.get(value, value)
        #noveltoon ta usando o idioma no caminho da URL: en, pt, es
        return re.sub(r"[^a-z-]", "", value).split("-", 1)[0] or "en"

    def _noveltoon_get_html(self, url: str) -> str:
        response = requests.get(
            url,
            timeout=self.args.timeout,
            headers={
                **DEFAULT_HEADERS,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Referer": self.noveltoon_base_url,
            },
        )
        response.raise_for_status()
        return response.text

    def _is_noveltoon_source(self, source_url: str) -> bool:
        return bool(
            source_url.startswith("noveltoon://")
            or re.search(r"noveltoon\.mobi/[^/]+/(?:watch/)?", source_url, re.IGNORECASE)
        )

    def _noveltoon_novel_parts(self, source_url: str, lang: str | None = None) -> tuple[str, str] | None:
        match = re.search(r"noveltoon://novel/([^/]+)/?(?:$|[?#])", source_url)
        if match:
            return self._noveltoon_lang_path(lang), match.group(1)

        match = re.search(r"noveltoon://novel/([^/]+)/([^/]+)", source_url)
        if match:
            return self._noveltoon_lang_path(match.group(1)), match.group(2)

        match = re.search(r"[?&]content_id=(\d+)", source_url)
        if match:
            lang_match = re.search(r"noveltoon\.mobi/([^/]+)/", source_url, re.IGNORECASE)
            return self._noveltoon_lang_path(lang_match.group(1) if lang_match else lang), match.group(1)

        raw = source_url.strip()
        if raw.isdigit():
            return self._noveltoon_lang_path(lang), raw
        return None

    def _noveltoon_chapter_parts(self, source_url: str) -> tuple[str, str, str] | None:
        match = re.search(r"noveltoon://chapter/([^/]+)/(\d+)/(\d+)", source_url)
        if match:
            return self._noveltoon_lang_path(match.group(1)), match.group(2), match.group(3)

        match = re.search(r"noveltoon://chapter/(\d+)/(\d+)", source_url)
        if match:
            return "en", match.group(1), match.group(2)

        match = re.search(r"noveltoon\.mobi/([^/]+)/watch/(\d+)/(\d+)", source_url, re.IGNORECASE)
        if match:
            return self._noveltoon_lang_path(match.group(1)), match.group(2), match.group(3)
        return None

    def _noveltoon_novel_url(self, content_id: str | int, lang: str | None = None) -> str:
        return f"noveltoon://novel/{self._noveltoon_lang_path(lang)}/{content_id}"

    def _noveltoon_chapter_url(self, content_id: str | int, episode_id: str | int, lang: str | None = None) -> str:
        return f"noveltoon://chapter/{self._noveltoon_lang_path(lang)}/{content_id}/{episode_id}"

    def _noveltoon_web_novel_url(self, content_id: str | int, lang: str | None = None, slug: str = "novel") -> str:
        return f"{self.noveltoon_base_url}/{self._noveltoon_lang_path(lang)}/{slug}?content_id={content_id}"

    def _noveltoon_web_chapter_url(self, content_id: str | int, episode_id: str | int, lang: str | None = None) -> str:
        return f"{self.noveltoon_base_url}/{self._noveltoon_lang_path(lang)}/watch/{content_id}/{episode_id}"

    def _noveltoon_display_url(self, source_url: str, lang: str | None = None) -> str:
        chapter_parts = self._noveltoon_chapter_parts(source_url)
        if chapter_parts:
            chapter_lang, content_id, episode_id = chapter_parts
            return self._noveltoon_web_chapter_url(content_id, episode_id, chapter_lang)
        novel_parts = self._noveltoon_novel_parts(source_url, lang)
        if novel_parts:
            novel_lang, content_id = novel_parts
            if source_url.startswith("http"):
                return source_url
            return self._noveltoon_web_novel_url(content_id, novel_lang)
        return source_url

    def _noveltoon_extract_title(self, html: str, fallback: str = "NovelToon") -> str:
        for pattern in (
            r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)',
            r'<h1[^>]*>(.*?)</h1>',
            r'<title[^>]*>(.*?)</title>',
        ):
            text = text_from_html(first_match(pattern, html) or "")
            text = re.sub(r"\s+-\s+NovelToon.*$", "", text, flags=re.IGNORECASE).strip()
            if text:
                return text
        return fallback

    def _noveltoon_extract_results_from_html(self, html: str, lang: str, limit: int = 12, keyword: str | None = None) -> list[dict]:
        results: list[dict] = []
        seen: set[str] = set()
        for href, body in re.findall(r'<a\b[^>]*href=["\']([^"\']*\?content_id=\d+[^"\']*)["\'][^>]*>(.*?)</a>', html, re.IGNORECASE | re.DOTALL):
            id_match = re.search(r"[?&]content_id=(\d+)", href)
            if not id_match:
                continue
            content_id = id_match.group(1)
            if content_id in seen:
                continue
            title = text_from_html(body)
            title = re.sub(r"\s+", " ", title).strip()
            if not title or len(title) < 2:
                continue
            if keyword and keyword.lower() not in title.lower():
                continue
            seen.add(content_id)
            results.append({
                "title": title[:180],
                "url": self._noveltoon_novel_url(content_id, lang),
                "id": content_id,
            })
            if len(results) >= limit:
                break
        return results

    def search_noveltoon(self, keyword: str, limit: int = 12, lang: str = "en") -> dict:
        keyword = keyword.strip()
        if not keyword:
            raise ValueError("Digite o nome da novel para buscar.")
        lang_path = self._noveltoon_lang_path(lang)
        candidates = [
            f"{self.noveltoon_base_url}/{lang_path}/search?keyword={quote(keyword)}",
            f"{self.noveltoon_base_url}/{lang_path}/search?word={quote(keyword)}",
            f"{self.noveltoon_base_url}/{lang_path}/search?q={quote(keyword)}",
            f"{self.noveltoon_base_url}/{lang_path}",
        ]
        results: list[dict] = []
        last_error: Exception | None = None
        for url in candidates:
            try:
                html = self._noveltoon_get_html(url)
                found = self._noveltoon_extract_results_from_html(html, lang_path, limit, keyword)
                for item in found:
                    if item["id"] not in {r.get("id") for r in results}:
                        results.append(item)
                if len(results) >= limit:
                    break
            except Exception as exc:
                last_error = exc
                continue

        if not results and last_error:
            raise RuntimeError(f"Nao consegui buscar no NovelToon. Detalhe: {last_error}")

        return {
            "ok": True,
            "provider": "noveltoon",
            "api_url": self.noveltoon_base_url,
            "keyword": keyword,
            "count": len(results),
            "results": results[:limit],
        }

    def _fetch_noveltoon_chapters(self, source_url: str, lang: str | None = None, preferred_chapter: str | None = None) -> list[Chapter]:
        novel_parts = self._noveltoon_novel_parts(source_url, lang)
        chapter_parts = self._noveltoon_chapter_parts(source_url)
        if chapter_parts and not novel_parts:
            novel_parts = (chapter_parts[0], chapter_parts[1])
        if not novel_parts:
            raise ValueError("Informe uma URL/ID de novel do NovelToon.")

        lang_path, content_id = novel_parts
        html = self._noveltoon_get_html(self._noveltoon_display_url(source_url, lang_path))
        chapters: list[Chapter] = []
        seen: set[str] = set()
        pattern = rf'<a\b[^>]*href=["\']([^"\']*/watch/{re.escape(str(content_id))}/(\d+)[^"\']*)["\'][^>]*>(.*?)</a>'
        for href, episode_id, body in re.findall(pattern, html, re.IGNORECASE | re.DOTALL):
            if episode_id in seen:
                continue
            seen.add(episode_id)
            label_text = text_from_html(body)
            number_text = first_match(r"(?:EP|Episode|Capitulo|Capítulo|Chapter)?\s*(\d+(?:\.\d+)?)", label_text) or str(len(chapters) + 1)
            title = re.sub(r"^\s*\d+\s*", "", label_text).strip() or f"EP {number_text}"
            chapters.append(Chapter(
                url=self._noveltoon_chapter_url(content_id, episode_id, lang_path),
                number=parse_float(number_text),
                number_text=number_text,
                chapter_id=episode_id,
                title=title,
            ))

        chapters.sort(key=lambda chapter: (chapter.number is None, chapter.number or 0, chapter.chapter_id or ""))
        return chapters

    def _noveltoon_extract_chapter_text(self, html: str) -> str:
        candidates: list[str] = []
        for pattern in (
            r'<(?:article|main)\b[^>]*>(.*?)</(?:article|main)>',
            r'<div\b[^>]+class=["\'][^"\']*(?:chapter|episode|read|story|content)[^"\']*["\'][^>]*>(.*?)</div>',
            r'<section\b[^>]+class=["\'][^"\']*(?:chapter|episode|read|story|content)[^"\']*["\'][^>]*>(.*?)</section>',
        ):
            candidates.extend(re.findall(pattern, html, re.IGNORECASE | re.DOTALL))

        cleaned: list[str] = []
        for fragment in candidates:
            text = text_from_html(fragment)
            if len(text) > 120:
                cleaned.append(text)
        if cleaned:
            return max(cleaned, key=len)

        body = first_match(r"<body[^>]*>(.*?)</body>", html) or html
        body = re.sub(r"<script\b.*?</script>", " ", body, flags=re.IGNORECASE | re.DOTALL)
        body = re.sub(r"<style\b.*?</style>", " ", body, flags=re.IGNORECASE | re.DOTALL)
        body = re.sub(r"<header\b.*?</header>", " ", body, flags=re.IGNORECASE | re.DOTALL)
        body = re.sub(r"<footer\b.*?</footer>", " ", body, flags=re.IGNORECASE | re.DOTALL)
        text = text_from_html(body)
        text = re.sub(r"^(?:History|Purchase Coins|Language|Home|Genres|Booklist|Contribute|Book Cover|Games)\b.*?", "", text, flags=re.IGNORECASE)
        return text.strip()

    def _load_noveltoon_chapter(self, url: str) -> dict:
        parts = self._noveltoon_chapter_parts(url)
        if not parts:
            raise ValueError("Informe uma URL de episodio/capitulo do NovelToon.")
        lang_path, content_id, episode_id = parts
        web_url = self._noveltoon_web_chapter_url(content_id, episode_id, lang_path)
        html = self._noveltoon_get_html(web_url)
        title = self._noveltoon_extract_title(html, fallback=f"EP {episode_id}")
        content = self._noveltoon_extract_chapter_text(html)
        if not content:
            raise RuntimeError("O NovelToon nao retornou texto publico para este capitulo.")

        previous_url: str | None = None
        next_url: str | None = None
        try:
            chapters = self._fetch_noveltoon_chapters(self._noveltoon_novel_url(content_id, lang_path), lang_path)
            previous_url, next_url = self._find_neighbors(chapters, url)
        except Exception:
            previous_url, next_url = None, None

        label = clean_filename(f"noveltoon-{content_id}-episode-{episode_id}", fallback="noveltoon-chapter")
        return {
            "ok": True,
            "provider": "noveltoon",
            "mode": "text",
            "api_url": self.noveltoon_base_url,
            "url": self._noveltoon_chapter_url(content_id, episode_id, lang_path),
            "source_url": web_url,
            "novel_id": content_id,
            "chapter_id": episode_id,
            "label": label,
            "title": title,
            "content": content,
            "number": parse_float(episode_id),
            "number_text": episode_id,
            "count": 1,
            "previous": previous_url,
            "next": next_url,
        }

    def get_driver(self):
        if self.driver is None:
            driver_args = SimpleNamespace(
                librewolf_path=self.args.librewolf_path,
                show_browser=self.args.show_browser,
                timeout=self.args.timeout,
            )
            self.driver = build_driver(driver_args)
        return self.driver

    def _get_cloudscraper(self) -> cloudscraper.CloudScraper:
        if self._cloudscraper is None:
            self._cloudscraper = create_cloudscraper()
        return self._cloudscraper

    def _ensure_async_loop(self) -> asyncio.AbstractEventLoop:
        if getattr(self, "_async_loop", None) is not None:
            return self._async_loop 

        loop = asyncio.new_event_loop()
        self._async_loop: asyncio.AbstractEventLoop = loop
        self._async_curl_session = None 

        def _run_loop() -> None:
            asyncio.set_event_loop(loop)
            loop.run_forever()

        t = threading.Thread(target=_run_loop, daemon=True, name="mangafire-async-loop")
        t.start()
        self._async_loop_thread = t
        return loop

    def _run_async(self, awaitable):
        loop = self._ensure_async_loop()
        future = asyncio.run_coroutine_threadsafe(awaitable, loop)
        return future.result()

    async def _get_curl_session(self) -> "curl_requests.AsyncSession":
        if getattr(self, "_async_curl_session", None) is None:
            self._async_curl_session = curl_requests.AsyncSession(impersonate="chrome")
            self._async_curl_session.headers.update(DEFAULT_HEADERS)
        return self._async_curl_session 

    async def _mangafire_async_get(self, url: str, referer: str, **kwargs):
        if curl_requests is None:
            raise RuntimeError("curl_cffi nao esta instalado.")

        headers = dict(DEFAULT_HEADERS)
        headers.update({"Referer": referer, "Origin": BASE_URL})
        headers.update(kwargs.pop("headers", {}) or {})
        timeout = kwargs.pop("timeout", self.args.timeout)

        session = await self._get_curl_session()
        return await session.get(url, timeout=timeout, headers=headers, **kwargs)

    async def _mangafire_async_json(
        self, url: str, referer: str, timeout: int | float | None = None
    ) -> dict:
        response = await self._mangafire_async_get(
            url,
            referer,
            timeout=timeout or self.args.timeout,
            headers={
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "X-Requested-With": "XMLHttpRequest",
            },
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("status") != 200:
            message = payload.get("message") or payload.get("messages") or payload
            raise RuntimeError(f"Resposta invalida do MangaFire: {message}")
        return payload

    async def _mangafire_async_fetch_chapters(self, source_url: str, lang: str) -> list[Chapter]:
        slug = slug_from_url(source_url)
        if not slug:
            raise ValueError("Informe uma URL do MangaFire.")
        normalized_lang = normalize_lang(lang or "pt-br")
        api_url, referer = chapter_list_api_url(slug, normalized_lang)
        payload = await self._mangafire_async_json(api_url, referer, self.args.timeout)
        chapters = extract_chapters_from_payload(payload)
        if not chapters:
            raise RuntimeError("A lista de capitulos veio vazia.")
        return chapters

    async def _mangafire_async_search_and_chapters(
        self,
        search_url: str,
        search_params: dict,
        chapters_source_url: str,
        lang: str,
    ) -> tuple[object, list[Chapter]]:
        search_task = self._mangafire_async_get(
            search_url,
            f"{BASE_URL}/",
            params=search_params,
            timeout=self.args.timeout,
        )
        chapters_task = self._mangafire_async_fetch_chapters(chapters_source_url, lang)
        return await asyncio.gather(search_task, chapters_task, return_exceptions=True)

    def _mangafire_curl_get(self, url: str, referer: str, **kwargs):
        return self._run_async(self._mangafire_async_get(url, referer, **kwargs))

    def _mangafire_curl_json(self, url: str, referer: str, timeout: int | float | None = None) -> dict:
        response = self._mangafire_curl_get(
            url,
            referer,
            timeout=timeout or self.args.timeout,
            headers={
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "X-Requested-With": "XMLHttpRequest",
            },
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("status") != 200:
            message = payload.get("message") or payload.get("messages") or payload
            raise RuntimeError(f"Resposta invalida do MangaFire: {message}")
        return payload

    def close_chapter(self) -> None:
        with self.lock:
            self.state = None
            self.cache.clear_current()

    def close(self) -> None:
        with self.lock:
            self.state = None
            self.cache.cleanup_all()
            if self.driver is not None:
                try:
                    self.driver.quit()
                except Exception:
                    pass
                self.driver = None

        loop: asyncio.AbstractEventLoop | None = getattr(self, "_async_loop", None)
        curl_session = getattr(self, "_async_curl_session", None)
        if loop is not None and curl_session is not None:
            try:
                async def _close_session():
                    await curl_session.close()
                future = asyncio.run_coroutine_threadsafe(_close_session(), loop)
                future.result(timeout=3)
            except Exception:
                pass
            self._async_curl_session = None
        if loop is not None:
            try:
                loop.call_soon_threadsafe(loop.stop)
            except Exception:
                pass
            self._async_loop = None

    def external_api_available(self) -> bool:
        if not self.use_api:
            return False
        try:
            response = requests.get(
                self.api_base_url.removesuffix("/api") or self.api_base_url,
                timeout=min(3, self.args.timeout),
            )
            return response.status_code < 500
        except Exception:
            return False

    def _search_timeout(self) -> int:
        try:
            configured = int(self.args.timeout)
        except (TypeError, ValueError):
            configured = SEARCH_TIMEOUT_SECONDS
        return max(2, min(SEARCH_TIMEOUT_SECONDS, configured))

    def _remaining_search_timeout(self, deadline: float) -> int:
        remaining = int(deadline - time.time())
        return max(1, min(self._search_timeout(), remaining))

    def _api_get(self, path: str, params: dict | None = None, timeout: int | None = None):
        if not self.use_api:
            raise RuntimeError("API externa do MangaFire desativada.")

        url = f"{self.api_base_url}{path}"
        is_local = "localhost" in url or "127.0.0.1" in url
        req_timeout = (1.5, 3.0) if is_local else (timeout or self.args.timeout)
        response = requests.get(
            url,
            params=params,
            timeout=req_timeout,
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()
        return response.json()

    def _api_error_message(self, exc: Exception) -> str:
        return f"API externa do MangaFire indisponivel em {self.api_base_url}: {exc}"

    def _api_list(self, payload) -> list:
        if isinstance(payload, list):
            return payload
        if not isinstance(payload, dict):
            return []
        for key in ("results", "data", "manga", "mangas", "items", "chapters", "images"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
        return []

    def _search_manga_via_api(self, keyword: str, limit: int = 12, timeout: int | None = None) -> dict:
        scan_limit = max(limit * 4, 20)
        payload = self._api_get(
            f"/search/{quote(keyword, safe='')}",
            {"page": 1},
            timeout=timeout,
        )
        results: list[dict] = []
        seen: set[str] = set()

        for item in self._api_list(payload):
            if not isinstance(item, dict):
                continue
            title = self._first_text(item, "title", "name", "mangaTitle")
            url = self._first_text(item, "url", "link", "href")
            manga_id = self._first_text(item, "id", "mangaId", "slug")

            if not url and manga_id:
                url = manga_page_url(manga_id)
            if url:
                url = urljoin(BASE_URL, url)
                manga_id = manga_id or slug_from_url(url)
            if not title or not url or url in seen:
                continue

            seen.add(url)
            results.append(
                {
                    "title": title,
                    "url": url,
                    "id": manga_id,
                    "poster": self._first_text(item, "poster", "image", "cover", "thumbnail"),
                }
            )
            if len(results) >= scan_limit:
                break

        results = self._rank_search_results(keyword, results, limit)

        return {
            "ok": True,
            "provider": "mangafire-api",
            "api_url": self.api_base_url,
            "keyword": keyword,
            "count": len(results),
            "results": results,
        }

    def search_mangadex(self, keyword: str, limit: int = 12) -> dict:
        scan_limit = min(max(limit * 4, 20), 100)
        results: list[dict] = []
        seen: set[str] = set()

        for search_term in self._search_keyword_variants(keyword):
            payload = self._mangadex_get(
                "/manga",
                {
                    "title": search_term,
                    "limit": scan_limit,
                    "includes[]": ["cover_art", "author", "artist"],
                    "contentRating[]": ["safe"],
                    "order[relevance]": "desc",
                },
            )
            found: list[dict] = []
            for item in payload.get("data", []):
                if not isinstance(item, dict):
                    continue
                manga_id = item.get("id")
                attrs = item.get("attributes") or {}
                if not manga_id:
                    continue
                cover = self._mangadex_cover_filename(item)
                cover_urls = self._mangadex_cover_urls(manga_id, cover)
                found.append(
                    {
                        "title": first_localized_text(attrs.get("title")) or manga_id,
                        "url": self._mangadex_manga_url(manga_id),
                        "id": manga_id,
                        "poster": cover_urls[0] if cover_urls else None,
                        "poster_fallbacks": cover_urls[1:],
                        "description": first_localized_text(attrs.get("description")),
                        "alternative_titles": [
                            first_localized_text(alt_title) or ""
                            for alt_title in attrs.get("altTitles", [])
                        ],
                        "content_rating": attrs.get("contentRating"),
                        "genres": [
                            first_localized_text((tag.get("attributes") or {}).get("name")) or ""
                            for tag in attrs.get("tags", [])
                        ],
                    }
            )
            self._add_unique_search_results(results, seen, found, scan_limit)
            if len(results) > 0:
                break

        results = self._rank_search_results(keyword, results, limit)

        return {
            "ok": True,
            "provider": "mangadex",
            "keyword": keyword,
            "count": len(results),
            "results": results,
        }

    def trending_mangadex(self, limit: int = 12) -> dict:
        scan_limit = min(max(limit, 4), 100)
        payload = self._mangadex_get(
            "/manga",
            {
                "limit": scan_limit,
                "includes[]": ["cover_art", "author", "artist"],
                "contentRating[]": ["safe"],
                "status[]": ["ongoing"],
                "order[followedCount]": "desc",
            },
        )
        results: list[dict] = []
        for item in payload.get("data", []):
            if not isinstance(item, dict):
                continue
            manga_id = item.get("id")
            attrs = item.get("attributes") or {}
            if not manga_id:
                continue
            cover = self._mangadex_cover_filename(item)
            cover_urls = self._mangadex_cover_urls(manga_id, cover)
            results.append(
                {
                    "title": first_localized_text(attrs.get("title")) or manga_id,
                    "url": self._mangadex_manga_url(manga_id),
                    "id": manga_id,
                    "poster": cover_urls[0] if cover_urls else None,
                    "poster_fallbacks": cover_urls[1:],
                    "description": first_localized_text(attrs.get("description")),
                    "alternative_titles": [
                        first_localized_text(alt_title) or ""
                        for alt_title in attrs.get("altTitles", [])
                    ],
                    "content_rating": attrs.get("contentRating"),
                    "genres": [
                        first_localized_text((tag.get("attributes") or {}).get("name")) or ""
                        for tag in attrs.get("tags", [])
                    ],
                }
            )

        return {
            "ok": True,
            "provider": "mangadex",
            "count": len(results),
            "results": results[:limit],
        }

    def catalog_mangadex(
        self,
        genres: dict[str, str],
        limit_per_genre: int = 8,
        lang: str = "pt-br",
    ) -> dict:
        tag_ids = self._mangadex_tag_ids()
        sections: dict[str, list[dict]] = {}
        seen: set[str] = set()
        scan_limit = min(max(limit_per_genre * 4, 24), 100)

        for section, genre_name in genres.items():
            tag_id = tag_ids.get(normalize_match_text(genre_name))
            if not tag_id:
                sections[section] = []
                continue
            params: dict = {
                "limit": scan_limit,
                "includes[]": ["cover_art", "author", "artist"],
                "contentRating[]": ["safe"],
                "includedTags[]": [tag_id],
                "order[followedCount]": "desc",
            }
            if lang:
                params["availableTranslatedLanguage[]"] = [lang]
            payload = self._mangadex_get("/manga", params)
            items: list[dict] = []
            for manga_item in payload.get("data", []):
                if not isinstance(manga_item, dict):
                    continue
                manga_id = str(manga_item.get("id") or "")
                attrs = manga_item.get("attributes") or {}
                cover = self._mangadex_cover_filename(manga_item)
                cover_urls = self._mangadex_cover_urls(manga_id, cover)
                if not manga_id or manga_id in seen or not cover_urls:
                    continue
                seen.add(manga_id)
                items.append(
                    {
                        "title": first_localized_text(attrs.get("title")) or manga_id,
                        "url": self._mangadex_manga_url(manga_id),
                        "id": manga_id,
                        "poster": cover_urls[0],
                        "poster_fallbacks": cover_urls[1:],
                        "description": first_localized_text(attrs.get("description")),
                        "alternative_titles": [
                            first_localized_text(alt_title) or ""
                            for alt_title in attrs.get("altTitles", [])
                        ],
                        "content_rating": attrs.get("contentRating"),
                        "genres": [
                            first_localized_text((tag.get("attributes") or {}).get("name")) or ""
                            for tag in attrs.get("tags", [])
                        ],
                        "provider": "mangadex",
                        "section": section,
                    }
                )
                if len(items) >= limit_per_genre:
                    break
            sections[section] = items

        return {
            "ok": True,
            "provider": "mangadex",
            "language": lang,
            "sections": sections,
            "count": sum(len(items) for items in sections.values()),
        }

    def anilist_metadata(self, title: str) -> dict:
        title = normalize_text(title)
        if not title:
            raise ValueError("Informe o titulo para buscar no AniList.")

        query = """
        query MangaInfo($search: String) {
          Media(search: $search, type: MANGA) {
            id
            siteUrl
            title { romaji english native }
            description(asHtml: false)
            averageScore
            meanScore
            popularity
            favourites
            format
            status
            chapters
            volumes
            startDate { year month day }
            endDate { year month day }
            countryOfOrigin
            genres
            coverImage { large extraLarge }
            staff(sort: [RELEVANCE, FAVOURITES_DESC], perPage: 8) {
              edges {
                role
                node {
                  name { full }
                  image { medium }
                  primaryOccupations
                }
              }
            }
            characters(sort: [ROLE, FAVOURITES_DESC], perPage: 10) {
              edges {
                role
                node {
                  name { full }
                  image { medium large }
                }
              }
            }
          }
        }
        """
        response = requests.post(
            ANILIST_GRAPHQL_URL,
            json={"query": query, "variables": {"search": title}},
            timeout=self.args.timeout,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": DEFAULT_HEADERS["User-Agent"],
            },
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("errors"):
            message = payload["errors"][0].get("message") or "AniList retornou erro."
            raise RuntimeError(message)
        media = ((payload.get("data") or {}).get("Media") or {})
        if not media:
            raise RuntimeError(f"AniList nao encontrou: {title}")

        titles = media.get("title") or {}
        cover = media.get("coverImage") or {}
        staff: list[dict] = []
        for edge in ((media.get("staff") or {}).get("edges") or []):
            node = edge.get("node") or {}
            name = (node.get("name") or {}).get("full")
            if not name:
                continue
            staff.append(
                {
                    "name": name,
                    "role": edge.get("role") or "",
                    "image": (node.get("image") or {}).get("medium"),
                    "occupations": node.get("primaryOccupations") or [],
                }
            )

        characters: list[dict] = []
        for edge in ((media.get("characters") or {}).get("edges") or []):
            node = edge.get("node") or {}
            name = (node.get("name") or {}).get("full")
            if not name:
                continue
            image = node.get("image") or {}
            characters.append(
                {
                    "name": name,
                    "role": edge.get("role") or "",
                    "image": image.get("large") or image.get("medium"),
                    "image_fallbacks": [
                        url for url in [image.get("medium")] if url and url != image.get("large")
                    ],
                }
            )

        description = text_from_html(str(media.get("description") or ""))
        authors = [
            item["name"]
            for item in staff
            if "story" in normalize_match_text(item.get("role") or "")
            or "art" in normalize_match_text(item.get("role") or "")
        ]
        if not authors:
            authors = [item["name"] for item in staff[:3]]

        return {
            "id": media.get("id"),
            "url": media.get("siteUrl"),
            "title": first_localized_text(titles, preferred=("pt-br", "en")) or titles.get("romaji") or title,
            "romaji_title": titles.get("romaji"),
            "english_title": titles.get("english"),
            "native_title": titles.get("native"),
            "description": description,
            "average_score": media.get("averageScore"),
            "mean_score": media.get("meanScore"),
            "popularity": media.get("popularity"),
            "favourites": media.get("favourites"),
            "format": media.get("format"),
            "status": media.get("status"),
            "chapters": media.get("chapters"),
            "volumes": media.get("volumes"),
            "start_date": media.get("startDate"),
            "end_date": media.get("endDate"),
            "country": media.get("countryOfOrigin"),
            "genres": media.get("genres") or [],
            "poster": cover.get("extraLarge") or cover.get("large"),
            "poster_fallbacks": [url for url in [cover.get("large")] if url and url != cover.get("extraLarge")],
            "authors": list(dict.fromkeys(authors)),
            "staff": staff,
            "characters": characters,
        }

    def search_dragontea(self, keyword: str, limit: int = 12) -> dict:
        """
        Busca mangas no dragontea.ink (WordPress + WP-Manga).

        Tenta em ordem:
          1. /?s=QUERY&post_type=wp-manga  (busca nativa do WP-Manga)
          2. /manga/?s=QUERY               (fallback WordPress padrao)
          3. /wp-json/wp/v2/posts?search=  (REST API como ultimo recurso)
        """
        keyword = keyword.strip()
        if not keyword:
            raise ValueError("Digite o nome do manga para buscar.")

        base_url = DEFAULT_DRAGONTEA_BASE_URL.rstrip("/")
        scan_limit = max(limit * 3, 20)
        results: list[dict] = []
        seen: set[str] = set()
        last_error: Exception | None = None

        session = requests.Session()
        session.headers.update(DEFAULT_HEADERS)
        session.headers.update({"Referer": base_url + "/"})

        def _extract(html: str) -> list[dict]:
            found: list[dict] = []

            for m in re.finditer(
                r'<(?:h\d|div)[^>]+class=["\'][^"\']*(?:post-title|tab-thumb|c-image-hover)[^"\']*["\'][^>]*>'
                r'.*?<a\s[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
                html, re.IGNORECASE | re.DOTALL
            ):
                url = m.group(1).strip()
                title = normalize_text(re.sub(r"<[^>]+>", "", unescape(m.group(2)))).strip()
                title = re.sub(r"\s*[-|]\s*Dragon\s*Tea.*$", "", title, flags=re.IGNORECASE).strip()
                if url and title and len(title) >= 2:
                    full = urljoin(base_url, url)
                    if full not in seen:
                        seen.add(full)
                        found.append({"title": title, "url": full})
                        if len(found) >= scan_limit:
                            return found

            if not found:
                for m in re.finditer(
                    r'<a\s[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
                    html, re.IGNORECASE | re.DOTALL
                ):
                    raw_url = m.group(1).strip()
                    title = normalize_text(re.sub(r"<[^>]+>", "", unescape(m.group(2)))).strip()
                    title = re.sub(r"\s*[-|]\s*Dragon\s*Tea.*$", "", title, flags=re.IGNORECASE).strip()
                    if not raw_url or not title or len(title) < 2:
                        continue
                    full = urljoin(base_url, raw_url) if not raw_url.startswith("http") else raw_url
                    path = urlparse(full).path.strip("/")
                    if not path:
                        continue
                    if re.search(r"^(?:page|tag|category|genre|manga-genre|author|artist|wp-content|wp-admin)", path, re.IGNORECASE):
                        continue
                    if "?" in full:
                        continue
                    if urlparse(full).netloc and base_url.split("//", 1)[-1].split("/")[0] not in urlparse(full).netloc:
                        continue
                    if full not in seen:
                        seen.add(full)
                        found.append({"title": title, "url": full})
                        if len(found) >= scan_limit:
                            break
            return found

        for search_url in [
            f"{base_url}/?s={quote(keyword)}&post_type=wp-manga",
            f"{base_url}/manga/?s={quote(keyword)}",
            f"{base_url}/?s={quote(keyword)}",
        ]:
            try:
                resp = session.get(search_url, timeout=self.args.timeout, allow_redirects=True)
                resp.raise_for_status()
                found = _extract(resp.text)
                for item in found:
                    if item["url"] not in {r["url"] for r in results}:
                        results.append(item)
                if results:
                    break
            except Exception as exc:
                last_error = exc
                continue

        if not results:
            try:
                resp = session.get(
                    f"{base_url}/wp-json/wp/v2/posts",
                    params={"search": keyword, "per_page": scan_limit, "post_type": "wp-manga"},
                    timeout=self.args.timeout,
                )
                resp.raise_for_status()
                items = resp.json()
                if isinstance(items, list):
                    for item in items:
                        raw_title = (item.get("title") or {}).get("rendered") or item.get("slug") or ""
                        title = normalize_text(re.sub(r"<[^>]+>", "", unescape(raw_title))).strip()
                        title = re.sub(r"\s*[-|]\s*Dragon\s*Tea.*$", "", title, flags=re.IGNORECASE).strip()
                        link = item.get("link") or ""
                        if title and link and link not in {r["url"] for r in results}:
                            results.append({"title": title, "url": link})
            except Exception as exc:
                last_error = exc

        if not results and last_error:
            raise RuntimeError(f"DragonTea indisponivel: {last_error}")

        results = self._rank_search_results(keyword, results, limit)

        return {
            "ok": True,
            "provider": "dragontea",
            "api_url": base_url,
            "keyword": keyword,
            "count": len(results),
            "results": results[:limit],
        }

    def search_readfull(self, keyword: str, limit: int = 12) -> dict:
        keyword = keyword.strip()
        if not keyword:
            raise ValueError("Digite o nome da novel para buscar.")

        try:
            raw_items = self._readfull_paginated("/novels/", max_pages=2)
        except Exception as exc:
            raise RuntimeError(
                f"API ReadFull indisponivel em {self.readfull_api_base_url}: {exc}"
            ) from exc

        min_score = 0.58
        results: list[dict] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            novel_id = item.get("id") or item.get("pk")
            if novel_id is None:
                continue

            title = self._first_text(item, "title", "name") or f"Novel {novel_id}"
            alt_names = self._first_text(item, "alt_names", "altNames") or ""
            source = self._first_text(item, "source") or ""
            score = fuzzy_match_score(keyword, title, alt_names, source)
            if score < min_score:
                continue

            results.append(
                {
                    "title": title,
                    "url": self._readfull_novel_url(novel_id),
                    "id": str(novel_id),
                    "poster": self._first_text(item, "image", "cover", "thumbnail"),
                    "description": self._first_text(item, "description"),
                }
            )

        results = self._rank_search_results(keyword, results, limit)

        return {
            "ok": True,
            "provider": "readfull",
            "api_url": self.readfull_api_base_url,
            "keyword": keyword,
            "count": len(results),
            "results": results,
        }

    def _mangadex_cover_filename(self, manga_item: dict) -> str | None:
        for relation in manga_item.get("relationships", []) or []:
            if relation.get("type") == "cover_art":
                attrs = relation.get("attributes") or {}
                filename = attrs.get("fileName")
                if isinstance(filename, str):
                    return filename
        return None

    def _mangadex_cover_urls(self, manga_id: str, filename: str | None) -> list[str]:
        if not manga_id or not filename:
            return []
        base = f"{MANGADEX_UPLOADS_URL}/covers/{manga_id}/{filename}"
        return [f"{base}.256.jpg", f"{base}.512.jpg", base]

    def _mangadex_tag_ids(self) -> dict[str, str]:
        if self._mangadex_tag_ids_cache is not None:
            return dict(self._mangadex_tag_ids_cache)
        payload = self._mangadex_get("/manga/tag")
        tags: dict[str, str] = {}
        for item in payload.get("data", []):
            if not isinstance(item, dict):
                continue
            tag_id = str(item.get("id") or "")
            name = first_localized_text((item.get("attributes") or {}).get("name"))
            if tag_id and name:
                tags[normalize_match_text(name)] = tag_id
        self._mangadex_tag_ids_cache = tags
        return dict(tags)

    def _first_text(self, item: dict, *keys: str) -> str | None:
        for key in keys:
            value = item.get(key)
            if value is None:
                continue
            if isinstance(value, (int, float)):
                return str(value)
            if isinstance(value, str):
                value = normalize_text(value)
                if value:
                    return value
        return None

    def _search_result_score(self, keyword: str, item: dict) -> float:
        values = [
            self._first_text(item, "title", "name", "label"),
            self._first_text(item, "alternative_title", "altTitle", "alt_names", "altNames"),
            self._first_text(item, "description", "synopsis", "summary"),
            self._first_text(item, "url", "link", "href", "source"),
        ]
        return max((fuzzy_match_score(keyword, value) for value in values if value), default=0.0)

    def _rank_search_results(self, keyword: str, results: list[dict], limit: int) -> list[dict]:
        ranked = sorted(
            enumerate(results),
            key=lambda pair: (self._search_result_score(keyword, pair[1]), -pair[0]),
            reverse=True,
        )
        return [item for _, item in ranked[:limit]]

    def _best_search_result_score(self, keyword: str, results: list[dict]) -> float:
        if not results:
            return 0.0
        return max(self._search_result_score(keyword, item) for item in results)

    def _search_keyword_variants(self, keyword: str, max_count: int = MAX_FUZZY_SEARCH_TERMS) -> list[str]:
        normalized = normalize_match_text(keyword)
        variants: list[str] = []

        def add(value: str) -> None:
            value = normalize_text(value)
            if value and value not in variants:
                variants.append(value)

        add(keyword)
        add(normalized)

        tokens = [token for token in normalized.split() if len(token) >= 3]
        if len(tokens) > 1:
            for token in sorted(tokens, key=len, reverse=True):
                add(token)

        compact = normalized.replace(" ", "")
        if len(compact) >= 5:
            for size in (6, 5, 4, 3):
                if len(compact) >= size:
                    add(compact[:size])

        return variants[:max_count]

    def _browser_search_terms(self, keyword: str) -> list[str]:
        normalized = normalize_match_text(keyword)
        tokens = [token for token in normalized.split() if len(token) >= 3]
        terms: list[str] = []

        def add(value: str) -> None:
            value = value.strip()
            if value and value not in terms:
                terms.append(value)

        add(keyword)
        if len(tokens) > 1:
            first = tokens[0]
            add(first)
            for size in (5, 4, 3):
                if len(first) >= size:
                    add(first[:size])
        else:
            compact = normalized.replace(" ", "")
            if len(compact) >= 4:
                add(compact[:4])
            if len(compact) >= 5:
                add(compact[:5])
            if len(compact) >= 3:
                add(compact[:3])

        return terms[:3]

    def _add_unique_search_results(
        self,
        results: list[dict],
        seen: set[str],
        found: list[dict],
        max_count: int,
    ) -> None:
        for item in found:
            url = str(item.get("url") or "").strip()
            title = str(item.get("title") or "").strip()
            if not url or not title or url in seen:
                continue
            seen.add(url)
            item["title"] = title
            item["url"] = url
            results.append(item)
            if len(results) >= max_count:
                break

    def search_manga(self, keyword: str, limit: int = 12) -> dict:
        keyword = keyword.strip()
        if not keyword:
            raise ValueError("Digite o nome do manga para buscar.")
        scan_limit = max(limit * 4, 20)

        if getattr(self.args, "provider", "") == "mangadex":
            return self.search_mangadex(keyword, limit)

        results: list[dict] = []
        seen: set[str] = set()
        last_error: Exception | None = None
        had_success = False
        result_provider: str | None = None
        search_terms = self._search_keyword_variants(keyword)
        try:
            configured_timeout = int(getattr(self.args, "timeout", SEARCH_TOTAL_TIMEOUT_SECONDS))
        except (TypeError, ValueError):
            configured_timeout = SEARCH_TOTAL_TIMEOUT_SECONDS
        search_deadline = time.time() + min(SEARCH_TOTAL_TIMEOUT_SECONDS, max(2, configured_timeout))

        if self.use_api:
            for search_term in search_terms:
                if time.time() >= search_deadline:
                    break
                try:
                    payload = self._search_manga_via_api(
                        search_term,
                        scan_limit,
                        self._remaining_search_timeout(search_deadline),
                    )
                    had_success = True
                    previous_count = len(results)
                    self._add_unique_search_results(
                        results,
                        seen,
                        payload.get("results") or [],
                        scan_limit,
                    )
                    if len(results) > previous_count:
                        result_provider = str(payload.get("provider") or "mangafire-api")
                except Exception as exc:
                    last_error = exc
                    continue
                if len(results) > 0:
                    break

        if not results:
            for search_term in search_terms:
                if time.time() >= search_deadline:
                    break
                try:
                    vrf = generate_vrf(search_term)
                    response = self._mangafire_curl_get(
                        f"{BASE_URL}/filter",
                        f"{BASE_URL}/",
                        params={
                            "keyword": search_term,
                            "page": 1,
                            "vrf": vrf,
                        },
                        timeout=self._remaining_search_timeout(search_deadline),
                    )
                    response.raise_for_status()
                    had_success = True
                    found = self._extract_search_results(response, scan_limit)
                    result_provider_candidate = "mangafire-curl_cffi"
                except Exception as exc:
                    last_error = exc
                    try:
                        scraper = self._get_cloudscraper()
                        vrf = generate_vrf(search_term)
                        response = scraper.get(
                            f"{BASE_URL}/filter",
                            params={
                                "keyword": search_term,
                                "page": 1,
                                "vrf": vrf,
                            },
                            timeout=self._remaining_search_timeout(search_deadline),
                            headers={"Referer": f"{BASE_URL}/"},
                        )
                        response.raise_for_status()
                        had_success = True
                        found = self._extract_search_results(response, scan_limit)
                        result_provider_candidate = "mangafire-cloudscraper"
                    except requests.HTTPError as exc:
                        last_error = exc
                        continue
                    except Exception as exc:
                        last_error = exc
                        continue
                previous_count = len(results)
                self._add_unique_search_results(results, seen, found, scan_limit)
                if len(results) > previous_count:
                    result_provider = result_provider_candidate
                if len(results) > 0:
                    break

        if len(results) == 0:
            try:
                with self.lock:
                    for search_term in self._browser_search_terms(keyword):
                        found = self._search_manga_with_driver(
                            search_term,
                            max(scan_limit, 30),
                            timeout=SEARCH_BROWSER_TIMEOUT_SECONDS,
                        )
                        previous_count = len(results)
                        self._add_unique_search_results(results, seen, found, max(scan_limit, 30))
                        if len(results) > previous_count:
                            result_provider = "mangafire-browser"
                        if len(results) > 0:
                            break
                had_success = True
            except Exception as exc:
                last_error = exc

        if not results and last_error and not had_success:
            raise RuntimeError(f"Nao consegui buscar mangas. Detalhe: {last_error}")

        return {
            "ok": True,
            "provider": result_provider or "mangafire",
            "keyword": keyword,
            "count": min(len(results), limit),
            "results": self._rank_search_results(keyword, results, limit),
        }

    def _extract_search_results(self, response: requests.Response, limit: int) -> list[dict]:
        content_type = response.headers.get("Content-Type", "")
        if "json" not in content_type.lower():
            return self._extract_search_results_from_html(response.text, limit)

        try:
            payload = response.json()
        except ValueError:
            return self._extract_search_results_from_html(response.text, limit)

        results: list[dict] = []
        self._walk_search_payload(payload, results, limit)
        return results[:limit]

    def _walk_search_payload(self, value, results: list[dict], limit: int) -> None:
        if len(results) >= limit:
            return

        if isinstance(value, str):
            if "/manga/" in value:
                for item in self._extract_search_results_from_html(value, limit - len(results)):
                    results.append(item)
            return

        if isinstance(value, list):
            for item in value:
                self._walk_search_payload(item, results, limit)
                if len(results) >= limit:
                    return
            return

        if not isinstance(value, dict):
            return

        possible_url = (
            value.get("url")
            or value.get("link")
            or value.get("href")
            or value.get("path")
            or ""
        )
        possible_title = (
            value.get("title")
            or value.get("name")
            or value.get("label")
            or value.get("text")
            or ""
        )
        if isinstance(possible_url, str) and "/manga/" in possible_url:
            url = urljoin(BASE_URL, possible_url)
            title = re.sub(r"\s+", " ", str(possible_title)).strip()
            if title:
                results.append({"title": title, "url": url})
                if len(results) >= limit:
                    return

        for item in value.values():
            self._walk_search_payload(item, results, limit)
            if len(results) >= limit:
                return

    def _extract_search_results_from_html(self, html: str, limit: int) -> list[dict]:
        parser = MangaSearchParser(limit=limit)
        parser.feed(html)
        return parser.results

    def _search_manga_with_driver(self, keyword: str, limit: int, timeout: int | None = None) -> list[dict]:
        driver = self.get_driver()
        driver_timeout = timeout or self.args.timeout
        try:
            driver.set_page_load_timeout(driver_timeout + 2)
        except Exception:
            pass

        try:
            clear_resource_timings(driver)
            try:
                current_url = driver.current_url or ""
            except Exception:
                current_url = ""
            if not current_url.startswith(BASE_URL):
                driver.get(BASE_URL)

            results: list[dict] = []
            deadline = time.time() + driver_timeout
            while time.time() < deadline:
                try:
                    search_input = driver.find_element("css selector", 'input[name="keyword"]')
                    break
                except Exception:
                    time.sleep(0.25)
            else:
                return results

            try:
                driver.execute_script(
                    """
                    document.querySelectorAll('.suggestion').forEach((node) => {
                        node.innerHTML = '';
                    });
                    """,
                )
            except Exception:
                pass

            clear_resource_timings(driver)
            try:
                driver.execute_script(
                    """
                    const input = arguments[0];
                    input.focus();
                    input.value = '';
                    input.dispatchEvent(new Event('input', { bubbles: true }));
                    input.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true, key: 'Backspace' }));
                    """,
                    search_input,
                )
            except Exception:
                search_input.clear()
            search_input.send_keys(keyword)

            while time.time() < deadline:
                try:
                    suggestion_html = driver.find_element(
                        "css selector",
                        ".suggestion",
                    ).get_attribute("innerHTML") or ""
                except Exception:
                    suggestion_html = ""

                results = self._extract_search_results_from_html(suggestion_html, limit)
                results = [
                    item for item in results
                    if self._search_result_score(keyword, item) >= 0.35
                ]
                if results:
                    break
                time.sleep(0.5)

            if not results:
                for url in reversed(resource_urls(driver)):
                    if "/ajax/manga/search" not in url:
                        continue
                    session = session_from_driver(driver, BASE_URL)
                    payload = request_json(session, url, BASE_URL, driver_timeout)
                    results = self._search_payload_to_results(payload, limit)
                    results = [
                        item for item in results
                        if self._search_result_score(keyword, item) >= 0.35
                    ]
                    if results:
                        break

            return self._rank_search_results(keyword, results, limit)
        finally:
            try:
                driver.set_page_load_timeout(self.args.timeout + 20)
            except Exception:
                pass

    def _search_payload_to_results(self, payload, limit: int) -> list[dict]:
        results: list[dict] = []
        self._walk_search_payload(payload, results, limit)
        return results[:limit]

    def _fetch_chapters_via_api(
        self,
        source_url: str,
        lang: str,
        preferred_chapter: str | None = None,
    ) -> list[Chapter]:
        slug = slug_from_url(source_url)
        if not slug:
            raise ValueError("Informe uma URL de manga ou capitulo do MangaFire.")

        normalized_lang = normalize_lang(lang or "pt-br")
        payload = self._api_get(
            f"/manga/{quote(slug, safe='')}/chapters/{quote(normalized_lang, safe='')}"
        )
        raw_chapters = self._api_list(payload)
        chapters: list[Chapter] = []

        for item in raw_chapters:
            if not isinstance(item, dict):
                continue

            number_text = self._first_text(item, "number", "number_text", "chapterNumber")
            title = self._first_text(item, "title", "name")
            chapter_id = self._first_text(item, "chapterId", "chapter_id", "id")
            url = self._first_text(item, "url", "link", "href")

            if not number_text and title:
                number_text = first_match(r"Chapter\s+([\d.]+)", title)
            if not url and number_text:
                url = chapter_url_from_number(slug, normalized_lang, number_text)
            if not url:
                continue

            url = urljoin(BASE_URL, url)
            chapter = Chapter(
                url=url,
                number=parse_float(number_text),
                number_text=number_text,
                chapter_id=chapter_id,
                title=title,
            )
            chapters.append(chapter)
            if chapter_id:
                self.api_chapter_ids_by_url[url] = chapter_id

        chapters.sort(
            key=lambda chapter: (
                chapter.number is None,
                chapter.number if chapter.number is not None else 0.0,
            )
        )
        self._last_mangafire_chapters_provider = "mangafire-api"
        return chapters

    def _fetch_mangadex_chapters(
        self,
        source_url: str,
        lang: str,
        preferred_chapter: str | None = None,
    ) -> list[Chapter]:
        manga_id = self._mangadex_manga_id_from_source(source_url)
        if not manga_id:
            chapter_id = self._mangadex_chapter_id_from_source(source_url)
            if chapter_id:
                detail = self._mangadex_get(f"/chapter/{chapter_id}", {"includes[]": ["manga"]})
                manga_id = self._mangadex_related_id(detail.get("data") or {}, "manga")
        if not manga_id:
            raise ValueError("Informe uma URL/ID de manga ou capitulo do MangaDex.")

        normalized_lang = normalize_lang(lang or "pt-br")
        _LANG_FALLBACKS: dict[str, list[str]] = {
            "pt-br": ["pt", "en"],
            "pt":    ["pt-br", "en"],
            "es-la": ["es", "en"],
            "es":    ["es-la", "en"],
            "zh":    ["zh-hk", "en"],
            "zh-hk": ["zh", "en"],
        }
        lang_candidates = [normalized_lang] + [
            fb for fb in _LANG_FALLBACKS.get(normalized_lang, ["en"])
            if fb != normalized_lang
        ]

        requested_chapters: list[Chapter] = []
        best_fallback: list[Chapter] = []

        for index, candidate_lang in enumerate(lang_candidates):
            chapters = self._fetch_mangadex_chapters_for_lang(manga_id, candidate_lang)
            if index == 0:
                requested_chapters = chapters
                if len(requested_chapters) >= MANGADEX_SPARSE_LANGUAGE_THRESHOLD:
                    return requested_chapters
                continue
            if len(chapters) > len(best_fallback):
                best_fallback = chapters

        if requested_chapters:
            should_use_fallback = (
                best_fallback
                and len(best_fallback) >= MANGADEX_SPARSE_LANGUAGE_THRESHOLD
                and len(best_fallback) >= max(len(requested_chapters) * 2, MANGADEX_SPARSE_LANGUAGE_THRESHOLD)
            )
            return best_fallback if should_use_fallback else requested_chapters

        if best_fallback:
            return best_fallback

        return []

    def _fetch_mangadex_chapters_for_lang(
        self,
        manga_id: str,
        lang: str,
    ) -> list[Chapter]:
        """Busca todos os capitulos de um manga no MangaDex para um idioma especifico."""
        chapters: list[Chapter] = []
        offset = 0
        limit = 500

        while True:
            payload = self._mangadex_get(
                f"/manga/{manga_id}/feed",
                {
                    "limit": limit,
                    "offset": offset,
                    "translatedLanguage[]": [lang],
                    "order[chapter]": "asc",
                    "order[volume]": "asc",
                },
            )
            data = payload.get("data") or []
            for item in data:
                attrs = item.get("attributes") or {}
                chapter_id = item.get("id")
                if not chapter_id:
                    continue
                number_text = attrs.get("chapter") or ""
                chapters.append(
                    Chapter(
                        url=self._mangadex_chapter_url(chapter_id),
                        number=parse_float(number_text),
                        number_text=str(number_text) if number_text else None,
                        chapter_id=chapter_id,
                        title=attrs.get("title") or None,
                    )
                )

            total = int(payload.get("total") or len(data))
            offset += len(data)
            if not data or offset >= total:
                break

        return chapters

    def _fetch_readfull_chapters(
        self,
        source_url: str,
        preferred_chapter: str | None = None,
    ) -> list[Chapter]:
        novel_id = self._readfull_novel_id_from_source(source_url)
        if not novel_id:
            raise ValueError("Informe uma URL/ID de novel do ReadFull.")

        raw_chapters = self._readfull_paginated(f"/novels/{novel_id}/chapters/", max_pages=50)
        chapters: list[Chapter] = []

        for item in raw_chapters:
            if not isinstance(item, dict):
                continue
            number_value = item.get("chapter_no") or item.get("chapter_number") or item.get("number")
            number_text = str(number_value) if number_value is not None else None
            if not number_text:
                continue
            title = self._first_text(item, "title", "name")
            chapters.append(
                Chapter(
                    url=self._readfull_chapter_url(novel_id, number_text),
                    number=parse_float(number_text),
                    number_text=number_text,
                    chapter_id=f"{novel_id}:{number_text}",
                    title=title,
                )
            )

        chapters.sort(
            key=lambda chapter: (
                chapter.number is None,
                chapter.number if chapter.number is not None else 0.0,
            )
        )
        return chapters

    def _mangadex_related_id(self, item: dict, relation_type: str) -> str | None:
        for relation in item.get("relationships", []) or []:
            if relation.get("type") == relation_type:
                relation_id = relation.get("id")
                if isinstance(relation_id, str):
                    return relation_id
        return None

    def _chapter_id_for_url(self, url: str) -> str | None:
        if url.startswith("api://chapter/"):
            return url.removeprefix("api://chapter/")

        mapped = self.api_chapter_ids_by_url.get(url)
        if mapped:
            return mapped

        slug = slug_from_url(url)
        number = chapter_number_from_url(url)
        lang = self._lang_from_chapter_url(url)
        if not slug or number is None or not lang:
            return None

        chapters = self._fetch_chapters_via_api(manga_page_url(slug), lang)
        for chapter in chapters:
            if chapter.number is not None and abs(chapter.number - number) < 0.0001:
                return chapter.chapter_id
        return None

    def _lang_from_chapter_url(self, url: str) -> str | None:
        match = re.search(r"mangafire\.to/read/[^/]+/([^/]+)/chapter-", url, re.IGNORECASE)
        return normalize_lang(match.group(1)) if match else None

    def _image_urls_from_api_payload(self, payload) -> list[str]:
        values = self._api_list(payload)
        if not values and isinstance(payload, dict):
            nested = payload.get("result")
            if isinstance(nested, dict):
                values = self._api_list(nested)

        urls: list[str] = []
        for item in values:
            if isinstance(item, str):
                urls.append(item)
            elif isinstance(item, list) and item and isinstance(item[0], str):
                urls.append(item[0])
            elif isinstance(item, dict):
                value = self._first_text(item, "url", "src", "image", "link")
                if value:
                    urls.append(value)

        return [urljoin(BASE_URL, url) for url in urls if url]

    def manga_metadata(
        self,
        source_url: str,
        lang: str = "pt-br",
        preferred_chapter: str | None = None,
        include_chapters: bool = True,
    ) -> dict:
        if self._is_toomics_source(source_url):
            chapters_payload = (
                self.list_chapters(source_url, lang, preferred_chapter)
                if include_chapters
                else {"chapters": [], "count": 0, "selected_url": None}
            )
            toon_id, lang_path, manga = self._toomics_cached_metadata(source_url, lang)
            manga["languages"] = [
                {
                    "code": lang_path,
                    "title": lang_path,
                    "chapter_count": chapters_payload.get("count"),
                }
            ]
            return {
                "ok": True,
                "provider": "toomics",
                "manga": manga,
                "language": lang_path,
                "chapter_count": chapters_payload.get("count", 0),
                "selected_chapter_url": chapters_payload.get("selected_url"),
                "chapters": chapters_payload.get("chapters", []),
            }

        if self._is_mangalivre_source(source_url):
            chapters_payload = (
                self.list_chapters(source_url, lang, preferred_chapter)
                if include_chapters
                else {"chapters": [], "count": 0, "selected_url": None}
            )
            slug = self._mangalivre_manga_slug_from_source(source_url)
            if not slug:
                raise ValueError("Informe uma URL/slug do MangaLivre.")
            manga_url = self._mangalivre_manga_url(slug)
            html = self._mangalivre_get_html(manga_url, self.mangalivre_base_url)
            manga = self._mangalivre_extract_metadata(manga_url, html)
            manga["latest_chapter"] = (
                chapters_payload.get("chapters", [{}])[0].get("number_text")
                if chapters_payload.get("chapters")
                else None
            )
            manga["languages"] = [
                {"code": "pt-br", "title": "Portugues (Brasil)", "chapter_count": chapters_payload.get("count")}
            ]
            return {
                "ok": True,
                "provider": "mangalivre",
                "manga": manga,
                "language": "pt-br",
                "chapter_count": chapters_payload.get("count", 0),
                "selected_chapter_url": chapters_payload.get("selected_url"),
                "chapters": chapters_payload.get("chapters", []),
            }

        if self._is_mangakatana_source(source_url):
            chapters_payload = (
                self.list_chapters(source_url, lang, preferred_chapter)
                if include_chapters
                else {"chapters": [], "count": 0, "selected_url": None}
            )
            slug = self._mangakatana_slug_from_source(source_url)
            if not slug:
                raise ValueError("Informe uma URL/slug do MangaKatana.")
            manga_url = self._mangakatana_manga_url(slug)
            html = self._mangakatana_get_html(manga_url, self.mangakatana_base_url)
            manga = self._mangakatana_extract_metadata(manga_url, html)
            manga["latest_chapter"] = (
                chapters_payload.get("chapters", [{}])[0].get("number_text")
                if chapters_payload.get("chapters")
                else None
            )
            manga["languages"] = [
                {"code": "en", "title": "English", "chapter_count": chapters_payload.get("count")}
            ]
            return {
                "ok": True,
                "provider": "mangakatana",
                "manga": manga,
                "language": "en",
                "chapter_count": chapters_payload.get("count", 0),
                "selected_chapter_url": chapters_payload.get("selected_url"),
                "chapters": chapters_payload.get("chapters", []),
            }

        if self._is_dragontea_source(source_url):
            chapters_payload = (
                self.list_chapters(source_url, lang, preferred_chapter)
                if include_chapters
                else {"chapters": [], "count": 0, "selected_url": None}
            )
            parsed = urlparse(source_url)
            title = self._dragontea_label_from_url(source_url).replace("-", " ").title()
            return {
                "ok": True,
                "provider": "dragontea",
                "manga": {
                    "slug": Path(unquote(parsed.path.rstrip("/") or "dragontea")).name,
                    "url": source_url,
                    "title": title,
                    "alternative_title": None,
                    "status": None,
                    "type": "Manga",
                    "poster": None,
                    "description": "Capitulo direto do DragonTea.",
                    "latest_chapter": self._dragontea_chapter_number_from_source(source_url),
                    "authors": [],
                    "genres": [],
                    "magazines": [],
                    "published": None,
                    "rating": {},
                    "languages": [{"code": "pt-br", "title": "Portuguese (Br)", "chapter_count": chapters_payload.get("count")}],
                },
                "language": "pt-br",
                "chapter_count": chapters_payload.get("count", 0),
                "selected_chapter_url": chapters_payload.get("selected_url"),
                "chapters": chapters_payload.get("chapters", []),
            }

        if self._is_mangasbrasuka_source(source_url):
            slug = self._mangasbrasuka_manga_slug_from_source(source_url)
            if not slug:
                parts = self._mangasbrasuka_chapter_parts(source_url)
                slug = parts[0] if parts else None
            if not slug:
                raise ValueError("Informe uma URL do MangasBrasuka.")
            manga_url = self._mangasbrasuka_manga_url(slug)
            html = self._mangasbrasuka_get_html(manga_url)
            manga = self._mangasbrasuka_extract_metadata(manga_url, html)
            chapters_payload = (
                self.list_chapters(manga_url, lang, preferred_chapter)
                if include_chapters
                else {"chapters": [], "count": 0, "selected_url": None}
            )
            manga["latest_chapter"] = (
                chapters_payload.get("chapters", [{}])[0].get("number_text")
                if chapters_payload.get("chapters")
                else None
            )
            manga["languages"] = [
                {"code": "pt-br", "title": "Portugues (Brasil)", "chapter_count": chapters_payload.get("count")}
            ]
            return {
                "ok": True,
                "provider": "mangasbrasuka",
                "manga": manga,
                "language": "pt-br",
                "chapter_count": chapters_payload.get("count", 0),
                "selected_chapter_url": chapters_payload.get("selected_url"),
                "chapters": chapters_payload.get("chapters", []),
            }

        if self._is_mangadex_source(source_url):
            return self._mangadex_manga_metadata(
                source_url,
                lang,
                preferred_chapter,
                include_chapters,
            )

        if self._is_pieceproject_source(source_url):
            chapters_payload = (
                self.list_chapters(source_url, lang, preferred_chapter)
                if include_chapters
                else {"chapters": [], "count": 0, "selected_url": None}
            )
            return {
                "ok": True,
                "provider": "pieceproject",
                "manga": {
                    "slug": "one-piece",
                    "url": DEFAULT_PIECEPROJECT_URL,
                    "title": "One Piece",
                    "alternative_title": None,
                    "status": None,
                    "type": "Manga",
                    "poster": "https://i.ibb.co/NnFxkGJ/manga1130.jpg",
                    "description": "Capitulos de One Piece em portugues pelo piecePROJECT.",
                    "latest_chapter": (
                        chapters_payload.get("chapters", [{}])[0].get("number_text")
                        if chapters_payload.get("chapters")
                        else None
                    ),
                    "authors": [],
                    "genres": [],
                    "magazines": [],
                    "published": None,
                    "rating": {},
                    "languages": [{"code": "pt-br", "title": "Portuguese (Br)", "chapter_count": chapters_payload.get("count")}],
                },
                "language": "pt-br",
                "chapter_count": chapters_payload.get("count", 0),
                "selected_chapter_url": chapters_payload.get("selected_url"),
                "chapters": chapters_payload.get("chapters", []),
            }

        if self._is_noveltoon_source(source_url):
            chapters_payload = self.list_chapters(source_url, lang, preferred_chapter) if include_chapters else {"chapters": [], "count": 0, "selected_url": None}
            novel_parts = self._noveltoon_novel_parts(source_url, lang) or (self._noveltoon_lang_path(lang), source_url.strip())
            return {
                "ok": True,
                "provider": "noveltoon",
                "manga": {
                    "slug": novel_parts[1],
                    "url": self._noveltoon_display_url(source_url, novel_parts[0]),
                    "title": None,
                    "type": "NovelToon",
                    "languages": [{"code": novel_parts[0], "title": novel_parts[0], "chapter_count": chapters_payload.get("count")}],
                },
                "language": novel_parts[0],
                "chapter_count": chapters_payload.get("count", 0),
                "selected_chapter_url": chapters_payload.get("selected_url"),
                "chapters": chapters_payload.get("chapters", []),
            }

        if self.use_api:
            try:
                return self._manga_metadata_via_api(
                    source_url,
                    lang,
                    preferred_chapter,
                    include_chapters,
                )
            except Exception:
                pass

        slug = slug_from_url(source_url)
        if not slug:
            raise ValueError("Informe uma URL de manga ou capitulo do MangaFire.")

        manga_url = manga_page_url(slug)
        response = self._get_cloudscraper().get(
            manga_url,
            timeout=self.args.timeout,
            headers=DEFAULT_HEADERS,
        )
        response.raise_for_status()

        manga = self._extract_manga_metadata(manga_url, response.text)
        payload = {
            "ok": True,
            "provider": "mangafire",
            "manga": manga,
        }

        if include_chapters:
            chapters_payload = self.list_chapters(manga_url, lang, preferred_chapter)
            payload.update(
                {
                    "language": normalize_lang(lang or "pt-br"),
                    "chapter_count": chapters_payload["count"],
                    "selected_chapter_url": chapters_payload.get("selected_url"),
                    "chapters": chapters_payload["chapters"],
                }
            )

        return payload

    def _mangadex_manga_metadata(
        self,
        source_url: str,
        lang: str = "pt-br",
        preferred_chapter: str | None = None,
        include_chapters: bool = True,
    ) -> dict:
        manga_id = self._mangadex_manga_id_from_source(source_url)
        if not manga_id:
            chapter_id = self._mangadex_chapter_id_from_source(source_url)
            if chapter_id:
                detail = self._mangadex_get(f"/chapter/{chapter_id}", {"includes[]": ["manga"]})
                manga_id = self._mangadex_related_id(detail.get("data") or {}, "manga")
        if not manga_id:
            raise ValueError("Informe uma URL/ID de manga ou capitulo do MangaDex.")

        payload = self._mangadex_get(
            f"/manga/{manga_id}",
            {"includes[]": ["cover_art", "author", "artist"]},
        )
        item = payload.get("data") or {}
        attrs = item.get("attributes") or {}
        cover = self._mangadex_cover_filename(item)
        authors: list[str] = []
        artists: list[str] = []
        for relation in item.get("relationships", []) or []:
            rel_attrs = relation.get("attributes") or {}
            name = rel_attrs.get("name")
            if not name:
                continue
            if relation.get("type") == "author":
                authors.append(name)
            elif relation.get("type") == "artist":
                artists.append(name)

        manga = {
            "slug": manga_id,
            "url": self._mangadex_manga_url(manga_id),
            "title": first_localized_text(attrs.get("title")),
            "alternative_title": None,
            "status": attrs.get("status"),
            "type": "MangaDex",
            "poster": (
                f"{MANGADEX_UPLOADS_URL}/covers/{manga_id}/{cover}.512.jpg"
                if cover else None
            ),
            "description": first_localized_text(attrs.get("description")),
            "latest_chapter": attrs.get("lastChapter"),
            "authors": authors,
            "genres": [
                first_localized_text((tag.get("attributes") or {}).get("name")) or ""
                for tag in attrs.get("tags", [])
            ],
            "magazines": [],
            "published": attrs.get("year"),
            "rating": {},
            "languages": [],
            "artists": artists,
        }
        manga["genres"] = [genre for genre in manga["genres"] if genre]

        result = {
            "ok": True,
            "provider": "mangadex",
            "manga": manga,
        }
        if include_chapters:
            chapters_payload = self.list_chapters(self._mangadex_manga_url(manga_id), lang, preferred_chapter)
            result.update(
                {
                    "language": normalize_lang(lang or "pt-br"),
                    "chapter_count": chapters_payload["count"],
                    "selected_chapter_url": chapters_payload.get("selected_url"),
                    "chapters": chapters_payload["chapters"],
                }
            )
        return result

    def _manga_metadata_via_api(
        self,
        source_url: str,
        lang: str = "pt-br",
        preferred_chapter: str | None = None,
        include_chapters: bool = True,
    ) -> dict:
        slug = slug_from_url(source_url)
        if not slug:
            raise ValueError("Informe uma URL de manga ou capitulo do MangaFire.")

        raw = self._api_get(f"/manga/{quote(slug, safe='')}")
        manga = self._normalize_api_manga(raw, slug)
        payload = {
            "ok": True,
            "provider": "mangafire-api",
            "api_url": self.api_base_url,
            "manga": manga,
        }

        try:
            languages_payload = self._api_get(f"/manga/{quote(slug, safe='')}/chapters")
            languages = self._normalize_api_languages(languages_payload)
            if languages:
                payload["manga"]["languages"] = languages
        except Exception:
            pass

        if include_chapters:
            chapters_payload = self.list_chapters(manga_page_url(slug), lang, preferred_chapter)
            payload.update(
                {
                    "language": normalize_lang(lang or "pt-br"),
                    "chapter_count": chapters_payload["count"],
                    "selected_chapter_url": chapters_payload.get("selected_url"),
                    "chapters": chapters_payload["chapters"],
                }
            )

        return payload

    def _normalize_api_manga(self, payload, slug: str) -> dict:
        data = payload
        if isinstance(payload, dict):
            for key in ("data", "manga", "result"):
                if isinstance(payload.get(key), dict):
                    data = payload[key]
                    break
        if not isinstance(data, dict):
            data = {}

        title = self._first_text(data, "title", "name", "mangaTitle")
        poster = self._first_text(data, "poster", "image", "cover", "thumbnail")
        description = self._first_text(data, "description", "synopsis", "summary")
        status = self._first_text(data, "status")
        manga_type = self._first_text(data, "type", "category")

        return {
            "slug": slug,
            "url": manga_page_url(slug),
            "title": title,
            "alternative_title": self._first_text(data, "alternativeTitle", "altTitle", "otherName"),
            "status": status,
            "type": manga_type,
            "poster": urljoin(BASE_URL, poster) if poster else None,
            "description": description,
            "latest_chapter": self._first_text(data, "latestChapter", "latest_chapter"),
            "authors": self._normalize_string_list(data.get("authors") or data.get("author")),
            "genres": self._normalize_string_list(data.get("genres") or data.get("genre")),
            "magazines": self._normalize_string_list(data.get("magazines") or data.get("magazine")),
            "published": self._first_text(data, "published", "publishedDate"),
            "rating": data.get("rating") if isinstance(data.get("rating"), dict) else {},
            "languages": self._normalize_api_languages(data.get("languages")),
            "raw": data,
        }

    def _normalize_string_list(self, value) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [part.strip() for part in re.split(r",|;", value) if part.strip()]
        if isinstance(value, list):
            output: list[str] = []
            for item in value:
                if isinstance(item, str):
                    output.append(normalize_text(item))
                elif isinstance(item, dict):
                    text = self._first_text(item, "title", "name", "label")
                    if text:
                        output.append(text)
            return output
        return []

    def _normalize_api_languages(self, payload) -> list[dict]:
        languages = self._api_list(payload)
        if isinstance(payload, dict) and isinstance(payload.get("languages"), list):
            languages = payload["languages"]

        output: list[dict] = []
        seen: set[str] = set()
        for item in languages:
            if isinstance(item, str):
                code = item
                title = item
                count = None
            elif isinstance(item, dict):
                code = self._first_text(item, "id", "code", "language") or ""
                title = self._first_text(item, "title", "name", "label") or code
                chapters = self._first_text(item, "chapters", "chapter_count", "chapterCount")
                count_match = re.search(r"\d+", chapters or "")
                count = int(count_match.group(0)) if count_match else None
            else:
                continue

            if not code or code in seen:
                continue
            seen.add(code)
            output.append({"code": code, "title": title, "chapter_count": count})
        return output

    def chapter_metadata(
        self,
        chapter_url: str,
        cache_pages: bool = False,
        include_source_urls: bool = False,
    ) -> dict:
        loaded = self.load_chapter(chapter_url)
        if loaded.get("mode") == "text":
            return {"ok": True, **loaded}
        return self.current_chapter_metadata(
            cache_pages=cache_pages,
            include_source_urls=include_source_urls,
            loaded=loaded,
        )

    def current_chapter_metadata(
        self,
        cache_pages: bool = False,
        include_source_urls: bool = False,
        loaded: dict | None = None,
    ) -> dict:
        with self.lock:
            if self.state is None:
                raise FileNotFoundError("Nenhum capitulo aberto.")

            state = self.state
            image_count = len(state.image_urls)
            payload = dict(loaded or {})
            payload.update(
                {
                    "ok": True,
                    "provider": payload.get("provider") or "mangafire",
                    "chapter": {
                        "url": state.url,
                        "label": state.label,
                        "number": payload.get("number", chapter_number_from_url(state.url)),
                        "number_text": payload.get("number_text", chapter_number_text_from_url(state.url)),
                        "page_count": image_count,
                        "previous": state.previous_url,
                        "next": state.next_url,
                    },
                    "cache": {
                        "enabled": True,
                        "complete": False,
                        "directory": str(state.cache_dir),
                    },
                }
            )

        images = [
            self.image_metadata(index, cache_pages, include_source_urls)
            for index in range(1, image_count + 1)
        ]
        payload["images"] = images
        payload["cache"]["complete"] = all(image.get("cached") for image in images)
        payload["count"] = image_count
        return payload

    def image_metadata(
        self,
        index: int,
        cache_page: bool = False,
        include_source_url: bool = False,
    ) -> dict:
        path: Path | None = None
        content_type: str | None = None

        if cache_page:
            path, content_type = self.get_image(index)

        with self.lock:
            if self.state is None:
                raise FileNotFoundError("Nenhum capitulo aberto.")
            if index < 1 or index > len(self.state.image_urls):
                raise FileNotFoundError("Pagina fora da faixa.")

            source_url = self.state.image_urls[index - 1]
            cached = self.state.image_cache.get(index)
            if path is None and cached and cached.path.exists():
                path = cached.path
                content_type = cached.content_type

        timestamp = int(time.time())
        payload = {
            "index": index,
            "cached": path is not None and path.exists(),
            "api_url": f"/api/v1/image/{index}?v={timestamp}",
            "reader_url": f"/api/image/{index}?v={timestamp}",
        }
        if include_source_url:
            payload["source_url"] = source_url

        if path is not None and path.exists():
            relative = path.resolve().relative_to(self.cache.root.resolve()).as_posix()
            payload.update(
                {
                    "cache_url": f"/cache/{quote(relative, safe='/')}",
                    "filename": path.name,
                    "content_type": content_type
                    or mimetypes.guess_type(path.name)[0]
                    or "application/octet-stream",
                    "bytes": path.stat().st_size,
                }
            )
        return payload

    def _extract_manga_metadata(self, manga_url: str, html: str) -> dict:
        slug = slug_from_url(manga_url)
        title = text_from_html(first_match(r'<h1[^>]*itemprop=["\']name["\'][^>]*>(.*?)</h1>', html) or "")
        if not title:
            title = text_from_html(first_match(r"<title[^>]*>(.*?)</title>", html) or "")
            title = re.sub(r"\s+Manga\s+-\s+Read.*$", "", title, flags=re.IGNORECASE).strip()

        alt_title = text_from_html(first_match(r'<h1[^>]*itemprop=["\']name["\'][^>]*>.*?</h1>\s*<h6[^>]*>(.*?)</h6>', html) or "")
        status = text_from_html(first_match(r'<div class=["\']info["\'][^>]*>\s*<p[^>]*>(.*?)</p>', html) or "")
        manga_type = text_from_html(first_match(r'<div class=["\']min-info["\'][^>]*>\s*<a[^>]*>(.*?)</a>', html) or "")
        poster = first_match(r'<img[^>]+itemprop=["\']image["\'][^>]+src=["\']([^"\']+)', html)
        if not poster:
            poster = first_match(r'<div class=["\']poster["\'][^>]*>.*?<img[^>]+src=["\']([^"\']+)', html)

        synopsis = text_from_html(first_match(r'<div class=["\']modal fade["\'][^>]+id=["\']synopsis["\'][^>]*>.*?<div class=["\']modal-content[^"\']*["\'][^>]*>(.*?)</div>\s*</div>\s*</div>', html) or "")
        description = synopsis or text_from_html(first_match(r'<div class=["\']description["\'][^>]*>(.*?)</div>', html) or "")

        meta = self._extract_manga_meta_pairs(html)
        languages = self._extract_manga_languages(html)
        rating_score = first_match(r'data-score=["\']([^"\']+)', html)
        review_count = first_match(r'itemprop=["\']reviewCount["\'][^>]*>(.*?)</span>', html)
        mal_match = re.search(
            r"<b>\s*([\d.]+)\s*MAL\s*</b>\s*by\s*([^<]+)\s*users",
            html,
            re.IGNORECASE,
        )
        latest_chapter = first_match(r"latest chapter\s+([\d.]+)", html)

        return {
            "slug": slug,
            "url": manga_url,
            "title": title,
            "alternative_title": alt_title or None,
            "status": status or None,
            "type": manga_type or None,
            "poster": urljoin(BASE_URL, poster) if poster else None,
            "description": description or None,
            "latest_chapter": latest_chapter,
            "authors": meta.get("Author", []),
            "genres": meta.get("Genres", []),
            "magazines": meta.get("Mangazines", []),
            "published": meta.get("Published", [None])[0],
            "rating": {
                "score": float(rating_score) if rating_score else None,
                "reviews": int(review_count) if review_count and review_count.isdigit() else None,
                "mal_score": float(mal_match.group(1)) if mal_match else None,
                "mal_users": normalize_text(mal_match.group(2)) if mal_match else None,
            },
            "languages": languages,
        }

    def _extract_manga_meta_pairs(self, html: str) -> dict[str, list[str]]:
        meta_block = first_match(
            r'<div class=["\']meta["\'][^>]*>(.*?)</div>\s*<div class=["\']rating-box',
            html,
        ) or ""
        pairs: dict[str, list[str]] = {}
        for label_html, value_html in re.findall(
            r"<div>\s*<span[^>]*>(.*?)</span>\s*<span[^>]*>(.*?)</span>\s*</div>",
            meta_block,
            re.IGNORECASE | re.DOTALL,
        ):
            label = text_from_html(label_html).rstrip(":")
            values = [
                text_from_html(value)
                for value in re.findall(r"<a\b[^>]*>(.*?)</a>", value_html, re.IGNORECASE | re.DOTALL)
            ]
            if not values:
                text_value = text_from_html(value_html)
                values = [text_value] if text_value else []
            pairs[label] = values
        return pairs

    def _extract_manga_languages(self, html: str) -> list[dict]:
        languages: list[dict] = []
        by_code: dict[str, dict] = {}
        for code, title, body in re.findall(
            r'<a[^>]+class=["\'][^"\']*dropdown-item[^"\']*["\'][^>]+data-code=["\']([^"\']+)["\'][^>]+data-title=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
            html,
            re.IGNORECASE | re.DOTALL,
        ):
            text = text_from_html(body)
            count_match = re.search(r"\((\d+)\s+Chapters?\)", text, re.IGNORECASE)
            entry = {
                "code": code,
                "title": normalize_text(title),
                "chapter_count": int(count_match.group(1)) if count_match else None,
            }
            existing = by_code.get(code)
            if existing is None or (
                existing.get("chapter_count") is None
                and entry.get("chapter_count") is not None
            ):
                by_code[code] = entry
        return list(by_code.values())

    def list_chapters(
        self,
        source_url: str,
        lang: str = "pt-br",
        preferred_chapter: str | None = None,
    ) -> dict:
        with self.lock:
            self._last_mangafire_chapters_provider = None
            if self._is_toomics_source(source_url):
                chapters = self._fetch_toomics_chapters(source_url, lang, preferred_chapter)
            elif self._is_mangalivre_source(source_url):
                chapters = self._fetch_mangalivre_chapters(source_url, preferred_chapter)
            elif self._is_mangasbrasuka_source(source_url):
                chapters = self._fetch_mangasbrasuka_chapters(source_url, preferred_chapter)
            elif self._is_mangakatana_source(source_url):
                chapters = self._fetch_mangakatana_chapters(source_url, preferred_chapter)
            elif self._is_dragontea_source(source_url):
                chapters = self._fetch_dragontea_chapters(source_url, preferred_chapter)
            elif self._is_mangadex_source(source_url):
                chapters = self._fetch_mangadex_chapters(source_url, lang, preferred_chapter)
            elif self._is_pieceproject_source(source_url):
                chapters = self._fetch_pieceproject_chapters(source_url, preferred_chapter)
            elif self._is_readfull_source(source_url):
                chapters = self._fetch_readfull_chapters(source_url, preferred_chapter)
            elif self._is_noveltoon_source(source_url):
                chapters = self._fetch_noveltoon_chapters(source_url, lang, preferred_chapter)
            elif self.use_api:
                try:
                    chapters = self._fetch_chapters_via_api(source_url, lang, preferred_chapter)
                except Exception:
                    chapters = self._fetch_chapters_with_fallback(source_url, lang, preferred_chapter)
            else:
                chapters = self._fetch_chapters_with_fallback(source_url, lang, preferred_chapter)
            selected = self._select_chapter(chapters, source_url, preferred_chapter)
            display_chapters = list(reversed(chapters))
            provider = (
                "toomics"
                if self._is_toomics_source(source_url)
                else "mangalivre" if self._is_mangalivre_source(source_url)
                else "mangasbrasuka" if self._is_mangasbrasuka_source(source_url)
                else "mangakatana" if self._is_mangakatana_source(source_url)
                else "dragontea" if self._is_dragontea_source(source_url)
                else "mangadex" if self._is_mangadex_source(source_url)
                else "pieceproject" if self._is_pieceproject_source(source_url)
                else "readfull" if self._is_readfull_source(source_url)
                else "noveltoon" if self._is_noveltoon_source(source_url)
                else self._last_mangafire_chapters_provider if self._last_mangafire_chapters_provider
                else "mangafire-api" if chapters and chapters[0].chapter_id
                else "mangafire"
            )
            language = (
                "en"
                if provider in {"mangakatana", "readfull"}
                else "pt-br" if provider in {"pieceproject", "mangalivre", "mangasbrasuka"}
                else normalize_lang(lang or "pt-br")
            )

            return {
                "ok": True,
                "provider": provider,
                "language": language,
                "source_url": source_url,
                "selected_url": selected.url if selected else None,
                "count": len(chapters),
                "chapters": [
                    self._serialize_chapter(chapter)
                    for chapter in display_chapters
                ],
            }

    def load_source(
        self,
        source_url: str,
        lang: str = "pt-br",
        preferred_chapter: str | None = None,
    ) -> dict:
        if (
            self._is_chapter_url(source_url)
            or (self._is_toomics_source(source_url) and self._toomics_chapter_parts(source_url))
            or (self._is_mangalivre_source(source_url) and self._mangalivre_chapter_slug_from_source(source_url))
            or (self._is_mangasbrasuka_source(source_url) and self._mangasbrasuka_chapter_parts(source_url))
            or (self._is_mangakatana_source(source_url) and self._mangakatana_chapter_parts(source_url))
            or self._is_dragontea_source(source_url)
            or (self._is_readfull_source(source_url) and self._readfull_chapter_parts(source_url))
            or (self._is_mangadex_source(source_url) and self._mangadex_chapter_id_from_source(source_url))
            or (self._is_pieceproject_source(source_url) and self._pieceproject_chapter_number_from_source(source_url))
            or (self._is_noveltoon_source(source_url) and self._noveltoon_chapter_parts(source_url))
        ):
            return self.load_chapter(source_url)

        chapters_payload = self.list_chapters(source_url, lang, preferred_chapter)
        selected_url = chapters_payload.get("selected_url")
        if not selected_url:
            raise RuntimeError("Nenhum capitulo foi selecionado automaticamente.")
        return self.load_chapter(selected_url)

    def load_chapter(self, url: str) -> dict:
        if self._is_toomics_source(url):
            return self._load_toomics_chapter(url)

        if self._is_mangalivre_source(url):
            return self._load_mangalivre_chapter(url)

        if self._is_mangasbrasuka_source(url):
            return self._load_mangasbrasuka_chapter(url)

        if self._is_mangakatana_source(url):
            return self._load_mangakatana_chapter(url)

        if self._is_dragontea_source(url):
            return self._load_dragontea_chapter(url)

        if self._is_readfull_source(url) and self._readfull_chapter_parts(url):
            return self._load_readfull_chapter(url)

        if self._is_noveltoon_source(url) and self._noveltoon_chapter_parts(url):
            return self._load_noveltoon_chapter(url)

        if self._is_mangadex_source(url) and self._mangadex_chapter_id_from_source(url):
            return self._load_mangadex_chapter(url)

        if self._is_pieceproject_source(url):
            return self._load_pieceproject_chapter(url)

        if self.use_api:
            try:
                return self._load_chapter_via_api(url)
            except (requests.RequestException, RuntimeError, ValueError, KeyError, TypeError, json.JSONDecodeError):
                pass

        try:
            return self._load_chapter_via_http(url)
        except Exception:
            pass

        with self.lock:
            if not self._is_chapter_url(url):
                raise ValueError("Informe uma URL de capitulo do MangaFire.")

            driver = self.get_driver()
            clear_resource_timings(driver)
            driver.get(url)
            session = session_from_driver(driver, url)

            image_api_url = wait_for_resource_url(
                driver,
                self.args.timeout,
                "imagens do capitulo",
                is_image_list_api,
            )
            image_payload = request_json(session, image_api_url, url, self.args.timeout)
            image_urls = extract_image_urls(image_payload)
            if not image_urls:
                raise RuntimeError("O MangaFire nao retornou imagens para este capitulo.")

            chapters = self._try_get_chapters(driver, session, url)
            previous_url, next_url = self._find_neighbors(chapters, url)

            label = self._chapter_label(url)
            cache_dir = self.cache.new_chapter_dir(label)
            self.state = ChapterState(
                url=url,
                label=label,
                image_urls=image_urls,
                cache_dir=cache_dir,
                session=session,
                previous_url=previous_url,
                next_url=next_url,
            )

            return {
                "ok": True,
                "url": url,
                "label": label,
                "count": len(image_urls),
                "previous": previous_url,
                "next": next_url,
                "images": [
                    {"index": index, "src": f"/api/image/{index}?v={int(time.time())}"}
                    for index in range(1, len(image_urls) + 1)
                ],
            }

    def _load_pieceproject_chapter(self, url: str) -> dict:
        catalog = self._pieceproject_catalog()
        wanted_number = self._pieceproject_chapter_number_from_source(url)
        selected = None
        if wanted_number:
            selected = next((item for item in catalog if str(item["number"]) == wanted_number), None)
        else:
            selected = catalog[0] if catalog else None

        if not selected:
            raise ValueError("Capitulo do piecePROJECT nao encontrado.")

        number_text = str(selected["number"])
        image_urls = [str(page).strip() for page in selected.get("pages") or [] if str(page).strip()]
        if not image_urls:
            raise RuntimeError("O piecePROJECT nao retornou imagens para este capitulo.")

        selected_url = self._pieceproject_chapter_url(number_text)
        chapters = self._fetch_pieceproject_chapters(self._pieceproject_manga_url())
        previous_url, next_url = self._find_neighbors(chapters, selected_url)

        session = requests.Session()
        session.headers.update(
            {
                **DEFAULT_HEADERS,
                "Referer": DEFAULT_PIECEPROJECT_URL,
                "Origin": "https://scan.onepieceproject.com.br",
            }
        )

        label = clean_filename(f"pieceproject-one-piece-chapter-{number_text}", fallback="pieceproject-chapter")
        cache_dir = self.cache.new_chapter_dir(label)
        web_url = self._pieceproject_web_chapter_url(number_text)
        self.state = ChapterState(
            url=web_url,
            label=label,
            image_urls=image_urls,
            cache_dir=cache_dir,
            session=session,
            previous_url=previous_url,
            next_url=next_url,
        )

        return {
            "ok": True,
            "provider": "pieceproject",
            "api_url": DEFAULT_PIECEPROJECT_URL,
            "url": selected_url,
            "source_url": web_url,
            "chapter_id": f"pieceproject:{number_text}",
            "label": label,
            "title": selected.get("title"),
            "number": parse_float(number_text),
            "number_text": number_text,
            "language": "pt-br",
            "count": len(image_urls),
            "previous": previous_url,
            "next": next_url,
            "images": [
                {"index": index, "src": f"/api/image/{index}?v={int(time.time())}"}
                for index in range(1, len(image_urls) + 1)
            ],
        }

    def _load_mangadex_chapter(self, url: str) -> dict:
        chapter_id = self._mangadex_chapter_id_from_source(url)
        if not chapter_id:
            raise ValueError("Informe uma URL de capitulo do MangaDex.")

        detail = self._mangadex_get(f"/chapter/{chapter_id}", {"includes[]": ["manga"]})
        chapter_item = detail.get("data") or {}
        attrs = chapter_item.get("attributes") or {}
        manga_id = self._mangadex_related_id(chapter_item, "manga")
        lang = attrs.get("translatedLanguage") or "pt-br"

        at_home = self._mangadex_get(f"/at-home/server/{chapter_id}")
        base_url = at_home.get("baseUrl")
        chapter_data = at_home.get("chapter") or {}
        chapter_hash = chapter_data.get("hash")
        pages = chapter_data.get("data") or []
        if not base_url or not chapter_hash or not pages:
            raise RuntimeError("A API do MangaDex nao retornou paginas para este capitulo.")

        image_urls = [
            f"{base_url}/data/{chapter_hash}/{filename}"
            for filename in pages
            if isinstance(filename, str)
        ]
        if not image_urls:
            raise RuntimeError("A API do MangaDex nao retornou imagens validas.")

        chapters: list[Chapter] = []
        previous_url: str | None = None
        next_url: str | None = None
        if manga_id:
            try:
                chapters = self._fetch_mangadex_chapters(self._mangadex_manga_url(manga_id), lang)
                previous_url, next_url = self._find_neighbors(chapters, url)
            except Exception:
                previous_url, next_url = None, None

        number_text = attrs.get("chapter")
        title = attrs.get("title")
        label_parts = ["mangadex"]
        if manga_id:
            label_parts.append(manga_id[:8])
        label_parts.append(f"chapter-{number_text or chapter_id[:8]}")
        label = clean_filename("-".join(label_parts), fallback="mangadex-chapter")

        session = requests.Session()
        session.headers.update(DEFAULT_HEADERS)
        cache_dir = self.cache.new_chapter_dir(label)
        self.state = ChapterState(
            url=url,
            label=label,
            image_urls=image_urls,
            cache_dir=cache_dir,
            session=session,
            previous_url=previous_url,
            next_url=next_url,
        )

        return {
            "ok": True,
            "provider": "mangadex",
            "url": url,
            "chapter_id": chapter_id,
            "label": label,
            "title": title,
            "number": parse_float(number_text),
            "number_text": str(number_text) if number_text else None,
            "language": lang,
            "count": len(image_urls),
            "previous": previous_url,
            "next": next_url,
            "images": [
                {"index": index, "src": f"/api/image/{index}?v={int(time.time())}"}
                for index in range(1, len(image_urls) + 1)
            ],
        }

    def _load_readfull_chapter(self, url: str) -> dict:
        parts = self._readfull_chapter_parts(url)
        if not parts:
            raise ValueError("Informe uma URL de capitulo do ReadFull.")
        novel_id, chapter_no = parts

        payload = self._readfull_get(f"/novels/{novel_id}/chapters/{chapter_no}/")
        if not isinstance(payload, dict):
            raise RuntimeError("A API ReadFull nao retornou um capitulo valido.")

        title = self._first_text(payload, "title", "name") or f"Chapter {chapter_no}"
        content = self._first_text(payload, "content", "text", "body") or ""
        if not content:
            raise RuntimeError("A API ReadFull retornou um capitulo sem conteudo.")

        chapters: list[Chapter] = []
        previous_url: str | None = None
        next_url: str | None = None
        try:
            chapters = self._fetch_readfull_chapters(self._readfull_novel_url(novel_id))
            previous_url, next_url = self._find_neighbors(chapters, url)
        except Exception:
            previous_url, next_url = None, None

        label = clean_filename(f"readfull-{novel_id}-chapter-{chapter_no}", fallback="readfull-chapter")

        return {
            "ok": True,
            "provider": "readfull",
            "mode": "text",
            "api_url": self.readfull_api_base_url,
            "url": self._readfull_chapter_url(novel_id, chapter_no),
            "novel_id": novel_id,
            "label": label,
            "title": title,
            "content": content,
            "number": parse_float(chapter_no),
            "number_text": chapter_no,
            "count": 1,
            "previous": previous_url,
            "next": next_url,
        }

    def _load_chapter_via_api(self, url: str) -> dict:
        with self.lock:
            if not (url.startswith("api://chapter/") or self._is_chapter_url(url)):
                raise ValueError("Informe uma URL de capitulo do MangaFire.")

            chapter_id = self._chapter_id_for_url(url)
            if not chapter_id:
                raise RuntimeError("Nao consegui resolver o chapterId pela API do MangaFire.")

            payload = self._api_get(f"/chapter/{quote(chapter_id, safe='')}")
            image_urls = self._image_urls_from_api_payload(payload)
            if not image_urls:
                raise RuntimeError("A API do MangaFire nao retornou imagens para este capitulo.")

            chapters: list[Chapter] = []
            previous_url: str | None = None
            next_url: str | None = None
            if self._is_chapter_url(url):
                slug = slug_from_url(url)
                lang = self._lang_from_chapter_url(url)
                if slug and lang:
                    try:
                        chapters = self._fetch_chapters_via_api(manga_page_url(slug), lang)
                        previous_url, next_url = self._find_neighbors(chapters, url)
                    except Exception:
                        previous_url, next_url = None, None

            session = session_from_scraper(self._get_cloudscraper(), url)
            label = self._chapter_label(url)
            cache_dir = self.cache.new_chapter_dir(label)
            self.state = ChapterState(
                url=url,
                label=label,
                image_urls=image_urls,
                cache_dir=cache_dir,
                session=session,
                previous_url=previous_url,
                next_url=next_url,
            )

            return {
                "ok": True,
                "provider": "mangafire-api",
                "api_url": self.api_base_url,
                "url": url,
                "chapter_id": chapter_id,
                "label": label,
                "count": len(image_urls),
                "previous": previous_url,
                "next": next_url,
                "images": [
                    {"index": index, "src": f"/api/image/{index}?v={int(time.time())}"}
                    for index in range(1, len(image_urls) + 1)
                ],
            }

    def _compose_toomics_chunk(
        self,
        index: int,
        image_urls: list[str],
        cache_dir: Path,
        session: requests.Session,
        headers: dict,
        timeout: tuple[float, float],
    ) -> tuple[Path, str]:
        target = cache_dir / f"{index:03d}-toomics-stitched.jpg"
        if target.exists():
            return target, "image/jpeg"

        images: list[Image.Image] = []
        stitched: Image.Image | None = None
        try:
            for source_index, image_url in enumerate(image_urls, start=1):
                response: requests.Response | None = None
                last_error: Exception | None = None
                for attempt in range(1, 5):
                    try:
                        response = session.get(image_url, timeout=timeout, headers=headers)
                        if response.status_code in {429, 500, 502, 503, 504}:
                            raise requests.HTTPError(
                                f"HTTP {response.status_code} ao baixar fatia {source_index}",
                                response=response,
                            )
                        response.raise_for_status()
                        break
                    except requests.RequestException as exc:
                        last_error = exc
                        if attempt == 4:
                            raise RuntimeError(
                                f"Falha ao baixar fatia {source_index} da pagina {index}: {exc}"
                            ) from exc
                        time.sleep(0.5 * attempt)

                if response is None:
                    raise RuntimeError(
                        f"Falha ao baixar fatia {source_index} da pagina {index}: {last_error}"
                    )

                with Image.open(io.BytesIO(response.content)) as opened:
                    if opened.mode in {"RGBA", "LA"} or (
                        opened.mode == "P" and "transparency" in opened.info
                    ):
                        rgba = opened.convert("RGBA")
                        image = Image.new("RGB", rgba.size, "white")
                        image.paste(rgba, mask=rgba.getchannel("A"))
                    else:
                        image = opened.convert("RGB")
                    images.append(image.copy())

            if not images:
                raise RuntimeError(f"Nenhuma fatia foi baixada para a pagina {index}.")

            width = max(image.width for image in images)
            height = sum(image.height for image in images)
            stitched = Image.new("RGB", (width, height), "white")
            y = 0
            for image in images:
                stitched.paste(image, ((width - image.width) // 2, y))
                y += image.height

            tmp_target = target.with_name(f"{target.name}.part")
            stitched.save(tmp_target, format="JPEG", quality=95)
            tmp_target.replace(target)
            return target, "image/jpeg"
        finally:
            for image in images:
                image.close()
            if stitched is not None:
                stitched.close()

    def get_image(self, index: int) -> tuple[Path, str]:
        with self.lock:
            state = self.state
            if state is None:
                raise FileNotFoundError("Nenhum capitulo aberto.")
            if index < 1 or index > len(state.image_urls):
                raise FileNotFoundError("Pagina fora da faixa.")

            cached = state.image_cache.get(index)
            if cached and cached.path.exists():
                return cached.path, cached.content_type

            image_url = state.image_urls[index - 1]
            source_image_chunk = (
                list(state.source_image_chunks[index - 1])
                if state.source_image_chunks
                else []
            )
            referer = state.url
            cache_dir = state.cache_dir
            session_headers = dict(state.session.headers)
            session_cookies = state.session.cookies.copy()

        headers = dict(DEFAULT_HEADERS)
        headers.update(session_headers)
        headers.update(
            {
                "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                "Referer": referer,
            }
        )
        session = self._get_cloudscraper()
        session.headers.update(headers)
        for name, value in session_cookies.items():
            session.cookies.set(name, value)

        read_timeout = min(max(float(self.args.timeout), 12.0), 25.0)
        timeout = (8.0, read_timeout)
        last_error: Exception | None = None
        response: requests.Response | None = None

        if source_image_chunk:
            target, content_type = self._compose_toomics_chunk(
                index,
                source_image_chunk,
                cache_dir,
                session,
                headers,
                timeout,
            )
        else:
            for attempt in range(1, 5):
                try:
                    response = session.get(
                        image_url,
                        timeout=timeout,
                        headers=headers,
                    )
                    if response.status_code in {429, 500, 502, 503, 504}:
                        raise requests.HTTPError(
                            f"HTTP {response.status_code} ao baixar pagina {index}",
                            response=response,
                        )
                    response.raise_for_status()
                    break
                except requests.RequestException as exc:
                    last_error = exc
                    if attempt == 4:
                        raise RuntimeError(f"Falha ao baixar pagina {index}: {exc}") from exc
                    time.sleep(0.5 * attempt)

            if response is None:
                raise RuntimeError(f"Falha ao baixar pagina {index}: {last_error}")

            content_type = response.headers.get("Content-Type", "image/jpeg").split(";")[0]
            filename = filename_from_url(image_url, index, content_type)
            target = cache_dir / filename
            tmp_target = target.with_name(f"{target.name}.part")
            tmp_target.write_bytes(response.content)
            tmp_target.replace(target)

        with self.lock:
            if self.state is not state:
                raise FileNotFoundError("O capitulo mudou antes da pagina terminar.")
            state.image_cache[index] = ImageCacheEntry(target, content_type)
            return target, content_type

    def cache_path(self, relative_path: str) -> tuple[Path, str]:
        path = (self.cache.root / unquote(relative_path)).resolve()
        if not self.cache.contains(path) or not path.exists() or not path.is_file():
            raise FileNotFoundError("Arquivo nao encontrado na cache.")
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return path, content_type

    def _try_get_chapters(
        self,
        driver,
        session: requests.Session,
        referer: str,
    ) -> list[Chapter]:
        for url in reversed(resource_urls(driver)):
            if not is_chapter_list_api(url):
                continue
            try:
                payload = request_json(session, url, referer, self.args.timeout)
                return extract_chapters_from_payload(payload)
            except Exception:
                return []
        return []

    def _fetch_chapters_via_curl_cffi(self, source_url: str, lang: str) -> list[Chapter]:
        slug = slug_from_url(source_url)
        if not slug:
            raise ValueError("Informe uma URL do MangaFire.")

        normalized_lang = normalize_lang(lang or "pt-br")
        api_url, referer = chapter_list_api_url(slug, normalized_lang)
        payload = self._mangafire_curl_json(api_url, referer, self.args.timeout)
        chapters = extract_chapters_from_payload(payload)
        if not chapters:
            raise RuntimeError("A lista de capitulos veio vazia.")

        for chapter in chapters:
            if chapter.chapter_id:
                self.api_chapter_ids_by_url[chapter.url] = chapter.chapter_id
        self._last_mangafire_chapters_provider = "mangafire-curl_cffi"
        return chapters

    def _fetch_chapter_images_via_curl_cffi(
        self,
        chapter_id: str,
        referer: str,
    ) -> list[str]:
        api_url, default_referer = chapter_images_api_url(chapter_id)
        payload = self._mangafire_curl_json(api_url, referer or default_referer, self.args.timeout)
        image_urls = extract_image_urls(payload)
        if not image_urls:
            raise RuntimeError("O MangaFire nao retornou imagens para este capitulo.")
        return image_urls

    def _fetch_chapters_with_fallback(
        self,
        source_url: str,
        lang: str,
        preferred_chapter: str | None = None,
    ) -> list[Chapter]:
        try:
            return self._fetch_chapters_via_curl_cffi(source_url, lang)
        except Exception:
            pass
        try:
            return self._fetch_chapters_via_http(source_url, lang)
        except Exception:
            return self._fetch_chapters(source_url, lang, preferred_chapter)

    def _fetch_chapters_via_http(self, source_url: str, lang: str) -> list[Chapter]:
        slug = slug_from_url(source_url)
        if not slug:
            raise ValueError("Informe uma URL do MangaFire.")

        scraper = self._get_cloudscraper()
        chapters = fetch_chapters_http(scraper, slug, lang, self.args.timeout)
        self._last_mangafire_chapters_provider = "mangafire-cloudscraper"
        return chapters

    def _load_chapter_via_http(self, url: str) -> dict:
        with self.lock:
            if not self._is_chapter_url(url):
                raise ValueError("Informe uma URL de capitulo do MangaFire.")

            slug = slug_from_url(url)
            chapter_lang = self._lang_from_chapter_url(url)
            chapter_id = self.api_chapter_ids_by_url.get(url)
            scraper = self._get_cloudscraper()

            chapters: list[Chapter] = []
            if not chapter_id and slug and chapter_lang:
                try:
                    chapters = self._fetch_chapters_via_curl_cffi(manga_page_url(slug), chapter_lang)
                except Exception:
                    chapters = fetch_chapters_http(scraper, slug, chapter_lang, self.args.timeout)
                selected = self._select_chapter(chapters, url)
                chapter_id = selected.chapter_id if selected else None
                for chapter in chapters:
                    if chapter.chapter_id:
                        self.api_chapter_ids_by_url[chapter.url] = chapter.chapter_id

            if not chapter_id:
                raise RuntimeError("Nao consegui resolver o chapterId do MangaFire.")

            async def _parallel_load():
                img_api_url, img_referer = chapter_images_api_url(chapter_id)
                img_task = self._mangafire_async_json(img_api_url, img_referer or url, self.args.timeout)

                if chapters:
                    img_payload = await img_task
                    return img_payload, None
                else:
                    chap_api_url, chap_referer = chapter_list_api_url(slug, chapter_lang)
                    chap_task = self._mangafire_async_json(chap_api_url, chap_referer, self.args.timeout)
                    img_result, chap_result = await asyncio.gather(img_task, chap_task, return_exceptions=True)
                    return img_result, chap_result

            img_payload, chap_payload = self._run_async(_parallel_load())

            if isinstance(img_payload, BaseException):
                image_urls = fetch_chapter_images_http(scraper, chapter_id, url, self.args.timeout)
                image_provider = "mangafire"
            else:
                image_urls = extract_image_urls(img_payload)
                image_provider = "mangafire-curl_cffi"
                if not image_urls:
                    image_urls = fetch_chapter_images_http(scraper, chapter_id, url, self.args.timeout)
                    image_provider = "mangafire"

            if not chapters and chap_payload is not None and not isinstance(chap_payload, BaseException):
                try:
                    fetched = extract_chapters_from_payload(chap_payload)
                    if fetched:
                        chapters = fetched
                        for chapter in chapters:
                            if chapter.chapter_id:
                                self.api_chapter_ids_by_url[chapter.url] = chapter.chapter_id
                except Exception:
                    pass

            if not chapters and slug and chapter_lang:
                try:
                    chapters = fetch_chapters_http(scraper, slug, chapter_lang, self.args.timeout)
                except Exception:
                    chapters = []

            previous_url, next_url = self._find_neighbors(chapters, url)

            label = self._chapter_label(url)
            cache_dir = self.cache.new_chapter_dir(label)
            session = session_from_scraper(scraper, url)
            self.state = ChapterState(
                url=url,
                label=label,
                image_urls=image_urls,
                cache_dir=cache_dir,
                session=session,
                previous_url=previous_url,
                next_url=next_url,
            )

            return {
                "ok": True,
                "provider": image_provider,
                "url": url,
                "chapter_id": chapter_id,
                "label": label,
                "count": len(image_urls),
                "previous": previous_url,
                "next": next_url,
                "images": [
                    {"index": index, "src": f"/api/image/{index}?v={int(time.time())}"}
                    for index in range(1, len(image_urls) + 1)
                ],
            }

    def _fetch_chapters(
        self,
        source_url: str,
        lang: str,
        preferred_chapter: str | None = None,
    ) -> list[Chapter]:
        if "mangafire.to/" not in source_url:
            raise ValueError("Informe uma URL do MangaFire.")

        driver = self.get_driver()
        attempts = self._chapter_seed_urls(source_url, lang, preferred_chapter)
        if not attempts:
            raise ValueError("Nao foi possivel montar uma URL de leitura para esse manga.")

        last_error: Exception | None = None
        for seed_url in attempts:
            try:
                clear_resource_timings(driver)
                driver.get(seed_url)
                api_url = wait_for_resource_url(
                    driver,
                    8,
                    "lista de capitulos",
                    is_chapter_list_api,
                )
                session = session_from_driver(driver, seed_url)
                payload = request_json(session, api_url, seed_url, self.args.timeout)
                chapters = extract_chapters_from_payload(payload)
                if chapters:
                    self._last_mangafire_chapters_provider = "mangafire-browser"
                    return chapters
            except Exception as exc:
                last_error = exc

        detail = f" Detalhe: {last_error}" if last_error else ""
        raise RuntimeError(f"Nao consegui buscar a lista de capitulos.{detail}")

    def _chapter_seed_urls(
        self,
        source_url: str,
        lang: str,
        preferred_chapter: str | None = None,
    ) -> list[str]:
        if self._is_chapter_url(source_url):
            return [source_url]

        slug = slug_from_url(source_url)
        if not slug:
            return []

        normalized_lang = normalize_lang(lang or "pt-br")
        candidates: list[str] = []

        if preferred_chapter:
            candidates.append(chapter_url_from_number(slug, normalized_lang, preferred_chapter))

        candidates.append(chapter_url_from_number(slug, normalized_lang, "1"))

        latest = self._latest_chapter_number(slug)
        if latest:
            candidates.append(chapter_url_from_number(slug, normalized_lang, latest))

        unique: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            if candidate in seen:
                continue
            seen.add(candidate)
            unique.append(candidate)
        return unique

    def _latest_chapter_number(self, slug: str) -> str | None:
        try:
            scraper = self._get_cloudscraper()
            response = scraper.get(
                manga_page_url(slug),
                timeout=min(5, self.args.timeout),
            )
            response.raise_for_status()
        except Exception:
            return None

        match = re.search(r"latest chapter\s+([\d.]+)", response.text, re.IGNORECASE)
        return match.group(1) if match else None

    def _select_chapter(
        self,
        chapters: list[Chapter],
        source_url: str,
        preferred_chapter: str | None = None,
    ) -> Chapter | None:
        if not chapters:
            return None

        preferred = self._parse_chapter_value(preferred_chapter)
        current = chapter_number_from_url(source_url)
        toomics_parts = self._toomics_chapter_parts(source_url)
        current_toomics_id = (
            f"toomics:{toomics_parts[1]}:{toomics_parts[2]}:{toomics_parts[3]}"
            if toomics_parts else None
        )
        mangalivre_slug = self._mangalivre_chapter_slug_from_source(source_url)
        current_mangalivre_id = f"mangalivre:{mangalivre_slug}" if mangalivre_slug else None
        mangakatana_parts = self._mangakatana_chapter_parts(source_url)
        current_mangakatana_id = (
            f"mangakatana:{mangakatana_parts[0]}:{mangakatana_parts[1]}"
            if mangakatana_parts else None
        )
        current_mangadex_id = self._mangadex_chapter_id_from_source(source_url)
        current_pieceproject = self._parse_chapter_value(self._pieceproject_chapter_number_from_source(source_url))
        readfull_parts = self._readfull_chapter_parts(source_url)
        current_readfull = self._parse_chapter_value(readfull_parts[1]) if readfull_parts else None
        noveltoon_parts = self._noveltoon_chapter_parts(source_url)
        current_noveltoon = self._parse_chapter_value(noveltoon_parts[2]) if noveltoon_parts else None

        if current_mangadex_id:
            for chapter in chapters:
                if chapter.chapter_id == current_mangadex_id:
                    return chapter

        if current_toomics_id:
            for chapter in chapters:
                if chapter.chapter_id == current_toomics_id:
                    return chapter

        if current_mangalivre_id:
            for chapter in chapters:
                if chapter.chapter_id == current_mangalivre_id:
                    return chapter

        if current_mangakatana_id:
            for chapter in chapters:
                if chapter.chapter_id == current_mangakatana_id:
                    return chapter

        current_toomics = self._parse_chapter_value(toomics_parts[3]) if toomics_parts else None
        current_mangalivre = self._parse_chapter_value(self._mangalivre_chapter_number_from_slug(mangalivre_slug))
        current_mangakatana = (
            self._parse_chapter_value(self._mangakatana_chapter_number_from_id(mangakatana_parts[1]))
            if mangakatana_parts else None
        )
        for wanted in (preferred, current, current_toomics, current_mangalivre, current_mangakatana, current_pieceproject, current_readfull, current_noveltoon):
            if wanted is None:
                continue
            for chapter in chapters:
                if chapter.number is not None and abs(chapter.number - wanted) < 0.0001:
                    return chapter

        if self._is_toomics_source(source_url):
            return chapters[0]

        return chapters[-1]

    def _parse_chapter_value(self, value: str | None) -> float | None:
        if not value:
            return None
        try:
            return float(value)
        except ValueError:
            return None

    def _serialize_chapter(self, chapter: Chapter) -> dict:
        number_text = chapter.number_text
        if not number_text and chapter.number is not None:
            number_text = format_chapter_number(chapter.number)

        return {
            "url": chapter.url,
            "label": f"Capitulo {number_text}" if number_text else chapter.label,
            "number": chapter.number,
            "number_text": number_text,
            "chapter_id": chapter.chapter_id,
            "title": chapter.title,
        }

    def _is_chapter_url(self, url: str) -> bool:
        return (
            "mangafire.to/" in url
            and "/read/" in url
            and chapter_number_from_url(url) is not None
        )

    def _find_neighbors(self, chapters: list[Chapter], current_url: str) -> tuple[str | None, str | None]:
        if not chapters:
            return None, None

        current_number = chapter_number_from_url(current_url)
        current_path = urlparse(current_url).path.rstrip("/")
        toomics_parts = self._toomics_chapter_parts(current_url)
        mangalivre_slug = self._mangalivre_chapter_slug_from_source(current_url)
        mangakatana_parts = self._mangakatana_chapter_parts(current_url)
        current_mangadex_id = self._mangadex_chapter_id_from_source(current_url)
        current_pieceproject = self._pieceproject_chapter_number_from_source(current_url)
        readfull_parts = self._readfull_chapter_parts(current_url)
        noveltoon_parts = self._noveltoon_chapter_parts(current_url)
        current_external_id = (
            (f"toomics:{toomics_parts[1]}:{toomics_parts[2]}:{toomics_parts[3]}" if toomics_parts else None)
            or (f"mangalivre:{mangalivre_slug}" if mangalivre_slug else None)
            or (f"mangakatana:{mangakatana_parts[0]}:{mangakatana_parts[1]}" if mangakatana_parts else None)
            or current_mangadex_id
            or (f"pieceproject:{current_pieceproject}" if current_pieceproject else None)
            or (readfull_parts[1] if readfull_parts else None)
            or (noveltoon_parts[2] if noveltoon_parts else None)
        )
        if current_number is None:
            current_number = self._parse_chapter_value(self._mangalivre_chapter_number_from_slug(mangalivre_slug))
        current_index: int | None = None

        for index, chapter in enumerate(chapters):
            chapter_path = urlparse(chapter.url).path.rstrip("/")
            same_url = chapter.url == current_url or chapter_path == current_path
            same_id = bool(current_external_id and chapter.chapter_id == current_external_id)
            same_number = (
                current_number is not None
                and chapter.number is not None
                and abs(chapter.number - current_number) < 0.0001
            )
            if same_url or same_id or same_number:
                current_index = index
                break

        if current_index is None:
            return None, None

        previous_url = chapters[current_index - 1].url if current_index > 0 else None
        next_url = chapters[current_index + 1].url if current_index + 1 < len(chapters) else None
        return previous_url, next_url

    def _chapter_label(self, url: str) -> str:
        if self._is_toomics_source(url):
            return self._toomics_chapter_label(url)
        if self._is_mangalivre_source(url):
            return self._mangalivre_chapter_label(url)
        if self._is_mangakatana_source(url):
            return self._mangakatana_chapter_label(url)
        if self._is_dragontea_source(url):
            return self._dragontea_label_from_url(url)
        slug = slug_from_url(url) or "mangafire"
        number = chapter_number_text_from_url(url) or str(int(time.time()))
        return clean_filename(f"{slug}-chapter-{number}")


class ReaderHandler(BaseHTTPRequestHandler):
    reader: MangaFireReader

    def log_message(self, format: str, *args) -> None:
        return

    def do_GET(self) -> None:
        parsed = urlparse(self.path)

        if parsed.path == "/":
            self._send_bytes(INDEX_HTML.encode("utf-8"), "text/html; charset=utf-8")
            return

        if parsed.path == "/api/v1/search":
            query = parse_qs(parsed.query)
            keyword = self._query_value(query, "q")
            limit = self._query_int(query, "limit", 12)
            provider = self._query_value(query, "provider", "mangalivre").lower()
            if provider == "mangadex":
                self._handle_json(lambda: self.reader.search_mangadex(keyword, limit=limit))
            elif provider == "pieceproject":
                self._handle_json(lambda: self.reader.search_pieceproject(keyword, limit=limit))
            elif provider == "readfull":
                self._handle_json(lambda: self.reader.search_readfull(keyword, limit=limit))
            elif provider == "noveltoon":
                lang = self._query_value(query, "lang", "en") or "en"
                self._handle_json(lambda: self.reader.search_noveltoon(keyword, limit=limit, lang=lang))
            elif provider == "toomics":
                lang = self._query_value(query, "lang", "en") or "en"
                self._handle_json(lambda: self.reader.search_toomics(keyword, limit=limit, lang=lang))
            elif provider == "mangalivre":
                self._handle_json(lambda: self.reader.search_mangalivre(keyword, limit=limit))
            elif provider == "mangasbrasuka":
                self._handle_json(lambda: self.reader.search_mangasbrasuka(keyword, limit=limit))
            elif provider == "mangakatana":
                self._handle_json(lambda: self.reader.search_mangakatana(keyword, limit=limit))
            else:
                self._handle_json(lambda: self.reader.search_manga(keyword, limit=limit))
            return

        if parsed.path == "/api/v1/manga":
            query = parse_qs(parsed.query)
            url = self._query_value(query, "url")
            lang = self._query_value(query, "lang", "pt-br") or "pt-br"
            chapter = self._query_value(query, "chapter") or None
            include_chapters = self._query_bool(query, "chapters", True)
            self._handle_json(
                lambda: self.reader.manga_metadata(
                    url,
                    lang,
                    chapter,
                    include_chapters,
                )
            )
            return

        if parsed.path == "/api/v1/chapters":
            query = parse_qs(parsed.query)
            url = self._query_value(query, "url")
            lang = self._query_value(query, "lang", "pt-br") or "pt-br"
            chapter = self._query_value(query, "chapter") or None
            self._handle_json(lambda: self.reader.list_chapters(url, lang, chapter))
            return

        if parsed.path == "/api/v1/chapter":
            query = parse_qs(parsed.query)
            url = self._query_value(query, "url")
            cache_pages = self._query_bool(query, "cache", False)
            include_source = self._query_bool(query, "source", False)
            self._handle_json(
                lambda: self.reader.chapter_metadata(
                    url,
                    cache_pages=cache_pages,
                    include_source_urls=include_source,
                )
            )
            return

        if parsed.path == "/api/v1/current-chapter":
            query = parse_qs(parsed.query)
            cache_pages = self._query_bool(query, "cache", False)
            include_source = self._query_bool(query, "source", False)
            self._handle_json(
                lambda: self.reader.current_chapter_metadata(
                    cache_pages=cache_pages,
                    include_source_urls=include_source,
                )
            )
            return

        if parsed.path.startswith("/api/v1/image/"):
            try:
                index = int(parsed.path.rsplit("/", 1)[-1])
                path, content_type = self.reader.get_image(index)
                self._send_file(path, content_type)
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.NOT_FOUND)
            return

        if parsed.path == "/api/load":
            query = parse_qs(parsed.query)
            url = (query.get("url") or [""])[0].strip()
            lang = (query.get("lang") or ["pt-br"])[0].strip() or "pt-br"
            chapter = (query.get("chapter") or [""])[0].strip() or None
            self._handle_json(lambda: self.reader.load_source(url, lang, chapter))
            return

        if parsed.path == "/api/chapters":
            query = parse_qs(parsed.query)
            url = (query.get("url") or [""])[0].strip()
            lang = (query.get("lang") or ["pt-br"])[0].strip() or "pt-br"
            chapter = (query.get("chapter") or [""])[0].strip() or None
            self._handle_json(lambda: self.reader.list_chapters(url, lang, chapter))
            return

        if parsed.path == "/api/search":
            query = parse_qs(parsed.query)
            keyword = (query.get("q") or [""])[0].strip()
            self._handle_json(lambda: self.reader.search_manga(keyword))
            return

        if parsed.path.startswith("/api/image/"):
            try:
                index = int(parsed.path.rsplit("/", 1)[-1])
                path, content_type = self.reader.get_image(index)
                self._send_file(path, content_type)
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.NOT_FOUND)
            return

        if parsed.path.startswith("/cache/"):
            try:
                path, content_type = self.reader.cache_path(parsed.path.removeprefix("/cache/"))
                self._send_file(path, content_type)
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.NOT_FOUND)
            return

        self._send_json({"ok": False, "error": "Rota nao encontrada."}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)

        if parsed.path in {"/api/close", "/api/v1/close"}:
            self.reader.close_chapter()
            self._send_json({"ok": True})
            return

        if parsed.path in {"/api/shutdown", "/api/v1/shutdown"}:
            self.reader.close()
            self._send_json({"ok": True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return

        self._send_json({"ok": False, "error": "Rota nao encontrada."}, HTTPStatus.NOT_FOUND)

    def _handle_json(self, action) -> None:
        try:
            payload = action()
            self._send_json(payload)
        except Exception as exc:
            self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def _send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send_bytes(data, "application/json; charset=utf-8", status)

    def _query_value(self, query: dict, name: str, default: str = "") -> str:
        return (query.get(name) or [default])[0].strip()

    def _query_int(self, query: dict, name: str, default: int) -> int:
        raw = self._query_value(query, name, str(default))
        try:
            return max(1, int(raw))
        except ValueError:
            return default

    def _query_bool(self, query: dict, name: str, default: bool = False) -> bool:
        raw = self._query_value(query, name, "1" if default else "0").lower()
        return raw in {"1", "true", "yes", "sim", "on"}

    def _send_file(self, path: Path, content_type: str) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(path.stat().st_size))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        with path.open("rb") as handle:
            shutil.copyfileobj(handle, self.wfile)

    def _send_bytes(
        self,
        data: bytes,
        content_type: str,
        status: HTTPStatus = HTTPStatus.OK,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Leitor local de mangas com cache temporaria por capitulo."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--librewolf-path", default=None, metavar="PATH")
    parser.add_argument("--show-browser", action="store_true")
    parser.add_argument("--timeout", type=int, default=45)
    parser.add_argument(
        "--dragontea-browser",
        choices=("edge", "chrome", "chromium", "firefox"),
        default="edge",
        help="Navegador usado para resolver imagens do DragonTea. Padrao: edge",
    )
    parser.add_argument(
        "--readfull-api-url",
        default=os.environ.get("READFULL_API_URL", DEFAULT_READFULL_API_URL),
        help="URL base da API ReadFull/NovelFull. Padrao: https://readfullapi.herokuapp.com",
    )
    parser.add_argument(
        "--noveltoon-base-url",
        default=os.environ.get("NOVELTOON_BASE_URL", DEFAULT_NOVELTOON_BASE_URL),
        help="URL base do NovelToon. Padrao: https://noveltoon.mobi",
    )
    parser.add_argument(
        "--mangalivre-base-url",
        default=os.environ.get("MANGALIVRE_BASE_URL", DEFAULT_MANGALIVRE_BASE_URL),
        help="URL base do MangaLivre. Padrao: https://mangalivre.blog",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    reader = MangaFireReader(args)

    ReaderHandler.reader = reader
    server = ThreadingHTTPServer((args.host, args.port), ReaderHandler)

    try:
        print(f"Leitor temporario aberto em: http://{args.host}:{args.port}")
        print("Ctrl+C fecha o servidor e apaga qualquer cache restante.")
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nFechando leitor...")
    finally:
        server.server_close()
        reader.close()


if __name__ == "__main__":
    main()
