"""Chronométrage par étape du worker (lot 0 : mesurer avant d'optimiser).

Chaque image traverse plusieurs étapes (conversion, inférence, préparation et encodage
de la diffusion…). `StageTimer` garde les dernières durées de chaque étape et en donne
la moyenne, le 95e centile et le maximum, sans dépendance externe.

Les étapes sont enregistrées depuis plusieurs fils (boucle asyncio, pool d'exécution,
fil d'encodage) : un verrou protège les fenêtres.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from contextlib import contextmanager


class StageTimer:
    def __init__(self, window: int = 120) -> None:
        self.window = window
        self._lock = threading.Lock()
        self._samples: dict[str, deque] = {}

    def add(self, stage: str, ms: float) -> None:
        with self._lock:
            q = self._samples.get(stage)
            if q is None:
                q = self._samples[stage] = deque(maxlen=self.window)
            q.append(ms)

    @contextmanager
    def measure(self, stage: str):
        t0 = time.perf_counter()
        try:
            yield
        finally:
            self.add(stage, (time.perf_counter() - t0) * 1000)

    def summary(self) -> dict[str, dict]:
        """{étape: {"avg_ms", "p95_ms", "max_ms", "n"}} sur la fenêtre glissante."""
        with self._lock:
            snap = {k: list(v) for k, v in self._samples.items()}
        out = {}
        for stage, vals in snap.items():
            if not vals:
                continue
            s = sorted(vals)
            p95 = s[min(len(s) - 1, int(round(0.95 * (len(s) - 1))))]
            out[stage] = {"avg_ms": round(sum(s) / len(s), 2), "p95_ms": round(p95, 2),
                          "max_ms": round(s[-1], 2), "n": len(s)}
        return out

    def line(self) -> str:
        """Résumé d'une ligne pour le journal : « étape moy/p95 ms »."""
        return " | ".join(f"{k} {v['avg_ms']:.1f}/{v['p95_ms']:.1f} ms" for k, v in self.summary().items())


@contextmanager
def timed(timer: StageTimer | None, stage: str):
    """Comme `timer.measure(stage)`, mais ne fait rien si aucun chronomètre n'est branché."""
    if timer is None:
        yield
        return
    with timer.measure(stage):
        yield
