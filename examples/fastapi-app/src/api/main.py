from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from reports import app as reports_app
from starlette.routing import Mount
from terser_hints import preserve_annotations

from . import crons
from .routes import browser, documents, files, numeric, platform, relay

app = FastAPI(title="api", version="0.1.0")

for module in (numeric, documents, browser, files, relay, platform, crons):
    app.include_router(module.router)

# a separately developed app (the `reports` workspace member), mounted under this one
app.mount("/reports", reports_app)


class Refused(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@app.exception_handler(Refused)
async def refused(request: Request, exc: Refused) -> JSONResponse:
    return JSONResponse(status_code=418, content={"refused": exc.reason, "path": request.url.path})


@app.middleware("http")
async def tag_responses(request: Request, call_next: Any) -> Any:
    response = await call_next(request)
    response.headers["x-api"] = "1"
    return response


@app.get("/")
@preserve_annotations
def root() -> dict[str, Any]:
    return {
        "routes": sorted(app.openapi()["paths"]),
        "mounts": [r.path for r in app.router.routes if isinstance(r, Mount)],
    }


@app.get("/teapot")
@preserve_annotations
def teapot(reason: str = "short and stout") -> None:
    raise Refused(reason)
