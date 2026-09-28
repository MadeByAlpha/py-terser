"""Hourly health probe of the numeric kernels."""

import numpy as np
from vercel.cron import cron

from api import kernels


@cron(minute=15)
async def handler() -> dict[str, object]:
    lengths = np.array([kernels.collatz_length(n) for n in range(1, 33)])
    return {"max": int(lengths.max()), "argmax": int(lengths.argmax()) + 1, "primes": kernels.primes(30)}
