from .base import Adapter, ProviderError, StepContext, StepResult
from .fal import FalAdapter
from .local_ffmpeg import LocalFfmpegAdapter
from .runway import RunwayAdapter
from .simulated import SimulatedAdapter

ADAPTERS: dict[str, type[Adapter]] = {
    "local_ffmpeg": LocalFfmpegAdapter,
    "simulated": SimulatedAdapter,
    "runway": RunwayAdapter,
    "fal": FalAdapter,
}

__all__ = ["ADAPTERS", "Adapter", "ProviderError", "StepContext", "StepResult"]
