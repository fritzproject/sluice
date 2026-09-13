"""Extractor for Wikimedia Commons — freely licensed media."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING
from urllib.parse import unquote

from sluicebox.extractors.base import Extractor
from sluicebox.models import Item, Source, Target

if TYPE_CHECKING:
    from sluicebox.extractors.base import Context

API_ENDPOINT = "https://commons.wikimedia.org/w/api.php"
CATEGORY_PATTERN = re.compile(r"commons\.wikimedia\.org/wiki/(Category:[^?#]+)", re.I)
FILE_PATTERN = re.compile(r"commons\.wikimedia\.org/wiki/(File:[^?#]+)", re.I)
# The API caps a single page of results; anything larger is paged through.
PAGE_SIZE = 500


class WikimediaCommonsExtractor(Extractor):
    """Downloads a Commons file, or every file in a Commons category.

    Everything on Wikimedia Commons is either public domain or published under
    a free licence, and the API is meant to be used this way. Categories are
    the interesting case: they are how Commons groups thousands of files, and
    downloading one is exactly the job this program was written for.

    Licences differ file by file, so each item carries its own in the metadata:
    free does not mean condition-free, and attribution is usually required.
    """

    name = "wikimedia"
    description = "Wikimedia Commons — freely licensed files and categories"

    @classmethod
    def matches(cls, url: str) -> bool:
        return bool(CATEGORY_PATTERN.search(url) or FILE_PATTERN.search(url))

    @staticmethod
    def _title(url: str) -> tuple[str, bool]:
        """Returns the page title and whether it is a category."""
        if match := CATEGORY_PATTERN.search(url):
            return unquote(match.group(1)).replace("_", " "), True
        if match := FILE_PATTERN.search(url):
            return unquote(match.group(1)).replace("_", " "), False
        msg = f"not a Wikimedia Commons URL: {url}"
        raise ValueError(msg)

    def _query(self, ctx: Context, **params: str | int) -> dict:
        response = ctx.session.get(
            API_ENDPOINT, timeout=ctx.timeout,
            params={"action": "query", "format": "json", **params})
        response.raise_for_status()
        return response.json()

    def _files(self, url: str, ctx: Context) -> list[dict]:
        title, is_category = self._title(url)
        if not is_category:
            return [{"title": title}]

        files: list[dict] = []
        continuation: dict[str, str] = {}
        while True:
            data = self._query(ctx, list="categorymembers", cmtitle=title,
                               # 6 is the "File" namespace: subcategories and
                               # article pages are not downloadable media.
                               cmnamespace=6, cmlimit=PAGE_SIZE, **continuation)
            files.extend(data.get("query", {}).get("categorymembers", []))
            continuation = data.get("continue", {})
            if not continuation:
                return files

    def _file_info(self, title: str, ctx: Context) -> dict:
        data = self._query(ctx, prop="imageinfo", titles=title,
                           iiprop="url|size|extmetadata")
        pages = data.get("query", {}).get("pages", {})
        for page in pages.values():
            info = (page.get("imageinfo") or [{}])[0]
            if info.get("url"):
                return info
        msg = f"no downloadable file for {title}"
        raise ValueError(msg)

    def inspect(self, url: str, ctx: Context) -> Source:
        title, is_category = self._title(url)
        files = self._files(url, ctx)
        return Source(
            title=title.removeprefix("Category:").removeprefix("File:").strip(),
            kind="collection" if is_category else "file",
            items_count=len(files),
            # Categories keep receiving new uploads; a single file does not.
            ongoing=is_category,
            metadata={"category": is_category},
        )

    def items(self, url: str, ctx: Context) -> list[Item]:
        return [
            Item(key=entry["title"],
                 title=entry["title"].removeprefix("File:").strip(),
                 index=position)
            for position, entry in enumerate(self._files(url, ctx), start=1)
        ]

    def resolve(self, item: Item, ctx: Context) -> Target:
        info = self._file_info(item.key, ctx)
        extra = info.get("extmetadata", {})
        licence = (extra.get("LicenseShortName", {}) or {}).get("value", "")
        author = (extra.get("Artist", {}) or {}).get("value", "")
        return Target(
            url=info["url"],
            filename=item.title,
            # Commons asks API clients to identify themselves.
            headers={"Api-User-Agent": "Sluice (+https://github.com/fritzproject/sluice)"},
            # Attribution data travels with the file so it is not lost: most
            # free licences require crediting the author.
            metadata={"licence": licence, "author": author},
        )
