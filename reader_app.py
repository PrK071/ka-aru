from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import json
import queue
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import customtkinter as ctk
import requests
from PIL import Image, ImageOps, ImageTk

from reader_server import (
    DEFAULT_PIECEPROJECT_URL,
    DEFAULT_READFULL_API_URL,
    MangaReader,
    fuzzy_match_score,
    normalize_match_text,
)


APP_DIR = Path(__file__).resolve().parent
SITES_FILE = APP_DIR / "reader_sites.json"
LOG_FILE = APP_DIR / "reader_app.log"
HOME_CACHE_DIR = APP_DIR / ".reader_home_cache"
HOME_METADATA_CACHE_FILE = HOME_CACHE_DIR / "catalog.json"
HOME_TRENDING_CACHE_FILE = HOME_CACHE_DIR / "trending.json"
HOME_MANGADEX_CACHE_FILE = HOME_CACHE_DIR / "mangadex_catalog.json"
HOME_ANILIST_CACHE_FILE = HOME_CACHE_DIR / "anilist_metadata.json"
HOME_COVER_CACHE_DIR = HOME_CACHE_DIR / "covers"
HOME_CACHE_VERSION = 4
HOME_TRENDING_CACHE_VERSION = 1
HOME_MANGADEX_CACHE_VERSION = 1
HOME_ANILIST_CACHE_VERSION = 1

APP_BG = "#050506"
SIDEBAR_BG = "#09090b"
PANEL_BG = "#0d0d10"
PANEL_SOFT = "#141417"
INPUT_BG = "#101114"
CANVAS_BG = "#000000"
BORDER = "#242428"
TEXT = "#f4f4f5"
MUTED = "#9a9aa1"
MUTED_DARK = "#66666d"
HOVER = "#202024"
PRIMARY = "#f5f5f5"
PRIMARY_HOVER = "#d9d9dc"
ACCENT = "#3f7f68"
ACCENT_HOVER = "#4b9479"
DANGER = "#1b1012"
DANGER_HOVER = "#2b161a"
PAGE_DOWNLOAD_WORKERS = 6
PAGE_QUEUE_BATCH = 6
PAGE_PLACEHOLDER_MIN_HEIGHT = 900
LAZY_PRELOAD_PIXELS = 6000
LAZY_PRELOAD_PAGES = 5
HOME_SCROLL_PIXELS = 168
HOME_SCROLL_UNITS = 1
READER_SCROLL_UNITS = 7
READER_LAYOUT_DELAY_MS = 90
HOME_CARD_WIDTH = 176
HOME_COVER_WIDTH = 152
HOME_COVER_HEIGHT = 218
HOME_COLUMNS = 4
HOME_SECTION_LIMIT = 8
HOME_MANGADEX_SECTION_LIMIT = 6
HOME_CACHE_MAX_AGE_SECONDS = 24 * 60 * 60
HOME_TRENDING_CACHE_MAX_AGE_SECONDS = 24 * 60 * 60
HOME_MANGADEX_CACHE_MAX_AGE_SECONDS = 24 * 60 * 60
HOME_ANILIST_CACHE_MAX_AGE_SECONDS = 24 * 60 * 60
HOME_CHARACTER_IMAGE_SIZE = 70

HOME_SECTIONS = ["Em alta agora", "Ação", "Aventura", "Fantasia", "Comédia", "Romance", "Terror"]
HOME_MANGADEX_GENRES = {
    "Ação": "Action",
    "Aventura": "Adventure",
    "Fantasia": "Fantasy",
    "Comédia": "Comedy",
    "Romance": "Romance",
    "Terror": "Horror",
}
HOME_GENRE_LABELS = {
    "acao": "Ação",
    "action": "Ação",
    "adventure": "Aventura",
    "aventura": "Aventura",
    "comedia": "Comédia",
    "comedy": "Comédia",
    "fantasia": "Fantasia",
    "fantasy": "Fantasia",
    "horror": "Terror",
    "romance": "Romance",
    "terror": "Terror",
}
HOME_BLOCKED_TERMS = {
    "18",
    "18+",
    "adult",
    "doujinshi",
    "ecchi",
    "erotic",
    "erotica",
    "hentai",
    "mature",
    "nsfw",
    "pornographic",
    "sexual",
        "smut",
}
ANILIST_STATUS_LABELS = {
    "FINISHED": "Finalizado",
    "RELEASING": "Em publicacao",
    "NOT_YET_RELEASED": "Nao lancado",
    "CANCELLED": "Cancelado",
    "HIATUS": "Hiato",
}
ANILIST_FORMAT_LABELS = {
    "MANGA": "Manga",
    "NOVEL": "Novel",
    "ONE_SHOT": "One-shot",
}
HOME_CATALOG = [
    {
        "title": "Jogador: Respawn",
        "query": "Jogador Respawn",
        "url": "https://global.toomics.com/por/webtoon/episode/toon/7869",
        "provider": "toomics",
        "section": "Fantasia",
        "genres": ["Ação", "Fantasia"],
    },
    {
        "title": "Minha Vida de Jogador",
        "query": "Minha Vida de Jogador",
        "url": "https://global.toomics.com/por/webtoon/episode/toon/7889",
        "provider": "toomics",
        "section": "Aventura",
        "genres": ["Ação", "Aventura"],
    },
    {
        "title": "Soul Eater",
        "query": "Soul Eater",
        "provider": "mangalivre",
        "section": "Ação",
        "genres": ["Ação", "Fantasia", "Comédia"],
    },
    {
        "title": "Tensei Shitara Slime Datta Ken",
        "query": "Tensei Shitara Slime Datta Ken",
        "url": "https://mangasbrasuka.com.br/manga/tensei-shitara-slime-datta-ken/",
        "provider": "mangasbrasuka",
        "section": "Fantasia",
        "genres": ["Aventura", "Fantasia", "Comédia"],
    },
    {
        "title": "Chainsaw Man",
        "query": "Chainsaw Man",
        "provider": "mangadex",
        "section": "Terror",
        "genres": ["Ação", "Terror"],
    },
    {
        "title": "Jujutsu Kaisen",
        "query": "Jujutsu Kaisen",
        "provider": "mangadex",
        "section": "Ação",
        "genres": ["Ação", "Fantasia", "Terror"],
    },
    {
        "title": "One Piece",
        "query": "One Piece",
        "url": "pieceproject://one-piece",
        "provider": "pieceproject",
        "section": "Aventura",
        "genres": ["Ação", "Aventura", "Comédia"],
    },
    {
        "title": "Berserk",
        "query": "Berserk",
        "provider": "mangadex",
        "section": "Fantasia",
        "genres": ["Ação", "Fantasia", "Terror"],
    },
    {
        "title": "Kaguya-sama: Love Is War",
        "query": "Kaguya-sama Love Is War",
        "provider": "mangadex",
        "section": "Comédia",
        "genres": ["Comédia", "Romance"],
    },
    {
        "title": "Solo Leveling",
        "query": "Solo Leveling",
        "provider": "mangadex",
        "section": "Aventura",
        "genres": ["Ação", "Aventura", "Fantasia"],
    },
    {
        "title": "Horimiya",
        "query": "Horimiya",
        "provider": "mangadex",
        "section": "Romance",
        "genres": ["Romance", "Comédia"],
    },
]

DEFAULT_SITES = {
    "sites": [
        {
            "name": "MangasBrasuka",
            "kind": "mangasbrasuka",
            "base_url": "https://mangasbrasuka.com.br",
            "manga_url_template": "https://mangasbrasuka.com.br/manga/{slug}",
            "default_lang": "pt-br",
        },
        {
            "name": "MangaLivre",
            "kind": "mangalivre",
            "base_url": "https://mangalivre.blog",
            "manga_url_template": "https://mangalivre.blog/manga/{slug}",
            "default_lang": "pt-br",
        },
        {
            "name": "MangaDex",
            "kind": "mangadex",
            "base_url": "https://mangadex.org",
            "manga_url_template": "https://mangadex.org/title/{slug}",
            "default_lang": "pt-br",
        },
        {
            "name": "One Piece Project",
            "kind": "pieceproject",
            "base_url": DEFAULT_PIECEPROJECT_URL,
            "manga_url_template": "pieceproject://one-piece",
            "default_lang": "pt-br",
        },
        {
            "name": "DragonTea",
            "kind": "dragontea",
            "base_url": "https://dragontea.ink",
            "manga_url_template": "https://dragontea.ink/{slug}",
            "default_lang": "pt-br",
        },
        {
            "name": "Toomics",
            "kind": "toomics",
            "base_url": "https://global.toomics.com",
            "manga_url_template": "https://global.toomics.com/por/webtoon/episode/toon/{slug}",
            "default_lang": "pt-br",
        },
        {
            "name": "MangaKatana",
            "kind": "mangakatana",
            "base_url": "https://mangakatana.com",
            "manga_url_template": "https://mangakatana.com/manga/{slug}",
            "default_lang": "en",
        },
        {
            "name": "ReadFull",
            "kind": "readfull",
            "base_url": DEFAULT_READFULL_API_URL,
            "manga_url_template": "readfull://novel/{slug}",
            "default_lang": "en",
        }
    ]
}

LEGACY_SITE_KINDS = {"noveltoon"}
UNSUPPORTED_RACE_KINDS = {"noveltoon", "dragontea"}
SEARCH_RACE_MAX_WORKERS = 6
MIN_RACE_RELEVANCE = 0.48
PIECEPROJECT_RACE_RELEVANCE = 0.55
SPARSE_CHAPTER_THRESHOLD = 8
SOURCE_RELIABILITY = {
    "mangalivre": 0.94,
    "mangasbrasuka": 0.92,
    "pieceproject": 0.95,
    "readfull": 0.82,
    "mangakatana": 0.86,
    "toomics": 0.78,
    "mangadex": 0.72,
    "dragontea": 0.55,
}
MANGALIVRE_PREFERRED_RELEVANCE = 0.96
MANGALIVRE_PREFERRED_MIN_CHAPTERS = 20
RACE_RELEVANCE_WEIGHT = 0.52
RACE_RELIABILITY_WEIGHT = 0.22
RACE_COMPLETENESS_WEIGHT = 0.10
RACE_LANGUAGE_WEIGHT = 0.16
RACE_MAX_SPEED_PENALTY = 0.06


@dataclass(frozen=True)
class _SiteRaceHit:
    site: dict
    elapsed: float
    search_payload: dict
    resolved_url: str
    relevance: float
    reliability: float
    completeness: float
    language_fit: float
    score: float
    chapters_payload: dict | None = None


def load_sites() -> list[dict]:
    if not SITES_FILE.exists():
        SITES_FILE.write_text(
            json.dumps(DEFAULT_SITES, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    try:
        data = json.loads(SITES_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        data = DEFAULT_SITES

    sites = [
        site
        for site in (data.get("sites") or DEFAULT_SITES["sites"])
        if site.get("name") and site.get("kind") not in LEGACY_SITE_KINDS
    ]
    names = {site.get("name") for site in sites}
    for default_site in DEFAULT_SITES["sites"]:
        if default_site["name"] not in names:
            sites.append(default_site)
    return sites


class ReaderApp(ctk.CTk):
    def __init__(self, args: argparse.Namespace) -> None:
        super().__init__()

        self.title("MangaTemp")
        self.geometry("1180x820")
        self.minsize(980, 680)

        self.sites = load_sites()
        self.site_by_name = {site["name"]: site for site in self.sites}
        self.active_site = next(
            (
                site
                for site in self.sites
                if site.get("kind") not in UNSUPPORTED_RACE_KINDS
            ),
            self.sites[0],
        )
        self.reader = MangaReader(
            SimpleNamespace(
                librewolf_path=args.librewolf_path,
                show_browser=args.show_browser,
                timeout=args.timeout,
                readfull_api_url=args.readfull_api_url,
                dragontea_browser=args.dragontea_browser,
            )
        )

        self.chapter_by_label: dict[str, str] = {}
        self.search_result_by_label: dict[str, str] = {}
        self.current_data: dict | None = None
        self.loading = False
        self.sidebar_visible = False
        self._auto_fetch_after_id: str | None = None
        self._last_chapter_fetch_key: tuple[str, str] | None = None
        self.resize_after_id: str | None = None
        self._page_images: list[ImageTk.PhotoImage | None] = []
        self._page_paths: list[str] = []
        self._page_errors: list[str | None] = []
        self._page_heights: list[int] = []
        self._load_thread: threading.Thread | None = None
        self._load_cancel = threading.Event()
        self._page_queue: queue.Queue[tuple[str, int, object]] | None = None
        self._pages_loaded = 0
        self._lazy_requested_pages: set[int] = set()
        self._lazy_inflight_pages: set[int] = set()
        self._lazy_after_id: str | None = None
        self._page_layout_after_id: str | None = None
        self._pending_page_anchor: tuple[int, int] | None = None
        self._reader_scroll_active_until = 0.0
        HOME_COVER_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self._home_cache_fresh = False
        self.home_catalog: list[dict] = self._load_cached_home_catalog()
        self.home_trending, self._home_trending_cache_fresh = self._load_cached_home_trending()
        self.home_mangadex_catalog, self._home_mangadex_cache_fresh = (
            self._load_cached_home_mangadex_catalog()
        )
        self.home_results: list[dict] = []
        self.home_view = "catalog"
        self._home_cover_images: dict[str, ctk.CTkImage] = {}
        self._home_cover_labels: dict[str, list] = {}
        self._home_cover_inflight: set[str] = set()
        self._home_character_images: dict[str, ctk.CTkImage] = {}
        self._home_character_labels: dict[str, list] = {}
        self._home_character_inflight: set[str] = set()
        self._home_poster_inflight: set[str] = set()
        self._anilist_cache = self._load_anilist_cache()
        self._home_catalog_loading = False
        self._home_search_generation = 0
        self._home_scroll_active_until = 0.0
        self._home_scrollbar_dragging = False
        self._home_render_after_id: str | None = None

        self._build_ui()
        self._apply_site_defaults()
        # Renderiza imediatamente com o cache disponível (sem esperar rede)
        self.after(50, self._show_catalog_view)
        self.after(100, self._load_home_catalog)          # Catalog local/cache — mais rapido
        self.after(1500, self._load_home_trending)        # Trending MangaDex — aguarda catalog
        self.after(2500, self._load_home_mangadex_catalog)  # Catalog MangaDex — por ultimo
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def _build_ui(self) -> None:
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")
        self.configure(fg_color=APP_BG)

        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.sidebar = ctk.CTkFrame(
            self,
            width=300,
            corner_radius=0,
            fg_color=SIDEBAR_BG,
            border_width=1,
            border_color=BORDER,
        )
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_columnconfigure(0, weight=1)

        self.reader_area = ctk.CTkFrame(self, corner_radius=0, fg_color=APP_BG)
        self.reader_area.grid(row=0, column=0, columnspan=2, sticky="nsew")
        self.reader_area.grid_columnconfigure(0, weight=1)
        self.reader_area.grid_rowconfigure(1, weight=1)

        self._build_sidebar()
        self._build_reader()
        self._build_home()
        self.bind_all("<MouseWheel>", self._on_global_mousewheel)
        self.bind_all("<Button-4>", self._on_global_mousewheel)
        self.bind_all("<Button-5>", self._on_global_mousewheel)
        self._apply_visual_style()
        self._set_sidebar_visible(False)
        self._show_home_view()

    def _apply_visual_style(self) -> None:
        entries = [self.search_entry, self.manga_entry, self.lang_entry]
        for entry in entries:
            entry.configure(
                fg_color=INPUT_BG,
                border_color=BORDER,
                text_color=TEXT,
                placeholder_text_color=MUTED_DARK,
                corner_radius=6,
                border_width=1,
            )

        menus = [self.search_menu, self.chapter_menu]
        for menu in menus:
            menu.configure(
                fg_color=INPUT_BG,
                button_color=PANEL_SOFT,
                button_hover_color=HOVER,
                dropdown_fg_color=PANEL_BG,
                dropdown_hover_color=HOVER,
                dropdown_text_color=TEXT,
                text_color=TEXT,
                corner_radius=6,
            )

        secondary_buttons = [
            self.search_button,
            self.fetch_button,
            self.prev_chapter_button,
            self.next_chapter_button,
            self.top_prev_button,
            self.top_next_button,
        ]
        for button in secondary_buttons:
            button.configure(
                fg_color=PANEL_SOFT,
                hover_color=HOVER,
                border_width=1,
                border_color=BORDER,
                text_color=TEXT,
                corner_radius=6,
            )

        self.open_button.configure(
            fg_color=PRIMARY,
            hover_color=PRIMARY_HOVER,
            text_color=APP_BG,
            corner_radius=6,
            border_width=0,
        )
        self.close_chapter_button.configure(
            fg_color=DANGER,
            hover_color=DANGER_HOVER,
            border_width=1,
            border_color="#3a1c22",
            text_color="#f6d6dc",
            corner_radius=6,
        )
        self.top_close_button.configure(
            fg_color=DANGER,
            hover_color=DANGER_HOVER,
            border_width=1,
            border_color="#3a1c22",
            text_color="#f6d6dc",
            corner_radius=6,
        )
        self.fit_switch.configure(
            text_color=TEXT,
            progress_color=PRIMARY,
            button_color=TEXT,
            button_hover_color=PRIMARY_HOVER,
            fg_color=PANEL_SOFT,
        )
        self.status_label.configure(text_color=MUTED)
        self.progress.configure(fg_color=PANEL_SOFT, progress_color=PRIMARY)
        self.header_label.configure(text_color=TEXT)
        self.home_button.configure(
            fg_color=PANEL_SOFT,
            hover_color=HOVER,
            border_width=1,
            border_color=BORDER,
            text_color=TEXT,
            corner_radius=6,
        )
        self.global_search_entry.configure(
            fg_color=INPUT_BG,
            border_color=BORDER,
            text_color=TEXT,
            placeholder_text_color=MUTED_DARK,
            corner_radius=6,
            border_width=1,
        )
        self.global_search_button.configure(
            fg_color=PRIMARY,
            hover_color=PRIMARY_HOVER,
            text_color=APP_BG,
            corner_radius=6,
        )

    def _toggle_sidebar(self) -> None:
        self._show_catalog_view()

    def _set_sidebar_visible(self, visible: bool) -> None:
        self.sidebar_visible = False
        self.sidebar.grid_remove()
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=0)
        self.reader_area.grid(row=0, column=0, columnspan=2, sticky="nsew")
        if self.resize_after_id:
            self.after_cancel(self.resize_after_id)
        self.resize_after_id = self.after(80, self._resize_image_pages)

    def _build_sidebar(self) -> None:
        title = ctk.CTkLabel(
            self.sidebar,
            text="MangaTemp",
            font=ctk.CTkFont(size=18, weight="bold"),
            anchor="w",
            text_color=TEXT,
        )
        title.grid(row=0, column=0, padx=18, pady=(18, 2), sticky="ew")

        subtitle = ctk.CTkLabel(
            self.sidebar,
            text="Cache temporaria por capitulo",
            font=ctk.CTkFont(size=11),
            anchor="w",
            text_color=MUTED_DARK,
        )
        subtitle.grid(row=1, column=0, padx=18, pady=(0, 14), sticky="ew")

        ctk.CTkLabel(self.sidebar, text="Fonte (automatica)", anchor="w", text_color=MUTED).grid(
            row=2, column=0, padx=18, pady=(6, 4), sticky="ew"
        )
        self.site_label = ctk.CTkLabel(
            self.sidebar,
            text="Auto: aguardando busca...",
            anchor="w",
            text_color=TEXT,
            fg_color=INPUT_BG,
            corner_radius=6,
            height=32,
        )
        self.site_label.grid(row=3, column=0, padx=18, sticky="ew")

        ctk.CTkLabel(self.sidebar, text="Buscar manga por nome", anchor="w", text_color=MUTED).grid(
            row=4, column=0, padx=18, pady=(14, 4), sticky="ew"
        )
        search_row = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        search_row.grid(row=5, column=0, padx=18, sticky="ew")
        search_row.grid_columnconfigure(0, weight=1)
        self.search_entry = ctk.CTkEntry(search_row, placeholder_text="Chainsaw Man")
        self.search_entry.grid(row=0, column=0, sticky="ew")
        self.search_entry.bind("<Return>", lambda _event: self.search_manga())
        self.search_button = ctk.CTkButton(
            search_row,
            width=72,
            text="Buscar",
            command=self.search_manga,
        )
        self.search_button.grid(row=0, column=1, padx=(8, 0), sticky="ew")

        ctk.CTkLabel(self.sidebar, text="Resultado", anchor="w", text_color=MUTED).grid(
            row=6, column=0, padx=18, pady=(10, 4), sticky="ew"
        )
        self.search_menu = ctk.CTkOptionMenu(
            self.sidebar,
            values=["Nenhum resultado"],
            command=self.on_search_selected,
        )
        self.search_menu.grid(row=7, column=0, padx=18, sticky="ew")

        ctk.CTkLabel(self.sidebar, text="Manga, slug ou URL", anchor="w", text_color=MUTED).grid(
            row=8, column=0, padx=18, pady=(14, 4), sticky="ew"
        )
        self.manga_entry = ctk.CTkEntry(
            self.sidebar,
            placeholder_text="soul-eaterr.2z2",
        )
        self.manga_entry.grid(row=9, column=0, padx=18, sticky="ew")
        self.manga_entry.bind("<Return>", lambda _event: self.open_selected())
        self.manga_entry.bind("<KeyRelease>", self._schedule_auto_fetch_chapters)

        ctk.CTkLabel(self.sidebar, text="Idioma", anchor="w", text_color=MUTED).grid(
            row=10, column=0, padx=18, pady=(12, 4), sticky="ew"
        )
        self.lang_entry = ctk.CTkEntry(self.sidebar)
        self.lang_entry.grid(row=11, column=0, padx=18, sticky="ew")
        self.lang_entry.bind("<KeyRelease>", self._schedule_auto_fetch_chapters)

        self.fetch_button = ctk.CTkButton(
            self.sidebar,
            text="Buscar capitulos",
            command=self.fetch_chapters,
        )

        ctk.CTkLabel(self.sidebar, text="Capitulo", anchor="w", text_color=MUTED).grid(
            row=12, column=0, padx=18, pady=(14, 4), sticky="ew"
        )
        self.chapter_menu = ctk.CTkOptionMenu(
            self.sidebar,
            values=["Nenhum capitulo"],
            command=lambda _value: None,
        )
        self.chapter_menu.grid(row=13, column=0, padx=18, sticky="ew")

        self.open_button = ctk.CTkButton(
            self.sidebar,
            text="Abrir no leitor",
            command=self.open_selected,
        )
        self.open_button.grid(row=14, column=0, padx=18, pady=(14, 8), sticky="ew")

        chapter_nav = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        chapter_nav.grid(row=15, column=0, padx=18, pady=(4, 0), sticky="ew")
        chapter_nav.grid_columnconfigure((0, 1), weight=1)

        self.prev_chapter_button = ctk.CTkButton(
            chapter_nav,
            text="Cap. anterior",
            command=self.open_previous_chapter,
            state="disabled",
        )
        self.prev_chapter_button.grid(row=0, column=0, padx=(0, 5), sticky="ew")
        self.next_chapter_button = ctk.CTkButton(
            chapter_nav,
            text="Proximo cap.",
            command=self.open_next_chapter,
            state="disabled",
        )
        self.next_chapter_button.grid(row=0, column=1, padx=(5, 0), sticky="ew")

        self.fit_switch = ctk.CTkSwitch(
            self.sidebar,
            text="Ajustar na largura",
            command=self._rerender_all_pages,
        )
        self.fit_switch.grid(row=16, column=0, padx=18, pady=(16, 0), sticky="w")
        self.fit_switch.select()

        self.close_chapter_button = ctk.CTkButton(
            self.sidebar,
            text="Sair do capitulo e apagar cache",
            fg_color="#6b1f2a",
            hover_color="#842937",
            command=self.close_chapter,
        )
        self.close_chapter_button.grid(row=18, column=0, padx=18, pady=(18, 8), sticky="ew")

        self.status_label = ctk.CTkLabel(
            self.sidebar,
            text="Escolha um site salvo e informe o manga.",
            anchor="w",
            justify="left",
            wraplength=260,
        )
        self.status_label.grid(row=19, column=0, padx=18, pady=(12, 8), sticky="ew")

        self.progress = ctk.CTkProgressBar(self.sidebar, mode="indeterminate")
        self.progress.grid(row=20, column=0, padx=18, pady=(4, 18), sticky="ew")
        self.progress.set(0)

    def _build_reader(self) -> None:
        self.topbar = ctk.CTkFrame(
            self.reader_area,
            fg_color=PANEL_BG,
            border_width=1,
            border_color=BORDER,
            corner_radius=6,
        )
        self.topbar.grid(row=0, column=0, padx=18, pady=(10, 8), sticky="ew")
        self.topbar.grid_columnconfigure(0, weight=0)
        self.topbar.grid_columnconfigure(1, weight=1)
        self.topbar.grid_columnconfigure(2, weight=0)
        self.topbar.grid_columnconfigure(3, weight=0)
        self.topbar.grid_columnconfigure(4, weight=0)

        self.home_button = ctk.CTkButton(
            self.topbar,
            text="Início",
            width=68,
            command=self._show_catalog_view,
        )
        self.home_button.grid(row=0, column=0, padx=(12, 12), pady=10, sticky="w")

        self.global_search_entry = ctk.CTkEntry(
            self.topbar,
            placeholder_text="Buscar mangá, manhwa ou novel",
            height=34,
        )
        self.global_search_entry.grid(row=0, column=1, padx=(0, 8), pady=10, sticky="ew")
        self.global_search_entry.bind("<Return>", lambda _event: self.platform_search())

        self.global_search_button = ctk.CTkButton(
            self.topbar,
            text="Buscar",
            width=76,
            height=34,
            command=self.platform_search,
        )
        self.global_search_button.grid(row=0, column=2, padx=(0, 12), pady=10, sticky="e")

        self.header_label = ctk.CTkLabel(
            self.topbar,
            text="Biblioteca",
            font=ctk.CTkFont(size=13, weight="bold"),
            anchor="e",
        )
        self.header_label.grid(row=0, column=3, padx=(0, 14), pady=(12, 12), sticky="e")

        self.top_reader_nav = ctk.CTkFrame(self.topbar, fg_color="transparent")
        self.top_reader_nav.grid(row=0, column=4, padx=(0, 12), pady=8, sticky="e")

        self.top_prev_button = ctk.CTkButton(
            self.top_reader_nav,
            text="Anterior",
            width=72,
            height=32,
            state="disabled",
            command=self.open_previous_chapter,
        )
        self.top_prev_button.grid(row=0, column=0, padx=(0, 6))

        self.top_next_button = ctk.CTkButton(
            self.top_reader_nav,
            text="Próximo",
            width=72,
            height=32,
            state="disabled",
            command=self.open_next_chapter,
        )
        self.top_next_button.grid(row=0, column=1, padx=(0, 6))

        self.top_close_button = ctk.CTkButton(
            self.top_reader_nav,
            text="Sair",
            width=58,
            height=32,
            command=self.close_chapter,
        )
        self.top_close_button.grid(row=0, column=2)
        self.top_reader_nav.grid_remove()

        self.reader_shell = ctk.CTkFrame(
            self.reader_area,
            fg_color=CANVAS_BG,
            border_width=1,
            border_color=BORDER,
            corner_radius=8,
        )
        self.reader_shell.grid(row=1, column=0, padx=18, pady=(0, 18), sticky="nsew")
        self.reader_shell.grid_rowconfigure(0, weight=1)
        self.reader_shell.grid_columnconfigure(0, weight=1)

        self.canvas = ctk.CTkCanvas(self.reader_shell, bg=CANVAS_BG, highlightthickness=0)
        self.canvas.grid(row=0, column=0, padx=(1, 0), pady=1, sticky="nsew")

        self.v_scroll = ctk.CTkScrollbar(
            self.reader_shell,
            command=self._on_canvas_yview,
            fg_color=CANVAS_BG,
            button_color=PANEL_SOFT,
            button_hover_color=HOVER,
        )
        self.v_scroll.grid(row=0, column=1, padx=(0, 2), pady=2, sticky="ns")
        self.canvas.configure(yscrollcommand=self.v_scroll.set)
        self.reader_shell.grid_columnconfigure(1, weight=0)

        self.placeholder_item = self.canvas.create_text(
            20,
            20,
            text="Abra um capitulo para comecar.",
            anchor="nw",
            fill=MUTED,
            tags=("placeholder",),
        )
        self._refresh_scrollregion()

        self.canvas.bind("<Configure>", self._on_canvas_resize)
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind("<Button-4>", self._on_mousewheel)
        self.canvas.bind("<Button-5>", self._on_mousewheel)

    def _build_home(self) -> None:
        self.home_area = ctk.CTkFrame(
            self.reader_area,
            fg_color=APP_BG,
            corner_radius=0,
        )
        self.home_area.grid(row=1, column=0, padx=18, pady=(0, 18), sticky="nsew")
        self.home_area.grid_rowconfigure(0, weight=1)
        self.home_area.grid_columnconfigure(0, weight=1)

        self.home_scroll = ctk.CTkScrollableFrame(
            self.home_area,
            fg_color=APP_BG,
            corner_radius=0,
            scrollbar_button_color=PANEL_SOFT,
            scrollbar_button_hover_color=HOVER,
        )
        self.home_scroll.grid(row=0, column=0, sticky="nsew")
        self.home_scroll.grid_columnconfigure(0, weight=1)
        self.home_scroll._parent_canvas.configure(yscrollincrement=0)
        self.home_scroll._scrollbar.configure(command=self._on_home_yview)
        self.home_scroll._parent_canvas.bind("<MouseWheel>", self._on_home_mousewheel)
        self.home_scroll._parent_canvas.bind("<Button-4>", self._on_home_mousewheel)
        self.home_scroll._parent_canvas.bind("<Button-5>", self._on_home_mousewheel)
        self.home_scroll._scrollbar.bind("<ButtonPress-1>", self._begin_home_scrollbar_drag)
        self.home_scroll._scrollbar.bind("<B1-Motion>", self._mark_home_scroll_event)
        self.home_scroll._scrollbar.bind("<ButtonRelease-1>", self._end_home_scrollbar_drag)

        intro = ctk.CTkFrame(
            self.home_scroll,
            fg_color=PANEL_BG,
            border_width=1,
            border_color=BORDER,
            corner_radius=6,
        )
        intro.grid(row=0, column=0, pady=(0, 18), sticky="ew")
        intro.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            intro,
            text="MangaTemp",
            font=ctk.CTkFont(size=28, weight="bold"),
            text_color=TEXT,
            anchor="w",
        ).grid(row=0, column=0, padx=22, pady=(20, 2), sticky="ew")
        ctk.CTkLabel(
            intro,
            text="Sua biblioteca",
            font=ctk.CTkFont(size=12),
            text_color=MUTED,
            anchor="w",
        ).grid(row=1, column=0, padx=22, pady=(0, 18), sticky="ew")

        heading = ctk.CTkFrame(self.home_scroll, fg_color="transparent")
        heading.grid(row=1, column=0, pady=(0, 10), sticky="ew")
        heading.grid_columnconfigure(0, weight=1)
        self.home_title_label = ctk.CTkLabel(
            heading,
            text="Descobrir",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=TEXT,
            anchor="w",
        )
        self.home_title_label.grid(row=0, column=0, sticky="ew")
        self.home_status_label = ctk.CTkLabel(
            heading,
            text="Atualizando catálogo...",
            font=ctk.CTkFont(size=11),
            text_color=MUTED,
            anchor="e",
        )
        self.home_status_label.grid(row=0, column=1, sticky="e")

        self.home_content = ctk.CTkFrame(self.home_scroll, fg_color="transparent")
        self.home_content.grid(row=2, column=0, sticky="ew")
        self.home_content.grid_columnconfigure(0, weight=1)

        self._render_home_sections()

    def _clear_widget_children(self, widget) -> None:
        for child in widget.winfo_children():
            child.destroy()

    def _on_home_mousewheel(self, event):
        self._mark_home_scroll_event()
        if event.num == 4:
            direction = -HOME_SCROLL_UNITS
        elif event.num == 5:
            direction = HOME_SCROLL_UNITS
        else:
            direction = int(-event.delta / 120 * HOME_SCROLL_UNITS)
        if direction:
            self._scroll_home_by_pixels(direction * HOME_SCROLL_PIXELS)
        return "break"

    def _on_global_mousewheel(self, event):
        if self.home_scroll.check_if_master_is_canvas(event.widget):
            return self._on_home_mousewheel(event)
        return None

    def _on_home_yview(self, *args) -> None:
        self._mark_home_scroll_event()
        self.home_scroll._parent_canvas.yview(*args)

    def _scroll_home_by_pixels(self, pixels: int) -> None:
        canvas = self.home_scroll._parent_canvas
        canvas.update_idletasks()
        scrollregion = str(canvas.cget("scrollregion") or "")
        try:
            x0, y0, x1, y1 = [float(part) for part in scrollregion.split()]
            total_height = max(1.0, y1 - y0)
        except (TypeError, ValueError):
            bbox = canvas.bbox("all")
            total_height = float(max(1, (bbox[3] - bbox[1]) if bbox else canvas.winfo_height()))
        visible_height = max(1.0, float(canvas.winfo_height()))
        max_top = max(0.0, total_height - visible_height)
        current_top = min(max_top, max(0.0, canvas.canvasy(0)))
        target_top = min(max_top, max(0.0, current_top + pixels))
        canvas.yview_moveto(target_top / total_height if total_height else 0.0)

    def _begin_home_scrollbar_drag(self, _event=None) -> None:
        self._home_scrollbar_dragging = True
        self._mark_home_scroll_event(active_ms=0.35)

    def _end_home_scrollbar_drag(self, _event=None) -> None:
        self._home_scrollbar_dragging = False
        self._mark_home_scroll_event(active_ms=0.12)

    def _mark_home_scroll_event(self, _event=None, active_ms: float = 0.18) -> None:
        if self._home_scrollbar_dragging:
            active_ms = max(active_ms, 0.22)
        self._home_scroll_active_until = time.monotonic() + active_ms

    def _run_on_ui(self, callback, delay_ms: int = 0) -> bool:
        try:
            self.after(delay_ms, callback)
            return True
        except Exception:
            return False

    def _run_when_home_scroll_idle(self, callback, on_cancel=None) -> bool:
        remaining = self._home_scroll_active_until - time.monotonic()
        if self._home_scrollbar_dragging:
            remaining = max(remaining, 0.12)
        if remaining > 0:
            delay_ms = max(24, int(remaining * 1000))
            return self._run_on_ui(
                lambda: self._run_when_home_scroll_idle(callback, on_cancel),
                delay_ms,
            )
        try:
            callback()
            return True
        except Exception:
            if on_cancel:
                on_cancel()
            return False

    def _schedule_home_sections_render(self, delay_ms: int = 120) -> None:
        if self._home_render_after_id:
            self.after_cancel(self._home_render_after_id)
        self._home_render_after_id = self.after(delay_ms, self._flush_home_sections_render)

    def _flush_home_sections_render(self) -> None:
        self._home_render_after_id = None
        remaining = self._home_scroll_active_until - time.monotonic()
        if remaining > 0:
            self._home_render_after_id = self.after(
                max(20, int(remaining * 1000)),
                self._flush_home_sections_render,
            )
            return
        if self.home_view == "catalog":
            self._render_home_sections()

    def _home_item_key(self, item: dict) -> str:
        return str(item.get("url") or item.get("query") or item.get("title") or "")

    def _home_display_genres(self, item: dict) -> list[str]:
        labels: list[str] = []
        for genre in item.get("genres") or []:
            label = HOME_GENRE_LABELS.get(normalize_match_text(str(genre)))
            if label and label not in labels:
                labels.append(label)
        section = str(item.get("section") or "")
        if section in HOME_SECTIONS[1:] and section not in labels:
            labels.insert(0, section)
        return labels[:3]

    def _home_anilist_for_display(self, item: dict) -> dict:
        metadata = item.get("anilist")
        if isinstance(metadata, dict):
            return metadata
        query = str(item.get("anilist_query") or item.get("query") or item.get("title") or "")
        return self._cached_anilist_metadata(query) or {}

    def _home_score_text(self, item: dict) -> str:
        metadata = self._home_anilist_for_display(item)
        score = metadata.get("average_score") or metadata.get("mean_score")
        try:
            numeric = int(score)
        except (TypeError, ValueError):
            return ""
        return f"{numeric}% AniList"

    def _load_cached_home_catalog(self) -> list[dict]:
        defaults = [dict(item) for item in HOME_CATALOG]
        try:
            cached = json.loads(HOME_METADATA_CACHE_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return defaults
        if not isinstance(cached, dict) or cached.get("version") != HOME_CACHE_VERSION:
            return defaults
        try:
            saved_at = float(cached.get("saved_at") or 0)
        except (TypeError, ValueError):
            saved_at = 0
        self._home_cache_fresh = time.time() - saved_at < HOME_CACHE_MAX_AGE_SECONDS
        cached = cached.get("catalog")
        if not isinstance(cached, list):
            return defaults

        cached_by_query = {
            normalize_match_text(str(item.get("query") or item.get("title") or "")): item
            for item in cached
            if isinstance(item, dict)
        }
        merged: list[dict] = []
        for default in defaults:
            query = str(default.get("query") or default.get("title") or "")
            item = dict(default)
            cached_item = cached_by_query.get(normalize_match_text(query))
            if cached_item and self._home_item_is_safe(cached_item):
                for key in ("url", "poster", "poster_fallbacks", "description", "authors"):
                    if cached_item.get(key):
                        item[key] = cached_item[key]
            merged.append(item)
        return merged

    def _load_cached_home_trending(self) -> tuple[list[dict], bool]:
        try:
            cached = json.loads(HOME_TRENDING_CACHE_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return [], False
        if not isinstance(cached, dict) or cached.get("version") != HOME_TRENDING_CACHE_VERSION:
            return [], False
        try:
            saved_at = float(cached.get("saved_at") or 0)
        except (TypeError, ValueError):
            saved_at = 0
        items = cached.get("items")
        if not isinstance(items, list):
            return [], False
        safe_items = [
            dict(item)
            for item in items
            if isinstance(item, dict) and self._home_item_is_safe(item)
        ][:HOME_SECTION_LIMIT]
        fresh = time.time() - saved_at < HOME_TRENDING_CACHE_MAX_AGE_SECONDS
        return safe_items, fresh

    def _save_home_trending_cache(self) -> None:
        try:
            HOME_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            HOME_TRENDING_CACHE_FILE.write_text(
                json.dumps(
                    {
                        "version": HOME_TRENDING_CACHE_VERSION,
                        "saved_at": time.time(),
                        "items": self.home_trending,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        except OSError:
            pass

    def _load_cached_home_mangadex_catalog(self) -> tuple[dict[str, list[dict]], bool]:
        try:
            cached = json.loads(HOME_MANGADEX_CACHE_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {}, False
        if not isinstance(cached, dict) or cached.get("version") != HOME_MANGADEX_CACHE_VERSION:
            return {}, False
        try:
            saved_at = float(cached.get("saved_at") or 0)
        except (TypeError, ValueError):
            saved_at = 0
        raw_sections = cached.get("sections")
        if not isinstance(raw_sections, dict):
            return {}, False
        sections: dict[str, list[dict]] = {}
        for section in HOME_SECTIONS[1:]:
            items = raw_sections.get(section) or []
            sections[section] = [
                dict(item)
                for item in items
                if isinstance(item, dict) and self._home_item_is_safe(item)
            ][:HOME_MANGADEX_SECTION_LIMIT]
        fresh = time.time() - saved_at < HOME_MANGADEX_CACHE_MAX_AGE_SECONDS
        return sections, fresh

    def _save_home_mangadex_catalog_cache(self) -> None:
        try:
            HOME_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            HOME_MANGADEX_CACHE_FILE.write_text(
                json.dumps(
                    {
                        "version": HOME_MANGADEX_CACHE_VERSION,
                        "saved_at": time.time(),
                        "sections": self.home_mangadex_catalog,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        except OSError:
            pass

    def _load_anilist_cache(self) -> dict[str, dict]:
        try:
            cached = json.loads(HOME_ANILIST_CACHE_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {}
        if not isinstance(cached, dict) or cached.get("version") != HOME_ANILIST_CACHE_VERSION:
            return {}
        items = cached.get("items")
        if not isinstance(items, dict):
            return {}
        return {
            str(key): value
            for key, value in items.items()
            if isinstance(value, dict)
        }

    def _save_anilist_cache(self) -> None:
        try:
            HOME_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            HOME_ANILIST_CACHE_FILE.write_text(
                json.dumps(
                    {
                        "version": HOME_ANILIST_CACHE_VERSION,
                        "saved_at": time.time(),
                        "items": self._anilist_cache,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        except OSError:
            pass

    def _anilist_cache_key(self, query: str) -> str:
        return normalize_match_text(query)

    def _cached_anilist_metadata(self, query: str) -> dict | None:
        key = self._anilist_cache_key(query)
        if not key:
            return None
        entry = self._anilist_cache.get(key)
        if not isinstance(entry, dict):
            return None
        try:
            saved_at = float(entry.get("saved_at") or 0)
        except (TypeError, ValueError):
            saved_at = 0
        if time.time() - saved_at > HOME_ANILIST_CACHE_MAX_AGE_SECONDS:
            return None
        data = entry.get("data")
        return dict(data) if isinstance(data, dict) else None

    def _fetch_anilist_metadata(self, item: dict) -> dict | None:
        query = str(
            item.get("anilist_query")
            or item.get("query")
            or item.get("title")
            or ""
        ).strip()
        if not query:
            return None
        cached = self._cached_anilist_metadata(query)
        if cached:
            return cached
        metadata = self.reader.anilist_metadata(query)
        key = self._anilist_cache_key(query)
        self._anilist_cache[key] = {
            "saved_at": time.time(),
            "data": metadata,
        }
        self._save_anilist_cache()
        return metadata

    def _merge_anilist_metadata(self, item: dict, metadata: dict | None) -> dict:
        if not metadata:
            return item
        enriched = dict(item)
        enriched["anilist"] = metadata
        for key in ("description", "authors"):
            if metadata.get(key):
                enriched[key] = metadata[key]
        if metadata.get("genres"):
            combined_genres = list(enriched.get("genres") or []) + list(metadata.get("genres") or [])
            enriched["genres"] = list(dict.fromkeys(combined_genres))
        cover_urls = self._home_cover_urls(metadata)
        if cover_urls:
            enriched["poster"] = cover_urls[0]
            enriched["poster_fallbacks"] = cover_urls[1:]
        return enriched

    def _save_home_catalog_cache(self) -> None:
        try:
            HOME_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            safe_catalog = [
                item for item in self.home_catalog
                if self._home_item_is_safe(item)
            ]
            HOME_METADATA_CACHE_FILE.write_text(
                json.dumps(
                    {
                        "version": HOME_CACHE_VERSION,
                        "saved_at": time.time(),
                        "catalog": safe_catalog,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        except OSError:
            pass

    def _home_item_is_safe(self, item: dict) -> bool:
        if item.get("adult") is True or item.get("is_adult") is True or item.get("nsfw") is True:
            return False
        title_tokens = set(normalize_match_text(str(item.get("title") or "")).split())
        if title_tokens & HOME_BLOCKED_TERMS:
            return False
        content_rating = normalize_match_text(
            str(item.get("content_rating") or item.get("contentRating") or item.get("rating") or "")
        )
        if any(term in content_rating.split() for term in HOME_BLOCKED_TERMS):
            return False
        values: list[str] = []
        for key in ("genres", "tags", "themes"):
            value = item.get(key) or []
            if isinstance(value, list):
                values.extend(str(part) for part in value)
            elif value:
                values.append(str(value))
        metadata = set(normalize_match_text(" ".join(values)).split())
        return not bool(metadata & HOME_BLOCKED_TERMS)

    def _home_title_score(self, query: str, item: dict) -> float:
        alternative_titles = item.get("alternative_titles") or []
        if not isinstance(alternative_titles, list):
            alternative_titles = [str(alternative_titles)]
        return fuzzy_match_score(
            query,
            item.get("title"),
            item.get("alternative_title"),
            item.get("alt_title"),
            " ".join(str(title) for title in alternative_titles),
        )

    def _home_best_result(
        self,
        query: str,
        results: list[dict],
        minimum_score: float = 0.86,
    ) -> dict | None:
        candidates = [
            item
            for item in results
            if self._home_item_is_safe(item)
            and self._home_title_score(query, item) >= minimum_score
        ]
        if not candidates:
            return None
        query_tokens = set(normalize_match_text(query).split())
        return max(
            candidates,
            key=lambda item: (
                self._home_title_score(query, item),
                -len(set(normalize_match_text(str(item.get("title") or "")).split()) - query_tokens),
            ),
        )

    def _home_exact_result(self, query: str, results: list[dict]) -> dict | None:
        query_norm = normalize_match_text(query)
        for item in results:
            if not self._home_item_is_safe(item):
                continue
            alternative_titles = item.get("alternative_titles") or []
            if not isinstance(alternative_titles, list):
                alternative_titles = [alternative_titles]
            titles = [
                item.get("title"),
                item.get("alternative_title"),
                item.get("alt_title"),
                *alternative_titles,
            ]
            if any(normalize_match_text(str(title or "")) == query_norm for title in titles):
                return item
        return None

    def _render_home_sections(self) -> None:
        canvas = self.home_scroll._parent_canvas
        previous_view = canvas.yview()[0] if canvas.winfo_exists() else 0.0
        self._clear_widget_children(self.home_content)
        self._home_cover_labels = {}
        seen: set[str] = set()
        sections: list[tuple[str, list[dict]]] = []
        for section in HOME_SECTIONS:
            if section == "Em alta agora":
                candidates = list(self.home_trending)
            else:
                dynamic = list(self.home_mangadex_catalog.get(section) or [])
                curated = [
                    item for item in self.home_catalog
                    if item.get("section") == section
                ]
                candidates = dynamic[:HOME_MANGADEX_SECTION_LIMIT] + curated + dynamic[HOME_MANGADEX_SECTION_LIMIT:]

            selected: list[dict] = []
            for item in candidates:
                identity = normalize_match_text(
                    str(item.get("title") or item.get("url") or "")
                )
                if not identity or identity in seen:
                    continue
                seen.add(identity)
                selected.append(item)
                if len(selected) >= HOME_SECTION_LIMIT:
                    break
            sections.append((section, selected))

        row = 0
        for title, items in sections:
            if not items:
                continue
            self._create_home_section(self.home_content, title, items, row)
            row += 1
        if previous_view > 0:
            self.after_idle(lambda: canvas.yview_moveto(previous_view))

    def _create_home_section(self, parent, title: str, items: list[dict], row: int) -> None:
        section = ctk.CTkFrame(parent, fg_color="transparent")
        section.grid(row=row, column=0, pady=(0, 22), sticky="ew")
        section.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            section,
            text=title,
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color=TEXT,
            anchor="w",
        ).grid(row=0, column=0, pady=(0, 8), sticky="ew")

        grid = ctk.CTkFrame(section, fg_color="transparent")
        grid.grid(row=1, column=0, sticky="ew")
        for column in range(HOME_COLUMNS):
            grid.grid_columnconfigure(column, weight=1, uniform=f"home-{row}")
        self._render_home_cards(grid, items)

    def _render_search_results(self, items: list[dict]) -> None:
        self._clear_widget_children(self.home_content)
        self._home_cover_labels = {}
        grid = ctk.CTkFrame(self.home_content, fg_color="transparent")
        grid.grid(row=0, column=0, sticky="ew")
        for column in range(HOME_COLUMNS):
            grid.grid_columnconfigure(column, weight=1, uniform="home-search")
        self._render_home_cards(grid, items)

    def _render_home_cards(self, grid, items: list[dict]) -> None:
        if not items:
            ctk.CTkLabel(
                grid,
                text="Nenhuma obra encontrada.",
                text_color=MUTED,
                anchor="w",
            ).grid(row=0, column=0, columnspan=HOME_COLUMNS, pady=30, sticky="ew")
            return

        for index, item in enumerate(items):
            row, column = divmod(index, HOME_COLUMNS)
            self._create_home_card(grid, item, row, column)

    def _create_home_card(self, parent, item: dict, row: int, column: int) -> None:
        card = ctk.CTkFrame(
            parent,
            width=HOME_CARD_WIDTH,
            fg_color=PANEL_BG,
            border_width=1,
            border_color=BORDER,
            corner_radius=6,
        )
        card.grid(row=row, column=column, padx=6, pady=6, sticky="n")
        card.grid_propagate(False)
        card.configure(height=326)

        key = self._home_item_key(item)
        cover_image = self._home_cover_images.get(key)
        cover = ctk.CTkLabel(
            card,
            width=HOME_COVER_WIDTH,
            height=HOME_COVER_HEIGHT,
            text="" if cover_image else str(item.get("title") or "?")[:1].upper(),
            image=cover_image,
            fg_color=PANEL_SOFT,
            text_color=MUTED,
            font=ctk.CTkFont(size=36, weight="bold"),
            corner_radius=4,
        )
        cover.grid(row=0, column=0, padx=12, pady=(12, 8))

        title = str(item.get("title") or "Sem título")
        ctk.CTkLabel(
            card,
            text=title,
            width=HOME_COVER_WIDTH,
            height=38,
            wraplength=HOME_COVER_WIDTH,
            justify="left",
            anchor="nw",
            text_color=TEXT,
            font=ctk.CTkFont(size=12, weight="bold"),
        ).grid(row=1, column=0, padx=12, sticky="ew")

        genres = self._home_display_genres(item)
        score_text = self._home_score_text(item)
        meta_parts = [part for part in [score_text, *genres[:2]] if part]
        genre_text = " • ".join(str(part) for part in meta_parts) or "Mangá"
        ctk.CTkLabel(
            card,
            text=genre_text,
            width=HOME_COVER_WIDTH,
            anchor="w",
            text_color=MUTED,
            font=ctk.CTkFont(size=10),
        ).grid(row=2, column=0, padx=12, pady=(1, 7), sticky="ew")

        ctk.CTkButton(
            card,
            text="Ver capítulos",
            width=HOME_COVER_WIDTH,
            height=28,
            fg_color=PANEL_SOFT,
            hover_color=HOVER,
            border_width=1,
            border_color=BORDER,
            text_color=TEXT,
            corner_radius=5,
            command=lambda selected=dict(item): self._select_home_item(selected),
        ).grid(row=3, column=0, padx=12, pady=(0, 10))

        if not cover_image:
            cover_urls = self._home_cover_urls(item)
            if cover_urls:
                self._load_home_cover(key, cover_urls, cover)
            else:
                self._resolve_missing_home_cover(item, cover)

    def _home_cover_urls(self, item: dict) -> list[str]:
        candidates = [item.get("poster"), *(item.get("poster_fallbacks") or [])]
        urls: list[str] = []
        for candidate in candidates:
            url = str(candidate or "").strip()
            if url and url not in urls:
                urls.append(url)
        return urls

    def _load_home_cover(self, key: str, urls: list[str], label) -> None:
        if not urls:
            return
        labels = self._home_cover_labels.setdefault(key, [])
        labels.append(label)
        cached_image = self._home_cover_images.get(key)
        if cached_image:
            label.configure(image=cached_image, text="")
            return
        if key in self._home_cover_inflight:
            return
        self._home_cover_inflight.add(key)
        cache_name = hashlib.sha256(urls[0].encode("utf-8")).hexdigest() + ".jpg"
        cache_path = HOME_COVER_CACHE_DIR / cache_name

        def worker() -> None:
            try:
                source_bytes: bytes | None = None
                if cache_path.exists():
                    try:
                        source_bytes = cache_path.read_bytes()
                        with Image.open(io.BytesIO(source_bytes)) as cached_source:
                            cached_source.verify()
                    except Exception:
                        source_bytes = None
                        cache_path.unlink(missing_ok=True)
                if source_bytes is None:
                    for url in urls:
                        try:
                            referer = (
                                "https://mangadex.org/"
                                if "uploads.mangadex.org" in url
                                else url
                            )
                            response = requests.get(
                                url,
                                timeout=15,
                                headers={"User-Agent": "Mozilla/5.0", "Referer": referer},
                            )
                            response.raise_for_status()
                            with Image.open(io.BytesIO(response.content)) as downloaded:
                                downloaded.verify()
                            source_bytes = response.content
                            break
                        except Exception:
                            continue
                if source_bytes is None:
                    raise RuntimeError("Nenhuma capa válida foi encontrada.")
                with Image.open(io.BytesIO(source_bytes)) as source:
                    image = ImageOps.fit(
                        source.convert("RGB"),
                        (HOME_COVER_WIDTH, HOME_COVER_HEIGHT),
                        method=Image.Resampling.LANCZOS,
                    )
                if not cache_path.exists():
                    image.save(cache_path, format="JPEG", quality=88, optimize=True)
                if not self._run_on_ui(
                    lambda: self._run_when_home_scroll_idle(
                        lambda: apply_image(image),
                        lambda: self._home_cover_inflight.discard(key),
                    )
                ):
                    self._home_cover_inflight.discard(key)
            except Exception:
                self._run_on_ui(lambda: self._home_cover_inflight.discard(key)) or self._home_cover_inflight.discard(key)

        def apply_image(image: Image.Image) -> None:
            ctk_image = ctk.CTkImage(
                light_image=image,
                dark_image=image,
                size=(HOME_COVER_WIDTH, HOME_COVER_HEIGHT),
            )
            self._home_cover_images[key] = ctk_image
            self._home_cover_inflight.discard(key)
            for target in self._home_cover_labels.get(key, []):
                if target.winfo_exists():
                    target.configure(image=ctk_image, text="")

        threading.Thread(target=worker, daemon=True).start()

    def _resolve_missing_home_cover(self, item: dict, label) -> None:
        key = self._home_item_key(item)
        if not key or key in self._home_poster_inflight:
            return
        self._home_poster_inflight.add(key)
        query = str(item.get("query") or item.get("title") or "").strip()
        if not query:
            self._home_poster_inflight.discard(key)
            return

        def worker() -> None:
            try:
                payload = self.reader.search_mangadex(query, limit=12)
                results = payload.get("results") or []
                best = self._home_exact_result(query, results) or self._home_best_result(
                    query,
                    results,
                    minimum_score=0.82,
                )
                urls = self._home_cover_urls(best or {})
                if not urls:
                    raise RuntimeError("Capa não encontrada.")
                item["poster"] = urls[0]
                item["poster_fallbacks"] = urls[1:]
                for catalog_item in self.home_catalog:
                    if self._home_item_key(catalog_item) == key:
                        catalog_item["poster"] = urls[0]
                        catalog_item["poster_fallbacks"] = urls[1:]
                if not self._run_on_ui(lambda: apply(urls)):
                    self._home_poster_inflight.discard(key)
            except Exception:
                self._run_on_ui(finish) or self._home_poster_inflight.discard(key)

        def apply(urls: list[str]) -> None:
            self._home_poster_inflight.discard(key)
            self._save_home_catalog_cache()
            if label.winfo_exists():
                self._load_home_cover(key, urls, label)

        def finish() -> None:
            self._home_poster_inflight.discard(key)

        threading.Thread(target=worker, daemon=True).start()

    def _select_home_item(self, item: dict) -> None:
        source = str(item.get("url") or item.get("query") or item.get("title") or "").strip()
        if not source:
            return
        selected = dict(item)
        title = str(selected.get("title") or selected.get("query") or source)
        self._show_home_view()
        self.home_view = "detail"
        self.home_title_label.configure(text=title)
        self.home_status_label.configure(text="Buscando capítulos...")
        self._render_home_detail(selected, loading=True)

        def work() -> tuple[dict, dict, str, _SiteRaceHit | None, dict | None]:
            enriched_selected = dict(selected)
            try:
                metadata = self._fetch_anilist_metadata(enriched_selected)
                enriched_selected = self._merge_anilist_metadata(enriched_selected, metadata)
            except Exception:
                pass

            if self._is_direct_source(source):
                detected = self._detect_site_for_url(source)
                payload = self.reader.list_chapters(source, "pt-br", None)
                return enriched_selected, payload, source, None, detected

            provider = str(selected.get("provider") or "").strip().lower()
            provider_site = next(
                (site for site in self.sites if str(site.get("kind") or "").lower() == provider),
                None,
            )
            if provider_site:
                search_payload = self._site_search_payload(provider_site, source, 12)
                results = search_payload.get("results") or []
                best = self._home_exact_result(source, results) or self._home_best_result(
                    source,
                    results,
                    minimum_score=0.72,
                )
                resolved_url = str((best or {}).get("url") or "").strip()
                if not resolved_url:
                    raise RuntimeError(
                        f"{provider_site.get('name', provider)} não encontrou esta obra."
                    )
                payload = self.reader.list_chapters(resolved_url, "pt-br", None)
                if not payload.get("chapters"):
                    raise RuntimeError(
                        f"{provider_site.get('name', provider)} não retornou capítulos."
                    )
                return enriched_selected, payload, resolved_url, None, provider_site

            hit = self._race_manga_request(
                source,
                "pt-br",
                search_limit=3,
                load_chapters=True,
            )
            return enriched_selected, hit.chapters_payload or {}, hit.resolved_url, hit, hit.site

        def done(result: tuple[dict, dict, str, _SiteRaceHit | None, dict | None]) -> None:
            selected_item, payload, resolved_source, hit, site = result
            if hit:
                self._apply_winning_site(hit)
            elif site:
                self.active_site = site
                self._update_site_label(site)

            self.manga_entry.delete(0, "end")
            self.manga_entry.insert(0, resolved_source)
            self.search_entry.delete(0, "end")
            self.search_entry.insert(0, title)
            self.home_view = "detail"
            count = int(payload.get("count") or len(payload.get("chapters") or []))
            source_name = str((site or {}).get("name") or payload.get("provider") or "fonte")
            self.home_status_label.configure(text=f"{count} capítulos via {source_name}")
            self._render_home_detail(selected_item, payload=payload, source_name=source_name)

        self.run_background("Buscando capítulos...", work, done, disable_reader_nav=False)

    def _render_home_detail(
        self,
        item: dict,
        *,
        payload: dict | None = None,
        source_name: str = "",
        loading: bool = False,
    ) -> None:
        self._clear_widget_children(self.home_content)
        self._home_cover_labels = {}
        self._home_character_labels = {}
        payload = payload or {}
        chapters = payload.get("chapters") or []

        toolbar = ctk.CTkFrame(self.home_content, fg_color="transparent")
        toolbar.grid(row=0, column=0, pady=(0, 12), sticky="ew")
        toolbar.grid_columnconfigure(1, weight=1)
        ctk.CTkButton(
            toolbar,
            text="Voltar ao catálogo",
            width=126,
            height=32,
            fg_color=PANEL_SOFT,
            hover_color=HOVER,
            border_width=1,
            border_color=BORDER,
            text_color=TEXT,
            corner_radius=5,
            command=self._show_catalog_view,
        ).grid(row=0, column=0, sticky="w")

        detail = ctk.CTkFrame(
            self.home_content,
            fg_color=PANEL_BG,
            border_width=1,
            border_color=BORDER,
            corner_radius=6,
        )
        detail.grid(row=1, column=0, pady=(0, 18), sticky="ew")
        detail.grid_columnconfigure(1, weight=1)

        key = self._home_item_key(item)
        anilist = self._home_anilist_for_display(item)
        cover_image = self._home_cover_images.get(key)
        cover = ctk.CTkLabel(
            detail,
            width=HOME_COVER_WIDTH,
            height=HOME_COVER_HEIGHT,
            text="" if cover_image else str(item.get("title") or "?")[:1].upper(),
            image=cover_image,
            fg_color=PANEL_SOFT,
            text_color=MUTED,
            font=ctk.CTkFont(size=36, weight="bold"),
            corner_radius=4,
        )
        cover.grid(row=0, column=0, rowspan=5, padx=18, pady=18, sticky="nw")

        ctk.CTkLabel(
            detail,
            text=str(item.get("title") or "Sem título"),
            font=ctk.CTkFont(size=24, weight="bold"),
            text_color=TEXT,
            anchor="w",
        ).grid(row=0, column=1, padx=(0, 18), pady=(20, 4), sticky="ew")

        genres = self._home_display_genres(item)
        ctk.CTkLabel(
            detail,
            text=" • ".join(str(genre) for genre in genres) or "Mangá",
            text_color=MUTED,
            anchor="w",
        ).grid(row=1, column=1, padx=(0, 18), pady=(0, 6), sticky="ew")

        info_text = self._anilist_info_text(anilist)
        if info_text:
            ctk.CTkLabel(
                detail,
                text=info_text,
                text_color=TEXT,
                anchor="w",
                font=ctk.CTkFont(size=12, weight="bold"),
            ).grid(row=2, column=1, padx=(0, 18), pady=(0, 6), sticky="ew")

        authors = item.get("authors") or anilist.get("authors") or []
        if authors:
            ctk.CTkLabel(
                detail,
                text="Autores: " + ", ".join(str(author) for author in authors[:5]),
                text_color=MUTED,
                anchor="w",
            ).grid(row=3, column=1, padx=(0, 18), pady=(0, 6), sticky="ew")

        description = str(item.get("description") or "").strip()
        ctk.CTkLabel(
            detail,
            text=description[:420] if description else "Escolha um capítulo para começar a leitura.",
            text_color=MUTED,
            justify="left",
            anchor="nw",
            wraplength=680,
        ).grid(row=4, column=1, padx=(0, 18), pady=(0, 8), sticky="new")

        ctk.CTkLabel(
            detail,
            text=self._detail_source_text(source_name, anilist),
            text_color=MUTED_DARK,
            anchor="w",
        ).grid(row=5, column=1, padx=(0, 18), pady=(0, 20), sticky="sw")

        if not cover_image:
            cover_urls = self._home_cover_urls(item)
            if cover_urls:
                self._load_home_cover(key, cover_urls, cover)
            else:
                self._resolve_missing_home_cover(item, cover)

        next_row = 2
        characters = anilist.get("characters") or []
        if characters:
            self._render_character_strip(characters, next_row)
            next_row += 1

        chapters_frame = ctk.CTkFrame(self.home_content, fg_color="transparent")
        chapters_frame.grid(row=next_row, column=0, sticky="ew")
        for column in range(HOME_COLUMNS):
            chapters_frame.grid_columnconfigure(column, weight=1, uniform="detail-chapters")

        if loading:
            ctk.CTkLabel(
                chapters_frame,
                text="Buscando capítulos...",
                text_color=MUTED,
                anchor="w",
            ).grid(row=0, column=0, columnspan=HOME_COLUMNS, pady=24, sticky="ew")
            return
        if not chapters:
            ctk.CTkLabel(
                chapters_frame,
                text="Nenhum capítulo encontrado nesta fonte.",
                text_color=MUTED,
                anchor="w",
            ).grid(row=0, column=0, columnspan=HOME_COLUMNS, pady=24, sticky="ew")
            return

        for index, chapter in enumerate(chapters):
            row, column = divmod(index, HOME_COLUMNS)
            label = str(chapter.get("label") or f"Capítulo {index + 1}")
            chapter_title = str(chapter.get("title") or "").strip()
            if chapter_title:
                label = f"{label} - {chapter_title}"
            if len(label) > 44:
                label = label[:41] + "..."
            ctk.CTkButton(
                chapters_frame,
                text=label,
                height=34,
                fg_color=PANEL_BG,
                hover_color=HOVER,
                border_width=1,
                border_color=BORDER,
                text_color=TEXT,
                corner_radius=5,
                command=lambda url=str(chapter.get("url") or ""): self.open_chapter_url(url),
            ).grid(row=row, column=column, padx=5, pady=5, sticky="ew")

    def _anilist_info_text(self, metadata: dict) -> str:
        if not metadata:
            return ""
        parts: list[str] = []
        score = metadata.get("average_score") or metadata.get("mean_score")
        try:
            if score is not None:
                parts.append(f"Nota {int(score)}%")
        except (TypeError, ValueError):
            pass
        format_label = ANILIST_FORMAT_LABELS.get(str(metadata.get("format") or ""), metadata.get("format"))
        if format_label:
            parts.append(str(format_label))
        status_label = ANILIST_STATUS_LABELS.get(str(metadata.get("status") or ""), metadata.get("status"))
        if status_label:
            parts.append(str(status_label))
        if metadata.get("chapters"):
            parts.append(f"{metadata['chapters']} caps")
        elif metadata.get("volumes"):
            parts.append(f"{metadata['volumes']} vols")
        if metadata.get("popularity"):
            parts.append(f"{metadata['popularity']} leitores")
        return " • ".join(parts)

    def _detail_source_text(self, source_name: str, metadata: dict) -> str:
        parts = []
        if source_name:
            parts.append(f"Fonte dos capítulos: {source_name}")
        if metadata.get("url"):
            parts.append("Dados: AniList")
        return " • ".join(parts)

    def _render_character_strip(self, characters: list[dict], row: int) -> None:
        section = ctk.CTkFrame(self.home_content, fg_color="transparent")
        section.grid(row=row, column=0, pady=(0, 18), sticky="ew")
        section.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            section,
            text="Personagens",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=TEXT,
            anchor="w",
        ).grid(row=0, column=0, pady=(0, 8), sticky="ew")

        grid = ctk.CTkFrame(section, fg_color="transparent")
        grid.grid(row=1, column=0, sticky="ew")
        columns = min(5, max(1, len(characters)))
        for column in range(columns):
            grid.grid_columnconfigure(column, weight=1, uniform="characters")

        for index, character in enumerate(characters[:10]):
            card = ctk.CTkFrame(
                grid,
                fg_color=PANEL_BG,
                border_width=1,
                border_color=BORDER,
                corner_radius=6,
            )
            row_index, column = divmod(index, columns)
            card.grid(row=row_index, column=column, padx=5, pady=5, sticky="nsew")
            image_url = str(character.get("image") or "").strip()
            image_label = ctk.CTkLabel(
                card,
                text=str(character.get("name") or "?")[:1].upper(),
                width=HOME_CHARACTER_IMAGE_SIZE,
                height=HOME_CHARACTER_IMAGE_SIZE,
                fg_color=PANEL_SOFT,
                text_color=MUTED,
                font=ctk.CTkFont(size=22, weight="bold"),
                corner_radius=4,
            )
            image_label.grid(row=0, column=0, padx=8, pady=(8, 6))
            if image_url:
                self._load_character_image(
                    image_url,
                    character.get("image_fallbacks") or [],
                    image_label,
                )

            role = str(character.get("role") or "").title()
            ctk.CTkLabel(
                card,
                text=str(character.get("name") or "Personagem"),
                width=132,
                height=30,
                wraplength=132,
                justify="center",
                text_color=TEXT,
                font=ctk.CTkFont(size=11, weight="bold"),
            ).grid(row=1, column=0, padx=8, sticky="ew")
            ctk.CTkLabel(
                card,
                text=role,
                text_color=MUTED,
                font=ctk.CTkFont(size=10),
            ).grid(row=2, column=0, padx=8, pady=(0, 8), sticky="ew")

    def _load_character_image(self, url: str, fallbacks: list[str], label) -> None:
        urls = [url, *fallbacks]
        urls = [candidate for index, candidate in enumerate(urls) if candidate and candidate not in urls[:index]]
        if not urls:
            return
        key = hashlib.sha256(urls[0].encode("utf-8")).hexdigest()
        cached = self._home_character_images.get(key)
        labels = self._home_character_labels.setdefault(key, [])
        labels.append(label)
        if cached:
            label.configure(image=cached, text="")
            return
        if key in self._home_character_inflight:
            return
        self._home_character_inflight.add(key)

        def worker() -> None:
            try:
                source_bytes: bytes | None = None
                for candidate in urls:
                    try:
                        response = requests.get(
                            candidate,
                            timeout=15,
                            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://anilist.co/"},
                        )
                        response.raise_for_status()
                        source_bytes = response.content
                        break
                    except Exception:
                        continue
                if source_bytes is None:
                    raise RuntimeError("Imagem de personagem indisponivel.")
                with Image.open(io.BytesIO(source_bytes)) as source:
                    image = ImageOps.fit(
                        source.convert("RGB"),
                        (HOME_CHARACTER_IMAGE_SIZE, HOME_CHARACTER_IMAGE_SIZE),
                        method=Image.Resampling.LANCZOS,
                    )
                if not self._run_on_ui(
                    lambda: self._run_when_home_scroll_idle(
                        lambda: apply_image(image),
                        lambda: self._home_character_inflight.discard(key),
                    )
                ):
                    self._home_character_inflight.discard(key)
            except Exception:
                self._run_on_ui(lambda: self._home_character_inflight.discard(key)) or self._home_character_inflight.discard(key)

        def apply_image(image: Image.Image) -> None:
            ctk_image = ctk.CTkImage(
                light_image=image,
                dark_image=image,
                size=(HOME_CHARACTER_IMAGE_SIZE, HOME_CHARACTER_IMAGE_SIZE),
            )
            self._home_character_images[key] = ctk_image
            self._home_character_inflight.discard(key)
            for target in self._home_character_labels.get(key, []):
                if target.winfo_exists():
                    target.configure(image=ctk_image, text="")

        threading.Thread(target=worker, daemon=True).start()

    def _show_home_view(self) -> None:
        self.home_area.grid()
        self.reader_shell.grid_remove()
        self.top_reader_nav.grid_remove()
        self.header_label.configure(text="Biblioteca")
        self.home_area.tkraise()

    def _show_catalog_view(self) -> None:
        self._show_home_view()
        self.home_view = "catalog"
        self.home_title_label.configure(text="Descobrir")
        self.home_status_label.configure(text=f"{len(self.home_catalog)} obras em destaque")
        self._render_home_sections()

    def _show_reader_view(self) -> None:
        self.home_area.grid_remove()
        self.reader_shell.grid()
        self.top_reader_nav.grid()
        self.reader_shell.tkraise()

    def platform_search(self) -> None:
        query = self.global_search_entry.get().strip()
        if not query:
            self._show_catalog_view()
            return

        self._home_search_generation += 1
        generation = self._home_search_generation
        self._show_home_view()
        self.home_view = "search"
        self.home_title_label.configure(text=f'Resultados para "{query}"')
        self.home_status_label.configure(text="Buscando em várias fontes...")
        self._render_search_results([])

        def work() -> tuple[list[dict], int]:
            sites = self._race_sites(query)
            collected: list[dict] = []
            with ThreadPoolExecutor(max_workers=min(SEARCH_RACE_MAX_WORKERS, len(sites))) as executor:
                futures = {
                    executor.submit(self._site_search_payload, site, query, 10): site
                    for site in sites
                }
                for future in as_completed(futures):
                    site = futures[future]
                    try:
                        payload = future.result()
                    except Exception:
                        continue
                    for result in payload.get("results") or []:
                        item = dict(result)
                        item["source_name"] = site.get("name")
                        if self._home_item_is_safe(item):
                            collected.append(item)

            unique: dict[str, dict] = {}
            for item in collected:
                key = str(item.get("url") or normalize_match_text(str(item.get("title") or "")))
                if not key:
                    continue
                current = unique.get(key)
                if current is None or self._search_result_relevance(query, item) > self._search_result_relevance(query, current):
                    unique[key] = item
            results = sorted(
                unique.values(),
                key=lambda item: self._search_result_relevance(query, item),
                reverse=True,
            )
            return results[:24], len(sites)

        def done(result: tuple[list[dict], int]) -> None:
            if generation != self._home_search_generation:
                return
            results, source_count = result
            self.home_results = [dict(item) for item in results]
            self.home_view = "search"
            self.home_title_label.configure(text=f'Resultados para "{query}"')
            self.home_status_label.configure(
                text=f"{len(self.home_results)} resultados • {source_count} fontes"
            )
            self._render_search_results(self.home_results)

        self.run_background("Buscando catálogo...", work, done, disable_reader_nav=False)

    def _load_home_catalog(self) -> None:
        if self._home_catalog_loading:
            return
        if self._home_cache_fresh:
            self.home_status_label.configure(text=f"{len(self.home_catalog)} obras em destaque")
            return
        self._home_catalog_loading = True

        def enrich(item: dict) -> dict:
            provider = str(item.get("provider") or "")
            query = str(item.get("query") or item.get("title") or "")

            # Items com URL direta já têm fonte definida — só busca capa se faltar
            has_direct_url = bool(item.get("url"))
            has_poster = bool(item.get("poster"))

            # Se já tem URL e capa, não precisa de nenhuma requisição
            if has_direct_url and has_poster:
                return item

            payload: dict = {}
            # Só busca na API do provider se não tiver URL resolvida
            if not has_direct_url:
                try:
                    if provider == "toomics":
                        payload = self.reader.search_toomics(query, limit=4, lang="pt-br")
                    elif provider == "mangalivre":
                        payload = self.reader.search_mangalivre(query, limit=4)
                    elif provider == "mangadex":
                        payload = self.reader.search_mangadex(query, limit=4)
                    elif provider == "pieceproject":
                        payload = self.reader.search_pieceproject(query, limit=4)
                except Exception:
                    pass

            results = payload.get("results") or []
            best = self._home_exact_result(query, results) if results else None

            enriched = dict(item)
            if best:
                for key in ("url", "description", "authors"):
                    if best.get(key) and not enriched.get(key):
                        enriched[key] = best[key]
                if best.get("poster") and self._home_item_is_safe(best):
                    enriched["poster"] = best["poster"]
                if best.get("genres"):
                    combined_genres = list(item.get("genres") or []) + list(best.get("genres") or [])
                    enriched["genres"] = list(dict.fromkeys(combined_genres))

            # Fallback de capa via MangaDex — só se realmente não tiver poster
            # e o provider não for mangadex (evita request duplicado)
            if not enriched.get("poster") and provider not in ("mangadex", "mangasbrasuka"):
                try:
                    fallback = self.reader.search_mangadex(query, limit=8)
                    fallback_best = self._home_exact_result(query, fallback.get("results") or [])
                    if fallback_best and fallback_best.get("poster"):
                        enriched["poster"] = fallback_best["poster"]
                except Exception:
                    pass

            return enriched

        def worker() -> None:
            updated = [dict(item) for item in self.home_catalog]
            # Separa em dois grupos: itens que precisam de mais trabalho vs simples
            needs_work = [i for i, it in enumerate(updated) if not (it.get("url") and it.get("poster"))]
            no_work = [i for i in range(len(updated)) if i not in needs_work]

            # Itens sem trabalho já podem atualizar a UI imediatamente
            if no_work:
                self._run_on_ui(lambda: [apply_item(i, updated[i]) for i in no_work])

            # Itens que precisam de enriquecimento rodam em paralelo com mais workers
            max_w = min(8, max(1, len(needs_work)))
            with ThreadPoolExecutor(max_workers=max_w) as executor:
                futures = {
                    executor.submit(enrich, dict(updated[i])): i
                    for i in needs_work
                }
                for future in as_completed(futures):
                    index = futures[future]
                    try:
                        updated[index] = future.result()
                    except Exception:
                        continue
                    self._run_on_ui(lambda i=index, it=updated[index]: apply_item(i, it))

            self._run_on_ui(lambda: finish(updated))

        def apply_item(index: int, item: dict) -> None:
            if index >= len(self.home_catalog):
                return
            self.home_catalog[index] = item

        def finish(updated: list[dict]) -> None:
            self.home_catalog = updated
            self._home_catalog_loading = False
            self._save_home_catalog_cache()
            self.home_status_label.configure(text=f"{len(updated)} obras em destaque")
            if self.home_view == "catalog":
                self._schedule_home_sections_render()

        threading.Thread(target=worker, daemon=True).start()

    def _load_home_trending(self) -> None:
        if self._home_trending_cache_fresh:
            return

        def worker() -> None:
            try:
                payload = self.reader.trending_mangadex(limit=HOME_SECTION_LIMIT * 3)
                items = []
                for result in payload.get("results") or []:
                    item = dict(result)
                    item["provider"] = "mangadex"
                    item["section"] = "Em alta agora"
                    if self._home_item_is_safe(item):
                        items.append(item)
                    if len(items) >= HOME_SECTION_LIMIT:
                        break
                self._run_on_ui(lambda: finish(items))
            except Exception:
                return

        def finish(items: list[dict]) -> None:
            if not items:
                return
            self.home_trending = items
            self._home_trending_cache_fresh = True
            self._save_home_trending_cache()
            if self.home_view == "catalog":
                self._schedule_home_sections_render()

        threading.Thread(target=worker, daemon=True).start()

    def _load_home_mangadex_catalog(self) -> None:
        if self._home_mangadex_cache_fresh:
            return

        def worker() -> None:
            try:
                payload = self.reader.catalog_mangadex(
                    HOME_MANGADEX_GENRES,
                    limit_per_genre=HOME_MANGADEX_SECTION_LIMIT,
                    lang="",  # sem filtro de lingua — mais rapido e mais capas disponiveis
                )
                sections = payload.get("sections") or {}
                safe_sections = {
                    section: [
                        dict(item)
                        for item in sections.get(section) or []
                        if self._home_item_is_safe(item)
                    ][:HOME_MANGADEX_SECTION_LIMIT]
                    for section in HOME_SECTIONS[1:]
                }
                self._run_on_ui(lambda: finish(safe_sections))
            except Exception:
                return

        def finish(sections: dict[str, list[dict]]) -> None:
            if not any(sections.values()):
                return
            self.home_mangadex_catalog = sections
            self._home_mangadex_cache_fresh = True
            self._save_home_mangadex_catalog_cache()
            if self.home_view == "catalog":
                self._schedule_home_sections_render()

        threading.Thread(target=worker, daemon=True).start()

    def _apply_site_defaults(self) -> None:
        site = self.current_site()
        self._update_site_label(site)
        self.lang_entry.delete(0, "end")
        self.lang_entry.insert(0, site.get("default_lang", "pt-br"))
        self.status(f"Busca automatica em {len(self._race_sites())} fontes (relevancia + confiabilidade).")

    def _update_site_label(self, site: dict, elapsed: float | None = None) -> None:
        text = f"Auto: {site['name']}"
        if elapsed is not None:
            text += f" ({elapsed:.1f}s)"
        self.site_label.configure(text=text)

    def _apply_winning_site(self, hit: _SiteRaceHit) -> None:
        self.active_site = hit.site
        self._update_site_label(hit.site, hit.elapsed)
        self.lang_entry.delete(0, "end")
        selected_lang = (
            str((hit.chapters_payload or {}).get("language") or "").strip()
            or hit.site.get("default_lang", "pt-br")
        )
        self.lang_entry.insert(0, selected_lang)

    def _race_sites(self, query: str | None = None) -> list[dict]:
        sites = [
            site
            for site in self.sites
            if site.get("kind") not in UNSUPPORTED_RACE_KINDS
        ]
        if not query:
            return sites

        one_piece_score = fuzzy_match_score(
            query,
            "One Piece",
            "OnePiece",
            "Luffy",
            "Ruffy",
        )
        if one_piece_score < PIECEPROJECT_RACE_RELEVANCE:
            sites = [site for site in sites if site.get("kind") != "pieceproject"]
        return sites

    def _search_result_relevance(self, query: str, result: dict) -> float:
        score = fuzzy_match_score(
            query,
            result.get("title"),
            result.get("description"),
            result.get("alternative_title"),
            result.get("alt_title"),
            result.get("url"),
            result.get("id"),
        )
        query_norm = normalize_match_text(query)
        title_norm = normalize_match_text(str(result.get("title") or ""))
        if query_norm and title_norm:
            if title_norm == query_norm:
                return 1.0
            if title_norm.startswith(query_norm):
                return max(score, 0.98)
            if query_norm in title_norm:
                score = min(score, 0.90)
        return score

    def _source_reliability(self, site: dict, payload: dict) -> float:
        kind = str(site.get("kind") or "").lower()
        reliability = SOURCE_RELIABILITY.get(kind, 0.50)
        return max(0.0, min(1.0, reliability))

    def _result_completeness(self, results: list[dict], chapters_payload: dict | None) -> float:
        completeness = 0.25 if results else 0.0
        best = results[0] if results else {}
        if best.get("url"):
            completeness += 0.15
        if best.get("title"):
            completeness += 0.10
        if best.get("poster") or best.get("description"):
            completeness += 0.05

        if chapters_payload:
            chapters = chapters_payload.get("chapters") or []
            count = int(chapters_payload.get("count") or len(chapters))
            if chapters and chapters_payload.get("selected_url"):
                completeness += 0.25
            if count >= 100:
                completeness += 0.22
            elif count >= 50:
                completeness += 0.19
            elif count >= 20:
                completeness += 0.17
            elif count >= 10:
                completeness += 0.15
            elif count > 0:
                completeness += 0.08
            if chapters and any(chapter.get("title") for chapter in chapters[:5]):
                completeness += 0.05

        return max(0.0, min(1.0, completeness))

    def _normalize_lang_code(self, value: str | None) -> str:
        normalized = (value or "").strip().lower().replace("_", "-")
        if not normalized:
            return ""
        aliases = {
            "br": "pt-br",
            "pt": "pt",
            "por": "pt",
            "eng": "en",
            "en-us": "en",
        }
        return aliases.get(normalized, normalized)

    def _same_language_family(self, left: str, right: str) -> bool:
        if left == right:
            return True
        if left.startswith("pt") and right.startswith("pt"):
            return True
        if left.startswith("en") and right.startswith("en"):
            return True
        if left.startswith("es") and right.startswith("es"):
            return True
        return False

    def _language_fit(self, site: dict, chapters_payload: dict | None, requested_lang: str) -> float:
        requested = self._normalize_lang_code(requested_lang) or "pt-br"
        provider = str((chapters_payload or {}).get("provider") or site.get("kind") or "").lower()
        payload_lang = self._normalize_lang_code(str((chapters_payload or {}).get("language") or ""))

        if payload_lang and self._same_language_family(requested, payload_lang):
            # MangaDex retorna o idioma no payload, mas a disponibilidade de
            # traducoes pt-br e limitada. Penaliza levemente para fontes pt-br
            # dedicadas vencerem quando tiverem catalogo completo.
            if provider == "mangadex" and requested.startswith("pt"):
                return 0.82
            return 1.0

        if provider == "mangalivre":
            return 1.0 if requested.startswith("pt") else 0.35

        if provider == "mangakatana":
            return 0.95 if requested.startswith("en") else 0.12

        if provider == "readfull":
            return 0.95 if requested.startswith("en") else 0.20

        if provider == "pieceproject":
            return 1.0 if requested.startswith("pt") else 0.35

        default_lang = self._normalize_lang_code(str(site.get("default_lang") or ""))
        if default_lang and self._same_language_family(requested, default_lang):
            return 0.85
        return 0.55

    def _race_score(
        self,
        relevance: float,
        reliability: float,
        completeness: float,
        language_fit: float,
        elapsed: float,
    ) -> float:
        speed_penalty = min(max(elapsed, 0.0) / 8.0, 1.0) * RACE_MAX_SPEED_PENALTY
        return (
            relevance * RACE_RELEVANCE_WEIGHT
            + reliability * RACE_RELIABILITY_WEIGHT
            + completeness * RACE_COMPLETENESS_WEIGHT
            + language_fit * RACE_LANGUAGE_WEIGHT
            - speed_penalty
        )

    def _site_search_payload(self, site: dict, query: str, limit: int) -> dict:
        kind = site.get("kind")
        if kind == "dragontea":
            return self.reader.search_dragontea(query, limit=limit)
        if kind == "mangadex":
            return self.reader.search_mangadex(query, limit=limit)
        if kind == "pieceproject":
            return self.reader.search_pieceproject(query, limit=limit)
        if kind == "readfull":
            return self.reader.search_readfull(query, limit=limit)
        if kind == "mangalivre":
            return self.reader.search_mangalivre(query, limit=limit)
        if kind == "mangasbrasuka":
            return self.reader.search_mangasbrasuka(query, limit=limit)
        if kind == "mangakatana":
            return self.reader.search_mangakatana(query, limit=limit)
        if kind == "toomics":
            return self.reader.search_toomics(
                query,
                limit=limit,
                lang=site.get("default_lang", "en"),
            )
        return self.reader.search_manga(query, limit=limit)

    def _site_race_task(
        self,
        site: dict,
        query: str,
        lang: str,
        *,
        search_limit: int,
        load_chapters: bool,
    ) -> _SiteRaceHit | None:
        started = time.perf_counter()
        try:
            payload = self._site_search_payload(site, query, search_limit)
            results = payload.get("results") or []
            if not results:
                return None

            min_relevance = (
                PIECEPROJECT_RACE_RELEVANCE
                if site.get("kind") == "pieceproject"
                else MIN_RACE_RELEVANCE
            )
            search_candidates: list[tuple[dict, float]] = []
            for item in results[:5]:
                item_relevance = self._search_result_relevance(query, item)
                if item_relevance >= min_relevance:
                    search_candidates.append((item, item_relevance))
            if not search_candidates:
                return None

            best_hit: _SiteRaceHit | None = None
            for best_result, relevance in search_candidates:
                resolved_url = str(best_result.get("url") or "").strip()
                if not resolved_url:
                    continue

                chapters_payload = None
                if load_chapters:
                    site_lang = lang or site.get("default_lang", "pt-br")
                    chapters_payload = self.reader.list_chapters(
                        resolved_url,
                        site_lang,
                        None,
                    )
                    chapter_count = int(chapters_payload.get("count") or 0)
                    if not chapters_payload.get("chapters"):
                        continue
                    if site.get("kind") == "mangadex" and chapter_count < SPARSE_CHAPTER_THRESHOLD:
                        continue

                elapsed = time.perf_counter() - started
                reliability = self._source_reliability(site, payload)
                completeness = self._result_completeness([best_result], chapters_payload)
                language_fit = self._language_fit(site, chapters_payload, lang)
                score = self._race_score(relevance, reliability, completeness, language_fit, elapsed)
                selected_payload = dict(payload)
                selected_payload["results"] = [
                    best_result,
                    *[
                        item for item in results
                        if str(item.get("url") or "").strip() != resolved_url
                    ],
                ]
                hit = _SiteRaceHit(
                    site=site,
                    elapsed=elapsed,
                    search_payload=selected_payload,
                    resolved_url=resolved_url,
                    relevance=relevance,
                    reliability=reliability,
                    completeness=completeness,
                    language_fit=language_fit,
                    score=score,
                    chapters_payload=chapters_payload,
                )
                if best_hit is None or (
                    hit.score,
                    hit.completeness,
                    hit.relevance,
                    -hit.elapsed,
                ) > (
                    best_hit.score,
                    best_hit.completeness,
                    best_hit.relevance,
                    -best_hit.elapsed,
                ):
                    best_hit = hit

            return best_hit
        except Exception:
            return None

    def _preferred_portuguese_hit(
        self,
        candidates: list[_SiteRaceHit],
        lang: str,
    ) -> _SiteRaceHit | None:
        requested = self._normalize_lang_code(lang) or "pt-br"
        if not requested.startswith("pt"):
            return None

        def sort_key(item: _SiteRaceHit) -> tuple[float, float, float, float, float]:
            return (
                item.score,
                item.reliability,
                item.language_fit,
                item.completeness,
                item.relevance,
            )

        top = max(candidates, key=sort_key, default=None)
        if top and top.site.get("kind") == "pieceproject":
            return None

        preferred: list[_SiteRaceHit] = []
        for hit in candidates:
            if hit.site.get("kind") != "mangalivre":
                continue
            chapters_payload = hit.chapters_payload or {}
            chapter_count = int(chapters_payload.get("count") or 0)
            if (
                hit.relevance >= MANGALIVRE_PREFERRED_RELEVANCE
                and hit.language_fit >= 0.95
                and chapter_count >= MANGALIVRE_PREFERRED_MIN_CHAPTERS
            ):
                preferred.append(hit)

        return max(preferred, key=sort_key, default=None)

    def _is_preferred_mangalivre_hit(self, hit: _SiteRaceHit | None, lang: str) -> bool:
        requested = self._normalize_lang_code(lang) or "pt-br"
        if not hit or not requested.startswith("pt") or hit.site.get("kind") != "mangalivre":
            return False
        chapters_payload = hit.chapters_payload or {}
        chapter_count = int(chapters_payload.get("count") or 0)
        return (
            hit.relevance >= MANGALIVRE_PREFERRED_RELEVANCE
            and hit.language_fit >= 0.95
            and chapter_count >= MANGALIVRE_PREFERRED_MIN_CHAPTERS
        )

    def _race_manga_request(
        self,
        query: str,
        lang: str = "pt-br",
        *,
        search_limit: int = 15,
        load_chapters: bool = False,
    ) -> _SiteRaceHit:
        sites = self._race_sites(query)
        if not sites:
            raise RuntimeError("Nenhuma fonte configurada para busca automatica.")

        requested = self._normalize_lang_code(lang) or "pt-br"
        if requested.startswith("pt") and load_chapters:
            mangalivre_site = next((site for site in sites if site.get("kind") == "mangalivre"), None)
            if mangalivre_site:
                hit = self._site_race_task(
                    mangalivre_site,
                    query,
                    lang,
                    search_limit=search_limit,
                    load_chapters=load_chapters,
                )
                if self._is_preferred_mangalivre_hit(hit, lang):
                    return hit
                sites = [site for site in sites if site is not mangalivre_site]
                if not sites and hit:
                    return hit
                if not sites:
                    raise RuntimeError("MangaLivre nao retornou resultado relevante.")

        workers = min(SEARCH_RACE_MAX_WORKERS, len(sites))
        errors: list[str] = []
        candidates: list[_SiteRaceHit] = []

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(
                    self._site_race_task,
                    site,
                    query,
                    lang,
                    search_limit=search_limit,
                    load_chapters=load_chapters,
                ): site
                for site in sites
            }
            for future in as_completed(futures):
                site = futures[future]
                try:
                    hit = future.result()
                except Exception as exc:
                    errors.append(f"{site['name']}: {exc}")
                    continue
                if hit is not None:
                    candidates.append(hit)
                else:
                    errors.append(f"{site['name']}: sem resultado relevante")

        if candidates:
            preferred = self._preferred_portuguese_hit(candidates, lang)
            if preferred:
                return preferred

            candidates.sort(
                key=lambda item: (
                    -item.score,
                    -item.reliability,
                    -item.language_fit,
                    -item.completeness,
                    -item.relevance,
                    item.elapsed,
                )
            )
            return candidates[0]

        detail = "; ".join(errors[:4])
        if len(errors) > 4:
            detail += f"; +{len(errors) - 4} outras"
        action = "capitulos" if load_chapters else "resultados"
        raise RuntimeError(f"Nenhuma fonte retornou {action} para: {query}. {detail}")

    def _detect_site_for_url(self, url: str) -> dict | None:
        lowered = url.lower()
        if "mangadex.org" in lowered or lowered.startswith("mangadex://"):
            kind = "mangadex"
        elif "mangalivre.blog" in lowered or lowered.startswith("mangalivre://"):
            kind = "mangalivre"
        elif lowered.startswith("readfull://") or "readfull" in lowered:
            kind = "readfull"
        elif lowered.startswith("pieceproject://") or "onepieceproject" in lowered:
            kind = "pieceproject"
        elif "dragontea.ink" in lowered:
            kind = "dragontea"
        elif "toomics.com" in lowered or lowered.startswith("toomics://"):
            kind = "toomics"
        elif "mangakatana.com" in lowered or lowered.startswith("mangakatana://"):
            kind = "mangakatana"
        elif "mangasbrasuka.com.br" in lowered or lowered.startswith("mangasbrasuka://"):
            kind = "mangasbrasuka"
        else:
            return None

        for site in self.sites:
            if site.get("kind") == kind:
                return site
        return None

    def _is_direct_source(self, value: str) -> bool:
        return value.startswith(
            (
                "http://", "https://",
                "readfull://", "mangadex://", "pieceproject://",
                "toomics://", "mangalivre://", "mangakatana://",
                "mangasbrasuka://",
            )
        )

    def _schedule_auto_fetch_chapters(self, _event=None, delay_ms: int = 700) -> None:
        if self._auto_fetch_after_id:
            self.after_cancel(self._auto_fetch_after_id)
            self._auto_fetch_after_id = None
        if not self.manga_entry.get().strip():
            return
        self._auto_fetch_after_id = self.after(delay_ms, self._auto_fetch_chapters)

    def _auto_fetch_chapters(self) -> None:
        self._auto_fetch_after_id = None
        self.fetch_chapters(auto=True)

    def current_site(self) -> dict:
        return self.active_site or self.sites[0]

    def resolve_source_url(self) -> str:
        raw = self.manga_entry.get().strip()
        if not raw:
            raise ValueError("Informe o manga, slug ou URL.")

        if raw.startswith(("http://", "https://", "readfull://", "mangadex://", "pieceproject://", "toomics://", "mangalivre://", "mangakatana://")):
            return raw

        site = self.current_site()
        template = site.get("manga_url_template")
        if not template:
            raise ValueError("Este site salvo nao tem template de URL.")

        slug = raw.strip().strip("/")
        return template.format(slug=slug)

    def _looks_like_search_text(self, value: str) -> bool:
        value = value.strip()
        if not value or value.startswith(("http://", "https://", "readfull://", "mangadex://", "pieceproject://", "toomics://", "mangalivre://", "mangakatana://")):
            return False
        if "/" in value or "\\" in value:
            return False
        return True

    def _search_first_source_url(self, query: str, lang: str = "pt-br") -> str:
        hit = self._race_manga_request(query, lang, search_limit=1, load_chapters=True)
        self._apply_winning_site(hit)
        return hit.resolved_url

    def search_manga(self) -> None:
        query = self.search_entry.get().strip()
        if not query:
            self.status("Digite o nome do manga para buscar.")
            return

        def work() -> tuple[list[dict], _SiteRaceHit]:
            lang = self.lang_entry.get().strip() or "pt-br"
            hit = self._race_manga_request(query, lang, search_limit=15, load_chapters=True)
            return hit.search_payload.get("results") or [], hit

        def done(result: tuple[list[dict], _SiteRaceHit]) -> None:
            results, hit = result
            self._apply_winning_site(hit)
            self.on_search_loaded(results)

        self.run_background(
            f"Buscando em {len(self._race_sites(query))} fontes (relevancia + confiabilidade)...",
            work,
            done,
        )

    def on_search_loaded(self, results: list[dict]) -> None:
        self.search_result_by_label = {}
        values: list[str] = []

        for result in results:
            title = str(result.get("title") or "Sem titulo").strip()
            url = str(result.get("url") or "").strip()
            if not url:
                continue

            label = title
            suffix = 2
            while label in self.search_result_by_label:
                label = f"{title} ({suffix})"
                suffix += 1

            values.append(label)
            self.search_result_by_label[label] = url

        if not values:
            self.search_menu.configure(values=["Nenhum resultado"])
            self.search_menu.set("Nenhum resultado")
            self.status("Nenhum manga encontrado.")
            return

        self.search_menu.configure(values=values)
        self.search_menu.set(values[0])
        self.on_search_selected(values[0])
        site_name = self.current_site().get("name", "fonte")
        self.status(
            f"{len(values)} resultados em {site_name}. Capitulos serao buscados automaticamente."
        )

    def on_search_selected(self, label: str) -> None:
        url = self.search_result_by_label.get(label)
        if not url:
            return

        self.manga_entry.delete(0, "end")
        self.manga_entry.insert(0, url)
        self.chapter_by_label = {}
        self.chapter_menu.configure(values=["Nenhum capitulo"])
        self.chapter_menu.set("Nenhum capitulo")
        self._last_chapter_fetch_key = None
        self._schedule_auto_fetch_chapters(delay_ms=150)

    def fetch_chapters(self, auto: bool = False) -> None:
        raw_source = self.manga_entry.get().strip()
        if not raw_source:
            if not auto:
                self.status("Informe o manga, slug, URL ou nome para buscar.")
            return

        search_query = raw_source if self._looks_like_search_text(raw_source) else None
        use_race = bool(search_query) or not self._is_direct_source(raw_source)
        lang = self.lang_entry.get().strip() or "pt-br"

        try:
            source = raw_source if (search_query or use_race) else self.resolve_source_url()
        except Exception as exc:
            if not auto:
                self.status(str(exc))
            return

        key = (raw_source, lang, use_race)
        if auto and key == self._last_chapter_fetch_key:
            return

        if self.loading:
            if auto:
                self._schedule_auto_fetch_chapters(delay_ms=900)
            else:
                self.status("Aguarde a tarefa atual terminar.")
            return

        self._last_chapter_fetch_key = key
        self.chapter_by_label = {}
        self.chapter_menu.configure(values=["Carregando capitulos..."])
        self.chapter_menu.set("Carregando capitulos...")
        if not self.current_data:
            self.header_label.configure(text="Buscando capitulos...")

        def work() -> tuple[tuple[list[dict], str | None, int], str]:
            if use_race:
                query = search_query or raw_source
                hit = self._race_manga_request(
                    query,
                    lang,
                    search_limit=1,
                    load_chapters=True,
                )
                self._apply_winning_site(hit)
                payload = hit.chapters_payload or {}
                resolved_source = hit.resolved_url
            else:
                detected = self._detect_site_for_url(source)
                if detected:
                    self.active_site = detected
                    self._update_site_label(detected)
                payload = self.reader.list_chapters(source, lang, None)
                resolved_source = source

            return (
                (payload["chapters"], payload.get("selected_url"), payload["count"]),
                resolved_source,
            )

        def done(result: tuple[tuple[list[dict], str | None, int], str]) -> None:
            chapters_result, resolved_source = result
            if resolved_source != raw_source:
                self.manga_entry.delete(0, "end")
                self.manga_entry.insert(0, resolved_source)
            self.on_chapters_loaded(chapters_result)

        message = (
            f"Buscando capitulos em {len(self._race_sites(search_query or raw_source))} fontes..."
            if use_race
            else "Buscando capitulos..."
        )
        self.run_background(message, work, done)

    def on_chapters_loaded(self, result: tuple[list[dict], str | None, int]) -> None:
        chapters, selected_url, count = result
        self.chapter_by_label = {}
        values: list[str] = []

        for chapter in chapters:
            label = chapter["label"]
            if chapter.get("title"):
                label = f"{label} - {chapter['title']}"
            values.append(label)
            self.chapter_by_label[label] = chapter["url"]

        if not values:
            values = ["Nenhum capitulo"]

        self.chapter_menu.configure(values=values)
        selected_label = values[0]
        for label, url in self.chapter_by_label.items():
            if url == selected_url:
                selected_label = label
                break
        self.chapter_menu.set(selected_label)
        site_name = self.current_site().get("name", "fonte")
        self.status(f"{count} capitulos encontrados via {site_name}.")
        if not self.current_data:
            self.header_label.configure(text=f"{count} capitulos ({site_name})")

    def open_selected(self) -> None:
        selected_label = self.chapter_menu.get()
        selected_url = self.chapter_by_label.get(selected_label)
        source: str | None = None
        search_query: str | None = None
        raw_source = self.manga_entry.get().strip()

        try:
            lang = self.lang_entry.get().strip() or "pt-br"
            preferred_chapter = None
            if not selected_url:
                search_query = raw_source if self._looks_like_search_text(raw_source) else None
                source = raw_source if search_query else self.resolve_source_url()
        except Exception as exc:
            self.status(str(exc))
            return

        def work() -> tuple[tuple[list[dict], str | None, int] | None, dict, str | None]:
            if selected_url:
                return None, self.reader.load_chapter(selected_url), None

            if not source:
                raise RuntimeError("Nenhum manga ou capitulo informado.")
            if "/chapter-" in source:
                return None, self.reader.load_chapter(source), source

            if search_query or (
                raw_source and not self._is_direct_source(raw_source)
            ):
                hit = self._race_manga_request(
                    search_query or raw_source,
                    lang,
                    search_limit=1,
                    load_chapters=True,
                )
                self._apply_winning_site(hit)
                payload = hit.chapters_payload or {}
                resolved_source = hit.resolved_url
            else:
                detected = self._detect_site_for_url(source)
                if detected:
                    self.active_site = detected
                    self._update_site_label(detected)
                payload = self.reader.list_chapters(source, lang, preferred_chapter)
                resolved_source = source
            selected = payload.get("selected_url")
            if not selected:
                raise RuntimeError("Nenhum capitulo selecionado.")
            chapters_result = (
                payload["chapters"],
                payload.get("selected_url"),
                payload["count"],
            )
            return chapters_result, self.reader.load_chapter(selected), resolved_source

        def done(result: tuple[tuple[list[dict], str | None, int] | None, dict, str | None]) -> None:
            chapters_result, chapter_data, resolved_source = result
            if resolved_source and resolved_source != raw_source:
                self.manga_entry.delete(0, "end")
                self.manga_entry.insert(0, resolved_source)
            self.on_open_selected_done((chapters_result, chapter_data))

        self.run_background(
            "Abrindo capitulo...",
            work,
            done,
        )

    def on_open_selected_done(self, result: tuple[tuple[list[dict], str | None, int] | None, dict]) -> None:
        chapters_result, chapter_data = result
        if chapters_result:
            self.on_chapters_loaded(chapters_result)
        self.on_chapter_opened(chapter_data)

    def open_previous_chapter(self) -> None:
        if self.current_data and self.current_data.get("previous"):
            self.open_chapter_url(self.current_data["previous"])

    def open_next_chapter(self) -> None:
        if self.current_data and self.current_data.get("next"):
            self.open_chapter_url(self.current_data["next"])

    def open_chapter_url(self, url: str) -> None:
        self.run_background(
            "Abrindo capitulo...",
            lambda: self.reader.load_chapter(url),
            self.on_chapter_opened,
        )

    def on_chapter_opened(self, data: dict) -> None:
        self._clear_pages()
        self.current_data = data
        self._show_reader_view()
        self.canvas.yview_moveto(0)
        self._show_placeholder(f"Preparando {data['label']}...")
        self.prev_chapter_button.configure(state="normal" if data.get("previous") else "disabled")
        self.next_chapter_button.configure(state="normal" if data.get("next") else "disabled")
        self.top_prev_button.configure(state="normal" if data.get("previous") else "disabled")
        self.top_next_button.configure(state="normal" if data.get("next") else "disabled")
        if data.get("mode") == "text":
            self._render_text_chapter(data)
            return
        self.header_label.configure(text=f"{data['label']} - {data['count']} paginas")
        self._start_longstrip_load()


    def _on_canvas_resize(self, event) -> None:
        if self.resize_after_id:
            self.after_cancel(self.resize_after_id)
        if self.current_data and self.current_data.get("mode") == "text":
            self.resize_after_id = self.after(80, self._resize_text_chapter)
            return
        if self._page_images or self._page_errors:
            self.resize_after_id = self.after(80, self._resize_image_pages)
        else:
            self.canvas.itemconfigure("placeholder", width=max(300, event.width - 40))
            self._refresh_scrollregion()

    def _on_canvas_yview(self, *args) -> None:
        self._mark_reader_scroll()
        self.canvas.yview(*args)
        self._schedule_lazy_visible_pages(delay_ms=45)

    def _on_mousewheel(self, event) -> None:
        self._mark_reader_scroll()
        if event.num == 4:
            self.canvas.yview_scroll(-READER_SCROLL_UNITS, "units")
        elif event.num == 5:
            self.canvas.yview_scroll(READER_SCROLL_UNITS, "units")
        else:
            self.canvas.yview_scroll(int(-1 * (event.delta / 120) * READER_SCROLL_UNITS), "units")
        self._schedule_lazy_visible_pages(delay_ms=45)
        return "break"

    def _mark_reader_scroll(self) -> None:
        self._reader_scroll_active_until = time.monotonic() + 0.18

    def _reader_width(self) -> int:
        self.canvas.update_idletasks()
        return max(400, self.canvas.winfo_width())

    def _refresh_scrollregion(self) -> None:
        self.canvas.update_idletasks()
        bbox = self.canvas.bbox("all")
        if bbox:
            width = max(self.canvas.winfo_width(), bbox[2])
            height = max(self.canvas.winfo_height(), bbox[3])
            self.canvas.configure(scrollregion=(0, 0, width, height))
        else:
            self.canvas.configure(
                scrollregion=(0, 0, self.canvas.winfo_width(), self.canvas.winfo_height())
            )

    def _show_placeholder(self, message: str) -> None:
        self.canvas.delete("page")
        self.canvas.delete("novel")
        self.canvas.delete("placeholder")
        self.placeholder_item = self.canvas.create_text(
            20,
            20,
            text=message,
            anchor="nw",
            fill=MUTED,
            width=max(300, self._reader_width() - 40),
            tags=("placeholder",),
        )
        self._refresh_scrollregion()

    def _text_layout(self) -> tuple[int, int, int]:
        width = self._reader_width()
        text_width = min(900, max(320, width - 120))
        x = max(40, (width - text_width) // 2)
        return width, x, text_width

    def _render_text_chapter(self, data: dict) -> None:
        self.canvas.delete("placeholder")
        self.canvas.delete("page")
        self.canvas.delete("novel")

        _width, x, text_width = self._text_layout()
        title = str(data.get("title") or data.get("label") or "Capitulo")
        number = data.get("number_text") or data.get("number")
        chapter_line = f"Capitulo {number}" if number else "Capitulo"
        content = str(data.get("content") or "").strip()

        self.canvas.create_text(
            x,
            42,
            text=title,
            anchor="nw",
            fill=TEXT,
            width=text_width,
            font=("Segoe UI", 22, "bold"),
            tags=("novel", "novel-title"),
        )
        self.canvas.create_text(
            x,
            82,
            text=chapter_line,
            anchor="nw",
            fill=MUTED,
            width=text_width,
            font=("Segoe UI", 11),
            tags=("novel", "novel-meta"),
        )
        self.canvas.create_text(
            x,
            126,
            text=content,
            anchor="nw",
            fill=TEXT,
            width=text_width,
            font=("Segoe UI", 15),
            tags=("novel", "novel-content"),
        )

        bbox = self.canvas.bbox("novel") or (0, 0, self._reader_width(), self.canvas.winfo_height())
        self.canvas.configure(
            scrollregion=(0, 0, self._reader_width(), max(bbox[3] + 64, self.canvas.winfo_height()))
        )
        self.header_label.configure(text=f"{data.get('label', 'ReadFull')} - texto")
        self.status("Capitulo de novel carregado.")

    def _resize_text_chapter(self) -> None:
        if not (self.current_data and self.current_data.get("mode") == "text"):
            return
        _width, x, text_width = self._text_layout()
        title_items = self.canvas.find_withtag("novel-title")
        meta_items = self.canvas.find_withtag("novel-meta")
        content_items = self.canvas.find_withtag("novel-content")
        if title_items:
            self.canvas.coords(title_items[0], x, 42)
            self.canvas.itemconfigure(title_items[0], width=text_width)
        if meta_items:
            self.canvas.coords(meta_items[0], x, 82)
            self.canvas.itemconfigure(meta_items[0], width=text_width)
        if content_items:
            self.canvas.coords(content_items[0], x, 126)
            self.canvas.itemconfigure(content_items[0], width=text_width)
        bbox = self.canvas.bbox("novel") or (0, 0, self._reader_width(), self.canvas.winfo_height())
        self.canvas.configure(
            scrollregion=(0, 0, self._reader_width(), max(bbox[3] + 64, self.canvas.winfo_height()))
        )

    def _scale_image(self, image: Image.Image) -> Image.Image:
        orig_w, orig_h = image.size
        if not self.fit_switch.get():
            return image
        avail_w = max(1, self._reader_width() - 8)
        return self._scale_image_to_width(image, avail_w, True)

    def _scale_image_to_width(
        self,
        image: Image.Image,
        target_width: int,
        fit_to_width: bool,
    ) -> Image.Image:
        orig_w, orig_h = image.size
        if not fit_to_width:
            return image
        scale = max(1, target_width) / orig_w
        w = max(1, int(orig_w * scale))
        h = max(1, int(orig_h * scale))
        if (w, h) == (orig_w, orig_h):
            return image
        return image.resize((w, h), Image.Resampling.LANCZOS)

    def _photo_from_path(self, path: Path) -> tuple[ImageTk.PhotoImage, int, int]:
        with Image.open(path) as source:
            if source.mode not in ("RGB", "RGBA"):
                img = source.convert("RGB")
            else:
                img = source.copy()
        img = self._scale_image(img)
        return ImageTk.PhotoImage(img), img.width, img.height

    def _clear_pages(self) -> None:
        # Sinaliza cancelamento e incrementa geracao; callbacks antigos serao ignorados.
        self._load_cancel.set()
        self._load_generation = getattr(self, "_load_generation", 0) + 1
        self._load_cancel = threading.Event()
        if self._lazy_after_id:
            self.after_cancel(self._lazy_after_id)
            self._lazy_after_id = None
        if self._page_layout_after_id:
            self.after_cancel(self._page_layout_after_id)
            self._page_layout_after_id = None
        self._pending_page_anchor = None
        self.canvas.delete("page")
        self.canvas.delete("novel")
        self.canvas.delete("placeholder")
        self._page_images.clear()
        self._page_paths.clear()
        self._page_errors.clear()
        self._page_heights.clear()
        self._lazy_requested_pages.clear()
        self._lazy_inflight_pages.clear()
        self._page_queue = None
        self._pages_loaded = 0
        self.loading = False
        self.progress.stop()
        self.progress.set(0)

    def _resize_image_pages(self) -> None:
        self._rerender_all_pages()
        self._schedule_lazy_visible_pages(delay_ms=40)

    def _rerender_all_pages(self) -> None:
        if not self.current_data:
            return
        for i, path_text in enumerate(self._page_paths):
            if not path_text:
                continue
            path = Path(path_text)
            if not path.exists():
                continue
            try:
                photo, _width, height = self._photo_from_path(path)
                self._page_images[i] = photo
                self._page_heights[i] = height
            except Exception:
                pass
        self._redraw_pages()

    def _page_gap(self) -> int:
        if not self.current_data:
            return 2
        try:
            return max(0, int(self.current_data.get("image_gap", 2)))
        except (TypeError, ValueError):
            return 2

    def _soft_continuous_placeholders(self) -> bool:
        return bool(
            self.current_data
            and self.current_data.get("continuous")
            and self.current_data.get("preload_all")
        )

    def _lazy_preload_pages(self) -> int:
        if self.current_data and self.current_data.get("continuous"):
            return max(LAZY_PRELOAD_PAGES, 8)
        return LAZY_PRELOAD_PAGES

    def _lazy_preload_pixels(self) -> int:
        if self.current_data and self.current_data.get("continuous"):
            return max(LAZY_PRELOAD_PIXELS, 3600)
        return LAZY_PRELOAD_PIXELS

    def _start_longstrip_load(self) -> None:
        if not self.current_data:
            return
        count = int(self.current_data["count"])
        cancel = self._load_cancel
        generation = getattr(self, "_load_generation", 0)
        page_queue: queue.Queue[tuple[str, int, object]] = queue.Queue()
        self._page_queue = page_queue
        self._lazy_requested_pages.clear()
        self._lazy_inflight_pages.clear()
        self._create_page_placeholders(count)
        self.header_label.configure(text=f"{self.current_data['label']} - {count} paginas (0/{count})")
        self.loading = False
        self.progress.stop()
        self.progress.set(0)
        self.status(f"Lazy loading ativo - {count} paginas.")
        self._schedule_lazy_visible_pages(delay_ms=0)
        self.after(80, lambda: self._poll_page_queue(page_queue, generation, count, cancel))

    def _schedule_lazy_visible_pages(self, delay_ms: int = 80) -> None:
        if not (self.current_data and self.current_data.get("mode") != "text"):
            return
        if self._lazy_after_id:
            self.after_cancel(self._lazy_after_id)
        self._lazy_after_id = self.after(delay_ms, self._load_visible_pages)

    def _load_visible_pages(self) -> None:
        self._lazy_after_id = None
        if not (self.current_data and self._page_queue):
            return

        generation = getattr(self, "_load_generation", 0)
        cancel = self._load_cancel
        candidates = self._lazy_page_candidates()
        to_load: list[int] = []
        for page_number in candidates:
            index = page_number - 1
            if index < 0 or index >= len(self._page_images):
                continue
            if self._page_images[index] is not None or self._page_errors[index] is not None:
                continue
            if page_number in self._lazy_requested_pages:
                continue
            self._lazy_requested_pages.add(page_number)
            self._lazy_inflight_pages.add(page_number)
            to_load.append(page_number)

        if not to_load:
            return

        self._start_lazy_download_batch(to_load, self._page_queue, generation, cancel)

    def _lazy_page_candidates(self) -> list[int]:
        total = len(self._page_heights)
        if total <= 0:
            return []
        if self.current_data and self.current_data.get("preload_all"):
            return list(range(1, total + 1))

        top = max(0, int(self.canvas.canvasy(0)))
        bottom = top + max(1, self.canvas.winfo_height())
        preload_pixels = self._lazy_preload_pixels()
        preload_top = max(0, top - preload_pixels)
        preload_bottom = bottom + preload_pixels

        first: int | None = None
        last: int | None = None
        y = 0
        gap = self._page_gap()
        for index, height in enumerate(self._page_heights):
            page_number = index + 1
            page_height = max(1, height)
            page_top = y
            page_bottom = y + page_height
            if page_bottom >= preload_top and page_top <= preload_bottom:
                first = page_number if first is None else first
                last = page_number
            y += page_height + gap

        if first is None or last is None:
            return [1]

        preload_pages = self._lazy_preload_pages()
        first = max(1, first - preload_pages)
        last = min(total, last + preload_pages)
        return list(range(first, last + 1))

    def _start_lazy_download_batch(
        self,
        page_numbers: list[int],
        page_queue: queue.Queue[tuple[str, int, object]],
        generation: int,
        cancel: threading.Event,
    ) -> None:
        target_width = max(1, self._reader_width() - 8)
        fit_to_width = bool(self.fit_switch.get())

        async def load_batch_async() -> None:
            workers = min(PAGE_DOWNLOAD_WORKERS, max(1, len(page_numbers)))
            executor = ThreadPoolExecutor(
                max_workers=workers,
                thread_name_prefix="mangatemp-page",
            )
            semaphore = asyncio.Semaphore(workers)

            async def load_one(page_number: int) -> None:
                if cancel.is_set():
                    return
                async with semaphore:
                    if cancel.is_set():
                        return
                    loop = asyncio.get_running_loop()
                    try:
                        local_path = await loop.run_in_executor(
                            executor,
                            self._download_page_to_temp,
                            page_number,
                            target_width,
                            fit_to_width,
                        )
                    except Exception as exc:
                        if not cancel.is_set():
                            page_queue.put(("error", page_number, exc))
                        return
                    if not cancel.is_set():
                        page_queue.put(("ok", page_number, local_path))

            tasks = [
                asyncio.create_task(load_one(page_number))
                for page_number in page_numbers
            ]
            try:
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
                if cancel.is_set():
                    for task in tasks:
                        task.cancel()
            finally:
                executor.shutdown(wait=False, cancel_futures=True)

        def load_batch() -> None:
            try:
                asyncio.run(load_batch_async())
            except Exception as exc:
                if not cancel.is_set():
                    page_queue.put(("batch_error", 0, (page_numbers, exc)))

        self._load_thread = threading.Thread(target=load_batch, daemon=True)
        self._load_thread.start()

    def _download_page_to_temp(
        self,
        page_number: int,
        target_width: int,
        fit_to_width: bool,
    ) -> tuple[Path, Image.Image, int]:
        path, _content_type = self.reader.get_image(page_number)
        with Image.open(path) as source:
            if source.mode not in ("RGB", "RGBA"):
                image = source.convert("RGB")
            else:
                image = source.copy()
        image = self._scale_image_to_width(image, target_width, fit_to_width)
        return path, image, image.height

    def _poll_page_queue(
        self,
        page_queue: queue.Queue[tuple[str, int, object]],
        generation: int,
        total: int,
        cancel: threading.Event,
    ) -> None:
        if generation != getattr(self, "_load_generation", 0) or cancel.is_set():
            return

        processed = 0
        needs_redraw = False
        while processed < PAGE_QUEUE_BATCH:
            try:
                status, page_number, payload = page_queue.get_nowait()
            except queue.Empty:
                break

            if status == "batch_error":
                page_numbers, exc = payload if isinstance(payload, tuple) else ([], RuntimeError(str(payload)))
                error = exc if isinstance(exc, Exception) else RuntimeError(str(exc))
                for failed_page in page_numbers:
                    self._lazy_inflight_pages.discard(failed_page)
                    self._append_page_error(failed_page, total, error, generation, redraw=False)
                    processed += 1
                    if processed >= PAGE_QUEUE_BATCH:
                        break
                needs_redraw = True
                continue

            self._lazy_inflight_pages.discard(page_number)
            if status == "ok":
                self._append_page(payload, page_number, total, generation, redraw=False)
            else:
                exc = payload if isinstance(payload, Exception) else RuntimeError(str(payload))
                self._append_page_error(page_number, total, exc, generation, redraw=False)
            needs_redraw = True
            processed += 1

        if needs_redraw:
            self._schedule_page_layout()
            self._schedule_lazy_visible_pages(delay_ms=30)

        if self._pages_loaded < total:
            delay = 40 if self._lazy_inflight_pages else 250
            self.after(delay, lambda: self._poll_page_queue(page_queue, generation, total, cancel))

    def _create_page_placeholders(self, total: int) -> None:
        self.canvas.delete("placeholder")
        self.canvas.delete("page")
        self._page_images = [None] * total
        self._page_paths = [""] * total
        self._page_errors = [None] * total
        self._page_heights = [self._estimated_page_height()] * total
        self._redraw_pages()

    def _estimated_page_height(self) -> int:
        if self.current_data and self.current_data.get("continuous"):
            try:
                aspect = float(self.current_data.get("estimated_aspect") or 0.97)
            except (TypeError, ValueError):
                aspect = 0.97
            return max(120, int((self._reader_width() - 8) * max(0.3, aspect)))
        return max(PAGE_PLACEHOLDER_MIN_HEIGHT, int((self._reader_width() - 8) * 1.35))

    def _redraw_pages(self) -> None:
        self.canvas.delete("page")
        width = self._reader_width()
        y = 0
        gap = self._page_gap()
        for index, photo in enumerate(self._page_images):
            page_number = index + 1
            error = self._page_errors[index] if index < len(self._page_errors) else None
            height = self._page_heights[index] if index < len(self._page_heights) else 120

            if photo is not None:
                image_width = photo.width()
                x = max(0, (width - image_width) // 2)
                self.canvas.create_image(
                    x,
                    y,
                    anchor="nw",
                    image=photo,
                    tags=("page", f"page-{page_number}", f"page-image-{page_number}"),
                )
                height = photo.height()
            elif error:
                self.canvas.create_rectangle(
                    0,
                    y,
                    width,
                    y + max(90, height),
                    fill=DANGER,
                    outline="#3a1c22",
                    tags=("page", f"page-{page_number}", f"page-box-{page_number}"),
                )
                self.canvas.create_text(
                    16,
                    y + 18,
                    text=f"Erro na pagina {page_number}: {error}",
                    anchor="nw",
                    fill="#f6a2ad",
                    width=max(280, width - 32),
                    tags=("page", f"page-{page_number}", f"page-text-{page_number}"),
                )
                height = max(90, height)
            else:
                soft_placeholder = self._soft_continuous_placeholders()
                label = "" if soft_placeholder else (
                    f"Baixando pagina {page_number}..."
                    if page_number in self._lazy_requested_pages
                    else f"Pagina {page_number}"
                )
                self.canvas.create_rectangle(
                    0,
                    y,
                    width,
                    y + height,
                    fill=CANVAS_BG if soft_placeholder else PANEL_BG,
                    outline=CANVAS_BG if soft_placeholder else BORDER,
                    tags=("page", f"page-{page_number}", f"page-box-{page_number}"),
                )
                self.canvas.create_text(
                    width // 2,
                    y + height // 2,
                    text=label,
                    anchor="center",
                    fill=CANVAS_BG if soft_placeholder else MUTED,
                    tags=("page", f"page-{page_number}", f"page-text-{page_number}"),
                )

            y += height + gap

        self.canvas.configure(scrollregion=(0, 0, width, max(y, self.canvas.winfo_height())))

    def _capture_page_anchor(self) -> tuple[int, int] | None:
        if not self._page_heights:
            return None
        top = max(0, int(self.canvas.canvasy(0)))
        y = 0
        gap = self._page_gap()
        for index, height in enumerate(self._page_heights):
            page_height = max(1, height)
            if top < y + page_height + gap:
                return index, top - y
            y += page_height + gap
        return len(self._page_heights) - 1, 0

    def _restore_page_anchor(self, anchor: tuple[int, int] | None) -> None:
        if not anchor or not self._page_heights:
            return
        index, offset = anchor
        index = max(0, min(index, len(self._page_heights) - 1))
        gap = self._page_gap()
        target_y = sum(max(1, height) + gap for height in self._page_heights[:index])
        target_y += max(0, offset)
        scrollregion = self.canvas.cget("scrollregion")
        try:
            total_height = float(str(scrollregion).split()[-1])
        except (TypeError, ValueError, IndexError):
            total_height = 0
        if total_height > 0:
            self.canvas.yview_moveto(min(1.0, target_y / total_height))

    def _schedule_page_layout(self, delay_ms: int = READER_LAYOUT_DELAY_MS) -> None:
        if self._pending_page_anchor is None:
            self._pending_page_anchor = self._capture_page_anchor()
        if self._page_layout_after_id:
            self.after_cancel(self._page_layout_after_id)
        self._page_layout_after_id = self.after(delay_ms, self._flush_page_layout)

    def _flush_page_layout(self) -> None:
        self._page_layout_after_id = None
        remaining = self._reader_scroll_active_until - time.monotonic()
        if remaining > 0:
            self._page_layout_after_id = self.after(
                max(20, int(remaining * 1000)),
                self._flush_page_layout,
            )
            return
        anchor = self._pending_page_anchor
        self._pending_page_anchor = None
        self._reposition_page_items()
        self._restore_page_anchor(anchor)

    def _reposition_page_items(self) -> None:
        if not (self._page_images or self._page_errors or self._page_heights):
            self._refresh_scrollregion()
            return

        width = self._reader_width()
        y = 0
        gap = self._page_gap()
        total = max(len(self._page_images), len(self._page_heights), len(self._page_errors))
        for index in range(total):
            photo = self._page_images[index] if index < len(self._page_images) else None
            page_number = index + 1
            error = self._page_errors[index] if index < len(self._page_errors) else None
            height = self._page_heights[index] if index < len(self._page_heights) else 120

            if photo is not None:
                image_items = self.canvas.find_withtag(f"page-image-{page_number}")
                box_items = self.canvas.find_withtag(f"page-box-{page_number}")
                text_items = self.canvas.find_withtag(f"page-text-{page_number}")
                for item in (*box_items, *text_items):
                    self.canvas.delete(item)
                x = max(0, (width - photo.width()) // 2)
                if image_items:
                    self.canvas.coords(image_items[0], x, y)
                    self.canvas.itemconfigure(image_items[0], image=photo)
                else:
                    self.canvas.create_image(
                        x,
                        y,
                        anchor="nw",
                        image=photo,
                        tags=("page", f"page-{page_number}", f"page-image-{page_number}"),
                    )
                height = photo.height()
            else:
                image_items = self.canvas.find_withtag(f"page-image-{page_number}")
                for item in image_items:
                    self.canvas.delete(item)
                box_items = self.canvas.find_withtag(f"page-box-{page_number}")
                text_items = self.canvas.find_withtag(f"page-text-{page_number}")
                if error:
                    height = max(90, height)
                    if box_items:
                        self.canvas.coords(box_items[0], 0, y, width, y + height)
                        self.canvas.itemconfigure(box_items[0], fill=DANGER, outline="#3a1c22")
                    else:
                        self.canvas.create_rectangle(
                            0,
                            y,
                            width,
                            y + height,
                            fill=DANGER,
                            outline="#3a1c22",
                            tags=("page", f"page-{page_number}", f"page-box-{page_number}"),
                        )
                    if text_items:
                        self.canvas.coords(text_items[0], 16, y + 18)
                        self.canvas.itemconfigure(
                            text_items[0],
                            text=f"Erro na pagina {page_number}: {error}",
                            fill="#f6a2ad",
                            anchor="nw",
                            width=max(280, width - 32),
                        )
                    else:
                        self.canvas.create_text(
                            16,
                            y + 18,
                            text=f"Erro na pagina {page_number}: {error}",
                            anchor="nw",
                            fill="#f6a2ad",
                            width=max(280, width - 32),
                            tags=("page", f"page-{page_number}", f"page-text-{page_number}"),
                        )
                else:
                    soft_placeholder = self._soft_continuous_placeholders()
                    label = "" if soft_placeholder else (
                        f"Baixando pagina {page_number}..."
                        if page_number in self._lazy_requested_pages
                        else f"Pagina {page_number}"
                    )
                    if box_items:
                        self.canvas.coords(box_items[0], 0, y, width, y + height)
                        self.canvas.itemconfigure(
                            box_items[0],
                            fill=CANVAS_BG if soft_placeholder else PANEL_BG,
                            outline=CANVAS_BG if soft_placeholder else BORDER,
                        )
                    else:
                        self.canvas.create_rectangle(
                            0,
                            y,
                            width,
                            y + height,
                            fill=CANVAS_BG if soft_placeholder else PANEL_BG,
                            outline=CANVAS_BG if soft_placeholder else BORDER,
                            tags=("page", f"page-{page_number}", f"page-box-{page_number}"),
                        )
                    if text_items:
                        self.canvas.coords(text_items[0], width // 2, y + height // 2)
                        self.canvas.itemconfigure(
                            text_items[0],
                            text=label,
                            fill=CANVAS_BG if soft_placeholder else MUTED,
                            anchor="center",
                            width=0,
                        )
                    else:
                        self.canvas.create_text(
                            width // 2,
                            y + height // 2,
                            text=label,
                            anchor="center",
                            fill=CANVAS_BG if soft_placeholder else MUTED,
                            tags=("page", f"page-{page_number}", f"page-text-{page_number}"),
                        )

            y += height + gap

        self.canvas.configure(scrollregion=(0, 0, width, max(y, self.canvas.winfo_height())))

    def _append_page(
        self,
        payload,
        page_number: int,
        total: int,
        generation: int = 0,
        redraw: bool = True,
    ) -> None:
        if generation != getattr(self, "_load_generation", 0):
            return
        if self._pending_page_anchor is None:
            self._pending_page_anchor = self._capture_page_anchor()
        try:
            if isinstance(payload, tuple) and len(payload) == 3:
                path, image, height = payload
                photo = ImageTk.PhotoImage(image)
            else:
                path = Path(payload)
                photo, _width, height = self._photo_from_path(path)
        except Exception as exc:
            self._append_page_error(page_number, total, exc, generation, redraw=redraw)
            return

        while len(self._page_images) < page_number:
            self._page_images.append(None)
            self._page_paths.append("")
            self._page_errors.append(None)
            self._page_heights.append(self._estimated_page_height())
        already_done = (
            self._page_images[page_number - 1] is not None
            or self._page_errors[page_number - 1] is not None
        )
        self._page_images[page_number - 1] = photo
        self._page_paths[page_number - 1] = str(path)
        self._page_errors[page_number - 1] = None
        self._page_heights[page_number - 1] = height
        if not already_done:
            self._pages_loaded += 1
        if redraw:
            self._schedule_page_layout()
        self.status(f"Carregando... {self._pages_loaded}/{total} paginas")
        if self.current_data:
            self.header_label.configure(
                text=f"{self.current_data['label']} - {total} paginas ({self._pages_loaded}/{total})"
            )

        if self._pages_loaded == total:
            if self.current_data:
                self.header_label.configure(text=f"{self.current_data['label']} - {total} paginas")
            self.status(f"Capitulo completo - {total} paginas. Cache temporaria ativa.")
            self.loading = False
            self.progress.stop()
            self.progress.set(0)
            self.set_controls_state("normal")
            self.refresh_nav_state()

    def _append_page_error(
        self,
        page_number: int,
        total: int,
        exc: Exception,
        generation: int = 0,
        redraw: bool = True,
    ) -> None:
        if generation != getattr(self, "_load_generation", 0):
            return
        if self._pending_page_anchor is None:
            self._pending_page_anchor = self._capture_page_anchor()
        while len(self._page_images) < page_number:
            self._page_images.append(None)
            self._page_paths.append("")
            self._page_errors.append(None)
            self._page_heights.append(self._estimated_page_height())
        already_done = (
            self._page_images[page_number - 1] is not None
            or self._page_errors[page_number - 1] is not None
        )
        self._page_paths[page_number - 1] = ""
        self._page_errors[page_number - 1] = str(exc)
        self._page_heights[page_number - 1] = 100
        if not already_done:
            self._pages_loaded += 1
        if redraw:
            self._schedule_page_layout()
        self.status(f"Carregando... {self._pages_loaded}/{total} paginas")
        if self.current_data:
            self.header_label.configure(
                text=f"{self.current_data['label']} - {total} paginas ({self._pages_loaded}/{total})"
            )
        if self._pages_loaded == total:
            if self.current_data:
                self.header_label.configure(text=f"{self.current_data['label']} - {total} paginas")
            self.loading = False
            self.progress.stop()
            self.progress.set(0)
            self.set_controls_state("normal")
            self.refresh_nav_state()

    def close_chapter(self) -> None:
        self._clear_pages()
        self.reader.close_chapter()
        self.current_data = None
        self._show_placeholder("Cache apagada. Abra outro capitulo quando quiser.")
        self.canvas.yview_moveto(0)
        self.header_label.configure(text="Nenhum capitulo aberto")
        self.prev_chapter_button.configure(state="disabled")
        self.next_chapter_button.configure(state="disabled")
        self.top_prev_button.configure(state="disabled")
        self.top_next_button.configure(state="disabled")
        self.status("Cache do capitulo apagada.")
        self._show_home_view()

    def run_background(
        self,
        message: str,
        work,
        done,
        disable_reader_nav: bool = True,
    ) -> None:
        if self.loading:
            # Cancela carga de longstrip em andamento para aceitar nova acao
            self._clear_pages()
        if self.loading:
            return  # outra operacao de background real em andamento

        self.loading = True
        self.status(message)
        self.progress.start()
        self.set_controls_state("disabled", disable_reader_nav=disable_reader_nav)
        result_queue: queue.Queue[tuple[str, object]] = queue.Queue()

        def runner() -> None:
            try:
                result = work()
            except Exception as exc:
                result_queue.put(("error", exc))
                return
            result_queue.put(("ok", result))

        threading.Thread(target=runner, daemon=True).start()
        self.after(100, lambda: self.poll_background(result_queue, done))

    def poll_background(self, result_queue: queue.Queue, done) -> None:
        try:
            status, payload = result_queue.get_nowait()
        except queue.Empty:
            if self.loading:
                self.after(100, lambda: self.poll_background(result_queue, done))
            return

        if status == "ok":
            self.on_background_done(done, payload)
        else:
            self.on_background_error(payload)

    def on_background_done(self, done, result) -> None:
        self.loading = False
        self.progress.stop()
        self.progress.set(0)
        self.set_controls_state("normal")
        try:
            done(result)
        except Exception as exc:
            self.on_background_error(exc)
            return
        finally:
            self.refresh_nav_state()

    def on_background_error(self, exc: Exception) -> None:
        self.loading = False
        self._last_chapter_fetch_key = None
        self.progress.stop()
        self.progress.set(0)
        self.set_controls_state("normal")
        self.log_exception(exc)
        self.status(f"Erro: {exc}")
        if hasattr(self, "home_status_label") and self.home_area.winfo_ismapped():
            self.home_status_label.configure(text=f"Erro: {exc}")
        self.refresh_nav_state()

    def set_controls_state(self, state: str, disable_reader_nav: bool = True) -> None:
        widgets = [
            self.search_entry,
            self.search_button,
            self.search_menu,
            self.manga_entry,
            self.lang_entry,
            self.fetch_button,
            self.chapter_menu,
            self.open_button,
            self.close_chapter_button,
            self.fit_switch,
            self.global_search_entry,
            self.global_search_button,
            self.top_close_button,
        ]
        if disable_reader_nav:
            widgets.extend([
                self.prev_chapter_button,
                self.next_chapter_button,
                self.top_prev_button,
                self.top_next_button,
            ])

        for widget in widgets:
            try:
                widget.configure(state=state)
            except Exception:
                pass

    def status(self, message: str) -> None:
        self.status_label.configure(text=message)

    def log_exception(self, exc: Exception) -> None:
        try:
            with LOG_FILE.open("a", encoding="utf-8") as handle:
                handle.write("\n--- erro ---\n")
                handle.write("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
        except Exception:
            pass

    def refresh_nav_state(self) -> None:
        if not self.current_data:
            self.prev_chapter_button.configure(state="disabled")
            self.next_chapter_button.configure(state="disabled")
            self.top_prev_button.configure(state="disabled")
            self.top_next_button.configure(state="disabled")
            return
        self.prev_chapter_button.configure(
            state="normal" if self.current_data.get("previous") else "disabled"
        )
        self.next_chapter_button.configure(
            state="normal" if self.current_data.get("next") else "disabled"
        )
        self.top_prev_button.configure(
            state="normal" if self.current_data.get("previous") else "disabled"
        )
        self.top_next_button.configure(
            state="normal" if self.current_data.get("next") else "disabled"
        )

    def on_close(self) -> None:
        self.reader.close()
        self.destroy()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Popup desktop para leitura temporaria.")
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
        default=DEFAULT_READFULL_API_URL,
        help="URL base da API ReadFull/NovelFull. Padrao: https://readfullapi.herokuapp.com",
    )
    return parser


def main() -> None:
    app = ReaderApp(build_parser().parse_args())
    app.mainloop()


if __name__ == "__main__":
    main()
