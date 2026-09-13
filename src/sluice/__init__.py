"""Sluice — a pluggable download manager.

The core handles the queue, adjustable throughput, retries, resuming
interrupted transfers, file naming and re-checking sources that can grow.
What sits behind a URL is the job of the extractors, which are independent
modules: the core knows none of them in particular.
"""

from __future__ import annotations

__version__ = "0.2.0"

__all__ = ["__version__"]
