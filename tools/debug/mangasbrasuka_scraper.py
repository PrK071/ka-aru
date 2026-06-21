from __future__ import annotations

import argparse
import re
import sys
import time
from dataclasses import dataclass
from html import unescape
from pathlib import Path
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import requests


BASE_URL = "https://mangasbrasuka.com.br"
OUTPUT_DIR = Path("downloads_brasuka")
REQUEST_TIMEOUT = 30

HEADERS_HTML = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Referer": BASE_URL + "/",
}

HEADERS_IMG = {
    "User-Agent": HEADERS_HTML["User-Agent"],
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    "Referer": BASE_URL + "/",
}


@dataclass(frozen=True)
class ChapterLink:
    label: str
    number_text: str
    number: float
    url: str


def normalize_url(raw_url: str | None, base_url: str = "") -> str:
    url = unescape(str(raw_url or "")).strip()
    if not url or url == "#" or url.startswith("data:"):
        return ""
    url = urljoin(base_url, url)
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""

    params = parse_qs(parsed.query)
    for key in ("a", "url", "u", "img", "image"):
        candidate = params.get(key, [None])[0]
        if candidate and re.match(r"^https?://", candidate, re.IGNORECASE):
            nested = normalize_url(candidate)
            if nested:
                return nested

    return parsed._replace(fragment="").geturl()


def image_key(raw_url: str) -> str:
    url = normalize_url(raw_url)
    if not url:
        return ""
    parsed = urlparse(url)
    path = unquote(parsed.path)
    if re.search(r"\.(?:avif|gif|jpe?g|png|webp)$", path, re.IGNORECASE):
        return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{path}"

    ignored = {"_", "cb", "cache", "cachebuster", "host", "rand", "r", "t", "timestamp", "v"}
    stable_params = [
        (key, tuple(values))
        for key, values in sorted(parse_qs(parsed.query, keep_blank_values=True).items())
        if key.lower() not in ignored
    ]
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{path}?{stable_params}"


def dedupe_urls(urls: list[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for raw_url in urls:
        url = normalize_url(raw_url)
        key = image_key(url)
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(url)
    return unique


def clean_name(value: str, fallback: str = "item") -> str:
    text = re.sub(r"[<>:\"/\\|?*\x00-\x1f]+", "-", value or "")
    text = re.sub(r"\s+", "-", text).strip("-. ")
    return text[:120] or fallback


def chapter_number_from_url(url: str) -> tuple[str, float] | None:
    slug = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
    match = re.search(r"capitulo-(\d+(?:\.\d+)?)$", slug, re.IGNORECASE)
    if not match:
        return None
    number_text = match.group(1)
    return number_text, float(number_text)


def manga_slug(url: str) -> str:
    parts = [part for part in urlparse(url).path.strip("/").split("/") if part]
    if len(parts) >= 2 and parts[0] == "manga":
        return clean_name(parts[1], "manga")
    return clean_name(parts[-1], "manga") if parts else "manga"


def get_html(url: str, referer: str | None = None) -> str:
    headers = dict(HEADERS_HTML)
    if referer:
        headers["Referer"] = referer
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT, allow_redirects=True)
            if response.status_code in {429, 500, 502, 503, 504} and attempt < 3:
                time.sleep(0.5 * attempt)
                continue
            response.raise_for_status()
            return response.text
        except requests.RequestException as exc:
            last_error = exc
            if attempt < 3:
                time.sleep(0.5 * attempt)
                continue
            raise
    raise RuntimeError(f"Falha ao carregar HTML: {last_error}")


def attrs_from_tag(tag: str) -> dict[str, str]:
    return {
        key.lower(): unescape(value)
        for key, _quote, value in re.findall(
            r'([a-zA-Z_:][-.\w:]*)\s*=\s*(["\'])(.*?)\2',
            tag,
            re.DOTALL,
        )
    }


def reader_scope(html: str) -> str:
    for div_match in re.finditer(r"<div\b[^>]*>", html, re.IGNORECASE | re.DOTALL):
        attrs = attrs_from_tag(div_match.group(0))
        classes = set(str(attrs.get("class") or "").split())
        if "reading-content" not in classes:
            continue
        tail = html[div_match.start() :]
        end_match = re.search(
            r'(?=<div\b[^>]*class=["\'][^"\']*(?:nav-links|wp-manga-nav|comments-area)|<footer\b|</main>|</body>)',
            tail,
            re.IGNORECASE,
        )
        return tail[: end_match.start()] if end_match else tail
    return html


def srcset_urls(srcset: str | None) -> list[str]:
    urls: list[str] = []
    if not srcset:
        return urls
    for item in srcset.split(","):
        first = item.strip().split()[0] if item.strip() else ""
        if first:
            urls.append(first)
    return urls


def looks_like_page_image(url: str) -> bool:
    parsed = urlparse(url)
    path = unquote(parsed.path)
    if not re.search(r"\.(?:avif|gif|jpe?g|png|webp)$", path, re.IGNORECASE):
        return False
    lowered = url.lower()
    return "/mangasbrasuka/manga_" in lowered or "/mangasbrasuka/manga/" in lowered


def extract_reader_images(html: str, page_url: str) -> list[str]:
    scope = reader_scope(html)
    candidates: list[str] = []

    for tag in re.findall(r"<img\b[^>]*>", scope, re.IGNORECASE | re.DOTALL):
        attrs = attrs_from_tag(tag)
        for attr in ("data-src", "data-original", "data-lazy-src", "src"):
            candidates.append(normalize_url(attrs.get(attr), page_url))
        candidates.extend(normalize_url(url, page_url) for url in srcset_urls(attrs.get("srcset")))
        candidates.extend(normalize_url(url, page_url) for url in srcset_urls(attrs.get("data-srcset")))

    for href in re.findall(r'href=["\']([^"\']+)["\']', scope, re.IGNORECASE):
        candidates.append(normalize_url(href, page_url))

    candidates.extend(
        normalize_url(match, page_url)
        for match in re.findall(
            r'https?://cdn\.mugiverso\.com/mangasbrasuka/manga[_/][^\s"\'<>]+\.(?:jpg|jpeg|png|webp)',
            scope,
            re.IGNORECASE,
        )
    )

    return [url for url in dedupe_urls(candidates) if looks_like_page_image(url)]


def parse_chapters(html: str, manga_url: str) -> list[ChapterLink]:
    manga_url = manga_url.rstrip("/") + "/"
    base = manga_url.rstrip("/")
    found: dict[str, ChapterLink] = {}
    for href in re.findall(r'<a\b[^>]+href=["\']([^"\']+)["\']', html, re.IGNORECASE | re.DOTALL):
        url = normalize_url(href, manga_url).rstrip("/") + "/"
        if not url.startswith(base + "/capitulo-"):
            continue
        parsed = chapter_number_from_url(url)
        if not parsed:
            continue
        number_text, number = parsed
        label = f"capitulo-{number_text}"
        found[image_key(url) or url] = ChapterLink(label=label, number_text=number_text, number=number, url=url)
    return sorted(found.values(), key=lambda item: (item.number, item.url))


def chapter_bounds_from_html(html: str, manga_url: str) -> tuple[int, int] | None:
    manga_url = manga_url.rstrip("/") + "/"
    base = manga_url.rstrip("/")
    numbers: list[int] = []
    for href in re.findall(r'href=["\']([^"\']+)["\']', html, re.IGNORECASE | re.DOTALL):
        url = normalize_url(href, manga_url).rstrip("/") + "/"
        if not url.startswith(base + "/capitulo-"):
            continue
        parsed = chapter_number_from_url(url)
        if not parsed:
            continue
        _number_text, number = parsed
        if number.is_integer():
            numbers.append(int(number))
    if not numbers:
        return None
    return min(numbers), max(numbers)


def build_chapter_range(manga_url: str, low: int, high: int) -> list[ChapterLink]:
    if low > high:
        low, high = high, low
    chapters: list[ChapterLink] = []
    for number in range(low, high + 1):
        label = f"capitulo-{number}"
        chapters.append(
            ChapterLink(
                label=label,
                number_text=str(number),
                number=float(number),
                url=f"{manga_url.rstrip('/')}/{label}/",
            )
        )
    return chapters


def fetch_chapters_ajax(manga_url: str, manga_id: str) -> list[ChapterLink]:
    headers = {
        **HEADERS_HTML,
        "Referer": manga_url,
        "X-Requested-With": "XMLHttpRequest",
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": BASE_URL,
    }
    response = requests.post(
        BASE_URL + "/wp-admin/admin-ajax.php",
        data={"action": "manga_get_chapters", "manga": manga_id},
        headers=headers,
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return parse_chapters(response.text, manga_url)


def fetch_chapter_list(manga_url: str) -> list[ChapterLink]:
    manga_url = manga_url.rstrip("/") + "/"
    print(f"[*] Index: {manga_url}")
    html = get_html(manga_url)

    chapters = parse_chapters(html, manga_url)
    bounds = chapter_bounds_from_html(html, manga_url)
    if bounds:
        low, high = bounds
        expected = high - low + 1
        if len(chapters) < expected:
            chapters = build_chapter_range(manga_url, low, high)

    manga_id_match = re.search(r'"manga_id":"(\d+)"', html)
    if not chapters and manga_id_match:
        try:
            ajax_chapters = fetch_chapters_ajax(manga_url, manga_id_match.group(1))
            if len(ajax_chapters) > len(chapters):
                chapters = ajax_chapters
        except requests.RequestException as exc:
            print(f"[!] AJAX lista falhou, usando HTML estatico: {exc}")

    if not chapters:
        raise RuntimeError("Nenhum capitulo encontrado no index do manga.")

    print(f"[*] Caps reais: {len(chapters)} ({chapters[0].label} -> {chapters[-1].label})")
    return chapters


def image_ext(url: str) -> str:
    suffix = Path(urlparse(url).path).suffix.lower()
    return suffix if suffix in {".avif", ".gif", ".jpg", ".jpeg", ".png", ".webp"} else ".webp"


def download_image(url: str, dest: Path, referer: str) -> bool:
    if dest.exists() and dest.stat().st_size > 0:
        return True
    headers = dict(HEADERS_IMG)
    headers["Referer"] = referer
    tmp = dest.with_name(dest.name + ".part")
    try:
        response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        tmp.write_bytes(response.content)
        tmp.replace(dest)
        return True
    except requests.RequestException as exc:
        print(f"    [erro img] {exc}")
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        return False


def scrape_static_chapter(
    chapter: ChapterLink,
    manga_url: str,
    manga_dir: Path,
    *,
    dry_run: bool = False,
    delay: float = 0.0,
) -> int:
    print(f"[*] GET real: {chapter.url}")
    html = get_html(chapter.url, referer=manga_url)
    images = extract_reader_images(html, chapter.url)
    if not images:
        print("    [warn] 0 imagens no container de leitura")
        return 0

    chapter_dir = manga_dir / clean_name(chapter.label, "capitulo")
    if not dry_run:
        chapter_dir.mkdir(parents=True, exist_ok=True)

    saved = 0
    for index, image_url in enumerate(images, start=1):
        filename = chapter_dir / f"pagina_{index:03d}{image_ext(image_url)}"
        print(f"    {index:03d}: {image_url}")
        if dry_run:
            saved += 1
            continue
        if download_image(image_url, filename, chapter.url):
            saved += 1
        if delay:
            time.sleep(delay)
    return saved


def scrape_manga(
    manga_url: str,
    start: int = 1,
    end: int | None = None,
    *,
    output_dir: Path = OUTPUT_DIR,
    dry_run: bool = False,
    delay: float = 0.0,
) -> None:
    manga_url = manga_url.rstrip("/") + "/"
    chapters = fetch_chapter_list(manga_url)
    if start < 1:
        start = 1
    if end is None or end > len(chapters):
        end = len(chapters)
    selected = chapters[start - 1 : end]
    manga_dir = output_dir / manga_slug(manga_url)
    if not dry_run:
        manga_dir.mkdir(parents=True, exist_ok=True)

    total = 0
    for chapter in selected:
        total += scrape_static_chapter(chapter, manga_url, manga_dir, dry_run=dry_run, delay=delay)

    mode = "dry-run" if dry_run else "salvo"
    print(f"[*] Fim: {mode}, {len(selected)} caps, {total} imagens.")
    print(f"[*] Dir: {manga_dir.resolve()}")


def scrape_single(chapter_url: str, *, output_dir: Path = OUTPUT_DIR, dry_run: bool = False) -> None:
    chapter_url = chapter_url.rstrip("/") + "/"
    parts = [part for part in urlparse(chapter_url).path.strip("/").split("/") if part]
    if len(parts) < 3:
        raise ValueError("URL de capitulo invalida.")
    manga_url = f"{BASE_URL}/manga/{parts[1]}/"
    parsed = chapter_number_from_url(chapter_url)
    if not parsed:
        raise ValueError("URL de capitulo invalida.")
    number_text, number = parsed
    chapter = ChapterLink(label=f"capitulo-{number_text}", number_text=number_text, number=number, url=chapter_url)
    scrape_static_chapter(chapter, manga_url, output_dir / manga_slug(manga_url), dry_run=dry_run)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scraper estatico MangasBrasuka: index -> URLs reais -> GET isolado por capitulo.",
    )
    parser.add_argument("url", help="URL do manga ou de um capitulo.")
    parser.add_argument("start", nargs="?", type=int, default=1, help="Indice inicial 1-based.")
    parser.add_argument("end", nargs="?", type=int, default=None, help="Indice final 1-based.")
    parser.add_argument("--out", type=Path, default=OUTPUT_DIR, help="Diretorio de saida.")
    parser.add_argument("--dry-run", action="store_true", help="Nao baixa arquivos; so lista URLs.")
    parser.add_argument("--delay", type=float, default=0.0, help="Delay entre downloads de imagens.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    url = args.url.strip()
    is_chapter = bool(re.search(r"/capitulo-\d+(?:\.\d+)?/?$", url, re.IGNORECASE))
    if is_chapter:
        scrape_single(url, output_dir=args.out, dry_run=args.dry_run)
    else:
        scrape_manga(url, args.start, args.end, output_dir=args.out, dry_run=args.dry_run, delay=args.delay)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
