"""Prova o caminho PRIMARIO (READER_READ_JS) contra o shield REAL.

Monta #pges_51dwq1 com uma img data: e uma img blob: e verifica que
sr.READER_READ_JS (getElementsByTagName + fetch in-page + FileReader) devolve
os bytes em base64 mesmo com o shield ativo (querySelector filtrado, scroll/
canvas mortos).
"""

from __future__ import annotations

import base64
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright

import sakura_requisitor as sr

# PNG 2x2 valido (base64).
PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAAEUlEQVR4nGNk"
    "+M+ADzCOKgAAJYwD/p2k0qoAAAAASUVORK5CYII="
)


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
    data_url = "data:image/png;base64," + PNG_B64

    page_html = f"""<!DOCTYPE html><html><head>
<script data-cfasync="false">{shield}</script>
</head><body>
<div id="pges_51dwq1"></div>
<script>
  // Monta as imgs do leitor APOS o shield (como o AJAX real faria).
  const box = document.getElementById('pges_51dwq1');
  const d = document.createElement('img'); d.src = "{data_url}"; box.appendChild(d);
  // blob: a partir dos mesmos bytes
  const bin = atob("{PNG_B64}");
  const arr = new Uint8Array(bin.length);
  for (let i=0;i<bin.length;i++) arr[i]=bin.charCodeAt(i);
  const blobUrl = URL.createObjectURL(new Blob([arr], {{type:'image/png'}}));
  const b = document.createElement('img'); b.src = blobUrl; box.appendChild(b);
  window.__ready = true;
</script>
</body></html>"""

    tmp = Path(tempfile.mkdtemp())
    f = tmp / "reader.html"
    f.write_text(page_html, encoding="utf-8")

    with sync_playwright() as pw:
        browser = _launch(pw)
        page = browser.new_context().new_page()
        page.goto(f.as_uri(), wait_until="load")
        page.wait_for_function("() => window.__ready === true", timeout=5000)
        items = page.evaluate(sr.READER_READ_JS) or []
        browser.close()

    print(f"items lidos: {len(items)} (esperado 2)")
    failures = []
    if len(items) != 2:
        failures.append(f"esperado 2 imgs via getElementsByTagName, veio {len(items)}")
    for it in items:
        src = (it.get("src") or "")[:24]
        du = it.get("dataUrl")
        ok = bool(du and du.startswith("data:image/png") and "," in du)
        decoded = 0
        if ok:
            try:
                decoded = len(base64.b64decode(du.split(",", 1)[1], validate=True))
            except Exception:
                ok = False
        print(f"  idx={it.get('index')} src={src!r}... dataUrl_ok={ok} bytes={decoded}")
        if not ok:
            failures.append(f"img idx={it.get('index')} sem dataUrl real (fetch in-page falhou sob shield)")

    print("\n" + ("OK: READER_READ_JS extrai bytes (data:+blob:) sob o shield real."
                  if not failures else "FALHA:\n - " + "\n - ".join(failures)))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
