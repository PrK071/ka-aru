"""Requisitor do Sakura Mangas: Playwright (browser visivel) + cloudscraper.

Fluxo:
  1. Abre um Chromium VISIVEL com perfil persistente (ou conecta via CDP).
  2. Cloudflare Turnstile e resolvido AUTOMATICAMENTE via CapSolver/2captcha
     (intercepta turnstile.render, manda sitekey ao servico, injeta o token).
     Sem chave/servico, cai para resolucao MANUAL na janela.
  3. Colhe cookies (cf_clearance, etc.) + User-Agent do contexto.
  4. Monta uma sessao cloudscraper com esses cookies -> requisicoes HTTP passam
     pelo Cloudflare (paginas/JSON normais).
  5. Extrai as paginas blob: do leitor via Playwright (cloudscraper nao le blob:)
     e grava os bytes em disco + manifest.json.

Uso:
  set CAPSOLVER_API_KEY=...   (ou --captcha-key / --captcha-provider 2captcha)
  python tools/sakura_requisitor.py "https://sakuramangas.org/.../capitulo-12"

Reaproveita as constantes ja validadas em reader_server.py (fonte unica).
"""

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

# Garante import de reader_server (raiz do projeto) quando rodado de tools/.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import cloudscraper  # noqa: E402

# Garante import de captcha_solver (mesma pasta tools/).
TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from captcha_solver import (  # noqa: E402
    TURNSTILE_INJECT_JS,
    TURNSTILE_INTERCEPT_JS,
    CaptchaError,
    CloudflareSolution,
    ProxyConfig,
    TurnstileParams,
    build_solver,
)

from reader_server import (  # noqa: E402
    DEFAULT_HEADERS,
    DEFAULT_SAKURA_CDP_URL,
    DEFAULT_SAKURA_PROFILE_DIR,
    SAKURA_BLOB_PROBE_JS,
    SAKURA_BRAVE_PATHS,
    SAKURA_EXTRACT_BLOB_JS,
    SAKURA_FALLBACK_SELECTOR,
    SAKURA_READER_SELECTOR,
    clean_filename,
)

try:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright
except ImportError:
    PlaywrightError = RuntimeError
    sync_playwright = None


# Mascara sinais obvios de automacao (anti block.php). Voce ainda resolve o captcha.
STEALTH_JS = r"""
(() => {
  try { Object.defineProperty(navigator, 'webdriver', { get: () => undefined }); } catch (e) {}
  try {
    if (!window.chrome) window.chrome = { runtime: {} };
    Object.defineProperty(navigator, 'languages', { get: () => ['pt-BR', 'pt', 'en-US', 'en'] });
    Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
  } catch (e) {}
})();
"""


# Bypass do shield canvas-DRM do sakuramangas.
#
# O shield (1o <script> do <head>) poisona HTMLCanvasElement.prototype.toDataURL
# (-> "data:,") e mascara o src das <img> do leitor, p/ impedir extracao. Ele usa
# Object.defineProperty(..., {configurable:false}) dentro de try/catch.
#
# Como os init scripts do Playwright rodam ANTES de qualquer script da pagina,
# travamos toDataURL (e hookamos drawImage/putImageData) com a impl REAL e como
# configurable:false ANTES do shield. Quando o shield tenta redefinir com o valor
# falso, o Object.defineProperty levanta TypeError (prop nao-configuravel com
# valor diferente) e e engolido pelo catch -> a funcao real sobrevive.
#
# Guardamos tambem uma referencia privada (__cvRealToDataURL) e expomos
# window.__cvDump() que le os pixels reais de cada canvas desenhado.
CANVAS_DRM_BYPASS_JS = r"""
(() => {
  if (window.__cvDrm) return;
  window.__cvDrm = true;

  const lock = (obj, name, value) => {
    try {
      Object.defineProperty(obj, name, {
        value: value, configurable: false, writable: false, enumerable: false,
      });
    } catch (e) {}
  };

  const Canvas = HTMLCanvasElement.prototype;
  const realToDataURL = Canvas.toDataURL;
  // Referencia privada (a prova do shield) + trava o prototipo com a impl real.
  lock(window, '__cvRealToDataURL', realToDataURL);
  lock(Canvas, 'toDataURL', realToDataURL);

  window.__cvCanvases = [];
  const track = (cv) => {
    try {
      if (cv && cv.width > 1 && cv.height > 1 && window.__cvCanvases.indexOf(cv) === -1) {
        window.__cvCanvases.push(cv);
      }
    } catch (e) {}
  };

  const Ctx = window.CanvasRenderingContext2D && window.CanvasRenderingContext2D.prototype;
  if (Ctx) {
    const realDraw = Ctx.drawImage;
    const realPut = Ctx.putImageData;
    if (realDraw) {
      lock(Ctx, 'drawImage', function () {
        const r = realDraw.apply(this, arguments);
        track(this.canvas);
        return r;
      });
    }
    if (realPut) {
      lock(Ctx, 'putImageData', function () {
        const r = realPut.apply(this, arguments);
        track(this.canvas);
        return r;
      });
    }
  }

  // Le os pixels reais de cada canvas (desenhado ou no DOM). Ignora canvas pequeno
  // (UI / captcha-canvas 240x70). Usa SEMPRE a toDataURL real guardada.
  window.__cvDump = (minSide) => {
    const min = minSide || 200;
    const out = [];
    const seen = new Set();
    const pool = new Set(window.__cvCanvases || []);
    document.querySelectorAll('canvas').forEach((c) => pool.add(c));
    for (const cv of pool) {
      try {
        if (!cv || cv.width < min || cv.height < min) continue;
        const url = window.__cvRealToDataURL.call(cv, 'image/png');
        if (!url || url === 'data:,' || seen.has(url)) continue;
        seen.add(url);
        out.push({ dataUrl: url, width: cv.width, height: cv.height });
      } catch (e) {}
    }
    return out;
  };
})();
"""


# --------------------------------------------------------------------------- #
# Helpers de saida / blobs
# --------------------------------------------------------------------------- #
def safe_slug(value: str) -> str:
    return clean_filename(value, fallback="capitulo")


def image_extension(mime: str, content: bytes) -> str:
    mime = (mime or "").lower().split(";", 1)[0].strip()
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


def output_directory(root: Path, chapter_url: str) -> Path:
    chapter_slug = Path(urlparse(chapter_url).path.rstrip("/")).name
    target = root / safe_slug(chapter_slug)
    target.mkdir(parents=True, exist_ok=True)
    return target


# --------------------------------------------------------------------------- #
# Browser (Playwright)
# --------------------------------------------------------------------------- #
def is_cloudflare_challenge(page) -> bool:
    try:
        title = (page.title() or "").casefold()
    except Exception:
        return False
    return any(m in title for m in ("just a moment", "um momento", "verificando"))


def is_rate_limited(page) -> tuple[bool, str]:
    """Detecta a pagina 'Rapido demais!' (lockout por IP). Retorna (bool, quando).

    Usa textContent (nao innerText) porque o bloco do loader costuma estar oculto
    no momento do check e innerText ignora texto de elementos invisiveis.
    """
    try:
        info = page.evaluate(
            """() => {
                const b = document.body;
                if (!b) return '';
                return (b.textContent || '').replace(/\\s+/g, ' ').slice(0, 2000);
            }"""
        ) or ""
    except Exception:
        return (False, "")
    low = info.casefold()
    if "rapido demais" in low or "rápido demais" in low or "muitas visitas" in low:
        when = ""
        m = re.search(r"liberado.*?(\d{1,2}:\d{2}[^.<]*)", info, re.IGNORECASE)
        if m:
            when = m.group(1).strip()
        return (True, when)
    return (False, "")


def is_cloudflare_blocked(page) -> tuple[bool, str]:
    """Detecta o block DURO do Cloudflare (1020 / WAF). Retorna (bool, ray_id).

    Diferente do challenge Turnstile: NAO ha desafio p/ resolver -- o firewall
    nega o acesso pelo IP/fingerprint. So sai trocando de IP (--proxy/VPN),
    esperando o block envelhecer, ou o dono do site liberar.
    """
    try:
        title = (page.title() or "").casefold()
    except Exception:
        title = ""
    try:
        info = page.evaluate(
            """() => {
                const b = document.body;
                if (!b) return '';
                return (b.textContent || '').replace(/\\s+/g, ' ').slice(0, 2000);
            }"""
        ) or ""
    except Exception:
        info = ""
    low = info.casefold()
    blocked = (
        "attention required" in title
        or "sorry, you have been blocked" in low
        or "you are unable to access" in low
    )
    if not blocked:
        return (False, "")
    ray = ""
    m = re.search(r"Ray ID:\s*([0-9a-f]+)", info, re.IGNORECASE)
    if m:
        ray = m.group(1).strip()
    return (True, ray)


def wait_for_user_to_pass(page, timeout_seconds: int) -> None:
    if not is_cloudflare_challenge(page):
        return
    print(">> Cloudflare detectado. Resolva a verificacao na janela do navegador.")
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        page.wait_for_timeout(1000)
        if not is_cloudflare_challenge(page):
            print(">> Verificacao concluida. Seguindo...")
            return
    raise TimeoutError("Cloudflare nao foi concluido dentro do tempo limite.")


def auto_solve_challenge(page, solver, timeout_seconds: int) -> None:
    """Resolve o Turnstile via servico (CapSolver/2captcha) e injeta o token.

    Levanta CaptchaError em qualquer falha (sem sitekey, sem token, sem liberar).
    """
    print(f">> Cloudflare detectado. Resolvendo automaticamente via {solver.name}...")

    # 1) Espera os parametros do widget aparecerem (hook em turnstile.render).
    params_raw = None
    param_deadline = time.monotonic() + 60
    while time.monotonic() < param_deadline:
        if not is_cloudflare_challenge(page):
            return  # liberou sozinho antes de precisar resolver
        params_raw = page.evaluate("() => window.__cfTurnstileParams")
        if params_raw and params_raw.get("sitekey"):
            break
        page.wait_for_timeout(500)

    user_agent = page.evaluate("() => navigator.userAgent") or ""
    params = TurnstileParams.from_page(params_raw, user_agent=user_agent)
    print(f">> Turnstile sitekey={params.sitekey} action={params.action}. Enviando ao servico...")

    # 2) Resolve no servico externo (pode levar dezenas de segundos).
    token = solver.solve_turnstile(params)
    print(">> Token recebido. Injetando na pagina...")

    # 3) Injeta o token e dispara o callback do widget.
    page.evaluate(TURNSTILE_INJECT_JS, token)

    # 4) Espera o Cloudflare validar e liberar.
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        page.wait_for_timeout(1000)
        if not is_cloudflare_challenge(page):
            print(">> Verificacao concluida (automatica). Seguindo...")
            return
    raise CaptchaError("Token injetado, mas o Cloudflare nao liberou no tempo limite.")


def solve_clearance(page, context, args, solver) -> None:
    """Resolve cf_clearance via AntiCloudflareTask (proxy-matched) e injeta o cookie.

    O cookie fica preso a (User-Agent, IP do proxy); por isso passamos a UA real do
    browser ao servico e o browser/cloudscraper usam o MESMO proxy.
    """
    if solver is None or not solver.supports_clearance:
        raise CaptchaError(f"{getattr(solver, 'name', 'solver')} nao suporta cf_clearance.")
    proxy = getattr(args, "proxy_config", None)
    if proxy is None:
        raise CaptchaError("cf_clearance exige --proxy (cookie fica preso ao IP).")

    user_agent = page.evaluate("() => navigator.userAgent") or ""
    print(f">> Resolvendo cf_clearance via {solver.name} (proxy {proxy.host}:{proxy.port})...")
    solution: CloudflareSolution = solver.solve_cloudflare_clearance(
        args.chapter_url, proxy, user_agent=user_agent
    )

    new_cookies = [
        {"name": name, "value": value, "url": args.chapter_url}
        for name, value in (solution.cookies or {"cf_clearance": solution.cf_clearance}).items()
        if name and value
    ]
    context.add_cookies(new_cookies)
    print(f">> cf_clearance injetado ({len(new_cookies)} cookie(s)). Recarregando...")

    page.goto(args.chapter_url, wait_until="domcontentloaded", timeout=60_000)
    deadline = time.monotonic() + args.challenge_timeout
    while time.monotonic() < deadline:
        if not is_cloudflare_challenge(page):
            print(">> cf_clearance aceito. Cloudflare liberado.")
            return
        page.wait_for_timeout(1000)
    raise CaptchaError("cf_clearance injetado, mas o Cloudflare nao liberou (UA/IP podem nao bater).")


def pass_cloudflare(page, context, args, solver) -> None:
    """Prioridade: cf_clearance (se pedido) -> token Turnstile -> manual."""
    if not is_cloudflare_challenge(page):
        return

    if solver is not None and args.cf_clearance:
        try:
            solve_clearance(page, context, args, solver)
            return
        except CaptchaError as exc:
            print(f">> Solve de cf_clearance falhou: {exc}")
            print(">> Tentando token Turnstile...")

    if solver is not None:
        try:
            auto_solve_challenge(page, solver, args.challenge_timeout)
            return
        except CaptchaError as exc:
            print(f">> Auto-captcha falhou: {exc}")
            if args.headless:
                raise
            print(">> Caindo para resolucao manual na janela.")
    wait_for_user_to_pass(page, args.challenge_timeout)


def build_captcha_solver(args):
    """Monta o solver conforme CLI/env. Retorna None se desativado/indisponivel."""
    if args.no_auto_captcha:
        return None
    try:
        solver = build_solver(args.captcha_provider, args.captcha_key, timeout=args.captcha_timeout)
    except CaptchaError as exc:
        print(f">> Auto-captcha indisponivel ({exc}). Usando resolucao manual.")
        return None
    print(f">> Auto-captcha ativo via {solver.name}.")
    return solver


def open_context(playwright, args):
    """Retorna (context, cleanup). Tenta CDP; cai para perfil persistente visivel."""
    cdp_url = (args.cdp_url or "").strip()
    proxy = getattr(args, "proxy_config", None)
    if cdp_url and args.use_cdp:
        try:
            browser = playwright.chromium.connect_over_cdp(cdp_url, timeout=8000)
            if proxy is not None:
                # CDP nao injeta proxy num browser ja aberto: tenta novo contexto
                # com proxy; se o browser ignorar, avisa p/ subir o Chrome com
                # --proxy-server=host:port (senao IP nao bate com o cf_clearance).
                try:
                    context = browser.new_context(proxy=proxy.playwright())
                    print(f">> CDP: novo contexto via proxy {proxy.host}:{proxy.port}.")
                except Exception as exc:
                    context = browser.contexts[0] if browser.contexts else browser.new_context()
                    print(
                        f">> CDP nao aceitou proxy ({exc}). Suba o Chrome com "
                        f"--proxy-server={proxy.host}:{proxy.port} p/ o cf_clearance bater."
                    )
            else:
                context = browser.contexts[0] if browser.contexts else browser.new_context()
            print(f">> Conectado via CDP em {cdp_url}")
            return context, browser.close
        except Exception as exc:
            print(f">> CDP indisponivel ({exc}). Abrindo navegador proprio...")

    profile = Path(args.profile).resolve()
    profile.mkdir(parents=True, exist_ok=True)
    launch_options = {
        "user_data_dir": str(profile),
        "headless": args.headless,
        "viewport": {"width": 1280, "height": 900},
        "args": [
            "--disable-blink-features=AutomationControlled",
            "--no-default-browser-check",
            "--no-first-run",
        ],
        "ignore_default_args": ["--enable-automation"],
    }
    proxy = getattr(args, "proxy_config", None)
    if proxy is not None:
        launch_options["proxy"] = proxy.playwright()
        print(f">> Browser via proxy {proxy.host}:{proxy.port}")
    candidates: list[dict] = []
    for path in SAKURA_BRAVE_PATHS:
        if path.exists():
            candidates.append({"executable_path": str(path)})
    candidates.extend(({"channel": "chrome"}, {"channel": "msedge"}, {}))

    errors: list[str] = []
    for opts in candidates:
        try:
            context = playwright.chromium.launch_persistent_context(**opts, **launch_options)
            return context, context.close
        except Exception as exc:
            errors.append(str(exc).splitlines()[0])
    raise RuntimeError("Nenhum Chromium compativel abriu: " + " | ".join(errors))


def collect_diagnostics(page) -> dict:
    try:
        data = page.evaluate(
            """() => {
                const imgs = Array.from(document.querySelectorAll('img'));
                const scheme = (s) => (s || '').split(':', 1)[0];
                const sample = imgs.slice(0, 12).map(i => ({
                    src: (i.currentSrc || i.src || '').slice(0, 120),
                    dataSrc: (i.getAttribute('data-src') || '').slice(0, 120),
                    cls: (i.className || '').slice(0, 60),
                }));
                return {
                    url: location.href,
                    title: document.title,
                    img_total: imgs.length,
                    img_blob: imgs.filter(i => scheme(i.currentSrc || i.src) === 'blob').length,
                    img_http: imgs.filter(i => /^https?/.test(i.currentSrc || i.src)).length,
                    img_data: imgs.filter(i => scheme(i.currentSrc || i.src) === 'data').length,
                    canvas: document.querySelectorAll('canvas').length,
                    iframes: Array.from(document.querySelectorAll('iframe')).map(f => (f.src || '').slice(0, 120)),
                    sample,
                };
            }"""
        )
        return data or {}
    except Exception as exc:
        return {"error": str(exc)}


def dump_diagnostics(page, target: Path, diag: dict) -> None:
    try:
        (target / "diagnostico.json").write_text(
            json.dumps(diag, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        pass
    try:
        (target / "pagina.html").write_text(page.content(), encoding="utf-8")
    except Exception:
        pass
    try:
        page.screenshot(path=str(target / "pagina.png"), full_page=True)
    except Exception:
        pass
    print(f">> Diagnostico salvo em {target} (diagnostico.json, pagina.html, pagina.png)")


def select_reader_selector(page) -> str:
    if page.locator(SAKURA_READER_SELECTOR).count() > 0:
        return SAKURA_READER_SELECTOR
    if page.locator(SAKURA_FALLBACK_SELECTOR).count() > 0:
        return SAKURA_FALLBACK_SELECTOR
    raise RuntimeError("Nenhuma imagem blob encontrada no leitor.")


def hydrate_reader(page, selector: str, max_passes: int = 6) -> int:
    previous: tuple[int, int, int] | None = None
    stable = 0
    for _ in range(max_passes):
        metrics = page.evaluate(
            "() => ({height: Math.max(document.body.scrollHeight, document.documentElement.scrollHeight),"
            " viewport: window.innerHeight || 720})"
        )
        step = max(500, int(metrics["viewport"] * 0.8))
        for y in range(0, int(metrics["height"]) + step, step):
            page.evaluate("y => window.scrollTo(0, y)", y)
            page.wait_for_timeout(80)
        page.wait_for_timeout(500)
        state = page.evaluate(
            "selector => { const i = Array.from(document.querySelectorAll(selector));"
            " return {count: i.length, loaded: i.filter(x => x.complete && x.naturalWidth > 0).length,"
            " height: Math.max(document.body.scrollHeight, document.documentElement.scrollHeight)}; }",
            selector,
        )
        signature = (state["count"], state["loaded"], state["height"])
        stable = stable + 1 if signature == previous else 0
        previous = signature
        if state["count"] > 0 and state["loaded"] == state["count"] and stable >= 1:
            break
    page.evaluate("window.scrollTo(0, 0)")
    return previous[0] if previous else page.locator(selector).count()


def extract_blob_pages(page, selector: str, target: Path) -> list[dict]:
    count = page.locator(selector).count()
    seen: set[str] = set()
    manifest: list[dict] = []
    for dom_index in range(count):
        payload = page.evaluate(SAKURA_EXTRACT_BLOB_JS, {"selector": selector, "index": dom_index})
        if not payload or not payload.get("dataUrl"):
            continue
        try:
            _, encoded = str(payload["dataUrl"]).split(",", 1)
            content = base64.b64decode(encoded, validate=True)
        except Exception:
            continue
        if not content:
            continue
        digest = hashlib.sha256(content).hexdigest()
        if digest in seen:
            continue
        seen.add(digest)

        page_number = len(manifest) + 1
        extension = image_extension(payload.get("mime", ""), content)
        filename = f"pagina_{page_number:03d}{extension}"
        (target / filename).write_bytes(content)
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
            }
        )
        print(f"[{page_number:03d}] {filename} ({len(content):,} bytes)")
    return manifest


# --------------------------------------------------------------------------- #
# Captura por REDE (vence o shield anti-extracao do DOM)
# --------------------------------------------------------------------------- #
# O sakuramangas injeta JS que poisona toDataURL (-> "data:,") e mascara o src
# das <img> do leitor. O shield atua no DOM, nao na pilha de rede: capturamos os
# bytes direto das respostas HTTP (page.on("response")).

CAPTURE_IMAGE_MIMES = ("image/jpeg", "image/jpg", "image/png", "image/webp", "image/avif", "image/gif")
CAPTURE_SKIP_HINTS = ("logo", "sprite", "avatar", "favicon", "icon", "/ads", "a-ads", "banner", "captcha", "thumb")
CAPTURE_MIN_BYTES = 6_000  # descarta icones/ui pequenos

# Cookies sensiveis: nunca gravar valor no manifest (mesmo com --dump-cookies).
SENSITIVE_COOKIES = {"cf_clearance", "__cf_bm", "__cfwaituntil"}


def attach_image_capture(page) -> list[dict]:
    """Liga um listener que guarda as respostas de imagem do leitor (em ordem)."""
    store: list[dict] = []
    seen_urls: set[str] = set()

    def on_response(response):
        try:
            url = response.url
            if url in seen_urls:
                return
            mime = (response.headers.get("content-type", "") or "").lower().split(";", 1)[0].strip()
            if mime not in CAPTURE_IMAGE_MIMES:
                return
            low = url.lower()
            if any(hint in low for hint in CAPTURE_SKIP_HINTS):
                return
            body = response.body()
            if not body or len(body) < CAPTURE_MIN_BYTES:
                return
            seen_urls.add(url)
            store.append({"url": url, "mime": mime, "body": body})
        except Exception:
            pass  # respostas de cache/abortadas nao tem body

    page.on("response", on_response)
    return store


def scroll_page(page, max_passes: int = 8) -> None:
    """Rola a pagina toda varias vezes p/ disparar o lazy-load das imagens."""
    previous_height = -1
    for _ in range(max_passes):
        metrics = page.evaluate(
            "() => ({height: Math.max(document.body.scrollHeight, document.documentElement.scrollHeight),"
            " viewport: window.innerHeight || 720})"
        )
        step = max(500, int(metrics["viewport"] * 0.8))
        for y in range(0, int(metrics["height"]) + step, step):
            page.evaluate("y => window.scrollTo(0, y)", y)
            page.wait_for_timeout(120)
        page.wait_for_timeout(600)
        height = page.evaluate(
            "() => Math.max(document.body.scrollHeight, document.documentElement.scrollHeight)"
        )
        if height == previous_height:
            break
        previous_height = height
    page.evaluate("window.scrollTo(0, 0)")


def save_captured_images(store: list[dict], target: Path) -> list[dict]:
    """Grava as imagens capturadas por rede, deduplicando por conteudo (sha256)."""
    seen: set[str] = set()
    manifest: list[dict] = []
    for item in store:
        content = item.get("body") or b""
        if len(content) < CAPTURE_MIN_BYTES:
            continue
        digest = hashlib.sha256(content).hexdigest()
        if digest in seen:
            continue
        seen.add(digest)

        page_number = len(manifest) + 1
        extension = image_extension(item.get("mime", ""), content)
        filename = f"pagina_{page_number:03d}{extension}"
        (target / filename).write_bytes(content)
        manifest.append(
            {
                "page": page_number,
                "filename": filename,
                "sha256": digest,
                "bytes": len(content),
                "mime": item.get("mime", ""),
                "source_url": item.get("url", ""),
                "via": "network",
            }
        )
        print(f"[{page_number:03d}] {filename} ({len(content):,} bytes)  <- rede")
    return manifest


def extract_canvas_pages(page, target: Path, min_side: int = 200) -> list[dict]:
    """Le os pixels reais dos canvas via __cvDump (bypass do shield) e grava PNGs."""
    try:
        dumps = page.evaluate("(min) => (window.__cvDump ? window.__cvDump(min) : [])", min_side)
    except Exception as exc:
        print(f">> __cvDump indisponivel ({exc}).")
        return []

    seen: set[str] = set()
    manifest: list[dict] = []
    for item in dumps or []:
        data_url = item.get("dataUrl") if isinstance(item, dict) else None
        if not data_url or "," not in data_url:
            continue
        try:
            _, encoded = data_url.split(",", 1)
            content = base64.b64decode(encoded, validate=True)
        except Exception:
            continue
        if len(content) < CAPTURE_MIN_BYTES:
            continue
        digest = hashlib.sha256(content).hexdigest()
        if digest in seen:
            continue
        seen.add(digest)

        page_number = len(manifest) + 1
        filename = f"pagina_{page_number:03d}.png"
        (target / filename).write_bytes(content)
        manifest.append(
            {
                "page": page_number,
                "filename": filename,
                "sha256": digest,
                "bytes": len(content),
                "mime": "image/png",
                "width": item.get("width", 0),
                "height": item.get("height", 0),
                "via": "canvas",
            }
        )
        print(f"[{page_number:03d}] {filename} ({len(content):,} bytes)  <- canvas")
    return manifest


# --------------------------------------------------------------------------- #
# Extracao das <img> reais do leitor (vence o shield via getElementsByTagName)
# --------------------------------------------------------------------------- #
# O shield filtra as <img> do #pges_51dwq1 em querySelector(All), mas NAO toca em
# getElementsByTagName / .children / .src nem na execucao de fetch. Lemos as imgs
# por essa brecha, baixamos os bytes via cloudscraper (http) ou fetch in-page
# (blob/data). Scroll e por mouse-wheel (CDP), pois scrollTo() em JS foi anulado.

READER_CONTAINER_ID = "pges_51dwq1"

# Conta as imgs do leitor pela brecha (getElementsByTagName).
READER_COUNT_JS = """
() => {
  const box = document.getElementById('%s');
  return box ? box.getElementsByTagName('img').length : 0;
}
""" % READER_CONTAINER_ID

# Le as imgs do leitor em ordem; p/ blob:/data: ja resolve os bytes em base64
# (fetch + FileReader continuam vivos sob o shield).
READER_READ_JS = """
async () => {
  const box = document.getElementById('%s');
  if (!box) return [];
  const imgs = Array.from(box.getElementsByTagName('img'));
  const toDataUrl = (blob) => new Promise((res, rej) => {
    const fr = new FileReader();
    fr.onload = () => res(fr.result);
    fr.onerror = rej;
    fr.readAsDataURL(blob);
  });
  const out = [];
  for (let i = 0; i < imgs.length; i++) {
    const im = imgs[i];
    const src = im.currentSrc || im.src || im.getAttribute('src') || '';
    let dataUrl = null;
    if (src.startsWith('blob:') || src.startsWith('data:')) {
      try {
        const r = await fetch(src);
        dataUrl = await toDataUrl(await r.blob());
      } catch (e) {}
    }
    out.push({ index: i, src: src, dataUrl: dataUrl });
  }
  return out;
}
""" % READER_CONTAINER_ID


def wait_reader_images(page, timeout_seconds: int) -> int:
    """Espera o #pges_51dwq1 ter imgs (lendo pela brecha). Retorna a contagem."""
    deadline = time.monotonic() + timeout_seconds
    last = 0
    while time.monotonic() < deadline:
        try:
            last = page.evaluate(READER_COUNT_JS) or 0
        except Exception:
            last = 0
        if last > 0:
            return last
        page.wait_for_timeout(500)
    return last


def mouse_scroll_all(page, max_steps: int = 60, delta: int = 1000) -> None:
    """Rola via mouse-wheel (CDP) ate a contagem de imgs estabilizar.

    Necessario porque o shield anulou window.scrollTo/scrollBy/scrollIntoView.
    """
    stable = 0
    previous = -1
    for _ in range(max_steps):
        try:
            page.mouse.wheel(0, delta)
        except Exception:
            break
        page.wait_for_timeout(180)
        try:
            count = page.evaluate(READER_COUNT_JS) or 0
        except Exception:
            count = previous
        stable = stable + 1 if count == previous else 0
        previous = count
        if count > 0 and stable >= 3:
            break


def fetch_in_page(page, url: str) -> bytes | None:
    """Baixa uma URL pelo fetch do PROPRIO browser (sessao autenticada).

    Ultimo recurso p/ imgs http quando cloudscraper/rede falham. fetch continua
    executavel sob o shield (so foi travado contra reconfiguracao).
    """
    try:
        data_url = page.evaluate(
            """async (u) => {
                const r = await fetch(u, { credentials: 'include' });
                if (!r.ok) return null;
                const b = await r.blob();
                return await new Promise((res, rej) => {
                    const fr = new FileReader();
                    fr.onload = () => res(fr.result);
                    fr.onerror = rej;
                    fr.readAsDataURL(b);
                });
            }""",
            url,
        )
    except Exception:
        return None
    if not data_url or "," not in str(data_url):
        return None
    try:
        return base64.b64decode(str(data_url).split(",", 1)[1], validate=True)
    except Exception:
        return None


def _decode_data_url(data_url: str) -> tuple[bytes, str]:
    head, encoded = str(data_url).split(",", 1)
    mime = ""
    if head.startswith("data:"):
        mime = head[5:].split(";", 1)[0]
    return base64.b64decode(encoded, validate=True), mime


def save_reader_images(items, scraper, capture_store, page, target: Path) -> list[dict]:
    """Baixa+grava as imgs do leitor em ordem.

    Fonte dos bytes por tipo de src:
      - blob:/data: -> ja vem em dataUrl (fetch in-page resolvido no JS).
      - http(s)     -> cloudscraper (cookies cf) -> captura de rede -> fetch in-page.
    """
    capture_index = {c.get("url"): c.get("body") for c in (capture_store or []) if c.get("url")}
    seen: set[str] = set()
    manifest: list[dict] = []

    for item in sorted(items or [], key=lambda x: x.get("index", 0)):
        src = (item.get("src") or "").strip()
        data_url = item.get("dataUrl")
        content: bytes | None = None
        mime = ""
        source = ""

        if data_url:  # blob:/data: resolvido no navegador
            try:
                content, mime = _decode_data_url(data_url)
                source = "in-page"
            except Exception:
                content = None
        elif src.startswith("http"):
            # 1) cloudscraper (com cookies do Cloudflare)
            try:
                resp = scraper.get(src, timeout=30)
                if resp.status_code == 200 and resp.content:
                    content = resp.content
                    mime = resp.headers.get("Content-Type", "")
                    source = "cloudscraper"
            except Exception:
                content = None
            # 2) captura de rede (page.on response)
            if not content and src in capture_index:
                content = capture_index[src]
                source = "rede"
            # 3) fetch in-page (sessao autenticada do browser)
            if not content:
                content = fetch_in_page(page, src)
                if content:
                    source = "in-page"

        if not content or len(content) < CAPTURE_MIN_BYTES:
            continue
        digest = hashlib.sha256(content).hexdigest()
        if digest in seen:
            continue
        seen.add(digest)

        page_number = len(manifest) + 1
        extension = image_extension(mime, content)
        filename = f"pagina_{page_number:03d}{extension}"
        (target / filename).write_bytes(content)
        manifest.append(
            {
                "page": page_number,
                "dom_index": item.get("index", page_number - 1),
                "filename": filename,
                "sha256": digest,
                "bytes": len(content),
                "mime": mime,
                "source_url": src,
                "via": source or "reader",
            }
        )
        print(f"[{page_number:03d}] {filename} ({len(content):,} bytes)  <- {source or 'reader'}")
    return manifest


def extract_sakura_reader(page, scraper, capture_store, target: Path, image_timeout: int) -> list[dict]:
    """Caminho primario do sakura: imgs reais do leitor via brecha + download."""
    found = wait_reader_images(page, image_timeout)
    if not found:
        print(">> #pges_51dwq1 sem imgs (leitor nao carregou).")
        return []
    print(f">> Leitor: {found} img(s) detectada(s) (via getElementsByTagName).")
    mouse_scroll_all(page)
    page.wait_for_timeout(800)
    items = page.evaluate(READER_READ_JS) or []
    page.evaluate("() => window.scrollTo && window.scrollTo(0, 0)")  # noop sob shield, ok
    return save_reader_images(items, scraper, capture_store, page, target)


# Cookies do Cloudflare que valem a pena persistir p/ reuso (pulam o desafio).
CLEARANCE_COOKIE_NAMES = {"cf_clearance", "__cf_bm", "cf_chl_rc_m"}


def clearance_cache_path(args) -> Path:
    if args.clearance_cache:
        return Path(args.clearance_cache)
    return Path(args.profile).resolve() / ".sakura-clearance.json"


def _proxy_signature(args) -> str:
    proxy = getattr(args, "proxy_config", None)
    return f"{proxy.host}:{proxy.port}" if proxy else ""


def load_clearance_cache(args) -> dict | None:
    """Le cf_clearance salvo se host+proxy batem e nao expirou. Senao None."""
    if args.no_clearance_cache:
        return None
    path = clearance_cache_path(args)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None

    host = urlparse(args.chapter_url).hostname or ""
    if data.get("host") != host:
        return None
    if data.get("proxy", "") != _proxy_signature(args):
        return None  # IP do proxy mudou -> cf_clearance invalido

    cookies = data.get("cookies") or []
    cf = next((c for c in cookies if c.get("name") == "cf_clearance"), None)
    if not cf:
        return None
    expires = cf.get("expires", -1)
    if expires not in (-1, None) and expires <= time.time() + 60:
        return None  # expirado (margem de 60s)
    return {"cookies": cookies, "user_agent": data.get("user_agent")}


def save_clearance_cache(args, cookies: list[dict], user_agent: str) -> None:
    """Persiste os cookies de clearance + assinatura (host/proxy/UA) p/ reuso."""
    if args.no_clearance_cache:
        return
    relevant = [c for c in cookies if c.get("name") in CLEARANCE_COOKIE_NAMES]
    if not any(c.get("name") == "cf_clearance" for c in relevant):
        return  # nada util p/ salvar
    payload = {
        "host": urlparse(args.chapter_url).hostname or "",
        "proxy": _proxy_signature(args),
        "user_agent": user_agent,
        "saved_at": time.time(),
        "cookies": relevant,
    }
    path = clearance_cache_path(args)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f">> cf_clearance salvo em {path} (reuso futuro).")
    except Exception as exc:
        print(f">> Falha ao salvar clearance cache: {exc}")


def build_cloudscraper(cookies: list[dict], user_agent: str, referer: str, proxy=None):
    scraper = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "mobile": False}
    )
    headers = dict(DEFAULT_HEADERS)
    if user_agent:
        headers["User-Agent"] = user_agent
    headers["Referer"] = referer
    scraper.headers.update(headers)
    if proxy is not None:
        scraper.proxies.update(proxy.requests_proxies())
    for cookie in cookies:
        name = cookie.get("name")
        value = cookie.get("value")
        if not name:
            continue
        kwargs = {"path": cookie.get("path", "/")}
        if cookie.get("domain"):
            kwargs["domain"] = cookie["domain"]
        scraper.cookies.set(name, value, **kwargs)
    return scraper


def probe_cloudscraper(scraper, url: str) -> dict:
    """Valida que a sessao cloudscraper passa pelo Cloudflare."""
    try:
        response = scraper.get(url, timeout=30, allow_redirects=True)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    body_head = (response.text or "")[:600].casefold()
    blocked = "just a moment" in body_head or "cf-challenge" in body_head
    return {
        "ok": response.status_code == 200 and not blocked,
        "status": response.status_code,
        "content_type": response.headers.get("Content-Type", ""),
        "bytes": len(response.content),
        "cloudflare_block": blocked,
    }


# --------------------------------------------------------------------------- #
# Orquestracao
# --------------------------------------------------------------------------- #
def run(args: argparse.Namespace) -> int:
    if sync_playwright is None:
        raise RuntimeError("Playwright ausente. Instale: pip install playwright && playwright install chromium")

    target = output_directory(Path(args.output), args.chapter_url)
    args.proxy_config = ProxyConfig.parse(args.proxy) if args.proxy else None
    solver = build_captcha_solver(args)

    with sync_playwright() as playwright:
        context, cleanup = open_context(playwright, args)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.add_init_script(CANVAS_DRM_BYPASS_JS)
            page.add_init_script(STEALTH_JS)
            page.add_init_script(TURNSTILE_INTERCEPT_JS)
            page.add_init_script(SAKURA_BLOB_PROBE_JS)
            capture = attach_image_capture(page)

            cached = load_clearance_cache(args)
            if cached:
                try:
                    context.add_cookies(cached["cookies"])
                    print(">> cf_clearance reaproveitado do cache (pulando solve, se valido).")
                except Exception as exc:
                    print(f">> Cache de clearance ignorado ({exc}).")

            print(f">> Abrindo {args.chapter_url}")
            page.goto(args.chapter_url, wait_until="domcontentloaded", timeout=60_000)
            pass_cloudflare(page, context, args, solver)

            # Passou pelo Cloudflare: persiste o cf_clearance atual p/ reuso.
            current_ua = page.evaluate("() => navigator.userAgent") or ""
            save_clearance_cache(args, context.cookies(), current_ua)

            # Block DURO do Cloudflare (1020/WAF): IP/fingerprint negado, sem desafio.
            blocked, ray = is_cloudflare_blocked(page)
            if blocked:
                raise RuntimeError(
                    "Cloudflare bloqueou o acesso (1020 'Sorry, you have been blocked')"
                    + (f" - Ray ID {ray}." if ray else ".")
                    + " Nao ha desafio p/ resolver: o IP/fingerprint esta na blocklist. "
                    "Use --proxy/VPN p/ trocar de IP, espere o block envelhecer, ou peca "
                    "ao dono do site p/ liberar."
                )

            # Lockout por IP do proprio site ("Rapido demais!").
            limited, when = is_rate_limited(page)
            if limited:
                raise RuntimeError(
                    "Site aplicou rate-limit por IP ('Rapido demais!')"
                    + (f" - acesso liberado as {when}." if when else ".")
                    + " Aguarde a liberacao ou use --proxy p/ trocar de IP."
                )

            user_agent = page.evaluate("() => navigator.userAgent") or ""
            cookies = context.cookies()

            # cloudscraper: sessao HTTP com os cookies do Cloudflare (baixa as paginas).
            scraper = build_cloudscraper(cookies, user_agent, args.chapter_url, proxy=args.proxy_config)
            http_probe = probe_cloudscraper(scraper, args.chapter_url)
            status = http_probe.get("status")
            if http_probe.get("ok"):
                print(f">> cloudscraper OK (HTTP {status}, {http_probe.get('bytes', 0):,} bytes).")
            else:
                print(f">> cloudscraper sem clearance (HTTP {status}).")

            manifest: list[dict] = []

            # 1) PRIMARIO: <img> reais do leitor via brecha getElementsByTagName +
            #    download por cloudscraper/rede/fetch-in-page (vence o shield).
            try:
                manifest = extract_sakura_reader(page, scraper, capture, target, args.image_timeout)
            except Exception as exc:
                print(f">> Caminho img do leitor falhou: {exc}")

            # 2) Fallback: blob: classico (leitores antigos).
            if not manifest:
                try:
                    page.wait_for_selector(SAKURA_FALLBACK_SELECTOR, timeout=min(args.image_timeout, 15) * 1000)
                    selector = select_reader_selector(page)
                    total = hydrate_reader(page, selector)
                    print(f">> Leitor hidratado: {total} imagens blob no DOM.")
                    manifest = extract_blob_pages(page, selector, target)
                except Exception:
                    pass

            # 3) Fallback: bypass canvas-DRM (le pixels reais do canvas).
            if not manifest:
                mouse_scroll_all(page)
                page.wait_for_timeout(1000)
                manifest = extract_canvas_pages(page, target)
                if manifest:
                    print(f">> {len(manifest)} pagina(s) via canvas (bypass DRM).")

            # 4) Ultimo recurso: imagens image/* capturadas na camada de rede.
            if not manifest:
                manifest = save_captured_images(capture, target)

            if not manifest:
                diag = collect_diagnostics(page)
                dump_diagnostics(page, target, diag)
                raise RuntimeError(
                    "Nenhuma pagina extraida. "
                    f"Diagnostico salvo em {target}. titulo={diag.get('title')!r}, "
                    f"imgs={diag.get('img_total')}, canvas={diag.get('canvas')}, "
                    f"capturadas_rede={len(capture)}"
                )

        finally:
            try:
                cleanup()
            except Exception:
                pass

    cookie_summary = [
        {
            "name": c.get("name"),
            "domain": c.get("domain"),
            "value": c.get("value") if args.dump_cookies and c.get("name") not in SENSITIVE_COOKIES else "[REDACTED]",
        }
        for c in cookies
    ]
    (target / "manifest.json").write_text(
        json.dumps(
            {
                "chapter_url": args.chapter_url,
                "pages": manifest,
                "http_probe": http_probe,
                "user_agent": user_agent,
                "cookies": cookie_summary,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"OK: {len(manifest)} paginas unicas em {target}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Requisitor Sakura Mangas: Playwright (voce resolve o captcha) + cloudscraper."
    )
    parser.add_argument("chapter_url", help="URL absoluta do capitulo.")
    parser.add_argument("--output", default="downloads/sakura", help="Pasta raiz de saida.")
    parser.add_argument(
        "--profile",
        default=DEFAULT_SAKURA_PROFILE_DIR,
        help="Perfil Chromium persistente (mantem cookies do Cloudflare).",
    )
    parser.add_argument("--cdp-url", default=DEFAULT_SAKURA_CDP_URL, help="Endpoint CDP de browser ja aberto.")
    parser.add_argument("--use-cdp", action="store_true", help="Conecta via CDP em vez de abrir browser proprio.")
    parser.add_argument("--headless", action="store_true", help="Sem janela (NAO da pra resolver captcha manual).")
    parser.add_argument("--challenge-timeout", type=int, default=240, help="Segundos p/ resolver o Cloudflare.")
    parser.add_argument("--image-timeout", type=int, default=90, help="Segundos esperando o leitor carregar.")
    parser.add_argument("--dump-cookies", action="store_true", help="Grava valores de cookies nao-sensiveis no manifest.")
    parser.add_argument(
        "--captcha-provider",
        default="capsolver",
        choices=["capsolver", "2captcha", "twocaptcha"],
        help="Servico de resolucao automatica do Turnstile.",
    )
    parser.add_argument(
        "--captcha-key",
        default=None,
        help="API key do servico (ou via env CAPSOLVER_API_KEY / TWOCAPTCHA_API_KEY).",
    )
    parser.add_argument("--captcha-timeout", type=int, default=180, help="Segundos p/ o servico resolver o captcha.")
    parser.add_argument(
        "--proxy",
        default=None,
        help="Proxy unico p/ browser+solver+HTTP: 'http://user:pass@host:port' ou 'host:port[:user:pass]'. "
        "Obrigatorio p/ --cf-clearance.",
    )
    parser.add_argument(
        "--cf-clearance",
        action="store_true",
        help="Prioriza solve do cookie cf_clearance (CapSolver AntiCloudflareTask, exige --proxy). "
        "Mais robusto que o token Turnstile no desafio interstitial.",
    )
    parser.add_argument(
        "--clearance-cache",
        default=None,
        help="Arquivo p/ salvar/reusar cf_clearance (padrao: <profile>/.sakura-clearance.json).",
    )
    parser.add_argument(
        "--no-clearance-cache",
        action="store_true",
        help="Nao salva nem reaproveita cf_clearance em disco.",
    )
    parser.add_argument(
        "--no-auto-captcha",
        action="store_true",
        help="Desativa auto-solve; resolve o Cloudflare manualmente na janela.",
    )
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
