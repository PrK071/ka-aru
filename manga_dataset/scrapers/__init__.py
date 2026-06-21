"""Registry de scrapers: mapeia nome -> classe.

Para adicionar um site novo:
    1. crie scrapers/meusite.py com uma subclasse de BaseScraper.
    2. registre com @register abaixo (ou no proprio arquivo).
"""

from __future__ import annotations

from typing import Type

from .base import BaseScraper, ChapterRef, MangaRef, PageRef  # re-export

_REGISTRY: dict[str, Type[BaseScraper]] = {}


def register(cls: Type[BaseScraper]) -> Type[BaseScraper]:
    """Decorator de classe que registra o scraper pelo seu `name`."""
    key = cls.name.lower()
    if key in _REGISTRY:
        raise ValueError(f"Scraper duplicado: {cls.name}")
    _REGISTRY[key] = cls
    return cls


def get_scraper(name: str) -> BaseScraper:
    """Instancia o scraper pelo nome (case-insensitive)."""
    cls = _REGISTRY.get(name.lower())
    if cls is None:
        raise KeyError(f"Scraper '{name}' nao registrado. Disponiveis: {available()}")
    return cls()


def available() -> list[str]:
    return sorted(cls.name for cls in _REGISTRY.values())


# Importa os modulos concretos p/ disparar os @register.
# Adicione aqui conforme implementar cada fonte.
import logging as _logging

# Importa os scrapers concretos p/ disparar os @register. Um import que falhe
# (ex: dependencia ausente) e logado mas NAO derruba o registry inteiro.
for _mod in ("mangadex", "mangakatana", "mangasbrasuka", "mangalivre", "toomics", "dragontea"):
    try:
        __import__(f"{__name__}.{_mod}", fromlist=[_mod])
    except Exception as _exc:  # noqa: BLE001
        _logging.getLogger(__name__).warning("scraper '%s' nao carregou: %s", _mod, _exc)

# Placeholders a implementar (mesma estrutura do mangadex.py / mangakatana.py):
#   mangalivre, mangasbrasuka, toomics, onepieceproject, dragontea, readfull, noveltoon

__all__ = [
    "BaseScraper",
    "MangaRef",
    "ChapterRef",
    "PageRef",
    "register",
    "get_scraper",
    "available",
]
