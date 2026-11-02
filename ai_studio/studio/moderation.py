"""Modération des instructions AVANT exécution (on ne paie jamais un fournisseur pour un refus).

Niveau 1 (ici) : règles déterministes. Niveau 2 (à brancher) : classifieur texte
et image/vidéo. Les règles sont volontairement strictes : en cas de doute, refuser
et journaliser plutôt que générer.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .planner import normalize

_RULES: list[tuple[str, str]] = [
    ("mineurs", r"\b(enfant|mineur|ado(lescent)?e?s?|child|kid|minor|teen)\w*\b.*\b(nu|nue|nude|sex|sexy|deshabill)"),
    ("contenu sexuel", r"\b(nu|nue|nus|nues|nude|naked|porn\w*|sexe|sexuel\w*|sexual|deshabill\w*|undress\w*|strip\w*)\b"),
    ("usurpation d'identité", r"\b(deepfake|face ?swap|echange(r)? (le|les) visage|remplace(r)? (le|son|mon) visage par celui)"),
    ("violence extrême", r"\b(decapit\w*|gore|torture\w*|behead\w*)\b"),
]


@dataclass(frozen=True)
class Verdict:
    allowed: bool
    category: str | None = None


def check_prompt(prompt: str) -> Verdict:
    t = normalize(prompt)
    for category, pattern in _RULES:
        if re.search(pattern, t):
            return Verdict(False, category)
    return Verdict(True)
