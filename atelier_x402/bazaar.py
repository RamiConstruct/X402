"""Adaptateurs hors ligne pour les réponses de découverte Bazaar (x402 v2).

Formats couverts — et seulement eux — d'après x402-foundation/x402 au commit
14bc0fbf784914a6eb24bf87cdcd8d827e2b3ff3 :

* liste ``GET /discovery/resources`` :
  ``{x402Version, items[], pagination{limit, offset, total}}``
  (``typescript/packages/extensions/src/bazaar/facilitatorClient.ts``) ;
* recherche ``GET /discovery/search`` :
  ``{x402Version, resources[], partialResults?, pagination?{limit, cursor}|null}``
  (même fichier et ``specs/extensions/bazaar.md``). La documentation
  (``docs/extensions/bazaar.mdx``) indique que la pagination de recherche dépend
  du facilitateur : certains placent ``limit``/``cursor`` à la racine, d'autres
  les omettent. Cette variante racine est reconnue et signalée comme telle ;
* éléments ``DiscoveryResource`` : ``resource, type, x402Version, accepts[],
  lastUpdated`` et champs optionnels, extension ``bazaar`` (``info``/``schema``).

Garanties :

* fonctions pures sur des données déjà chargées : aucun appel réseau, aucune
  ressource ni outil appelé, aucune référence de schéma externe résolue ;
* toutes les offres ``accepts`` sont conservées, sans « première offre »
  privilégiée ; ``amount`` reste une chaîne d'entier exacte ; aucune décimale
  d'actif ni conversion USD n'est supposée ;
* une enveloppe contradictoire (``items`` ET ``resources``) est rejetée ;
* les exemples officiels ne prouvent ni disponibilité ni demande commerciale.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from .costs import CostEstimate
from .models import Provenance, to_plain
from .redact import redact

SUPPORTED_VERSION = 2
SOURCE_COMMIT = "14bc0fbf784914a6eb24bf87cdcd8d827e2b3ff3"

_ATOMIC = re.compile(r"^[0-9]+$")
_PRINTABLE_ASCII = re.compile(r"^[\x20-\x7e]+$")
_LOCAL_HOSTS = {"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback"}
COMPARABLE_SCHEMES = frozenset({"exact"})  # « upto » est un plafond, pas un coût final


@dataclass
class BazaarOffer:
    index: int
    scheme: str | None
    network: str | None
    amount_atomic: str | None
    asset: str | None
    pay_to: str | None
    max_timeout_seconds: Any
    extra: Any
    comparable: bool
    notes: list[str] = field(default_factory=list)


@dataclass
class BazaarEntry:
    index: int
    key: str | None
    kind: str  # "http", "mcp" ou "inconnu"
    resource: str | None
    resource_is_http_url: bool
    tool_name: str | None
    method: str | None
    transport: str | None
    x402_version: Any
    last_updated: str | None
    description: str | None
    mime_type: str | None
    service_name: str | None
    tags: list[str]
    icon_url: str | None
    offers: list[BazaarOffer]
    bazaar_info: Any
    bazaar_schema: Any
    schema_external_refs: list[str]
    valid: bool
    diagnostics: list[str] = field(default_factory=list)
    raw: Any = None


@dataclass
class BazaarPage:
    endpoint: str  # "list", "search" ou "rejete"
    source: str
    provenance: Provenance
    x402_version: Any
    entries: list[BazaarEntry]
    pagination: Any
    pagination_state: str  # "absente", "null", "objet", "racine", "invalide"
    partial_results: bool | None
    coverage: str  # "complete", "partial", "unknown"
    coverage_reason: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["provenance"] = self.provenance.value
        data["comparaison_offres"] = compare_offers(self.entries)
        data["avertissement"] = (
            "Normalisation hors ligne. Aucune ressource, aucun outil ni aucun "
            "facilitateur n'a été appelé. Un exemple de documentation ne prouve "
            "ni disponibilité ni demande commerciale."
        )
        return to_plain(redact(data))


# -- enveloppes ------------------------------------------------------------------

def detect_endpoint(payload: Any) -> tuple[str | None, str | None]:
    """Retourne (endpoint, erreur). Jamais de choix arbitraire."""
    if not isinstance(payload, dict):
        return None, f"enveloppe rejetée: racine de type {type(payload).__name__}"
    has_items, has_resources = "items" in payload, "resources" in payload
    if has_items and has_resources:
        return None, "enveloppe rejetée: « items » (liste) et « resources » (recherche) présents"
    if has_items:
        return "list", None
    if has_resources:
        return "search", None
    return None, "enveloppe rejetée: ni « items » ni « resources »"


def parse_response(payload: Any, source: str,
                   provenance: Provenance = Provenance.DECLARATION_COMMERCIALE,
                   expected: str | None = None) -> BazaarPage:
    endpoint, error = detect_endpoint(payload)
    if error is None and expected is not None and endpoint != expected:
        error = f"enveloppe rejetée: « {endpoint} » reçue, « {expected} » attendue"
    if error is not None:
        return BazaarPage("rejete", source, provenance, None, [], None, "absente", None,
                          "unknown", "enveloppe rejetée", errors=[error])
    if endpoint == "list":
        return parse_list_response(payload, source, provenance)
    return parse_search_response(payload, source, provenance)


def parse_list_response(payload: dict, source: str,
                        provenance: Provenance = Provenance.DECLARATION_COMMERCIALE) -> BazaarPage:
    page = _page("list", payload, source, provenance, "items")
    if page.endpoint == "rejete":
        return page
    raw_pagination = payload.get("pagination", _MISSING)
    if raw_pagination is _MISSING:
        page.pagination_state = "absente"
        _set_coverage(page, "unknown", "pagination absente: total inconnu, non inventé")
    elif raw_pagination is None:
        page.pagination_state = "null"
        _set_coverage(page, "unknown", "pagination null: total inconnu, non inventé")
    elif not isinstance(raw_pagination, dict):
        page.pagination_state = "invalide"
        page.errors.append("pagination de liste invalide (objet attendu)")
        _set_coverage(page, "unknown", "pagination invalide")
    else:
        page.pagination_state = "objet"
        page.pagination = raw_pagination
        limit, offset, total = (_int_or_none(raw_pagination.get(k)) for k in ("limit", "offset", "total"))
        if offset is None or total is None:
            page.warnings.append("pagination incomplète: offset ou total manquant ou invalide")
            _set_coverage(page, "unknown", "offset ou total inconnu")
        elif offset > 0:
            _set_coverage(page, "partial", f"page commençant à l'offset {offset}")
        elif offset + len(page.entries) < total:
            _set_coverage(page, "partial", f"{len(page.entries)} éléments lus sur {total} annoncés")
        elif offset + len(page.entries) > total:
            page.warnings.append(f"{len(page.entries)} éléments pour un total annoncé de {total}")
            _set_coverage(page, "unknown", "total annoncé incohérent")
        else:
            _set_coverage(page, "complete", f"{total} éléments annoncés, tous lus")
        if limit is not None and len(page.entries) > limit:
            page.warnings.append(f"{len(page.entries)} éléments pour une limite de {limit}")
    _degrade_for_invalid_entries(page)
    return page


def parse_search_response(payload: dict, source: str,
                          provenance: Provenance = Provenance.DECLARATION_COMMERCIALE) -> BazaarPage:
    page = _page("search", payload, source, provenance, "resources")
    if page.endpoint == "rejete":
        return page
    partial = payload.get("partialResults", _MISSING)
    if partial is _MISSING:
        page.partial_results = None
    elif isinstance(partial, bool):
        page.partial_results = partial
    else:
        page.warnings.append(f"partialResults non booléen ignoré: {partial!r}")
        page.partial_results = None

    raw_pagination = payload.get("pagination", _MISSING)
    root_variant = "cursor" in payload or "limit" in payload
    cursor: Any = _MISSING
    if raw_pagination is not _MISSING and root_variant:
        page.pagination_state = "invalide"
        page.errors.append("pagination contradictoire: objet « pagination » et limit/cursor à la racine")
    elif raw_pagination is _MISSING and root_variant:
        page.pagination_state = "racine"
        page.pagination = {k: payload[k] for k in ("limit", "cursor") if k in payload}
        page.warnings.append("variante de facilitateur: limit/cursor à la racine de la recherche")
        cursor = payload.get("cursor", _MISSING)
    elif raw_pagination is _MISSING:
        page.pagination_state = "absente"
    elif raw_pagination is None:
        page.pagination_state = "null"
    elif isinstance(raw_pagination, dict):
        page.pagination_state = "objet"
        page.pagination = raw_pagination
        cursor = raw_pagination.get("cursor", _MISSING)
        if cursor is _MISSING:
            page.warnings.append("pagination sans « cursor » (obligatoire quand l'objet est présent)")
    else:
        page.pagination_state = "invalide"
        page.errors.append("pagination de recherche invalide (objet ou null attendu)")

    has_next = isinstance(cursor, str) and cursor != ""
    if page.pagination_state == "invalide":
        _set_coverage(page, "unknown", "pagination invalide ou contradictoire")
    elif page.partial_results is True or has_next:
        why = "partialResults=true" if page.partial_results else "curseur de page suivante présent"
        _set_coverage(page, "partial", why)
    elif page.partial_results is False:
        _set_coverage(page, "complete", "partialResults=false et aucune page suivante")
    else:
        _set_coverage(page, "unknown", "partialResults absent: troncature inconnue, non inventée")
    _degrade_for_invalid_entries(page)
    return page


# -- éléments -------------------------------------------------------------------

def parse_entry(index: int, item: Any) -> BazaarEntry:
    diagnostics: list[str] = []
    if not isinstance(item, dict):
        return BazaarEntry(index, None, "inconnu", None, False, None, None, None, None, None,
                           None, None, None, [], None, [], None, None, [], False,
                           [f"élément de type {type(item).__name__}, objet attendu"], redact(item))
    resource = item.get("resource") if isinstance(item.get("resource"), str) else None
    if resource is None:
        diagnostics.append("« resource » absent ou non textuel")
    declared_type = item.get("type") if isinstance(item.get("type"), str) else None
    bazaar = (item.get("extensions") or {}).get("bazaar") if isinstance(item.get("extensions"), dict) else None
    info = bazaar.get("info") if isinstance(bazaar, dict) else None
    schema = bazaar.get("schema") if isinstance(bazaar, dict) else None
    inp = info.get("input") if isinstance(info, dict) and isinstance(info.get("input"), dict) else {}
    input_type = inp.get("type") if isinstance(inp.get("type"), str) else None

    kind = declared_type or input_type or "inconnu"
    if declared_type and input_type and declared_type != input_type:
        diagnostics.append(f"type contradictoire: élément « {declared_type} », bazaar « {input_type} »")
        kind = "inconnu"
    if kind not in ("http", "mcp"):
        diagnostics.append(f"type de ressource non couvert: {kind!r}")

    tool_name = inp.get("toolName") if isinstance(inp.get("toolName"), str) and inp.get("toolName") else None
    if kind == "mcp" and tool_name is None:
        diagnostics.append("outil MCP sans « toolName »: identifiant (resource, toolName) incomplet")
    key = None
    if resource is not None:
        key = f"{resource}#outil={tool_name}" if kind == "mcp" else resource
        if kind == "mcp" and tool_name is None:
            key = None

    scheme = urlsplit(resource).scheme.lower() if resource else ""
    is_http_url = scheme in ("http", "https")
    if resource and not is_http_url:
        diagnostics.append(f"« {scheme or '?'}:// » est un identifiant, pas une URL HTTP à appeler")

    version = item.get("x402Version")
    if version != SUPPORTED_VERSION:
        diagnostics.append(f"x402Version de l'élément {version!r} ≠ {SUPPORTED_VERSION}: non couvert")

    accepts = item.get("accepts")
    offers: list[BazaarOffer] = []
    if not isinstance(accepts, list):
        diagnostics.append("« accepts » absent ou non liste: aucune offre")
    else:
        if not accepts:
            diagnostics.append("« accepts » vide: aucune offre")
        offers = [parse_offer(i, offer) for i, offer in enumerate(accepts)]

    service_name, tags, icon_url, meta_notes = sanitize_service_metadata(item)
    diagnostics.extend(meta_notes)
    external_refs = find_external_refs(schema) + find_external_refs(inp.get("inputSchema"))
    if external_refs:
        diagnostics.append(f"références de schéma externes NON résolues: {', '.join(external_refs)}")

    blocking = (resource is None or key is None or kind not in ("http", "mcp")
                or version != SUPPORTED_VERSION or not offers
                or any(d.startswith("type contradictoire") for d in diagnostics))
    return BazaarEntry(
        index=index, key=key, kind=kind, resource=resource, resource_is_http_url=is_http_url,
        tool_name=tool_name,
        method=inp.get("method") if isinstance(inp.get("method"), str) else None,
        transport=(inp.get("transport") if isinstance(inp.get("transport"), str)
                   else ("streamable-http (défaut de la spécification)" if kind == "mcp" else None)),
        x402_version=version,
        last_updated=item.get("lastUpdated") if isinstance(item.get("lastUpdated"), str) else None,
        description=item.get("description") if isinstance(item.get("description"), str) else None,
        mime_type=item.get("mimeType") if isinstance(item.get("mimeType"), str) else None,
        service_name=service_name, tags=tags, icon_url=icon_url, offers=offers,
        bazaar_info=redact(info), bazaar_schema=redact(schema),
        schema_external_refs=external_refs, valid=not blocking, diagnostics=diagnostics,
        raw=redact(item),
    )


def parse_offer(index: int, offer: Any) -> BazaarOffer:
    notes: list[str] = []
    if not isinstance(offer, dict):
        return BazaarOffer(index, None, None, None, None, None, None, None, False,
                           [f"offre de type {type(offer).__name__}, objet attendu"])
    amount = offer.get("amount")
    atomic: str | None = None
    if isinstance(amount, str) and _ATOMIC.match(amount):
        atomic = amount
    elif isinstance(amount, int) and not isinstance(amount, bool) and amount >= 0:
        atomic = str(amount)
        notes.append("montant JSON numérique (chaîne attendue): conservé exactement ici, "
                     "mais un lecteur en double précision le perdrait au-delà de 2^53")
    elif amount is None:
        notes.append("montant absent: inconnu, jamais traité comme zéro")
    else:
        notes.append(f"montant atomique invalide: {amount!r}")
    scheme = offer.get("scheme") if isinstance(offer.get("scheme"), str) else None
    comparable = atomic is not None and scheme in COMPARABLE_SCHEMES
    if scheme == "upto":
        notes.append("schéma « upto »: montant plafond, pas coût final")
    elif scheme not in COMPARABLE_SCHEMES:
        notes.append(f"schéma {scheme!r} non comparable dans cet atelier")
    for name in ("network", "asset", "payTo"):
        if not isinstance(offer.get(name), str) or not offer.get(name):
            notes.append(f"« {name} » absent ou invalide")
            comparable = False
    notes.append("décimales de l'actif non fournies par Bazaar: aucune conversion en unité "
                 "lisible ni en USD")
    return BazaarOffer(
        index=index, scheme=scheme,
        network=offer.get("network") if isinstance(offer.get("network"), str) else None,
        amount_atomic=atomic,
        asset=offer.get("asset") if isinstance(offer.get("asset"), str) else None,
        pay_to=offer.get("payTo") if isinstance(offer.get("payTo"), str) else None,
        max_timeout_seconds=offer.get("maxTimeoutSeconds"),
        extra=redact(offer.get("extra")), comparable=comparable, notes=notes,
    )


def offer_cost_estimate(offer: BazaarOffer) -> CostEstimate:
    """Estimation pour CostGuard : facturable, montant INCONNU (décimales inconnues).

    Un montant atomique n'est jamais converti ni traité comme zéro : la
    décision de CostGuard est donc toujours un refus.
    """
    return CostEstimate(billable=True, amount=None, currency=None, unit=None, quantity=Decimal(1))


def compare_offers(entries: list[BazaarEntry]) -> dict[str, Any]:
    """Classe les offres « exact » par (réseau, actif), en unités atomiques entières.

    Aucune comparaison entre réseaux ou actifs différents ; une offre non
    comparable reste listée comme telle.
    """
    groups: dict[str, list[dict[str, Any]]] = {}
    not_comparable: list[dict[str, Any]] = []
    for entry in entries:
        for offer in entry.offers:
            ref = {"entree": entry.index, "cle": entry.key, "offre": offer.index,
                   "montant_atomique": offer.amount_atomic, "schema": offer.scheme}
            if not (offer.comparable and entry.valid):
                not_comparable.append(ref | {"raison": "; ".join(offer.notes[:-1]) or "entrée invalide"})
                continue
            groups.setdefault(f"{offer.network}|{offer.asset}", []).append(ref)
    for refs in groups.values():
        refs.sort(key=lambda r: int(r["montant_atomique"]))
    return {"groupes_exact_par_reseau_et_actif": dict(sorted(groups.items())),
            "non_comparables": not_comparable}


# -- schémas et métadonnées -------------------------------------------------------

def find_external_refs(schema: Any, _path: str = "#") -> list[str]:
    """Liste les ``$ref``/``$id`` qui ne sont pas des fragments locaux (« # »).

    Aucune référence n'est jamais chargée : on se contente de les signaler.
    """
    found: list[str] = []
    if isinstance(schema, dict):
        for key, value in schema.items():
            if key in ("$ref", "$id") and isinstance(value, str) and not value.startswith("#"):
                found.append(f"{_path}/{key}={value}")
            else:
                found.extend(find_external_refs(value, f"{_path}/{key}"))
    elif isinstance(schema, list):
        for i, value in enumerate(schema):
            found.extend(find_external_refs(value, f"{_path}/{i}"))
    return found


def sanitize_service_metadata(item: dict) -> tuple[str | None, list[str], str | None, list[str]]:
    """Règles « soft-drop » de specs/extensions/bazaar.md (serviceName, tags, iconUrl)."""
    notes: list[str] = []
    name = item.get("serviceName")
    if name is not None and not (isinstance(name, str) and _PRINTABLE_ASCII.match(name)
                                 and len(name) <= 32):
        notes.append("serviceName invalide écarté (ASCII imprimable, 32 caractères max)")
        name = None
    tags: list[str] = []
    raw_tags = item.get("tags")
    if raw_tags is not None:
        if not isinstance(raw_tags, list):
            notes.append("tags non liste écartés")
        else:
            seen: set[str] = set()
            for tag in raw_tags:
                if not (isinstance(tag, str) and _PRINTABLE_ASCII.match(tag) and len(tag) <= 32):
                    notes.append(f"tag invalide écarté: {tag!r}")
                elif tag.lower() not in seen and len(tags) < 5:
                    seen.add(tag.lower())
                    tags.append(tag)
            if len([t for t in raw_tags if isinstance(t, str)]) > len(tags):
                notes.append("tags tronqués ou dédoublonnés (5 maximum)")
    icon = item.get("iconUrl")
    if icon is not None and not _valid_icon_url(icon):
        notes.append("iconUrl écartée (URL http(s) publique attendue; jamais chargée)")
        icon = None
    return name, tags, icon, notes


def _valid_icon_url(value: Any) -> bool:
    if not isinstance(value, str) or len(value) > 2048 or any(ord(c) < 32 for c in value):
        return False
    try:
        parts = urlsplit(value)
    except ValueError:
        return False
    if parts.scheme not in ("http", "https") or "@" in parts.netloc or not parts.hostname:
        return False
    host = unquote(parts.hostname).lower().rstrip(".")
    if host in _LOCAL_HOSTS or host.isdigit() or host.startswith("0x"):
        return False
    try:
        ipaddress.ip_address(host.strip("[]"))
        return False
    except ValueError:
        return True


# -- fixtures hors ligne ---------------------------------------------------------

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "bazaar"


class FixtureRefused(ValueError):
    pass


def load_manifest(directory: Path = FIXTURES_DIR) -> dict[str, Any]:
    return json.loads((directory / "MANIFEST.json").read_text(encoding="utf-8"))


def load_fixture(path: Path | str) -> BazaarPage:
    """Charge une fixture listée dans MANIFEST.json, empreinte SHA-256 vérifiée.

    Les fixtures étant synthétiques, leur provenance est « fictif ».
    """
    path = Path(path)
    manifest = load_manifest(path.parent)
    entry = next((f for f in manifest.get("fixtures", []) if f.get("fichier") == path.name), None)
    if entry is None:
        raise FixtureRefused(f"{path.name}: absente de MANIFEST.json, refusée")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != entry.get("sha256"):
        raise FixtureRefused(f"{path.name}: empreinte différente de MANIFEST.json, refusée")
    if entry.get("synthetique") is not True:
        raise FixtureRefused(f"{path.name}: provenance non synthétique non prise en charge ici")
    payload = json.loads(data.decode("utf-8"), parse_float=Decimal)
    expected = entry.get("endpoint_attendu")
    return parse_response(payload, f"fixture:{path.name}", Provenance.FICTIF,
                          expected=expected if expected in ("list", "search") else None)


# -- utilitaires ----------------------------------------------------------------

_MISSING = object()


def _page(endpoint: str, payload: dict, source: str, provenance: Provenance,
          list_key: str) -> BazaarPage:
    page = BazaarPage(endpoint, source, provenance, payload.get("x402Version"), [], None,
                      "absente", None, "unknown", "")
    items = payload.get(list_key)
    if not isinstance(items, list):
        page.endpoint = "rejete"
        page.errors.append(f"enveloppe rejetée: « {list_key} » n'est pas une liste")
        page.coverage_reason = "enveloppe rejetée"
        return page
    if page.x402_version != SUPPORTED_VERSION:
        page.warnings.append(
            f"x402Version de l'enveloppe {page.x402_version!r}: seule la version 2 est couverte")
    page.entries = [parse_entry(i, item) for i, item in enumerate(items)]
    keys = [e.key for e in page.entries if e.key]
    for dup in sorted({k for k in keys if keys.count(k) > 1}):
        page.warnings.append(f"identifiant en double conservé sans fusion: {dup}")
    return page


def _set_coverage(page: BazaarPage, state: str, reason: str) -> None:
    page.coverage, page.coverage_reason = state, reason


def _degrade_for_invalid_entries(page: BazaarPage) -> None:
    invalid = [e.index for e in page.entries if not e.valid]
    if invalid and page.coverage == "complete":
        _set_coverage(page, "partial", f"éléments invalides aux positions {invalid}")
    elif invalid:
        page.coverage_reason += f" ; éléments invalides aux positions {invalid}"
    if page.x402_version != SUPPORTED_VERSION and page.coverage == "complete":
        _set_coverage(page, "unknown", "version de protocole non couverte")


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value
