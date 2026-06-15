from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote

import requests

BASE_URL = "https://mangasbrasuka.com.br"
CDN_URL = "https://cdn.mugiverso.com"

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

OUTPUT_DIR = Path("downloads_brasuka")
DELAY_BETWEEN_PAGES = 0.5   
DELAY_BETWEEN_IMAGES = 0.3 


def _get_html(url: str, referer: str | None = None) -> str:
    headers = dict(HEADERS_HTML)
    if referer:
        headers["Referer"] = referer
    r = requests.get(url, headers=headers, timeout=25, allow_redirects=True)
    r.raise_for_status()
    return r.text


def _extract_page_image(html: str) -> str | None:
    m = re.search(
        r'href=["\']https?://redenovax\.com/jump/[^\s"\'<>]+["\']',
        html,
        re.IGNORECASE,
    )
    if m:
        href = m.group(0)[6:-1] 
        params = parse_qs(urlparse(href).query)
        real_url = params.get("a", [None])[0]
        if real_url and ("manga_" in real_url or "mangasbrasuka" in real_url):
            return real_url

    m2 = re.search(
        r'https://cdn\.mugiverso\.com/mangasbrasuka/manga[_/][^\s"\'<>]+\.(?:jpg|jpeg|png|webp)',
        html,
        re.IGNORECASE,
    )
    if m2:
        return m2.group(0)

    return None


def _extract_chapter_list(html: str, manga_url: str) -> list[dict]:
    base = manga_url.rstrip("/")
    links = re.findall(
        r'href=["\'](' + re.escape(base) + r'/capitulo-[\d\.]+/)["\']',
        html,
        re.IGNORECASE,
    )
    seen: dict[str, int] = {}
    result = []
    for url in links:
        if url in seen:
            continue
        seen[url] = 1
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        num_m = re.search(r"(\d+(?:\.\d+)?)", slug)
        num = num_m.group(1) if num_m else slug
        result.append({"label": slug, "number": num, "url": url})

    result.sort(key=lambda c: float(c["number"]) if c["number"].replace(".", "").isdigit() else 0)
    return result


def _fetch_all_chapters_ajax(manga_url: str, manga_id: str) -> list[dict]:
    base = manga_url.rstrip("/")
    ajax_url = BASE_URL + "/wp-admin/admin-ajax.php"
    headers = {
        **HEADERS_HTML,
        "Referer": manga_url,
        "X-Requested-With": "XMLHttpRequest",
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": BASE_URL,
    }
    payload = {
        "action": "manga_get_chapters",
        "manga": manga_id,
    }
    try:
        r = requests.post(ajax_url, data=payload, headers=headers, timeout=20)
        r.raise_for_status()
        html_fragment = r.text
        links = re.findall(
            r'href=["\'](' + re.escape(base) + r'/capitulo-[\d\.]+/)["\']',
            html_fragment,
            re.IGNORECASE,
        )
        if not links:
            return []
        seen: dict[str, int] = {}
        result = []
        for url in links:
            if url in seen:
                continue
            seen[url] = 1
            slug = url.rstrip("/").rsplit("/", 1)[-1]
            num_m = re.search(r"(\d+(?:\.\d+)?)", slug)
            num = num_m.group(1) if num_m else slug
            result.append({"label": slug, "number": num, "url": url})
        result.sort(key=lambda c: float(c["number"]) if c["number"].replace(".", "").isdigit() else 0)
        return result
    except Exception:
        return []


def _manga_slug(url: str) -> str:
    """Extrai o slug do manga da URL."""
    parts = [p for p in urlparse(url).path.strip("/").split("/") if p]
    if len(parts) >= 2 and parts[0] == "manga":
        return parts[1]
    return parts[-1] if parts else "manga"


def _download_image(url: str, dest: Path) -> bool:
    """Baixa uma imagem e salva em dest. Retorna True se OK."""
    if dest.exists():
        return True
    try:
        r = requests.get(url, headers=HEADERS_IMG, timeout=30)
        r.raise_for_status()
        dest.write_bytes(r.content)
        return True
    except requests.RequestException as exc:
        print(f"    [ERRO] {exc}")
        return False

def fetch_chapter_list(manga_url: str) -> list[dict]:
    manga_url = manga_url.rstrip("/") + "/"
    print(f"[*] Buscando lista de capítulos: {manga_url}")
    html = _get_html(manga_url)

    manga_id_m = re.search(r'"manga_id":"(\d+)"', html)
    manga_id = manga_id_m.group(1) if manga_id_m else None

    chapters: list[dict] = []
    if manga_id:
        print(f"[*] Buscando via AJAX (manga_id={manga_id})...")
        chapters = _fetch_all_chapters_ajax(manga_url, manga_id)

    if not chapters:
        chapters = _extract_chapter_list(html, manga_url)

    if not chapters:
        print("[!] Nenhum capítulo encontrado.")
        print("    Verifique se a URL é a página do manga (não a de um capítulo).")
        return []

    print(f"[*] {len(chapters)} capítulos/páginas encontrados (do capitulo-{chapters[0]['number']} ao capitulo-{chapters[-1]['number']})")
    return chapters


def scrape_chapter_range(
    manga_url: str,
    start: int = 1,
    end: int | None = None,
) -> None:
    manga_url = manga_url.rstrip("/") + "/"
    slug = _manga_slug(manga_url)
    save_dir = OUTPUT_DIR / slug
    save_dir.mkdir(parents=True, exist_ok=True)

    chapters = fetch_chapter_list(manga_url)
    if not chapters:
        return

    if end is None:
        end = len(chapters)
    subset = chapters[start - 1 : end]

    print(f"[*] Baixando páginas {start} a {start + len(subset) - 1} de {len(chapters)}")
    print(f"[*] Salvando em: {save_dir.resolve()}\n")

    total = len(subset)
    for i, chapter in enumerate(subset, start=start):
        cap_url = chapter["url"]
        label = chapter["label"]

        print(f"  [{i:04d}/{start + total - 1}] {label}: {cap_url}")

        try:
            html = _get_html(cap_url, referer=manga_url)
        except requests.RequestException as exc:
            print(f"    [ERRO HTML] {exc}")
            time.sleep(DELAY_BETWEEN_PAGES)
            continue

        img_url = _extract_page_image(html)
        if not img_url:
            print(f"    [AVISO] Nenhuma imagem encontrada nesta página")
            time.sleep(DELAY_BETWEEN_PAGES)
            continue

        ext = Path(urlparse(img_url).path).suffix or ".webp"
        filename = save_dir / f"{i:04d}{ext}"

        if filename.exists():
            print(f"    já existe: {filename.name}")
        else:
            ok = _download_image(img_url, filename)
            if ok:
                print(f"    -> {filename.name}  ({img_url})")
            time.sleep(DELAY_BETWEEN_IMAGES)

        time.sleep(DELAY_BETWEEN_PAGES)

    print(f"\n[✓] Concluído! Pasta: {save_dir.resolve()}")
    print(f"    Total baixado: {len(list(save_dir.glob('*.*')))} imagens")


def scrape_single_chapter(chapter_url: str) -> None:
    chapter_url = chapter_url.rstrip("/") + "/"
    parts = [p for p in urlparse(chapter_url).path.strip("/").split("/") if p]

    manga_slug = parts[1] if len(parts) >= 2 and parts[0] == "manga" else "manga"
    cap_label = parts[-1] if len(parts) >= 3 else "capitulo-1"
    num_m = re.search(r"(\d+(?:\.\d+)?)", cap_label)
    page_num = int(float(num_m.group(1))) if num_m else 1

    save_dir = OUTPUT_DIR / manga_slug
    save_dir.mkdir(parents=True, exist_ok=True)

    print(f"[*] Capítulo: {chapter_url}")
    html = _get_html(chapter_url)
    img_url = _extract_page_image(html)

    if not img_url:
        print("[!] Nenhuma imagem encontrada.")
        debug = Path("debug_brasuka_last.html")
        debug.write_text(html, encoding="utf-8")
        print(f"    HTML salvo em: {debug.resolve()}")
        return

    ext = Path(urlparse(img_url).path).suffix or ".webp"
    filename = save_dir / f"{page_num:04d}{ext}"

    print(f"[*] Imagem: {img_url}")
    ok = _download_image(img_url, filename)
    if ok:
        print(f"[✓] Salvo: {filename.resolve()}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    url = sys.argv[1].strip()

    is_chapter = bool(re.search(r"/capitulo-\d+/?$", url, re.IGNORECASE))

    if is_chapter:
        scrape_single_chapter(url)
    else:
        page_start = int(sys.argv[2]) if len(sys.argv) > 2 else 1
        page_end = int(sys.argv[3]) if len(sys.argv) > 3 else None
        scrape_chapter_range(url, start=page_start, end=page_end)
