# Usare Sluicebox dietro una VPN

🇬🇧 [Read in English](vpn.md)

Sluicebox funziona benissimo su una connessione normale, ed è il comportamento
predefinito: non c'è niente da configurare. Questa pagina serve quando vuoi che
il suo traffico esca da una VPN — una linea condivisa che preferisci non
saturare col tuo indirizzo, una sorgente che limita per indirizzo, o
semplicemente un IP statico che preferisci non mettere davanti a tutto.

Ci sono **due strade**, e non sono equivalenti. Scegli con cognizione.

---

## Il caso base: connessione diretta

Nessuna variabile, nessun container in più. Il traffico esce dalla connessione
dell'host. Puoi verificarlo in qualunque momento:

```bash
docker exec sluicebox python -c "import requests; print(requests.get('https://api.ipify.org').text)"
```

---

## Opzione A — condividere la rete del container VPN

Il container entra nel *network namespace* di quello VPN, esattamente come si
fa di solito con un client BitTorrent. **Tutto** passa dal tunnel, e se il
tunnel cade il traffico si ferma invece di uscire in chiaro: un kill switch,
gratis.

```yaml
services:
  gluetun:
    image: qmcgaw/gluetun
    container_name: gluetun
    cap_add: [NET_ADMIN]
    environment:
      VPN_SERVICE_PROVIDER: tuo-fornitore
      VPN_TYPE: wireguard
      WIREGUARD_PRIVATE_KEY: ${WIREGUARD_PRIVATE_KEY}
      SERVER_COUNTRIES: Switzerland
    ports:
      # L'interfaccia si pubblica QUI, non sul servizio sluicebox: un container
      # che condivide un namespace non ha porte proprie.
      - "8420:8420"

  sluicebox:
    build: .
    network_mode: service:gluetun     # <- è tutto qui
    depends_on: [gluetun]
    environment:
      PUID: "1000"
      PGID: "1000"
    volumes:
      - /srv/downloads:/downloads
      - ./state:/state
```

**La trappola da sapere prima**: un container dentro il namespace di un altro
non può pubblicare porte. La mappatura `8420` va spostata sul container VPN, e
senza saperlo si passa un pomeriggio a chiedersi perché l'interfaccia non
risponde più. Se su quel container VPN ci sono già altri servizi, è nel suo
elenco di porte che va aggiunta la tua.

Tieni la chiave privata in un file `.env` accanto al compose — mai dentro al
compose, che prima o poi finisce in un repository.

---

## Opzione B — usare il proxy HTTP del container VPN

Sluicebox mantiene la propria rete e manda dal proxy della VPN **solo le
richieste in uscita**. L'interfaccia resta raggiungibile in LAN come sempre,
sulla sua porta.

```yaml
services:
  gluetun:
    image: qmcgaw/gluetun
    container_name: gluetun
    cap_add: [NET_ADMIN]
    networks: [vpn_net]
    environment:
      VPN_SERVICE_PROVIDER: tuo-fornitore
      VPN_TYPE: wireguard
      WIREGUARD_PRIVATE_KEY: ${WIREGUARD_PRIVATE_KEY}
      SERVER_COUNTRIES: Switzerland
      HTTPPROXY: "on"
      HTTPPROXY_LISTENING_ADDRESS: ":8888"
      # Senza la sottorete del chiamante elencata qui, il firewall di gluetun
      # rifiuta le connessioni che arrivano da fuori del suo namespace — e il
      # sintomo sembra un timeout di rete, non una regola.
      FIREWALL_OUTBOUND_SUBNETS: 172.31.7.0/24

  sluicebox:
    build: .
    networks: [vpn_net]
    ports:
      - "8420:8420"                   # resta nostra: l'interfaccia sta in LAN
    environment:
      SLUICEBOX_PROXIES: http://gluetun:8888
      PUID: "1000"
      PGID: "1000"
    volumes:
      - /srv/downloads:/downloads
      - ./state:/state

networks:
  vpn_net:
    ipam:
      config:
        - subnet: 172.31.7.0/24       # deve coincidere con FIREWALL_OUTBOUND_SUBNETS
```

Attenzione: questo **non** è un kill switch. Se il proxy diventa
irraggiungibile i trasferimenti falliscono — esito sicuro — ma il container
conserva comunque accesso di rete normale. Dove nulla deve poter uscire fuori
dal tunnel, usa l'opzione A.

---

## Quale scegliere

| | Opzione A (rete condivisa) | Opzione B (proxy) |
|---|---|---|
| Interfaccia in LAN | la porta si sposta sul container VPN | resta dov'è |
| Kill switch | sì, per costruzione | no |
| Più uscite insieme | no | sì |
| Convivenza con una VPN già in uso | ne occupa le porte | non la tocca |

Opzione A se il punto è che nulla debba mai uscire fuori dal tunnel. Opzione B
se vuoi che l'interfaccia resti dov'è, o se ti servono più uscite.

---

## Più uscite, a rotazione

`SLUICEBOX_PROXIES` accetta un elenco separato da virgole. A ogni elemento
viene assegnata un'uscita a turno:

```yaml
      SLUICEBOX_PROXIES: http://vpn-ch:8888,http://vpn-nl:8888,http://vpn-de:8888
```

Un container gluetun per uscita, ognuno col suo `SERVER_COUNTRIES` e la sua
porta proxy. L'interfaccia mostra quante uscite sono configurate.

**Una regola che il programma impone, imparata a caro prezzo**: la risoluzione
del collegamento di un elemento e lo scaricamento dei suoi byte passano sempre
dalla *stessa* uscita. Alcune sorgenti firmano il collegamento legandolo
all'indirizzo che lo ha richiesto, quindi un collegamento ottenuto da un
indirizzo e scaricato da un altro torna indietro come `403` — mentre lo stesso
collegamento, preso dall'indirizzo che lo ha chiesto, funziona senza problemi.
Se vedi download fallire con `403` su una sorgente che elenca gli elementi
tranquillamente, è la prima cosa da controllare.

---

## Verificare

```bash
# L'uscita realmente in uso, dall'interno del container
docker exec sluicebox python - <<'PY'
import os, requests
proxy = (os.environ.get("SLUICEBOX_PROXIES") or "").split(",")[0].strip()
p = {"http": proxy, "https": proxy} if proxy else None
print("diretta:", requests.get("https://api.ipify.org", timeout=15).text)
if p:
    print("proxy  :", requests.get("https://api.ipify.org", proxies=p, timeout=25).text)
PY
```

Due indirizzi diversi significa che funziona. Lo stesso indirizzo due volte
significa che il proxy viene ignorato: controlla `SLUICEBOX_PROXIES` e la
sottorete nel firewall.

Con l'opzione A non c'è niente da confrontare: ogni richiesta esce dal tunnel,
quindi un indirizzo solo è il risultato giusto.

---

## Una precisazione doverosa

Ruotare le uscite distribuisce il carico fra più indirizzi. Non rende anonimo
nulla, e non è un modo per aggirare le condizioni d'uso di una sorgente: una
sorgente che chiede di non scaricare in massa lo sta chiedendo a prescindere
dall'indirizzo che usi.

L'impostazione che davvero ti tiene gradito è la pausa fra un elemento e
l'altro: un paio di secondi (`SLUICEBOX_PACING_MIN_SECONDS` / `_MAX_`) e un
tetto ragionevole di trasferimenti costano quasi nulla in tempo totale, perché
le richieste rifiutate costano comunque un tentativo.
