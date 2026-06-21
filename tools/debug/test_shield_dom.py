"""Valida as BRECHAS do shield real p/ extrair as <img> do leitor.

Hipoteses (contra o shield real, sem tocar no sakura):
  1. querySelectorAll('#pges_51dwq1 img') -> 0 (shield filtra).
  2. getElementById('pges_51dwq1').getElementsByTagName('img') -> count real (NAO filtrado).
  3. img.src / img.currentSrc -> URL real (nao mascarado neste shield).
  4. fetch() ainda EXECUTA (so foi travado p/ reconfig), permitindo ler blob:.
"""

from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright


def _launch(pw):
    for opts in ({"headless": True}, {"headless": True, "channel": "chrome"},
                 {"headless": True, "channel": "msedge"}, {"headless": False}):
        try:
            return pw.chromium.launch(**opts)
        except Exception:
            continue
    raise RuntimeError("Nenhum chromium abriu.")


def main() -> int:
    shield = (ROOT / "tools" / "debug" / "fixtures" / "sakura_shield.js").read_text(encoding="utf-8")

    # Leitor sintetico: #pges_51dwq1 com 3 imgs http + 1 blob, montado ANTES do shield
    # (no real, o shield e o 1o script; imgs entram via AJAX depois, mas p/ testar a
    # visibilidade das brechas basta te-las no DOM quando o shield ja rodou).
    page_html = f"""<!DOCTYPE html><html><head>
<script data-cfasync="false">{shield}</script>
</head><body>
<div id="pges_51dwq1">
  <img id="p1" src="https://example.com/page-001.webp">
  <img id="p2" src="https://example.com/page-002.webp">
  <img id="p3" src="https://example.com/page-003.webp">
</div>
<script>
  window.__r = {{}};
  try {{ window.__r.qsa = document.querySelectorAll('#pges_51dwq1 img').length; }} catch(e) {{ window.__r.qsa = 'ERR:'+e; }}
  try {{
    const box = document.getElementById('pges_51dwq1');
    const imgs = box.getElementsByTagName('img');
    window.__r.gebtn = imgs.length;
    window.__r.srcs = Array.from(imgs).map(i => i.getAttribute('src') || i.src);
  }} catch(e) {{ window.__r.gebtn = 'ERR:'+e; }}
  try {{ window.__r.children = document.getElementById('pges_51dwq1').children.length; }} catch(e) {{ window.__r.children = 'ERR:'+e; }}
  try {{ window.__r.fetchType = typeof window.fetch; }} catch(e) {{ window.__r.fetchType = 'ERR'; }}
</script>
</body></html>"""

    tmp = Path(tempfile.mkdtemp())
    f = tmp / "reader.html"
    f.write_text(page_html, encoding="utf-8")

    with sync_playwright() as pw:
        browser = _launch(pw)
        page = browser.new_context().new_page()
        page.goto(f.as_uri(), wait_until="load")
        r = page.evaluate("() => window.__r")
        browser.close()

    print("querySelectorAll('#pges img') :", r.get("qsa"), "(esperado 0 = filtrado)")
    print("getElementsByTagName('img')   :", r.get("gebtn"), "(esperado 3 = brecha)")
    print(".children.length              :", r.get("children"), "(esperado 3 = brecha)")
    print("img srcs lidos                :", r.get("srcs"))
    print("typeof fetch                  :", r.get("fetchType"), "(esperado 'function')")

    ok = (r.get("qsa") == 0 and r.get("gebtn") == 3 and r.get("children") == 3
          and isinstance(r.get("srcs"), list) and len(r.get("srcs")) == 3
          and all("page-00" in s for s in r.get("srcs"))
          and r.get("fetchType") == "function")
    print("\n" + ("OK: brechas confirmadas (getElementsByTagName + .src + fetch vivos)."
                  if ok else "FALHA: alguma brecha nao confirmada."))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
