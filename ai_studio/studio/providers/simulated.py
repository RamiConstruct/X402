from __future__ import annotations

from .. import media
from .base import Adapter, ProviderError, StepContext, StepResult


class SimulatedAdapter(Adapter):
    """Simule un moteur génératif payant, sans réseau ni dépense réelle."""

    def run(self, ctx: StepContext) -> StepResult:
        token = ctx.engine.params.get("fail_if_prompt_contains")
        if token and token in ctx.prompt:
            raise ProviderError("échec simulé du fournisseur (test de remboursement)")
        try:
            media.simulated_edit(ctx.input_path, ctx.output_path)
        except media.MediaError as e:
            raise ProviderError(str(e)) from e
        return StepResult(actual_cost_micro=ctx.engine.pricing.cost_micro(ctx.duration_s),
                          external_id=f"sim-{ctx.idempotency_key[-12:]}")
