"""Bibliothèque d'images de référence (live/references/) : montre à l'IA à quoi ressemble un
chevalier, un décor ou un style, au lieu de le deviner à partir du seul texte (IP-Adapter).

Arborescence : references/<characters|decors|styles>/<clé>/<n>.jpg + manifest.json (auteur, licence,
source de chaque image). Les images sont servies publiquement sous /refs/… pour que le moteur
(Daydream) puisse les télécharger.
"""
from __future__ import annotations

import json
from pathlib import Path

from .scene import Scene

DEFAULT_ROOT = Path(__file__).parent / "references"


class References:
    def __init__(self, root: Path = DEFAULT_ROOT, public_base: str = "https://live.labotory.site") -> None:
        self.root = Path(root)
        self.public_base = public_base.rstrip("/")
        try:
            self.manifest: dict = json.loads((self.root / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.manifest = {}

    def images(self, kind: str, key: str | None) -> list[dict]:
        if not key:
            return []
        return [i for i in self.manifest.get(kind, {}).get(key, []) if (self.root / kind / key / i["file"]).is_file()]

    def pick(self, scene: Scene) -> str | None:
        """URL publique de l'image à montrer à l'IA : personnage d'abord, puis style, puis décor.
        La graine de la scène choisit l'image (« autre version » en montre une autre). Jamais pour une
        caricature (pas de photo réelle derrière une parodie)."""
        if scene.parody:
            return None
        for kind, key in (("characters", scene.character), ("styles", scene.style), ("decors", scene.decor)):
            imgs = self.images(kind, key)
            if imgs:
                img = imgs[scene.seed % len(imgs)]
                return f"{self.public_base}/refs/{kind}/{key}/{img['file']}"
        return None

    def counts(self) -> dict:
        return {kind: {k: len(self.images(kind, k)) for k in items} for kind, items in self.manifest.items()}
