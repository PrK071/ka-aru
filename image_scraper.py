from __future__ import annotations

import argparse
import re
import time
from pathlib import Path
from typing import Iterable
from urllib.parse import unquote, urlparse

import requests
from playwright.sync_api import (
    Error as PlaywrightError,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)


IMAGE_ATTRS = (
    "currentSrc",
    "src",
    "data-src",
    "data-original",
    "data-lazy-src",
    "data-url",
    "data-cfsrc",
)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0 Safari/537.36"
    ),
}

COLLECT_IMAGE_URLS_JS = """
(elements, attrs) => {
  const urls = [];
  const seen = new Set();

  const add = (value) => {
    if (!value || typeof value !== "string") return;
    const trimmed = value.trim();
    if (!trimmed) return;

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
      const parts = item.trim().split(/\\s+/);
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

  const addBackgroundUrls = (element) => {
    const values = [
      element.getAttribute("style") || "",
      window.getComputedStyle(element).backgroundImage || "",
    ];

    for (const value of values) {
      for (const match of value.matchAll(/url\\((['"]?)(.*?)\\1\\)/g)) {
        add(match[2]);
      }
    }
  };

  const addElement = (element) => {
    for (const attr of attrs) {
      add(element[attr]);
      add(element.getAttribute(attr));
    }

    add(pickFromSrcset(element.getAttribute("srcset")));
    add(pickFromSrcset(element.getAttribute("data-srcset")));
    addBackgroundUrls(element);
  };

  for (const selected of elements) {
    const candidates = [];
    if (selected.matches("img, source")) candidates.push(selected);
    candidates.push(...selected.querySelectorAll("img, source"));

    if (candidates.length === 0) {
      candidates.push(selected);
    }

    for (const candidate of candidates) {
      addElement(candidate);
    }
  }

  return urls;
}
"""


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


def collect_image_urls(page: Page, selector: str) -> list[str]:
    urls = page.eval_on_selector_all(selector, COLLECT_IMAGE_URLS_JS, list(IMAGE_ATTRS))
    return [url for url in urls if isinstance(url, str)]


def scroll_to_load_images(
    page: Page,
    selector: str,
    pause: float,
    max_scrolls: int,
    stable_rounds: int,
) -> list[str]:
    stable_count = 0
    last_count = -1
    last_height = -1
    current_y = 0

    for _ in range(max_scrolls):
        urls = collect_image_urls(page, selector)
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

        if stable_count >= stable_rounds:
            break

        last_count = len(urls)
        last_height = height
        current_y = min(current_y + max(300, int(viewport * 0.85)), height)
        page.evaluate("(y) => window.scrollTo(0, y)", current_y)
        page.wait_for_timeout(int(pause * 1000))

    page.wait_for_timeout(int(pause * 1000))
    return collect_image_urls(page, selector)


def session_from_context(cookies: list[dict], referer: str) -> requests.Session:
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)
    session.headers.update({"Referer": referer})

    for cookie in cookies:
        kwargs = {"path": cookie.get("path", "/")}
        if cookie.get("domain"):
            kwargs["domain"] = cookie["domain"]

        session.cookies.set(cookie["name"], cookie["value"], **kwargs)

    return session


def iter_downloads(
    session: requests.Session,
    urls: Iterable[str],
    output_dir: Path,
    delay: float,
    timeout: int,
) -> Iterable[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)

    for index, url in enumerate(urls, start=1):
        response = session.get(url, timeout=timeout)
        response.raise_for_status()

        filename = filename_from_url(url, index, response.headers.get("Content-Type"))
        target = output_dir / filename
        target.write_bytes(response.content)

        yield target

        if delay > 0:
            time.sleep(delay)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Renderiza uma pagina com Playwright e baixa imagens dentro de uma div/container. "
            "Use apenas em paginas e obras que voce tem permissao para arquivar."
        )
    )
    parser.add_argument("url", help="URL da pagina/capitulo autorizado.")
    parser.add_argument(
        "-s",
        "--selector",
        required=True,
        help='Seletor CSS da div ou das imagens. Ex.: "div.reader-area" ou "div.reader-area img"',
    )
    parser.add_argument(
        "-o",
        "--output",
        default="downloads",
        help="Pasta de saida. Padrao: downloads",
    )
    parser.add_argument(
        "--name",
        default=None,
        help="Nome da subpasta do capitulo. Padrao: derivado do titulo da pagina.",
    )
    parser.add_argument(
        "--browser",
        choices=("chrome", "edge", "chromium", "firefox"),
        default="edge",
        help="Navegador usado pelo Playwright. Padrao: edge",
    )
    parser.add_argument(
        "--show-browser",
        action="store_true",
        help="Mostra o navegador. Util se a pagina bloquear modo headless.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.5,
        help="Pausa entre downloads, em segundos. Padrao: 0.5",
    )
    parser.add_argument(
        "--scroll-pause",
        type=float,
        default=1.0,
        help="Pausa entre rolagens do leitor, em segundos. Padrao: 1.0",
    )
    parser.add_argument(
        "--max-scrolls",
        type=int,
        default=80,
        help="Limite de rolagens para carregar imagens lazy-load. Padrao: 80",
    )
    parser.add_argument(
        "--stable-rounds",
        type=int,
        default=3,
        help="Quantas rolagens no fim sem novas imagens indicam que acabou. Padrao: 3",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Timeout para Playwright e HTTP, em segundos. Padrao: 30",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Lista as imagens encontradas sem baixar.",
    )
    return parser


def launch_browser(playwright, browser_name: str, show_browser: bool):
    headless = not show_browser

    if browser_name == "chrome":
        return playwright.chromium.launch(channel="chrome", headless=headless)
    if browser_name == "edge":
        return playwright.chromium.launch(channel="msedge", headless=headless)
    if browser_name == "chromium":
        return playwright.chromium.launch(headless=headless)
    if browser_name == "firefox":
        return playwright.firefox.launch(headless=headless)

    raise ValueError(f"Navegador nao suportado: {browser_name}")


def main() -> None:
    args = build_parser().parse_args()
    timeout_ms = args.timeout * 1000

    try:
        with sync_playwright() as playwright:
            browser = launch_browser(playwright, args.browser, args.show_browser)
            context = browser.new_context(
                user_agent=DEFAULT_HEADERS["User-Agent"],
                viewport={"width": 1280, "height": 1800},
            )
            page = context.new_page()

            try:
                page.goto(args.url, wait_until="domcontentloaded", timeout=timeout_ms)
                page.wait_for_selector(args.selector, state="attached", timeout=timeout_ms)
                try:
                    page.wait_for_load_state("networkidle", timeout=5000)
                except PlaywrightTimeoutError:
                    pass

                image_urls = scroll_to_load_images(
                    page,
                    args.selector,
                    args.scroll_pause,
                    args.max_scrolls,
                    args.stable_rounds,
                )
                if not image_urls:
                    raise SystemExit("Nenhuma imagem encontrada dentro do container informado.")

                if args.dry_run:
                    for url in image_urls:
                        print(url)
                    return

                chapter_name = clean_filename(args.name or page.title())
                output_dir = Path(args.output) / chapter_name
                session = session_from_context(context.cookies(), args.url)

                print(f"{len(image_urls)} imagens encontradas.")
                for target in iter_downloads(
                    session,
                    image_urls,
                    output_dir,
                    args.delay,
                    args.timeout,
                ):
                    print(f"salvo: {target}")

                print(f"concluido: {output_dir}")
            finally:
                context.close()
                browser.close()
    except PlaywrightTimeoutError as exc:
        raise SystemExit(
            f"Timeout no Playwright. Confira a URL e o seletor CSS: {args.selector}\n"
            f"Detalhe: {exc}"
        ) from exc
    except PlaywrightError as exc:
        raise SystemExit(
            "Erro ao iniciar/controlar o navegador pelo Playwright. "
            "Confira se o navegador escolhido esta instalado. "
            "Para browsers do Playwright, rode: python -m playwright install chromium\n"
            f"Detalhe: {exc}"
        ) from exc
    except PermissionError as exc:
        raise SystemExit(
            "O sistema bloqueou o Playwright ao iniciar um processo do navegador. "
            "Tente rodar o comando em um PowerShell normal, fora de sandbox/restricao.\n"
            f"Detalhe: {exc}"
        ) from exc


if __name__ == "__main__":
    main()
