"""Teste local do bypass canvas-DRM (sem tocar no sakuramangas).

Emula o shield real (poisona HTMLCanvasElement.prototype.toDataURL -> "data:,"
via Object.defineProperty configurable:false dentro de try/catch) e prova que,
com CANVAS_DRM_BYPASS_JS injetado ANTES, os pixels reais ainda sao lidos.

Roda headless. Uso: python tools/debug/test_canvas_bypass.py
"""

from __future__ import annotations

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

# Shield sintetico: imita o "i(e,t,r)" + toDataURL fake do sakura.
SYNTH_SHIELD = r"""
(function () {
  "use strict";
  try {
    const fake = () => "data:,";
    const i = (e, t, r) => {
      try {
        const o = { configurable: false, writable: false, enumerable: false };
        if (r !== undefined) o.value = r;
        else {
          const d = Object.getOwnPropertyDescriptor(e, t);
          if (!d || !d.configurable) return;
        }
        Object.defineProperty(e, t, o);
      } catch (e) {}
    };
    i(HTMLCanvasElement.prototype, "toDataURL", fake);
    window.__shieldRan = true;
  } catch (e) {}
})();
"""

PAGE_HTML = """
<!DOCTYPE html><html><head><script>%s</script></head>
<body>
<canvas id="c" width="400" height="400"></canvas>
<script>
  const cv = document.getElementById('c');
  const ctx = cv.getContext('2d');
  for (let k = 0; k < 600; k++) {
    ctx.fillStyle = 'rgb(' + (Math.random()*255|0) + ',' + (Math.random()*255|0) + ',' + (Math.random()*255|0) + ')';
    ctx.fillRect(Math.random()*400, Math.random()*400, Math.random()*60+5, Math.random()*60+5);
  }
  window.__drawn = true;
</script>
</body></html>
""" % SYNTH_SHIELD


def _launch(pw):
    attempts = [
        {"headless": True},
        {"headless": True, "channel": "chrome"},
        {"headless": True, "channel": "msedge"},
        {"headless": False},
    ]
    errors = []
    for opts in attempts:
        try:
            return pw.chromium.launch(**opts)
        except Exception as exc:
            errors.append(f"{opts}: {str(exc).splitlines()[0]}")
    raise RuntimeError("Nenhum chromium abriu:\n  " + "\n  ".join(errors))


def main() -> int:
    failures = []
    tmpdir = Path(tempfile.mkdtemp())
    html_path = tmpdir / "shield_page.html"
    html_path.write_text(PAGE_HTML, encoding="utf-8")
    file_url = html_path.as_uri()

    with sync_playwright() as pw:
        browser = _launch(pw)

        # --- Controle: SEM bypass -> shield deve poisonar toDataURL.
        ctrl = browser.new_context().new_page()
        ctrl.goto(file_url, wait_until="load")
        ctrl_shield = ctrl.evaluate("() => window.__shieldRan === true")
        ctrl_val = ctrl.evaluate("() => document.getElementById('c').toDataURL('image/png')")
        print(f"[controle] shield rodou={ctrl_shield}  toDataURL={ctrl_val[:24]!r}")
        if ctrl_val != "data:,":
            failures.append("controle: shield NAO poisonou (toDataURL deveria ser 'data:,')")

        # --- Bypass: COM CANVAS_DRM_BYPASS_JS injetado antes do shield.
        ctx = browser.new_context()
        page = ctx.new_page()
        page.add_init_script(sr.CANVAS_DRM_BYPASS_JS)
        page.goto(file_url, wait_until="load")

        shield_ran = page.evaluate("() => window.__shieldRan === true")
        drm_ran = page.evaluate("() => window.__cvDrm === true")
        real_type = page.evaluate("() => typeof window.__cvRealToDataURL")
        proto_val = page.evaluate("() => document.getElementById('c').toDataURL('image/png')")
        dumps = page.evaluate("() => window.__cvDump ? window.__cvDump() : null")

        print(f"[bypass]   shield={shield_ran} drm={drm_ran} realToDataURL={real_type} "
              f"protoToDataURL={proto_val[:18]!r} dumps={len(dumps or [])}")

        if not shield_ran:
            failures.append("bypass: shield nem rodou (teste invalido)")
        if not dumps:
            failures.append("bypass: __cvDump nao retornou pixels reais")
        else:
            d0 = dumps[0]
            if not str(d0.get("dataUrl", "")).startswith("data:image/png"):
                failures.append("bypass: __cvDump dataUrl nao e PNG real")
            manifest = sr.extract_canvas_pages(page, tmpdir)
            print(f"[bypass]   extract_canvas_pages -> {len(manifest)} arquivo(s); "
                  f"bytes={manifest[0]['bytes'] if manifest else 0}")
            if not manifest:
                failures.append("bypass: extract_canvas_pages nao salvou nada (>6KB?)")

        browser.close()

    if failures:
        print("\nFALHAS:")
        for f in failures:
            print(" -", f)
        return 1
    print("\nOK: bypass le pixels reais mesmo com o shield ativo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
