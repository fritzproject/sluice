"""Extractor for Project Gutenberg — public domain books."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from sluicebox.extractors.base import Extractor
from sluicebox.models import Item, Source, Target

if TYPE_CHECKING:
    from sluicebox.extractors.base import Context

BOOK_PATTERN = re.compile(r"gutenberg\.org/(?:ebooks|files|cache/epub)/(\d+)")
GUTENDEX_ENDPOINT = "https://gutendex.com/books/{book_id}"

# One entry per format we are willing to download, in the order we prefer them
# when the same book is offered several times. Anything not listed here (cover
# images, RDF metadata) is skipped: it is not what people ask for.
FORMAT_PREFERENCE = [
    ("application/epub+zip", "epub"),
    ("application/x-mobipocket-ebook", "mobi"),
    ("text/html", "html"),
    ("text/plain; charset=utf-8", "txt"),
    ("text/plain", "txt"),
]


class GutenbergExtractor(Extractor):
    """Downloads a Project Gutenberg book in every format it is offered in.

    Project Gutenberg publishes works whose copyright has expired, and says so
    explicitly: bulk downloading is expected and supported. Metadata comes from
    Gutendex, the public JSON API in front of the catalogue.
    """

    name = "gutenberg"
    description = "Project Gutenberg — public domain books"

    @classmethod
    def matches(cls, url: str) -> bool:
        return bool(BOOK_PATTERN.search(url))

    @staticmethod
    def _book_id(url: str) -> str:
        match = BOOK_PATTERN.search(url)
        if not match:
            msg = f"not a Project Gutenberg book URL: {url}"
            raise ValueError(msg)
        return match.group(1)

    def _book(self, url: str, ctx: Context) -> dict:
        response = ctx.session.get(
            GUTENDEX_ENDPOINT.format(book_id=self._book_id(url)), timeout=ctx.timeout)
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _downloadable(book: dict) -> list[tuple[str, str]]:
        """Pairs of (extension, url), one per offered format we accept."""
        formats = book.get("formats", {})
        chosen: list[tuple[str, str]] = []
        seen: set[str] = set()
        for mime, extension in FORMAT_PREFERENCE:
            link = formats.get(mime)
            # ".zip" links hold the same text already available uncompressed.
            if link and extension not in seen and not link.endswith(".zip"):
                chosen.append((extension, link))
                seen.add(extension)
        return chosen

    def inspect(self, url: str, ctx: Context) -> Source:
        book = self._book(url, ctx)
        authors = ", ".join(a.get("name", "") for a in book.get("authors", []))
        return Source(
            title=str(book.get("title") or f"Gutenberg {self._book_id(url)}"),
            kind="collection",
            items_count=len(self._downloadable(book)),
            # A published book does not gain new formats: nothing to re-check.
            ongoing=False,
            metadata={"authors": authors, "id": self._book_id(url)},
        )

    def items(self, url: str, ctx: Context) -> list[Item]:
        book = self._book(url, ctx)
        return [
            Item(key=link, title=f"{book.get('title', 'book')}.{extension}", index=position)
            for position, (extension, link) in enumerate(self._downloadable(book), start=1)
        ]

    def resolve(self, item: Item, ctx: Context) -> Target:
        return Target(url=item.key, filename=item.title)
