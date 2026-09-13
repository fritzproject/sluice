# Installing Sluicebox

🇮🇹 [Leggi in italiano](install.it.md)

Three ways to run it, from simplest to most permanent. Whichever you pick, read
the **[Folders and permissions](#folders-and-permissions)** section: it is the
single most common cause of "it downloads fine but nothing else can touch the
files".

---

## 1. Locally, with Python

Requires Python 3.10 or newer.

```bash
git clone https://github.com/fritzproject/sluice.git
cd sluice
python -m venv .venv && source .venv/bin/activate
pip install -e ".[web]"
```

Check it works:

```bash
sluicebox extractors
sluicebox inspect https://www.gutenberg.org/ebooks/2009
sluicebox serve --port 8420
```

By default files land in `./downloads` and the queue in `./state`, both
relative to where you launched it. Override with `-o` and `--state`, or with
the environment variables below.

---

## 2. Docker, single container

```bash
cp docker-compose.example.yml docker-compose.yml
```

Edit the two volume lines and the UID/GID, then:

```bash
docker compose up -d --build
docker compose logs -f
```

The interface is on `http://<host>:8420`.

### The compose file, line by line

```yaml
services:
  sluicebox:
    build: .                       # or image: ghcr.io/... once published
    container_name: sluicebox
    restart: unless-stopped
    ports:
      - "8420:8420"                # host:container
    environment:
      TZ: Europe/Rome
      PUID: "1000"                 # see "Folders and permissions"
      PGID: "1000"
      SLUICEBOX_CONCURRENT_TRANSFERS: "4"
      SLUICEBOX_PARALLEL_SOURCES: "3"
    volumes:
      - /srv/downloads:/downloads  # where the files go
      - ./state:/state             # queue, settings, log
```

Two volumes, and both matter:

- **`/downloads`** is the only path that needs to be shared with anything else
  (a media server, a file manager, a backup job).
- **`/state`** holds the queue, the saved settings and the watched sources.
  Lose it and you lose the queue — not the downloaded files, but everything
  that was pending. Keep it on persistent storage, never in a tmpfs.

### Building the image yourself

The `Dockerfile` in the repository takes two build arguments so the process
inside the container runs as **your** user rather than root:

```bash
docker build --build-arg UID=$(id -u) --build-arg GID=$(id -g) -t sluicebox .
```

With compose:

```yaml
    build:
      context: .
      args:
        UID: "1000"
        GID: "1000"
```

---

## 3. Behind a reverse proxy

Sluicebox speaks plain HTTP and has **no authentication of its own**. Anything
that can reach port 8420 can queue downloads and change settings. Do not
expose it to the internet directly: put it behind a proxy that handles TLS and
authentication.

**Caddy**

```caddyfile
sluice.example.org {
    basic_auth {
        someone $2a$14$...        # caddy hash-password
    }
    reverse_proxy localhost:8420
}
```

**nginx**

```nginx
location / {
    auth_basic           "Sluicebox";
    auth_basic_user_file /etc/nginx/.htpasswd;
    proxy_pass           http://127.0.0.1:8420;
    proxy_set_header     Host $host;
    proxy_set_header     X-Forwarded-For $proxy_add_x_forwarded_for;
    # Transfers can be long: do not cut them short.
    proxy_read_timeout   3600s;
}
```

If you only need it on your own machine, bind the port to loopback instead —
`"127.0.0.1:8420:8420"` in compose — and skip the proxy entirely.

---

## Folders and permissions

This is where most setups go wrong, and the failure is confusing: downloads
succeed, then another program cannot move, import or delete the files.

**The rule:** the container must write files owned by a user that the *other*
programs can also write as. Not root.

### Find the right UID and GID

```bash
id                                  # your own user
docker exec <other-container> id    # e.g. your media server
ls -ln /srv/downloads               # numeric owner of the target folder
```

Use those numbers for `PUID`/`PGID`. If several programs share the folder, what
matters is that they share a **group**, and that the folder is group-writable.

### Prepare the destination folder

```bash
sudo mkdir -p /srv/downloads
sudo chown -R 1000:1000 /srv/downloads
sudo chmod -R 775 /srv/downloads
```

`775` rather than `755` on purpose: with `755` only the owner can create files,
so a second program running under a different user but the same group would be
refused.

### The trap worth knowing about

If Sluicebox ever ran as root and created the destination folder itself, that
folder now belongs to root — and switching to a normal user afterwards is not
enough, because creating a file inside a folder requires write permission **on
the folder**, not on its parent. Symptom: existing collections keep working
while every new one fails with `Permission denied`.

Fix the ownership of what is already there, once:

```bash
sudo chown -R 1000:1000 /srv/downloads
```

### Checking

```bash
docker exec sluicebox id
docker exec sluicebox touch /downloads/write-test && echo OK
docker exec sluicebox rm /downloads/write-test
ls -ln /srv/downloads               # owner must match the other programs
```

---

## Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `SLUICEBOX_DOWNLOAD_ROOT` | `./downloads` | where files land |
| `SLUICEBOX_STATE_DIR` | `./state` | queue, settings, log |
| `SLUICEBOX_CONCURRENT_TRANSFERS` | `4` | total simultaneous transfers |
| `SLUICEBOX_PARALLEL_SOURCES` | `3` | how many sources at once |
| `SLUICEBOX_PACING_MIN_SECONDS` | `0` | minimum random pause between items |
| `SLUICEBOX_PACING_MAX_SECONDS` | `0` | maximum random pause |
| `SLUICEBOX_MAX_RETRIES` | `4` | attempts before an item is marked failed |
| `SLUICEBOX_RECHECK_INTERVAL_SECONDS` | `21600` | how often watched sources are re-checked |
| `SLUICEBOX_TIMEOUT` | `30` | per-request timeout, seconds |
| `SLUICEBOX_PROXIES` | — | comma-separated exits, used in rotation |
| `SLUICEBOX_USER_AGENT` | `Sluicebox/0.2 …` | how Sluicebox identifies itself |

The four throughput values are only **starting points**: change them from the
interface and they are saved to `/state`, taking precedence from then on.

### About `SLUICEBOX_PROXIES`

Each item is assigned one exit in rotation, and both resolving the link and
downloading the bytes go through **that same exit**. This is deliberate: some
sources sign the download link against the address that requested it, so
splitting the two gets the transfer rejected with a misleading error.

Two ways to set this up with gluetun, with the trade-offs spelled out:
[running behind a VPN](vpn.md).

Rotation spreads load across exits. It does not make anything anonymous, and it
is not a way around a source's terms of use.

---

## Upgrading

```bash
git pull
docker compose up -d --build
```

The queue survives: it lives in `/state`, is written atomically, and on
startup any job with unfinished items is resumed — re-queueing **only** the
missing ones. Interrupted transfers continue from where they stopped rather
than starting over.

---

## Troubleshooting

**`no extractor can handle this URL`** — no installed extractor recognises it.
Check `sluicebox extractors`; `direct` only accepts `http`/`https`.

**Everything fails with HTTP 429 or 503** — you are asking too fast. Lower
*simultaneous transfers* and set a pause (`SLUICEBOX_PACING_MIN_SECONDS` 2,
`_MAX_` 7). The polite settings are almost always faster overall, because
refused requests cost retries.

**A job says `interrupted`** — some items never finished, usually because of a
restart. Press *Retry* on the job, or *Retry everything* in the top bar; the
partial files resume rather than restart.

**Files are owned by root** — see [Folders and permissions](#folders-and-permissions).

**The queue disappeared after a restart** — `/state` was not on a persistent
volume. The downloaded files are fine; the pending queue is not recoverable.
