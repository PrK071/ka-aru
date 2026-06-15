from __future__ import annotations

import argparse
import os
import re
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable
from urllib.parse import quote, unquote, urljoin, urlparse

from mangafire_vrf import generate_vrf, mangafire_id_part

import cloudscraper
import requests
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


BASE_URL = "https://mangafire.to"
READER_FALLBACK_SELECTORS = "#page-wrapper, div.pages, main"

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) "
        "Gecko/20100101 Firefox/125.0"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
}

_USERNAME = os.environ.get("USERNAME") or os.environ.get("USER") or "User"

LIBREWOLF_PATHS = [
    r"C:\Program Files\LibreWolf\librewolf.exe",
    r"C:\Program Files (x86)\LibreWolf\librewolf.exe",
    rf"C:\Users\{_USERNAME}\AppData\Local\LibreWolf\librewolf.exe",
    "/usr/bin/librewolf",
    "/usr/local/bin/librewolf",
    "/snap/bin/librewolf",
]

IMAGE_ATTRS = [
    "currentSrc",
    "src",
    "data-src",
    "data-original",
    "data-lazy-src",
    "data-url",
    "data-cfsrc",
]

RESOURCE_URLS_JS = """
return performance.getEntriesByType("resource").map((entry) => entry.name);
"""

COLLECT_IMAGE_URLS_JS = r"""
(function(attrs) {
  const urls = [];
  const seen = new Set();

  const add = (value) => {
    if (!value || typeof value !== "string") return;
    const trimmed = value.trim();
    if (!trimmed) return;

    let url;
    try { url = new URL(trimmed, document.baseURI).href; } catch { return; }
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
        score = parseInt(descriptor.slice(0, -1), 10) || 0;
      } else if (descriptor.endsWith("x")) {
        score = (parseFloat(descriptor.slice(0, -1)) || 0) * 1000;
      }

      if (score > bestScore) {
        bestScore = score;
        bestUrl = parts[0];
      }
    }

    return bestUrl;
  };

  const addBackgroundUrls = (element) => {
    const values = [
      element.getAttribute("style") || "",
      window.getComputedStyle(element).backgroundImage || "",
    ];

    for (const value of values) {
      for (const match of value.matchAll(/url\((['"]?)(.*?)\1\)/g)) {
        add(match[2]);
      }
    }
  };

  const selectors = [
    "#page-wrapper",
    "div.pages",
    ".chapter-reader",
    ".reader-area",
    "main",
  ];

  const roots = selectors
    .map((selector) => document.querySelector(selector))
    .filter(Boolean);

  if (roots.length === 0) roots.push(document.body);

  for (const root of roots) {
    const candidates = [];
    if (root.matches("img, source")) candidates.push(root);
    candidates.push(...root.querySelectorAll("img, source"));

    for (const element of candidates) {
      for (const attr of attrs) {
        add(element[attr]);
        add(element.getAttribute(attr));
      }

      add(pickFromSrcset(element.getAttribute("srcset")));
      add(pickFromSrcset(element.getAttribute("data-srcset")));
      addBackgroundUrls(element);
    }
  }

  return urls;
})(arguments[0])
"""


@dataclass(frozen=True)
class Chapter:
    url: str
    number: float | None = None
    number_text: str | None = None
    chapter_id: str | None = None
    title: str | None = None

    @property
    def label(self) -> str:
        if self.number_text:
            return f"chapter-{self.number_text}"
        if self.number is not None:
            return f"chapter-{format_chapter_number(self.number)}"
        return clean_filename(Path(urlparse(self.url).path).name or "chapter")


class ChapterLinkParser(HTMLParser):
    def __init__(self, lang: str | None = None) -> None:
        super().__init__(convert_charrefs=True)
        self.lang = normalize_lang(lang) if lang else None
        self.chapters: list[Chapter] = []
        self._seen: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return

        data = {name.lower(): value for name, value in attrs if value is not None}
        href = data.get("href")
        if not href or "/read/" not in href or "/chapter-" not in href:
            return

        url = urljoin(BASE_URL, href)
        url_lower = url.lower()
        if self.lang and f"/{self.lang}/" not in url_lower:
            return

        if url in self._seen:
            return

        number_text = data.get("data-number") or chapter_number_text_from_url(url)
        number = parse_chapter_number(number_text)
        self._seen.add(url)
        self.chapters.append(
            Chapter(
                url=url,
                number=number,
                number_text=number_text,
                chapter_id=data.get("data-id"),
                title=data.get("title"),
            )
        )


def normalize_lang(value: str) -> str:
    return value.strip().lower()


def parse_chapter_number(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def format_chapter_number(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return str(value).rstrip("0").rstrip(".")


def clean_filename(value: str, fallback: str = "manga") -> str:
    value = re.sub(r"[^\w\s.-]", "", value, flags=re.UNICODE).strip()
    value = re.sub(r"\s+", "-", value)
    return value or fallback


def filename_from_url(url: str, index: int, content_type: str | None = None) -> str:
    parsed = urlparse(url)
    suffix = Path(unquote(parsed.path)).suffix.lower()
    if not suffix or len(suffix) > 5:
        suffix = {
            "image/jpeg": ".jpg",
            "image/jpg": ".jpg",
            "image/png": ".png",
            "image/webp": ".webp",
            "image/gif": ".gif",
            "image/avif": ".avif",
        }.get((content_type or "").split(";")[0].lower(), ".jpg")
    return f"{index:03d}{suffix}"


def slug_from_url(url: str) -> str | None:
    match = re.search(r"mangafire\.to/(?:read|manga)/([^/?#]+)", url)
    return match.group(1) if match else None


def manga_page_url(slug: str) -> str:
    return f"{BASE_URL}/manga/{slug}"


def chapter_number_text_from_url(url: str) -> str | None:
    match = re.search(r"chapter-([\d.]+)", url, re.IGNORECASE)
    return match.group(1) if match else None


def chapter_number_from_url(url: str) -> float | None:
    return parse_chapter_number(chapter_number_text_from_url(url))


def chapter_url_from_number(slug: str, lang: str, number: float | str) -> str:
    if isinstance(number, float):
        number_text = format_chapter_number(number)
    else:
        number_text = str(number).strip()

    return f"{BASE_URL}/read/{slug}/{normalize_lang(lang)}/chapter-{number_text}"


def find_librewolf(custom_path: str | None = None) -> str:
    import shutil

    if custom_path:
        if Path(custom_path).exists():
            return custom_path
        raise SystemExit(f"LibreWolf nao encontrado em: {custom_path}")

    found = shutil.which("librewolf")
    if found:
        return found

    for path in LIBREWOLF_PATHS:
        if Path(path).exists():
            return path

    raise SystemExit(
        "LibreWolf nao encontrado automaticamente.\n"
        r'Informe com: --librewolf-path "C:\...\librewolf.exe"'
    )


def build_driver(args: argparse.Namespace) -> webdriver.Firefox:
    opts = FirefoxOptions()
    binary = find_librewolf(args.librewolf_path)
    print(f"[browser] LibreWolf: {binary}")

    opts.binary_location = binary
    if not args.show_browser:
        opts.add_argument("--headless")

    opts.set_preference("general.useragent.override", DEFAULT_HEADERS["User-Agent"])
    opts.set_preference("intl.accept_languages", "pt-BR, pt, en-US, en")
    opts.set_preference("dom.webdriver.enabled", False)
    opts.set_preference("useAutomationExtension", False)
    opts.page_load_strategy = "eager"

    service = FirefoxService(log_output=os.devnull)
    driver = webdriver.Firefox(options=opts, service=service)
    driver.set_window_size(1280, 1800)
    driver.set_page_load_timeout(args.timeout + 20)
    return driver


def wait_for_selector(driver: webdriver.Firefox, css: str, timeout: int) -> bool:
    try:
        WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, css))
        )
        return True
    except TimeoutException:
        return False


def clear_resource_timings(driver: webdriver.Firefox) -> None:
    try:
        driver.execute_script("performance.clearResourceTimings();")
    except WebDriverException:
        pass


def resource_urls(driver: webdriver.Firefox) -> list[str]:
    try:
        result = driver.execute_script(RESOURCE_URLS_JS)
    except WebDriverException:
        return []
    return [url for url in (result or []) if isinstance(url, str)]


def wait_for_resource_url(
    driver: webdriver.Firefox,
    timeout: int,
    label: str,
    predicate,
) -> str:
    def find_url(current_driver):
        for url in reversed(resource_urls(current_driver)):
            if predicate(url):
                return url
        return False

    try:
        return WebDriverWait(driver, timeout).until(find_url)
    except TimeoutException as exc:
        raise TimeoutException(f"Timeout aguardando endpoint AJAX de {label}.") from exc


def is_chapter_list_api(url: str) -> bool:
    url_lower = url.lower()
    return (
        "/ajax/read/" in url_lower
        and "/chapter/" in url_lower
        and "/ajax/read/chapter/" not in url_lower
        and "vrf=" in url_lower
    )


def is_image_list_api(url: str, chapter_id: str | None = None) -> bool:
    url_lower = url.lower()
    if "/ajax/read/chapter/" not in url_lower or "vrf=" not in url_lower:
        return False
    if chapter_id and f"/chapter/{chapter_id}" not in url_lower:
        return False
    return True


def create_cloudscraper() -> cloudscraper.CloudScraper:
    scraper = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "mobile": False},
        delay=0,
    )
    scraper.headers.update(DEFAULT_HEADERS)
    return scraper


def session_from_scraper(scraper: cloudscraper.CloudScraper, referer: str) -> requests.Session:
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)
    session.headers.update(
        {
            "Referer": referer,
            "Origin": BASE_URL,
            "X-Requested-With": "XMLHttpRequest",
        }
    )
    session.cookies.update(scraper.cookies.get_dict())
    return session


def request_mangafire_json(
    scraper: cloudscraper.CloudScraper,
    url: str,
    referer: str,
    timeout: int,
) -> dict:
    response = scraper.get(
        url,
        timeout=timeout,
        headers={
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Referer": referer,
            "X-Requested-With": "XMLHttpRequest",
        },
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("status") != 200:
        message = payload.get("message") or payload.get("messages") or payload
        raise RuntimeError(f"Resposta invalida do MangaFire: {message}")
    return payload


def chapter_list_api_url(slug: str, lang: str) -> tuple[str, str]:
    normalized_lang = normalize_lang(lang)
    id_part = mangafire_id_part(slug)
    vrf = generate_vrf(f"{id_part}@chapter@{normalized_lang}")
    return (
        f"{BASE_URL}/ajax/read/{id_part}/chapter/{normalized_lang}?vrf={quote(vrf, safe='')}",
        f"{BASE_URL}/manga/{slug}",
    )


def chapter_images_api_url(chapter_id: str) -> tuple[str, str]:
    vrf = generate_vrf(f"chapter@{chapter_id}")
    return (
        f"{BASE_URL}/ajax/read/chapter/{chapter_id}?vrf={quote(vrf, safe='')}",
        f"{BASE_URL}/read/chapter/{chapter_id}",
    )


def fetch_chapters_http(
    scraper: cloudscraper.CloudScraper,
    slug: str,
    lang: str,
    timeout: int,
) -> list[Chapter]:
    api_url, referer = chapter_list_api_url(slug, lang)
    payload = request_mangafire_json(scraper, api_url, referer, timeout)
    chapters = extract_chapters_from_payload(payload)
    if not chapters:
        raise RuntimeError("A lista de capitulos veio vazia.")
    return chapters


def fetch_chapter_images_http(
    scraper: cloudscraper.CloudScraper,
    chapter_id: str,
    referer: str,
    timeout: int,
) -> list[str]:
    api_url, default_referer = chapter_images_api_url(chapter_id)
    payload = request_mangafire_json(
        scraper,
        api_url,
        referer or default_referer,
        timeout,
    )
    image_urls = extract_image_urls(payload)
    if not image_urls:
        raise RuntimeError("O MangaFire nao retornou imagens para este capitulo.")
    return image_urls


def session_from_driver(driver: webdriver.Firefox, referer: str) -> requests.Session:
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)
    session.headers.update(
        {
            "Referer": referer,
            "Origin": BASE_URL,
            "X-Requested-With": "XMLHttpRequest",
        }
    )

    for cookie in driver.get_cookies():
        kwargs = {"path": cookie.get("path", "/")}
        if cookie.get("domain"):
            kwargs["domain"] = cookie["domain"]
        session.cookies.set(cookie["name"], cookie["value"], **kwargs)

    return session


def request_json(
    session: requests.Session,
    url: str,
    referer: str,
    timeout: int,
) -> dict:
    response = session.get(
        url,
        timeout=timeout,
        headers={
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Referer": referer,
        },
    )
    response.raise_for_status()
    payload = response.json()

    if payload.get("status") != 200:
        message = payload.get("message") or payload.get("messages") or payload
        raise RuntimeError(f"Resposta invalida do MangaFire: {message}")

    return payload


def parse_chapters_from_html(html: str, lang: str | None = None) -> list[Chapter]:
    parser = ChapterLinkParser(lang=lang)
    parser.feed(html or "")
    return sorted(
        parser.chapters,
        key=lambda chapter: (
            chapter.number is None,
            chapter.number if chapter.number is not None else 0,
            chapter.url,
        ),
    )


def extract_chapters_from_payload(payload: dict) -> list[Chapter]:
    result = payload.get("result") or {}
    return parse_chapters_from_html(result.get("html") or "")


def extract_image_urls(payload: dict) -> list[str]:
    result = payload.get("result") or {}
    images = result.get("images") or []
    urls: list[str] = []

    for item in images:
        if isinstance(item, str):
            url = item
        elif isinstance(item, (list, tuple)) and item:
            url = item[0]
        else:
            continue

        if isinstance(url, str) and url.startswith(("http://", "https://")):
            urls.append(url)

    return urls


def collect_dom_image_urls(driver: webdriver.Firefox) -> list[str]:
    result = driver.execute_script(COLLECT_IMAGE_URLS_JS, IMAGE_ATTRS)
    return [url for url in (result or []) if isinstance(url, str)]


def scroll_to_load_dom_images(driver, pause, max_scrolls, stable_rounds) -> list[str]:
    stable_count = 0
    last_count = -1
    last_height = -1
    current_y = 0

    for _ in range(max_scrolls):
        urls = collect_dom_image_urls(driver)
        height = int(
            driver.execute_script(
                "return Math.max(document.body.scrollHeight, document.documentElement.scrollHeight)"
            )
            or 0
        )
        viewport = int(driver.execute_script("return window.innerHeight") or 900)
        at_bottom = current_y + viewport >= height

        if len(urls) == last_count and height == last_height and at_bottom:
            stable_count += 1
        else:
            stable_count = 0

        if stable_count >= stable_rounds:
            break

        last_count = len(urls)
        last_height = height
        current_y = min(current_y + max(300, int(viewport * 0.85)), height)
        driver.execute_script("window.scrollTo(0, arguments[0])", current_y)
        time.sleep(pause)

    time.sleep(pause)
    return collect_dom_image_urls(driver)


def save_debug(driver: webdriver.Firefox, reason: str) -> None:
    ss_path = Path("debug_screenshot.png")
    try:
        driver.save_screenshot(str(ss_path))
        print(f"  Screenshot salvo em: {ss_path.resolve()}")
    except Exception:
        pass

    try:
        current_url = driver.current_url
        title = driver.title
    except Exception:
        current_url = "(indisponivel)"
        title = "(indisponivel)"

    print(f"  AVISO: {reason}")
    print(f"  URL atual: {current_url}")
    print(f"  Titulo: {title}")

    try:
        interesting = [
            url
            for url in resource_urls(driver)
            if "ajax/read" in url or "mfcdn" in url or "chapter" in url
        ][-10:]
        if interesting:
            print("  Ultimos recursos relevantes:")
            for url in interesting:
                print(f"    {url}")
    except Exception:
        pass


def get_chapter_list_from_reader(
    driver: webdriver.Firefox,
    seed_reader_url: str,
    args: argparse.Namespace,
) -> list[Chapter]:
    print(f"  Abrindo leitor para obter lista: {seed_reader_url}")
    clear_resource_timings(driver)
    driver.get(seed_reader_url)

    api_url = wait_for_resource_url(
        driver,
        args.timeout,
        "lista de capitulos",
        is_chapter_list_api,
    )

    session = session_from_driver(driver, seed_reader_url)
    payload = request_json(session, api_url, seed_reader_url, args.timeout)
    chapters = extract_chapters_from_payload(payload)

    if not chapters:
        raise RuntimeError("A lista de capitulos veio vazia.")

    return chapters


def get_chapter_list_from_manga_page(url: str, lang: str, timeout: int) -> list[Chapter]:
    scraper = create_cloudscraper()
    response = scraper.get(
        url,
        timeout=timeout,
        headers=DEFAULT_HEADERS,
    )
    response.raise_for_status()
    return parse_chapters_from_html(response.text, lang=lang)


def iter_downloads(
    session: requests.Session,
    urls: Iterable[str],
    output_dir: Path,
    delay: float,
    timeout: int,
) -> Iterable[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)

    for index, url in enumerate(urls, start=1):
        response = session.get(
            url,
            timeout=timeout,
            headers={
                "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            },
        )
        response.raise_for_status()

        filename = filename_from_url(url, index, response.headers.get("Content-Type"))
        target = output_dir / filename
        target.write_bytes(response.content)
        yield target

        if delay > 0:
            time.sleep(delay)


def download_chapter(
    driver: webdriver.Firefox,
    chapter: Chapter,
    output_root: Path,
    args: argparse.Namespace,
) -> None:
    print(f"\n[capitulo] {chapter.label}  ->  {chapter.url}")

    image_urls: list[str] = []
    session = session_from_driver(driver, chapter.url)

    if chapter.chapter_id:
        try:
            scraper = create_cloudscraper()
            image_urls = fetch_chapter_images_http(
                scraper,
                chapter.chapter_id,
                chapter.url,
                args.timeout,
            )
            session = session_from_scraper(scraper, chapter.url)
        except Exception:
            image_urls = []

    if not image_urls:
        clear_resource_timings(driver)
        driver.get(chapter.url)
        session = session_from_driver(driver, chapter.url)

    try:
        if not image_urls:
            api_url = wait_for_resource_url(
                driver,
                args.timeout,
                "imagens do capitulo",
                lambda url: is_image_list_api(url, chapter.chapter_id),
            )
            payload = request_json(session, api_url, chapter.url, args.timeout)
            image_urls = extract_image_urls(payload)
    except Exception as exc:
        print(f"  Nao consegui ler o JSON do leitor: {exc}")
        print("  Tentando fallback pelo DOM renderizado...")
        if wait_for_selector(driver, READER_FALLBACK_SELECTORS, args.timeout):
            image_urls = scroll_to_load_dom_images(
                driver,
                args.scroll_pause,
                args.max_scrolls,
                args.stable_rounds,
            )

    if not image_urls:
        save_debug(driver, "nenhuma imagem encontrada para este capitulo.")
        print("  Se a pagina abriu em branco ou foi para a home, tente --show-browser.")
        return

    print(f"  {len(image_urls)} imagens encontradas.")

    if args.dry_run:
        for url in image_urls:
            print(f"  {url}")
        return

    output_dir = output_root / clean_filename(chapter.label)
    for target in iter_downloads(
        session,
        image_urls,
        output_dir,
        args.delay,
        args.timeout,
    ):
        print(f"  salvo: {target}")

    print(f"  concluido: {output_dir}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scraper para MangaFire usando LibreWolf via Selenium."
    )
    parser.add_argument("url", help="URL do manga ou capitulo no MangaFire.")
    parser.add_argument("--lang", default="pt-br", help="Idioma. Padrao: pt-br")
    parser.add_argument("--from-chapter", type=float, default=None, metavar="N")
    parser.add_argument("--to-chapter", type=float, default=None, metavar="N")
    parser.add_argument("--only-chapter", type=float, default=None, metavar="N")
    parser.add_argument("-o", "--output", default="downloads")
    parser.add_argument("--manga-name", default=None)
    parser.add_argument("--librewolf-path", default=None, metavar="PATH")
    parser.add_argument("--show-browser", action="store_true")
    parser.add_argument("--delay", type=float, default=0.5)
    parser.add_argument("--scroll-pause", type=float, default=1.5)
    parser.add_argument("--max-scrolls", type=int, default=120)
    parser.add_argument("--stable-rounds", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--chapter-pause", type=float, default=2.0)
    return parser


def chapter_in_range(chapter: Chapter, args: argparse.Namespace) -> bool:
    number = chapter.number
    if number is None:
        return False
    if args.from_chapter is not None and number < args.from_chapter:
        return False
    if args.to_chapter is not None and number > args.to_chapter:
        return False
    return True


def choose_seed_reader_url(
    input_url: str,
    slug: str,
    lang: str,
    args: argparse.Namespace,
) -> str:
    if chapter_number_from_url(input_url) is not None:
        return input_url

    seed_number = args.to_chapter or args.from_chapter or args.only_chapter or 1
    return chapter_url_from_number(slug, lang, seed_number)


def resolve_chapters(
    driver: webdriver.Firefox,
    args: argparse.Namespace,
    slug: str,
    input_chapter_number: float | None,
    original_only_chapter: float | None,
) -> list[Chapter]:
    number_text = chapter_number_text_from_url(args.url)

    if input_chapter_number is not None and args.from_chapter is None and args.to_chapter is None:
        return [
            Chapter(
                url=args.url,
                number=input_chapter_number,
                number_text=number_text,
            )
        ]

    if input_chapter_number is None and original_only_chapter is not None:
        return [
            Chapter(
                url=chapter_url_from_number(slug, args.lang, original_only_chapter),
                number=original_only_chapter,
                number_text=format_chapter_number(original_only_chapter),
            )
        ]

    if input_chapter_number is None and normalize_lang(args.lang) == "en":
        chapters = get_chapter_list_from_manga_page(
            manga_page_url(slug),
            args.lang,
            args.timeout,
        )
        if chapters:
            return [chapter for chapter in chapters if chapter_in_range(chapter, args)]

    try:
        scraper = create_cloudscraper()
        chapters = fetch_chapters_http(scraper, slug, args.lang, args.timeout)
        if chapters:
            return [chapter for chapter in chapters if chapter_in_range(chapter, args)]
    except Exception:
        pass

    seed_url = choose_seed_reader_url(args.url, slug, args.lang, args)
    chapters = get_chapter_list_from_reader(driver, seed_url, args)
    return [chapter for chapter in chapters if chapter_in_range(chapter, args)]


def main() -> None:
    args = build_parser().parse_args()
    original_only_chapter = args.only_chapter

    if args.only_chapter is not None:
        args.from_chapter = args.only_chapter
        args.to_chapter = args.only_chapter

    slug = slug_from_url(args.url)
    if not slug:
        raise SystemExit("Nao foi possivel extrair o slug da URL do MangaFire.")

    manga_name = clean_filename(args.manga_name or slug)
    output_root = Path(args.output) / manga_name
    input_chapter_number = chapter_number_from_url(args.url)

    driver = build_driver(args)

    try:
        chapters_to_download = resolve_chapters(
            driver,
            args,
            slug,
            input_chapter_number,
            original_only_chapter,
        )

        if not chapters_to_download:
            raise SystemExit("Nenhum capitulo encontrado na faixa especificada.")

        print(f"\nManga : {manga_name}")
        print(f"Output: {output_root}")
        print(f"Capitulos: {len(chapters_to_download)}\n")

        for index, chapter in enumerate(chapters_to_download):
            download_chapter(driver, chapter, output_root, args)
            is_last = index == len(chapters_to_download) - 1
            if not is_last and args.chapter_pause > 0:
                time.sleep(args.chapter_pause)

        print(f"\nConcluido. Arquivos em: {output_root}")

    except KeyboardInterrupt:
        print("\nInterrompido.")
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
