"""Estrattore per un semplice collegamento HTTP(S) a un file."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import TYPE_CHECKING
from urllib.parse import unquote, urlparse

from sluice.extractors.base import Extractor
from sluice.models import Item, Source, Target

if TYPE_CHECKING:
    from sluice.extractors.base import Context


class DirectExtractor(Extractor):
    """Il caso piu' semplice: l'URL e' gia' il file da scaricare.

    Fa anche da esempio minimo per chi ne scrive uno nuovo: sono quattro
    metodi e nessuno di questi tocca il disco o la rete piu' del necessario.
    """

    name = "direct"
    description = "Collegamento diretto a un file HTTP(S)"

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
            # HEAD e' solo cortesia: se il server non la gestisce si prosegue
            # lo stesso, la dimensione la si scopre in fase di scaricamento.
            response = ctx.session.head(url, timeout=ctx.timeout, allow_redirects=True)
            if response.ok:
                size = int(response.headers.get("content-length", 0))
        except Exception:  # noqa: BLE001 - informazione facoltativa
            size = 0
        return Source(title=title, kind="file", items_count=1,
                      metadata={"size": size})

    def items(self, url: str, ctx: Context) -> list[Item]:
        return [Item(key=url, title=self._filename(url), index=1)]

    def resolve(self, item: Item, ctx: Context) -> Target:
        return Target(url=item.key, filename=item.title)
