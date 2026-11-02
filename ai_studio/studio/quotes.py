"""Routage et devis : pour chaque étape du plan, choisir un moteur selon le mode
(économique = prix minimal, qualité = score qualité maximal), chiffrer, et
expliquer les moteurs exclus."""
from __future__ import annotations

import hashlib
import json

from .config import Settings
from .engines import EngineSpec, Registry
from .planner import Step

MODES = {
    "eco": "Économique",
    "quality": "Qualité maximale",
}


def step_duration(step: Step, asset_duration: float, segment_duration: float) -> float:
    # Un recadrage s'applique toujours à toute la vidéo (on ne mélange pas deux formats dans un fichier).
    return asset_duration if step.capability.startswith("format.") else segment_duration


def _pick(cands: list[EngineSpec], mode: str, duration: float) -> EngineSpec:
    if mode == "eco":
        return min(cands, key=lambda e: (e.pricing.price_credits(e.pricing.cost_micro(duration)), -e.quality, e.id))
    return max(cands, key=lambda e: (e.quality, -e.pricing.price_credits(e.pricing.cost_micro(duration)), e.id))


def cache_key(asset_sha: str, start: float, end: float, steps: list[dict]) -> str:
    payload = json.dumps({"a": asset_sha, "r": [round(start, 3), round(end, 3)],
                          "s": [(s["capability"], s["engine_id"], s.get("prompt", "")) for s in steps]}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def build_options(steps: list[Step], registry: Registry, settings: Settings, *, asset_sha: str,
                  asset_duration: float, start: float, end: float, cache_lookup) -> list[dict]:
    seg = end - start
    options: list[dict] = []
    for mode, label in MODES.items():
        opt_steps, excluded, problem = [], [], None
        for st in steps:
            d = step_duration(st, asset_duration, seg)
            cands, excl = registry.candidates(st.capability, d, settings)
            excluded += [{**x, "capability": st.capability} for x in excl]
            if not cands:
                problem = f"aucun moteur disponible pour « {st.label} »"
                break
            e = _pick(cands, mode, d)
            cost = e.pricing.cost_micro(d)
            opt_steps.append({
                "capability": st.capability, "label": st.label, "prompt": st.prompt, "params": st.params,
                "engine_id": e.id, "engine_name": e.display_name, "duration_s": round(d, 3),
                "cost_micro": cost, "price_credits": e.pricing.price_credits(cost),
                "simulated": e.simulated, "paid": e.paid, "eta_s": round(d * e.speed_factor + 5, 1),
            })
        if problem:
            options.append({"id": mode, "label": label, "available": False, "reason": problem, "excluded": excluded})
            continue
        key = cache_key(asset_sha, start, end, opt_steps)
        hit = cache_lookup(key)
        total_cost = sum(s["cost_micro"] for s in opt_steps)
        total_price = 0 if hit else sum(s["price_credits"] for s in opt_steps)
        options.append({
            "id": mode, "label": label, "available": True, "steps": opt_steps,
            "total_cost_micro": 0 if hit else total_cost, "total_price_credits": total_price,
            "eta_s": 2 if hit else round(sum(s["eta_s"] for s in opt_steps), 1),
            "simulated": any(s["simulated"] for s in opt_steps), "cache_hit": bool(hit), "cache_key": key,
            "excluded": excluded,
        })
    # Si les deux modes choisissent exactement les mêmes moteurs, n'en présenter qu'un.
    avail = [o for o in options if o["available"]]
    if len(avail) == 2 and [s["engine_id"] for s in avail[0]["steps"]] == [s["engine_id"] for s in avail[1]["steps"]]:
        avail[0]["label"] = "Recommandé"
        options = [avail[0]]
    return options
