"""Interfaccia web e API HTTP."""

from __future__ import annotations

__all__ = ["create_app"]


def __getattr__(name: str):  # noqa: ANN202
    # Importazione pigra: chi usa solo la libreria o la riga di comando non
    # deve avere Flask installato.
    if name == "create_app":
        from sluice.web.app import create_app
        return create_app
    raise AttributeError(name)
