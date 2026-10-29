import contextlib
import io
import json
import logging
import tempfile
import unittest
from pathlib import Path

from atelier_x402.cli import main
from atelier_x402.discovery import DiscoveryResult, FixtureDiscovery
from atelier_x402.models import Provenance, Source
from atelier_x402.normalize import normalize_item
from atelier_x402.redact import MASK, RedactingFilter, redact
from atelier_x402.report import compare, result_to_dict, summary_markdown

PRIVATE_KEY = "0x" + "ab" * 32
SRC = Source("fixture", "t.json", "2026-10-29T00:00:00+00:00")


def run_cli(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(list(argv))
    return code, out.getvalue()


class ReportTests(unittest.TestCase):
    def test_json_export_fields(self):
        data = result_to_dict(FixtureDiscovery().discover())
        rec = data["services"][0]
        for key in ("provider", "capability", "source", "observed_at_utc", "price",
                    "provenance", "verification_status", "unknowns"):
            self.assertIn(key, rec)
        self.assertEqual(set(rec["price"]), {"amount", "currency", "unit", "raw"})
        self.assertIn("avertissement", data)
        json.dumps(data)  # sérialisable

    def test_compare_never_mixes_currency_or_unit(self):
        items = [
            {"capability": "text", "name": "a", "price": {"amount": "1", "currency": "AAA", "unit": "per_request"}},
            {"capability": "text", "name": "b", "price": {"amount": "2", "currency": "BBB", "unit": "per_request"}},
            {"capability": "text", "name": "c", "price": {"amount": "3", "currency": "AAA", "unit": "per_1k_tokens"}},
            {"capability": "text", "name": "d", "price": {"amount": "0.5", "currency": "AAA", "unit": "per_request"}},
            {"capability": "text", "name": "e", "price": {"amount": "0.1"}},
        ]
        records = [normalize_item(i, SRC, Provenance.FICTIF) for i in items]
        cmp = compare(records)
        self.assertEqual([i["service"] for i in cmp["groupes_comparables"]["texte|AAA|par_requete"]],
                         ["d", "a"])
        self.assertEqual(len(cmp["groupes_comparables"]), 3)
        self.assertEqual([i["service"] for i in cmp["non_comparables"]], ["e"])

    def test_secrets_redacted_in_exports(self):
        item = {"name": "s", "api_key": "sk-abcdefghijklmnop", "note": f"cle {PRIVATE_KEY}",
                "headers": {"Authorization": "Bearer xyzxyzxyz123"}}
        result = DiscoveryResult(records=[normalize_item(item, SRC, Provenance.FICTIF)])
        text = json.dumps(result_to_dict(result), ensure_ascii=False) + summary_markdown(result)
        for secret in ("sk-abcdefghijklmnop", PRIVATE_KEY, "xyzxyzxyz123"):
            self.assertNotIn(secret, text)
        self.assertIn(MASK, text)

    def test_redact_patterns(self):
        self.assertEqual(redact({"PAYMENT-SIGNATURE": "abc"}), {"PAYMENT-SIGNATURE": MASK})
        self.assertNotIn("sk-", redact("clé sk-1234567890abcdef"))
        self.assertEqual(redact({"amount": "0.01"}), {"amount": "0.01"})

    def test_log_redaction(self):
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.addFilter(RedactingFilter())
        logger = logging.getLogger("atelier_x402.test")
        logger.addHandler(handler)
        try:
            logger.warning("clé %s", PRIVATE_KEY)
        finally:
            logger.removeHandler(handler)
        self.assertNotIn(PRIVATE_KEY, stream.getvalue())
        self.assertIn(MASK, stream.getvalue())

    def test_summary_mentions_unknowns(self):
        md = summary_markdown(FixtureDiscovery().discover())
        self.assertIn("inconnu", md)
        self.assertIn("fictif", md)
        self.assertIn("Non comparables", md)


class CliTests(unittest.TestCase):
    def test_discover_writes_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out = run_cli("discover", "--out", tmp)
            self.assertEqual(code, 0)
            self.assertTrue((Path(tmp) / "decouverte.json").exists())
            self.assertTrue((Path(tmp) / "synthese.md").exists())

    def test_http_sources_ignored_without_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_cli("discover", "--out", tmp, "--http-source", "https://exemple.org/")
            data = json.loads((Path(tmp) / "decouverte.json").read_text())
        self.assertTrue(any("désactivée" in e for e in data["erreurs"]))

    def test_check_cost_refuses_unknown_and_known(self):
        code, out = run_cli("check-cost", "--price", "0.01")
        self.assertEqual(code, 0)
        self.assertFalse(json.loads(out)["autorise"])
        code, out = run_cli("check-cost", "--price", "0.01", "--currency", "USDC",
                            "--unit", "per_request", "--per-call-cap", "1",
                            "--budget-currency", "USDC")
        self.assertEqual(json.loads(out)["raisons"], ["appels facturables bloqués dans ce lot"])

    def test_simulate_all(self):
        code, out = run_cli("simulate-x402", "--all")
        self.assertEqual(code, 0)
        reports = json.loads(out)
        self.assertTrue(all(r["paiement_reel_effectue"] is False for r in reports))

    def test_providers(self):
        code, out = run_cli("providers")
        self.assertIn("abonnement_chat", out)
        self.assertIn("api=non", out)


if __name__ == "__main__":
    unittest.main()
