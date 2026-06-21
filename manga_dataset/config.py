"""Configuracao central do projeto (via variaveis de ambiente).

Nunca hardcode o token do Hugging Face. Defina no ambiente:

    setx HF_TOKEN "hf_xxx"                # Windows (reabra o terminal)
    export HF_TOKEN="hf_xxx"             # Linux/Mac

Ou crie um arquivo .env e carregue com python-dotenv (opcional).
"""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT: Path = Path(__file__).resolve().parent

# Carrega .env automaticamente se python-dotenv estiver instalado (opcional).
try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except Exception:
    pass

# --- Hugging Face -----------------------------------------------------------
# Token de escrita (Settings -> Access Tokens -> role "write").
HF_TOKEN: str | None = os.environ.get("HF_TOKEN")

# Repositorio de dataset publico, no formato "usuario/nome-do-dataset".
HF_DATASET_REPO: str = os.environ.get("HF_DATASET_REPO", "seu-usuario/mangas-dataset")

# Branch do dataset (Git LFS guarda os binarios automaticamente).
HF_REVISION: str = os.environ.get("HF_REVISION", "main")

# --- Armazenamento local ----------------------------------------------------
# Banco SQLite unico (sera publicado no GitHub).
DB_PATH: Path = Path(os.environ.get("MANGA_DB_PATH", PROJECT_ROOT / "mangas.db"))

# Pasta de arquivos TEMPORARIOS (cada imagem e apagada apos o upload).
TEMP_DIR: Path = Path(os.environ.get("MANGA_TEMP_DIR", PROJECT_ROOT / ".tmp_images"))

# --- Rede -------------------------------------------------------------------
REQUEST_TIMEOUT: int = int(os.environ.get("MANGA_REQUEST_TIMEOUT", "30"))
MAX_RETRIES: int = int(os.environ.get("MANGA_MAX_RETRIES", "3"))
RETRY_BACKOFF: float = float(os.environ.get("MANGA_RETRY_BACKOFF", "2.0"))

USER_AGENT: str = os.environ.get(
    "MANGA_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
)


def ensure_dirs() -> None:
    """Garante que as pastas locais existem."""
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
