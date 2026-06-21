"""Camada de banco de dados SQLite (`mangas.db`).

Tabela unica `pages`: cada linha = 1 pagina de 1 capitulo de 1 mangá, com a URL
publica da imagem no Hugging Face. Inclui `slugify()` para unificar o mesmo
mangá vindo de fontes diferentes (ex: "One Piece" / "one_piece" -> "one-piece").
"""

from __future__ import annotations

import re
import sqlite3
import unicodedata
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from config import DB_PATH

# DDL: chapter como TEXT preserva floats ("105.5") e nomes ("Extra", "Omake").
# UNIQUE evita duplicar a mesma pagina ao re-rodar o crawler (idempotente).
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS pages (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    manga_name   TEXT    NOT NULL,
    manga_slug   TEXT    NOT NULL,
    chapter      TEXT    NOT NULL,
    page_number  INTEGER NOT NULL,
    url_image    TEXT    NOT NULL,
    source       TEXT    NOT NULL,
    scraped_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (manga_slug, source, chapter, page_number)
);

CREATE INDEX IF NOT EXISTS idx_pages_slug    ON pages (manga_slug);
CREATE INDEX IF NOT EXISTS idx_pages_source  ON pages (source);
CREATE INDEX IF NOT EXISTS idx_pages_chapter ON pages (manga_slug, chapter);
"""


def slugify(value: str) -> str:
    """Padroniza nome -> slug: minusculo, sem acento, hifenizado.

    "One Piece!" -> "one-piece"
    "Tensei Shitara Slime" -> "tensei-shitara-slime"
    """
    text = str(value or "").strip()
    # remove acentos (NFKD -> descarta diacriticos)
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)  # tudo que nao for alfanumerico -> hifen
    return text.strip("-") or "desconhecido"


def normalize_chapter(value) -> str:
    """Padroniza o numero do capitulo entre fontes diferentes.

    Numerico  -> sem zero a esquerda e sem `.0` redundante, mantendo decimais:
        "01"     -> "1"
        "010.50" -> "10.5"
        "10.0"   -> "10"
        "1050.5" -> "1050.5"
    Nao-numerico (ex: "Extra", "Omake") -> preservado (trim).
    """
    s = str(value or "").strip()
    if not s:
        return "0"
    try:
        number = float(s)
    except ValueError:
        return s  # rotulo nao-numerico: mantem como veio
    if number.is_integer():
        return str(int(number))
    # str(float) ja da a forma mais curta em py3: 10.50 -> "10.5", 10.250 -> "10.25"
    return str(number)


@contextmanager
def get_connection(db_path: Path = DB_PATH) -> Iterator[sqlite3.Connection]:
    """Context manager: conexao com row_factory + commit/rollback automatico."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")   # melhor concorrencia leitura/escrita
    conn.execute("PRAGMA foreign_keys=ON;")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Path = DB_PATH) -> None:
    """Cria a tabela e os indices (idempotente)."""
    with get_connection(db_path) as conn:
        conn.executescript(SCHEMA_SQL)


def insert_page(
    conn: sqlite3.Connection,
    *,
    manga_name: str,
    chapter: str,
    page_number: int,
    url_image: str,
    source: str,
    manga_slug: str | None = None,
    scraped_at: str | None = None,
) -> bool:
    """Insere 1 pagina. Retorna True se inseriu, False se ja existia (UNIQUE).

    `manga_slug` e derivado de `manga_name` se nao informado.
    """
    slug = manga_slug or slugify(manga_name)
    chapter = normalize_chapter(chapter)
    ts = scraped_at or datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        """
        INSERT OR IGNORE INTO pages
            (manga_name, manga_slug, chapter, page_number, url_image, source, scraped_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (manga_name, slug, str(chapter), int(page_number), url_image, source, ts),
    )
    return cur.rowcount > 0


def page_exists(
    conn: sqlite3.Connection,
    *,
    manga_slug: str,
    source: str,
    chapter: str,
    page_number: int,
) -> bool:
    """Checa se a pagina ja foi catalogada (evita re-upload no Hugging Face)."""
    row = conn.execute(
        """
        SELECT 1 FROM pages
        WHERE manga_slug = ? AND source = ? AND chapter = ? AND page_number = ?
        LIMIT 1
        """,
        (manga_slug, source, normalize_chapter(chapter), int(page_number)),
    ).fetchone()
    return row is not None


if __name__ == "__main__":
    # Inicializa o banco e demonstra o slugify.
    init_db()
    print(f"Banco pronto em: {DB_PATH}")
    for sample in ["One Piece!", "Tensei Shitara Slime", "Solo Leveling: Ragnarök"]:
        print(f"  {sample!r:40} -> {slugify(sample)}")
