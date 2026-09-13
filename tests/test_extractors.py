"""Verifiche sul registro degli estrattori e su quelli inclusi."""

from __future__ import annotations

import json

import pytest

from sluice import extractors
from sluice.extractors.archive_org import ArchiveOrgExtractor
from sluice.extractors.base import Context, Extractor
from sluice.extractors.direct import DirectExtractor
from sluice.extractors.rss import RssExtractor
from sluice.models import Item

FEED = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <title>Il Podcast</title>
  <item><title>Puntata due</title>
        <enclosure url="https://esempio.test/due.mp3" type="audio/mpeg"/></item>
  <item><title>Puntata uno</title>
        <enclosure url="https://esempio.test/uno.mp3" type="audio/mpeg"/></item>
</channel></rss>"""

METADATA = {
    "metadata": {"title": "Concerto del 1977", "creator": "Tizio"},
    "files": [
        {"name": "brano1.flac", "format": "Flac", "size": "100"},
        {"name": "brano2.flac", "format": "Flac", "size": "200"},
        {"name": "elenco.json", "format": "JSON", "size": "10"},
    ],
}


class FakeResponse:
    def __init__(self, payload: bytes | dict) -> None:
        self._payload = payload
        self.ok = True
        self.headers: dict[str, str] = {}

    @property
    def content(self) -> bytes:
        if isinstance(self._payload, bytes):
            return self._payload
        return json.dumps(self._payload).encode()

    def json(self) -> dict:
        return self._payload if isinstance(self._payload, dict) else json.loads(self._payload)

    def raise_for_status(self) -> None:
        return None


class FakeSession:
    def __init__(self, payload: bytes | dict) -> None:
        self.payload = payload

    def get(self, url: str, **kwargs) -> FakeResponse:  # noqa: ANN003, ARG002
        return FakeResponse(self.payload)

    def head(self, url: str, **kwargs) -> FakeResponse:  # noqa: ANN003, ARG002
        return FakeResponse(b"")


# ------------------------------------------------------------------ registro
def test_direct_resta_come_ripiego() -> None:
    """`direct` accetta qualunque http(s): non deve rubare gli URL altrui."""
    scelto = extractors.find("https://archive.org/details/qualcosa")
    assert scelto is ArchiveOrgExtractor

    assert extractors.find("https://esempio.test/file.zip") is DirectExtractor


def test_url_non_gestito() -> None:
    assert extractors.find("magnet:?xt=urn:btih:abc") is None


def test_registrazione_ha_priorita() -> None:
    class Finto(Extractor):
        name = "finto"

        @classmethod
        def matches(cls, url: str) -> bool:
            return "esempio.test" in url

        def inspect(self, url, ctx):  # noqa: ANN001, ANN201, ARG002
            ...

        def items(self, url, ctx):  # noqa: ANN001, ANN201, ARG002
            ...

        def resolve(self, item, ctx):  # noqa: ANN001, ANN201, ARG002
            ...

    extractors.register(Finto)
    try:
        assert extractors.find("https://esempio.test/file.zip") is Finto
    finally:
        extractors._registry.remove(Finto)  # noqa: SLF001


# ----------------------------------------------------------------------- RSS
def test_rss_ordina_dal_piu_vecchio() -> None:
    ctx = Context(session=FakeSession(FEED.encode()))
    estrattore = RssExtractor()

    sorgente = estrattore.inspect("https://esempio.test/feed.xml", ctx)
    assert sorgente.title == "Il Podcast"
    assert sorgente.items_count == 2
    assert sorgente.ongoing, "un feed puo' sempre ricevere nuove puntate"

    elementi = estrattore.items("https://esempio.test/feed.xml", ctx)
    # Il feed le elenca al contrario: la numerazione deve crescere col tempo.
    assert [e.title for e in elementi] == ["Puntata uno", "Puntata due"]
    assert [e.index for e in elementi] == [1, 2]


def test_rss_nome_file_dal_collegamento() -> None:
    target = RssExtractor().resolve(
        Item(key="https://esempio.test/uno.mp3", title="Puntata uno"),
        Context(session=FakeSession(b"")))
    assert target.filename == "uno.mp3"


# --------------------------------------------------------------- archive.org
def test_archive_scarta_i_file_di_servizio() -> None:
    ctx = Context(session=FakeSession(METADATA))
    url = "https://archive.org/details/concerto1977"

    sorgente = ArchiveOrgExtractor().inspect(url, ctx)
    assert sorgente.title == "Concerto del 1977"
    assert sorgente.items_count == 2, "il JSON di servizio non va contato"
    assert not sorgente.ongoing, "un elemento archiviato non cresce piu'"

    elementi = ArchiveOrgExtractor().items(url, ctx)
    assert [e.title for e in elementi] == ["brano1.flac", "brano2.flac"]


def test_archive_url_non_valido() -> None:
    with pytest.raises(ValueError, match="non riconosciuto"):
        ArchiveOrgExtractor()._identifier("https://esempio.test/altro")  # noqa: SLF001
