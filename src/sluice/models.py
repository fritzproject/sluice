"""Tipi scambiati fra il nucleo e gli estrattori.

Sono volutamente pochi e semplici: un estrattore deve poter essere scritto
leggendo una pagina sola di documentazione.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Source:
    """Cosa c'e' dall'altra parte di un URL: un file solo o una raccolta."""

    title: str
    #: "file" per un singolo elemento, "collection" per una raccolta ordinata
    #: (una serie, un podcast, un album, un archivio).
    kind: str = "collection"
    items_count: int = 0
    #: Se la raccolta puo' ancora crescere. Gli estrattori che lo sanno lo
    #: dichiarano: il nucleo lo usa per decidere se ha senso ricontrollarla.
    ongoing: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Item:
    """Un elemento scaricabile all'interno di una sorgente."""

    #: Identificatore stabile nella sorgente: serve a ritrovare l'elemento
    #: dopo un riavvio, quindi non deve dipendere dall'ordinamento.
    key: str
    title: str
    #: Numero d'ordine (episodio, traccia, capitolo), se il concetto ha senso.
    index: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Target:
    """Dove andare a prendere davvero i byte di un elemento."""

    url: str
    #: Nome suggerito dalla sorgente. Il nucleo puo' ignorarlo e applicare il
    #: proprio schema di denominazione.
    filename: str
    #: Header aggiuntivi richiesti per quella specifica richiesta (Referer,
    #: token, cookie di sessione...).
    headers: dict[str, str] = field(default_factory=dict)
