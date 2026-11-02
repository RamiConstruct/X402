"""Analyse de l'intention : instruction en langage naturel → plan d'étapes typées.

Le planificateur par règles (FR/EN) fonctionne hors ligne et de façon déterministe.
Il découpe l'instruction en propositions ; chaque proposition est soit une
opération de montage locale reconnue (vertical, noir et blanc, ralenti…), soit
transmise à un moteur d'édition générative (`edit.prompt`).

Un planificateur LLM (appel d'outils à schéma strict) pourra remplacer celui-ci
en respectant la même interface `plan(prompt) -> list[Step]`.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass, field

MAX_PROMPT_CHARS = 1000

# Ordre d'application : génératif d'abord, puis style, vitesse, son, format en dernier.
_ORDER = {"edit.prompt": 0, "style": 1, "speed": 2, "audio": 3, "format": 4}

_LOCAL_RULES: list[tuple[str, str, str]] = [
    # (capacité, motif sur texte normalisé sans accents, libellé)
    ("format.vertical", r"\bvertical|9\s*[:/x]\s*16|\bportrait\b|tiktok|reels?\b|shorts?\b", "Recadrage vertical 9:16"),
    ("format.square", r"\bcarre\b|\bsquare\b|1\s*[:/x]\s*1\b", "Recadrage carré 1:1"),
    ("style.bw", r"noir_et_blanc|\bn&b\b|black_and_white|monochrome", "Noir et blanc"),
    ("style.cinematic", r"cinema|cinematique|cinematographique|cinematic|look film", "Étalonnage cinéma"),
    ("style.warm", r"\b(plus )?chaud(e|es|s)?\b|\bwarm(er)?\b", "Tons chauds"),
    ("style.cool", r"\b(plus )?froid(e|es|s)?\b|\bcool(er)?\b|bleute", "Tons froids"),
    ("speed.slow", r"ralenti|slow\s*-?\s*mo(tion)?|au ralenti", "Ralenti ×0,5"),
    ("speed.fast", r"accelere|accelerer|timelapse|fast forward|\bx2\b", "Accéléré ×2"),
    ("audio.mute", r"coupe(r)? le son|sans (le )?son|\bmute\b|supprime(r)? le son|enleve(r)? le son", "Son coupé"),
]

_PROTECT = [(r"noir et blanc", "noir_et_blanc"), (r"black (and|&) white", "black_and_white")]
_SPLIT = re.compile(r"\s*(?:,|;|\bpuis\b|\bensuite\b|\bet\b|\bthen\b|\band\b)\s*")


def normalize(text: str) -> str:
    t = unicodedata.normalize("NFKD", text.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    for pat, rep in _PROTECT:
        t = re.sub(pat, rep, t)
    return re.sub(r"\s+", " ", t).strip()


@dataclass
class Step:
    capability: str
    label: str
    prompt: str = ""
    params: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


class PlanError(ValueError):
    pass


def plan(prompt: str) -> list[Step]:
    prompt = (prompt or "").strip()
    if not prompt:
        raise PlanError("instruction vide")
    if len(prompt) > MAX_PROMPT_CHARS:
        raise PlanError(f"instruction trop longue (max {MAX_PROMPT_CHARS} caractères)")

    norm = normalize(prompt)
    original_clauses = _split_original(prompt)
    clauses = [c for c in _SPLIT.split(norm) if c]
    steps: dict[str, Step] = {}
    generative: list[str] = []
    for i, clause in enumerate(clauses):
        matched = False
        for cap, pattern, label in _LOCAL_RULES:
            if re.search(pattern, clause):
                steps.setdefault(cap, Step(capability=cap, label=label))
                matched = True
        if not matched:
            generative.append(original_clauses[i] if i < len(original_clauses) else clause)

    # Contradictions évidentes : la dernière demande l'emporte, signalée dans le libellé.
    for a, b in (("style.warm", "style.cool"), ("speed.slow", "speed.fast"), ("format.vertical", "format.square")):
        if a in steps and b in steps:
            loser = a if norm.rfind(_first_kw(a, norm)) < norm.rfind(_first_kw(b, norm)) else b
            steps.pop(loser)

    result = list(steps.values())
    if not steps:
        gen_text = prompt  # aucune opération locale : l'instruction complète va au moteur génératif
    else:
        gen_text = ", ".join(g.strip() for g in generative if len(g.strip()) > 2)
    if gen_text:
        result.append(Step(capability="edit.prompt", label="Édition générative", prompt=gen_text))
    if not result:
        result.append(Step(capability="edit.prompt", label="Édition générative", prompt=prompt))
    result.sort(key=lambda s: _ORDER.get(s.capability.split(".")[0] if s.capability != "edit.prompt" else "edit.prompt", 9))
    return result


def _first_kw(cap: str, norm: str) -> str:
    pattern = next(p for c, p, _ in _LOCAL_RULES if c == cap)
    m = re.search(pattern, norm)
    return m.group(0) if m else ""


def _split_original(prompt: str) -> list[str]:
    """Même découpage que sur le texte normalisé, mais en conservant la casse et les accents."""
    protected = prompt
    for pat, rep in _PROTECT:
        protected = re.sub(pat, rep, protected, flags=re.IGNORECASE)
    parts = [p for p in re.split(r"\s*(?:,|;|\bpuis\b|\bensuite\b|\bet\b|\bthen\b|\band\b)\s*", protected, flags=re.IGNORECASE) if p]
    return [p.replace("noir_et_blanc", "noir et blanc").replace("black_and_white", "black and white") for p in parts]
