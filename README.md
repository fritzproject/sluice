# Sluice

Gestore di download a moduli. Il nucleo si occupa di **coda, portata regolabile,
tentativi, ripresa dei trasferimenti interrotti, denominazione dei file e
ricontrollo periodico delle sorgenti**. Cosa ci sia dietro un URL lo dicono gli
**estrattori**, moduli indipendenti che il nucleo non conosce singolarmente.

Una chiusa è un canale con una paratoia che regola il flusso: si apre di più
quando la banda lo permette, si stringe quando serve andare piano. È esattamente
quello che fa questo programma.

---

## Perché

Scaricare un file è banale. Scaricarne cinquecento senza perdere pezzi molto meno:

- il programma si riavvia a metà e i file incompleti restano lì, morti
- un lavoro viene dato per "completato" mentre ha ancora elementi in sospeso, e
  nessuno se ne accorge più
- si scarica tutto insieme finché la sorgente comincia a rifiutare le richieste
- una raccolta di un solo elemento occupa un posto e ne lascia fermi altri quattro
- gli elementi nuovi di una raccolta che cresce vanno cercati a mano ogni volta

Sluice nasce da questi problemi, incontrati uno per uno. Le soluzioni sono nel
nucleo, quindi valgono per qualunque estrattore, presente o futuro.

---

## Caratteristiche

| | |
|---|---|
| **Ripresa** | i trasferimenti interrotti ripartono dal punto esatto (richieste `Range`), con ricaduta automatica su un nuovo tentativo se il server non le accetta |
| **Portata regolabile a caldo** | trasferimenti simultanei e sorgenti in parallelo si cambiano mentre il lavoro è in corso, senza riavviare |
| **Stato onesto** | un lavoro con elementi in sospeso risulta `interrupted`, mai `done`: quello che manca resta visibile e recuperabile |
| **Coda persistente** | riavvii e aggiornamenti non perdono niente, e alla ripartenza vengono riaccodati solo gli elementi mancanti |
| **Recupero** | tentativi con attesa crescente, ripresa per singolo lavoro o per tutti in una volta |
| **Sorveglianza** | le raccolte che possono crescere vengono ricontrollate, e i nuovi elementi si accodano da soli |
| **Denominazione** | schemi con segnaposto, compresa la forma riconosciuta dai server multimediali |
| **File `.part`** | il nome definitivo compare solo a trasferimento concluso: nessuno importa mai un file a metà |
| **Uscite multiple** | proxy usati a rotazione; risoluzione e scaricamento di uno stesso elemento passano sempre dalla stessa uscita |

Interfaccia web, API HTTP e riga di comando.

---

## Installazione

```bash
pip install -e ".[web]"
```

Oppure con Docker:

```bash
cp docker-compose.example.yml docker-compose.yml
docker compose up -d --build
```

## Uso

```bash
sluice inspect https://esempio.test/feed.xml     # cosa c'è, senza scaricare
sluice get https://esempio.test/feed.xml -o ~/Download
sluice get https://esempio.test/feed.xml --watch # e prendi anche i futuri
sluice serve --port 8420                         # interfaccia web e API
sluice extractors                                # moduli disponibili
```

## Estrattori inclusi

| Nome | Cosa gestisce |
|---|---|
| `direct` | un collegamento HTTP(S) a un file |
| `rss` | feed RSS/Atom con allegati (podcast, videocast) |
| `archive_org` | elementi di Internet Archive |

Ne servono altri? Sono **quattro metodi**: vedi
[docs/writing-extractors.md](docs/writing-extractors.md). Un estrattore si
installa come pacchetto separato, senza toccare il nucleo.

---

## Configurazione

Tutto via ambiente, con prefisso `SLUICE_`; i valori di portata si cambiano poi
dall'interfaccia e vengono salvati.

| Variabile | Predefinito | |
|---|---|---|
| `SLUICE_DOWNLOAD_ROOT` | `./downloads` | dove finiscono i file |
| `SLUICE_STATE_DIR` | `./state` | coda e registro |
| `SLUICE_CONCURRENT_TRANSFERS` | `4` | trasferimenti simultanei totali |
| `SLUICE_PARALLEL_SOURCES` | `3` | quante sorgenti lavorare insieme |
| `SLUICE_PACING_MIN_SECONDS` / `_MAX_` | `0` | pausa casuale fra un elemento e l'altro |
| `SLUICE_MAX_RETRIES` | `4` | tentativi prima di arrendersi |
| `SLUICE_RECHECK_INTERVAL_SECONDS` | `21600` | ogni quanto ricontrollare le sorgenti aperte |
| `SLUICE_PROXIES` | — | uscite separate da virgola, usate a rotazione |

## API

| | |
|---|---|
| `POST /api/inspect` | `{url}` → cosa c'è, senza scaricare |
| `POST /api/jobs` | `{url, items?, layout?, watch?}` → accoda |
| `GET /api/jobs` | stato di tutto, più il riepilogo |
| `POST /api/jobs/<id>/retry` | riprende quello che manca in un lavoro |
| `POST /api/retry-all` | riprende quello che manca ovunque |
| `GET·POST /api/watches`, `DELETE /api/watches/<id>` | sorgenti sorvegliate |
| `POST /api/watches/check` | controlla subito, senza aspettare il giro |
| `GET·POST /api/settings` | portata e comportamento, a caldo |

## Sviluppo

```bash
pip install -e ".[web,dev]"
pytest
ruff check .
```

## Licenza

MIT — vedi [LICENSE](LICENSE).

Gli estrattori distribuiti separatamente hanno licenza propria, e ciascuno
risponde della sorgente che tratta: il nucleo non ne include e non ne promuove
nessuno in particolare.
