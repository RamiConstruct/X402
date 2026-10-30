"""Évaluation et exécution SIMULÉES d'un arbitrage entre deux plateformes.

Décision à l'instant D, sur les carnets VISIBLES (reçus avant D) :

1. carnets valides, même actif et même devise de cotation (USD, USDC et USDT
   sont trois devises distinctes) ; carnets ni périmés ni désynchronisés ;
2. sens « acheter sur X, vendre sur Y » avec un écart brut positif ;
3. quantité = min(cible, inventaire de base sur Y, quantité payable sur X avec
   frais, profondeur des deux carnets), arrondie VERS LE BAS au pas de lot des
   deux plateformes, puis minimums de quantité et de valeur vérifiés ;
4. prix moyens par profondeur (le carnet représente déjà le glissement : aucun
   glissement supplémentaire n'est ajouté), frais des deux jambes, coût simulé
   de rééquilibrage ; arrondis prudents (coûts et frais vers le haut, produits
   vers le bas) ; décision seulement si le net planifié est > 0.

Exécution simulée : chaque jambe arrive à D + latence de sa plateforme et est
servie par le carnet RÉEL à cet instant (ordre à cours limité immédiat : prix
limite = pire niveau planifié, aucun prix plus mauvais). Les remplissages
partiels sont possibles ; une jambe seule laisse une EXPOSITION OUVERTE, jamais
comptée comme un gain. Les soldes sont prépositionnés : aucun transfert
instantané entre plateformes n'est supposé.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_EVEN, Decimal, localcontext
from typing import Any

from .book import Market, OrderBook, to_decimal
from .replay import BookState, Replay

ZERO = Decimal(0)


@dataclass(frozen=True)
class Params:
    decision_time: int
    target_qty: Decimal
    latency_ms: dict[str, int]
    max_staleness_ms: int
    max_skew_ms: int
    rebalance_cost_per_unit: Decimal

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Params":
        return cls(
            decision_time=int(data["decision_time"]),
            target_qty=to_decimal(data["target_qty"], "target_qty"),
            latency_ms={k: int(v) for k, v in data["latency_ms"].items()},
            max_staleness_ms=int(data["max_staleness_ms"]),
            max_skew_ms=int(data["max_skew_ms"]),
            rebalance_cost_per_unit=to_decimal(data["rebalance_cost_per_unit"], "rebalance"),
        )


Inventory = dict[str, dict[str, Decimal]]  # plateforme -> actif -> solde


@dataclass
class Fill:
    qty: Decimal = ZERO
    notional: Decimal = ZERO  # somme prix x quantité, non arrondie
    levels: list[tuple[Decimal, Decimal]] = field(default_factory=list)

    @property
    def avg_price(self) -> Decimal | None:
        return None if self.qty == 0 else self.notional / self.qty


@dataclass
class Leg:
    venue: str
    side: str  # "achat" ou "vente"
    planned: Fill
    limit_price: Decimal | None
    executed: Fill = field(default_factory=Fill)
    cash: Decimal = ZERO  # montant en devise de cotation, arrondi prudemment
    fee: Decimal = ZERO
    exec_time: int | None = None


@dataclass
class Result:
    status: str  # "rejete", "non_execute", "execute_complet", "execute_apparie_partiel", "une_jambe"
    reasons: list[str]
    direction: str | None = None
    gross_spread_unit: Decimal | None = None
    planned_qty: Decimal = ZERO
    planned_gross: Decimal | None = None
    planned_fees: Decimal | None = None
    planned_rebalance: Decimal | None = None
    planned_net: Decimal | None = None
    buy: Leg | None = None
    sell: Leg | None = None
    matched_qty: Decimal = ZERO
    realized_pnl: Decimal | None = None
    open_exposure_base: Decimal = ZERO
    exposure_note: str | None = None
    inventory_before: Inventory = field(default_factory=dict)
    inventory_after: Inventory = field(default_factory=dict)
    checks: dict[str, bool] = field(default_factory=dict)
    visible: dict[str, dict[str, Any]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def evaluate(markets: dict[str, Market], replay: Replay, params: Params,
             inventory: Inventory) -> Result:
    """Évalue dans un contexte Decimal assez précis pour qu'aucun produit ni somme
    de valeurs du domaine ne soit arrondi en silence (seuls les arrondis monétaires
    explicites, par quantize, arrondissent)."""
    with localcontext() as ctx:
        ctx.prec = EXACT_PREC
        ctx.rounding = ROUND_HALF_EVEN
        return _evaluate(markets, replay, params, inventory)


def _evaluate(markets: dict[str, Market], replay: Replay, params: Params,
              inventory: Inventory) -> Result:
    venues = sorted(markets)
    if len(venues) != 2:
        return Result("rejete", ["exactement deux plateformes attendues"])
    inventory = {v: dict(a) for v, a in inventory.items()}
    result = Result("rejete", [], inventory_before=_copy(inventory), inventory_after=_copy(inventory))
    D = params.decision_time
    states = {v: replay.visible_book(v, D) for v in venues}
    result.visible = {v: _describe(s) for v, s in states.items()}
    out_of_domain = _input_problems(markets, params, inventory, [s.book for s in states.values()])
    if out_of_domain:
        result.reasons.append("entrée hors du domaine pris en charge: " + "; ".join(out_of_domain[:3]))
        return result

    a, b = (markets[v] for v in venues)
    if a.base != b.base:
        result.reasons.append(f"actifs différents: {a.base} / {b.base}")
    if a.quote != b.quote:
        result.reasons.append(
            f"devise de cotation incompatible: {a.quote} / {b.quote} (jamais assimilées)")
    for v, state in states.items():
        if not state.valid:
            result.reasons.append(f"carnet {v} invalide: {'; '.join(state.problems)}")
        elif D - state.last_market_time > params.max_staleness_ms:
            result.reasons.append(
                f"carnet {v} périmé: dernière heure de marché {state.last_market_time}, "
                f"décision {D}, tolérance {params.max_staleness_ms} ms")
    if all(s.valid for s in states.values()):
        skew = abs(states[a.venue].last_market_time - states[b.venue].last_market_time)
        if skew > params.max_skew_ms:
            result.reasons.append(f"carnets désynchronisés: écart {skew} ms > {params.max_skew_ms} ms")
    if result.reasons:
        return result

    # Sens : acheter sur la plateforme au meilleur ask, vendre sur celle au meilleur bid.
    best = None
    for buy_v, sell_v in ((a.venue, b.venue), (b.venue, a.venue)):
        spread = states[sell_v].book.best_bid() - states[buy_v].book.best_ask()
        if best is None or spread > best[2]:
            best = (buy_v, sell_v, spread)
    buy_v, sell_v, spread = best
    result.direction = f"achat {buy_v} -> vente {sell_v}"
    result.gross_spread_unit = spread
    if spread <= 0:
        result.reasons.append(f"aucun écart brut positif (meilleur écart {spread})")
        return result

    buy_m, sell_m = markets[buy_v], markets[sell_v]
    buy_book, sell_book = states[buy_v].book, states[sell_v].book
    limits = {
        "cible": params.target_qty,
        f"inventaire {sell_m.base} sur {sell_v}": inventory.get(sell_v, {}).get(sell_m.base, ZERO),
        f"profondeur ask {buy_v} (prix < meilleur bid {sell_v})": _depth(
            buy_book.sorted_asks(), lambda p: p < sell_book.best_bid()),
        f"profondeur bid {sell_v} (prix > meilleur ask {buy_v})": _depth(
            sell_book.sorted_bids(), lambda p: p > buy_book.best_ask()),
    }
    cap = min(limits.values())
    binding = [name for name, value in limits.items() if value == cap]
    budget = inventory.get(buy_v, {}).get(buy_m.quote, ZERO)
    try:
        step = common_lot_step(buy_m.lot_size, sell_m.lot_size)
        qty = _floor_to_step(max(cap, ZERO), step)
        affordable = _max_affordable(qty, step, buy_book, buy_m, budget)
    except DomainError as exc:
        result.reasons.append(f"quantité ou pas de lot hors du domaine pris en charge: {exc}")
        return result
    if qty == 0 and cap >= max(buy_m.lot_size, sell_m.lot_size):
        # Chaque plateforme pourrait traiter seule cette quantité, mais pas les deux ensemble.
        result.reasons.append(
            f"aucune quantité commune aux pas de lot des deux plateformes "
            f"(pas commun {step} > {cap})")
        return result
    if affordable < qty:
        binding = [f"solde {buy_m.quote} payable sur {buy_v} "
                   "(réserve au prix limite, frais et arrondis compris)"]
        qty = affordable
    result.planned_qty = qty
    result.notes.append(f"contrainte(s) limitante(s): {', '.join(binding)} ; pas commun {step}")
    minimum = max(buy_m.min_qty, sell_m.min_qty)
    if qty < minimum or qty == 0:
        why = f"quantité {qty} < minimum {minimum} après arrondi au pas de lot"
        if any(n.startswith(("solde", "inventaire")) for n in binding):
            why = "solde insuffisant: " + why
        if any(n.startswith("profondeur") for n in binding):
            why = "profondeur insuffisante: " + why
        result.reasons.append(why)
        return result

    buy_plan = _walk(buy_book.sorted_asks(), qty, None)
    sell_plan = _walk(sell_book.sorted_bids(), qty, None)
    cost = _ceil(buy_plan.notional, buy_m.quote_precision)
    proceeds = _floor(sell_plan.notional, sell_m.quote_precision)
    fee_buy = _ceil(cost * buy_m.taker_fee, buy_m.quote_precision)
    fee_sell = _ceil(proceeds * sell_m.taker_fee, sell_m.quote_precision)
    for m, notional in ((buy_m, cost), (sell_m, proceeds)):
        if notional < m.min_notional:
            result.reasons.append(
                f"valeur {notional} {m.quote} < minimum {m.min_notional} sur {m.venue}")
    rebalance = _ceil(qty * params.rebalance_cost_per_unit, buy_m.quote_precision)
    result.planned_gross = proceeds - cost
    result.planned_fees = fee_buy + fee_sell
    result.planned_rebalance = rebalance
    result.planned_net = proceeds - fee_sell - cost - fee_buy - rebalance
    if result.reasons:
        return result
    if result.planned_net <= 0:
        result.reasons.append(
            f"écart brut {result.planned_gross} mais net {result.planned_net} après frais "
            f"({result.planned_fees}) et rééquilibrage simulé ({rebalance}): pas d'ordre")
        return result

    # -- exécution simulée --------------------------------------------------------
    buy_leg = Leg(buy_v, "achat", buy_plan, max(p for p, _ in buy_plan.levels))
    sell_leg = Leg(sell_v, "vente", sell_plan, min(p for p, _ in sell_plan.levels))
    for leg, market in ((buy_leg, buy_m), (sell_leg, sell_m)):
        leg.exec_time = D + params.latency_ms.get(leg.venue, 0)
        truth = replay.true_book(leg.venue, leg.exec_time)
        if not truth.valid or _book_problems(truth.book, leg.venue):
            result.notes.append(f"carnet réel {leg.venue} invalide ou hors domaine à {leg.exec_time}: "
                                "aucun remplissage")
            continue
        if leg.side == "achat":
            leg.executed = _walk(truth.book.sorted_asks(), qty, lambda p, lim=leg.limit_price: p <= lim)
            leg.cash = _ceil(leg.executed.notional, market.quote_precision)
        else:
            leg.executed = _walk(truth.book.sorted_bids(), qty, lambda p, lim=leg.limit_price: p >= lim)
            leg.cash = _floor(leg.executed.notional, market.quote_precision)
        leg.fee = _ceil(leg.cash * market.taker_fee, market.quote_precision)
    result.buy, result.sell = buy_leg, sell_leg

    bought, sold = buy_leg.executed.qty, sell_leg.executed.qty
    after = _copy(inventory)
    _add(after, buy_v, buy_m.base, bought)
    _add(after, buy_v, buy_m.quote, -(buy_leg.cash + buy_leg.fee))
    _add(after, sell_v, sell_m.base, -sold)
    _add(after, sell_v, sell_m.quote, sell_leg.cash - sell_leg.fee)
    result.inventory_after = after
    result.matched_qty = min(bought, sold)
    result.open_exposure_base = bought - sold

    if bought == 0 and sold == 0:
        result.status = "non_execute"
        result.reasons.append("écart disparu avant l'arrivée des ordres (latence): aucun remplissage")
    elif bought != sold:
        result.status = "une_jambe"
        side = "acheté non revendu" if bought > sold else "vendu non racheté"
        result.exposure_note = (
            f"EXPOSITION OUVERTE: {abs(bought - sold)} {buy_m.base} {side}. Perte possible ; "
            "aucun gain réalisé n'est compté pour une paire non terminée.")
        result.reasons.append("une seule jambe (ou remplissages inégaux): exposition ouverte")
    else:
        result.status = "execute_complet" if bought == qty else "execute_apparie_partiel"
        reb = _ceil(bought * params.rebalance_cost_per_unit, buy_m.quote_precision)
        result.realized_pnl = (sell_leg.cash - sell_leg.fee) - (buy_leg.cash + buy_leg.fee) - reb
        result.notes.append(f"P&L réalisé inclut le rééquilibrage simulé ({reb}), non débité des soldes")

    # -- contrôles de conservation et de rapprochement --------------------------------
    base_delta = sum(_get(after, v, buy_m.base) - _get(inventory, v, buy_m.base) for v in venues)
    quote_delta = sum(_get(after, v, buy_m.quote) - _get(inventory, v, buy_m.quote) for v in venues)
    result.checks["actif_conserve"] = base_delta == result.open_exposure_base
    result.checks["soldes_non_negatifs"] = all(x >= 0 for assets in after.values() for x in assets.values())
    if result.realized_pnl is not None:
        reb = _ceil(bought * params.rebalance_cost_per_unit, buy_m.quote_precision)
        result.checks["pnl_rapproche"] = result.realized_pnl == quote_delta - reb
    if not all(result.checks.values()):
        # Ne devrait jamais arriver : la réserve couvre le pire cas. Jamais de statut réussi.
        failed = [name for name, ok in result.checks.items() if not ok]
        result.status = "erreur_invariant"
        result.realized_pnl = None
        result.reasons.append(f"invariant violé: {', '.join(failed)} ; résultat non utilisable")
    return result


# -- utilitaires de calcul ----------------------------------------------------------

def _walk(levels: list[tuple[Decimal, Decimal]], qty: Decimal, accept) -> Fill:
    fill = Fill()
    remaining = qty
    for price, available in levels:
        if remaining <= 0 or (accept is not None and not accept(price)):
            break
        take = min(available, remaining)
        fill.qty += take
        fill.notional += take * price
        fill.levels.append((price, take))
        remaining -= take
    return fill


def _depth(levels: list[tuple[Decimal, Decimal]], accept) -> Decimal:
    return sum((q for p, q in levels if accept(p)), ZERO)


# Domaine pris en charge pour les pas de lot et les quantités : au-delà, refus
# explicite (évite des entiers démesurés). Tout le calcul de pas se fait en
# entiers Python exacts, jamais sous le contexte Decimal ambiant (précision 28
# par défaut), qui arrondirait en silence les longues mantisses.
MAX_DIGITS = 34
MIN_EXPONENT = -40
MAX_EXPONENT = 12
# Un résultat intermédiaire (PPCM, plancher, multiple de pas) dérivé d'entrées du
# domaine ne dépasse jamais cette borne : produit de deux coefficients d'entrée
# plus l'écart d'exposants. Au-delà, c'est une erreur de domaine, jamais un arrondi.
MAX_INTERMEDIATE_DIGITS = 2 * MAX_DIGITS + (MAX_EXPONENT - MIN_EXPONENT) + 2
# Précision des calculs d'evaluate : un produit de deux valeurs bornées tient sans arrondi.
EXACT_PREC = 2 * MAX_INTERMEDIATE_DIGITS + 2 * MAX_DIGITS


class DomainError(ValueError):
    """Valeur hors du domaine pris en charge (refus motivé, jamais arrondi)."""


def _coefficient(value: Decimal, name: str, max_digits: int = MAX_DIGITS) -> tuple[int, int]:
    """(coefficient entier, exposant) exacts : value == coefficient x 10**exposant."""
    if not isinstance(value, Decimal) or not value.is_finite():
        raise DomainError(f"{name}: Decimal fini exigé")
    sign, digits, exponent = value.as_tuple()
    if sign or not any(digits):
        raise DomainError(f"{name}: valeur strictement positive exigée")
    coefficient = int("".join(map(str, digits)))
    significant = len(str(coefficient).rstrip("0"))
    if significant > max_digits or not MIN_EXPONENT <= exponent <= MAX_EXPONENT:
        raise DomainError(
            f"{name}: hors du domaine pris en charge ({max_digits} chiffres significatifs, "
            f"exposant entre {MIN_EXPONENT} et {MAX_EXPONENT})")
    return coefficient, exponent


def _decimal_from_int(coefficient: int, exponent: int) -> Decimal:
    """Construit coefficient x 10**exposant sans aucun arrondi de contexte."""
    if coefficient == 0:
        return Decimal((0, (0,), exponent))
    while exponent < 0 and coefficient % 10 == 0:  # zéros superflus retirés, valeur inchangée
        coefficient //= 10
        exponent += 1
    return Decimal((0, tuple(int(c) for c in str(coefficient)), exponent))


def _aligned(value: Decimal, exponent: int) -> int:
    """Entier exact de value / 10**exposant (exposant <= exposant de value)."""
    _, digits, own = value.as_tuple()
    return int("".join(map(str, digits)) or "0") * 10 ** (own - exponent)


def common_lot_step(lot_a: Decimal, lot_b: Decimal) -> Decimal:
    """Plus petit commun multiple EXACT de deux pas décimaux."""
    ca, ea = _coefficient(lot_a, "pas de lot")
    cb, eb = _coefficient(lot_b, "pas de lot")
    exponent = min(ea, eb)
    a, b = ca * 10 ** (ea - exponent), cb * 10 ** (eb - exponent)
    return _decimal_from_int(math.lcm(a, b), exponent)


def _lots_in(qty: Decimal, step: Decimal) -> int:
    """Nombre entier exact de pas contenus dans qty (plancher), sans arrondi de contexte."""
    if qty <= 0:
        return 0
    _coefficient(qty, "quantité", MAX_INTERMEDIATE_DIGITS)  # peut être un résultat intermédiaire
    exponent = min(qty.as_tuple().exponent, step.as_tuple().exponent)
    return _aligned(qty, exponent) // _aligned(step, exponent)


def _times(step: Decimal, lots: int) -> Decimal:
    """step x lots, exact (borne des résultats intermédiaires contrôlée)."""
    coefficient, exponent = _coefficient(step, "pas commun", MAX_INTERMEDIATE_DIGITS)
    product = coefficient * lots
    if len(str(product).rstrip("0")) > MAX_INTERMEDIATE_DIGITS:
        raise DomainError("quantité intermédiaire au-delà de la borne contrôlée")
    return _decimal_from_int(product, exponent)


def _floor_to_step(qty: Decimal, step: Decimal) -> Decimal:
    return _times(step, _lots_in(qty, step))


def buy_reserve(book: OrderBook, qty: Decimal, market: Market) -> Decimal | None:
    """Pire débit possible pour acheter ``qty`` : tout au prix limite, frais et arrondis compris.

    L'exécution simulée ne paie jamais plus que le prix limite (pire niveau
    planifié) : réserver ``qty x limite`` garantit la solvabilité même si le
    carnet se déplace vers la limite avant l'arrivée de l'ordre.
    """
    plan = _walk(book.sorted_asks(), qty, None)
    if plan.qty < qty or not plan.levels:
        return None
    worst = _ceil(qty * max(p for p, _ in plan.levels), market.quote_precision)
    return worst + _ceil(worst * market.taker_fee, market.quote_precision)


def _max_affordable(qty: Decimal, step: Decimal, book: OrderBook, market: Market,
                    budget: Decimal) -> Decimal:
    """Plus grande quantité multiple de ``step`` (<= qty) dont la réserve tient dans le budget."""
    def fits(n: int) -> bool:
        reserve = buy_reserve(book, _times(step, n), market)
        return reserve is not None and reserve <= budget

    low, high = 0, _lots_in(qty, step)
    while low < high:  # la réserve croît avec la quantité : recherche dichotomique
        mid = (low + high + 1) // 2
        if fits(mid):
            low = mid
        else:
            high = mid - 1
    return _times(step, low)


def _ceil(value: Decimal, precision: Decimal) -> Decimal:
    return value.quantize(precision, rounding=ROUND_CEILING)


def _floor(value: Decimal, precision: Decimal) -> Decimal:
    return value.quantize(precision, rounding=ROUND_FLOOR)


def _copy(inv: Inventory) -> Inventory:
    return {v: dict(a) for v, a in inv.items()}


def _add(inv: Inventory, venue: str, asset: str, delta: Decimal) -> None:
    inv.setdefault(venue, {})
    inv[venue][asset] = inv[venue].get(asset, ZERO) + delta


def _get(inv: Inventory, venue: str, asset: str) -> Decimal:
    return inv.get(venue, {}).get(asset, ZERO)


def _input_ok(value: Decimal, name: str) -> str | None:
    """None si la valeur d'entrée est 0 ou dans le domaine (positive, bornée)."""
    if isinstance(value, Decimal) and value.is_finite() and value == 0:
        return None
    try:
        _coefficient(value, name)
    except DomainError as exc:
        return str(exc)
    return None


def _book_problems(book: OrderBook, venue: str) -> list[str]:
    found = []
    for side, levels in (("bid", book.bids), ("ask", book.asks)):
        for price, qty in levels.items():
            found += [m for m in (_input_ok(price, f"prix {side} {venue}"),
                                  _input_ok(qty, f"quantité {side} {venue}")) if m]
    return found


def _input_problems(markets: dict[str, Market], params: Params, inventory: Inventory,
                    books: list[OrderBook]) -> list[str]:
    values = [(params.target_qty, "cible"), (params.rebalance_cost_per_unit, "rééquilibrage")]
    for m in markets.values():
        values += [(getattr(m, f), f"{f} {m.venue}") for f in (
            "tick_size", "lot_size", "min_qty", "min_notional", "taker_fee", "quote_precision")]
    for venue, assets in inventory.items():
        values += [(amount, f"solde {asset} {venue}") for asset, amount in assets.items()]
    found = [m for value, name in values if (m := _input_ok(value, name))]
    for venue, book in zip(sorted(markets), books):
        found += _book_problems(book, venue)
    return found


def _describe(state: BookState) -> dict[str, Any]:
    return {
        "valide": state.valid, "meilleur_bid": state.book.best_bid(),
        "meilleur_ask": state.book.best_ask(), "derniere_heure_marche": state.last_market_time,
        "derniere_reception": state.last_received_at, "evenements_appliques": state.events_applied,
        "problemes": state.problems, "avertissements": state.warnings,
    }
