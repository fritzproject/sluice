"""Sluice — gestore di download a moduli.

Il nucleo si occupa di coda, portata regolabile, tentativi, ripresa dei
trasferimenti interrotti, denominazione dei file e ricontrollo delle sorgenti
che possono crescere. Cosa ci sia dietro un URL lo dicono gli estrattori, che
sono moduli indipendenti: il nucleo non ne conosce nessuno in particolare.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
