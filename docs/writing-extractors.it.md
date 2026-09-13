# Scrivere un estrattore

🇬🇧 [Read in English](writing-extractors.md)

Un estrattore risponde a tre domande su un URL: **cosa c'è**, **quali elementi
contiene**, e **dove prendere davvero i byte** di ciascuno.

Non scarica niente e non tocca il disco. Coda, portata, tentativi, ripresa,
denominazione e persistenza sono del nucleo, uguali per tutti: un estrattore
eredita gratis ogni miglioria fatta lì.

## I quattro metodi

```python
from sluice.extractors.base import Context, Extractor
from sluice.models import Item, Source, Target


class MioExtractor(Extractor):
    name = "mio"
    description = "Una riga, mostrata nell'interfaccia"

    @classmethod
    def matches(cls, url: str) -> bool:
        """True se so gestire questo URL. Deve essere veloce: niente rete."""
        return "esempio.test" in url

    def inspect(self, url: str, ctx: Context) -> Source:
        """Cosa c'è, senza scaricare gli elementi."""
        dati = ctx.session.get(f"{url}/info", timeout=ctx.timeout).json()
        return Source(
            title=dati["titolo"],
            kind="collection",              # oppure "file"
            items_count=dati["quanti"],
            ongoing=dati["ancora_aperta"],  # se può ancora crescere
        )

    def items(self, url: str, ctx: Context) -> list[Item]:
        """Gli elementi, in ordine."""
        dati = ctx.session.get(f"{url}/elenco", timeout=ctx.timeout).json()
        return [
            Item(key=voce["id"], title=voce["nome"], index=numero)
            for numero, voce in enumerate(dati["voci"], start=1)
        ]

    def resolve(self, item: Item, ctx: Context) -> Target:
        """Il collegamento diretto per un elemento."""
        dati = ctx.session.get(f"/link/{item.key}", timeout=ctx.timeout).json()
        return Target(url=dati["url"], filename=dati["nome"],
                      headers={"Referer": "https://esempio.test/"})
```

## Cinque cose da sapere

**`key` deve essere stabile.** È l'identificatore con cui un elemento viene
ritrovato dopo un riavvio, quindi non può dipendere dalla posizione in elenco:
se la sorgente inserisce qualcosa in mezzo, tutto il resto slitta e il
programma riscarica file già presenti.

**`resolve()` viene chiamato a ogni tentativo**, non una volta sola. I
collegamenti a scadenza vanno quindi *generati* lì, mai memorizzati: al terzo
tentativo, mezz'ora dopo, un collegamento salvato sarebbe già scaduto.

**Usa sempre `ctx.session`.** Alcune sorgenti firmano il collegamento finale
legandolo all'indirizzo che lo ha richiesto: risolvere da un posto e scaricare
da un altro fa fallire il trasferimento con un errore che sembra
inspiegabile. La sessione che ricevi è la stessa usata per lo scaricamento, e
porta con sé l'eventuale proxy assegnato a quell'elemento.

**Dichiara `ongoing` con onestà.** Se è `False`, il nucleo smette di
ricontrollare la sorgente quando non resta nulla, invece di interrogarla per
sempre. Se la sorgente espone un proprio stato (conclusa / in corso), usalo: è
più affidabile di qualunque euristica sul titolo.

**Lascia passare le eccezioni.** Non serve gestire tentativi o attese: ci pensa
il nucleo, con attesa crescente, mostrando un messaggio compatto
nell'interfaccia e tenendo il dettaglio nel registro.

## Portarsi dietro licenza e attribuzione

`Target.metadata` viaggia con l'elemento e finisce nello stato del lavoro.
Usalo per ciò che non deve andare perso — quasi tutte le licenze libere
richiedono di citare l'autore:

```python
return Target(url=info["url"], filename=item.title,
              metadata={"licence": "CC BY-SA 4.0", "author": "Un Fotografo"})
```

## Distribuzione

Un estrattore vive in un pacchetto suo e si dichiara come entry point:

```toml
# pyproject.toml del pacchetto dell'estrattore
[project.entry-points."sluice.extractors"]
mio = "mio_pacchetto.extractor:MioExtractor"
```

Installato il pacchetto, Sluice lo carica all'avvio. Gli estrattori registrati
hanno precedenza su quelli inclusi, così si può sostituire un comportamento
predefinito senza modificare il nucleo. Un estrattore che non si carica viene
saltato con un errore nel registro: non impedisce mai l'avvio.

## Prova

```python
def test_elenco():
    class SessioneFinta:
        def get(self, url, **kwargs):
            return FakeResponse({"titolo": "Prova", "quanti": 2})

    ctx = Context(session=SessioneFinta())
    elementi = MioExtractor().items("https://esempio.test/x", ctx)
    assert [e.index for e in elementi] == [1, 2]
```

Gli estrattori si provano senza rete e senza disco: sono funzioni da URL a
dati. Vedi `tests/test_extractors.py` per esempi completi su quelli inclusi.
