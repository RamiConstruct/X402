"""Régressions de X402-001 révision 2 (revue dot), sans réseau.

P1 : l'abandon interrompt le socket actif (TLS compris), même après le
     détachement du socket brut par ``wrap_socket``.
P2 : un corps plus court que Content-Length est un corps tronqué.
P2 : l'export de simulation sérialise exactement les Decimal imbriqués.

Les sockets utilisés sont des paires locales (``socket.socketpair``) : aucune
connexion réseau, aucune résolution DNS.
"""

import contextlib
import http.client
import io
import json
import socket
import ssl
import tempfile
import threading
import time
import unittest
from decimal import Decimal
from pathlib import Path

from atelier_x402.cli import main
from atelier_x402.discovery.http_public import (
    Deadline,
    HttpsTransport,
    PartialResponse,
    _PinnedHTTPSConnection,
)
from atelier_x402.models import to_plain
from atelier_x402.report import coverage
from tests.test_x402_001 import TARGET, FakeConnection, discovery

BOUND_S = 3.0  # seuil large : le minuteur tire à 0,2 s, le socket attendrait 10 s


class SocketPairConnection(_PinnedHTTPSConnection):
    """Connexion épinglée dont le socket brut est un bout de paire locale."""

    def __init__(self, context, on_open=None):
        super().__init__(TARGET, timeout=10, context=context)
        self.raw, self.peer = socket.socketpair()
        self.raw.settimeout(10)
        self.on_open = on_open
        self.opened = False

    def _open_raw(self):
        self.opened = True
        if self.on_open:
            self.on_open(self)
        return self.raw


class _DetachedSocket(socket.socket):
    """Imite SSLSocket : nouvel objet qui reprend le descripteur détaché."""

    def do_handshake(self):
        return None


class DetachingContext:
    """Contexte factice : détache le socket brut comme le fait ``wrap_socket``."""

    def __init__(self, during_wrap=None):
        self.during_wrap = during_wrap

    def wrap_socket(self, sock, server_hostname=None, do_handshake_on_connect=True):
        wrapped = _DetachedSocket(fileno=sock.detach())
        wrapped.settimeout(10)
        if self.during_wrap:
            self.during_wrap()
        return wrapped


def abort_after(conn, delay=0.2):
    timer = threading.Timer(delay, conn.abort)
    timer.daemon = True
    timer.start()
    return timer


class TlsAbortTests(unittest.TestCase):
    def setUp(self):
        self.conns = []

    def tearDown(self):
        for conn in self.conns:
            for sock in (conn.sock, conn.raw, conn.peer):
                with contextlib.suppress(Exception):
                    sock.close()

    def make(self, context, **kw):
        conn = SocketPairConnection(context, **kw)
        self.conns.append(conn)
        return conn

    def test_abort_interrupts_real_tls_handshake(self):
        conn = self.make(ssl.create_default_context())
        abort_after(conn)
        start = time.monotonic()
        with self.assertRaises(OSError):  # ssl.SSLError hérite d'OSError
            conn.connect()  # le pair ne répond jamais au ClientHello
        self.assertLess(time.monotonic() - start, BOUND_S)
        # le socket brut a bien été détaché : l'ancien abort() agissait dans le vide
        self.assertEqual(conn.raw.fileno(), -1)
        self.assertIsInstance(conn._active, ssl.SSLSocket)
        self.assertIs(conn._active, conn.sock)

    def test_abort_interrupts_header_read_on_detached_active_socket(self):
        conn = self.make(DetachingContext())
        conn.connect()
        self.assertEqual(conn.raw.fileno(), -1)
        self.assertIsNot(conn.sock, conn.raw)
        conn.request("GET", "/s")
        abort_after(conn)
        start = time.monotonic()
        with self.assertRaises((OSError, http.client.HTTPException)):
            conn.getresponse()  # le pair n'envoie jamais d'en-têtes
        self.assertLess(time.monotonic() - start, BOUND_S)

    def test_abort_before_connect_opens_nothing(self):
        conn = self.make(DetachingContext())
        conn.abort()
        with self.assertRaises(TimeoutError):
            conn.connect()
        self.assertFalse(conn.opened)

    def test_abort_racing_raw_open_closes_raw(self):
        conn = self.make(DetachingContext(), on_open=lambda c: c.abort())
        with self.assertRaises(TimeoutError):
            conn.connect()
        self.assertEqual(conn.raw.fileno(), -1)

    def test_abort_racing_wrap_closes_wrapped_socket(self):
        holder = {}
        conn = self.make(DetachingContext(during_wrap=lambda: holder["c"].abort()))
        holder["c"] = conn
        with self.assertRaises(TimeoutError):
            conn.connect()
        self.assertIsNone(conn.sock)
        self.assertEqual(conn.raw.fileno(), -1)

    def test_transport_watchdog_end_to_end(self):
        conn = self.make(ssl.create_default_context())
        transport = HttpsTransport(connection_factory=lambda target, timeout: conn)
        start = time.monotonic()
        with self.assertRaises(OSError):
            transport(TARGET, Deadline(0.3), 1000)
        self.assertLess(time.monotonic() - start, BOUND_S)


class _FakeSock:
    def __init__(self, data):
        self.data = data

    def makefile(self, mode):
        return io.BufferedReader(io.BytesIO(self.data))


def real_http_response(raw):
    """Vraie ``http.client.HTTPResponse`` analysée depuis des octets en mémoire."""
    resp = http.client.HTTPResponse(_FakeSock(raw), method="GET")
    resp.begin()
    return resp


class FixedResponseConnection(FakeConnection):
    def __init__(self, response):
        super().__init__()
        self.real_response = response

    def getresponse(self):
        return self.real_response


class TruncatedBodyTests(unittest.TestCase):
    def test_http_client_read1_returns_empty_on_truncation(self):
        resp = real_http_response(b"HTTP/1.1 200 OK\r\nContent-Length: 50\r\n\r\n[]")
        self.assertEqual(resp.read1(100), b"[]")
        self.assertEqual(resp.read1(100), b"")  # aucune exception : à nous de vérifier

    def test_real_http_client_truncated_402(self):
        resp = real_http_response(
            b"HTTP/1.1 402 Payment Required\r\nContent-Length: 50\r\n\r\n{\"accepts\"")
        conn = FixedResponseConnection(resp)
        with self.assertRaises(PartialResponse) as ctx:
            HttpsTransport(connection_factory=conn.factory)(TARGET, Deadline(5), 1000)
        self.assertEqual(ctx.exception.status, 402)
        self.assertIn("tronqué", ctx.exception.reason)

    def test_real_http_client_exact_length_ok(self):
        resp = real_http_response(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n[]")
        conn = FixedResponseConnection(resp)
        result = HttpsTransport(connection_factory=conn.factory)(TARGET, Deadline(5), 1000)
        self.assertEqual(result.body, b"[]")

    def _single_connection(self, status, body, declared):
        opened = []

        def factory(target, timeout):
            conn = FakeConnection(status, {"content-length": str(declared)}, [body])
            opened.append(conn)
            return conn

        return opened, HttpsTransport(connection_factory=factory)

    def test_truncated_402_observed_without_retry(self):
        opened, transport = self._single_connection(402, b'{"accepts": [', 50)
        d, _, sleeps = discovery(transport=transport, max_attempts=3)
        result = d.discover()
        self.assertEqual(len(opened), 1)
        self.assertEqual(sleeps, [])
        self.assertIn("tronqué", result.payment_required[0].body_error)
        self.assertIsNone(result.payment_required[0].body)

    def test_truncated_503_not_retried(self):
        opened, transport = self._single_connection(503, b"erreur", 50)
        d, _, sleeps = discovery(transport=transport, max_attempts=3)
        result = d.discover()
        self.assertEqual(len(opened), 1)
        self.assertEqual(sleeps, [])
        self.assertIn("tronqué", result.errors[0])

    def test_valid_json_truncated_framing_never_complete(self):
        opened, transport = self._single_connection(200, b'[{"name": "a"}]', 100)
        result = discovery(transport=transport)[0].discover()
        self.assertEqual(result.records, [])
        self.assertIn("tronqué", result.errors[0])
        self.assertNotEqual(coverage(result)["etat"], "complete")


SCENARIOS_NUMERIC = """{
  "_meta": {"fictif": true},
  "testnets_simules": ["testnet-fictif"],
  "budget_hypothetique": {"per_call_cap": 0.05, "session_cap": 1.00,
                          "currency": "JETONTEST", "seuil_long": 0.1234567890123456789012345678901},
  "scenarios": {
    "ok": {
      "service": {"provider": "Fournisseur Fictif", "name": "demo", "note_prix": 0.10},
      "response": {"status": 402, "headers": {},
        "body": {"accepts": [{"scheme": "exact", "network": "testnet-fictif",
                              "amount_atomic": 2000, "asset_symbol": "JETONTEST",
                              "asset_decimals": 6, "unit": "per_request"}]}}
    }
  }
}"""


class SimulationExportTests(unittest.TestCase):
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(list(argv))
        return code, out.getvalue()

    def test_numeric_decimals_exported_exactly(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s.json"
            path.write_text(SCENARIOS_NUMERIC)
            out_path = Path(tmp) / "rapport.json"
            code, out = self.run_cli("simulate-x402", "--scenarios", str(path),
                                     "--scenario", "ok", "--out", str(out_path))
            written = out_path.read_text()
        self.assertEqual(code, 0)
        report = json.loads(out)
        auth = next(s for s in report["etapes"] if s["etape"] == "autorisation")
        budget = auth["details"]["evaluation_hypothetique"]["budget"]
        self.assertEqual(budget["per_call_cap"], "0.05")
        self.assertEqual(budget["session_cap"], "1.00")
        self.assertEqual(budget["seuil_long"], "0.1234567890123456789012345678901")
        self.assertEqual(report["etapes"][0]["details"]["service"]["note_prix"], "0.10")
        self.assertTrue(auth["details"]["evaluation_hypothetique"]["autorise"])
        self.assertEqual(report["issue"], "simule")
        self.assertEqual(json.loads(written), report)

    def test_numeric_decimals_all_scenarios(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s.json"
            path.write_text(SCENARIOS_NUMERIC)
            code, out = self.run_cli("simulate-x402", "--scenarios", str(path), "--all")
        self.assertEqual(code, 0)
        self.assertEqual(len(json.loads(out)), 1)

    def test_to_plain_exact_and_nested(self):
        value = {"a": [Decimal("0.10"), {"b": Decimal("1E-30")}], "c": (Decimal("2"),)}
        self.assertEqual(to_plain(value), {"a": ["0.10", {"b": "1E-30"}], "c": ["2"]})


if __name__ == "__main__":
    unittest.main()
