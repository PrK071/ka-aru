"""Base OPCIONAL para fontes que exigem navegador (JS pesado / Cloudflare).

Isolada de proposito: os scrapers HTTP (requests/curl_cffi) NAO dependem disto.
So quem precisa de browser (JS pesado / anti-bot) herda de PlaywrightScraper.

Requisitos (so p/ essas fontes):
    pip install playwright
    playwright install chromium
"""

from __future__ import annotations

import logging
from pathlib import Path

from config import REQUEST_TIMEOUT, TEMP_DIR, USER_AGENT
from .base import BaseScraper, DownloadError

logger = logging.getLogger(__name__)

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None


# Coleta URLs de imagens de um seletor, tentando varios atributos lazy.
_COLLECT_JS = """
({ selector, attrs }) => {
  const out = [];
  document.querySelectorAll(selector).forEach((img) => {
    for (const a of attrs) {
      const v = img.getAttribute(a) || img[a];
      if (v && !String(v).startsWith('data:')) { out.push(String(v)); break; }
    }
  });
  return out;
}
"""


class PlaywrightScraper(BaseScraper):
    """Fornece um navegador headless reaproveitavel + helpers de render/scroll.

    O navegador e aberto sob demanda e reutilizado entre chamadas; lembre de
    chamar close() (ou deixe o __del__ cuidar) ao terminar.
    """

    headless: bool = True
    LAZY_ATTRS = ("data-src", "data-original", "data-lazy-src", "data-url", "currentSrc", "src")

    def __init__(self) -> None:
        super().__init__()
        if sync_playwright is None:
            raise RuntimeError(
                "Playwright ausente. Instale: pip install playwright && playwright install chromium"
            )
    headless: bool = True
    profile_dir: str | None = None  # se setado, usa contexto PERSISTENTE (mantem cf_clearance)
    LAZY_ATTRS = ("data-src", "data-original", "data-lazy-src", "data-url", "currentSrc", "src")

    def __init__(self) -> None:
        super().__init__()
        if sync_playwright is None:
            raise RuntimeError(
                "Playwright ausente. Instale: pip install playwright && playwright install chromium"
            )
        self._pw = None
        self._browser = None
        self._ctx = None
        self._page = None

    # --- ciclo de vida do browser ------------------------------------------
    def _ensure_page(self):
        if self._page is not None:
            return self._page
        self._pw = sync_playwright().start()
        import os
        from pathlib import Path as _Path
        _env = os.environ.get("MANGA_HEADLESS")
        headless = self.headless if _env is None else (_env not in ("0", "false", "False", "no"))
        common = {
            "headless": headless,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--no-default-browser-check",
            ],
            "ignore_default_args": ["--enable-automation"],
            "user_agent": USER_AGENT,
            "viewport": {"width": 1280, "height": 900},
        }

        if self.profile_dir:
            # Contexto PERSISTENTE: cf_clearance/cookies sobrevivem entre execucoes.
            profile = _Path(self.profile_dir).resolve()
            profile.mkdir(parents=True, exist_ok=True)
            channels = ["msedge", "chrome", None]
            last_exc = None
            for ch in channels:
                try:
                    kwargs = dict(common, user_data_dir=str(profile))
                    if ch:
                        kwargs["channel"] = ch
                    self._ctx = self._pw.chromium.launch_persistent_context(**kwargs)
                    break
                except Exception as exc:  # noqa: BLE001
                    last_exc = exc
            if self._ctx is None:
                raise RuntimeError(f"Nenhum navegador (persistente) abriu: {last_exc}")
            self._browser = None
            self._page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()
        else:
            ctx_opts = {k: common[k] for k in ("user_agent", "viewport")}
            launch_opts = {k: common[k] for k in ("headless", "args", "ignore_default_args")}
            channels = ["msedge", "chrome", None]
            last_exc = None
            for ch in channels:
                try:
                    self._browser = (self._pw.chromium.launch(channel=ch, **launch_opts)
                                     if ch else self._pw.chromium.launch(**launch_opts))
                    break
                except Exception as exc:  # noqa: BLE001
                    last_exc = exc
            if self._browser is None:
                raise RuntimeError(f"Nenhum navegador abriu: {last_exc}")
            self._ctx = self._browser.new_context(**ctx_opts)
            self._page = self._ctx.new_page()

        # mascara sinais obvios de automacao (ajuda a passar o Cloudflare)
        self._page.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
            "window.chrome=window.chrome||{runtime:{}};"
        )
        return self._page

    def close(self) -> None:
        for obj in (self._ctx, self._browser):
            try:
                if obj is not None:
                    obj.close()
            except Exception:
                pass
        try:
            if self._pw is not None:
                self._pw.stop()
        except Exception:
            pass
        self._page = self._ctx = self._browser = self._pw = None

    def __del__(self):  # best-effort
        try:
            self.close()
        except Exception:
            pass

    # --- helpers ------------------------------------------------------------
    def render(self, url: str, *, wait_selector: str | None = None,
               wait_ms: int = 0, timeout: int = 60_000):
        """Navega ate `url`, espera Cloudflare liberar e o seletor aparecer."""
        page = self._ensure_page()
        page.goto(url, wait_until="domcontentloaded", timeout=timeout)
        self._wait_cloudflare(page)
        if wait_selector:
            try:
                page.wait_for_selector(wait_selector, timeout=timeout)
            except Exception:
                pass
        if wait_ms:
            page.wait_for_timeout(wait_ms)
        return page

    @staticmethod
    def _wait_cloudflare(page, timeout_s: int = 90) -> None:
        """Espera o desafio 'Just a moment' do Cloudflare sumir (auto-resolve)."""
        import time as _t
        deadline = _t.monotonic() + timeout_s
        while _t.monotonic() < deadline:
            try:
                title = (page.title() or "").casefold()
            except Exception:
                title = ""
            if not any(m in title for m in ("just a moment", "um momento", "verificando", "moment...")):
                return
            page.wait_for_timeout(1000)

    def collect_images(self, page, selector: str) -> list[str]:
        urls = page.evaluate(_COLLECT_JS, {"selector": selector, "attrs": list(self.LAZY_ATTRS)})
        seen, out = set(), []
        for u in urls or []:
            if isinstance(u, str) and u not in seen:
                seen.add(u)
                out.append(u)
        return out

    def scroll_collect_images(self, page, selector: str, max_steps: int = 80) -> list[str]:
        """Rola a pagina ate a contagem de imagens estabilizar (lazy-load)."""
        stable, last_count, last_height, y = 0, -1, -1, 0
        for _ in range(max_steps):
            urls = self.collect_images(page, selector)
            height = int(page.evaluate(
                "() => Math.max(document.body.scrollHeight, document.documentElement.scrollHeight)"
            ) or 0)
            viewport = int(page.evaluate("() => window.innerHeight") or 900)
            at_bottom = y + viewport >= height
            if len(urls) == last_count and height == last_height and at_bottom:
                stable += 1
            else:
                stable = 0
            if stable >= 3:
                break
            last_count, last_height = len(urls), height
            y = min(y + max(300, int(viewport * 0.85)), height)
            page.evaluate("(yy) => window.scrollTo(0, yy)", y)
            page.wait_for_timeout(600)
        page.wait_for_timeout(500)
        return self.collect_images(page, selector)

    # --- download usando o contexto do browser (herda cookies do Cloudflare) #
    def download_to_temp(self, page_ref) -> Path:
        """Baixa a imagem via APIRequestContext do browser (passa pelo Cloudflare)."""
        import os
        import tempfile

        self._ensure_page()
        headers = {"User-Agent": USER_AGENT, **(page_ref.headers or {})}
        try:
            resp = self._ctx.request.get(page_ref.image_url, headers=headers, timeout=REQUEST_TIMEOUT * 1000)
            if not resp.ok:
                raise DownloadError(f"HTTP {resp.status} em {page_ref.image_url}")
            content = resp.body()
        except DownloadError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise DownloadError(f"GET falhou {page_ref.image_url}: {exc}") from exc
        if not content:
            raise DownloadError(f"Imagem vazia: {page_ref.image_url}")

        ext = self._guess_extension(page_ref.image_url, resp.headers.get("content-type"))
        TEMP_DIR.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(suffix=ext, dir=TEMP_DIR)
        with os.fdopen(fd, "wb") as fh:
            fh.write(content)
        return Path(name)
