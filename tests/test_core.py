"""Verifiche sul nucleo: portata, denominazione, ripresa, stato finale."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from sluice.downloader import download
from sluice.engine import Engine
from sluice.limiter import Limiter
from sluice.models import Target
from sluice.naming import Layout, sanitize


# --------------------------------------------------------------- limitatore
def test_limiter_blocca_oltre_il_tetto() -> None:
    limiter = Limiter(1)
    limiter.acquire()
    entrato = threading.Event()

    def secondo() -> None:
        limiter.acquire()
        entrato.set()

    threading.Thread(target=secondo, daemon=True).start()
    assert not entrato.wait(0.2), "il secondo non doveva passare col tetto a 1"

    limiter.release()
    assert entrato.wait(1), "liberato uno slot, il secondo doveva passare"


def test_limiter_si_allarga_a_caldo() -> None:
    """Alzare il tetto deve sbloccare subito chi era in attesa."""
    limiter = Limiter(1)
    limiter.acquire()
    entrato = threading.Event()

    threading.Thread(target=lambda: (limiter.acquire(), entrato.set()), daemon=True).start()
    time.sleep(0.1)
    assert not entrato.is_set()

    limiter.set_limit(2)
    assert entrato.wait(1), "alzando il tetto l'attesa doveva sbloccarsi"


def test_limiter_rifiuta_tetti_invalidi() -> None:
    with pytest.raises(ValueError, match="almeno 1"):
        Limiter(0)


# ------------------------------------------------------------ denominazione
@pytest.mark.parametrize(("grezzo", "atteso"), [
    ("Titolo: con due punti", "Titolo con due punti"),
    ("a/b\\c", "abc"),
    ("   spazi    doppi   ", "spazi doppi"),
    ("...", "senza-nome"),
])
def test_sanitize(grezzo: str, atteso: str) -> None:
    assert sanitize(grezzo) == atteso


def test_layout_numera_e_raggruppa(tmp_path: Path) -> None:
    layout = Layout()
    percorso = layout.build(tmp_path, source="La Raccolta", title="Primo pezzo",
                            index=3, suggested="qualcosa.mp3")
    assert percorso == tmp_path / "La Raccolta" / "03 - Primo pezzo.mp3"


def test_layout_file_singolo_senza_sottocartella(tmp_path: Path) -> None:
    """Un file solo non va messo in una cartella che si chiama come lui."""
    percorso = Layout.for_single_file().build(
        tmp_path, source="README.md", title="README.md", index=1, suggested="README.md")
    assert percorso == tmp_path / "README.md"


def test_layout_schema_libreria_multimediale(tmp_path: Path) -> None:
    layout = Layout(folder="{source}", filename="{source} S01E{index:02d}{ext}")
    percorso = layout.build(tmp_path, source="Serie", title="ignorato",
                            index=7, suggested="x.mkv")
    assert percorso.name == "Serie S01E07.mkv"


# ------------------------------------------------------------------ ripresa
class FakeResponse:
    def __init__(self, body: bytes, status: int = 200, headers: dict | None = None) -> None:
        self.body = body
        self.status_code = status
        self.headers = headers or {"content-length": str(len(body))}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            msg = f"HTTP {self.status_code}"
            raise RuntimeError(msg)

    def iter_content(self, chunk_size: int = 0):  # noqa: ANN201, ARG002
        yield self.body

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_: object) -> None:
        return None


class FakeSession:
    """Sessione che risponde alle richieste parziali come farebbe un CDN."""

    def __init__(self, contenuto: bytes, *, accetta_range: bool = True) -> None:
        self.contenuto = contenuto
        self.accetta_range = accetta_range
        self.richieste: list[dict] = []

    def get(self, url: str, **kwargs) -> FakeResponse:  # noqa: ANN003, ARG002
        headers = kwargs.get("headers") or {}
        self.richieste.append(headers)
        intervallo = headers.get("Range")
        if intervallo and self.accetta_range:
            inizio = int(intervallo.split("=")[1].split("-")[0])
            resto = self.contenuto[inizio:]
            return FakeResponse(resto, status=206,
                                headers={"content-length": str(len(resto))})
        return FakeResponse(self.contenuto)


def test_download_completo(tmp_path: Path) -> None:
    sessione = FakeSession(b"0123456789")
    destinazione = tmp_path / "file.bin"
    download(Target(url="http://x/file.bin", filename="file.bin"), destinazione, sessione)
    assert destinazione.read_bytes() == b"0123456789"
    assert not (tmp_path / "file.bin.part").exists(), "il .part va rimosso a fine lavoro"


def test_download_riprende_dal_punto_di_interruzione(tmp_path: Path) -> None:
    """Il pezzo gia' scaricato non va ributtato via."""
    destinazione = tmp_path / "file.bin"
    (tmp_path / "file.bin.part").write_bytes(b"01234")   # interrotto a meta'

    sessione = FakeSession(b"0123456789")
    download(Target(url="http://x/file.bin", filename="file.bin"), destinazione, sessione)

    assert destinazione.read_bytes() == b"0123456789"
    assert sessione.richieste[0].get("Range") == "bytes=5-"


def test_download_riparte_da_zero_se_il_server_ignora_la_ripresa(tmp_path: Path) -> None:
    destinazione = tmp_path / "file.bin"
    (tmp_path / "file.bin.part").write_bytes(b"01234")

    sessione = FakeSession(b"0123456789", accetta_range=False)
    download(Target(url="http://x/file.bin", filename="file.bin"), destinazione, sessione)

    assert destinazione.read_bytes() == b"0123456789", "niente byte duplicati in testa"


def test_download_salta_i_file_gia_presenti(tmp_path: Path) -> None:
    destinazione = tmp_path / "file.bin"
    destinazione.write_bytes(b"gia' qui")
    sessione = FakeSession(b"nuovo contenuto")

    download(Target(url="http://x/file.bin", filename="file.bin"), destinazione, sessione)

    assert destinazione.read_bytes() == b"gia' qui"
    assert sessione.richieste == [], "non doveva nemmeno chiedere"


# ------------------------------------------------------------- stato finale
@pytest.mark.parametrize(("stati", "atteso"), [
    (["done", "done"], "done"),
    (["done", "failed"], "partial"),
    (["failed", "failed"], "failed"),
    # Il caso che conta: dichiarare finito un lavoro con pezzi ancora in
    # sospeso e' il modo piu' sicuro per perderli di vista per sempre.
    (["done", "queued"], "interrupted"),
    (["done", "transferring"], "interrupted"),
])
def test_stato_finale(stati: list[str], atteso: str) -> None:
    job = {"items": {str(n): {"status": s} for n, s in enumerate(stati)}}
    Engine._finalize(job)  # noqa: SLF001
    assert job["status"] == atteso


def test_incomplete_ignora_i_lavori_in_corso() -> None:
    job = {"status": "running", "items": {"a": {"status": "failed"}}}
    assert Engine.incomplete(job) == [], "un lavoro in corso non si tocca"

    job["status"] = "interrupted"
    assert Engine.incomplete(job) == ["a"]
