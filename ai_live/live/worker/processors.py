"""Processeurs d'images du worker.

* `demo`            : effet CPU (numpy) qui dépend du prompt — sert à tester le tunnel sans GPU.
* `streamdiffusion` : vrai moteur (fork Daydream de StreamDiffusion, Apache-2.0) — exige un GPU NVIDIA.
"""
from __future__ import annotations

import hashlib
import logging
import os
import threading

import numpy as np

from .metrics import StageTimer, timed

log = logging.getLogger("live.worker")


class Processor:
    timer: StageTimer | None = None  # branché par le worker pour détailler les étapes internes

    def update(self, params: dict) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def process(self, rgb: np.ndarray) -> np.ndarray:  # pragma: no cover - interface
        raise NotImplementedError


class DemoProcessor(Processor):
    """Teinte + postérisation dont la couleur dépend du prompt et la force de t_index_list."""

    def __init__(self, params: dict) -> None:
        self.lock = threading.Lock()
        self.prompt = ""
        self.strength = 0.6
        self.update(params)

    def update(self, params: dict) -> None:
        with self.lock:
            if "prompt" in params:
                self.prompt = str(params["prompt"])
            if params.get("t_index_list"):
                t = int(params["t_index_list"][0])
                self.strength = max(0.15, min(1.0, 1.0 - t / 50))

    def tint(self) -> np.ndarray:
        h = hashlib.sha256(self.prompt.encode()).digest()
        return np.array([h[0], h[1], h[2]], dtype=np.float32)

    def process(self, rgb: np.ndarray) -> np.ndarray:
        with self.lock:
            tint, s = self.tint(), self.strength
        img = rgb.astype(np.float32)
        poster = np.floor(img / 64.0) * 64.0 + 32.0
        out = (1 - s) * img + s * (0.55 * poster + 0.45 * tint)
        return np.clip(out, 0, 255).astype(np.uint8)


class StreamDiffusionProcessor(Processor):
    """Enveloppe `StreamDiffusionWrapper` (daydreamlive/StreamDiffusion).

    Paramètres acceptés : ceux de l'API Daydream (model_id, prompt, negative_prompt,
    t_index_list, guidance_scale, delta, width, height, num_inference_steps, controlnets).

    Deux chemins pour faire entrer et sortir l'image (`SD_TENSOR_IO`) :

    * `0` (défaut, chemin d'origine) : numpy → PIL (redimensionnement CPU) → modèle → PIL → numpy.
    * `1` (à valider sur GPU) : l'image est envoyée une fois sur le GPU, redimensionnée par torch,
      donnée au modèle en tenseur, et ressort en tenseur (`output_type="pt"`) : une seule copie
      vers le GPU, une seule copie retour, aucun passage par PIL. Les étapes `sd_pre`, `sd_model`
      et `sd_post` du chronomètre permettent de comparer les deux chemins.
    """

    def __init__(self, params: dict) -> None:
        from PIL import Image  # noqa: F401  (dépendances GPU importées seulement ici)
        from streamdiffusion import StreamDiffusionWrapper

        self.tensor_io = os.environ.get("SD_TENSOR_IO", "0") == "1"
        self.width = int(params.get("width", 512))
        self.height = int(params.get("height", 512))
        cns = [c for c in params.get("controlnets") or [] if c.get("enabled", True)]
        guidance = float(params.get("guidance_scale", 1.0))
        self.lock = threading.Lock()
        self.wrapper = StreamDiffusionWrapper(
            model_id_or_path=params.get("model_id", "stabilityai/sd-turbo"),
            t_index_list=list(params.get("t_index_list") or [22]),
            mode="img2img", output_type="pt" if self.tensor_io else "pil", width=self.width, height=self.height,
            acceleration=os.environ.get("SD_ACCELERATION", "tensorrt"),
            engine_dir=os.environ.get("SD_ENGINE_DIR", "engines"),
            frame_buffer_size=1, warmup=10, use_denoising_batch=True,
            cfg_type="none" if guidance <= 1.0 else "self",
            do_add_noise=bool(params.get("do_add_noise", True)),
            use_controlnet=bool(cns),
            controlnet_config=[{"model_id": c["model_id"], "preprocessor": c.get("preprocessor"),
                                "conditioning_scale": float(c.get("conditioning_scale", 0.5)),
                                "preprocessor_params": c.get("preprocessor_params") or {}, "enabled": True}
                               for c in cns] or None,
            enable_similar_image_filter=True,
        )
        self.wrapper.prepare(prompt=params.get("prompt", "a person"),
                             negative_prompt=params.get("negative_prompt", ""),
                             num_inference_steps=int(params.get("num_inference_steps", 50)),
                             guidance_scale=guidance, delta=float(params.get("delta", 0.7)))

    def update(self, params: dict) -> None:
        kw: dict = {}
        if "prompt" in params:
            kw["prompt_list"] = [(str(params["prompt"]), 1.0)]
        if "negative_prompt" in params:
            kw["negative_prompt"] = params["negative_prompt"]
        if params.get("t_index_list"):
            kw["t_index_list"] = list(params["t_index_list"])
        for k in ("guidance_scale", "delta"):
            if k in params:
                kw[k] = float(params[k])
        if kw:
            with self.lock:
                self.wrapper.update_stream_params(**kw)

    def process(self, rgb: np.ndarray) -> np.ndarray:
        if self.tensor_io:
            return self._process_tensor(rgb)
        from PIL import Image
        with timed(self.timer, "sd_pre"):
            img = Image.fromarray(rgb).resize((self.width, self.height))
        with timed(self.timer, "sd_model"):
            with self.lock:
                out = self.wrapper(image=img)
        with timed(self.timer, "sd_post"):
            return np.asarray(out.convert("RGB"))

    def _process_tensor(self, rgb: np.ndarray) -> np.ndarray:
        import torch
        import torch.nn.functional as F

        device = getattr(self.wrapper, "device", "cuda")
        with timed(self.timer, "sd_pre"):
            # (H, W, 3) uint8 → (1, 3, H, W) réels dans [0, 1] sur le GPU ; le pipeline normalise ensuite en [-1, 1].
            x = torch.from_numpy(np.ascontiguousarray(rgb)).to(device)
            x = x.permute(2, 0, 1).unsqueeze(0).float().div_(255.0)
            if tuple(x.shape[-2:]) != (self.height, self.width):
                x = F.interpolate(x, size=(self.height, self.width), mode="bilinear", align_corners=False, antialias=True)
        with timed(self.timer, "sd_model"):
            with self.lock:
                out = self.wrapper(image=x)
        with timed(self.timer, "sd_post"):
            return tensor_to_rgb(out)


def tensor_to_rgb(out) -> np.ndarray:
    """Sortie du modèle en `output_type="pt"` → tableau (H, W, 3) uint8 pour l'encodeur.

    Accepte (1, 3, H, W) ou (3, H, W) en réels [0, 1] (cas normal, sur le GPU), et (1, H, W, 3)
    ou (H, W, 3) en uint8 (image de repli du filtre de sécurité). La conversion en uint8 se fait
    sur le GPU, puis une seule copie vers la mémoire centrale.
    """
    import torch

    t = out[0] if isinstance(out, (list, tuple)) else out
    if t.dim() == 4:
        t = t[0]
    if t.dtype == torch.uint8:
        hwc = t if t.shape[-1] == 3 else t.permute(1, 2, 0)
    else:
        if t.shape[0] != 3 and t.shape[-1] == 3:
            t = t.permute(2, 0, 1)
        hwc = (t.float().clamp(0, 1) * 255).round().to(torch.uint8).permute(1, 2, 0)
    return hwc.contiguous().cpu().numpy()


def make_processor(params: dict) -> Processor:
    kind = os.environ.get("WORKER_PROCESSOR", "demo")
    if kind == "streamdiffusion":
        return StreamDiffusionProcessor(params)
    return DemoProcessor(params)
