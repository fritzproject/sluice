"""How downloaded files end up being named."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

#: Characters forbidden on at least one supported platform.
INVALID_CHARS = re.compile(r'[\\/:*?"<>|]')
COLLAPSE_SPACES = re.compile(r"\s{2,}")


def sanitize(name: str, *, fallback: str = "unnamed") -> str:
    """Make a string usable as a file or folder name."""
    cleaned = INVALID_CHARS.sub("", name).strip(" .")
    cleaned = COLLAPSE_SPACES.sub(" ", cleaned)
    return cleaned or fallback


@dataclass
class Layout:
    """The scheme used to build the path and name of downloaded files.

    Placeholders are ``{source}``, ``{title}``, ``{index}``, ``{index:02d}``
    and ``{ext}``. The defaults put each collection in its own folder and
    number the items, which is what the common case wants.
    """

    #: Folder to group items under. Empty means no subfolder — what a single
    #: file needs, or it would end up inside a folder named after itself.
    folder: str = "{source}"
    filename: str = "{index:02d} - {title}{ext}"
    #: Alternative scheme for media libraries: most servers recognise
    #: collections written in the S01E01 form.
    MEDIA_LIBRARY: str = "{source} S01E{index:02d}{ext}"

    @classmethod
    def for_single_file(cls) -> Layout:
        """Scheme suited to a source holding exactly one file."""
        return cls(folder="", filename="{title}{ext}")

    def build(self, root: Path, *, source: str, title: str,
              index: int | None, suggested: str) -> Path:
        extension = Path(suggested).suffix
        values = {
            "source": sanitize(source),
            "title": sanitize(Path(title).stem or title),
            "index": index if index is not None else 0,
            "ext": extension,
        }
        rendered_folder = self.folder.format(**values).strip() if self.folder else ""
        folder = root / sanitize(rendered_folder) if rendered_folder else root
        name = sanitize(self.filename.format(**values), fallback=suggested)
        if not Path(name).suffix and extension:
            name += extension
        return folder / name
