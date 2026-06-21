from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

try:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright
except ImportError:
    PlaywrightError = RuntimeError
    sync_playwright = None


READER_SELECTOR = ".pag-item img[src^='blob:'], .imagem-ctn img[src^='blob:']"
FALLBACK_SELECTOR = "img[src^='blob:']"
BRAVE_PATHS = (
    Path(r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"),
    Path.home() / "AppData/Local/BraveSoftware/Brave-Browser/Application/brave.exe",
)

PROBE_SCRIPT = r"""
(() => {
  if (window.__sakuraProbeInstalled) return;
  window.__sakuraProbeInstalled = true;
  window.__sakuraBlobMeta = [];
  window.__sakuraBlobObjects = new Map();
  window.__sakuraFetchLog = [];

  const originalCreateObjectURL = URL.createObjectURL.bind(URL);
  URL.createObjectURL = function (value) {
    const url = originalCreateObjectURL(value);
    if (value instanceof Blob) {
      window.__sakuraBlobObjects.set(url, value);
      window.__sakuraBlobMeta.push({
        url,
        type: value.type || "application/octet-stream",
        size: value.size,
        createdAt: Date.now(),
      });
    }
    return url;
  };

  const originalFetch = window.fetch.bind(window);
  window.fetch = async function (...args) {
    const response = await originalFetch(...args);
    try {
      const input = args[0];
      const url = typeof input === "string" ? input : input?.url;
      window.__sakuraFetchLog.push({
        transport: "fetch",
        url: url || response.url,
        status: response.status,
        type: response.headers.get("content-type") || "",
        length: response.headers.get("content-length") || "",
      });
    } catch (_) {}
    return response;
  };

  const originalOpen = XMLHttpRequest.prototype.open;
  const originalSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (method, url) {
    this.__sakuraRequest = { method, url: String(url) };
    return originalOpen.apply(this, arguments);
  };
  XMLHttpRequest.prototype.send = function () {
    this.addEventListener("loadend", () => {
      try {
        window.__sakuraFetchLog.push({
          transport: "xhr",
          method: this.__sakuraRequest?.method || "GET",
          url: this.responseURL || this.__sakuraRequest?.url || "",
          status: this.status,
          type: this.getResponseHeader("content-type") || "",
          length: this.getResponseHeader("content-length") || "",
        });
      } catch (_) {}
    }, { once: true });
    return originalSend.apply(this, arguments);
  };
})();
"""

EXTRACT_BLOB_SCRIPT = r"""
async ({ selector, index }) => {
  const images = Array.from(document.querySelectorAll(selector));
  const image = images[index];
  if (!image) return null;

  const src = image.currentSrc || image.src || "";
  if (!src.startsWith("blob:")) return null;

  let blob = window.__sakuraBlobObjects?.get(src) || null;
  if (!blob) {
    const response = await fetch(src);
    if (!response.ok) throw new Error(`Falha lendo blob: HTTP ${response.status}`);
    blob = await response.blob();
  }

  const dataUrl = await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });

  return {
    src,
    dataUrl,
    mime: blob.type || "application/octet-stream",
    width: image.naturalWidth || 0,
    height: image.naturalHeight || 0,
  };
}
"""


def safe_slug(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9._-]+", "-", value).strip("-._")
    return value or "capitulo"


def image_extension(mime: str, content: bytes) -> str:
    mime = (mime or "").lower().split(";", 1)[0]
    by_mime = {
        "image/avif": ".avif",
        "image/gif": ".gif",
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
    }
    if mime in by_mime:
        return by_mime[mime]
    if content.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if content.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return ".webp"
    return ".bin"


def is_cloudflare_challenge(page) -> bool:
    title = (page.title() or "").casefold()
    return "just a moment" in title or "um momento" in title


def wait_for_access(page, timeout_seconds: int, headless: bool) -> None:
    if not is_cloudflare_challenge(page):
        return
    if headless:
        raise RuntimeError(
            "Cloudflare pediu verificacao. Rode sem --headless e conclua no Chrome."
        )

    print("Cloudflare ativo. Conclua a verificacao na janela do Chrome.")
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        page.wait_for_timeout(1000)
        if not is_cloudflare_challenge(page):
            return
    raise TimeoutError("Cloudflare nao foi concluido dentro do tempo limite.")


def select_reader_images(page) -> str:
    if page.locator(READER_SELECTOR).count() > 0:
        return READER_SELECTOR
    if page.locator(FALLBACK_SELECTOR).count() > 0:
        return FALLBACK_SELECTOR
    raise RuntimeError("Nenhuma imagem blob encontrada no leitor.")


def hydrate_reader(page, selector: str, max_passes: int = 5) -> dict:
    previous_state: tuple[int, int, int] | None = None
    stable_passes = 0

    for _ in range(max_passes):
        metrics = page.evaluate(
            """() => ({
                height: Math.max(document.body.scrollHeight, document.documentElement.scrollHeight),
                viewport: window.innerHeight || 720,
            })"""
        )
        step = max(500, int(metrics["viewport"] * 0.8))
        for y in range(0, int(metrics["height"]) + step, step):
            page.evaluate("y => window.scrollTo(0, y)", y)
            page.wait_for_timeout(80)
        page.wait_for_timeout(500)

        state = page.evaluate(
            """selector => {
                const images = Array.from(document.querySelectorAll(selector));
                return {
                    count: images.length,
                    loaded: images.filter(img => img.complete && img.naturalWidth > 0).length,
                    height: Math.max(document.body.scrollHeight, document.documentElement.scrollHeight),
                };
            }""",
            selector,
        )
        signature = (state["count"], state["loaded"], state["height"])
        stable_passes = stable_passes + 1 if signature == previous_state else 0
        previous_state = signature
        if state["count"] > 0 and state["loaded"] == state["count"] and stable_passes >= 1:
            page.evaluate("window.scrollTo(0, 0)")
            return state

    page.evaluate("window.scrollTo(0, 0)")
    return {
        "count": page.locator(selector).count(),
        "loaded": page.locator(selector).count(),
        "height": 0,
    }


def output_directory(root: Path, chapter_url: str) -> Path:
    chapter_slug = Path(urlparse(chapter_url).path.rstrip("/")).name
    target = root / safe_slug(chapter_slug)
    target.mkdir(parents=True, exist_ok=True)
    return target


def launch_browser_context(playwright, launch_options: dict):
    candidates: list[dict] = []
    for path in BRAVE_PATHS:
        if path.exists():
            candidates.append({"executable_path": str(path)})
    candidates.extend(({"channel": "chrome"}, {"channel": "msedge"}, {}))

    errors: list[str] = []
    for browser_options in candidates:
        try:
            return playwright.chromium.launch_persistent_context(
                **browser_options,
                **launch_options,
            )
        except PlaywrightError as exc:
            errors.append(str(exc).splitlines()[0])
    raise RuntimeError("Nenhum Chromium compativel abriu: " + " | ".join(errors))


def save_blob_pages(page, selector: str, target: Path) -> list[dict]:
    count = page.locator(selector).count()
    seen_hashes: set[str] = set()
    manifest: list[dict] = []

    for dom_index in range(count):
        payload = page.evaluate(
            EXTRACT_BLOB_SCRIPT,
            {"selector": selector, "index": dom_index},
        )
        if not payload or not payload.get("dataUrl"):
            continue

        _, encoded = payload["dataUrl"].split(",", 1)
        content = base64.b64decode(encoded, validate=True)
        digest = hashlib.sha256(content).hexdigest()
        if digest in seen_hashes:
            continue
        seen_hashes.add(digest)

        page_number = len(manifest) + 1
        extension = image_extension(payload.get("mime", ""), content)
        filename = f"pagina_{page_number:03d}{extension}"
        path = target / filename
        path.write_bytes(content)
        manifest.append(
            {
                "page": page_number,
                "dom_index": dom_index,
                "filename": filename,
                "sha256": digest,
                "bytes": len(content),
                "mime": payload.get("mime", ""),
                "width": payload.get("width", 0),
                "height": payload.get("height", 0),
                "blob_url": payload.get("src", ""),
            }
        )
        print(f"[{page_number:03d}] {filename} ({len(content):,} bytes)")

    return manifest


def run(args: argparse.Namespace) -> int:
    if sync_playwright is None:
        raise RuntimeError("Playwright ausente. Instale: pip install playwright")

    target = output_directory(Path(args.output), args.chapter_url)
    profile = Path(args.profile).resolve()
    profile.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        launch_options = {
            "user_data_dir": str(profile),
            "headless": args.headless,
            "viewport": {"width": 1280, "height": 900},
        }
        context = launch_browser_context(playwright, launch_options)

        page = context.pages[0] if context.pages else context.new_page()
        network_log: list[dict] = []

        def record_response(response) -> None:
            request = response.request
            content_type = response.headers.get("content-type", "")
            if request.resource_type in {"fetch", "xhr", "image"} or any(
                marker in content_type for marker in ("image/", "octet-stream")
            ):
                network_log.append(
                    {
                        "url": response.url,
                        "status": response.status,
                        "resource_type": request.resource_type,
                        "method": request.method,
                        "content_type": content_type,
                        "content_length": response.headers.get("content-length", ""),
                    }
                )

        page.on("response", record_response)
        page.add_init_script(PROBE_SCRIPT)
        page.goto(args.chapter_url, wait_until="domcontentloaded", timeout=60_000)
        wait_for_access(page, args.challenge_timeout, args.headless)
        page.wait_for_selector(FALLBACK_SELECTOR, timeout=args.image_timeout * 1000)

        selector = select_reader_images(page)
        state = hydrate_reader(page, selector)
        print(f"DOM: {state['count']} imagens; carregadas: {state['loaded']}")

        manifest = save_blob_pages(page, selector, target)
        probe = page.evaluate(
            """() => ({
                blobs: window.__sakuraBlobMeta || [],
                requests: window.__sakuraFetchLog || [],
            })"""
        )
        (target / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (target / "network.json").write_text(
            json.dumps(
                {"playwright": network_log, "page_probe": probe},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        context.close()

    if not manifest:
        raise RuntimeError("Blobs encontrados, mas nenhuma pagina valida foi salva.")
    print(f"OK: {len(manifest)} paginas unicas em {target}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Extrai paginas blob do leitor do Sakura Mangas sem duplicar imagens."
    )
    parser.add_argument("chapter_url", help="URL absoluta do capitulo.")
    parser.add_argument("--output", default="downloads/sakura", help="Pasta raiz de saida.")
    parser.add_argument(
        "--profile",
        default=".sakura-browser-profile",
        help="Perfil Chromium persistente para cookies do Cloudflare.",
    )
    parser.add_argument("--headless", action="store_true", help="Executa sem janela.")
    parser.add_argument("--challenge-timeout", type=int, default=180)
    parser.add_argument("--image-timeout", type=int, default=90)
    return parser


def main() -> int:
    try:
        return run(build_parser().parse_args())
    except KeyboardInterrupt:
        print("Interrompido.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
