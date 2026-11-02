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

log = logging.getLogger("live.worker")


class Processor:
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
    t_index_list, guidance_scale, delta, width, height, num_inference_steps, controlnets, seed).
    """

    def __init__(self, params: dict) -> None:
        from PIL import Image  # noqa: F401  (dépendances GPU importées seulement ici)
        from streamdiffusion import StreamDiffusionWrapper

        self.width = int(params.get("width", 512))
        self.height = int(params.get("height", 512))
        cns = [c for c in params.get("controlnets") or [] if c.get("enabled", True)]
        guidance = float(params.get("guidance_scale", 1.0))
        self.lock = threading.Lock()
        self.wrapper = StreamDiffusionWrapper(
            model_id_or_path=params.get("model_id", "stabilityai/sd-turbo"),
            t_index_list=list(params.get("t_index_list") or [22]),
            mode="img2img", output_type="pil", width=self.width, height=self.height,
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
            seed=int(params.get("seed", 42)),  # graine fixe : rendu plus stable d'une image à l'autre
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
        from PIL import Image
        img = Image.fromarray(rgb).resize((self.width, self.height))
        with self.lock:
            out = self.wrapper(image=img)
        return np.asarray(out.convert("RGB"))


def make_processor(params: dict) -> Processor:
    kind = os.environ.get("WORKER_PROCESSOR", "demo")
    if kind == "streamdiffusion":
        return StreamDiffusionProcessor(params)
    return DemoProcessor(params)
