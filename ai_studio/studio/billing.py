"""Achat de crédits par Stripe Checkout (inactif tant que les clés Stripe ne sont pas configurées).

Flux : le client choisit un pack → POST /api/billing/checkout crée une session Stripe Checkout et
renvoie son adresse → le client paie chez Stripe → Stripe appelle POST /api/billing/webhook
(événement « checkout.session.completed », signé) → les crédits sont ajoutés au grand livre,
une seule fois même si Stripe renvoie l'événement (clé d'idempotence = identifiant de session).
Aucune donnée de carte ne transite par nos serveurs.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time

import httpx

# 1 crédit = 0,01 USD : les packs sont vendus à leur valeur faciale (la marge est déjà dans le prix des moteurs).
PACKS = {
    "p500": {"credits": 500, "amount_cents": 500, "currency": "usd"},
    "p2000": {"credits": 2000, "amount_cents": 2000, "currency": "usd"},
    "p5000": {"credits": 5000, "amount_cents": 5000, "currency": "usd"},
}
API = "https://api.stripe.com/v1"
TOLERANCE_S = 300


class BillingError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def _client() -> httpx.Client:
    return httpx.Client(timeout=20)


def create_checkout(secret_key: str, *, pack_id: str, user_id: str, email: str, base_url: str) -> dict:
    pack = PACKS.get(pack_id)
    if not pack:
        raise BillingError("pack inconnu")
    form = {
        "mode": "payment",
        "line_items[0][quantity]": "1",
        "line_items[0][price_data][currency]": pack["currency"],
        "line_items[0][price_data][unit_amount]": str(pack["amount_cents"]),
        "line_items[0][price_data][product_data][name]": f"{pack['credits']} crédits AI Studio",
        "client_reference_id": user_id,
        "customer_email": email,
        "metadata[credits]": str(pack["credits"]),
        "metadata[user_id]": user_id,
        "metadata[pack]": pack_id,
        "success_url": f"{base_url}/?achat=ok",
        "cancel_url": f"{base_url}/?achat=annule",
    }
    with _client() as c:
        r = c.post(f"{API}/checkout/sessions", data=form, headers={"Authorization": f"Bearer {secret_key}"})
    if r.status_code >= 400:
        raise BillingError(f"Stripe a refusé la création du paiement ({r.status_code})", 502)
    d = r.json()
    return {"id": d["id"], "url": d["url"]}


def verify_event(payload: bytes, sig_header: str, secret: str, now: float | None = None) -> dict:
    """Vérifie la signature Stripe (HMAC-SHA256 de « t.payload ») et la fraîcheur de l'événement."""
    parts = dict(p.split("=", 1) for p in (sig_header or "").split(",") if "=" in p)
    try:
        t = int(parts.get("t", ""))
    except ValueError:
        raise BillingError("signature Stripe invalide")
    v1s = [v for k, v in (p.split("=", 1) for p in sig_header.split(",") if "=" in p) if k == "v1"]
    expected = hmac.new(secret.encode(), f"{t}.".encode() + payload, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, v) for v in v1s):
        raise BillingError("signature Stripe invalide")
    if abs((now or time.time()) - t) > TOLERANCE_S:
        raise BillingError("événement Stripe trop ancien")
    return json.loads(payload)


def paid_session(event: dict) -> tuple[str, str, int] | None:
    """(identifiant de session, utilisateur, crédits) si l'événement est un paiement réussi, sinon None."""
    if event.get("type") not in ("checkout.session.completed", "checkout.session.async_payment_succeeded"):
        return None
    o = (event.get("data") or {}).get("object") or {}
    if o.get("payment_status") != "paid":
        return None
    meta = o.get("metadata") or {}
    uid = o.get("client_reference_id") or meta.get("user_id")
    try:
        credits = int(meta.get("credits", "0"))
    except ValueError:
        return None
    if not uid or credits <= 0 or meta.get("pack") not in (None, *PACKS) or credits > 100_000:
        return None
    return o["id"], uid, credits
