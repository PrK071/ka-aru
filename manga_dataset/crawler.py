"""Orquestrador principal.

Fluxo OBRIGATORIO por pagina (nunca acumula imagem no HD):
    1. download temporario  (scraper.download_to_temp)
    2. upload p/ Hugging Face (uploader.upload_image) -> URL publica
    3. grava metadados + URL no SQLite (database.insert_page)
    4. DELETA o arquivo temporario (finally)

Erros sao tratados POR PAGINA: uma falha de download/upload e logada e o loop
segue para a proxima pagina, sem derrubar a execucao inteira.

Uso:
    python crawler.py --mock                                 # demo do fluxo, sem rede/HF
    python crawler.py --source <Fonte> --dry-run --manga-url "<url>"  # valida sem subir
    python crawler.py --source <Fonte> --max-mangas 2 --max-chapters 3
    (use `--source` com um dos nomes listados por: python crawler.py)
"""

from __future__ import annotations

import argparse
import logging
import os
import tempfile
from pathlib import Path
from typing import Iterator

import config
from database import get_connection, init_db, page_exists, slugify
from scrapers import available, get_scraper
from scrapers.base import BaseScraper, ChapterRef, MangaRef, PageRef

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("crawler")


# --------------------------------------------------------------------------- #
# Modo MOCK: scraper + uploader falsos p/ demonstrar a logica sem tocar a rede.
# --------------------------------------------------------------------------- #
class MockScraper(BaseScraper):
    name = "MockSource"

    def iter_mangas(self) -> Iterator[MangaRef]:
        yield MangaRef(name="One Piece", url="https://exemplo/op")

    def iter_chapters(self, manga: MangaRef) -> Iterator[ChapterRef]:
        for ch in ("1050", "1050.5"):
            yield ChapterRef(manga=manga, chapter=ch, url=f"https://exemplo/op/{ch}")

    def iter_pages(self, chapter: ChapterRef) -> Iterator[PageRef]:
        for n in range(1, 4):
            yield PageRef(chapter=chapter, page_number=n, image_url=f"https://exemplo/img/{n}.jpg")

    def download_to_temp(self, page: PageRef) -> Path:
        # Simula o download gerando bytes ficticios num arquivo temporario.
        config.TEMP_DIR.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(suffix=".jpg", dir=config.TEMP_DIR)
        with os.fdopen(fd, "wb") as fh:
            fh.write(os.urandom(2048))  # "imagem" fake
        return Path(name)


class DryRunUploader:
    """Uploader falso: NAO envia ao Hugging Face. Valida o arquivo baixado
    (tamanho + assinatura de imagem) e devolve uma URL plausivel.
    """

    # Assinaturas (magic bytes) das imagens comuns.
    _MAGIC = (b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n", b"GIF87a", b"GIF89a", b"RIFF")

    def ensure_repo(self) -> None:
        logger.info("[dry-run] ensure_repo (no-op, sem HF)")

    @staticmethod
    def build_repo_path(*, manga_slug, source, chapter, page_number, extension) -> str:
        ext = extension if extension.startswith(".") else f".{extension}"
        return f"images/{manga_slug}/{slugify(source)}/ch-{slugify(str(chapter))}/p{int(page_number):03d}{ext}"

    def upload_image(self, local_path: Path, repo_path: str) -> str:
        size = local_path.stat().st_size
        with open(local_path, "rb") as fh:
            head = fh.read(12)
        looks_image = any(head.startswith(sig) for sig in self._MAGIC)
        flag = "img-ok" if looks_image else "SEM-assinatura-de-imagem"
        logger.info("[dry-run] %s bytes (%s) -> %s", f"{size:,}", flag, repo_path)
        return f"https://huggingface.co/datasets/EXEMPLO/mangas-dataset/resolve/main/{repo_path}"


# --------------------------------------------------------------------------- #
# Nucleo do fluxo
# --------------------------------------------------------------------------- #
def process_page(conn, uploader, scraper: BaseScraper, page: PageRef) -> str:
    """Executa o fluxo de UMA pagina. Retorna 'inserted' | 'skipped' | 'failed'."""
    chapter = page.chapter
    manga = chapter.manga
    slug = slugify(manga.name)

    # Idempotente: ja catalogado -> nao baixa nem sobe de novo.
    if page_exists(conn, manga_slug=slug, source=scraper.name,
                   chapter=chapter.chapter, page_number=page.page_number):
        logger.debug("skip (ja existe): %s ch%s p%d", slug, chapter.chapter, page.page_number)
        return "skipped"

    tmp_path: Path | None = None
    try:
        # 1) download temporario
        tmp_path = scraper.download_to_temp(page)

        # 2) upload -> URL publica
        repo_path = uploader.build_repo_path(
            manga_slug=slug,
            source=scraper.name,
            chapter=chapter.chapter,
            page_number=page.page_number,
            extension=tmp_path.suffix,
        )
        url = uploader.upload_image(tmp_path, repo_path)

        # 3) grava no banco
        from database import insert_page  # local p/ evitar custo no mock
        inserted = insert_page(
            conn,
            manga_name=manga.name,
            manga_slug=slug,
            chapter=chapter.chapter,
            page_number=page.page_number,
            url_image=url,
            source=scraper.name,
        )
        conn.commit()
        return "inserted" if inserted else "skipped"

    except Exception as exc:  # erro POR pagina: loga e segue
        logger.error("falha na pagina %s ch%s p%d: %s",
                     slug, chapter.chapter, page.page_number, exc)
        return "failed"

    finally:
        # 4) SEMPRE deleta o temporario (sucesso ou erro)
        if tmp_path is not None:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError as exc:
                logger.warning("nao consegui apagar temp %s: %s", tmp_path, exc)


def crawl(
    scraper: BaseScraper,
    uploader,
    *,
    manga_refs=None,
    max_mangas: int | None = None,
    max_chapters: int | None = None,
    max_pages: int | None = None,
) -> dict[str, int]:
    """Loop principal: mangas -> capitulos -> paginas.

    `manga_refs`: iteravel opcional de MangaRef p/ mirar obras especificas
    (ex: --manga-url). Se None, usa scraper.iter_mangas().
    """
    stats = {"inserted": 0, "skipped": 0, "failed": 0}
    uploader.ensure_repo()
    init_db()

    source_mangas = manga_refs if manga_refs is not None else scraper.iter_mangas()

    with get_connection() as conn:
        for m_i, manga in enumerate(source_mangas):
            if max_mangas is not None and m_i >= max_mangas:
                break
            logger.info("MANGA: %s", manga.name)
            try:
                chapters = list(scraper.iter_chapters(manga))
            except Exception as exc:
                logger.error("falha listando capitulos de %s: %s", manga.name, exc)
                continue

            for c_i, chapter in enumerate(chapters):
                if max_chapters is not None and c_i >= max_chapters:
                    break
                logger.info("  CAP %s", chapter.chapter)
                try:
                    pages = list(scraper.iter_pages(chapter))
                except Exception as exc:
                    logger.error("falha listando paginas %s ch%s: %s",
                                 manga.name, chapter.chapter, exc)
                    continue

                for p_i, page in enumerate(pages):
                    if max_pages is not None and p_i >= max_pages:
                        break
                    result = process_page(conn, uploader, scraper, page)
                    stats[result] += 1

    logger.info("FIM: %s", stats)
    return stats


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Crawler de mangás -> Hugging Face -> SQLite.")
    p.add_argument("--source", default=None, help=f"Fonte registrada. Opcoes: {available()}")
    p.add_argument("--mock", action="store_true",
                   help="Demo 100%% offline (scraper e upload falsos).")
    p.add_argument("--dry-run", action="store_true",
                   help="Scraper REAL (baixa de verdade) + SQLite real, mas SEM subir no Hugging Face. "
                        "Valida raspagem+insercao antes de estressar a API.")
    p.add_argument("--manga-url", default=None,
                   help="Raspa apenas esta obra (pula iter_mangas). Util p/ teste focado.")
    p.add_argument("--max-mangas", type=int, default=None)
    p.add_argument("--max-chapters", type=int, default=None)
    p.add_argument("--max-pages", type=int, default=None)
    return p


def _manga_refs_from_args(args):
    """Se --manga-url, devolve [MangaRef] mirando 1 obra; senao None."""
    if not args.manga_url:
        return None
    name = args.manga_url.rstrip("/").split("/")[-1] or args.manga_url
    return [MangaRef(name=name, url=args.manga_url)]


def main() -> int:
    args = build_parser().parse_args()
    config.ensure_dirs()
    limits = dict(max_mangas=args.max_mangas, max_chapters=args.max_chapters, max_pages=args.max_pages)

    # 1) MOCK: tudo falso, sem rede.
    if args.mock:
        logger.info(">> MODO MOCK (offline, scraper e upload falsos)")
        crawl(MockScraper(), DryRunUploader(), **limits)
        return 0

    if not args.source:
        print("Informe --source <Fonte> (ou --mock). Fontes:", available())
        return 2

    scraper = get_scraper(args.source)
    manga_refs = _manga_refs_from_args(args)

    # 2) DRY-RUN: scraper real + SQLite real, upload FALSO (sem HF).
    if args.dry_run:
        logger.info(">> MODO DRY-RUN (scraper real, SEM upload no Hugging Face)")
        crawl(scraper, DryRunUploader(), manga_refs=manga_refs, **limits)
        return 0

    # 3) REAL: sobe no Hugging Face (exige huggingface_hub + HF_TOKEN).
    from uploader import HuggingFaceUploader  # import tardio
    crawl(scraper, HuggingFaceUploader(), manga_refs=manga_refs, **limits)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
