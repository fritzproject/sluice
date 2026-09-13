"""Extractor for Internet Archive items (archive.org)."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from sluice.extractors.base import Extractor
from sluice.models import Item, Source, Target

if TYPE_CHECKING:
    from sluice.extractors.base import Context

ITEM_PATTERN = re.compile(r"archive\.org/(?:details|download)/([^/?#]+)")
METADATA_ENDPOINT = "https://archive.org/metadata/{identifier}"
DOWNLOAD_ENDPOINT = "https://archive.org/download/{identifier}/{name}"

# Housekeeping files the archive generates for itself: downloading them serves
# no purpose and only inflates the item count.
SKIPPED_FORMATS = {"Metadata", "Item Tile", "JSON", "Archive BitTorrent",
                   "Item CDX Index", "Item CDX Meta-Index", "Log", "CSV"}


class ArchiveOrgExtractor(Extractor):
    """Downloads the files of an Internet Archive item.

    A vast, openly accessible collection: authorised concert recordings,
    public domain books and software, radio archives. Useful in its own right,
    and a good stress test, since a single item can hold hundreds of files of
    wildly different sizes.
    """

    name = "archive_org"
    description = "Internet Archive items (archive.org)"

    @classmethod
    def matches(cls, url: str) -> bool:
        return bool(ITEM_PATTERN.search(url))

    @staticmethod
    def _identifier(url: str) -> str:
        match = ITEM_PATTERN.search(url)
        if not match:
            msg = f"not an archive.org item URL: {url}"
            raise ValueError(msg)
        return match.group(1)

    def _metadata(self, url: str, ctx: Context) -> dict:
        identifier = self._identifier(url)
        response = ctx.session.get(
            METADATA_ENDPOINT.format(identifier=identifier), timeout=ctx.timeout)
        response.raise_for_status()
        return response.json()

    @classmethod
    def _files(cls, metadata: dict) -> list[dict]:
        return [f for f in metadata.get("files", [])
                if f.get("format") not in SKIPPED_FORMATS and f.get("name")]

    def inspect(self, url: str, ctx: Context) -> Source:
        metadata = self._metadata(url, ctx)
        info = metadata.get("metadata", {})
        files = self._files(metadata)
        return Source(
            title=str(info.get("title") or self._identifier(url)),
            kind="collection",
            items_count=len(files),
            # An archived item is closed: re-checking it would find nothing.
            ongoing=False,
            metadata={"identifier": self._identifier(url),
                      "creator": info.get("creator", ""),
                      "date": info.get("date", ""),
                      "licence": info.get("licenseurl", "")},
        )

    def items(self, url: str, ctx: Context) -> list[Item]:
        identifier = self._identifier(url)
        files = self._files(self._metadata(url, ctx))
        return [
            Item(key=f"{identifier}/{f['name']}", title=f["name"], index=position,
                 metadata={"size": int(f.get("size", 0) or 0),
                           "format": f.get("format", "")})
            for position, f in enumerate(sorted(files, key=lambda f: f["name"]), start=1)
        ]

    def resolve(self, item: Item, ctx: Context) -> Target:
        identifier, _, name = item.key.partition("/")
        return Target(
            url=DOWNLOAD_ENDPOINT.format(identifier=identifier, name=name),
            filename=name.rsplit("/", 1)[-1],
        )
