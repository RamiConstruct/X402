"""Adaptateur générique pour la file d'attente fal.ai (queue.fal.run).

Un seul adaptateur couvre de nombreux modèles : le manifeste fournit l'identifiant
du modèle et le nom des champs. NON TESTÉ contre l'API réelle.
"""
from __future__ import annotations

import httpx

from .base import Adapter, ProviderError, StepContext, StepResult, download, input_reference, poll


class FalAdapter(Adapter):
    def __init__(self, client: httpx.Client | None = None, sleep=None) -> None:
        self.client = client or httpx.Client(timeout=60)
        self.sleep = sleep

    def run(self, ctx: StepContext) -> StepResult:
        p = ctx.engine.params
        model = p.get("model_id", "")
        if not model or model == "A-RENSEIGNER":
            raise ProviderError("identifiant de modèle fal non renseigné dans le manifeste")
        headers = {"Authorization": f"Key {ctx.api_key}"}
        body = {p.get("video_field", "video_url"): input_reference(ctx, float(p.get("max_data_uri_mb", 10))),
                p.get("prompt_field", "prompt"): ctx.prompt[:1000], **p.get("extra_input", {})}
        r = self.client.post(f"https://queue.fal.run/{model}", json=body, headers=headers)
        if r.status_code >= 400:
            raise ProviderError(f"fal a refusé la requête (HTTP {r.status_code}) : {r.text[:300]}")
        sub = r.json()
        status_url, response_url = sub.get("status_url"), sub.get("response_url")
        if not status_url or not response_url:
            raise ProviderError("réponse fal incomplète")
        ctx.log("requête fal en file", {"request_id": sub.get("request_id")})

        def check():
            s = self.client.get(status_url, headers=headers)
            if s.status_code >= 400:
                raise ProviderError(f"suivi fal impossible (HTTP {s.status_code})")
            st = s.json().get("status")
            if st == "COMPLETED":
                return True, None
            if st in {"FAILED", "ERROR", "CANCELLED"}:
                raise ProviderError(f"requête fal {st}")
            return False, None

        kwargs = {"sleep": self.sleep} if self.sleep else {}
        poll(check, timeout_s=float(p.get("timeout_s", 900)), **kwargs)
        res = self.client.get(response_url, headers=headers)
        if res.status_code >= 400:
            raise ProviderError(f"résultat fal indisponible (HTTP {res.status_code})")
        video = res.json().get(p.get("output_field", "video")) or {}
        url = video.get("url") if isinstance(video, dict) else None
        if not url:
            raise ProviderError("résultat fal sans URL de vidéo")
        download(url, ctx.output_path)
        return StepResult(actual_cost_micro=ctx.engine.pricing.cost_micro(ctx.duration_s),
                          external_id=sub.get("request_id"))
