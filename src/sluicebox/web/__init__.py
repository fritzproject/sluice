"""Web interface and HTTP API."""

from __future__ import annotations

__all__ = ["create_app"]


def __getattr__(name: str):  # noqa: ANN202
    # Imported lazily: using the library or the CLI must not require Flask.
    if name == "create_app":
        from sluicebox.web.app import create_app
        return create_app
    raise AttributeError(name)
