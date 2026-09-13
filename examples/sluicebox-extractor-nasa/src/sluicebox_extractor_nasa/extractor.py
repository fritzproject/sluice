"""Extractor for the NASA Image and Video Library.

A complete, working example of a third-party extractor: a separate package
that plugs into Sluice through an entry point, without touching the core.

The source is public domain — NASA material is generally free of copyright —
and the API needs no key, which makes it a good example to run as-is.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from sluicebox.extractors.base import Extractor
from sluicebox.models import Item, Source, Target

if TYPE_CHECKING:
    from sluicebox.extractors.base import Context

SEARCH_ENDPOINT = "https://images-api.nasa.gov/search"
ASSET_ENDPOINT = "https://images-api.nasa.gov/asset/{nasa_id}"

# Two shapes are accepted: a single item page, and a search URL. A search is
# the interesting one — it is how you grab a whole mission at once.
ITEM_PATTERN = re.compile(r"images\.nasa\.gov/details/([^/?#]+)")
SEARCH_PATTERN = re.compile(r"images\.nasa\.gov/search\b")
QUERY_PATTERN = re.compile(r"[?&]q=([^&]+)")

#: Suffix order from best to worst. The API returns every rendition of the
#: same picture; downloading all four would just waste bandwidth on
#: thumbnails, so one is picked per item.
PREFERRED = ("~orig", "~large", "~medium", "~small")
#: How many search results to take. The API pages, but a single page is plenty
#: for an example and keeps the request count polite.
SEARCH_LIMIT = 100


class NasaExtractor(Extractor):
    """Downloads NASA imagery, either one item or a whole search."""

    name = "nasa"
    description = "NASA Image and Video Library (public domain)"

    @classmethod
    def matches(cls, url: str) -> bool:
        return bool(ITEM_PATTERN.search(url) or SEARCH_PATTERN.search(url))

    @staticmethod
    def _query(url: str) -> str:
        match = QUERY_PATTERN.search(url)
        if not match:
            msg = "search URL without a q= parameter"
            raise ValueError(msg)
        from urllib.parse import unquote_plus
        return unquote_plus(match.group(1))

    def _results(self, url: str, ctx: Context) -> list[dict]:
        if match := ITEM_PATTERN.search(url):
            return [{"nasa_id": match.group(1), "title": match.group(1)}]

        response = ctx.session.get(
            SEARCH_ENDPOINT, timeout=ctx.timeout,
            params={"q": self._query(url), "media_type": "image"})
        response.raise_for_status()
        items = response.json().get("collection", {}).get("items", [])
        found = []
        for entry in items[:SEARCH_LIMIT]:
            data = (entry.get("data") or [{}])[0]
            if data.get("nasa_id"):
                found.append({"nasa_id": data["nasa_id"],
                              "title": data.get("title") or data["nasa_id"]})
        return found

    def inspect(self, url: str, ctx: Context) -> Source:
        results = self._results(url, ctx)
        single = bool(ITEM_PATTERN.search(url))
        return Source(
            title=results[0]["title"] if single else f"NASA — {self._query(url)}",
            kind="file" if single else "collection",
            items_count=len(results),
            # A saved search keeps matching newly published material.
            ongoing=not single,
            metadata={"licence": "public domain (NASA)"},
        )

    def items(self, url: str, ctx: Context) -> list[Item]:
        return [
            Item(key=entry["nasa_id"], title=entry["title"], index=position)
            for position, entry in enumerate(self._results(url, ctx), start=1)
        ]

    def resolve(self, item: Item, ctx: Context) -> Target:
        response = ctx.session.get(
            ASSET_ENDPOINT.format(nasa_id=item.key), timeout=ctx.timeout)
        response.raise_for_status()
        hrefs = [i.get("href", "") for i in response.json().get("collection", {}).get("items", [])]

        chosen = next((h for suffix in PREFERRED for h in hrefs if suffix in h), None)
        if not chosen:
            msg = f"no downloadable rendition for {item.key}"
            raise ValueError(msg)

        # The API still hands out http:// links; asking over https avoids an
        # unnecessary redirect on every single file.
        chosen = chosen.replace("http://", "https://", 1)
        extension = chosen.rsplit(".", 1)[-1] or "jpg"
        return Target(url=chosen, filename=f"{item.key}.{extension}",
                      metadata={"licence": "public domain (NASA)", "nasa_id": item.key})
