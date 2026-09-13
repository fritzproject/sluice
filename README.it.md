# Sluice

**Gestore di download a moduli.** Il nucleo si occupa di coda, portata
regolabile, tentativi, ripresa dei trasferimenti interrotti, denominazione dei
file e ricontrollo delle sorgenti che crescono. Cosa ci sia dietro un URL lo
dicono gli **estrattori**, moduli indipendenti che il nucleo non conosce
singolarmente.

🇬🇧 [Read in English](README.md) · 📦 [Guida all'installazione](docs/install.it.md) ·
🧩 [Scrivere un estrattore](docs/writing-extractors.it.md)

Una chiusa è un canale con una paratoia che regola il flusso: si apre di più
quando c'è spazio, si stringe quando serve andare piano. L'idea è tutta lì.

---

## Perché

Scaricare un file è banale. Scaricarne cinquecento senza perderne nessuno no:

- il programma si riavvia a metà e i file incompleti restano lì, morti
- un lavoro risulta "completato" mentre ha ancora elementi in sospeso, e
  nessuno se ne accorge più
- si scarica tutto insieme finché la sorgente comincia a rifiutare le richieste
- una raccolta con un solo elemento occupa un posto e lascia fermi gli altri
- gli elementi nuovi di una raccolta che cresce vanno cercati a mano ogni volta

Sluice nasce da questi cinque problemi, incontrati uno per uno. Le soluzioni
stanno nel nucleo, quindi valgono per ogni estrattore — compreso il tuo.

---

## Cosa fa

| | |
|---|---|
| **Ripresa** | i trasferimenti interrotti ripartono dal byte esatto (`Range` HTTP), con ricaduta su un riavvio pulito se il server la rifiuta |
| **Portata regolabile a caldo** | trasferimenti simultanei e sorgenti in parallelo si cambiano mentre il lavoro è in corso |
| **Stato onesto** | un lavoro con elementi in sospeso risulta `interrupted`, mai `done`: ciò che manca resta visibile e recuperabile |
| **Coda persistente** | riavvii e aggiornamenti non perdono niente, e si riaccodano solo gli elementi mancanti |
| **Recupero** | tentativi con attesa crescente, per singolo lavoro o per tutti insieme |
| **Sorveglianza** | le raccolte che possono crescere vengono ricontrollate, e i nuovi elementi si accodano da soli |
| **Denominazione** | schemi con segnaposto, compresa la forma riconosciuta dai server multimediali |
| **File `.part`** | il nome definitivo compare solo a trasferimento concluso: nessuno importa mai un file a metà |
| **Uscite multiple** | proxy a rotazione; risoluzione e scaricamento di uno stesso elemento passano sempre dalla stessa uscita |

Interfaccia web, API HTTP e riga di comando.

---

## Per iniziare

```bash
pip install -e ".[web]"
sluice serve --port 8420        # poi apri http://localhost:8420
```

Con Docker — volumi, permessi e reverse proxy nella
[guida all'installazione](docs/install.it.md):

```bash
cp docker-compose.example.yml docker-compose.yml
docker compose up -d --build
```

---

## Esempi

Sorgenti reali e lecite, da provare subito.

**Un libro di pubblico dominio, in tutti i formati pubblicati**

```bash
sluice get https://www.gutenberg.org/ebooks/2009 -o ~/Libri
```

Project Gutenberg pubblica opere il cui diritto d'autore è scaduto. Sluice
scarica le versioni EPUB, HTML e testo, saltando copertine e file di servizio.

**Un'intera categoria di Wikimedia Commons**

```bash
sluice inspect https://commons.wikimedia.org/wiki/Category:Lighthouses_in_Italy
sluice get https://commons.wikimedia.org/wiki/Category:Lighthouses_in_Italy -o ~/Immagini
```

Su Commons è tutto di pubblico dominio o con licenza libera. Le categorie
contengono migliaia di file e vengono sfogliate automaticamente. Ogni file
porta con sé licenza e autore — libero non vuol dire senza condizioni, e
l'attribuzione è quasi sempre richiesta.

**Un podcast, arretrati compresi e tutto quello che uscirà poi**

```bash
sluice get https://feeds.example.org/show.xml --watch -o ~/Podcast
```

`--watch` tiene il feed sotto osservazione: le puntate nuove si accodano da
sole, e gli arretrati arrivano dal più vecchio, così la numerazione cresce col
tempo.

**Una registrazione di concerto da Internet Archive**

```bash
sluice get https://archive.org/details/gd1977-05-08.sbd.hicks.4982.sbeok.shnf -o ~/Musica
```

Internet Archive raccoglie registrazioni dal vivo autorizzate, libri di
pubblico dominio, software e archivi radiofonici — un singolo elemento può
contenere centinaia di file.

**Un file secco**

```bash
sluice get https://esempio.org/dataset.zip -o ~/Download
```

---

## Estrattori inclusi

| Nome | Cosa gestisce |
|---|---|
| `gutenberg` | Project Gutenberg — libri di pubblico dominio |
| `wikimedia` | Wikimedia Commons — file e categorie con licenza libera |
| `archive_org` | elementi di Internet Archive |
| `rss` | feed RSS/Atom con allegati (podcast, videocast) |
| `direct` | un collegamento HTTP(S) a un file |

## Componenti aggiuntivi

Gli estrattori per altre sorgenti si installano come normali pacchetti Python.
Non c'è nessun passaggio di configurazione: Sluice li scopre da solo all'avvio
tramite il loro entry point.

```bash
pip install ./examples/sluice-extractor-nasa
sluice extractors
#   nasa           NASA Image and Video Library (public domain)
#   archive_org    Internet Archive items
#   …
```

Per rimuoverne uno basta `pip uninstall`. Un estrattore registrato ha
precedenza su quelli inclusi, quindi si può sostituire un comportamento
predefinito senza dover forkare il progetto.

[`examples/sluice-extractor-nasa`](examples/sluice-extractor-nasa) è un
componente completo e funzionante in un centinaio di righe: copialo come punto
di partenza. La guida completa è
[docs/writing-extractors.it.md](docs/writing-extractors.it.md) — un estrattore
sono **quattro metodi**, e il nucleo non si tocca.

---

## Configurazione

Tutto via ambiente, con prefisso `SLUICE_`. I valori di portata sono solo il
punto di partenza: poi si regolano dall'interfaccia e vengono salvati.

| Variabile | Predefinito | |
|---|---|---|
| `SLUICE_DOWNLOAD_ROOT` | `./downloads` | dove finiscono i file |
| `SLUICE_STATE_DIR` | `./state` | coda e registro |
| `SLUICE_CONCURRENT_TRANSFERS` | `4` | trasferimenti simultanei totali |
| `SLUICE_PARALLEL_SOURCES` | `3` | quante sorgenti lavorare insieme |
| `SLUICE_PACING_MIN_SECONDS` / `_MAX_` | `0` | pausa casuale fra un elemento e l'altro |
| `SLUICE_MAX_RETRIES` | `4` | tentativi prima di arrendersi |
| `SLUICE_RECHECK_INTERVAL_SECONDS` | `21600` | ogni quanto ricontrollare le sorgenti sorvegliate |
| `SLUICE_PROXIES` | — | uscite separate da virgola, usate a rotazione |

## API

| | |
|---|---|
| `POST /api/inspect` | `{url}` → cosa c'è, senza scaricare |
| `POST /api/jobs` | `{url, items?, layout?, watch?}` → accoda |
| `GET /api/jobs` | tutto, più il riepilogo |
| `POST /api/jobs/<id>/retry` | recupera ciò che manca in un lavoro |
| `POST /api/retry-all` | recupera ciò che manca ovunque |
| `GET·POST /api/watches`, `DELETE /api/watches/<id>` | sorgenti sorvegliate |
| `POST /api/watches/check` | controlla subito, senza aspettare il giro |
| `GET·POST /api/settings` | portata e comportamento, a caldo |

## Sviluppo

```bash
pip install -e ".[web,dev]"
pytest          # 32 test, nessuno richiede la rete
ruff check .
```

## Licenza

MIT — vedi [LICENSE](LICENSE).

Gli estrattori distribuiti separatamente hanno licenza propria, e ciascuno
risponde della sorgente che tratta. Sluice non ne include nessuno per sorgenti
i cui contenuti non siano liberamente disponibili, e non ne promuove alcuno.
