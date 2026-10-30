"""Tests de LAB-001 : laboratoire d'arbitrage hors ligne, données synthétiques."""

import contextlib
import copy
import io
import json
import re
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from labtrading import BANNER
from labtrading.arbitrage import Params, evaluate
from labtrading.book import Market, MessageError, OrderBook, parse_message, to_decimal
from labtrading.cli import main
from labtrading.events import EventError, available_at, load_events, surprise
from labtrading.replay import Event, Replay
from labtrading.report import (
    SCENARIOS_DIR, ScenarioError, load_scenario, markdown, run_scenario, scenario_report,
)

ROOT = Path(__file__).resolve().parents[1]


def scenario(name):
    return load_scenario(SCENARIOS_DIR / f"scenario_{name}.json")


def result(name):
    return run_scenario(scenario(name))


def variant(name="net_positif_complet", **changes):
    data = copy.deepcopy(scenario(name))
    for key, value in changes.items():
        if key in ("params",):
            data[key].update(value)
        else:
            data[key] = value
    return data


def run_cli(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(list(argv))
    return code, out.getvalue(), err.getvalue()


D = Decimal


class MandatoryScenarioTests(unittest.TestCase):
    def test_gross_positive_net_negative(self):
        r = result("brut_positif_net_negatif")
        self.assertEqual(r.status, "rejete")
        self.assertGreater(r.planned_gross, 0)
        self.assertLess(r.planned_net, 0)
        self.assertIsNone(r.buy)  # aucun ordre simulé

    def test_stale_book_fake_gain_refused(self):
        r = result("carnet_perime")
        self.assertEqual(r.status, "rejete")
        self.assertTrue(any("périmé" in x for x in r.reasons))
        self.assertGreater(r.visible["B"]["meilleur_bid"], r.visible["A"]["meilleur_ask"])

    def test_insufficient_depth(self):
        r = result("profondeur_insuffisante")
        self.assertTrue(r.reasons[0].startswith("profondeur insuffisante"))

    def test_incompatible_quote_currencies(self):
        self.assertTrue(any("USD / USDT" in x for x in result("devise_incompatible").reasons))
        data = variant()
        data["markets"][1]["quote"] = "USDC"
        r = run_scenario(data)
        self.assertTrue(any("jamais assimilées" in x for x in r.reasons))

    def test_rounding_and_minimums(self):
        r = result("arrondi_minimum")
        self.assertEqual(r.planned_qty, D("0.001"))
        self.assertTrue(any("minimum 0.002" in x for x in r.reasons))
        notional = variant(params={"target_qty": "0.005"})
        notional["markets"][0]["min_notional"] = "10"
        r = run_scenario(notional)
        self.assertTrue(any("valeur" in x and "minimum 10" in x for x in r.reasons))
        lots = variant()
        lots["markets"][0]["lot_size"] = "0.003"
        lots["markets"][1]["lot_size"] = "0.002"
        lots["params"]["target_qty"] = "0.005"
        r = run_scenario(lots)
        self.assertTrue(r.reasons[0].startswith("aucune quantité commune aux pas de lot"))

    def test_future_data_inaccessible(self):
        data = scenario("donnee_future")
        self.assertEqual(run_scenario(data).status, "rejete")
        markets = {m["venue"]: Market.from_dict(m) for m in data["markets"]}
        replay = Replay(markets, [Event.from_dict(e) for e in data["events"]])
        self.assertEqual(replay.visible_book("B", 10000).book.best_bid(), D("99.80"))
        self.assertEqual(replay.true_book("B", 10000).book.best_bid(), D("101.00"))  # vérité, jamais vue
        later = copy.deepcopy(data)
        later["params"]["decision_time"] = 10500
        self.assertEqual(run_scenario(later).status, "execute_complet")

    def test_single_leg_leaves_exposure_without_gain(self):
        r = result("une_seule_jambe")
        self.assertEqual(r.status, "une_jambe")
        self.assertEqual(r.buy.executed.qty, D("0.5"))
        self.assertEqual(r.sell.executed.qty, 0)
        self.assertEqual(r.open_exposure_base, D("0.5"))
        self.assertIsNone(r.realized_pnl)
        self.assertIn("EXPOSITION OUVERTE", r.exposure_note)
        self.assertTrue(r.checks["actif_conserve"])

    def test_insufficient_balance(self):
        r = result("solde_insuffisant")
        self.assertTrue(r.reasons[0].startswith("solde insuffisant"))
        no_base = variant(inventory={"A": {"XFIC": "0", "USD": "1000"}, "B": {"XFIC": "0", "USD": "0"}})
        self.assertTrue(run_scenario(no_base).reasons[0].startswith("solde insuffisant"))

    def test_latency_destroys_spread(self):
        r = result("latence_detruit_ecart")
        self.assertEqual(r.status, "non_execute")
        self.assertGreater(r.planned_net, 0)  # le plan semblait rentable
        self.assertEqual((r.buy.executed.qty, r.sell.executed.qty), (0, 0))
        self.assertIsNone(r.realized_pnl)

    def test_conservation_and_pnl_reconciliation(self):
        r = result("net_positif_complet")
        self.assertEqual(r.status, "execute_complet")
        self.assertEqual(r.realized_pnl, D("0.34"))
        self.assertEqual(r.checks, {"actif_conserve": True, "soldes_non_negatifs": True,
                                    "pnl_rapproche": True})
        before, after = r.inventory_before, r.inventory_after
        self.assertEqual(after["A"]["XFIC"] + after["B"]["XFIC"], before["A"]["XFIC"] + before["B"]["XFIC"])
        quote_delta = sum(after[v]["USD"] - before[v]["USD"] for v in ("A", "B"))
        self.assertEqual(r.realized_pnl, quote_delta - D("0.05"))

    def test_sequence_gap_and_desync(self):
        self.assertTrue(any("trou de séquence" in x for x in result("trou_sequence").reasons))
        self.assertTrue(any("désynchronisés" in x for x in result("carnets_desynchronises").reasons))

    def test_no_double_counted_slippage(self):
        data = variant(params={"target_qty": "2"},
                       inventory={"A": {"XFIC": "0", "USD": "1000"}, "B": {"XFIC": "5", "USD": "0"}})
        r = run_scenario(data)
        # coût = marche exacte du carnet (1 @ 100.00 + 1 @ 100.10), sans glissement ajouté
        self.assertEqual(r.buy.planned.notional, D("200.10"))
        self.assertEqual(r.sell.planned.notional, D("201.90"))
        self.assertEqual(r.planned_gross, D("1.80"))


class RoundingAndFeeTests(unittest.TestCase):
    def test_fees_rounded_up_proceeds_down(self):
        r = result("net_positif_complet")
        self.assertEqual(r.buy.fee, D("0.05"))   # 50.00 x 0.001
        self.assertEqual(r.sell.fee, D("0.06"))  # 50.50 x 0.001 = 0.0505 -> 0.06
        self.assertEqual(r.planned_fees, D("0.11"))

    def test_partial_matched_fill(self):
        data = variant(events=scenario("net_positif_complet")["events"] + [
            {"venue": "B", "market_time": 10010, "received_at": 10040, "seq": 2,
             "message": {"channel": "book", "type": "update", "data": [{"symbol": "XFIC/USD",
                         "bids": [{"price": "101.00", "qty": "0.2"}], "asks": []}]}},
            {"venue": "A", "market_time": 10010, "received_at": 10030, "seq": 2,
             "message": {"type": "l2update", "product_id": "XFIC-USD",
                         "changes": [["sell", "100.00", "0.2"]]}}])
        r = run_scenario(data)
        self.assertEqual(r.status, "execute_apparie_partiel")
        self.assertEqual(r.matched_qty, D("0.2"))
        self.assertTrue(r.checks["pnl_rapproche"])


class BookAndReplayTests(unittest.TestCase):
    def setUp(self):
        data = scenario("net_positif_complet")
        self.markets = {m["venue"]: Market.from_dict(m) for m in data["markets"]}

    def test_both_formats_parse(self):
        cb = parse_message({"type": "l2update", "product_id": "XFIC-USD",
                            "changes": [["buy", "99.50", "0"]]}, self.markets["A"])
        self.assertEqual(cb.changes, (("bid", D("99.50"), D("0")),))
        kr = parse_message({"channel": "book", "type": "snapshot", "data": [{"symbol": "XFIC/USD",
                            "bids": [{"price": "1.00", "qty": "2"}], "asks": [], "checksum": 1}]},
                           self.markets["B"])
        self.assertEqual(kr.kind, "snapshot")
        self.assertIn("NON vérifié", kr.warnings[0])

    def test_invalid_messages(self):
        bad = [
            ({"type": "l2update", "product_id": "AUTRE", "changes": []}, "A"),
            ({"type": "l2update", "product_id": "XFIC-USD", "changes": [["buy", "1", "-1"]]}, "A"),
            ({"type": "inconnu", "product_id": "XFIC-USD"}, "A"),
            ({"channel": "book", "type": "update", "data": []}, "B"),
        ]
        for msg, venue in bad:
            with self.subTest(msg=msg):
                with self.assertRaises(MessageError):
                    parse_message(msg, self.markets[venue])
        for value in (0.1, True, "NaN", "abc"):
            with self.subTest(value=value):
                with self.assertRaises(MessageError):
                    to_decimal(value)

    def test_update_before_snapshot_and_snapshot_reset(self):
        snap = {"type": "snapshot", "product_id": "XFIC-USD", "bids": [["99.00", "1"]], "asks": [["100.00", "1"]]}
        upd = {"type": "l2update", "product_id": "XFIC-USD", "changes": [["buy", "99.10", "1"]]}
        events = [Event("A", 1, 2, 1, upd), Event("A", 3, 4, 2, snap)]
        replay = Replay({"A": self.markets["A"]}, events)
        self.assertFalse(replay.visible_book("A", 2).valid)
        state = replay.visible_book("A", 4)
        self.assertTrue(state.valid)
        self.assertTrue(state.warnings)

    def test_crossed_and_off_tick_books_invalid(self):
        crossed = OrderBook({D("101"): D("1")}, {D("100"): D("1")})
        self.assertTrue(any("croisé" in p for p in crossed.problems(self.markets["A"])))
        off_tick = OrderBook({D("99.005"): D("1")}, {D("100"): D("1")})
        self.assertTrue(any("pas de cotation" in p for p in off_tick.problems(self.markets["A"])))

    def test_clock_inconsistency_refused(self):
        with self.assertRaises(MessageError):
            Event.from_dict({"venue": "A", "market_time": 10, "received_at": 5, "seq": 1, "message": {}})


def consensus(**kw):
    base = {"value": 90, "source": "enquête fictive", "indicator": "emploi_fictif",
            "period": "2026-10", "cutoff_at": "2026-11-05T00:00:00Z",
            "available_at": "2026-11-05T12:00:00Z"}
    base.update(kw)
    return base


class OfficialEventTests(unittest.TestCase):
    def setUp(self):
        data = json.loads((SCENARIOS_DIR / "evenements_officiels_fictifs.json").read_text())
        self.assertIs(data["fictif"], True)
        self.events = load_events(data["events"])

    @staticmethod
    def t(text):
        return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)

    def test_point_in_time_and_revisions(self):
        before_pub = {e.id for e in available_at(self.events, self.t("2026-11-06T13:30:00"))}
        self.assertNotIn("pub-emploi-2026-10", before_pub)
        after_pub = available_at(self.events, self.t("2026-11-10T00:00:00"))
        emploi = [e for e in after_pub if e.period == "2026-10" and e.kind != "calendrier"]
        self.assertEqual([e.value for e in emploi], [100])  # révision pas encore disponible
        after_rev = available_at(self.events, self.t("2026-12-05T00:00:00"))
        emploi = [e for e in after_rev if e.period == "2026-10" and e.kind != "calendrier"]
        self.assertEqual([e.value for e in emploi], [80])

    def test_schema_rules(self):
        base = {"id": "x", "source": "BLS", "kind": "calendrier", "published_at": "2026-01-01T00:00:00Z",
                "first_seen_at": "2026-01-01T00:00:00Z", "available_at": "2026-01-01T00:00:00Z"}
        with self.assertRaises(EventError):
            load_events([{**base, "value": 1}])  # un calendrier ne contient pas la publication
        with self.assertRaises(EventError):
            load_events([{**base, "available_at": "2025-12-31T00:00:00Z"}])
        with self.assertRaises(EventError):
            load_events([{**base, "kind": "revision"}])
        with self.assertRaises(EventError):
            load_events([{**base, "published_at": "2026-01-01T00:00:00"}])  # sans fuseau

    def test_surprise_requires_timestamped_consensus(self):
        pub = next(e for e in self.events if e.id == "pub-emploi-2026-10")
        t = self.t("2026-11-07T00:00:00")
        with self.assertRaises(EventError):
            surprise(pub, None, t)
        with self.assertRaises(EventError):
            surprise(pub, {"value": 90, "available_at": "2026-11-05T00:00:00Z"}, t)  # non sourcé
        self.assertEqual(surprise(pub, consensus(), t), 10)


class ReportCliAndSafetyTests(unittest.TestCase):
    def test_reproducible_reports_with_banner(self):
        first = [scenario_report(n, scenario(n), result(n)) for n in ("net_positif_complet", "une_seule_jambe")]
        second = [scenario_report(n, scenario(n), result(n)) for n in ("net_positif_complet", "une_seule_jambe")]
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))
        self.assertTrue(all(r["avertissement"] == BANNER for r in first))
        md = markdown(first)
        self.assertTrue(md.startswith(f"# {BANNER}"))
        self.assertIn("HYPOTHÈSES", json.dumps(first, ensure_ascii=False))

    def test_cli_all_json_and_markdown(self):
        code, out, err = run_cli("run", "--all", "--json")
        self.assertEqual(code, 0)
        reports = json.loads(out)
        self.assertEqual(len(reports), len(list(SCENARIOS_DIR.glob("scenario_*.json"))))
        self.assertIn(BANNER, err)
        code, out, _ = run_cli("run", "--scenario", "une_seule_jambe")
        self.assertIn("EXPOSITION OUVERTE", out)

    def test_no_ranking_of_strategies(self):
        _, out, _ = run_cli("run", "--all", "--json")
        self.assertNotRegex(out.lower(), r"meilleur[e]?_(bot|strat)|classement")

    def test_unmarked_scenario_refused(self):
        with self.assertRaises(ScenarioError):
            path = ROOT / "tests" / "_tmp_non_fictif.json"
            try:
                path.write_text('{"markets": []}')
                load_scenario(path)
            finally:
                path.unlink(missing_ok=True)

    def test_no_network_code_in_lab(self):
        forbidden = re.compile(r"^\s*(import|from)\s+(socket|urllib|http|requests|ssl|asyncio)\b", re.M)
        for path in (ROOT / "labtrading").glob("*.py"):
            with self.subTest(module=path.name):
                self.assertIsNone(forbidden.search(path.read_text(encoding="utf-8")))

    def test_params_are_hypotheses(self):
        p = Params.from_dict(scenario("net_positif_complet")["params"])
        self.assertEqual(p.rebalance_cost_per_unit, D("0.10"))
        self.assertIn("pas des tarifs", scenario_report("x", scenario("net_positif_complet"),
                                                         result("net_positif_complet"))["hypotheses"]["note"])


if __name__ == "__main__":
    unittest.main()
