"""Catalogue des modèles temps réel proposés, avec leurs besoins GPU.

Le client choisit un modèle ; le prix par minute est calculé à partir du prix réel
de la machine louée × la marge du modèle. En mode propriétaire (toi), marge = 1.
Les i/s attendues sont des ESTIMATIONS à remplacer par tes mesures.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LiveModel:
    key: str
    label: str
    model_id: str
    min_vram_gb: int
    width: int
    height: int
    use_controlnets: bool
    markup: float                 # prix client = coût GPU × markup
    notes: str
    fps_estimate: str             # [HYP] à mesurer


MODELS: dict[str, LiveModel] = {
    m.key: m for m in [
        LiveModel("sd-turbo", "Rapide — SD-Turbo 512px", "stabilityai/sd-turbo", 12, 512, 512, False, 2.0,
                  "Le plus rapide et le moins cher ; style marqué, détails limités.", "25–60 i/s sur RTX 4090/5090"),
        LiveModel("sd15-dreamshaper", "Polyvalent — Dreamshaper 8 (SD1.5)", "Lykon/dreamshaper-8", 16, 512, 512, True, 2.0,
                  "Bons personnages et styles ; ControlNet pour garder la pose.", "15–30 i/s sur RTX 4090/5090"),
        LiveModel("sdxl-turbo", "Qualité — SDXL-Turbo + ControlNet", "stabilityai/sdxl-turbo", 24, 512, 512, True, 2.0,
                  "Meilleure qualité ; conserve pose et profondeur. GPU 24 Go minimum.", "15–25 i/s sur RTX 4090/5090"),
    ]
}
