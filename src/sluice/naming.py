"""Come si chiamano i file una volta scaricati."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

#: Caratteri vietati su almeno uno dei sistemi supportati.
INVALID_CHARS = re.compile(r'[\\/:*?"<>|]')
COLLAPSE_SPACES = re.compile(r"\s{2,}")


def sanitize(name: str, *, fallback: str = "senza-nome") -> str:
    """Rende una stringa utilizzabile come nome di file o cartella."""
    cleaned = INVALID_CHARS.sub("", name).strip(" .")
    cleaned = COLLAPSE_SPACES.sub(" ", cleaned)
    return cleaned or fallback


@dataclass
class Layout:
    """Schema con cui comporre percorso e nome dei file scaricati.

    I segnaposto disponibili sono ``{source}``, ``{title}``, ``{index}``,
    ``{index:02d}`` e ``{ext}``. Gli schemi predefiniti mettono ogni raccolta
    in una cartella propria e numerano gli elementi, che e' quello che serve
    nel caso piu' comune.
    """

    #: Cartella in cui raggruppare gli elementi. Vuota: nessuna sottocartella,
    #: che e' quello che serve per un file singolo (altrimenti finirebbe in una
    #: cartella chiamata come lui).
    folder: str = "{source}"
    filename: str = "{index:02d} - {title}{ext}"
    #: Schema alternativo per chi organizza una libreria multimediale: molti
    #: server riconoscono le raccolte con la forma S01E01.
    MEDIA_LIBRARY: str = "{source} S01E{index:02d}{ext}"

    @classmethod
    def for_single_file(cls) -> Layout:
        """Schema adatto a una sorgente che contiene un solo file."""
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
