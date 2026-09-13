# Installare Sluice

🇬🇧 [Read in English](install.md)

Tre modi per usarlo, dal più semplice al più stabile. Qualunque scegli, leggi la
sezione **[Cartelle e permessi](#cartelle-e-permessi)**: è di gran lunga la
causa più frequente del classico "scarica benissimo ma poi nessun altro
programma riesce a toccare i file".

---

## 1. In locale, con Python

Serve Python 3.10 o successivo.

```bash
git clone https://github.com/fritzproject/sluice.git
cd sluice
python -m venv .venv && source .venv/bin/activate
pip install -e ".[web]"
```

Prova che funzioni:

```bash
sluice extractors
sluice inspect https://www.gutenberg.org/ebooks/2009
sluice serve --port 8420
```

Di base i file finiscono in `./downloads` e la coda in `./state`, entrambi
relativi alla cartella da cui l'hai lanciato. Si cambiano con `-o` e `--state`,
oppure con le variabili d'ambiente più sotto.

---

## 2. Docker, container singolo

```bash
cp docker-compose.example.yml docker-compose.yml
```

Modifica le due righe dei volumi e UID/GID, poi:

```bash
docker compose up -d --build
docker compose logs -f
```

L'interfaccia è su `http://<host>:8420`.

### Il compose, riga per riga

```yaml
services:
  sluice:
    build: .                       # oppure image: ghcr.io/... una volta pubblicata
    container_name: sluice
    restart: unless-stopped
    ports:
      - "8420:8420"                # host:container
    environment:
      TZ: Europe/Rome
      PUID: "1000"                 # vedi "Cartelle e permessi"
      PGID: "1000"
      SLUICE_CONCURRENT_TRANSFERS: "4"
      SLUICE_PARALLEL_SOURCES: "3"
    volumes:
      - /srv/downloads:/downloads  # dove finiscono i file
      - ./state:/state             # coda, impostazioni, registro
```

Due volumi, ed entrambi contano:

- **`/downloads`** è l'unico percorso che deve essere condiviso con altro (un
  server multimediale, un gestore file, un backup).
- **`/state`** contiene coda, impostazioni salvate e sorgenti sorvegliate.
  Perderlo significa perdere la coda — non i file già scaricati, ma tutto
  quello che era in sospeso. Tienilo su spazio persistente, mai in tmpfs.

### Costruire l'immagine

Il `Dockerfile` accetta due argomenti di build, così il processo dentro al
container gira come **il tuo** utente invece che come root:

```bash
docker build --build-arg UID=$(id -u) --build-arg GID=$(id -g) -t sluice .
```

Con compose:

```yaml
    build:
      context: .
      args:
        UID: "1000"
        GID: "1000"
```

---

## 3. Dietro un reverse proxy

Sluice parla HTTP in chiaro e **non ha alcuna autenticazione propria**:
chiunque raggiunga la porta 8420 può accodare download e cambiare le
impostazioni. Non esporlo direttamente su internet — mettilo dietro un proxy
che si occupi di TLS e autenticazione.

**Caddy**

```caddyfile
sluice.esempio.org {
    basic_auth {
        tizio $2a$14$...          # caddy hash-password
    }
    reverse_proxy localhost:8420
}
```

**nginx**

```nginx
location / {
    auth_basic           "Sluice";
    auth_basic_user_file /etc/nginx/.htpasswd;
    proxy_pass           http://127.0.0.1:8420;
    proxy_set_header     Host $host;
    proxy_set_header     X-Forwarded-For $proxy_add_x_forwarded_for;
    # I trasferimenti possono essere lunghi: non troncarli.
    proxy_read_timeout   3600s;
}
```

Se ti serve solo sulla tua macchina, lega la porta a loopback —
`"127.0.0.1:8420:8420"` nel compose — e salta del tutto il proxy.

---

## Cartelle e permessi

È qui che si sbaglia più spesso, e il sintomo è fuorviante: i download
riescono, ma un altro programma non riesce a spostare, importare o cancellare
i file.

**La regola:** il container deve scrivere file appartenenti a un utente con cui
anche *gli altri* programmi possano scrivere. Non root.

### Trovare UID e GID giusti

```bash
id                                  # il tuo utente
docker exec <altro-container> id    # es. il tuo server multimediale
ls -ln /srv/downloads               # proprietario numerico della cartella
```

Usa quei numeri per `PUID`/`PGID`. Se più programmi condividono la cartella,
ciò che conta è che condividano un **gruppo** e che la cartella sia
scrivibile dal gruppo.

### Preparare la cartella di destinazione

```bash
sudo mkdir -p /srv/downloads
sudo chown -R 1000:1000 /srv/downloads
sudo chmod -R 775 /srv/downloads
```

`775` e non `755`, di proposito: con `755` solo il proprietario può creare
file, quindi un secondo programma con utente diverso ma stesso gruppo verrebbe
respinto.

### La trappola da conoscere

Se Sluice ha girato anche una sola volta come root e ha creato lui la cartella
di destinazione, quella cartella ora appartiene a root — e passare dopo a un
utente normale **non basta**, perché creare un file dentro una cartella
richiede il permesso di scrittura **sulla cartella**, non sul suo genitore. Il
sintomo è caratteristico: le raccolte già esistenti continuano a funzionare,
mentre ogni raccolta nuova fallisce con `Permission denied`.

Si sistema una volta sola:

```bash
sudo chown -R 1000:1000 /srv/downloads
```

### Verifica

```bash
docker exec sluice id
docker exec sluice touch /downloads/prova && echo OK
docker exec sluice rm /downloads/prova
ls -ln /srv/downloads               # il proprietario deve coincidere con gli altri programmi
```

---

## Variabili d'ambiente

| Variabile | Predefinito | Significato |
|---|---|---|
| `SLUICE_DOWNLOAD_ROOT` | `./downloads` | dove finiscono i file |
| `SLUICE_STATE_DIR` | `./state` | coda, impostazioni, registro |
| `SLUICE_CONCURRENT_TRANSFERS` | `4` | trasferimenti simultanei totali |
| `SLUICE_PARALLEL_SOURCES` | `3` | quante sorgenti insieme |
| `SLUICE_PACING_MIN_SECONDS` | `0` | pausa casuale minima fra elementi |
| `SLUICE_PACING_MAX_SECONDS` | `0` | pausa casuale massima |
| `SLUICE_MAX_RETRIES` | `4` | tentativi prima di dare un elemento per fallito |
| `SLUICE_RECHECK_INTERVAL_SECONDS` | `21600` | ogni quanto ricontrollare le sorgenti sorvegliate |
| `SLUICE_TIMEOUT` | `30` | timeout per richiesta, in secondi |
| `SLUICE_PROXIES` | — | uscite separate da virgola, usate a rotazione |
| `SLUICE_USER_AGENT` | `Sluice/0.2 …` | come Sluice si presenta |

I quattro valori di portata sono solo il **punto di partenza**: cambiandoli
dall'interfaccia vengono salvati in `/state` e da lì in poi hanno la
precedenza.

### Su `SLUICE_PROXIES`

A ogni elemento viene assegnata un'uscita a rotazione, e sia la risoluzione del
collegamento sia lo scaricamento dei byte passano da **quella stessa uscita**.
È voluto: alcune sorgenti firmano il collegamento legandolo all'indirizzo che
lo ha richiesto, quindi separare le due fasi fa rifiutare il trasferimento con
un errore che sembra inspiegabile.

La rotazione distribuisce il carico fra le uscite. Non rende anonimo nulla, e
non è un modo per aggirare le condizioni d'uso di una sorgente.

---

## Aggiornare

```bash
git pull
docker compose up -d --build
```

La coda sopravvive: vive in `/state`, viene scritta in modo atomico, e
all'avvio ogni lavoro con elementi non conclusi viene ripreso riaccodando
**solo** quelli mancanti. I trasferimenti interrotti proseguono dal punto in
cui si erano fermati invece di ricominciare.

---

## Se qualcosa non va

**`no extractor can handle this URL`** — nessun estrattore installato riconosce
quell'indirizzo. Controlla `sluice extractors`; `direct` accetta solo
`http`/`https`.

**Tutto fallisce con HTTP 429 o 503** — stai chiedendo troppo in fretta.
Abbassa i *trasferimenti simultanei* e imposta una pausa
(`SLUICE_PACING_MIN_SECONDS` 2, `_MAX_` 7). Le impostazioni prudenti sono quasi
sempre più veloci in totale, perché ogni richiesta rifiutata costa un tentativo.

**Un lavoro risulta `interrupted`** — alcuni elementi non sono mai arrivati in
fondo, di solito per un riavvio. Premi *Riprendi* sul lavoro, o *Riprendi tutto*
nella barra in alto: i file parziali riprendono invece di ricominciare.

**I file appartengono a root** — vedi [Cartelle e permessi](#cartelle-e-permessi).

**La coda è sparita dopo un riavvio** — `/state` non era su un volume
persistente. I file scaricati ci sono ancora; la coda in sospeso no.
