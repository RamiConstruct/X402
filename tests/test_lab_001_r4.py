"""Régressions de LAB-001 révision 4 : borne des résultats intermédiaires, sans exception propagée."""

import contextlib
import copy
import importlib.util
import io
import json
import shutil
import tempfile
import unittest
from decimal import Decimal, localcontext
from pathlib import Path
from unittest import mock

from labtrading import arbitrage
from labtrading.cli import main
from labtrading.report import SCENARIOS_DIR, load_scenario, markdown, run_scenario, scenario_report

D = Decimal
ROOT = Path(__file__).resolve().parents[1]


def extreme(**changes):
    data = copy.deepcopy(load_scenario(SCENARIOS_DIR / "scenario_net_positif_complet.json"))
    data["markets"][0]["lot_size"] = data["markets"][1]["lot_size"] = changes.pop("lot", "3E-40")
    data["params"]["target_qty"] = changes.pop("target", "0.5")
    data["description"] = "pas de lot 3E-40 (cas limite de la revue r3)"
    return data


EXPECTED_QTY = D(f"{(5 * 10 ** 39 // 3) * 3}E-40")  # plus grand multiple de 3E-40 <= 0.5, en entiers


def load_build_site():
    spec = importlib.util.spec_from_file_location("build_site_r4", ROOT / "site" / "build_site.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class IntermediateBoundTests(unittest.TestCase):
    def test_dot_case_exact_end_to_end(self):
        r = run_scenario(extreme())
        self.assertEqual(r.planned_qty, EXPECTED_QTY)
        self.assertEqual(len(str(r.planned_qty).replace("0.", "", 1).lstrip("0")), 40)  # 40 chiffres
        self.assertEqual(r.status, "execute_complet")
        self.assertEqual(r.buy.executed.qty, r.sell.executed.qty)
        self.assertTrue(all(r.checks.values()))

    def test_independent_of_caller_context(self):
        with localcontext() as ctx:
            ctx.prec = 5
            r = run_scenario(extreme())
            self.assertEqual(ctx.prec, 5)  # contexte de l'appelant restauré
        self.assertEqual(r.planned_qty, EXPECTED_QTY)
        self.assertTrue(all(r.checks.values()))

    def test_bound_exceeded_is_a_motivated_rejection(self):
        with mock.patch.object(arbitrage, "MAX_INTERMEDIATE_DIGITS", 10):
            r = run_scenario(extreme())
        self.assertEqual(r.status, "rejete")
        self.assertTrue(any("hors du domaine" in x for x in r.reasons))
        self.assertIsNone(r.buy)
        self.assertIsNone(r.sell)

    def test_out_of_domain_inputs_are_rejected_not_raised(self):
        cases = {
            "pas 3E-41": extreme(lot="3E-41"),
            "cible 36 chiffres": extreme(target="0." + "1" * 36),
        }
        price = extreme()
        price["events"][0]["message"]["asks"][0][0] = "100." + "0" * 39 + "1"  # prix à 43 chiffres
        cases["prix 43 chiffres"] = price
        balance = extreme()
        balance["inventory"]["A"]["USD"] = "1" * 40
        cases["solde 40 chiffres"] = balance
        for name, data in cases.items():
            with self.subTest(case=name):
                r = run_scenario(data)
                self.assertEqual(r.status, "rejete")
                self.assertTrue(any("hors du domaine" in x for x in r.reasons))
                self.assertIsNone(r.buy)

    def test_other_programming_errors_are_not_masked(self):
        with mock.patch.object(arbitrage, "buy_reserve", side_effect=RuntimeError("bogue")):
            with self.assertRaises(RuntimeError):
                run_scenario(extreme())


class BatchAndSiteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        for name in ("net_positif_complet", "une_seule_jambe"):
            shutil.copy(SCENARIOS_DIR / f"scenario_{name}.json", self.tmp / f"scenario_{name}.json")
        (self.tmp / "scenario_m_pas_extreme.json").write_text(json.dumps(extreme()), encoding="utf-8")
        (self.tmp / "scenario_m_hors_domaine.json").write_text(json.dumps(extreme(lot="3E-41")),
                                                               encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_report_batch_completes(self):
        reports = []
        for path in sorted(self.tmp.glob("scenario_*.json")):  # cas limites au milieu du lot
            data = load_scenario(path)
            reports.append(scenario_report(path.stem, data, run_scenario(data)))
        statuses = {rep["scenario"]: rep["resultat"]["status"] for rep in reports}
        self.assertEqual(statuses["scenario_m_pas_extreme"], "execute_complet")
        self.assertEqual(statuses["scenario_m_hors_domaine"], "rejete")
        self.assertEqual(len(reports), 4)
        self.assertIn("SIMULATION SYNTHÉTIQUE", markdown(reports))

    def test_cli_on_extreme_scenarios(self):
        for name, status in (("m_pas_extreme", "execute_complet"), ("m_hors_domaine", "rejete")):
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = main(["run", "--json", "--scenario", str(self.tmp / f"scenario_{name}.json")])
            self.assertEqual(code, 0, err.getvalue())
            self.assertEqual(json.loads(out.getvalue())["resultat"]["status"], status)

    def test_site_generation_consumes_batch(self):
        build_site = load_build_site()
        with mock.patch.object(build_site, "SCENARIOS_DIR", self.tmp):
            rows = build_site.lab_results()
        by_name = {row["nom"]: row for row in rows}
        self.assertEqual(by_name["m_pas_extreme"]["statut"], "execute_complet")
        self.assertEqual(by_name["m_hors_domaine"]["statut"], "rejete")
        self.assertIn("hors du domaine", by_name["m_hors_domaine"]["motif"])
        self.assertIsNone(by_name["m_hors_domaine"]["pnl"])  # aucun résultat financier inventé


if __name__ == "__main__":
    unittest.main()
