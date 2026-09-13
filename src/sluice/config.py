"""Settings: initial values from the environment, then adjustable at runtime."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

#: Accepted ranges for the adjustable numeric settings.
BOUNDS: dict[str, tuple[float, float]] = {
    "concurrent_transfers": (1, 32),
    "parallel_sources": (1, 16),
    "pacing_min_seconds": (0, 120),
    "pacing_max_seconds": (0, 300),
    "max_retries": (1, 10),
    "recheck_interval_seconds": (300, 604800),
}


def _env(name: str, default: str) -> str:
    return os.environ.get(f"SLUICE_{name.upper()}", default)


# Read through default_factory, not as a plain default: a plain default is
# evaluated once when the module is imported, so anything that sets an
# environment variable afterwards — a test, an embedding application — would
# be silently ignored.
def _env_int(name: str, default: str):  # noqa: ANN202
    return field(default_factory=lambda: int(_env(name, default)))


def _env_float(name: str, default: str):  # noqa: ANN202
    return field(default_factory=lambda: float(_env(name, default)))


def _env_path(name: str, default: str):  # noqa: ANN202
    return field(default_factory=lambda: Path(_env(name, default)))


@dataclass
class Settings:
    """Throughput and behaviour knobs.

    Kept apart from the startup configuration (folders, proxies) because these
    change constantly while the program runs, and those do not.
    """

    #: Total simultaneous transfers: this is the real ceiling.
    concurrent_transfers: int = _env_int("concurrent_transfers", "4")
    #: How many sources to spread them across. Needed because a collection with
    #: a single item would otherwise hold a slot and leave the others idle.
    parallel_sources: int = _env_int("parallel_sources", "3")
    #: Random pause before each item: avoids presenting a source with a burst
    #: of identical back-to-back requests.
    pacing_min_seconds: float = _env_float("pacing_min_seconds", "0")
    pacing_max_seconds: float = _env_float("pacing_max_seconds", "0")
    max_retries: int = _env_int("max_retries", "4")
    #: How often to re-check collections that can still grow.
    recheck_interval_seconds: int = _env_int("recheck_interval_seconds", "21600")

    def as_dict(self) -> dict:
        return asdict(self)

    def update(self, values: dict) -> dict:
        """Apply known fields after validating them. Returns what changed."""
        known = {f.name for f in fields(self)}
        applied: dict = {}
        for key, raw in values.items():
            if key not in known:
                continue
            low, high = BOUNDS[key]
            number = float(raw)
            if not low <= number <= high:
                msg = f"{key} must be between {low:g} and {high:g}"
                raise ValueError(msg)
            current = getattr(self, key)
            value = int(number) if isinstance(current, int) else number
            setattr(self, key, value)
            applied[key] = value

        if self.pacing_min_seconds > self.pacing_max_seconds:
            self.pacing_min_seconds = self.pacing_max_seconds
            applied["pacing_min_seconds"] = self.pacing_min_seconds
        return applied


@dataclass
class Config:
    """Startup configuration, fixed for the lifetime of the process."""

    download_root: Path = _env_path("download_root", "./downloads")
    state_dir: Path = _env_path("state_dir", "./state")
    #: Proxies used in rotation, one per item. Resolving and downloading the
    #: same item always go through the same one, because some sources tie the
    #: signed link to whoever requested it.
    proxies: list[str] = field(
        default_factory=lambda: [p.strip() for p in _env("proxies", "").split(",") if p.strip()])
    user_agent: str = field(
        default_factory=lambda: _env("user_agent",
                                     "Sluice/0.2 (+https://github.com/fritzproject/sluice)"))
    timeout: int = _env_int("timeout", "30")

    def __post_init__(self) -> None:
        self.download_root = Path(self.download_root)
        self.state_dir = Path(self.state_dir)
