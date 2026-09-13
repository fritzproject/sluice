"""Impostazioni: valori iniziali da ambiente, poi modificabili a caldo."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path

#: Intervalli ammessi per le impostazioni numeriche regolabili.
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


@dataclass
class Settings:
    """Regolazioni di portata e comportamento.

    Sono separate dalla configurazione di avvio (cartelle, proxy) perche'
    cambiano in continuazione durante l'uso, mentre le altre no.
    """

    #: Trasferimenti simultanei complessivi: e' il tetto vero.
    concurrent_transfers: int = int(_env("concurrent_transfers", "4"))
    #: Fra quante sorgenti distribuirli. Serve perche' una raccolta di un solo
    #: elemento, da sola, lascerebbe inutilizzati gli altri posti disponibili.
    parallel_sources: int = int(_env("parallel_sources", "3"))
    #: Pausa casuale prima di ogni elemento: evita di presentarsi a una
    #: sorgente come una raffica di richieste identiche.
    pacing_min_seconds: float = float(_env("pacing_min_seconds", "0"))
    pacing_max_seconds: float = float(_env("pacing_max_seconds", "0"))
    max_retries: int = int(_env("max_retries", "4"))
    #: Ogni quanto ricontrollare le raccolte ancora aperte.
    recheck_interval_seconds: int = int(_env("recheck_interval_seconds", "21600"))

    def as_dict(self) -> dict:
        return asdict(self)

    def update(self, values: dict) -> dict:
        """Applica solo i campi noti, dopo averli validati. Restituisce i cambiati."""
        known = {f.name for f in fields(self)}
        applied: dict = {}
        for key, raw in values.items():
            if key not in known:
                continue
            low, high = BOUNDS[key]
            number = float(raw)
            if not low <= number <= high:
                msg = f"{key} deve essere compreso fra {low:g} e {high:g}"
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
    """Impostazioni di avvio, fisse per l'intera esecuzione."""

    download_root: Path = Path(_env("download_root", "./downloads"))
    state_dir: Path = Path(_env("state_dir", "./state"))
    #: Proxy usati a rotazione, uno per elemento. Risoluzione e scaricamento
    #: di uno stesso elemento passano sempre dallo stesso, perche' certe
    #: sorgenti legano il collegamento firmato a chi lo ha richiesto.
    proxies: list[str] = None  # type: ignore[assignment]
    user_agent: str = _env(
        "user_agent",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    )
    timeout: int = int(_env("timeout", "30"))

    def __post_init__(self) -> None:
        if self.proxies is None:
            raw = _env("proxies", "")
            self.proxies = [p.strip() for p in raw.split(",") if p.strip()]
        self.download_root = Path(self.download_root)
        self.state_dir = Path(self.state_dir)
