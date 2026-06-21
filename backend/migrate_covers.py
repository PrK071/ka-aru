"""Migracao de capas: baixa TODAS as capas remotas do catalogo para
static/covers/ e atualiza o caminho local (cover_path) no snapshot.

O "banco" do MangaTemp e o snapshot do catalogo (backend/.cache/catalog.json) +
os catalogos em .reader_home_cache. Este script varre esses arquivos, baixa as
capas que ainda apontam para URLs externas (via /api/image proxy ou
cover_original_url) e grava cover_path -> /static/covers/<manga_id>.<ext>.

Idempotente: capas ja baixadas sao reaproveitadas (sem novo download).

Uso:
    python -m backend.migrate_covers
    python backend/migrate_covers.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Permite rodar como `python backend/migrate_covers.py` (sem -m).
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend import main as app  # reusa helpers, paths e config


def _collect_items(data: dict) -> list[dict]:
    """Itens unicos de items[] + sections[].items[] (por identidade de objeto)."""
    seen: set[int] = set()
    bucket: list[dict] = []
    collections = [data.get("items") or []]
    for section in data.get("sections") or []:
        if isinstance(section, dict):
            collections.append(section.get("items") or [])
    for collection in collections:
        for item in collection:
            if isinstance(item, dict) and id(item) not in seen:
                seen.add(id(item))
                bucket.append(item)
    return bucket


def _has_remote_cover(item: dict) -> bool:
    src = str(item.get("cover_original_url") or "").strip() or app._unproxy_image_url(item.get("cover_url") or "")
    return app._is_remote_image_url(src)


def migrate_file(path: Path) -> tuple[int, int]:
    """Migra um arquivo de catalogo. Retorna (baixadas, total_com_capa_remota)."""
    if not path.exists():
        return (0, 0)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"  ! ignorando {path.name}: JSON invalido ({exc})")
        return (0, 0)
    if not isinstance(data, dict):
        return (0, 0)

    items = _collect_items(data)
    alvo = [it for it in items if _has_remote_cover(it)]
    pendentes = [it for it in items if not it.get("cover_path") and _has_remote_cover(it)]
    print(f"  {path.name}: {len(items)} itens | {len(pendentes)} sem capa local -> baixando...")

    # 1) baixa em paralelo (idempotente) e seta cover_path
    if alvo:
        app._download_covers_to_disk(alvo, limit=10_000)

    # 2) verificacao: garante ARQUIVO FISICO.
    #    original -> fonte alternativa (MangaDex/AniList por titulo) -> placeholder.
    app._ensure_placeholder()
    ok = recovered = placeholders = 0
    for it in items:
        cp = it.get("cover_path") or ""
        if app._cover_file_exists(cp):
            ok += 1
            continue
        # (a) tenta (re)baixar a capa ORIGINAL
        it.pop("cover_path", None)
        app._store_cover_local(it)
        if app._cover_file_exists(it.get("cover_path") or ""):
            ok += 1
            continue
        # (b) FONTE ALTERNATIVA por titulo
        if app._recover_and_store_cover(it):
            recovered += 1
            continue
        # (c) desistiu -> placeholder "Sem Capa"
        it["cover_path"] = app.PLACEHOLDER_URL
        placeholders += 1

    try:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        print(f"  ! falha ao gravar {path.name}: {exc}")
    print(f"  -> {ok} ja-local | {recovered} recuperadas (fonte alt) | {placeholders} placeholder")
    return (ok + recovered, placeholders)


def main() -> int:
    app.COVERS_DIR.mkdir(parents=True, exist_ok=True)

    # "Banco" da home = snapshot do catalogo do MangaTemp (nosso schema).
    # Os caches em .reader_home_cache sao do reader_server (outro schema) e nao
    # alimentam a home -> nao mexemos neles.
    candidatos = [p for p in (app.CATALOG_SNAPSHOT_PATH,) if p.exists()]
    if not candidatos:
        print("Nenhum snapshot de catalogo encontrado. Rode o backend uma vez "
              "(GET /api/mangas) para gerar, depois rode a migracao.")
        return 1

    total_ok = total_ph = 0
    for path in candidatos:
        ok, placeholders = migrate_file(path)
        total_ok += ok
        total_ph += placeholders

    print(f"\nOK: {total_ok} capas locais | {total_ph} sem capa -> placeholder. "
          f"Estaticos em {app.STATIC_DIR}")
    print("Reinicie o backend (uvicorn) para a home servir as capas estaticas.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
