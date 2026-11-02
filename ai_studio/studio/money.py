"""Unités monétaires — entiers uniquement, arrondis explicites.

* Coûts fournisseurs : micro-dollars US (µUSD, 1 USD = 1_000_000).
* Crédits utilisateur : 1 crédit = 0,01 USD = 10_000 µUSD.

Toute conversion qui n'est pas exacte doit dire dans quel sens elle arrondit :
les prix facturés sont arrondis au crédit SUPÉRIEUR (jamais en défaveur de la
plateforme de façon silencieuse), et le montant brut est conservé à côté.
"""
from __future__ import annotations

from decimal import ROUND_CEILING, Decimal

MICRO_PER_USD = 1_000_000
MICRO_PER_CREDIT = 10_000


def usd_to_micro_exact(usd: Decimal | str) -> int:
    """Convertit un montant en USD en µUSD ; refuse toute perte de précision."""
    d = Decimal(str(usd)) * MICRO_PER_USD
    if d != d.to_integral_value():
        raise ValueError(f"montant {usd} USD non représentable en µUSD sans arrondi")
    return int(d)


def micro_to_credits_ceil(micro: int) -> int:
    """µUSD → crédits, arrondi au crédit supérieur (arrondi explicite et documenté)."""
    if micro < 0:
        raise ValueError("montant négatif")
    return -(-micro // MICRO_PER_CREDIT)


def credits_to_micro(credits: int) -> int:
    return credits * MICRO_PER_CREDIT


def ceil_decimal_to_int(d: Decimal) -> int:
    return int(d.to_integral_value(rounding=ROUND_CEILING))


def fmt_usd(micro: int) -> str:
    return f"{Decimal(micro) / MICRO_PER_USD:.4f} USD"
