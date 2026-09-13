"""Extractor for RSS/Atom feeds with enclosures (podcasts, videocasts)."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET  # noqa: N817
from pathlib import PurePosixPath
from typing import TYPE_CHECKING
from urllib.parse import unquote, urlparse

from sluicebox.extractors.base import Extractor
from sluicebox.models import Item, Source, Target

if TYPE_CHECKING:
    from sluicebox.extractors.base import Context

NAMESPACES = {"atom": "http://www.w3.org/2005/Atom"}


class RssExtractor(Extractor):
    """Downloads a feed's enclosures, oldest first.

    This is the case that shows best what the core is for: a podcast with
    three hundred back episodes wants exactly a queue, a bounded transfer
    rate, resumable transfers, and a periodic re-check for new ones.
    """

    name = "rss"
    description = "RSS/Atom feed with enclosures (podcasts and the like)"

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
        """(title, enclosure url) pairs, oldest first."""
        found: list[tuple[str, str]] = []

        for item in root.iter("item"):            # RSS 2.0
            enclosure = item.find("enclosure")
            title = (item.findtext("title") or "untitled").strip()
            if enclosure is not None and enclosure.get("url"):
                found.append((title, enclosure.get("url", "")))

        for entry in root.iter(f"{{{NAMESPACES['atom']}}}entry"):   # Atom
            title = (entry.findtext(f"{{{NAMESPACES['atom']}}}title") or "untitled").strip()
            for link in entry.iter(f"{{{NAMESPACES['atom']}}}link"):
                if link.get("rel") == "enclosure" and link.get("href"):
                    found.append((title, link.get("href", "")))
                    break

        # Feeds list the newest entry first: reversing makes the numbering grow
        # with time, which is what anyone expects from a collection.
        return list(reversed(found))

    def inspect(self, url: str, ctx: Context) -> Source:
        root = self._parse(url, ctx)
        title = (root.findtext("./channel/title")
                 or root.findtext(f"{{{NAMESPACES['atom']}}}title")
                 or "Feed")
        entries = self._entries(root)
        # A feed can always receive new episodes: worth re-checking.
        return Source(title=title.strip(), kind="collection",
                      items_count=len(entries), ongoing=True)

    def items(self, url: str, ctx: Context) -> list[Item]:
        entries = self._entries(self._parse(url, ctx))
        return [Item(key=link, title=title, index=position)
                for position, (title, link) in enumerate(entries, start=1)]

    def resolve(self, item: Item, ctx: Context) -> Target:
        name = unquote(PurePosixPath(urlparse(item.key).path).name)
        if not name:
            safe = re.sub(r"[^\w\s.-]", "", item.title).strip() or "episode"
            name = f"{safe}.mp3"
        return Target(url=item.key, filename=name)
