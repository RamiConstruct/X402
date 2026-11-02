"""Client du protocole « flux temps réel » de Daydream.

Protocole (vérifié dans le SDK TypeScript officiel `daydreamlive/daydream-typescript`
et le plugin TouchDesigner officiel `daydreamlive/daydream-touchdesigner`) :

  POST  {base}/v1/streams          {"pipeline": "streamdiffusion", "params": {"model_id": ..., ...}}
        → {"id", "whip_url", "output_playback_id", ...}
  POST  {whip_url}                 corps = offre SDP, en-tête Authorization: Bearer <clé>
        → réponse SDP ; en-tête « Livepeer-Playback-Url » = URL WHEP de la sortie
  POST  {whep_url}                 offre SDP de lecture → réponse SDP (réessayer tant que la sortie n'est pas prête)
  PATCH {base}/v1/streams/{id}     {"pipeline", "params": {"model_id", <paramètres modifiés>}}

Le worker auto-hébergé (`live.worker`) implémente le MÊME protocole : passer de
l'API Daydream à ton propre GPU = changer `base_url`, la clé et le modèle.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import httpx

from .scene import DEFAULT_NEGATIVE, Scene

# ControlNets acceptés par Daydream (validation de l'API vérifiée le 2026-11-02) : ils conservent
# la profondeur (depth), les contours (canny) et la continuité d'une image à l'autre (tile + feedback).
_DEPTH_XL = {"model_id": "xinsir/controlnet-depth-sdxl-1.0", "preprocessor": "depth_tensorrt", "conditioning_scale": 0.45}
_TILE_XL = {"model_id": "xinsir/controlnet-tile-sdxl-1.0", "preprocessor": "feedback", "conditioning_scale": 0.21}
_CANNY_XL = {"model_id": "xinsir/controlnet-canny-sdxl-1.0", "preprocessor": "canny", "conditioning_scale": 0.22}
CONTROLNETS = {
    "stabilityai/sdxl-turbo": [_DEPTH_XL, _TILE_XL],
    "stabilityai/sd-turbo": [
        {"model_id": "thibaud/controlnet-sd21-depth-diffusers", "preprocessor": "depth_tensorrt", "conditioning_scale": 0.45},
        {"model_id": "thibaud/controlnet-sd21-openpose-diffusers", "preprocessor": "openpose", "conditioning_scale": 0.4},
    ],
}

# Modes de rendu proposés à l'utilisateur. Taille 512 partout : chez Daydream, un flux en 640
# reste bloqué sur « Loading pipeline… » (mesuré le 2026-11-02), alors que 512 démarre en ~5 s. Le modèle n'est changé que sur les moteurs qui le
# permettent (Daydream) ; ailleurs, seuls le nombre de passes et la taille s'appliquent.
QUALITY_MODES: dict[str, dict] = {
    "rapide": {"label": "Rapide", "hint": "le plus fluide, détails plus simples",
               "model": "stabilityai/sd-turbo", "size": 512, "passes": 1},
    "equilibre": {"label": "Équilibré", "hint": "le meilleur compromis pour le direct",
                  "model": "stabilityai/sdxl-turbo", "size": 512, "passes": 1},
    "qualite": {"label": "Qualité", "hint": "plus beau et plus stable, un peu moins fluide",
                "model": "stabilityai/sdxl-turbo", "size": 512, "passes": 2,
                "controlnets": [_DEPTH_XL, _CANNY_XL, _TILE_XL]},
}
DEFAULT_MODE = "equilibre"


def resolve_mode(cfg: "EngineConfig", mode: str | None) -> dict:
    """Paramètres effectifs (modèle, taille, passes, ControlNets) d'un mode pour un moteur donné."""
    m = QUALITY_MODES.get(mode or DEFAULT_MODE, QUALITY_MODES[DEFAULT_MODE])
    model = m["model"] if cfg.switch_models else cfg.model_id
    size = m["size"] if cfg.switch_models else cfg.width
    cns = (m.get("controlnets") if model == m["model"] else None) or CONTROLNETS.get(model)
    return {"key": mode if mode in QUALITY_MODES else DEFAULT_MODE, "model": model, "width": size,
            "height": size if cfg.switch_models else cfg.height, "passes": m["passes"],
            "controlnets": cns if cfg.use_controlnets else None}


class EngineError(RuntimeError):
    pass


@dataclass
class EngineConfig:
    name: str
    base_url: str
    api_key: str
    model_id: str = "stabilityai/sdxl-turbo"
    pipeline: str = "streamdiffusion"
    width: int = 512
    height: int = 512
    use_controlnets: bool = True
    usd_per_minute: float | None = None   # tarif à renseigner après vérification (None = inconnu)
    supports_output_size: bool = False    # worker auto-hébergé : format de diffusion (720x1280…) ; Daydream : non
    switch_models: bool = False           # True : les modes de rendu peuvent changer de modèle (Daydream)


def scene_params(scene: Scene, cfg: EngineConfig, *, initial: bool, mode: str | None = None) -> dict:
    m = resolve_mode(cfg, mode)
    p: dict = {
        "model_id": m["model"],
        "prompt": scene.prompt(),
        "negative_prompt": DEFAULT_NEGATIVE + (", photorealistic, photo" if scene.parody else ""),
        "t_index_list": scene.t_index_list(m["passes"]),
        "guidance_scale": 1.0,
        "delta": 0.7,
        "do_add_noise": True,
        "seed": scene.seed,
    }
    if cfg.supports_output_size:
        p["bypass"] = scene.bypass            # worker auto-hébergé : renvoie l'image originale
    elif scene.bypass:
        p["t_index_list"] = [49]              # Daydream : pas de bypass natif → retouche minimale
    if initial:
        p.pop("bypass", None)
        p.update(width=m["width"], height=m["height"], num_inference_steps=50)
        cns = m["controlnets"]
        if cns:
            p["controlnets"] = [{**c, "preprocessor_params": {}, "enabled": True} for c in cns]
    return p


class StreamEngine:
    def __init__(self, cfg: EngineConfig, client: httpx.Client | None = None, sleep=time.sleep) -> None:
        self.cfg = cfg
        self.client = client or httpx.Client(timeout=30)
        self.sleep = sleep

    def _headers(self, json_body: bool = True) -> dict:
        if not self.cfg.api_key:
            raise EngineError(f"clé API manquante pour le moteur « {self.cfg.name} »")
        h = {"Authorization": f"Bearer {self.cfg.api_key}"}
        if json_body:
            h["Content-Type"] = "application/json"
        return h

    def create(self, scene: Scene, output_rtmp_urls: list[str] | None = None, output_size: str | None = None,
               mode: str | None = None) -> dict:
        """Diffusion directe : la 1re adresse va dans output_rtmp_url (champ officiel de l'API Daydream) ;
        les suivantes (multidiffusion) ne sont gérées que par le worker auto-hébergé."""
        body = {"pipeline": self.cfg.pipeline, "params": scene_params(scene, self.cfg, initial=True, mode=mode)}
        urls = list(output_rtmp_urls or [])
        if urls:
            body["output_rtmp_url"] = urls[0]
            if self.cfg.supports_output_size:
                if len(urls) > 1:
                    body["output_rtmp_urls"] = urls[1:]
                if output_size:
                    body["params"]["output_size"] = output_size
            elif len(urls) > 1:
                raise EngineError("ce moteur ne diffuse que vers une seule plateforme à la fois")
        r = self.client.post(f"{self.cfg.base_url}/v1/streams", json=body, headers=self._headers())
        if r.status_code >= 400:
            raise EngineError(f"création du flux refusée (HTTP {r.status_code}) : {r.text[:300]}")
        data = r.json()
        if not data.get("id") or not data.get("whip_url"):
            raise EngineError("réponse de création incomplète (id / whip_url)")
        return data

    def update(self, stream_id: str, scene: Scene, mode: str | None = None) -> None:
        body = {"pipeline": self.cfg.pipeline, "params": scene_params(scene, self.cfg, initial=False, mode=mode)}
        r = self.client.patch(f"{self.cfg.base_url}/v1/streams/{stream_id}", json=body, headers=self._headers())
        if r.status_code >= 400:
            raise EngineError(f"mise à jour refusée (HTTP {r.status_code}) : {r.text[:300]}")

    def whip(self, whip_url: str, offer_sdp: str) -> tuple[str, str | None]:
        h = self._headers(json_body=False)
        h["Content-Type"] = "application/sdp"
        r = self.client.post(whip_url, content=offer_sdp.encode(), headers=h, follow_redirects=True)
        if r.status_code >= 400:
            raise EngineError(f"connexion WHIP refusée (HTTP {r.status_code}) : {r.text[:300]}")
        return r.text, r.headers.get("livepeer-playback-url")

    def whep(self, whep_url: str, offer_sdp: str, retries: int = 40, delay_s: float = 0.25) -> str:
        last = ""
        for _ in range(retries):
            r = self.client.post(whep_url, content=offer_sdp.encode(), headers={"Content-Type": "application/sdp"},
                                 follow_redirects=True)
            if r.status_code < 300 and r.text.startswith("v="):
                return r.text
            last = f"HTTP {r.status_code}"
            self.sleep(delay_s)  # la sortie IA met quelques secondes à démarrer
        raise EngineError(f"sortie IA indisponible ({last})")

    def delete(self, stream_id: str) -> None:
        try:
            # Contrat du SDK officiel : DELETE /v1/streams?id=<id>
            self.client.delete(f"{self.cfg.base_url}/v1/streams", params={"id": stream_id}, headers=self._headers())
        except httpx.HTTPError:
            pass
