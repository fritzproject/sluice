"""Extractor for a plain HTTP(S) link to a file."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import TYPE_CHECKING
from urllib.parse import unquote, urlparse

from sluicebox.extractors.base import Extractor
from sluicebox.models import Item, Source, Target

if TYPE_CHECKING:
    from sluicebox.extractors.base import Context


class DirectExtractor(Extractor):
    """The simplest case: the URL already is the file to download.

    It doubles as the smallest possible example for anyone writing a new
    extractor — four methods, none of which touches the disk or does more
    network work than strictly needed.
    """

    name = "direct"
    description = "Direct HTTP(S) link to a file"

    @classmethod
    def matches(cls, url: str) -> bool:
        return urlparse(url).scheme in {"http", "https"}

    @staticmethod
    def _filename(url: str) -> str:
        name = unquote(PurePosixPath(urlparse(url).path).name)
        return name or "download.bin"

    def inspect(self, url: str, ctx: Context) -> Source:
        title = self._filename(url)
        size = 0
        try:
            # HEAD is a courtesy only: if the server does not support it we
            # carry on, and learn the size during the transfer instead.
            response = ctx.session.head(url, timeout=ctx.timeout, allow_redirects=True)
            if response.ok:
                size = int(response.headers.get("content-length", 0))
        except Exception:  # noqa: BLE001 - optional information
            size = 0
        return Source(title=title, kind="file", items_count=1, metadata={"size": size})

    def items(self, url: str, ctx: Context) -> list[Item]:
        return [Item(key=url, title=self._filename(url), index=1)]

    def resolve(self, item: Item, ctx: Context) -> Target:
        return Target(url=item.key, filename=item.title)
