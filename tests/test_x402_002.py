"""Régressions de la mission X402-002 (adaptateurs Bazaar hors ligne), sans réseau."""

import contextlib
import hashlib
import http.client
import io
import json
import shutil
import tempfile
import unittest
import urllib.request
from decimal import Decimal
from pathlib import Path
from unittest import mock

from atelier_x402 import bazaar
from atelier_x402.cli import EXIT_INCOMPLETE, main
from atelier_x402.costs import BudgetPolicy, CostGuard
from atelier_x402.models import Provenance
from atelier_x402.redact import MASK

FIX = bazaar.FIXTURES_DIR


def page(name):
    return bazaar.load_fixture(FIX / name)


def run_cli(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(list(argv))
    return code, out.getvalue()


def item(**kw):
    base = {"resource": "https://api.exemple-fictif.org/x", "type": "http", "x402Version": 2,
            "accepts": [{"scheme": "exact", "network": "eip155:84532", "asset": "0xA",
                         "payTo": "0xB", "amount": "10", "maxTimeoutSeconds": 60}]}
    base.update(kw)
    return base


class EnvelopeTests(unittest.TestCase):
    def test_list_preserves_version_and_pagination(self):
        p = page("liste_complete.json")
        self.assertEqual((p.endpoint, p.x402_version, p.coverage), ("list", 2, "complete"))
        self.assertEqual(p.pagination, {"limit": 10, "offset": 0, "total": 2})
        self.assertEqual(len(p.entries), 2)

    def test_search_absent_and_null_pagination_not_invented(self):
        absent = page("recherche_pagination_absente.json")
        self.assertEqual((absent.pagination_state, absent.pagination, absent.coverage),
                         ("absente", None, "unknown"))
        self.assertIsNone(absent.partial_results)
        null = page("recherche_pagination_null.json")
        self.assertEqual((null.pagination_state, null.pagination), ("null", None))
        self.assertIs(null.partial_results, False)
        bare_null = bazaar.parse_search_response(
            {"x402Version": 2, "resources": [item()], "pagination": None}, "t")
        self.assertEqual(bare_null.coverage, "unknown")

    def test_list_without_pagination_is_unknown(self):
        for pagination in ({}, {"pagination": None}):
            with self.subTest(pagination=pagination):
                p = bazaar.parse_list_response({"x402Version": 2, "items": [item()], **pagination}, "t")
                self.assertEqual(p.coverage, "unknown")
                self.assertIsNone(p.pagination)

    def test_partial_results_and_cursor(self):
        p = page("recherche_partielle_curseur.json")
        self.assertEqual((p.coverage, p.partial_results), ("partial", True))
        self.assertEqual(p.pagination["cursor"], "page-2-fictive")
        cursor_only = bazaar.parse_search_response(
            {"x402Version": 2, "resources": [item()], "partialResults": False,
             "pagination": {"limit": 1, "cursor": "suite"}}, "t")
        self.assertEqual(cursor_only.coverage, "partial")

    def test_root_pagination_variant_documented(self):
        p = page("recherche_variante_racine.json")
        self.assertEqual(p.pagination_state, "racine")
        self.assertEqual(p.pagination, {"limit": 20, "cursor": None})
        self.assertTrue(any("variante" in w for w in p.warnings))

    def test_contradictory_envelopes_rejected(self):
        p = page("enveloppe_contradictoire.json")
        self.assertEqual((p.endpoint, p.entries), ("rejete", []))
        self.assertIn("items", p.errors[0])
        both = bazaar.parse_search_response(
            {"x402Version": 2, "resources": [], "pagination": {"cursor": None}, "cursor": "x"}, "t")
        self.assertEqual((both.pagination_state, both.coverage), ("invalide", "unknown"))
        wrong = bazaar.parse_response({"x402Version": 2, "items": []}, "t", expected="search")
        self.assertEqual(wrong.endpoint, "rejete")
        for payload in ([], {"x402Version": 2}, {"items": "pas une liste"}):
            with self.subTest(payload=payload):
                self.assertEqual(bazaar.parse_response(payload, "t").endpoint, "rejete")

    def test_list_total_beyond_page_is_partial(self):
        p = page("liste_offres_multiples.json")
        self.assertEqual(p.coverage, "partial")
        offset = bazaar.parse_list_response(
            {"x402Version": 2, "items": [item()], "pagination": {"limit": 1, "offset": 5, "total": 6}}, "t")
        self.assertEqual(offset.coverage, "partial")

    def test_unsupported_version_never_complete(self):
        p = bazaar.parse_list_response(
            {"x402Version": 1, "items": [item(x402Version=1)],
             "pagination": {"limit": 1, "offset": 0, "total": 1}}, "t")
        self.assertNotEqual(p.coverage, "complete")


class OfferTests(unittest.TestCase):
    def test_all_offers_kept_in_order_without_preference(self):
        offers = page("liste_offres_multiples.json").entries[0].offers
        self.assertEqual([o.amount_atomic for o in offers], ["3000", "2000", "9000"])
        self.assertEqual([o.scheme for o in offers], ["exact", "exact", "upto"])
        self.assertEqual(len({o.network for o in offers}), 2)

    def test_upto_not_comparable(self):
        upto = page("liste_offres_multiples.json").entries[0].offers[2]
        self.assertFalse(upto.comparable)
        self.assertTrue(any("plafond" in n for n in upto.notes))

    def test_big_integers_exact_and_missing_amount_unknown(self):
        offers = page("liste_grand_entier_decimales_inconnues.json").entries[0].offers
        self.assertEqual(offers[0].amount_atomic, "9007199254740993")
        self.assertEqual(offers[1].amount_atomic, "9007199254740995")
        self.assertTrue(any("2^53" in n for n in offers[1].notes))
        self.assertIsNone(offers[2].amount_atomic)
        self.assertFalse(offers[2].comparable)
        self.assertTrue(any("jamais traité comme zéro" in n for n in offers[2].notes))

    def test_invalid_amounts(self):
        for amount in ("1.5", "-3", Decimal("1.5"), 1.5, True, "0x10", ""):
            with self.subTest(amount=amount):
                offer = bazaar.parse_offer(0, {"scheme": "exact", "amount": amount, "network": "n",
                                               "asset": "a", "payTo": "p"})
                self.assertIsNone(offer.amount_atomic)
                self.assertFalse(offer.comparable)

    def test_no_decimals_or_usd_assumed(self):
        exported = json.dumps(page("liste_grand_entier_decimales_inconnues.json").to_dict())
        self.assertNotIn("usd", exported.lower().replace("aucune conversion", "")
                         .replace("ni en usd", ""))
        for offer in page("liste_complete.json").entries[0].offers:
            self.assertTrue(any("décimales de l'actif non fournies" in n for n in offer.notes))
            self.assertIsInstance(offer.amount_atomic, str)

    def test_compare_only_same_network_and_asset(self):
        comparison = page("liste_offres_multiples.json").to_dict()["comparaison_offres"]
        groups = comparison["groupes_exact_par_reseau_et_actif"]
        self.assertEqual(len(groups), 2)
        self.assertTrue(all(len(refs) == 1 for refs in groups.values()))
        self.assertEqual(len(comparison["non_comparables"]), 1)

    def test_compare_orders_by_exact_integer(self):
        entries = [bazaar.parse_entry(0, item(accepts=[
            {"scheme": "exact", "network": "n", "asset": "a", "payTo": "p", "amount": "10"},
            {"scheme": "exact", "network": "n", "asset": "a", "payTo": "p", "amount": "9007199254740993"},
            {"scheme": "exact", "network": "n", "asset": "a", "payTo": "p", "amount": "9"}]))]
        refs = bazaar.compare_offers(entries)["groupes_exact_par_reseau_et_actif"]["n|a"]
        self.assertEqual([r["montant_atomique"] for r in refs], ["9", "10", "9007199254740993"])

    def test_unknown_cost_never_zero_cost_guard_refuses(self):
        guard = CostGuard(BudgetPolicy(session_cap=Decimal(1), per_call_cap=Decimal(1), currency="USDC"))
        for p in (page("liste_complete.json"), page("liste_grand_entier_decimales_inconnues.json")):
            for entry in p.entries:
                for offer in entry.offers:
                    estimate = bazaar.offer_cost_estimate(offer)
                    self.assertIsNone(estimate.amount)
                    self.assertFalse(guard.authorize(estimate).allowed)
                    self.assertIn("prix inconnu", guard.evaluate_hypothetical(estimate).reasons)
        zero = bazaar.parse_offer(0, {"scheme": "exact", "amount": "0", "network": "n",
                                      "asset": "a", "payTo": "p"})
        self.assertFalse(guard.authorize(bazaar.offer_cost_estimate(zero)).allowed)


class McpTests(unittest.TestCase):
    def setUp(self):
        self.page = page("recherche_mcp_partage.json")
        self.by_tool = {e.tool_name: e for e in self.page.entries}

    def test_two_tools_same_resource_not_merged(self):
        a, b = self.by_tool["resumer"], self.by_tool["traduire"]
        self.assertEqual(a.resource, b.resource)
        self.assertNotEqual(a.key, b.key)
        self.assertEqual(a.key, "https://api.exemple-fictif.org/mcp#outil=resumer")
        self.assertEqual(a.kind, "mcp")
        self.assertTrue(a.valid and b.valid)

    def test_mcp_identifier_is_not_a_url_to_call(self):
        entry = self.by_tool["classer"]
        self.assertFalse(entry.resource_is_http_url)
        self.assertTrue(any("pas une URL HTTP à appeler" in d for d in entry.diagnostics))
        self.assertTrue(entry.valid)

    def test_missing_tool_name_diagnosed(self):
        entry = self.by_tool[None]
        self.assertFalse(entry.valid)
        self.assertIsNone(entry.key)
        self.assertTrue(any("toolName" in d for d in entry.diagnostics))
        self.assertEqual(self.page.coverage, "partial")

    def test_external_schema_ref_recorded_never_loaded(self):
        entry = self.by_tool["schema_externe"]
        self.assertEqual(len(entry.schema_external_refs), 1)
        self.assertIn("https://schemas.exemple-fictif.org/y.json", entry.schema_external_refs[0])
        self.assertTrue(any("NON résolues" in d for d in entry.diagnostics))
        # le schéma reste une donnée intacte
        props = entry.bazaar_info["input"]["inputSchema"]["properties"]
        self.assertEqual(props["y"], {"$ref": "https://schemas.exemple-fictif.org/y.json"})

    def test_local_refs_not_flagged(self):
        self.assertEqual(bazaar.find_external_refs({"$defs": {}, "a": {"$ref": "#/$defs/x"}}), [])
        self.assertEqual(len(bazaar.find_external_refs({"a": [{"$id": "file:///etc/x"}]})), 1)

    def test_contradictory_type_invalid(self):
        p = page("liste_entrees_invalides.json")
        contradictory = p.entries[2]
        self.assertEqual(contradictory.kind, "inconnu")
        self.assertFalse(contradictory.valid)
        self.assertFalse(p.entries[0].valid)  # texte libre
        self.assertFalse(p.entries[1].valid)  # resource absente
        self.assertTrue(p.entries[3].valid)
        self.assertEqual(p.coverage, "partial")


class ProvenanceAndMetadataTests(unittest.TestCase):
    def test_fixture_provenance_and_default(self):
        self.assertIs(page("liste_complete.json").provenance, Provenance.FICTIF)
        live = bazaar.parse_response({"x402Version": 2, "resources": [item()]}, "t")
        self.assertIs(live.provenance, Provenance.DECLARATION_COMMERCIALE)
        exported = page("liste_complete.json").to_dict()
        self.assertEqual(exported["provenance"], "fictif")
        self.assertIn("ne prouve ni disponibilité", exported["avertissement"])

    def test_raw_redacted(self):
        entry = bazaar.parse_entry(0, item(api_key="sk-abcdefghijklmnop",
                                           resource="https://api.exemple-fictif.org/x?token=SECRET9"))
        text = json.dumps(bazaar.BazaarPage("search", "t", Provenance.FICTIF, 2, [entry], None,
                                            "absente", None, "unknown", "").to_dict(),
                          ensure_ascii=False)
        self.assertNotIn("sk-abcdefghijklmnop", text)
        self.assertNotIn("SECRET9", text)
        self.assertIn(MASK, text)

    def test_service_metadata_soft_drop(self):
        name, tags, icon, notes = bazaar.sanitize_service_metadata({
            "serviceName": "x" * 33, "tags": ["a", "A", "b", "c", "d", "e", "f", 5, "é"],
            "iconUrl": "https://localhost/icon.png"})
        self.assertIsNone(name)
        self.assertEqual(tags, ["a", "b", "c", "d", "e"])
        self.assertIsNone(icon)
        self.assertGreaterEqual(len(notes), 3)
        for bad in ("https://127.0.0.1/i.png", "https://2130706433/i.png", "data:image/png;base64,AA",
                    "https://u@exemple-fictif.org/i.png", "ftp://exemple-fictif.org/i.png"):
            with self.subTest(icon=bad):
                self.assertIsNone(bazaar.sanitize_service_metadata({"iconUrl": bad})[2])
        self.assertEqual(bazaar.sanitize_service_metadata(
            {"iconUrl": "https://exemple-fictif.org/i.png"})[2], "https://exemple-fictif.org/i.png")


class ManifestTests(unittest.TestCase):
    def test_manifest_lists_every_fixture_with_matching_hash(self):
        manifest = bazaar.load_manifest()
        listed = {f["fichier"] for f in manifest["fixtures"]}
        on_disk = {p.name for p in FIX.glob("*.json")} - {"MANIFEST.json"}
        self.assertEqual(listed, on_disk)
        self.assertGreaterEqual(len(listed), 8)
        for f in manifest["fixtures"]:
            with self.subTest(fixture=f["fichier"]):
                digest = hashlib.sha256((FIX / f["fichier"]).read_bytes()).hexdigest()
                self.assertEqual(digest, f["sha256"])
                self.assertIs(f["synthetique"], True)
                self.assertTrue(f["forme_documentee_dans"])

    def test_manifest_source_is_pinned(self):
        source = bazaar.load_manifest()["source"]
        self.assertEqual(source["commit"], bazaar.SOURCE_COMMIT)
        self.assertRegex(source["recupere_le_utc"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertIn("docs.x402.org", source["methode"])
        for f in source["fichiers"]:
            self.assertIn(source["commit"], f["url"])
            self.assertRegex(f["blob"], r"^[0-9a-f]{40}$")

    def test_expected_results_match_manifest(self):
        for f in bazaar.load_manifest()["fixtures"]:
            with self.subTest(fixture=f["fichier"]):
                p = page(f["fichier"])
                self.assertEqual(p.endpoint, f["endpoint_attendu"])
                self.assertEqual(p.coverage, f["couverture_attendue"])

    def test_tampered_or_unlisted_fixture_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            shutil.copy(FIX / "MANIFEST.json", tmp / "MANIFEST.json")
            (tmp / "liste_complete.json").write_text((FIX / "liste_complete.json").read_text() + " ")
            (tmp / "inconnue.json").write_text('{"x402Version": 2, "items": []}')
            with self.assertRaisesRegex(bazaar.FixtureRefused, "empreinte"):
                bazaar.load_fixture(tmp / "liste_complete.json")
            with self.assertRaisesRegex(bazaar.FixtureRefused, "absente"):
                bazaar.load_fixture(tmp / "inconnue.json")


class NoNetworkAndCliTests(unittest.TestCase):
    def test_cli_all_never_calls_anything(self):
        boom = mock.Mock(side_effect=AssertionError("appel réseau interdit"))
        with mock.patch.object(urllib.request, "urlopen", boom), \
                mock.patch.object(http.client.HTTPConnection, "request", boom):
            code, out = run_cli("bazaar", "--all")
        boom.assert_not_called()
        self.assertEqual(code, EXIT_INCOMPLETE)
        self.assertEqual(len(json.loads(out)), len(bazaar.load_manifest()["fixtures"]))

    def test_cli_single_complete_fixture(self):
        code, out = run_cli("bazaar", "--fixture", str(FIX / "liste_complete.json"))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["coverage"], "complete")

    def test_cli_refused_fixture_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copy(FIX / "MANIFEST.json", Path(tmp) / "MANIFEST.json")
            path = Path(tmp) / "hors_manifeste.json"
            path.write_text("{}")
            code, out = run_cli("bazaar", "--fixture", str(path))
        self.assertEqual(code, EXIT_INCOMPLETE)
        self.assertIn("absente", json.loads(out)["erreur"])

    def test_historical_fixture_mode_unchanged(self):
        code, out = run_cli("compare")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["couverture"]["etat"], "complete")


if __name__ == "__main__":
    unittest.main()
