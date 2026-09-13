# Sluicebox

**A pluggable download manager.** The core handles the queue, adjustable
throughput, retries, resuming interrupted transfers, file naming and
re-checking sources that grow. What sits behind a URL is the job of
**extractors** — independent modules the core knows nothing about in
particular.

🇮🇹 [Leggi in italiano](README.it.md) · 📦 [Install guide](docs/install.md) ·
🧩 [Write an extractor](docs/writing-extractors.md)

A sluice box is the channel prospectors run material through: a gate regulates
the flow, and what you actually want is caught on the way. Open it wider when
there is room, narrow it when things need to go slowly. That is the whole idea.

---

## Why

Downloading one file is trivial. Downloading five hundred without losing any
is not:

- the program restarts half-way and the incomplete files sit there, dead
- a job is reported "complete" while items are still pending, and nobody
  ever notices
- everything downloads at once until the source starts refusing requests
- a collection holding a single item takes one slot and leaves the rest idle
- new items in a growing collection have to be hunted down by hand every time

Sluicebox exists because of those five problems, met one at a time. The fixes
live in the core, so they apply to every extractor — including yours.

---

## What it does

| | |
|---|---|
| **Resume** | interrupted transfers restart from the exact byte (HTTP `Range`), falling back to a clean restart if the server refuses |
| **Live throughput control** | simultaneous transfers and parallel sources change while work is running, no restart |
| **Honest status** | a job with pending items reads `interrupted`, never `done`: what is missing stays visible and recoverable |
| **Durable queue** | restarts and upgrades lose nothing, and only missing items are re-queued |
| **Recovery** | retries with growing back-off, per job or everything at once |
| **Watching** | collections that can grow are re-checked, and new items queue themselves |
| **Naming** | placeholder templates, including the form media servers recognise |
| **`.part` files** | the final name appears only when the transfer completes, so nothing ever imports a half-written file |
| **Multiple exits** | proxies used in rotation; resolving and downloading one item always share the same exit |

Web interface, HTTP API and CLI.

---

## Quick start

```bash
pip install -e ".[web]"
sluicebox serve --port 8420        # then open http://localhost:8420
```

With Docker — see the [install guide](docs/install.md) for volumes,
permissions and reverse proxies:

```bash
cp docker-compose.example.yml docker-compose.yml
docker compose up -d --build
```

---

## Examples

Real, lawful sources you can try right now.

**A public domain book, in every format it is published in**

```bash
sluicebox get https://www.gutenberg.org/ebooks/2009 -o ~/Books
```

Project Gutenberg publishes works whose copyright has expired. Sluicebox fetches
the EPUB, HTML and plain text versions and skips cover art and metadata files.

**An entire Wikimedia Commons category**

```bash
sluicebox inspect https://commons.wikimedia.org/wiki/Category:Lighthouses_in_Italy
sluicebox get https://commons.wikimedia.org/wiki/Category:Lighthouses_in_Italy -o ~/Pictures
```

Everything on Commons is public domain or freely licensed. Categories hold
thousands of files and are paged through automatically. Each file carries its
licence and author in the job data — free does not mean condition-free, and
attribution is usually required.

**A podcast, back catalogue and everything published afterwards**

```bash
sluicebox get https://feeds.example.org/show.xml --watch -o ~/Podcasts
```

`--watch` keeps the feed under review: new episodes queue themselves, and the
back catalogue is fetched oldest-first so numbering grows with time.

**A concert recording from Internet Archive**

```bash
sluicebox get https://archive.org/details/gd1977-05-08.sbd.hicks.4982.sbeok.shnf -o ~/Music
```

The Internet Archive holds authorised live recordings, public domain books,
software and radio archives — single items can contain hundreds of files.

**One file, straight**

```bash
sluicebox get https://example.org/dataset.zip -o ~/Downloads
```

---

## Built-in extractors

| Name | Handles |
|---|---|
| `gutenberg` | Project Gutenberg — public domain books |
| `wikimedia` | Wikimedia Commons — freely licensed files and categories |
| `archive_org` | Internet Archive items |
| `rss` | RSS/Atom feeds with enclosures (podcasts, videocasts) |
| `direct` | a plain HTTP(S) link to a file |

## Add-ons

Extractors for other sources install as ordinary Python packages. There is no
configuration step: Sluicebox discovers them at startup through their entry point.

```bash
pip install ./examples/sluicebox-extractor-nasa
sluicebox extractors
#   nasa           NASA Image and Video Library (public domain)
#   archive_org    Internet Archive items
#   …
```

Removing one is `pip uninstall`. A registered extractor takes precedence over
the built-in ones, so a default behaviour can be replaced without forking.

[`examples/sluicebox-extractor-nasa`](examples/sluicebox-extractor-nasa) is a
complete, working add-on in about 90 lines — copy it as a starting point. The
full guide is [docs/writing-extractors.md](docs/writing-extractors.md): an
extractor is **four methods**, and the core is never touched.

---

## Configuration

Everything through the environment, prefixed `SLUICEBOX_`. The throughput values
are only starting points: they are adjustable from the interface afterwards
and saved with the state.

| Variable | Default | |
|---|---|---|
| `SLUICEBOX_DOWNLOAD_ROOT` | `./downloads` | where files land |
| `SLUICEBOX_STATE_DIR` | `./state` | queue and log |
| `SLUICEBOX_CONCURRENT_TRANSFERS` | `4` | total simultaneous transfers |
| `SLUICEBOX_PARALLEL_SOURCES` | `3` | how many sources to work at once |
| `SLUICEBOX_PACING_MIN_SECONDS` / `_MAX_` | `0` | random pause between items |
| `SLUICEBOX_MAX_RETRIES` | `4` | attempts before giving up |
| `SLUICEBOX_RECHECK_INTERVAL_SECONDS` | `21600` | how often watched sources are re-checked |
| `SLUICEBOX_PROXIES` | — | comma-separated exits, used in rotation |

## API

| | |
|---|---|
| `POST /api/inspect` | `{url}` → what is there, without downloading |
| `POST /api/jobs` | `{url, items?, layout?, watch?}` → queue it |
| `GET /api/jobs` | everything, plus the summary |
| `POST /api/jobs/<id>/retry` | recover what is missing in one job |
| `POST /api/retry-all` | recover what is missing everywhere |
| `GET·POST /api/watches`, `DELETE /api/watches/<id>` | watched sources |
| `POST /api/watches/check` | check now, without waiting for the timer |
| `GET·POST /api/settings` | throughput and behaviour, live |

## Development

```bash
pip install -e ".[web,dev]"
pytest          # 32 tests, no network required
ruff check .
```

## Licence

MIT — see [LICENSE](LICENSE).

Extractors distributed separately carry their own licence, and each is
responsible for the source it handles. Sluicebox ships none for sources whose
content is not freely available, and endorses none.
