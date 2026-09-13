"""The interface every extractor implements."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import requests

    from sluice.models import Item, Source, Target


@dataclass
class Context:
    """What the core hands to an extractor.

    The `session` is the same one used to inspect a source and to download its
    items, and that is not a detail: some sources sign the final link against
    the address that asked for it, so resolving from one place and downloading
    from another fails. Using the session you are given inherits the right
    network identity — including any proxy assigned to that item — for free.
    """

    session: requests.Session
    #: Suggested timeout for requests, in seconds.
    timeout: int = 30


class Extractor(ABC):
    """Turns a URL into downloadable items.

    An extractor downloads nothing and never touches the disk: it only says
    what is there and where to get it. Queueing, resuming, retries, naming and
    limits belong to the core, and work the same way for every extractor —
    which means every extractor inherits improvements made there for free.
    """

    #: Short identifier, used in configuration and logs.
    name: str = "extractor"
    #: One-line description shown in the interface.
    description: str = ""

    @classmethod
    @abstractmethod
    def matches(cls, url: str) -> bool:
        """True if this extractor can handle the URL. Must be fast: no network."""

    @abstractmethod
    def inspect(self, url: str, ctx: Context) -> Source:
        """Describe the source without downloading its items."""

    @abstractmethod
    def items(self, url: str, ctx: Context) -> list[Item]:
        """List the available items, in order."""

    @abstractmethod
    def resolve(self, item: Item, ctx: Context) -> Target:
        """Return the direct link for a single item.

        Called right before the transfer, and again on every retry: links that
        expire must therefore be generated here, never stored. On a third
        attempt half an hour later, a cached link would already be dead.
        """
