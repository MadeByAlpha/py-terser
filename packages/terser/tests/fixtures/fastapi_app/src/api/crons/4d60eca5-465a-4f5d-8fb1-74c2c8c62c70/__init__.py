"""Nightly rollup of the request counters."""

from vercel.cron import cron

from .counters import COUNTERS, rollup


@cron("0 3 * * *")
async def handler() -> dict[str, object]:
    return {"totals": rollup(COUNTERS), "keys": sorted(COUNTERS)}
