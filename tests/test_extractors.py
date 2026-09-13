"""The registry and the built-in extractors."""

from __future__ import annotations

import json

import pytest

from sluicebox import extractors
from sluicebox.extractors.archive_org import ArchiveOrgExtractor
from sluicebox.extractors.base import Context, Extractor
from sluicebox.extractors.direct import DirectExtractor
from sluicebox.extractors.gutenberg import GutenbergExtractor
from sluicebox.extractors.rss import RssExtractor
from sluicebox.extractors.wikimedia import WikimediaCommonsExtractor
from sluicebox.models import Item

FEED = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <title>The Podcast</title>
  <item><title>Episode two</title>
        <enclosure url="https://example.test/two.mp3" type="audio/mpeg"/></item>
  <item><title>Episode one</title>
        <enclosure url="https://example.test/one.mp3" type="audio/mpeg"/></item>
</channel></rss>"""

ARCHIVE_METADATA = {
    "metadata": {"title": "Concert, 1977", "creator": "Someone"},
    "files": [
        {"name": "track1.flac", "format": "Flac", "size": "100"},
        {"name": "track2.flac", "format": "Flac", "size": "200"},
        {"name": "index.json", "format": "JSON", "size": "10"},
    ],
}

GUTENBERG_BOOK = {
    "title": "On the Origin of Species",
    "authors": [{"name": "Darwin, Charles"}],
    "formats": {
        "application/epub+zip": "https://gutenberg.test/book.epub",
        "text/plain; charset=utf-8": "https://gutenberg.test/book.txt",
        "text/html": "https://gutenberg.test/book.html",
        "image/jpeg": "https://gutenberg.test/cover.jpg",
        "application/rdf+xml": "https://gutenberg.test/book.rdf",
    },
}


class FakeResponse:
    def __init__(self, payload: bytes | dict) -> None:
        self._payload = payload
        self.ok = True
        self.headers: dict[str, str] = {}

    @property
    def content(self) -> bytes:
        return self._payload if isinstance(self._payload, bytes) else json.dumps(
            self._payload).encode()

    def json(self) -> dict:
        return self._payload if isinstance(self._payload, dict) else json.loads(self._payload)

    def raise_for_status(self) -> None:
        return None


class FakeSession:
    def __init__(self, payload: bytes | dict | list) -> None:
        #: A list is served one entry per call, for paged APIs.
        self.payloads = list(payload) if isinstance(payload, list) else None
        self.payload = payload
        self.calls: list[dict] = []

    def get(self, url: str, **kwargs) -> FakeResponse:  # noqa: ANN003
        self.calls.append(kwargs.get("params") or {})
        if self.payloads is not None:
            return FakeResponse(self.payloads.pop(0))
        return FakeResponse(self.payload)

    def head(self, url: str, **kwargs) -> FakeResponse:  # noqa: ANN003, ARG002
        return FakeResponse(b"")


# ------------------------------------------------------------------ registry
def test_direct_stays_the_fallback() -> None:
    """`direct` accepts any http(s) URL: it must not steal the others'."""
    assert extractors.find("https://archive.org/details/something") is ArchiveOrgExtractor
    assert extractors.find("https://commons.wikimedia.org/wiki/Category:Cats") \
        is WikimediaCommonsExtractor
    assert extractors.find("https://www.gutenberg.org/ebooks/2009") is GutenbergExtractor
    assert extractors.find("https://example.test/file.zip") is DirectExtractor


def test_unhandled_url() -> None:
    assert extractors.find("magnet:?xt=urn:btih:abc") is None


def test_registered_extractor_takes_precedence() -> None:
    class Fake(Extractor):
        name = "fake"

        @classmethod
        def matches(cls, url: str) -> bool:
            return "example.test" in url

        def inspect(self, url, ctx): ...  # noqa: ANN001, ANN201, ARG002
        def items(self, url, ctx): ...  # noqa: ANN001, ANN201, ARG002
        def resolve(self, item, ctx): ...  # noqa: ANN001, ANN201, ARG002

    extractors.register(Fake)
    try:
        assert extractors.find("https://example.test/file.zip") is Fake
    finally:
        extractors._registry.remove(Fake)  # noqa: SLF001


# ----------------------------------------------------------------------- RSS
def test_rss_orders_oldest_first() -> None:
    ctx = Context(session=FakeSession(FEED.encode()))
    extractor = RssExtractor()

    source = extractor.inspect("https://example.test/feed.xml", ctx)
    assert source.title == "The Podcast"
    assert source.items_count == 2
    assert source.ongoing, "a feed can always receive new episodes"

    items = extractor.items("https://example.test/feed.xml", ctx)
    # The feed lists them newest first: numbering must grow with time instead.
    assert [i.title for i in items] == ["Episode one", "Episode two"]
    assert [i.index for i in items] == [1, 2]


def test_rss_filename_from_link() -> None:
    target = RssExtractor().resolve(
        Item(key="https://example.test/one.mp3", title="Episode one"),
        Context(session=FakeSession(b"")))
    assert target.filename == "one.mp3"


# --------------------------------------------------------------- archive.org
def test_archive_skips_housekeeping_files() -> None:
    ctx = Context(session=FakeSession(ARCHIVE_METADATA))
    url = "https://archive.org/details/concert1977"

    source = ArchiveOrgExtractor().inspect(url, ctx)
    assert source.title == "Concert, 1977"
    assert source.items_count == 2, "the housekeeping JSON must not be counted"
    assert not source.ongoing, "an archived item does not grow any more"

    items = ArchiveOrgExtractor().items(url, ctx)
    assert [i.title for i in items] == ["track1.flac", "track2.flac"]


def test_archive_rejects_bad_url() -> None:
    with pytest.raises(ValueError, match="not an archive.org"):
        ArchiveOrgExtractor()._identifier("https://example.test/other")  # noqa: SLF001


# ----------------------------------------------------------------- Gutenberg
def test_gutenberg_keeps_only_readable_formats() -> None:
    ctx = Context(session=FakeSession(GUTENBERG_BOOK))
    url = "https://www.gutenberg.org/ebooks/2009"

    source = GutenbergExtractor().inspect(url, ctx)
    assert source.title == "On the Origin of Species"
    assert not source.ongoing, "a published book gains no new formats"
    # Cover image and RDF metadata are not what anyone asked for.
    assert source.items_count == 3

    items = GutenbergExtractor().items(url, ctx)
    assert [i.title.rsplit(".", 1)[1] for i in items] == ["epub", "html", "txt"]


def test_gutenberg_rejects_bad_url() -> None:
    with pytest.raises(ValueError, match="not a Project Gutenberg"):
        GutenbergExtractor()._book_id("https://example.test/book")  # noqa: SLF001


# --------------------------------------------------------- Wikimedia Commons
def test_wikimedia_pages_through_a_category() -> None:
    """Categories hold thousands of files: paging must not lose any."""
    first = {"query": {"categorymembers": [{"title": "File:a.jpg"}]},
             "continue": {"cmcontinue": "next"}}
    second = {"query": {"categorymembers": [{"title": "File:b.jpg"}]}}
    ctx = Context(session=FakeSession([first, second, first, second]))
    url = "https://commons.wikimedia.org/wiki/Category:Lighthouses"

    source = WikimediaCommonsExtractor().inspect(url, ctx)
    assert source.title == "Lighthouses"
    assert source.items_count == 2, "the second page must be followed"
    assert source.ongoing, "a category keeps receiving uploads"

    items = WikimediaCommonsExtractor().items(url, ctx)
    assert [i.title for i in items] == ["a.jpg", "b.jpg"]


def test_wikimedia_single_file_is_not_a_collection() -> None:
    ctx = Context(session=FakeSession({}))
    source = WikimediaCommonsExtractor().inspect(
        "https://commons.wikimedia.org/wiki/File:Example.jpg", ctx)
    assert source.kind == "file"
    assert not source.ongoing


def test_wikimedia_carries_licence_and_author() -> None:
    """Free does not mean condition-free: attribution must not get lost."""
    payload = {"query": {"pages": {"1": {"imageinfo": [{
        "url": "https://upload.test/Example.jpg",
        "extmetadata": {"LicenseShortName": {"value": "CC BY-SA 4.0"},
                        "Artist": {"value": "A Photographer"}},
    }]}}}}
    target = WikimediaCommonsExtractor().resolve(
        Item(key="File:Example.jpg", title="Example.jpg"),
        Context(session=FakeSession(payload)))

    assert target.url == "https://upload.test/Example.jpg"
    assert target.metadata["licence"] == "CC BY-SA 4.0"
    assert target.metadata["author"] == "A Photographer"
