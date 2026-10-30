"""Régressions de la mission X402-001 (consolidation du lot 1), sans réseau."""

import contextlib
import http.client
import io
import json
import logging
import tempfile
import threading
import time
import unittest
from decimal import Decimal
from pathlib import Path

from atelier_x402.cli import EXIT_INCOMPLETE, main
from atelier_x402.costs import NON_BILLABLE, BudgetPolicy, CostEstimate, CostGuard
from atelier_x402.discovery import DiscoveryResult, FixtureDiscovery, HttpPolicy, PublicHttpDiscovery
from atelier_x402.discovery.http_public import (
    Deadline,
    HttpsTransport,
    PartialResponse,
    RawResponse,
    ResponseTooLarge,
    resolve_within,
)
from atelier_x402.discovery.netguard import ValidatedTarget
from atelier_x402.models import BillingUnit, Provenance, Source
from atelier_x402.normalize import normalize_item
from atelier_x402.redact import MASK, RedactingFilter, redact_text, redact_url
from atelier_x402.report import comparison_report, coverage, result_to_dict, summary_markdown
from atelier_x402.x402 import check_terms

HOST = "catalogue.exemple-fictif.org"
TARGET = ValidatedTarget(url=f"https://{HOST}/s", host=HOST, port=443, path="/s",
                         address="93.184.216.34")
LONG = "0.1234567890123456789012345678901"


# -- doubles contrôlés ---------------------------------------------------------

class FakeResponse:
    def __init__(self, status, headers, script):
        self.status = status
        self._headers = list(headers.items())
        self._script = list(script)

    def getheaders(self):
        return self._headers

    def read1(self, n):
        if not self._script:
            return b""
        step = self._script.pop(0)
        if isinstance(step, BaseException):
            raise step
        if callable(step):
            return step()
        return step[:n]


class FakeConnection:
    """Connexion scriptée : enregistre délais, requêtes, abandon et fermeture."""

    def __init__(self, status=200, headers=None, script=(), getresponse_error=None):
        self.response = FakeResponse(status, headers or {}, script)
        self.getresponse_error = getresponse_error
        self.timeouts, self.requests = [], []
        self.aborted = threading.Event()
        self.closed = False

    def factory(self, target, timeout):
        self.timeouts.append(timeout)
        return self

    def request(self, method, path, headers):
        self.requests.append((method, path, dict(headers)))

    def set_timeout(self, seconds):
        self.timeouts.append(seconds)

    def getresponse(self):
        if self.getresponse_error:
            raise self.getresponse_error
        return self.response

    def abort(self):
        self.aborted.set()

    def close(self):
        self.closed = True


def blocking_until_abort(conn, limit=5.0):
    """Lecture qui bloque jusqu'à l'abandon par le minuteur (ou ``limit``)."""
    def step():
        if conn.aborted.wait(limit):
            raise OSError("connexion fermée par le minuteur")
        return b"x"
    return step


def ok(payload_text):
    return RawResponse(200, {"content-type": "application/json"}, payload_text.encode())


class ScriptedTransport:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def __call__(self, target, deadline, max_bytes):
        self.calls.append(target.path)
        value = self.routes[target.path]
        if isinstance(value, BaseException):
            raise value
        return value


def discovery(routes=None, transport=None, resolver=None, **policy):
    policy.setdefault("allowed_hosts", frozenset({HOST}))
    transport = transport or ScriptedTransport(routes)
    sleeps = []
    d = PublicHttpDiscovery(sources=[f"https://{HOST}/s"], policy=HttpPolicy(**policy),
                            enabled=True, transport=transport,
                            resolver=resolver or (lambda h, p: ["93.184.216.34"]),
                            sleep=sleeps.append)
    return d, transport, sleeps


# -- 1. aucun réessai après 402, même corps illisible -------------------------

class Interrupted402Tests(unittest.TestCase):
    def test_partial_402_from_transport_not_retried(self):
        d, t, sleeps = discovery({"/s": PartialResponse(402, {"x": "1"}, "corps interrompu")},
                                 max_attempts=3)
        result = d.discover()
        self.assertEqual(t.calls, ["/s"])
        self.assertEqual(sleeps, [])
        obs = result.payment_required[0]
        self.assertEqual(obs.body_error, "corps interrompu")
        self.assertIsNone(obs.body)

    def test_real_transport_402_body_cut(self):
        conn = FakeConnection(402, {"content-length": "50"},
                              [b'{"accepts": [', http.client.IncompleteRead(b"", 40)])
        transport = HttpsTransport(connection_factory=conn.factory)
        with self.assertRaises(PartialResponse) as ctx:
            transport(TARGET, Deadline(5), 1000)
        self.assertEqual(ctx.exception.status, 402)
        self.assertTrue(conn.closed)

    def test_end_to_end_402_cut_single_connection(self):
        opened = []

        def factory(target, timeout):
            conn = FakeConnection(402, {}, [ConnectionResetError("coupure")])
            opened.append(conn)
            return conn

        d, _, sleeps = discovery(transport=HttpsTransport(connection_factory=factory),
                                 max_attempts=3)
        result = d.discover()
        self.assertEqual(len(opened), 1)
        self.assertEqual(sleeps, [])
        self.assertEqual(len(result.payment_required), 1)
        self.assertIn("corps interrompu", result.payment_required[0].body_error)

    def test_402_too_large_is_observed_not_retried(self):
        conn = FakeConnection(402, {"content-length": "999999"}, [])
        d, _, _ = discovery(transport=HttpsTransport(connection_factory=conn.factory),
                            max_attempts=3, max_response_bytes=100)
        result = d.discover()
        self.assertEqual(len(result.payment_required), 1)
        self.assertIn("Content-Length", result.payment_required[0].body_error)

    def test_partial_200_not_retried(self):
        d, t, _ = discovery({"/s": PartialResponse(200, {}, "corps interrompu")}, max_attempts=3)
        result = d.discover()
        self.assertEqual(t.calls, ["/s"])
        self.assertIn("corps interrompu", result.errors[0])


# -- 2. échéance globale : DNS, réponse lente, attentes ------------------------

class DeadlineTests(unittest.TestCase):
    def test_blocked_dns_bounded_wait(self):
        release = threading.Event()

        def stuck_resolver(host, port):
            release.wait(10)
            return ["93.184.216.34"]

        d, t, _ = discovery({"/s": ok("[]")}, resolver=stuck_resolver,
                            total_deadline_s=0.3, timeout_s=5)
        start = time.monotonic()
        try:
            result = d.discover()
        finally:
            release.set()
        self.assertLess(time.monotonic() - start, 2.0)
        self.assertEqual(t.calls, [])
        self.assertIn("DNS", result.errors[0])

    def test_dns_wait_bounded_by_per_request_timeout(self):
        release = threading.Event()
        try:
            start = time.monotonic()
            with self.assertRaises(TimeoutError):
                resolve_within(lambda h, p: release.wait(10), HOST, 443, Deadline(0.2))
            self.assertLess(time.monotonic() - start, 1.5)
        finally:
            release.set()

    def test_slow_drip_body_stopped_at_deadline(self):
        def drip():
            time.sleep(0.05)
            return b" "
        conn = FakeConnection(200, {}, [drip] * 1000)
        start = time.monotonic()
        with self.assertRaises(PartialResponse) as ctx:
            HttpsTransport(connection_factory=conn.factory, chunk_size=1)(TARGET, Deadline(0.3), 10**6)
        self.assertLess(time.monotonic() - start, 1.5)
        self.assertIn("échéance", ctx.exception.reason)
        # le délai de socket est recalculé et décroît à chaque lecture
        self.assertTrue(all(b <= a + 1e-9 for a, b in zip(conn.timeouts[1:], conn.timeouts[2:])))

    def test_watchdog_aborts_blocked_read(self):
        conn = FakeConnection(200, {}, [])
        conn.response._script = [blocking_until_abort(conn)]
        start = time.monotonic()
        with self.assertRaises(PartialResponse):
            HttpsTransport(connection_factory=conn.factory)(TARGET, Deadline(0.2), 1000)
        self.assertTrue(conn.aborted.is_set())
        self.assertLess(time.monotonic() - start, 1.5)

    def test_backoff_never_sleeps_past_deadline(self):
        d, t, sleeps = discovery({"/s": RawResponse(503, {})}, max_attempts=3,
                                 backoff_s=60, total_deadline_s=1)
        result = d.discover()
        self.assertEqual(sleeps, [])
        self.assertEqual(t.calls, ["/s"])
        self.assertIn("503", result.errors[0])

    def test_per_request_deadline_never_exceeds_global(self):
        parent = Deadline(1.0)
        self.assertLessEqual(parent.child(50).expires_at, parent.expires_at)


class TransportDoubleTests(unittest.TestCase):
    def test_reads_chunks_lowercases_headers_and_sends_no_auth(self):
        conn = FakeConnection(200, {"Content-Type": "application/json"}, [b"[1,", b"2]"])
        resp = HttpsTransport(connection_factory=conn.factory)(TARGET, Deadline(5), 1000)
        self.assertEqual(resp.body, b"[1,2]")
        self.assertEqual(resp.headers, {"content-type": "application/json"})
        method, path, headers = conn.requests[0]
        self.assertEqual((method, path), ("GET", "/s"))
        self.assertFalse(any(k.lower() in ("authorization", "cookie") for k in headers))
        self.assertTrue(conn.closed)

    def test_streamed_body_over_limit(self):
        conn = FakeConnection(200, {}, [b"a" * 60, b"b" * 60])
        with self.assertRaises(ResponseTooLarge):
            HttpsTransport(connection_factory=conn.factory)(TARGET, Deadline(5), 100)

    def test_error_before_status_is_network_error(self):
        conn = FakeConnection(getresponse_error=ConnectionResetError("reset"))
        with self.assertRaises(ConnectionResetError):
            HttpsTransport(connection_factory=conn.factory)(TARGET, Deadline(5), 100)
        self.assertTrue(conn.closed)

    def test_expired_deadline_never_connects(self):
        conn = FakeConnection()
        with self.assertRaises(TimeoutError):
            HttpsTransport(connection_factory=conn.factory)(TARGET, Deadline(-1), 100)
        self.assertEqual(conn.requests, [])


# -- 3. décimaux JSON exacts ---------------------------------------------------

class LongDecimalTests(unittest.TestCase):
    def test_http_number_literal_kept_exact(self):
        body = '{"services": [{"name": "a", "price": {"amount": %s, "currency": "JETONTEST",' \
               ' "unit": "per_request"}}]}' % LONG
        d, _, _ = discovery({"/s": ok(body)})
        record = d.discover().records[0]
        self.assertEqual(record.price.amount, Decimal(LONG))
        self.assertEqual(record.warnings, [])

    def test_fixture_number_literal_kept_exact_in_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "f.json"
            path.write_text('{"_meta": {"fictif": true}, "services": [{"name": "a", '
                            '"price": {"amount": %s}}]}' % LONG)
            result = FixtureDiscovery(path).discover()
        self.assertEqual(result.records[0].price.amount, Decimal(LONG))
        exported = json.loads(json.dumps(result_to_dict(result)))
        self.assertEqual(exported["services"][0]["price"]["amount"], LONG)
        self.assertEqual(exported["services"][0]["raw"]["price"]["amount"], LONG)


# -- 4. couverture partielle et schémas invalides ------------------------------

class CoverageTests(unittest.TestCase):
    def test_invalid_schema_reported_not_empty_success(self):
        for body, needle in (('{"foo": 1}', "services"), ("42", "racine")):
            with self.subTest(body=body):
                result = discovery({"/s": ok(body)})[0].discover()
                self.assertIn("schéma invalide", result.errors[0])
                self.assertIn(needle, result.errors[0])
                self.assertEqual(coverage(result)["etat"], "echec")

    def test_partial_catalog(self):
        routes = {"/s": ok('{"services": [{"name": "a"}], "next": "/p2"}'),
                  "/p2": RawResponse(500, {})}
        result = discovery(routes, max_attempts=1)[0].discover()
        report = comparison_report(result)
        self.assertEqual(report["couverture"]["etat"], "partielle")
        self.assertEqual(report["couverture"]["services"], 1)
        self.assertTrue(any("500" in e for e in report["erreurs"]))

    def test_402_kept_in_comparison(self):
        result = discovery({"/s": RawResponse(402, {}, b'{"accepts": []}')})[0].discover()
        report = comparison_report(result)
        self.assertEqual(len(report["reponses_402_observees"]), 1)
        self.assertEqual(report["couverture"]["etat"], "echec")

    def test_bad_next_keeps_items_and_reports(self):
        result = discovery({"/s": ok('{"services": [{"name": "a"}], "next": 5}')})[0].discover()
        self.assertEqual(len(result.records), 1)
        self.assertEqual(coverage(result)["etat"], "partielle")

    def test_invalid_items_make_coverage_partial(self):
        result = discovery({"/s": ok('["texte", {"name": "a"}]')})[0].discover()
        self.assertEqual(coverage(result)["elements_invalides"], 1)
        self.assertEqual(coverage(result)["etat"], "partielle")

    def test_empty_is_not_success(self):
        cov = coverage(DiscoveryResult())
        self.assertEqual(cov["etat"], "vide")
        self.assertIn("PAS une réussite", cov["note"])

    def test_fixture_without_services_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "f.json"
            path.write_text('{"_meta": {"fictif": true}, "services": {"a": 1}}')
            result = FixtureDiscovery(path).discover()
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = main(["compare", "--fixture", str(path)])
        self.assertIn("schéma invalide", result.errors[0])
        self.assertEqual(code, EXIT_INCOMPLETE)
        report = json.loads(out.getvalue())
        self.assertEqual(report["couverture"]["etat"], "echec")
        self.assertTrue(report["erreurs"])

    def test_summary_shows_coverage(self):
        self.assertIn("Couverture : complete", summary_markdown(FixtureDiscovery().discover()))


# -- 5. paramètres sensibles des URL -------------------------------------------

class UrlRedactionTests(unittest.TestCase):
    URL = f"https://{HOST}/s?api_key=SECRET1&page=2&sig=SECRET2#access_token=SECRET3"

    def test_redact_url(self):
        out = redact_url(self.URL)
        for secret in ("SECRET1", "SECRET2", "SECRET3"):
            self.assertNotIn(secret, out)
        self.assertIn("page=2", out)
        self.assertNotIn("pw", redact_url(f"https://user:pw@{HOST}/"))

    def test_redact_text_inside_messages(self):
        out = redact_text(f"{self.URL}: statut HTTP 500")
        self.assertNotIn("SECRET1", out)
        self.assertIn("statut HTTP 500", out)

    def test_exports_and_source_uri_masked(self):
        url = f"https://{HOST}/s?token=SECRET4"
        routes = {"/s?token=SECRET4": ok('[{"name": "a"}]')}
        d = PublicHttpDiscovery(sources=[url], policy=HttpPolicy(allowed_hosts=frozenset({HOST})),
                                enabled=True, transport=ScriptedTransport(routes),
                                resolver=lambda h, p: ["93.184.216.34"])
        result = d.discover()
        result.errors.append(f"{url}: exemple d'erreur")
        text = json.dumps(result_to_dict(result), ensure_ascii=False) + summary_markdown(result) \
            + json.dumps(comparison_report(result), ensure_ascii=False)
        self.assertNotIn("SECRET4", text)
        self.assertIn(MASK, text)

    def test_logs_masked(self):
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.addFilter(RedactingFilter())
        logger = logging.getLogger("atelier_x402.http")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        try:
            d, _, _ = discovery({"/s?key=SECRET5": RawResponse(402, {})})
            d.sources = [f"https://{HOST}/s?key=SECRET5"]
            d.discover()
        finally:
            logger.removeHandler(handler)
        self.assertIn("402", stream.getvalue())
        self.assertNotIn("SECRET5", stream.getvalue())


# -- 6. coûts invalides ---------------------------------------------------------

POLICY = BudgetPolicy(session_cap=Decimal(1), per_call_cap=Decimal("0.05"), currency="JETONTEST")


def estimate(amount=Decimal("0.01"), quantity=Decimal(1)):
    return CostEstimate(True, amount, "JETONTEST", BillingUnit.PAR_REQUETE, quantity)


class InvalidCostTests(unittest.TestCase):
    def test_non_finite_negative_or_float_refused(self):
        cases = {
            "NaN": estimate(Decimal("NaN")),
            "sNaN": estimate(Decimal("sNaN")),
            "Infinity": estimate(Decimal("Infinity")),
            "négatif": estimate(Decimal("-0.01")),
            "float": estimate(0.01),
            "quantité infinie": estimate(quantity=Decimal("Infinity")),
            "quantité négative": estimate(quantity=Decimal(-1)),
        }
        for name, est in cases.items():
            with self.subTest(case=name):
                guard = CostGuard(POLICY)
                self.assertFalse(guard.authorize(est).allowed)
                hypo = guard.evaluate_hypothetical(est)
                self.assertFalse(hypo.allowed)
                self.assertTrue(any("refusé" in r for r in hypo.reasons))

    def test_invalid_caps_or_spent_refused(self):
        for policy, spent in ((BudgetPolicy(Decimal("NaN"), Decimal("0.05"), "JETONTEST"), Decimal(0)),
                              (BudgetPolicy(Decimal(1), Decimal(-1), "JETONTEST"), Decimal(0)),
                              (POLICY, Decimal("-5"))):
            with self.subTest(policy=policy, spent=spent):
                self.assertFalse(CostGuard(policy, spent=spent).evaluate_hypothetical(estimate()).allowed)

    def test_inconsistent_non_billable_refused(self):
        guard = CostGuard(POLICY)
        self.assertTrue(guard.authorize(NON_BILLABLE).allowed)
        for amount in (Decimal("0.5"), Decimal("NaN"), Decimal(-1)):
            with self.subTest(amount=amount):
                est = CostEstimate(False, amount, None, BillingUnit.PAR_REQUETE, Decimal(1))
                self.assertFalse(guard.authorize(est).allowed)

    def test_cli_check_cost_nan_refused(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(["check-cost", "--price", "NaN", "--currency", "JETONTEST",
                         "--unit", "per_request", "--per-call-cap", "Infinity",
                         "--budget-currency", "JETONTEST"])
        self.assertEqual(code, 0)
        self.assertFalse(json.loads(out.getvalue())["autorise"])

    def test_x402_infinite_atomic_amount_refused(self):
        body = {"accepts": [{"scheme": "exact", "network": "testnet-fictif",
                             "amount_atomic": "Infinity", "asset_symbol": "JETONTEST",
                             "asset_decimals": 6, "unit": "per_request"}]}
        step, _ = check_terms(body, frozenset({"testnet-fictif"}))
        self.assertEqual(step.status, "refus")


if __name__ == "__main__":
    unittest.main()
