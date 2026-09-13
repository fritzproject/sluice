# Running behind a VPN

🇮🇹 [Leggi in italiano](vpn.it.md)

Sluicebox works perfectly well on a plain connection, and that is the default:
nothing to configure. This page is for when you want its traffic to leave
through a VPN instead — a shared line you would rather not saturate under your
own address, a source that rate-limits per address, or simply a static IP you
would rather not put in front of everything.

There are **two ways**, and they are not equivalent. Pick deliberately.

---

## The default: direct

No variables, no extra containers. Traffic leaves through whatever connection
the host has. Verify it any time with:

```bash
docker exec sluicebox python -c "import requests; print(requests.get('https://api.ipify.org').text)"
```

---

## Option A — share the VPN container's network

The container joins the VPN container's network namespace, exactly as a
BitTorrent client usually does. **Everything** goes through the tunnel, and if
the tunnel drops the traffic stops rather than leaking — a kill switch, for
free.

```yaml
services:
  gluetun:
    image: qmcgaw/gluetun
    container_name: gluetun
    cap_add: [NET_ADMIN]
    environment:
      VPN_SERVICE_PROVIDER: your-provider
      VPN_TYPE: wireguard
      WIREGUARD_PRIVATE_KEY: ${WIREGUARD_PRIVATE_KEY}
      SERVER_COUNTRIES: Switzerland
    ports:
      # The web interface is published HERE, not on the sluicebox service:
      # a container sharing a namespace has no ports of its own.
      - "8420:8420"

  sluicebox:
    build: .
    network_mode: service:gluetun     # <- the whole point
    depends_on: [gluetun]
    environment:
      PUID: "1000"
      PGID: "1000"
    volumes:
      - /srv/downloads:/downloads
      - ./state:/state
```

**The catch worth knowing in advance:** a container in someone else's network
namespace cannot publish ports. The `8420` mapping has to move to the VPN
container, and it is easy to spend an afternoon wondering why the interface
stopped answering. If anything else already publishes ports on that VPN
container, its port list is where you add yours.

Keep the private key in a `.env` file next to the compose file — never in the
compose file itself, which usually ends up in a repository sooner or later.

---

## Option B — use the VPN container's HTTP proxy

Sluicebox keeps its own network and sends **only its outbound requests**
through the VPN's proxy. The interface stays reachable on the LAN as usual, on
its own port.

```yaml
services:
  gluetun:
    image: qmcgaw/gluetun
    container_name: gluetun
    cap_add: [NET_ADMIN]
    networks: [vpn_net]
    environment:
      VPN_SERVICE_PROVIDER: your-provider
      VPN_TYPE: wireguard
      WIREGUARD_PRIVATE_KEY: ${WIREGUARD_PRIVATE_KEY}
      SERVER_COUNTRIES: Switzerland
      HTTPPROXY: "on"
      HTTPPROXY_LISTENING_ADDRESS: ":8888"
      # Without the caller's subnet listed here, gluetun's firewall refuses
      # connections arriving from outside its own namespace — and the failure
      # looks like a network timeout, not like a rule.
      FIREWALL_OUTBOUND_SUBNETS: 172.31.7.0/24

  sluicebox:
    build: .
    networks: [vpn_net]
    ports:
      - "8420:8420"                   # still ours: the UI stays on the LAN
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
        - subnet: 172.31.7.0/24       # must match FIREWALL_OUTBOUND_SUBNETS
```

Note this is **not** a kill switch: if the proxy becomes unreachable the
transfers fail, which is the safe outcome, but the container itself still has
ordinary network access. Where no traffic may ever leave outside the tunnel,
use Option A.

---

## Which one

| | Option A (shared network) | Option B (proxy) |
|---|---|---|
| Interface on the LAN | port moves to the VPN container | stays where it is |
| Kill switch | yes, inherent | no |
| Several exits at once | no | yes |
| Fits alongside an existing VPN stack | needs its ports | leaves it untouched |

Option A if the point is that nothing may ever leave outside the tunnel.
Option B if you want the interface to stay put, or you want more than one exit.

---

## Several exits, in rotation

`SLUICEBOX_PROXIES` takes a comma-separated list. Each item is assigned an exit
in turn:

```yaml
      SLUICEBOX_PROXIES: http://vpn-ch:8888,http://vpn-nl:8888,http://vpn-de:8888
```

One gluetun container per exit, each with its own `SERVER_COUNTRIES` and its
own proxy port. The interface shows how many exits are configured.

**One rule the design enforces, learned the hard way:** resolving an item's
link and downloading its bytes always go through the *same* exit. Some sources
sign the download link against the address that requested it, so a link
obtained from one address and fetched from another comes back `403` — while the
same link fetched from the address that asked for it works fine. If you ever
see downloads failing with `403` on a source that lists items happily, this is
the first thing to check.

---

## Verifying

```bash
# The exit actually in use, from inside the container
docker exec sluicebox python - <<'PY'
import os, requests
proxy = (os.environ.get("SLUICEBOX_PROXIES") or "").split(",")[0].strip()
p = {"http": proxy, "https": proxy} if proxy else None
print("direct:", requests.get("https://api.ipify.org", timeout=15).text)
if p:
    print("proxy :", requests.get("https://api.ipify.org", proxies=p, timeout=25).text)
PY
```

Two different addresses means it is working. The same address twice means the
proxy is being ignored — check `SLUICEBOX_PROXIES` and the firewall subnet.

With Option A there is nothing to compare: every request leaves through the
tunnel, so a single address is the correct result.

---

## Worth being clear about

Rotating exits spreads load across addresses. It does not make anything
anonymous, and it is not a way around a source's terms of use. A source that
asks you not to bulk download is asking regardless of which address you use.

The setting that actually keeps you welcome is pacing: a couple of seconds
between items (`SLUICEBOX_PACING_MIN_SECONDS` / `_MAX_`) and a sane transfer
ceiling cost almost nothing in total time, because refused requests cost
retries anyway.
