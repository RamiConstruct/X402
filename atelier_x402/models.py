"""Modèle normalisé d'une description de service.

Trois notions sont volontairement séparées :

* ``Provenance`` : d'où vient l'information (fixture fictive, déclaration
  commerciale publiée par un tiers, résultat d'un test réellement exécuté).
* ``VerificationStatus`` : ce que l'atelier a réellement vérifié.
* Les champs inconnus restent ``None`` et sont listés dans ``unknowns`` ;
  rien n'est deviné ni complété par défaut.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any


class Provenance(str, Enum):
    FICTIF = "fictif"
    DECLARATION_COMMERCIALE = "declaration_commerciale"
    TESTE_REELLEMENT = "teste_reellement"


class VerificationStatus(str, Enum):
    NON_VERIFIE = "non_verifie"
    SIMULATION_OK = "simulation_ok"
    VERIFIE_PAR_TEST = "verifie_par_test"
    ECHEC_TEST = "echec_test"


class Category(str, Enum):
    TEXTE = "texte"
    CODE = "code"
    RECHERCHE = "recherche"
    IMAGE = "image"
    AUDIO = "audio"
    EMBEDDINGS = "embeddings"
    INCONNUE = "inconnue"


class BillingUnit(str, Enum):
    PAR_REQUETE = "par_requete"
    PAR_1K_TOKENS = "par_1k_tokens"
    PAR_1M_TOKENS = "par_1m_tokens"
    PAR_IMAGE = "par_image"
    PAR_MINUTE_AUDIO = "par_minute_audio"
    PAR_SECONDE = "par_seconde"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(frozen=True)
class Price:
    """Prix déclaré. ``amount`` est un Decimal ; jamais de conversion de devise."""

    amount: Decimal | None = None
    currency: str | None = None
    unit: BillingUnit | None = None
    raw: Any = None

    @property
    def is_complete(self) -> bool:
        return None not in (self.amount, self.currency, self.unit)


@dataclass(frozen=True)
class Source:
    kind: str  # "fixture" | "http"
    uri: str
    retrieved_at_utc: str


@dataclass
class ServiceRecord:
    record_id: str
    provider: str | None
    service_name: str | None
    capability: Category
    capability_raw: Any
    source: Source
    observed_at_utc: str | None
    price: Price
    payment_protocol: str | None
    network: str | None
    provenance: Provenance
    verification_status: VerificationStatus
    unknowns: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    raw: Any = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["capability"] = self.capability.value
        data["provenance"] = self.provenance.value
        data["verification_status"] = self.verification_status.value
        data["price"] = {
            "amount": None if self.price.amount is None else str(self.price.amount),
            "currency": self.price.currency,
            "unit": None if self.price.unit is None else self.price.unit.value,
            "raw": self.price.raw,
        }
        return data
