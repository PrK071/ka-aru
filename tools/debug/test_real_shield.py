"""Testa o bypass canvas-DRM contra o SHIELD REAL do sakuramangas.

Extrai o 1o <script data-cfasync> do HTML ja salvo
(.tmp-sakura-test/1/pagina.html), monta uma pagina local com esse shield real +
um canvas desenhado, e prova que o CANVAS_DRM_BYPASS_JS le os pixels reais.

Nao toca no sakura (so usa o HTML em disco). Roda headless.
"""

from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
for p in (str(ROOT), str(TOOLS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from playwright.sync_api import sync_playwright

import sakura_requisitor as sr

SAVED_HTML_CANDIDATES = [
    ROOT / ".tmp-sakura-test" / "1" / "pagina.html",
    ROOT / "downloads" / "sakura" / "1" / "pagina.html",
]


def extract_shield_js(html: str) -> str | None:
    """Pega o conteudo do 1o <script ...>...</script> (o shield data-cfasync)."""
    m = re.search(r"<script\b[^>]*>(.*?)</script>", html, re.IGNORECASE | re.DOTALL)
    if not m:
        return None
    js = m.group(1).strip()
    # Sanidade: o shield real define "data:," como retorno falso.
    return js if "data:," in js else js


def _launch(pw):
    for opts in ({"headless": True}, {"headless": True, "channel": "chrome"},
                 {"headless": True, "channel": "msedge"}, {"headless": False}):
        try:
            return pw.chromium.launch(**opts)
        except Exception:
            continue
    raise RuntimeError("Nenhum chromium abriu.")


def build_page_html(shield_js: str) -> str:
    return f"""<!DOCTYPE html><html lang="pt-br"><head>
<script data-cfasync="false">{shield_js}</script>
</head><body>
<div id="pges_51dwq1">
  <canvas id="c" width="500" height="700"></canvas>
</div>
<script>
  try {{
    const cv = document.getElementById('c');
    const ctx = cv.getContext('2d');
    if (ctx) {{
      for (let k = 0; k < 900; k++) {{
        ctx.fillStyle = 'rgb(' + (Math.random()*255|0) + ',' + (Math.random()*255|0) + ',' + (Math.random()*255|0) + ')';
        ctx.fillRect(Math.random()*500, Math.random()*700, Math.random()*70+5, Math.random()*70+5);
      }}
      window.__ctxOk = true;
    }} else {{
      window.__ctxOk = false;
    }}
  }} catch (e) {{ window.__ctxErr = String(e); }}
  window.__drawn = true;
</script>
</body></html>"""


def main() -> int:
    html_file = next((p for p in SAVED_HTML_CANDIDATES if p.exists()), None)
    if not html_file:
        print("FALHA: nenhum pagina.html salvo encontrado p/ extrair o shield real.")
        return 2
    shield_js = extract_shield_js(html_file.read_text(encoding="utf-8", errors="ignore"))
    if not shield_js:
        print("FALHA: nao consegui extrair o shield do HTML salvo.")
        return 2
    print(f">> Shield real extraido de {html_file} ({len(shield_js)} chars).")

    tmpdir = Path(tempfile.mkdtemp())
    page_html = build_page_html(shield_js)
    html_path = tmpdir / "real_shield.html"
    html_path.write_text(page_html, encoding="utf-8")
    url = html_path.as_uri()

    failures = []
    with sync_playwright() as pw:
        browser = _launch(pw)

        # Controle: sem bypass -> shield real deve poisonar.
        ctrl = browser.new_context().new_page()
        ctrl.goto(url, wait_until="load")
        ctrl_val = ctrl.evaluate("() => document.getElementById('c').toDataURL('image/png')")
        ctx_ok = ctrl.evaluate("() => window.__ctxOk")
        print(f"[controle] ctxOk={ctx_ok}  toDataURL={ctrl_val[:24]!r}")

        # Bypass.
        page = browser.new_context().new_page()
        page.add_init_script(sr.CANVAS_DRM_BYPASS_JS)
        page.goto(url, wait_until="load")
        bp_ctx_ok = page.evaluate("() => window.__ctxOk")
        proto_val = page.evaluate("() => document.getElementById('c').toDataURL('image/png')")
        dumps = page.evaluate("() => window.__cvDump ? window.__cvDump() : null")
        print(f"[bypass]   ctxOk={bp_ctx_ok}  protoToDataURL={proto_val[:18]!r}  dumps={len(dumps or [])}")

        if not bp_ctx_ok:
            failures.append("bypass: getContext('2d') falhou (shield quebra o contexto?)")
        if not dumps:
            failures.append("bypass: __cvDump nao retornou pixels reais contra o shield real")
        else:
            manifest = sr.extract_canvas_pages(page, tmpdir)
            print(f"[bypass]   extract_canvas_pages -> {len(manifest)} arquivo(s); "
                  f"bytes={manifest[0]['bytes'] if manifest else 0}")
            if not manifest:
                failures.append("bypass: extract_canvas_pages nao salvou nada")

        browser.close()

    if failures:
        print("\nFALHAS:")
        for f in failures:
            print(" -", f)
        return 1
    print("\nOK: bypass vence o SHIELD REAL do sakura (le pixels do canvas).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
