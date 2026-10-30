"""Rejeu événementiel : heure de marché, réception locale et décision séparées.

Chaque événement porte ``market_time`` (heure annoncée par la plateforme),
``received_at`` (arrivée locale) et ``seq`` (ordre par plateforme), en
millisecondes entières.

* ``visible_book(venue, t)`` : ce que le système CONNAÎT à l'instant ``t`` —
  seulement les événements reçus (``received_at <= t``). Aucune donnée future.
* ``true_book(venue, t)`` : l'état du marché à l'instant ``t`` (``market_time <= t``),
  utilisé UNIQUEMENT pour simuler l'exécution après la décision ; il n'est
  jamais fourni à la décision.

Un trou de séquence, une mise à jour sans snapshot préalable ou un message
invalide rend le carnet invalide jusqu'au snapshot suivant.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .book import Market, MessageError, OrderBook, parse_message


@dataclass(frozen=True)
class Event:
    venue: str
    market_time: int
    received_at: int
    seq: int
    message: Any

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Event":
        try:
            values = {k: data[k] for k in ("market_time", "received_at", "seq")}
        except KeyError as exc:
            raise MessageError(f"événement sans {exc}") from None
        for name, value in values.items():
            if isinstance(value, bool) or not isinstance(value, int):
                raise MessageError(f"{name} doit être un entier (millisecondes)")
        if values["received_at"] < values["market_time"]:
            raise MessageError("received_at antérieur à market_time: horloges incohérentes")
        return cls(str(data.get("venue")), values["market_time"], values["received_at"],
                   values["seq"], data.get("message"))


@dataclass
class BookState:
    venue: str
    book: OrderBook
    valid: bool
    last_market_time: int | None
    last_received_at: int | None
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    events_applied: int = 0


class Replay:
    def __init__(self, markets: dict[str, Market], events: list[Event]):
        self.markets = markets
        unknown = {e.venue for e in events} - set(markets)
        if unknown:
            raise MessageError(f"événements pour des plateformes inconnues: {sorted(unknown)}")
        self.events = list(events)

    def visible_book(self, venue: str, at: int) -> BookState:
        events = [e for e in self.events if e.venue == venue and e.received_at <= at]
        events.sort(key=lambda e: (e.received_at, e.seq))
        return self._build(venue, events)

    def true_book(self, venue: str, at: int) -> BookState:
        events = [e for e in self.events if e.venue == venue and e.market_time <= at]
        events.sort(key=lambda e: e.seq)
        return self._build(venue, events)

    def _build(self, venue: str, events: list[Event]) -> BookState:
        market = self.markets[venue]
        state = BookState(venue, OrderBook(), False, None, None)
        last_seq: int | None = None
        for event in events:
            try:
                msg = parse_message(event.message, market)
            except MessageError as exc:
                state.valid = False
                state.problems.append(f"seq {event.seq}: message invalide ({exc})")
                last_seq = None
                continue
            if msg.kind == "snapshot":
                if state.problems:
                    state.warnings.append("snapshot reçu: carnet réinitialisé après « "
                                          + " ; ".join(state.problems) + " »")
                    state.problems = []
                state.book = OrderBook()
                state.valid = True
            elif last_seq is None or not state.valid:
                state.valid = False
                state.problems.append(f"seq {event.seq}: mise à jour sans snapshot valide préalable")
                continue
            elif event.seq != last_seq + 1:
                state.valid = False
                state.problems.append(f"trou de séquence: {last_seq} puis {event.seq}")
                last_seq = None
                continue
            for side, price, qty in msg.changes:
                state.book.set_level(side, price, qty)
            state.warnings.extend(w for w in msg.warnings if w not in state.warnings)
            last_seq = event.seq
            state.last_market_time = event.market_time
            state.last_received_at = event.received_at
            state.events_applied += 1
        if state.valid:
            book_problems = state.book.problems(market)
            if book_problems:
                state.valid = False
                state.problems.extend(book_problems)
        elif not events:
            state.problems.append("aucun événement reçu")
        return state
