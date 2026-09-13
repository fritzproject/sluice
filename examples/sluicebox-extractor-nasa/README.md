# sluicebox-extractor-nasa

An example **add-on** for [Sluicebox](https://github.com/fritzproject/sluice):
a complete third-party extractor, in its own package, that plugs in through an
entry point without the core knowing anything about it.

It handles the [NASA Image and Video Library](https://images.nasa.gov) —
public domain material, and an API that needs no key, so it runs as-is.

## Install

```bash
pip install ./examples/sluicebox-extractor-nasa      # from a clone
# or, once published:  pip install sluicebox-extractor-nasa
```

Then confirm Sluicebox picked it up:

```bash
sluicebox extractors
#   nasa           NASA Image and Video Library (public domain)
#   archive_org    Internet Archive items
#   …
```

Nothing else to configure. Removing it is `pip uninstall sluicebox-extractor-nasa`.

## Use

A whole search — every matching image, queued:

```bash
sluicebox get "https://images.nasa.gov/search?q=apollo%2011" -o ~/Pictures
```

A single item:

```bash
sluicebox get https://images.nasa.gov/details/as11-40-5874 -o ~/Pictures
```

Each picture is published in several renditions; the extractor picks the
largest one rather than downloading four copies of the same image.

A search is declared `ongoing`, so watching it makes sense: tick *Re-check* in
the interface, or pass `--watch`, and newly published matches queue themselves.

## What to copy from it

It is about 90 lines and shows the four methods a real extractor needs:

- `matches()` recognises two URL shapes, a search and a single item
- `inspect()` reports `kind` and `ongoing` honestly, so the core knows whether
  re-checking the source is worth anything
- `items()` returns stable keys — the NASA id, not a position in a list, so a
  restart finds the same item again even if search results move around
- `resolve()` is called fresh on every attempt, picks a rendition, and carries
  the licence in `metadata` so attribution is not lost

Full guide: [writing an extractor](../../docs/writing-extractors.md).
