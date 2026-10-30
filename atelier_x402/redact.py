"""Masquage des secrets avant tout stockage, journal ou rapport.

Le masquage est volontairement large : mieux vaut masquer une valeur publique
(par ex. un hash de transaction) que laisser passer une clé.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import unquote_plus, urlsplit, urlunsplit

MASK = "[MASQUÉ]"

_SENSITIVE_KEY = re.compile(
    r"(api[_-]?key|secret|token|password|passwd|authorization|auth|cookie|"
    r"private|priv[_-]?key|mnemonic|seed|signature|payment[_-]?signature|"
    r"x[_-]?payment|credential|bearer)",
    re.IGNORECASE,
)

_SENSITIVE_VALUE = [
    re.compile(r"0x[0-9a-fA-F]{64}"),  # clé privée EVM ou équivalent 32 octets
    re.compile(r"\bsk-[A-Za-z0-9_\-]{12,}"),  # format courant de clé API
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-~+/=]{8,}"),
    re.compile(r"\b(?:[a-z]{3,8}\s+){11,23}[a-z]{3,8}\b"),  # phrase mnémonique probable
]


_URL = re.compile(r"\b[a-zA-Z][a-zA-Z0-9+.\-]*://[^\s\"'<>]+")
_SENSITIVE_PARAMS = {"key", "sig", "sign", "pwd", "pass", "session", "sessionid", "sid",
                     "jwt", "code", "state", "nonce", "hmac"}


def _sensitive_param(name: str) -> bool:
    lowered = unquote_plus(name).strip().lower()
    return lowered in _SENSITIVE_PARAMS or bool(_SENSITIVE_KEY.search(lowered))


def _redact_params(params: str) -> str:
    if "=" not in params:
        return params
    out = []
    for segment in params.split("&"):
        name, sep, _value = segment.partition("=")
        out.append(f"{name}={MASK}" if sep and _sensitive_param(name) else segment)
    return "&".join(out)


def redact_url(url: str) -> str:
    """Masque identifiants, paramètres de requête et de fragment sensibles."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return MASK
    netloc = parts.netloc
    if "@" in netloc:
        netloc = f"{MASK}@{netloc.rsplit('@', 1)[1]}"
    return urlunsplit((parts.scheme, netloc, parts.path,
                       _redact_params(parts.query), _redact_params(parts.fragment)))


def redact_text(text: str) -> str:
    text = _URL.sub(lambda m: redact_url(m.group(0)), text)
    for pattern in _SENSITIVE_VALUE:
        text = pattern.sub(MASK, text)
    return text


def redact(value: Any) -> Any:
    """Copie récursive de ``value`` avec les secrets masqués."""
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if isinstance(key, str) and _SENSITIVE_KEY.search(key):
                out[key] = MASK
            else:
                out[key] = redact(item)
        return out
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


class RedactingFilter(logging.Filter):
    """Filtre de journalisation : masque les secrets dans chaque message."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_text(record.getMessage())
        record.args = ()
        return True


def install_log_redaction(logger: logging.Logger | None = None) -> None:
    """Pose le filtre sur les handlers : il couvre aussi les journaux enfants."""
    target = logger or logging.getLogger()
    for handler in target.handlers:
        if not any(isinstance(f, RedactingFilter) for f in handler.filters):
            handler.addFilter(RedactingFilter())
