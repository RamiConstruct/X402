"""Régressions de LAB-001 révision 2 (revue dot) : solvabilité, pas communs, révisions, consensus."""

import copy
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from unittest import mock

from labtrading import arbitrage
from labtrading.arbitrage import buy_reserve, common_lot_step
from labtrading.book import Market, OrderBook
from labtrading.events import EventError, OfficialEvent, _root, load_events, revision_delta, surprise
from labtrading.report import SCENARIOS_DIR, load_scenario, run_scenario

D = Decimal


def base(name="net_positif_complet"):
    return copy.deepcopy(load_scenario(SCENARIOS_DIR / f"scenario_{name}.json"))


def kr_update(seq, mt, bids=(), asks=()):
    return {"venue": "B", "market_time": mt, "received_at": mt + 30, "seq": seq,
            "message": {"channel": "book", "type": "update", "data": [{"symbol": "XFIC/USD",
                        "bids": [{"price": p, "qty": q} for p, q in bids],
                        "asks": [{"price": p, "qty": q} for p, q in asks]}]}}


def cb_update(seq, mt, changes):
    return {"venue": "A", "market_time": mt, "received_at": mt + 20, "seq": seq,
            "message": {"type": "l2update", "product_id": "XFIC-USD", "changes": [list(c) for c in changes]}}


def balances_ok(result):
    return all(x >= 0 for assets in result.inventory_after.values() for x in assets.values())


class SolvencyTests(unittest.TestCase):
    def test_dot_case_never_negative(self):
        data = base()
        data["params"]["target_qty"] = "0.501"
        data["inventory"]["A"]["USD"] = "50.1501"
        market = Market.from_dict(data["markets"][0])
        book = OrderBook({D("99.50"): D("1")}, {D("100.00"): D("1"), D("100.10"): D("2")})
        self.assertEqual(buy_reserve(book, D("0.501"), market), D("50.16"))  # > 50.1501 : refusé
        r = run_scenario(data)
        self.assertEqual(r.planned_qty, D("0.500"))
        self.assertEqual(r.status, "execute_complet")
        self.assertTrue(balances_ok(r))
        self.assertEqual(r.inventory_after["A"]["USD"], D("0.1001"))
        self.assertTrue(all(r.checks.values()))

    def test_book_moves_to_limit_before_execution(self):
        data = base()
        data["events"][0]["message"]["asks"] = [["100.00", "0.3"], ["100.10", "2"]]
        # avant l'arrivée de l'achat, le niveau 100.00 disparaît : tout se remplit à la limite 100.10
        data["events"].append(cb_update(2, 10010, [("sell", "100.00", "0")]))
        market = Market.from_dict(data["markets"][0])
        book = OrderBook({D("99.50"): D("1")}, {D("100.00"): D("0.3"), D("100.10"): D("2")})
        reserve = buy_reserve(book, D("0.5"), market)
        self.assertEqual(reserve, D("50.11"))  # 0.5 x 100.10 = 50.05 + frais 0.06
        data["inventory"]["A"]["USD"] = str(reserve)  # budget exactement égal à la réserve
        r = run_scenario(data)
        self.assertEqual(r.planned_qty, D("0.5"))
        self.assertGreater(r.buy.executed.notional, r.buy.planned.notional)  # plus cher que planifié
        self.assertEqual(r.buy.executed.qty, D("0.5"))
        self.assertTrue(balances_ok(r))
        self.assertEqual(r.inventory_after["A"]["USD"], D("0"))

    def test_partial_fills_keep_invariants(self):
        data = base()
        data["events"].append(cb_update(2, 10010, [("sell", "100.00", "0.2")]))
        data["events"].append(kr_update(2, 10010, bids=[("101.00", "0.2")]))
        r = run_scenario(data)
        self.assertEqual(r.status, "execute_apparie_partiel")
        self.assertTrue(balances_ok(r))
        self.assertTrue(all(r.checks.values()))

    def test_invariant_violation_never_reported_as_success(self):
        data = base()
        data["inventory"]["A"]["USD"] = "1"  # insuffisant, mais la réserve est faussée ci-dessous
        with mock.patch.object(arbitrage, "buy_reserve", return_value=D("0")):
            r = run_scenario(data)
        self.assertEqual(r.status, "erreur_invariant")
        self.assertIsNone(r.realized_pnl)
        self.assertFalse(r.checks["soldes_non_negatifs"])


class CommonLotTests(unittest.TestCase):
    def test_common_step_exact(self):
        self.assertEqual(common_lot_step(D("0.003"), D("0.002")), D("0.006"))
        self.assertEqual(common_lot_step(D("0.002"), D("0.003")), D("0.006"))
        self.assertEqual(common_lot_step(D("0.0025"), D("0.004")), D("0.02"))
        self.assertEqual(common_lot_step(D("1"), D("0.25")), D("1"))
        with self.assertRaises(ValueError):
            common_lot_step(D("0"), D("0.1"))

    def test_dot_case_both_orders(self):
        for lots in (("0.003", "0.002"), ("0.002", "0.003")):
            with self.subTest(lots=lots):
                data = base()
                data["markets"][0]["lot_size"], data["markets"][1]["lot_size"] = lots
                data["params"]["target_qty"] = "0.101"
                r = run_scenario(data)
                self.assertEqual(r.planned_qty, D("0.096"))
                self.assertEqual(r.status, "execute_complet")
                self.assertTrue(all(r.checks.values()))

    def test_no_positive_common_quantity(self):
        data = base()
        data["markets"][0]["lot_size"], data["markets"][1]["lot_size"] = "0.003", "0.002"
        data["params"]["target_qty"] = "0.005"
        r = run_scenario(data)
        self.assertTrue(r.reasons[0].startswith("aucune quantité commune aux pas de lot"))

    def test_minimum_after_common_step(self):
        data = base()
        data["markets"][0]["lot_size"], data["markets"][1]["lot_size"] = "0.003", "0.002"
        data["markets"][1]["min_qty"] = "0.1"
        data["params"]["target_qty"] = "0.101"  # 0.096 < minimum 0.1
        r = run_scenario(data)
        self.assertTrue(any("minimum 0.1" in x for x in r.reasons))


def event(id_, kind="publication", version=1, corrects=None, value=100, available="2026-11-06T13:30:20Z",
          published="2026-11-06T13:30:00Z", period="2026-10", source="BLS", indicator="emploi_fictif"):
    data = {"id": id_, "source": source, "kind": kind, "period": period, "indicator": indicator,
            "published_at": published, "first_seen_at": published, "available_at": available,
            "version": version, "value": None if kind == "calendrier" else value}
    if corrects:
        data["corrects"] = corrects
    return data


def utc(text):
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)


class RevisionGraphTests(unittest.TestCase):
    def test_self_correction_rejected(self):
        with self.assertRaisesRegex(EventError, "lui-même"):
            load_events([event("a", kind="revision", version=2, corrects="a")])

    def test_cycle_rejected_and_bounded(self):
        with self.assertRaises(EventError):
            load_events([event("a", kind="revision", version=2, corrects="b"),
                         event("b", kind="revision", version=3, corrects="a")])
        # même en contournant la validation des versions, _root termine
        a = OfficialEvent.from_dict(event("a", kind="revision", version=2, corrects="b"))
        b = OfficialEvent.from_dict(event("b", kind="revision", version=3, corrects="a"))
        with self.assertRaisesRegex(EventError, "cycle"):
            _root(a, {"a": a, "b": b})

    def test_inconsistent_revisions_rejected(self):
        pub = event("p")
        cases = {
            "version": event("r", kind="revision", version=1, corrects="p", available="2026-12-04T13:31:00Z",
                             published="2026-12-04T13:30:00Z"),
            "rétroactive": event("r", kind="revision", version=2, corrects="p",
                                 available="2026-11-01T00:00:00Z", published="2026-11-01T00:00:00Z"),
            "période": event("r", kind="revision", version=2, corrects="p", period="2026-09",
                             available="2026-12-04T13:31:00Z", published="2026-12-04T13:30:00Z"),
            "inconnue": event("r", kind="revision", version=2, corrects="zzz"),
        }
        for name, rev in cases.items():
            with self.subTest(case=name):
                with self.assertRaises(EventError):
                    load_events([pub, rev])
        with self.assertRaises(EventError):  # un calendrier n'est pas corrigé par une valeur
            load_events([event("c", kind="calendrier"),
                         event("r", kind="revision", version=2, corrects="c")])

    def test_revision_delta_point_in_time(self):
        events = load_events([event("p"), event("r", kind="revision", version=2, corrects="p", value=80,
                                                available="2026-12-04T13:31:00Z",
                                                published="2026-12-04T13:30:00Z")])
        rev = events[1]
        with self.assertRaises(EventError):
            revision_delta(rev, events, utc("2026-12-01T00:00:00"))
        self.assertEqual(revision_delta(rev, events, utc("2026-12-05T00:00:00")), D("-20"))
        with self.assertRaisesRegex(EventError, "publication"):
            surprise(rev, {}, utc("2026-12-05T00:00:00"))


def consensus(**kw):
    data = {"value": 90, "source": "enquête fictive", "indicator": "emploi_fictif", "period": "2026-10",
            "cutoff_at": "2026-11-05T00:00:00Z", "available_at": "2026-11-05T12:00:00Z"}
    data.update(kw)
    return data


class ConsensusTests(unittest.TestCase):
    def setUp(self):
        self.pub = load_events([event("p")])[0]  # publiée 13:30, disponible 13:30:20
        self.t = utc("2026-11-06T14:00:00")

    def test_ex_ante_consensus_ok(self):
        self.assertEqual(surprise(self.pub, consensus(), self.t), D("10"))

    def test_consensus_after_publication_rejected_even_before_decision(self):
        late = consensus(cutoff_at="2026-11-06T13:31:00Z", available_at="2026-11-06T13:31:00Z")
        with self.assertRaisesRegex(EventError, "non antérieur"):
            surprise(self.pub, late, self.t)

    def test_equal_timestamp_rejected_by_convention(self):
        same = consensus(cutoff_at="2026-11-06T13:30:00Z", available_at="2026-11-06T13:30:00Z")
        with self.assertRaises(EventError):
            surprise(self.pub, same, self.t)

    def test_other_rules(self):
        bad = {
            "non fini": consensus(value="NaN"),
            "infini": consensus(value="Infinity"),
            "booléen": consensus(value=True),
            "indicateur": consensus(indicator="autre"),
            "période": consensus(period="2026-09"),
            "sans source": consensus(source=""),
            "figé après disponibilité": consensus(cutoff_at="2026-11-05T13:00:00Z"),
            "champ manquant": {k: v for k, v in consensus().items() if k != "cutoff_at"},
        }
        for name, cons in bad.items():
            with self.subTest(case=name):
                with self.assertRaises(EventError):
                    surprise(self.pub, cons, self.t)
        with self.assertRaises(EventError):  # publication pas encore disponible
            surprise(self.pub, consensus(), utc("2026-11-06T13:30:10"))
        nan_pub = load_events([event("q", value="NaN")])[0]
        with self.assertRaises(EventError):
            surprise(nan_pub, consensus(), self.t)


if __name__ == "__main__":
    unittest.main()
