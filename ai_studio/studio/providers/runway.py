"""Adaptateur Runway (vidéo-à-vidéo).

Écrit d'après la documentation publique de l'API Runway (tâche asynchrone :
POST d'une tâche puis interrogation de GET /v1/tasks/{id}). NON TESTÉ contre
l'API réelle : vérifier endpoint, modèle et version dans engines/runway_aleph.yaml
avant d'activer STUDIO_ALLOW_PAID_PROVIDERS.
"""
from __future__ import annotations

import httpx

from .base import Adapter, ProviderError, StepContext, StepResult, download, input_reference, poll


class RunwayAdapter(Adapter):
    def __init__(self, client: httpx.Client | None = None, sleep=None) -> None:
        self.client = client or httpx.Client(timeout=60)
        self.sleep = sleep

    def run(self, ctx: StepContext) -> StepResult:
        p = ctx.engine.params
        headers = {"Authorization": f"Bearer {ctx.api_key}", "X-Runway-Version": p.get("api_version", "2024-11-06")}
        body = {"model": p["model"], "videoUri": input_reference(ctx, float(p.get("max_data_uri_mb", 16))),
                "promptText": ctx.prompt[:1000], "ratio": p.get("ratio", "1280:720")}
        r = self.client.post(p["base_url"] + p["endpoint"], json=body, headers=headers)
        if r.status_code >= 400:
            raise ProviderError(f"Runway a refusé la tâche (HTTP {r.status_code}) : {r.text[:300]}")
        task_id = r.json().get("id")
        if not task_id:
            raise ProviderError("réponse Runway sans identifiant de tâche")
        ctx.log("tâche Runway créée", {"task_id": task_id})

        def check():
            t = self.client.get(f"{p['base_url']}/v1/tasks/{task_id}", headers=headers)
            if t.status_code >= 400:
                raise ProviderError(f"suivi Runway impossible (HTTP {t.status_code})")
            data = t.json()
            status = data.get("status")
            if status == "SUCCEEDED":
                return True, data
            if status in {"FAILED", "CANCELLED"}:
                raise ProviderError(f"tâche Runway {status} : {data.get('failure') or data.get('failureCode')}")
            return False, None

        kwargs = {"sleep": self.sleep} if self.sleep else {}
        data = poll(check, timeout_s=float(p.get("timeout_s", 900)), **kwargs)
        outputs = data.get("output") or []
        if not outputs:
            raise ProviderError("tâche Runway terminée sans fichier de sortie")
        download(outputs[0], ctx.output_path)
        # Coût réel = tarif du manifeste appliqué à la durée envoyée ; à réconcilier avec la facture Runway.
        return StepResult(actual_cost_micro=ctx.engine.pricing.cost_micro(ctx.duration_s), external_id=task_id)
