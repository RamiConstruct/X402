"""Achat de crédits par Stripe Checkout (Stripe simulé : aucun vrai paiement)."""
import hashlib
import hmac
import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from studio import billing
from studio.api import create_app
from studio.config import Settings
from studio.service import Studio

WH = "whsec_test_secret"


def signed(payload: bytes, secret: str = WH, t: int | None = None) -> str:
    t = t or int(time.time())
    sig = hmac.new(secret.encode(), f"{t}.".encode() + payload, hashlib.sha256).hexdigest()
    return f"t={t},v1={sig}"


@pytest.fixture
def stripe_app(tmp_path, monkeypatch):
    seen = {}

    def handler(req: httpx.Request):
        seen["auth"] = req.headers["authorization"]
        seen["form"] = dict(httpx.QueryParams(req.content.decode()))
        return httpx.Response(200, json={"id": "cs_test_1", "url": "https://checkout.stripe.com/c/pay/cs_test_1"})

    monkeypatch.setattr(billing, "_client", lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    st = Settings(data_dir=tmp_path / "d", secret_key="k", dev_mode=False, signup_credits=0, run_worker=False,
                  stripe_secret_key="sk_test_x", stripe_webhook_secret=WH, public_base_url="https://studio.example")
    studio = Studio(st)
    c = TestClient(create_app(st, studio))
    tok = c.post("/api/auth/register", json={"email": "a@b.co", "password": "motdepasse123", "invite": ""}).json()["token"]
    return c, {"Authorization": f"Bearer {tok}"}, seen


def test_packs_and_checkout(stripe_app):
    c, h, seen = stripe_app
    packs = c.get("/api/billing/packs", headers=h).json()
    assert packs["enabled"] and [p["credits"] for p in packs["packs"]] == [500, 2000, 5000]
    r = c.post("/api/billing/checkout", json={"pack": "p2000"}, headers=h)
    assert r.status_code == 200 and r.json()["url"].startswith("https://checkout.stripe.com/")
    f = seen["form"]
    assert seen["auth"] == "Bearer sk_test_x"
    assert f["mode"] == "payment" and f["line_items[0][price_data][unit_amount]"] == "2000"
    assert f["metadata[credits]"] == "2000" and f["client_reference_id"].startswith("usr")
    assert f["success_url"].startswith("https://studio.example/")
    assert c.post("/api/billing/checkout", json={"pack": "zzz"}, headers=h).status_code == 400


def _event(uid: str, sid: str = "cs_test_1", paid: bool = True, credits: int = 2000) -> bytes:
    return json.dumps({"id": "evt_1", "type": "checkout.session.completed", "data": {"object": {
        "id": sid, "client_reference_id": uid, "payment_status": "paid" if paid else "unpaid",
        "metadata": {"credits": str(credits), "user_id": uid}}}}).encode()


def test_webhook_credits_once(stripe_app):
    c, h, _ = stripe_app
    uid = c.get("/api/me", headers=h).json()["user_id"] if "user_id" in c.get("/api/me", headers=h).json() else None
    me = c.get("/api/me", headers=h).json()
    uid = uid or me.get("id")
    body = _event(uid)
    r = c.post("/api/billing/webhook", content=body, headers={"stripe-signature": signed(body)})
    assert r.status_code == 200
    assert c.get("/api/me", headers=h).json()["credits_available"] == 2000
    # Stripe renvoie le même événement : pas de double crédit
    c.post("/api/billing/webhook", content=body, headers={"stripe-signature": signed(body)})
    assert c.get("/api/me", headers=h).json()["credits_available"] == 2000


def test_webhook_rejects_forgery_and_unpaid(stripe_app):
    c, h, _ = stripe_app
    uid = c.get("/api/me", headers=h).json().get("id")
    body = _event(uid, sid="cs_x")
    assert c.post("/api/billing/webhook", content=body, headers={"stripe-signature": signed(body, "whsec_faux")}).status_code == 400
    old = signed(body, t=int(time.time()) - 3600)
    assert c.post("/api/billing/webhook", content=body, headers={"stripe-signature": old}).status_code == 400  # rejoué trop tard
    unpaid = _event(uid, sid="cs_y", paid=False)
    c.post("/api/billing/webhook", content=unpaid, headers={"stripe-signature": signed(unpaid)})
    assert c.get("/api/me", headers=h).json()["credits_available"] == 0


def test_disabled_without_keys(client):
    tok = client.post("/api/auth/register", json={"email": "z@b.co", "password": "motdepasse123", "invite": ""}).json()["token"]
    h = {"Authorization": f"Bearer {tok}"}
    assert client.get("/api/billing/packs", headers=h).json()["enabled"] is False
    assert client.post("/api/billing/checkout", json={"pack": "p500"}, headers=h).status_code == 503
