"""Carnets d'ordres synthétiques et lecture de deux formats de messages.

Les deux formats sont INSPIRÉS de flux publics (aucune compatibilité revendiquée,
documentation officielle non consultée depuis l'environnement de développement) :

* style « cb » (inspiré du canal level2 de Coinbase Exchange) :
  ``{"type": "snapshot", "product_id", "bids": [[prix, taille]], "asks": [...]}`` puis
  ``{"type": "l2update", "product_id", "changes": [["buy"|"sell", prix, taille]]}`` ;
* style « kr » (inspiré du canal book de Kraken spot v2) :
  ``{"channel": "book", "type": "snapshot"|"update",
     "data": [{"symbol", "bids": [{"price", "qty"}], "asks": [...]}]}``.

Une taille nulle supprime le niveau. Les prix et quantités sont des ``Decimal``
(texte ou nombre JSON lu en Decimal) ; un ``float`` Python est refusé.
AUCUN contrôle de somme de contrôle (checksum) n'est implémenté : un champ
« checksum » éventuel est signalé comme NON vérifié.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any


class MessageError(ValueError):
    pass


@dataclass(frozen=True)
class Market:
    """Paramètres d'une plateforme dans un scénario (hypothèses, pas des tarifs vérifiés)."""

    venue: str
    style: str  # "cb" ou "kr"
    symbol: str
    base: str
    quote: str
    tick_size: Decimal
    lot_size: Decimal
    min_qty: Decimal
    min_notional: Decimal
    taker_fee: Decimal
    quote_precision: Decimal

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Market":
        try:
            market = cls(
                venue=str(data["venue"]), style=str(data["style"]), symbol=str(data["symbol"]),
                base=str(data["base"]), quote=str(data["quote"]),
                **{k: to_decimal(data[k], k) for k in (
                    "tick_size", "lot_size", "min_qty", "min_notional", "taker_fee",
                    "quote_precision")},
            )
        except KeyError as exc:
            raise MessageError(f"paramètre de marché manquant: {exc}") from None
        if market.style not in ("cb", "kr"):
            raise MessageError(f"style de flux inconnu: {market.style!r}")
        for name in ("tick_size", "lot_size", "quote_precision"):
            if getattr(market, name) <= 0:
                raise MessageError(f"{name} doit être > 0")
        if market.taker_fee < 0 or market.min_qty < 0 or market.min_notional < 0:
            raise MessageError("frais et minimums doivent être >= 0")
        return market


def to_decimal(value: Any, name: str = "valeur") -> Decimal:
    if isinstance(value, bool) or isinstance(value, float):
        raise MessageError(f"{name}: type {type(value).__name__} refusé (texte ou Decimal exigé)")
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise MessageError(f"{name}: valeur illisible {value!r}") from None
    if not result.is_finite():
        raise MessageError(f"{name}: valeur non finie")
    return result


@dataclass
class OrderBook:
    bids: dict[Decimal, Decimal] = field(default_factory=dict)
    asks: dict[Decimal, Decimal] = field(default_factory=dict)

    def copy(self) -> "OrderBook":
        return OrderBook(dict(self.bids), dict(self.asks))

    def set_level(self, side: str, price: Decimal, qty: Decimal) -> None:
        levels = self.bids if side == "bid" else self.asks
        if qty == 0:
            levels.pop(price, None)
        else:
            levels[price] = qty

    def best_bid(self) -> Decimal | None:
        return max(self.bids) if self.bids else None

    def best_ask(self) -> Decimal | None:
        return min(self.asks) if self.asks else None

    def sorted_asks(self) -> list[tuple[Decimal, Decimal]]:
        return sorted(self.asks.items())

    def sorted_bids(self) -> list[tuple[Decimal, Decimal]]:
        return sorted(self.bids.items(), reverse=True)

    def problems(self, market: Market) -> list[str]:
        found: list[str] = []
        for side, levels in (("bid", self.bids), ("ask", self.asks)):
            if not levels:
                found.append(f"côté {side} vide")
            for price, qty in levels.items():
                if price <= 0 or qty < 0:
                    found.append(f"niveau {side} invalide: {price} x {qty}")
                elif price % market.tick_size != 0:
                    found.append(f"prix {side} {price} hors pas de cotation {market.tick_size}")
        bid, ask = self.best_bid(), self.best_ask()
        if bid is not None and ask is not None and bid >= ask:
            found.append(f"carnet croisé: meilleur bid {bid} >= meilleur ask {ask}")
        return found


@dataclass(frozen=True)
class BookMessage:
    kind: str  # "snapshot" ou "update"
    changes: tuple[tuple[str, Decimal, Decimal], ...]  # (côté, prix, quantité)
    warnings: tuple[str, ...] = ()


def parse_message(message: Any, market: Market) -> BookMessage:
    if not isinstance(message, dict):
        raise MessageError("message non objet")
    if market.style == "cb":
        return _parse_cb(message, market)
    return _parse_kr(message, market)


def _level(side: str, price: Any, qty: Any) -> tuple[str, Decimal, Decimal]:
    p, q = to_decimal(price, "prix"), to_decimal(qty, "quantité")
    if p <= 0 or q < 0:
        raise MessageError(f"niveau invalide: {p} x {q}")
    return side, p, q


def _parse_cb(msg: dict, market: Market) -> BookMessage:
    if msg.get("product_id") != market.symbol:
        raise MessageError(f"produit {msg.get('product_id')!r} ≠ {market.symbol!r}")
    kind = msg.get("type")
    changes: list[tuple[str, Decimal, Decimal]] = []
    if kind == "snapshot":
        for key, side in (("bids", "bid"), ("asks", "ask")):
            for entry in _list(msg, key):
                if not isinstance(entry, list) or len(entry) != 2:
                    raise MessageError(f"niveau {key} mal formé: {entry!r}")
                changes.append(_level(side, *entry))
        return BookMessage("snapshot", tuple(changes))
    if kind == "l2update":
        for entry in _list(msg, "changes"):
            if not isinstance(entry, list) or len(entry) != 3 or entry[0] not in ("buy", "sell"):
                raise MessageError(f"changement mal formé: {entry!r}")
            changes.append(_level("bid" if entry[0] == "buy" else "ask", entry[1], entry[2]))
        return BookMessage("update", tuple(changes))
    raise MessageError(f"type de message inconnu: {kind!r}")


def _parse_kr(msg: dict, market: Market) -> BookMessage:
    if msg.get("channel") != "book" or msg.get("type") not in ("snapshot", "update"):
        raise MessageError("message « book » snapshot/update attendu")
    data = _list(msg, "data")
    if len(data) != 1 or not isinstance(data[0], dict):
        raise MessageError("« data » doit contenir exactement un objet")
    entry = data[0]
    if entry.get("symbol") != market.symbol:
        raise MessageError(f"symbole {entry.get('symbol')!r} ≠ {market.symbol!r}")
    changes: list[tuple[str, Decimal, Decimal]] = []
    for key, side in (("bids", "bid"), ("asks", "ask")):
        for level in entry.get(key, []) or []:
            if not isinstance(level, dict) or set(level) - {"price", "qty"}:
                raise MessageError(f"niveau {key} mal formé: {level!r}")
            changes.append(_level(side, level.get("price"), level.get("qty")))
    warnings = ("checksum présent mais NON vérifié par le laboratoire",) if "checksum" in entry else ()
    kind = "snapshot" if msg["type"] == "snapshot" else "update"
    return BookMessage(kind, tuple(changes), warnings)


def _list(msg: dict, key: str) -> list:
    value = msg.get(key)
    if not isinstance(value, list):
        raise MessageError(f"« {key} » absent ou non liste")
    return value
