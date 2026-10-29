import unittest
from decimal import Decimal

from atelier_x402.costs import (
    BILLABLE_CALLS_ALLOWED,
    NON_BILLABLE,
    BudgetPolicy,
    CostEstimate,
    CostGuard,
)
from atelier_x402.models import BillingUnit

FULL = CostEstimate(billable=True, amount=Decimal("0.01"), currency="JETONTEST",
                    unit=BillingUnit.PAR_REQUETE, quantity=Decimal(1))
POLICY = BudgetPolicy(session_cap=Decimal("1"), per_call_cap=Decimal("0.05"),
                      currency="JETONTEST")


class CostGuardTests(unittest.TestCase):
    def test_lock_is_off(self):
        self.assertFalse(BILLABLE_CALLS_ALLOWED)

    def test_billable_always_refused_even_within_caps(self):
        d = CostGuard(POLICY).authorize(FULL)
        self.assertFalse(d.allowed)
        self.assertEqual(d.reasons, ("appels facturables bloqués dans ce lot",))

    def test_unknowns_refused(self):
        cases = {
            "prix inconnu": CostEstimate(True, None, "JETONTEST", BillingUnit.PAR_REQUETE, Decimal(1)),
            "devise inconnue": CostEstimate(True, Decimal("0.01"), None, BillingUnit.PAR_REQUETE, Decimal(1)),
            "unité de facturation inconnue": CostEstimate(True, Decimal("0.01"), "JETONTEST", None, Decimal(1)),
            "estimation de consommation inconnue": CostEstimate(True, Decimal("0.01"), "JETONTEST", BillingUnit.PAR_REQUETE, None),
            "caractère facturable inconnu": CostEstimate(None, Decimal("0.01"), "JETONTEST", BillingUnit.PAR_REQUETE, Decimal(1)),
        }
        for reason, estimate in cases.items():
            with self.subTest(reason=reason):
                guard = CostGuard(POLICY)
                self.assertFalse(guard.authorize(estimate).allowed)
                self.assertIn(reason, guard.evaluate_hypothetical(estimate).reasons)
                self.assertFalse(guard.evaluate_hypothetical(estimate).allowed)

    def test_unconfirmed_budget_currency(self):
        guard = CostGuard(BudgetPolicy(session_cap=Decimal(17), per_call_cap=Decimal(1)))
        self.assertIn("devise du budget non confirmée", guard.evaluate_hypothetical(FULL).reasons)

    def test_currency_mismatch_no_conversion(self):
        guard = CostGuard(BudgetPolicy(Decimal(17), Decimal(1), "USD"))
        usdc = CostEstimate(True, Decimal("0.01"), "USDC", BillingUnit.PAR_REQUETE, Decimal(1))
        self.assertTrue(any("aucune conversion" in r
                            for r in guard.evaluate_hypothetical(usdc).reasons))

    def test_caps(self):
        big = CostEstimate(True, Decimal("0.02"), "JETONTEST", BillingUnit.PAR_REQUETE, Decimal(3))
        reasons = CostGuard(POLICY).evaluate_hypothetical(big).reasons
        self.assertTrue(any("plafond par appel" in r for r in reasons))
        self.assertTrue(CostGuard(POLICY, spent=Decimal("0.99")).evaluate_hypothetical(FULL).allowed)
        guard = CostGuard(POLICY, spent=Decimal("0.995"))
        self.assertTrue(any("reste de session" in r for r in guard.evaluate_hypothetical(FULL).reasons))

    def test_caps_must_be_configured(self):
        reasons = CostGuard(BudgetPolicy(currency="JETONTEST")).evaluate_hypothetical(FULL).reasons
        self.assertIn("plafond par appel non configuré", reasons)
        self.assertIn("plafond de session non configuré", reasons)

    def test_hypothetical_ok_within_caps(self):
        self.assertTrue(CostGuard(POLICY).evaluate_hypothetical(FULL).allowed)

    def test_paid_retry_refused(self):
        d = CostGuard(POLICY).authorize(FULL, is_retry=True)
        self.assertFalse(d.allowed)
        self.assertIn("réessai payant automatique interdit", d.reasons)

    def test_non_billable_allowed_and_journaled(self):
        guard = CostGuard(POLICY)
        self.assertTrue(guard.authorize(NON_BILLABLE).allowed)
        self.assertEqual(len(guard.journal), 1)
        self.assertEqual(guard.spent, 0)


if __name__ == "__main__":
    unittest.main()
