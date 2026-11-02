from __future__ import annotations

from .. import media
from .base import Adapter, ProviderError, StepContext, StepResult


class LocalFfmpegAdapter(Adapter):
    def run(self, ctx: StepContext) -> StepResult:
        try:
            media.apply_local(ctx.input_path, ctx.output_path, ctx.capability)
        except media.MediaError as e:
            raise ProviderError(str(e)) from e
        return StepResult(actual_cost_micro=ctx.engine.pricing.cost_micro(ctx.duration_s))
