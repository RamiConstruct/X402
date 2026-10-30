"""Normalisation des descriptions brutes en ``ServiceRecord``.

Règles :

* un champ absent ou illisible reste ``None`` et apparaît dans ``unknowns`` ;
* la provenance est imposée par la source (fixture => fictif, HTTP =>
  déclaration commerciale). Une donnée brute qui *prétend* avoir été testée
  n'est jamais promue « testée » : seul un test exécuté par l'atelier le
  pourrait, et ce lot n'en exécute aucun ;
* aucune devise n'est déduite d'un symbole ambigu (« $ ») et aucune
  conversion n'est faite (USDC n'est pas USD).
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from .models import (
    BillingUnit,
    Category,
    Price,
    Provenance,
    ServiceRecord,
    Source,
    VerificationStatus,
)
from .redact import redact

_CATEGORY_ALIASES = {
    Category.TEXTE: {"texte", "text", "llm", "chat", "completion", "generation_texte"},
    Category.CODE: {"code", "coding", "code_generation"},
    Category.RECHERCHE: {"recherche", "search", "web_search", "retrieval"},
    Category.IMAGE: {"image", "images", "image_generation", "vision"},
    Category.AUDIO: {"audio", "speech", "tts", "stt", "transcription"},
    Category.EMBEDDINGS: {"embeddings", "embedding", "vectors"},
}

_UNIT_ALIASES = {
    BillingUnit.PAR_REQUETE: {"par_requete", "per_request", "request", "call", "per_call"},
    BillingUnit.PAR_1K_TOKENS: {"par_1k_tokens", "per_1k_tokens", "1k_tokens"},
    BillingUnit.PAR_1M_TOKENS: {"par_1m_tokens", "per_1m_tokens", "1m_tokens"},
    BillingUnit.PAR_IMAGE: {"par_image", "per_image", "image"},
    BillingUnit.PAR_MINUTE_AUDIO: {"par_minute_audio", "per_audio_minute", "per_minute"},
    BillingUnit.PAR_SECONDE: {"par_seconde", "per_second"},
}

_CURRENCY_CODE = re.compile(r"^[A-Z][A-Z0-9]{2,9}$")
_AMBIGUOUS_SYMBOLS = {"$", "€", "£", "¥"}

_TESTED_CLAIMS = {"tested", "teste", "teste_reellement", "verified", "verifie", "verifie_par_test"}


def _key(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return value.strip().lower().replace("-", "_").replace(" ", "_") or None


def normalize_category(raw: Any) -> Category:
    key = _key(raw)
    for category, aliases in _CATEGORY_ALIASES.items():
        if key in aliases:
            return category
    return Category.INCONNUE


def normalize_unit(raw: Any) -> BillingUnit | None:
    key = _key(raw)
    for unit, aliases in _UNIT_ALIASES.items():
        if key in aliases:
            return unit
    return None


def parse_amount(raw: Any, warnings: list[str]) -> tuple[Decimal | None, str | None]:
    """Retourne (montant, symbole_detecte).

    Les lecteurs JSON de l'atelier utilisent ``parse_float=Decimal`` : un montant
    JSON arrive donc ici en ``Decimal`` exact. Un ``float`` ne peut venir que
    d'un appel Python direct ; il est accepté avec un avertissement.
    """
    if raw is None or isinstance(raw, bool):
        return None, None
    symbol = None
    if isinstance(raw, Decimal):
        text = str(raw)
    elif isinstance(raw, int):
        text = str(raw)
    elif isinstance(raw, float):
        warnings.append("montant reçu en flottant: précision d'origine non garantie")
        text = repr(raw)
    elif isinstance(raw, str):
        text = raw.strip()
        if text[:1] in _AMBIGUOUS_SYMBOLS:
            symbol, text = text[0], text[1:].strip()
    else:
        warnings.append(f"montant de type inattendu: {type(raw).__name__}")
        return None, None
    try:
        amount = Decimal(text)
    except InvalidOperation:
        warnings.append(f"montant illisible: {raw!r}")
        return None, symbol
    if not amount.is_finite() or amount < 0:
        warnings.append(f"montant invalide: {raw!r}")
        return None, symbol
    return amount, symbol


def normalize_currency(raw: Any, symbol: str | None, warnings: list[str]) -> str | None:
    if isinstance(raw, str) and raw.strip():
        code = raw.strip().upper()
        if _CURRENCY_CODE.match(code):
            return code
        warnings.append(f"devise non reconnue conservée comme inconnue: {raw!r}")
        return None
    if symbol:
        warnings.append(f"symbole {symbol!r} ambigu: devise non confirmée")
    return None


def normalize_timestamp(raw: Any, warnings: list[str]) -> str | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        warnings.append(f"date illisible: {raw!r}")
        return None
    if parsed.tzinfo is None:
        warnings.append("date sans fuseau: conservée comme inconnue (UTC non garanti)")
        return None
    return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _text(item: dict, *keys: str) -> str | None:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _record_id(source: Source, item: Any) -> str:
    payload = json.dumps(item, sort_keys=True, default=str) + source.uri
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def normalize_item(item: Any, source: Source, provenance: Provenance) -> ServiceRecord:
    if provenance is Provenance.TESTE_REELLEMENT:
        raise ValueError(
            "la provenance « teste_reellement » ne peut pas venir d'une description: "
            "elle exige une preuve de test produite par l'atelier"
        )
    warnings: list[str] = []
    if not isinstance(item, dict):
        warnings.append("élément non objet: conservé tel quel")
        item_dict: dict = {}
    else:
        item_dict = item

    price_raw = item_dict.get("price")
    price_obj = price_raw if isinstance(price_raw, dict) else {"amount": price_raw}
    amount, symbol = parse_amount(price_obj.get("amount"), warnings)
    currency = normalize_currency(price_obj.get("currency"), symbol, warnings)
    unit_raw = price_obj.get("unit")
    unit = normalize_unit(unit_raw)
    if unit_raw is not None and unit is None:
        warnings.append(f"unité de facturation non reconnue: {unit_raw!r}")

    capability_raw = item_dict.get("capability")
    capability = normalize_category(capability_raw)
    if capability_raw is not None and capability is Category.INCONNUE:
        warnings.append(f"capacité hors catégories connues: {capability_raw!r}")

    claimed = _key(item_dict.get("verification_status")) or _key(item_dict.get("status"))
    if claimed in _TESTED_CLAIMS:
        warnings.append(
            "la source se déclare « testée »: ignoré, aucun test exécuté par l'atelier"
        )

    payment = item_dict.get("payment") if isinstance(item_dict.get("payment"), dict) else {}

    record = ServiceRecord(
        record_id=_record_id(source, item),
        provider=_text(item_dict, "provider", "vendor"),
        service_name=_text(item_dict, "name", "service_name"),
        capability=capability,
        capability_raw=capability_raw,
        source=source,
        observed_at_utc=normalize_timestamp(item_dict.get("observed_at"), warnings),
        price=Price(amount=amount, currency=currency, unit=unit, raw=redact(price_raw)),
        payment_protocol=_text(payment, "protocol"),
        network=_text(payment, "network"),
        provenance=provenance,
        verification_status=VerificationStatus.NON_VERIFIE,
        warnings=warnings,
        raw=redact(item),
    )
    record.unknowns = _unknowns(record)
    return record


def _unknowns(record: ServiceRecord) -> list[str]:
    checks = {
        "provider": record.provider,
        "service_name": record.service_name,
        "capability": None if record.capability is Category.INCONNUE else record.capability,
        "observed_at_utc": record.observed_at_utc,
        "price.amount": record.price.amount,
        "price.currency": record.price.currency,
        "price.unit": record.price.unit,
        "payment_protocol": record.payment_protocol,
        "network": record.network,
    }
    return [name for name, value in checks.items() if value is None]
