"""Teste local do provider Sakura; nao acessa sakuramangas.org."""

from __future__ import annotations

import base64
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright

from reader_server import (
    MangaReader,
    SAKURA_BLOB_PROBE_JS,
    SAKURA_EXTRACT_BLOB_JS,
    SAKURA_READER_SELECTOR,
)


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def reader_stub() -> MangaReader:
    reader = object.__new__(MangaReader)
    reader.sakura_base_url = "https://sakuramangas.org"
    return reader


def test_urls(reader: MangaReader) -> None:
    assert reader._sakura_source_parts(
        "https://sakuramangas.org/obras/usamimi-jackpot"
    ) == ("usamimi-jackpot", None)
    assert reader._sakura_chapter_parts(
        "https://sakuramangas.org/obras/usamimi-jackpot/5-5/"
    ) == ("usamimi-jackpot", "5-5")
    assert reader._sakura_chapter_number_from_source(
        "https://sakuramangas.org/obras/usamimi-jackpot/5-5/"
    ) == "5.5"


def test_manga_parser(reader: MangaReader) -> None:
    raw = {
        "title": "Usamimi Jackpot",
        "description": "Sinopse",
        "poster": "/obras/usamimi-jackpot/thumb_256.jpg",
        "authors": ["Hotondoha Ashura"],
        "genres": ["Romance"],
        "status": "Em andamento",
        "chapters": [
            {"id": "8", "url": "/obras/usamimi-jackpot/8", "label": "Cap. 8", "title": "Oito"},
            {"id": "55", "url": "/obras/usamimi-jackpot/5-5", "label": "Cap. 5.5", "title": "Extra"},
            {"id": "1", "url": "/obras/usamimi-jackpot/1-v1", "label": "Cap. 1", "title": "Um"},
        ],
    }
    reader._sakura_run_page = lambda *_args, **_kwargs: raw
    manga, chapters = reader._sakura_scrape_manga(
        "https://sakuramangas.org/obras/usamimi-jackpot"
    )
    assert manga["title"] == "Usamimi Jackpot"
    assert manga["latest_chapter"] == "8"
    assert [chapter.number_text for chapter in chapters] == ["1", "5.5", "8"]


def test_blob_extract(reader: MangaReader) -> None:
    encoded = base64.b64encode(PNG_1X1).decode("ascii")
    html = f"""<!doctype html><html><body><div class='pag-item'></div>
    <script>
      const bytes = Uint8Array.from(atob('{encoded}'), c => c.charCodeAt(0));
      const blob = new Blob([bytes], {{ type: 'image/png' }});
      const img = document.createElement('img');
      img.src = URL.createObjectURL(blob);
      document.querySelector('.pag-item').appendChild(img);
    </script></body></html>"""
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        page_path = root / "provider.html"
        page_path.write_text(html, encoding="utf-8")
        target = root / "pages"
        target.mkdir()
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.add_init_script(SAKURA_BLOB_PROBE_JS)
            page.goto(page_path.as_uri())
            page.wait_for_selector(SAKURA_READER_SELECTOR)
            probe = page.evaluate(
                SAKURA_EXTRACT_BLOB_JS,
                {"selector": SAKURA_READER_SELECTOR, "index": 0},
            )
            assert str(probe["dataUrl"]).startswith("data:image/png;base64,")
            urls, cache = reader._sakura_extract_pages(page, SAKURA_READER_SELECTOR, target)
            browser.close()
        assert len(urls) == 1
        assert cache[1].path.read_bytes() == PNG_1X1
        assert cache[1].content_type == "image/png"


def main() -> int:
    reader = reader_stub()
    test_urls(reader)
    test_manga_parser(reader)
    test_blob_extract(reader)
    print("OK: provider Sakura parseia obra/capitulos e extrai Blob para cache.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
