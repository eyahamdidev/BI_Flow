"""Wilson score interval for a binomial rate. n=20 is reported, not hidden."""

from __future__ import annotations

import math

_Z = 1.959963984540054


def wilson_interval(successes: int, n: int, z: float = _Z) -> tuple[float, float]:
    if n <= 0:
        raise ValueError("n must be positive")
    if successes < 0 or successes > n:
        raise ValueError("successes must be between 0 and n")
    phat = successes / n
    z2 = z * z
    denom = 1.0 + z2 / n
    centre = (phat + z2 / (2.0 * n)) / denom
    margin = z * math.sqrt(phat * (1.0 - phat) / n + z2 / (4.0 * n * n)) / denom
    return max(0.0, centre - margin), min(1.0, centre + margin)
