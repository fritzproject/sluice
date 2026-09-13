# Writing an extractor

🇮🇹 [Leggi in italiano](writing-extractors.it.md)

An extractor answers three questions about a URL: **what is there**, **which
items it contains**, and **where to actually fetch the bytes** of each one.

It downloads nothing and never touches the disk. Queueing, throughput,
retries, resuming, naming and persistence belong to the core and work the same
for everyone — so an extractor inherits every improvement made there for free.

## The four methods

```python
from sluicebox.extractors.base import Context, Extractor
from sluicebox.models import Item, Source, Target


class MyExtractor(Extractor):
    name = "mine"
    description = "One line, shown in the interface"

    @classmethod
    def matches(cls, url: str) -> bool:
        """True if I can handle this URL. Must be fast: no network."""
        return "example.test" in url

    def inspect(self, url: str, ctx: Context) -> Source:
        """What is there, without downloading the items."""
        data = ctx.session.get(f"{url}/info", timeout=ctx.timeout).json()
        return Source(
            title=data["title"],
            kind="collection",            # or "file"
            items_count=data["count"],
            ongoing=data["still_open"],   # whether it can still grow
        )

    def items(self, url: str, ctx: Context) -> list[Item]:
        """The items, in order."""
        data = ctx.session.get(f"{url}/list", timeout=ctx.timeout).json()
        return [
            Item(key=entry["id"], title=entry["name"], index=number)
            for number, entry in enumerate(data["entries"], start=1)
        ]

    def resolve(self, item: Item, ctx: Context) -> Target:
        """The direct link for one item."""
        data = ctx.session.get(f"/link/{item.key}", timeout=ctx.timeout).json()
        return Target(url=data["url"], filename=data["name"],
                      headers={"Referer": "https://example.test/"})
```

## Five things worth knowing

**`key` must be stable.** It is how an item is found again after a restart, so
it cannot depend on position in a list: if the source inserts something in the
middle, everything else shifts and already-downloaded files get fetched again.

**`resolve()` is called on every attempt**, not once. Links that expire must
therefore be *generated* there, never cached: on a third attempt half an hour
later, a stored link is already dead.

**Always use `ctx.session`.** Some sources sign the final link against the
address that requested it, so resolving from one place and downloading from
another fails with an error that looks inexplicable. The session you are given
is the same one used for the transfer, and carries any proxy assigned to that
item.

**Be honest about `ongoing`.** When it is `False`, the core stops re-checking
the source once nothing is left, instead of polling it forever. If the source
publishes its own status (finished / in progress), use it: it beats any
guesswork based on the title.

**Let exceptions through.** There is no need to handle retries or back-off:
the core does that, with growing delays, and shows a compact message in the
interface while keeping the detail in the log.

## Carrying licence and attribution

`Target.metadata` travels with the item and is stored in the job state. Use it
for anything that must not get lost — most free licences require crediting the
author:

```python
return Target(url=info["url"], filename=item.title,
              metadata={"licence": "CC BY-SA 4.0", "author": "A Photographer"})
```

## Distribution

An extractor lives in its own package and declares an entry point:

```toml
# pyproject.toml of the extractor package
[project.entry-points."sluicebox.extractors"]
mine = "my_package.extractor:MyExtractor"
```

Once the package is installed, Sluicebox loads it at startup. Registered
extractors take precedence over the built-in ones, so a default behaviour can
be replaced without touching the core. An extractor that fails to load is
skipped with an error in the log: it never prevents startup.

## Testing

```python
def test_listing():
    class FakeSession:
        def get(self, url, **kwargs):
            return FakeResponse({"title": "Test", "count": 2})

    ctx = Context(session=FakeSession())
    items = MyExtractor().items("https://example.test/x", ctx)
    assert [i.index for i in items] == [1, 2]
```

Extractors are testable without network and without disk: they are functions
from a URL to data. See `tests/test_extractors.py` for complete examples
covering the built-in ones.
