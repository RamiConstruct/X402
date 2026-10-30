import itertools
import json
import unittest

from atelier_x402.discovery import DiscoveryDisabled, HttpPolicy, PublicHttpDiscovery
from atelier_x402.discovery.http_public import PartialResponse, RawResponse, ResponseTooLarge
from atelier_x402.discovery.netguard import DestinationRefused, validate_url
from atelier_x402.models import Provenance
from atelier_x402.redact import MASK

HOST = "catalogue.exemple-fictif.org"
PUBLIC_IP = "93.184.216.34"


def resolver_for(mapping):
    def resolve(host, _port):
        return mapping.get(host, [PUBLIC_IP])
    return resolve


class FakeTransport:
    """Transport sans réseau : sert des réponses scriptées par chemin."""

    def __init__(self, routes):
        self.routes = routes  # chemin -> RawResponse | liste | exception
        self.calls = []

    def __call__(self, target, deadline, max_bytes):
        self.calls.append((target.host, target.path, target.address, deadline.remaining()))
        value = self.routes[target.path]
        if isinstance(value, list):
            value = value.pop(0) if len(value) > 1 else value[0]
        if isinstance(value, Exception):
            raise value
        if len(value.body) > max_bytes:
            raise ResponseTooLarge(value.status, value.headers, "trop gros")
        return value


def ok(payload):
    return RawResponse(200, {"content-type": "application/json"}, json.dumps(payload).encode())


def make(routes, sources=("https://%s/s" % HOST,), resolver=None, **policy):
    transport = FakeTransport(routes)
    policy.setdefault("allowed_hosts", frozenset({HOST, "autre.exemple-fictif.org"}))
    sleeps = []
    discovery = PublicHttpDiscovery(
        sources=list(sources), policy=HttpPolicy(**policy), enabled=True,
        transport=transport, resolver=resolver or resolver_for({}), sleep=sleeps.append,
    )
    return discovery, transport, sleeps


class DisabledByDefaultTests(unittest.TestCase):
    def test_disabled_by_default(self):
        d = PublicHttpDiscovery(sources=["https://%s/" % HOST], policy=HttpPolicy())
        with self.assertRaises(DiscoveryDisabled):
            d.discover()


class DestinationTests(unittest.TestCase):
    allowed = frozenset({HOST, "localhost", "box.local"})

    def check_refused(self, url, mapping=None):
        with self.assertRaises(DestinationRefused):
            validate_url(url, self.allowed, resolver_for(mapping or {}))

    def test_https_only(self):
        self.check_refused("http://%s/" % HOST)
        self.check_refused("ftp://%s/" % HOST)

    def test_host_not_allowlisted(self):
        self.check_refused("https://inconnu.exemple-fictif.org/")

    def test_local_names(self):
        self.check_refused("https://localhost/")
        self.check_refused("https://box.local/")

    def test_literal_ip_refused(self):
        self.check_refused("https://127.0.0.1/")
        self.check_refused("https://[::1]/")

    def test_private_resolutions_refused(self):
        for address in ("127.0.0.1", "10.0.0.5", "192.168.1.1", "172.16.0.1",
                        "169.254.169.254", "100.64.0.1", "::1", "fe80::1", "fc00::1",
                        "::ffff:127.0.0.1", "0.0.0.0", "224.0.0.1"):
            with self.subTest(address=address):
                self.check_refused("https://%s/" % HOST, {HOST: [address]})

    def test_mixed_public_private_refused(self):
        self.check_refused("https://%s/" % HOST, {HOST: [PUBLIC_IP, "10.0.0.1"]})

    def test_port_and_credentials(self):
        self.check_refused("https://%s:8443/" % HOST)
        self.check_refused("https://user:pw@%s/" % HOST)

    def test_valid_target_pins_address(self):
        t = validate_url("https://%s/x?p=1" % HOST, self.allowed, resolver_for({}))
        self.assertEqual((t.address, t.path), (PUBLIC_IP, "/x?p=1"))


class LimitsTests(unittest.TestCase):
    def test_records_are_commercial_declarations(self):
        d, _, _ = make({"/s": ok({"services": [{"name": "a", "status": "tested"}]})})
        result = d.discover()
        self.assertEqual(len(result.records), 1)
        self.assertIs(result.records[0].provenance, Provenance.DECLARATION_COMMERCIALE)
        self.assertEqual(result.records[0].verification_status.value, "non_verifie")

    def test_connection_uses_validated_address(self):
        d, t, _ = make({"/s": ok([])})
        d.discover()
        self.assertEqual(t.calls[0][2], PUBLIC_IP)

    def test_response_too_large(self):
        d, _, _ = make({"/s": ok({"services": [{"name": "x" * 500}]})}, max_response_bytes=100)
        result = d.discover()
        self.assertEqual(result.records, [])
        self.assertIn("ResponseTooLarge", result.errors[0])

    def test_pagination_limited(self):
        routes = {"/s": ok({"services": [{"name": "1"}], "next": "/p2"}),
                  "/p2": ok({"services": [{"name": "2"}], "next": "/p3"}),
                  "/p3": ok({"services": [{"name": "3"}]})}
        d, t, _ = make(routes, max_pages=2)
        result = d.discover()
        self.assertEqual(len(result.records), 2)
        self.assertEqual(len(t.calls), 2)
        self.assertTrue(any("pages" in e for e in result.errors))

    def test_pagination_loop_detected(self):
        d, t, _ = make({"/s": ok({"services": [], "next": "/s"})}, max_pages=5)
        result = d.discover()
        self.assertEqual(len(t.calls), 1)
        self.assertTrue(any("boucle" in e for e in result.errors))

    def test_pagination_to_foreign_host_refused(self):
        d, t, _ = make({"/s": ok({"services": [], "next": "https://evil.exemple-fictif.org/"})})
        result = d.discover()
        self.assertEqual(len(t.calls), 1)
        self.assertTrue(any("liste blanche" in e for e in result.errors))

    def test_max_items(self):
        d, _, _ = make({"/s": ok({"services": [{"name": str(i)} for i in range(10)]})},
                       max_items=3)
        self.assertEqual(len(d.discover().records), 3)

    def test_max_sources(self):
        sources = ["https://%s/s" % HOST] * 5
        d, t, _ = make({"/s": ok([])}, sources=sources, max_sources=2)
        result = d.discover()
        self.assertEqual(len(t.calls), 2)
        self.assertTrue(any("limite 2" in e for e in result.errors))

    def test_retries_limited_on_5xx(self):
        d, t, sleeps = make({"/s": [RawResponse(503, {}), RawResponse(503, {}),
                                    RawResponse(503, {})]}, max_attempts=2)
        result = d.discover()
        self.assertEqual(len(t.calls), 2)
        self.assertEqual(len(sleeps), 1)
        self.assertIn("503", result.errors[0])

    def test_retry_then_success(self):
        d, t, _ = make({"/s": [TimeoutError("lent"), ok([{"name": "a"}])]}, max_attempts=2)
        self.assertEqual(len(d.discover().records), 1)
        self.assertEqual(len(t.calls), 2)

    def test_no_retry_on_4xx(self):
        d, t, _ = make({"/s": RawResponse(404, {})}, max_attempts=3)
        d.discover()
        self.assertEqual(len(t.calls), 1)

    def test_global_deadline(self):
        clock = itertools.chain([0.0], itertools.repeat(100.0))
        d, t, _ = make({"/s": ok([])}, total_deadline_s=10)
        d.clock = lambda: next(clock)
        result = d.discover()
        self.assertEqual(t.calls, [])
        self.assertIn("échéance", result.errors[0])

    def test_timeout_bounded_by_policy(self):
        d, t, _ = make({"/s": ok([])}, timeout_s=2.0)
        d.discover()
        self.assertLessEqual(t.calls[0][3], 2.0)


class RedirectTests(unittest.TestCase):
    def redirect(self, location, status=302):
        return RawResponse(status, {"location": location})

    def test_same_host_redirect_allowed(self):
        d, t, _ = make({"/s": self.redirect("/v2"), "/v2": ok([{"name": "a"}])})
        result = d.discover()
        self.assertEqual(len(result.records), 1)
        self.assertEqual(result.records[0].source.uri, "https://%s/v2" % HOST)

    def test_cross_host_redirect_refused_even_if_allowlisted(self):
        d, t, _ = make({"/s": self.redirect("https://autre.exemple-fictif.org/x")})
        result = d.discover()
        self.assertEqual(len(t.calls), 1)
        self.assertTrue(any("inter-hôtes" in e for e in result.errors))

    def test_redirect_to_private_refused(self):
        d, t, _ = make({"/s": self.redirect("https://127.0.0.1/admin")})
        result = d.discover()
        self.assertEqual(len(t.calls), 1)
        self.assertTrue(result.errors)

    def test_redirect_to_http_refused(self):
        d, t, _ = make({"/s": self.redirect("http://%s/x" % HOST)})
        self.assertTrue(any("HTTPS" in e for e in d.discover().errors))

    def test_too_many_redirects(self):
        d, t, _ = make({"/s": self.redirect("/a"), "/a": self.redirect("/b"),
                        "/b": ok([])}, max_redirects=1)
        result = d.discover()
        self.assertEqual(len(t.calls), 2)
        self.assertTrue(any("trop de redirections" in e for e in result.errors))

    def test_redirect_without_location(self):
        d, _, _ = make({"/s": RawResponse(301, {})})
        self.assertTrue(any("sans Location" in e for e in d.discover().errors))


class PaymentRequiredTests(unittest.TestCase):
    def test_402_stops_and_observes_without_retry(self):
        body = {"accepts": [{"scheme": "exact", "network": "testnet-fictif"}]}
        resp = RawResponse(402, {"payment-required": "abc",
                                 "authorization": "Bearer abcdefghijkl"},
                           json.dumps(body).encode())
        routes = {"/s": resp, "/p2": ok([{"name": "jamais"}])}
        d, t, sleeps = make(routes, max_attempts=3)
        result = d.discover()
        self.assertEqual(len(t.calls), 1)        # aucun réessai
        self.assertEqual(sleeps, [])
        self.assertEqual(result.records, [])
        self.assertEqual(len(result.payment_required), 1)
        obs = result.payment_required[0]
        self.assertEqual(obs.action, "arret_observation_sans_paiement")
        self.assertEqual(obs.body, body)
        self.assertEqual(obs.headers["authorization"], MASK)

    def test_402_on_second_page_keeps_first_page(self):
        routes = {"/s": ok({"services": [{"name": "a"}], "next": "/p2"}),
                  "/p2": RawResponse(402, {}, b"pas du json")}
        d, t, _ = make(routes)
        result = d.discover()
        self.assertEqual(len(result.records), 1)
        self.assertEqual(result.payment_required[0].body["non_json"], True)


if __name__ == "__main__":
    unittest.main()
