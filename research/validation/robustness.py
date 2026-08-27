from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class BootstrapSummary:
    median_terminal: float
    p05_terminal: float
    p95_terminal: float
    probability_loss: float


def bootstrap_terminal_equity(returns: list[float], paths: int = 2000, seed: int = 42) -> BootstrapSummary:
    if not returns:
        return BootstrapSummary(1.0, 1.0, 1.0, 0.0)
    rng = np.random.default_rng(seed)
    arr = np.asarray(returns, dtype=float)
    samples = rng.choice(arr, size=(paths, len(arr)), replace=True)
    terminals = np.prod(1.0 + samples, axis=1)
    return BootstrapSummary(float(np.median(terminals)), float(np.quantile(terminals, 0.05)),
                            float(np.quantile(terminals, 0.95)), float(np.mean(terminals < 1.0)))
