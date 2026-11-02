"""Commandes vocales / texte (français, quelques formes anglaises) → modification de scène.

Déterministe et instantané : pas d'appel LLM pour les commandes courantes. Les
commandes d'urgence (« retour à l'original ») sont reconnues en premier.
Un LLM à appels d'outils pourra traiter les phrases non reconnues plus tard.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .scene import CHARACTERS, DECORS, STYLES, Scene, SceneHistory, find_in, find_public_figure, norm

_BLOCKED = [
    ("contenu sexuel", r"\b(nu|nue|nus|nues|nude|naked|porn\w*|sexe|sexy|sexuel\w*|deshabill\w*|lingerie|strip\w*)\b"),
    ("violence extrême", r"\b(decapit\w*|gore|sang|torture\w*|cadavre)\b"),
    ("haine", r"\b(nazi\w*|hitler|kkk)\b"),
]

_WEATHER = {
    "neige": "heavy snowfall", "pluie": "rain falling", "orage": "thunderstorm, lightning",
    "brouillard": "thick fog", "feu": "flames and embers", "etoile": "starry night sky", "aurore": "aurora borealis in the sky",
}


@dataclass
class Result:
    ok: bool
    message: str
    changed: bool = False
    blocked: str | None = None


def _clean_subject(s: str) -> str:
    s = re.sub(r"^(un|une|le|la|les|des|du|en|a|an|the)\s+", "", s.strip(" .!?,"))
    return s[:120]


_CLAUSE_SPLIT = re.compile(r"\s*(?:,|;|\bpuis\b|\bensuite\b|\bet\b|\bthen\b|\band\b)\s+")


def apply_command(history: SceneHistory, text: str) -> Result:
    """Applique une commande ; une phrase composée (« chevalier et décor cyberpunk ») est
    découpée en propositions appliquées dans l'ordre."""
    for category, pattern in _BLOCKED:  # refus global AVANT toute modification partielle
        if re.search(pattern, norm(text)):
            return Result(False, f"commande refusée ({category})", blocked=category)
    protected = re.sub(r"noir et blanc", "noir_et_blanc", norm(text))
    clauses = [c.replace("noir_et_blanc", "noir et blanc") for c in _CLAUSE_SPLIT.split(protected) if c.strip()]
    if len(clauses) <= 1:
        return _apply_one(history, text)
    results, last_subject = [], ""
    for c in clauses:
        r = _apply_one(history, c)
        if not r.ok and last_subject:  # « transforme-moi en pirate et en viking » : proposition elliptique
            r = _apply_one(history, f"{last_subject} {c}")
        if r.blocked:
            return r
        if r.ok and re.match(r"(transforme|deviens|change)", c):
            last_subject = c.split(" en ")[0] + " en" if " en " in c else ""
        results.append(r)
    ok = [r for r in results if r.ok]
    if not ok:
        return results[0]
    return Result(True, " ; ".join(r.message for r in ok), any(r.changed for r in ok))


def _apply_one(history: SceneHistory, text: str) -> Result:
    t = norm(text)
    if not t:
        return Result(False, "commande vide")

    for category, pattern in _BLOCKED:
        if re.search(pattern, t):
            return Result(False, f"commande refusée ({category})", blocked=category)

    # 1) Urgence / bascule — sans ambiguïté, traité avant tout le reste
    if re.search(r"(retour|reviens|revenir) (a |a l'|au )?(l')?(original|normal|vrai moi)|coupe(r)? (l')?(ia|effet)|"
                 r"enleve(r)? (l')?effet|stop (l')?effet|redeviens moi|^original$|^normal$", t):
        s = history.edit()
        s.bypass = True
        history.apply(s)
        return Result(True, "flux original affiché", True)
    if re.search(r"(remets|reprends|relance|reactive)(-| )?(l')?(effet|ia|transformation)?\b", t) and len(t) < 40:
        s = history.edit()
        s.bypass = False
        history.apply(s)
        return Result(True, "transformation réactivée", True)
    if re.search(r"\b(annule|reviens en arriere|undo|defais)\b", t):
        ok = history.undo()
        return Result(ok, "dernière modification annulée" if ok else "rien à annuler", ok)
    if re.search(r"\b(reinitialise|tout effacer|remise a zero|reset)\b", t):
        history.apply(Scene())
        return Result(True, "scène réinitialisée", True)

    # 2) Variante : même scène, nouvelle graine (autre interprétation par l'IA)
    if re.search(r"\b(autre (version|variante|essai|interpretation)|variante|une autre|change (de )?version|re ?genere)\b", t):
        s = history.edit()
        s.seed = (s.seed * 1103515245 + 12345) % 2_147_483_647 or 1
        s.bypass = False
        history.apply(s)
        return Result(True, "nouvelle variante", True)

    # 2b) Intensité
    if re.search(r"plus (fort|intense|extreme)|encore plus|a fond|maximum", t):
        s = history.edit()
        s.strength = min(5, s.strength + 1)
        history.apply(s)
        return Result(True, f"intensité {s.strength}/5", True)
    if re.search(r"moins (fort|intense)|plus (leger|subtil|doux)|doucement|minimum", t):
        s = history.edit()
        s.strength = max(1, s.strength - 1)
        history.apply(s)
        return Result(True, f"intensité {s.strength}/5", True)

    s = history.edit()
    s.bypass = False
    msgs: list[str] = []

    # 3) Décor
    m = re.search(r"(?:decor|fond|arriere-plan|arriere plan|environnement|background)\s*(?:par|en|:|=|de)?\s*(.+)$", t)
    if m:
        target = m.group(1)
        key = find_in(DECORS, target)
        s.decor, s.decor_free = (key, None) if key else (None, _clean_subject(target))
        msgs.append(f"décor : {DECORS[key]['label'] if key else s.decor_free}")

    # 4) Style
    m = re.search(r"(?:style|en mode|facon|look)\s+(.+)$", t)
    if m and not msgs:
        key = find_in(STYLES, m.group(1))
        if key:
            s.style = key
            msgs.append(f"style : {STYLES[key]['label']}")

    # 5) Personnage
    m = re.search(r"(?:transforme(?:-| )?moi|transforme moi|change(?:-| )?moi|deviens|devenir|je veux etre|"
                  r"fais(?:-| )?moi (?:ressembler a|devenir)|turn me into|make me)\s+(?:en|a|an|un|une|comme)?\s*(.+)$", t)
    if m and not msgs:
        target = m.group(1)
        figure = find_public_figure(target)
        if figure:
            s.parody_of, s.character, s.character_free = figure, None, None
            msgs.append(f"caricature parodique : {figure} (bandeau PARODIE activé)")
        else:
            key = find_in(CHARACTERS, target)
            s.parody_of = None
            s.character, s.character_free = (key, None) if key else (None, _clean_subject(target))
            msgs.append(f"personnage : {CHARACTERS[key]['label'] if key else s.character_free}")

    # 6) Météo / ajouts
    if re.search(r"\b(ajoute|mets|fais apparaitre|fais tomber|ajouter)\b", t) or not msgs:
        for k, extra in _WEATHER.items():
            if re.search(rf"\b{k}", t) and extra not in s.extras:
                s.extras = (s.extras + [extra])[-3:]
                msgs.append(f"ajout : {k}")
    if re.search(r"\b(enleve|retire|supprime)\b", t):
        before = list(s.extras)
        removed = {e for k, e in _WEATHER.items() if re.search(rf"\b{k}", t)}
        s.extras = [e for e in s.extras if e not in removed]
        if s.extras != before:
            msgs.append("effet retiré")

    # 7) Mots seuls reconnus (« cyberpunk », « anime », « chevalier »)
    if not msgs:
        if key := find_in(DECORS, t):
            s.decor, s.decor_free = key, None
            msgs.append(f"décor : {DECORS[key]['label']}")
        elif key := find_in(STYLES, t):
            s.style = key
            msgs.append(f"style : {STYLES[key]['label']}")
        elif key := find_in(CHARACTERS, t):
            s.character, s.character_free, s.parody_of = key, None, None
            msgs.append(f"personnage : {CHARACTERS[key]['label']}")
        elif figure := find_public_figure(t):
            s.parody_of, s.character, s.character_free = figure, None, None
            msgs.append(f"caricature parodique : {figure} (bandeau PARODIE activé)")

    if not msgs:
        return Result(False, "commande non comprise — essaie « transforme-moi en chevalier », « décor cyberpunk », « style anime », « retour à l'original »")
    history.apply(s)
    return Result(True, " ; ".join(msgs), True)


def set_preset(history: SceneHistory, kind: str, key: str | None) -> Result:
    catalogs = {"character": CHARACTERS, "decor": DECORS, "style": STYLES}
    if kind not in catalogs or (key is not None and key not in catalogs[kind]):
        return Result(False, "préréglage inconnu")
    s = history.edit()
    s.bypass = False
    if kind == "character":
        s.character, s.character_free, s.parody_of = key, None, None
    elif kind == "decor":
        s.decor, s.decor_free = key, None
    else:
        s.style = key
    history.apply(s)
    return Result(True, "préréglage appliqué", True)
