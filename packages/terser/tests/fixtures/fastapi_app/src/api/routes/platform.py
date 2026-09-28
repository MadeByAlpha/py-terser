from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from terser_hints import preserve_annotations, preserve_docstring
from vercel.cron import CronSchedule, CronTabError
from vercel.headers import geolocation, ip_address

router = APIRouter(prefix="/platform", tags=["platform"])


@router.get("/geo")
@preserve_annotations
@preserve_docstring
def geo(request: Request) -> dict[str, Any]:
    """What Vercel's edge tells about the client, through its request headers."""
    return {"ip": ip_address(request), "geo": geolocation(request)}


@router.get("/schedule")
@preserve_annotations
def schedule(expr: str) -> dict[str, Any]:
    try:
        parsed = CronSchedule.from_str(expr)
    except CronTabError as exc:
        return {"error": str(exc)}
    return {"schedule": str(parsed), "hour": parsed.hour, "day_of_week": parsed.day_of_week}
