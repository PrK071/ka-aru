"""Registry de scrapers: mapeia nome -> classe, com AUTO-DESCOBERTA.

Qualquer modulo .py colocado nesta pasta (que registre uma subclasse de
BaseScraper com @register) e carregado automaticamente. Assim o nucleo publico
nao precisa citar nenhuma fonte: os scrapers concretos sao plugaveis e podem
ficar fora do versionamento.

Adicionar uma fonte:
    1. crie scrapers/<qualquer_nome>.py com subclasse de BaseScraper (ou de
       PlaywrightScraper, em browser_base, se precisar de navegador);
    2. decore a classe com @register. Pronto — o loader acha sozinho.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from typing import Type

from .base import BaseScraper, ChapterRef, MangaRef, PageRef  # re-export

logger = logging.getLogger(__name__)

_REGISTRY: dict[str, Type[BaseScraper]] = {}

# Modulos de infraestrutura (nao sao scrapers concretos).
_SKIP_MODULES = {"base", "browser_base"}


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


def _autodiscover() -> None:
    """Importa todos os modulos de scraper desta pasta (dispara os @register).

    Um import que falhe (ex: dependencia ausente) e logado, mas NAO derruba os
    demais. Nenhum nome de fonte fica hardcoded aqui.
    """
    for mod in pkgutil.iter_modules(__path__):
        if mod.name in _SKIP_MODULES or mod.name.startswith("_"):
            continue
        try:
            importlib.import_module(f"{__name__}.{mod.name}")
        except Exception as exc:  # noqa: BLE001
            logger.warning("scraper '%s' nao carregou: %s", mod.name, exc)


_autodiscover()

__all__ = [
    "BaseScraper", "MangaRef", "ChapterRef", "PageRef",
    "register", "get_scraper", "available",
]
