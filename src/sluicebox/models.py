"""The few types exchanged between the core and the extractors.

Deliberately small: writing an extractor should never require reading more
than one page of documentation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Source:
    """What sits behind a URL: a single file, or a collection."""

    title: str
    #: "file" for a single item, "collection" for an ordered set of them
    #: (a series, a podcast, an album, an archive).
    kind: str = "collection"
    items_count: int = 0
    #: Whether the collection can still grow. Extractors that know this say so,
    #: and the core uses it to decide whether re-checking is worth anything.
    ongoing: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Item:
    """One downloadable element inside a source."""

    #: Stable identifier within the source. It is how an item is found again
    #: after a restart, so it must not depend on position: if the source
    #: inserts something in the middle, everything else would shift and
    #: already-downloaded files would be fetched a second time.
    key: str
    title: str
    #: Ordinal (episode, track, chapter) where the notion makes sense.
    index: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Target:
    """Where to actually fetch the bytes of one item."""

    url: str
    #: Name suggested by the source. The core may ignore it and apply its own
    #: naming scheme instead.
    filename: str
    #: Extra headers required by this particular request (Referer, tokens,
    #: session cookies, a courtesy user agent...).
    headers: dict[str, str] = field(default_factory=dict)
    #: Anything worth carrying alongside the file — licence and author, for
    #: instance, which most free licences require you to keep.
    metadata: dict[str, Any] = field(default_factory=dict)
