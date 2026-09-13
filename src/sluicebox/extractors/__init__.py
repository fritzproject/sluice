"""The extractor registry.

Built-in extractors are listed here. Third-party ones need no change to this
file: a package only has to declare an entry point in the ``sluice.extractors``
group (see docs/writing-extractors.md) and it is loaded at startup.
"""

from __future__ import annotations

import logging
from importlib.metadata import entry_points

from sluicebox.extractors.archive_org import ArchiveOrgExtractor
from sluicebox.extractors.base import Context, Extractor
from sluicebox.extractors.direct import DirectExtractor
from sluicebox.extractors.gutenberg import GutenbergExtractor
from sluicebox.extractors.rss import RssExtractor
from sluicebox.extractors.wikimedia import WikimediaCommonsExtractor

logger = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "sluicebox.extractors"

#: Order matters: the first extractor that recognises a URL wins, and `direct`
#: accepts any http(s) URL, so it has to stay last as the fallback.
_BUILTIN: list[type[Extractor]] = [
    ArchiveOrgExtractor,
    WikimediaCommonsExtractor,
    GutenbergExtractor,
    RssExtractor,
    DirectExtractor,
]
_registry: list[type[Extractor]] = []


def load_plugins() -> None:
    """Load extractors installed as separate packages."""
    for entry in entry_points(group=ENTRY_POINT_GROUP):
        try:
            plugin = entry.load()
        except Exception:  # noqa: BLE001 - a broken plugin must not stop startup
            logger.exception("Could not load extractor '%s'", entry.name)
            continue
        if not (isinstance(plugin, type) and issubclass(plugin, Extractor)):
            logger.warning("Ignoring '%s': not an Extractor subclass", entry.name)
            continue
        register(plugin)
        logger.info("Extractor loaded: %s", plugin.name)


def register(extractor: type[Extractor]) -> None:
    """Add an extractor, taking precedence over the built-in ones."""
    if extractor not in _registry:
        _registry.insert(0, extractor)


def available() -> list[type[Extractor]]:
    return [*_registry, *_BUILTIN]


def find(url: str) -> type[Extractor] | None:
    """First extractor that claims it can handle the URL."""
    for extractor in available():
        try:
            if extractor.matches(url):
                return extractor
        except Exception:  # noqa: BLE001 - matches() must not break the rest
            logger.exception("matches() failed in %s", extractor.name)
    return None


__all__ = ["Context", "Extractor", "available", "find", "load_plugins", "register"]
