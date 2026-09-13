"""Enables `python -m sluice`."""

from __future__ import annotations

import sys

from sluicebox.cli import main

if __name__ == "__main__":
    sys.exit(main())
