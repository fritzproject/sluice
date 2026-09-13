"""Estrattore per feed RSS/Atom con allegati (podcast, videocast, bollettini)."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET  # noqa: N817
from pathlib import PurePosixPath
from typing import TYPE_CHECKING
from urllib.parse import unquote, urlparse

from sluice.extractors.base import Extractor
from sluice.models import Item, Source, Target

if TYPE_CHECKING:
    from sluice.extractors.base import Context

NAMESPACES = {"atom": "http://www.w3.org/2005/Atom"}


class RssExtractor(Extractor):
    """Scarica gli allegati di un feed, dal piu' vecchio al piu' recente.

    E' il caso d'uso che meglio mostra a cosa serve il nucleo: un podcast con
    trecento puntate arretrate vuole esattamente coda, portata limitata,
    ripresa dei trasferimenti interrotti e ricontrollo periodico per le nuove.
    """

    name = "rss"
    description = "Feed RSS/Atom con allegati (podcast e simili)"

    @classmethod
    def matches(cls, url: str) -> bool:
        if urlparse(url).scheme not in {"http", "https"}:
            return False
        lowered = url.lower()
        return any(hint in lowered for hint in ("rss", "feed", "atom", ".xml"))

    def _parse(self, url: str, ctx: Context) -> ET.Element:
        response = ctx.session.get(url, timeout=ctx.timeout)
        response.raise_for_status()
        return ET.fromstring(response.content)  # noqa: S314

    @staticmethod
    def _entries(root: ET.Element) -> list[tuple[str, str]]:
        """Coppie (titolo, url allegato), dalla piu' vecchia alla piu' recente."""
        found: list[tuple[str, str]] = []

        for item in root.iter("item"):            # RSS 2.0
            enclosure = item.find("enclosure")
            title = (item.findtext("title") or "senza titolo").strip()
            if enclosure is not None and enclosure.get("url"):
                found.append((title, enclosure.get("url", "")))

        for entry in root.iter(f"{{{NAMESPACES['atom']}}}entry"):   # Atom
            title = (entry.findtext(f"{{{NAMESPACES['atom']}}}title")
                     or "senza titolo").strip()
            for link in entry.iter(f"{{{NAMESPACES['atom']}}}link"):
                if link.get("rel") == "enclosure" and link.get("href"):
                    found.append((title, link.get("href", "")))
                    break

        # I feed elencano il piu' recente per primo: invertiamo, cosi' la
        # numerazione cresce col tempo come ci si aspetta da una raccolta.
        return list(reversed(found))

    def inspect(self, url: str, ctx: Context) -> Source:
        root = self._parse(url, ctx)
        title = (root.findtext("./channel/title")
                 or root.findtext(f"{{{NAMESPACES['atom']}}}title")
                 or "Feed")
        entries = self._entries(root)
        # Un feed puo' sempre ricevere nuove puntate: vale la pena ricontrollarlo.
        return Source(title=title.strip(), kind="collection",
                      items_count=len(entries), ongoing=True)

    def items(self, url: str, ctx: Context) -> list[Item]:
        entries = self._entries(self._parse(url, ctx))
        return [Item(key=link, title=title, index=position)
                for position, (title, link) in enumerate(entries, start=1)]

    def resolve(self, item: Item, ctx: Context) -> Target:
        name = unquote(PurePosixPath(urlparse(item.key).path).name)
        if not name:
            safe = re.sub(r"[^\w\s.-]", "", item.title).strip() or "puntata"
            name = f"{safe}.mp3"
        return Target(url=item.key, filename=name)
