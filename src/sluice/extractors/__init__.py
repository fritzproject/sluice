"""Registro degli estrattori.

Gli estrattori interni sono registrati qui. Quelli di terze parti si
aggiungono senza toccare questo file: basta che il pacchetto dichiari un
entry point nel gruppo ``sluice.extractors`` (vedi docs/writing-extractors.md),
e viene caricato all'avvio.
"""

from __future__ import annotations

import logging
from importlib.metadata import entry_points

from sluice.extractors.archive_org import ArchiveOrgExtractor
from sluice.extractors.base import Context, Extractor
from sluice.extractors.direct import DirectExtractor
from sluice.extractors.rss import RssExtractor

logger = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "sluice.extractors"

#: L'ordine conta: vince il primo che riconosce l'URL, e `direct` accetta
#: qualunque http(s), quindi resta per forza in fondo come ripiego.
_BUILTIN: list[type[Extractor]] = [ArchiveOrgExtractor, RssExtractor, DirectExtractor]
_registry: list[type[Extractor]] = []


def load_plugins() -> None:
    """Carica gli estrattori installati come pacchetti separati."""
    for entry in entry_points(group=ENTRY_POINT_GROUP):
        try:
            plugin = entry.load()
        except Exception:  # noqa: BLE001 - un plugin rotto non deve impedire l'avvio
            logger.exception("Estrattore '%s' non caricato", entry.name)
            continue
        if not (isinstance(plugin, type) and issubclass(plugin, Extractor)):
            logger.warning("Estrattore '%s' ignorato: non deriva da Extractor", entry.name)
            continue
        register(plugin)
        logger.info("Estrattore caricato: %s", plugin.name)


def register(extractor: type[Extractor]) -> None:
    """Aggiunge un estrattore, con priorita' sui predefiniti."""
    if extractor not in _registry:
        _registry.insert(0, extractor)


def available() -> list[type[Extractor]]:
    return [*_registry, *_BUILTIN]


def find(url: str) -> type[Extractor] | None:
    """Primo estrattore che dichiara di saper gestire l'URL."""
    for extractor in available():
        try:
            if extractor.matches(url):
                return extractor
        except Exception:  # noqa: BLE001 - matches() non deve poter rompere il resto
            logger.exception("matches() fallita in %s", extractor.name)
    return None


__all__ = ["Context", "Extractor", "available", "find", "load_plugins", "register"]
