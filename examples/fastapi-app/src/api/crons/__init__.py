"""
Cron jobs, one package per job named by its UUID.

Jobs are found at import time and imported by name, so no job is named in the code: adding a
package adds its endpoint. Each job package exposes `handler`, registered with `vercel.cron.cron`.
"""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Callable
from types import ModuleType
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from terser_hints import preserve_annotations

router = APIRouter(prefix="/crons", tags=["crons"])


@preserve_annotations
class CronRun(BaseModel):
    id: str
    crons: list[tuple[str, str]]
    result: dict[str, Any]


def _discover() -> dict[str, ModuleType]:
    return {
        info.name: importlib.import_module(f"{__name__}.{info.name}")
        for info in pkgutil.iter_modules(__path__)
        if info.ispkg
    }


JOBS = _discover()


def _endpoint(job_id: str, module: ModuleType) -> Callable[[], Any]:
    handler = module.handler

    @preserve_annotations
    async def run() -> CronRun:
        return CronRun(id=job_id, crons=handler.get_crons(), result=await handler())

    return run


for _job_id, _module in JOBS.items():
    router.add_api_route(f"/{_job_id}", _endpoint(_job_id, _module), methods=["GET"], name=f"cron-{_job_id}")


@router.get("/")
@preserve_annotations
def index() -> list[str]:
    return sorted(JOBS)


@router.get("/{job_id}/source")
@preserve_annotations
def source(job_id: str) -> dict[str, str]:
    if (module := JOBS.get(job_id)) is None:
        raise HTTPException(status_code=404, detail="no such job")
    return {"module": module.__name__, "file": module.__file__.rpartition("/crons/")[2]}
