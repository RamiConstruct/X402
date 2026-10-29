import json
import tempfile
import unittest
from pathlib import Path

from atelier_x402.x402 import check_terms, load_scenarios, simulate

DATA = load_scenarios()
TESTNETS = frozenset(DATA["testnets_simules"])


def steps(report):
    return {s.name: s for s in report.steps}


class FlowTests(unittest.TestCase):
    def test_never_pays(self):
        for name in DATA["scenarios"]:
            with self.subTest(scenario=name):
                report = simulate(name, DATA)
                d = report.to_dict()
                self.assertTrue(d["simulation"])
                self.assertFalse(d["paiement_reel_effectue"])
                self.assertIsNone(d["transaction"])
                self.assertEqual(d["rentabilite"], "non évaluée")
                pay = steps(report).get("paiement_testnet")
                if pay:
                    self.assertEqual(pay.status, "simule_non_execute")
                    self.assertFalse(pay.details["cle_generee"])
                    self.assertFalse(pay.details["portefeuille_cree"])

    def test_ok_path_full_but_real_decision_refused(self):
        report = simulate("ok", DATA)
        self.assertEqual([s.name for s in report.steps], [
            "decouverte", "reponse_402", "verification_conditions",
            "autorisation", "paiement_testnet", "resultat"])
        auth = steps(report)["autorisation"].details
        self.assertFalse(auth["decision_reelle"]["autorise"])
        self.assertIn("appels facturables bloqués dans ce lot",
                      auth["decision_reelle"]["raisons"])
        self.assertTrue(auth["evaluation_hypothetique"]["autorise"])
        self.assertEqual(report.outcome, "simule")

    def test_refusals(self):
        expected = {
            "prix_inconnu": ("verification_conditions", "décimales"),
            "devise_inconnue": ("verification_conditions", "devise"),
            "reseau_non_testnet": ("verification_conditions", "testnet"),
            "schema_inconnu": ("verification_conditions", "schéma"),
        }
        for name, (step, needle) in expected.items():
            with self.subTest(scenario=name):
                report = simulate(name, DATA)
                self.assertEqual(report.steps[-1].name, step)
                self.assertEqual(report.outcome, "refus")
                self.assertTrue(any(needle in r for r in report.steps[-1].details["raisons"]))
                self.assertNotIn("paiement_testnet", steps(report))

    def test_cap_exceeded(self):
        report = simulate("depasse_plafond", DATA)
        self.assertEqual(report.steps[-1].name, "autorisation")
        self.assertEqual(report.outcome, "refus")

    def test_no_402_stops(self):
        report = simulate("pas_de_402", DATA)
        self.assertEqual(report.outcome, "arret")

    def test_check_terms_amount_from_atomic(self):
        body = {"accepts": [{"scheme": "exact", "network": "testnet-fictif",
                             "amount_atomic": "2500", "asset_symbol": "JETONTEST",
                             "asset_decimals": 6, "unit": "per_request"}]}
        step, estimate = check_terms(body, TESTNETS)
        self.assertEqual(step.status, "ok")
        self.assertEqual(str(estimate.amount), "0.002500")

    def test_check_terms_bad_bodies(self):
        for body in (None, {}, {"accepts": []}, {"accepts": ["x"]},
                     {"accepts": [{"scheme": "exact", "network": "testnet-fictif",
                                   "amount_atomic": "1.5", "asset_decimals": 6,
                                   "asset_symbol": "JETONTEST", "unit": "per_request"}]}):
            with self.subTest(body=body):
                self.assertEqual(check_terms(body, TESTNETS)[0].status, "refus")

    def test_unmarked_scenarios_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s.json"
            path.write_text(json.dumps({"scenarios": {}}))
            with self.assertRaises(ValueError):
                load_scenarios(path)


if __name__ == "__main__":
    unittest.main()
