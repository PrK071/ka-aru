"""Upload de imagens para um dataset publico no Hugging Face (Git LFS).

A `huggingface_hub.HfApi.upload_file` envia o binario e o Git LFS do dataset
versiona automaticamente. A URL publica direta segue o padrao:

    https://huggingface.co/datasets/{repo}/resolve/{revision}/{path_no_repo}

Pre-requisitos:
    pip install huggingface_hub
    HF_TOKEN com permissao de escrita (ver config.py)
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from huggingface_hub import HfApi
from huggingface_hub.utils import HfHubHTTPError

from config import (
    HF_DATASET_REPO,
    HF_REVISION,
    HF_TOKEN,
    MAX_RETRIES,
    RETRY_BACKOFF,
)
from database import slugify

logger = logging.getLogger(__name__)


class UploadError(RuntimeError):
    """Falha definitiva de upload (apos esgotar os retries)."""


class HuggingFaceUploader:
    """Cliente fino sobre HfApi para subir imagens e devolver a URL publica."""

    def __init__(
        self,
        repo_id: str = HF_DATASET_REPO,
        token: str | None = HF_TOKEN,
        revision: str = HF_REVISION,
    ) -> None:
        if not token:
            raise UploadError("HF_TOKEN ausente. Defina a variavel de ambiente.")
        self.repo_id = repo_id
        self.revision = revision
        self.api = HfApi(token=token)

    def ensure_repo(self) -> None:
        """Cria o dataset publico se ainda nao existir (idempotente)."""
        self.api.create_repo(
            repo_id=self.repo_id,
            repo_type="dataset",
            private=False,
            exist_ok=True,
        )

    @staticmethod
    def build_repo_path(
        *, manga_slug: str, source: str, chapter: str, page_number: int, extension: str
    ) -> str:
        """Caminho organizado dentro do dataset.

        Ex: images/<slug>/<fonte>/ch-1050.5/p003.jpg
        """
        ext = extension if extension.startswith(".") else f".{extension}"
        safe_chapter = slugify(str(chapter)) or "0"
        return (
            f"images/{manga_slug}/{slugify(source)}/"
            f"ch-{safe_chapter}/p{int(page_number):03d}{ext}"
        )

    def public_url(self, repo_path: str) -> str:
        """Monta a URL direta de download (resolve)."""
        return (
            f"https://huggingface.co/datasets/{self.repo_id}"
            f"/resolve/{self.revision}/{repo_path}"
        )

    def upload_image(self, local_path: Path, repo_path: str) -> str:
        """Sobe `local_path` para `repo_path` no dataset. Retorna a URL publica.

        Reententa com backoff exponencial em erros transitorios de rede/HTTP.
        Levanta UploadError se todas as tentativas falharem.
        """
        local_path = Path(local_path)
        if not local_path.is_file():
            raise UploadError(f"Arquivo local inexistente: {local_path}")

        last_exc: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                self.api.upload_file(
                    path_or_fileobj=str(local_path),
                    path_in_repo=repo_path,
                    repo_id=self.repo_id,
                    repo_type="dataset",
                    revision=self.revision,
                    commit_message=f"add {repo_path}",
                )
                url = self.public_url(repo_path)
                logger.info("upload OK: %s", url)
                return url
            except (HfHubHTTPError, OSError, ConnectionError) as exc:
                last_exc = exc
                wait = RETRY_BACKOFF ** attempt
                logger.warning(
                    "upload falhou (tentativa %d/%d): %s -> retry em %.1fs",
                    attempt, MAX_RETRIES, exc, wait,
                )
                time.sleep(wait)

        raise UploadError(f"Upload falhou apos {MAX_RETRIES} tentativas: {last_exc}")
