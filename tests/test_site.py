"""Page de suivi : registre, configuration Cloudflare et Worker (sans réseau)."""

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"


def wrangler_config() -> dict:
    text = (SITE / "wrangler.jsonc").read_text(encoding="utf-8")
    return json.loads(re.sub(r"^\s*//.*$", "", text, flags=re.M))


class SiteConfigTests(unittest.TestCase):
    def setUp(self):
        self.registry = json.loads((SITE / "projets.json").read_text(encoding="utf-8"))

    def test_routes_match_registry_and_spare_root_domain(self):
        domain = self.registry["domaine"]
        expected = {f'{self.registry["sous_domaine_accueil"]}.{domain}'} | {
            f'{p["slug"]}.{domain}' for p in self.registry["projets"]}
        routes = wrangler_config()["routes"]
        self.assertEqual({r["pattern"] for r in routes}, expected)
        self.assertTrue(all(r["custom_domain"] is True for r in routes))
        self.assertNotIn(domain, {r["pattern"] for r in routes})  # racine intacte (VPS)

    def test_no_credentials_in_config_or_registry(self):
        config = wrangler_config()
        self.assertNotIn("account_id", config)
        text = (SITE / "wrangler.jsonc").read_text() + (SITE / "projets.json").read_text()
        self.assertIsNone(re.search(r"(?i)(api[_-]?token|password|mot de passe|@ik\.me)\s*[:=]", text))

    def test_public_decision_recorded(self):
        self.assertEqual(self.registry["visibilite"], "publique")

    @unittest.skipUnless(shutil.which("node"), "node absent")
    def test_worker_routing_with_node(self):
        proc = subprocess.run(["node", "--test", str(SITE / "worker" / "index.test.mjs")],
                              capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("# pass 4", proc.stdout)


if __name__ == "__main__":
    unittest.main()
