"""Interfaccia che ogni estrattore deve implementare."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import requests

    from sluice.models import Item, Source, Target


@dataclass
class Context:
    """Quello che il nucleo mette a disposizione di un estrattore.

    La `session` e' la stessa per l'ispezione e per lo scaricamento di un
    elemento, e non e' un dettaglio: alcune sorgenti firmano il collegamento
    finale legandolo all'indirizzo che lo ha richiesto, quindi risolvere da un
    posto e scaricare da un altro fallisce. Usando sempre la sessione ricevuta
    si eredita gratis l'eventuale proxy e l'identita' di rete corretta.
    """

    session: requests.Session
    #: Timeout consigliato per le richieste, in secondi.
    timeout: int = 30


class Extractor(ABC):
    """Traduce un URL in elementi scaricabili.

    Un estrattore non scarica nulla e non tocca il disco: dice soltanto cosa
    c'e' e dove prenderlo. Coda, ripresa, tentativi, denominazione e limiti
    sono responsabilita' del nucleo, uguali per tutti.
    """

    #: Identificatore breve, usato nella configurazione e nei log.
    name: str = "extractor"
    #: Descrizione di una riga mostrata nell'interfaccia.
    description: str = ""

    @classmethod
    @abstractmethod
    def matches(cls, url: str) -> bool:
        """True se questo estrattore sa gestire l'URL."""

    @abstractmethod
    def inspect(self, url: str, ctx: Context) -> Source:
        """Descrive la sorgente senza scaricare gli elementi."""

    @abstractmethod
    def items(self, url: str, ctx: Context) -> list[Item]:
        """Elenca gli elementi disponibili, in ordine."""

    @abstractmethod
    def resolve(self, item: Item, ctx: Context) -> Target:
        """Restituisce il collegamento diretto per un singolo elemento.

        Viene chiamato appena prima dello scaricamento, e di nuovo a ogni
        nuovo tentativo: i collegamenti a scadenza vanno quindi rigenerati
        qui, non memorizzati.
        """
