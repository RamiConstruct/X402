import unittest

from atelier_x402.costs import BudgetPolicy, CostGuard
from atelier_x402.models import Category
from atelier_x402.providers import (
    AccessKind,
    ProviderDisabled,
    ProviderRequest,
    SimulatedProvider,
    default_registry,
)

REQ = ProviderRequest(Category.CODE, "bonjour")


class ProviderTests(unittest.TestCase):
    def test_only_simulated_enabled(self):
        enabled = [p.name for p in default_registry() if p.enabled]
        self.assertEqual(enabled, ["simule"])

    def test_simulated_is_deterministic_and_marked(self):
        guard = CostGuard(BudgetPolicy())
        a = SimulatedProvider().invoke(REQ, guard)
        b = SimulatedProvider().invoke(REQ, guard)
        self.assertEqual(a.output, b.output)
        self.assertTrue(a.simulated)
        self.assertIn("SIMULATION", a.output)
        self.assertTrue(a.cost_decision.allowed)
        self.assertFalse(a.cost_decision.billable)

    def test_simulated_covers_all_categories(self):
        expected = {"texte", "code", "recherche", "image", "audio", "embeddings"}
        self.assertEqual({c.value for c in SimulatedProvider.categories}, expected)

    def test_disabled_providers_refuse(self):
        guard = CostGuard(BudgetPolicy())
        for p in default_registry()[1:]:
            with self.subTest(provider=p.name):
                with self.assertRaises(ProviderDisabled):
                    p.invoke(REQ, guard)
                self.assertIsNone(p.estimate(REQ).billable)  # coût inconnu => refus
        self.assertEqual(guard.journal, [])  # aucune évaluation de coût atteinte

    def test_chat_subscription_is_not_api_access(self):
        chat = next(p for p in default_registry() if p.access_kind is AccessKind.ABONNEMENT_CHAT)
        self.assertFalse(chat.has_api_access)
        chat.enabled = True  # même activé par erreur
        with self.assertRaisesRegex(ProviderDisabled, "pas d'accès API"):
            chat.invoke(REQ, CostGuard(BudgetPolicy()))


if __name__ == "__main__":
    unittest.main()
