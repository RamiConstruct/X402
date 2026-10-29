import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from atelier_x402.discovery import FixtureDiscovery
from atelier_x402.models import (
    BillingUnit,
    Category,
    Provenance,
    Source,
    VerificationStatus,
)
from atelier_x402.normalize import normalize_item

SRC = Source(kind="fixture", uri="test.json", retrieved_at_utc="2026-10-29T00:00:00+00:00")


class NormalizeTests(unittest.TestCase):
    def test_complete_item(self):
        r = normalize_item({
            "provider": "P", "name": "S", "capability": "text",
            "observed_at": "2026-10-02T08:30:00+02:00",
            "price": {"amount": "0.002", "currency": "jetontest", "unit": "per_request"},
            "payment": {"protocol": "x402", "network": "testnet-fictif"},
        }, SRC, Provenance.FICTIF)
        self.assertEqual(r.capability, Category.TEXTE)
        self.assertEqual(r.price.amount, Decimal("0.002"))
        self.assertEqual(r.price.currency, "JETONTEST")
        self.assertEqual(r.price.unit, BillingUnit.PAR_REQUETE)
        self.assertEqual(r.observed_at_utc, "2026-10-02T06:30:00+00:00")
        self.assertEqual(r.unknowns, [])
        self.assertEqual(r.verification_status, VerificationStatus.NON_VERIFIE)

    def test_float_amount_read_exactly(self):
        r = normalize_item({"price": {"amount": 0.1}}, SRC, Provenance.FICTIF)
        self.assertEqual(r.price.amount, Decimal("0.1"))

    def test_missing_data_kept_unknown(self):
        r = normalize_item({}, SRC, Provenance.FICTIF)
        for name in ("provider", "service_name", "capability", "observed_at_utc",
                     "price.amount", "price.currency", "price.unit",
                     "payment_protocol", "network"):
            self.assertIn(name, r.unknowns)
        self.assertIsNone(r.price.amount)
        self.assertFalse(r.price.is_complete)

    def test_non_object_item_kept(self):
        r = normalize_item("texte libre", SRC, Provenance.FICTIF)
        self.assertEqual(r.raw, "texte libre")
        self.assertIn("provider", r.unknowns)

    def test_ambiguous_symbol_gives_unknown_currency(self):
        r = normalize_item({"price": {"amount": "$0.01"}}, SRC, Provenance.FICTIF)
        self.assertEqual(r.price.amount, Decimal("0.01"))
        self.assertIsNone(r.price.currency)
        self.assertTrue(any("ambigu" in w for w in r.warnings))

    def test_usdc_is_not_usd(self):
        r = normalize_item({"price": {"amount": "1", "currency": "USDC"}}, SRC, Provenance.FICTIF)
        self.assertEqual(r.price.currency, "USDC")

    def test_invalid_values_unknown(self):
        r = normalize_item({"price": {"amount": "-1", "currency": "€€", "unit": "par_lune"},
                            "observed_at": "2026-10-04 09:00:00"}, SRC, Provenance.FICTIF)
        self.assertIsNone(r.price.amount)
        self.assertIsNone(r.price.currency)
        self.assertIsNone(r.price.unit)
        self.assertIsNone(r.observed_at_utc)  # pas de fuseau => pas d'UTC inventé
        self.assertGreaterEqual(len(r.warnings), 4)

    def test_nan_and_bool_amount_refused(self):
        for raw in ("NaN", "Infinity", True):
            r = normalize_item({"price": {"amount": raw}}, SRC, Provenance.FICTIF)
            self.assertIsNone(r.price.amount, raw)


class ProvenanceTests(unittest.TestCase):
    def test_tested_claim_never_promoted(self):
        r = normalize_item({"status": "verified"}, SRC, Provenance.DECLARATION_COMMERCIALE)
        self.assertEqual(r.provenance, Provenance.DECLARATION_COMMERCIALE)
        self.assertEqual(r.verification_status, VerificationStatus.NON_VERIFIE)
        self.assertTrue(any("testée" in w for w in r.warnings))

    def test_cannot_build_tested_record_from_description(self):
        with self.assertRaises(ValueError):
            normalize_item({}, SRC, Provenance.TESTE_REELLEMENT)

    def test_fixture_records_are_fictitious(self):
        result = FixtureDiscovery().discover()
        self.assertGreater(len(result.records), 5)
        self.assertTrue(all(r.provenance is Provenance.FICTIF for r in result.records))
        self.assertTrue(all(r.source.kind == "fixture" for r in result.records))

    def test_unmarked_fixture_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.json"
            path.write_text(json.dumps({"services": [{"name": "réel?"}]}))
            result = FixtureDiscovery(path).discover()
        self.assertEqual(result.records, [])
        self.assertTrue(result.errors)


if __name__ == "__main__":
    unittest.main()
