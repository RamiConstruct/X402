"""Régressions de LAB-001 révision 3 : pas commun exact, sans arrondi de contexte Decimal."""

import copy
import math
import unittest
from decimal import Decimal, localcontext

from labtrading.arbitrage import _floor_to_step, _lots_in, common_lot_step
from labtrading.report import SCENARIOS_DIR, load_scenario, run_scenario

D = Decimal
LONG_A = D("1.0000000000000000000000000001")           # 29 chiffres significatifs
LONG_SMALL = D("0.0010000000000000000000000000001")    # exposant -31
COEFF = 10000000000000000000000000001


def scenario(lots, target="0.5", **inventory):
    data = copy.deepcopy(load_scenario(SCENARIOS_DIR / "scenario_net_positif_complet.json"))
    data["markets"][0]["lot_size"], data["markets"][1]["lot_size"] = lots
    data["params"]["target_qty"] = target
    for venue, assets in inventory.items():
        data["inventory"][venue].update(assets)
    return data


class ExactStepTests(unittest.TestCase):
    def test_dot_long_mantissas_both_orders(self):
        expected_a = D(COEFF)  # PPCM(1.000…0001, 1)
        # PPCM indépendant en entiers : 10**28 et COEFF sont premiers entre eux. La
        # construction depuis une chaîne est exacte ; une multiplication Decimal ne l'est pas.
        self.assertEqual(math.gcd(COEFF, 10 ** 28), 1)
        expected_small = D(f"{COEFF * 10 ** 28}E-31")
        self.assertEqual(expected_small, D("10000000000000000000000000.001"))
        for a, b, expected in ((LONG_A, D("1"), expected_a), (LONG_SMALL, D("0.001"), expected_small)):
            with self.subTest(a=a, b=b):
                self.assertEqual(common_lot_step(a, b), expected)
                self.assertEqual(common_lot_step(b, a), expected)
        self.assertEqual(str(common_lot_step(LONG_SMALL, D("0.001"))), "10000000000000000000000000.001")

    def test_independent_of_context_precision(self):
        for prec in (3, 5, 12, 28):
            with self.subTest(prec=prec), localcontext() as ctx:
                ctx.prec = prec
                self.assertEqual(common_lot_step(LONG_A, D("1")), D(COEFF))
                self.assertEqual(common_lot_step(D("0.003"), D("0.002")), D("0.006"))
                self.assertEqual(_floor_to_step(D("0.101"), D("0.006")), D("0.096"))
                self.assertEqual(_lots_in(D("20000000000000000000000000002.5"), D(COEFF)), 2)

    def test_largest_common_multiple_not_above_target(self):
        target = D("20000000000000000000000000002.5")
        self.assertEqual(_floor_to_step(target, common_lot_step(LONG_A, D("1"))),
                         D("20000000000000000000000000002"))
        self.assertEqual(_floor_to_step(D("0.0059999"), D("0.006")), 0)
        self.assertEqual(_floor_to_step(D("0.006"), D("0.006")), D("0.006"))

    def test_out_of_domain_rejected_explicitly(self):
        bad = [D("1." + "0" * 34 + "1"),   # 36 chiffres significatifs
               D("1E-41"), D("1E+13"), D("0"), D("-0.001"), D("NaN"), D("Infinity")]
        for lot in bad:
            with self.subTest(lot=lot):
                with self.assertRaises(ValueError):
                    common_lot_step(lot, D("0.001"))
        self.assertEqual(math.lcm(3, 2), 6)  # garde-fou : le PPCM entier de référence


class EvaluateTests(unittest.TestCase):
    def test_old_defect_no_longer_accepts_off_step_quantity(self):
        # Ancien code : pas commun arrondi à 1, donc 2 unités acceptées alors que 2 n'est
        # pas un multiple de 1.0000000000000000000000000001.
        r = run_scenario(scenario((str(LONG_A), "1"), target="2", B={"XFIC": "5"}))
        self.assertEqual(r.status, "rejete")
        self.assertTrue(r.reasons[0].startswith("aucune quantité commune aux pas de lot"))

    def test_reduced_context_keeps_quantities_exact(self):
        for lots in (("0.003", "0.002"), ("0.002", "0.003")):
            with self.subTest(lots=lots), localcontext() as ctx:
                ctx.prec = 12
                r = run_scenario(scenario(lots, target="0.101"))
                self.assertEqual(r.planned_qty, D("0.096"))
                self.assertEqual(r.status, "execute_complet")
                self.assertTrue(all(r.checks.values()))

    def test_out_of_domain_lot_is_a_reason_not_a_crash(self):
        r = run_scenario(scenario(("1E-41", "0.001")))
        self.assertEqual(r.status, "rejete")
        self.assertTrue(any("hors du domaine" in x for x in r.reasons))

    def test_twelve_scenarios_unchanged(self):
        expected = {
            "arrondi_minimum": "rejete", "brut_positif_net_negatif": "rejete", "carnet_perime": "rejete",
            "carnets_desynchronises": "rejete", "devise_incompatible": "rejete", "donnee_future": "rejete",
            "latence_detruit_ecart": "non_execute", "net_positif_complet": "execute_complet",
            "profondeur_insuffisante": "rejete", "solde_insuffisant": "rejete", "trou_sequence": "rejete",
            "une_seule_jambe": "une_jambe",
        }
        for path in sorted(SCENARIOS_DIR.glob("scenario_*.json")):
            name = path.stem.removeprefix("scenario_")
            with self.subTest(scenario=name):
                self.assertEqual(run_scenario(load_scenario(path)).status, expected[name])


if __name__ == "__main__":
    unittest.main()
