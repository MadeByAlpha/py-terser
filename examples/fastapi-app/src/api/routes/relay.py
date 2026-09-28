from __future__ import annotations

import json
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from reports import app as reports_app
from terser_hints import preserve_annotations, preserve_docstring

router = APIRouter(prefix="/relay", tags=["relay"])


def _upstream(request: httpx.Request) -> httpx.Response:
    """A fake upstream service, echoing what httpx sent it."""
    body = json.loads(request.content) if request.content else None
    return httpx.Response(
        200,
        json={
            "method": request.method,
            "path": request.url.path,
            "query": sorted(request.url.params.multi_items()),
            "agent": request.headers["x-agent"],
            "body": body,
        },
        headers={"x-upstream": "mock"},
    )


@router.get("/echo")
@preserve_annotations
async def echo(word: str = "hello") -> dict[str, Any]:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(_upstream), base_url="https://upstream.invalid", headers={"x-agent": "api"}
    ) as client:
        response = await client.post("/v1/echo", params={"word": word, "n": 2}, json={"word": word[::-1]})
    response.raise_for_status()
    return {"status": response.status_code, "upstream": response.headers["x-upstream"], "json": response.json()}


@router.post("/reports/{name}")
@preserve_annotations
@preserve_docstring
async def relay_report(name: str, values: list[float]) -> dict[str, Any]:
    """Store a sample in the mounted `reports` app through httpx, then read its histogram back."""
    transport = httpx.ASGITransport(app=reports_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://reports") as client:
        created = await client.post("/samples", json={"name": name, "data": values})
        if created.is_error:
            raise HTTPException(status_code=created.status_code, detail=created.json()["detail"])
        histogram = await client.get(f"/samples/{name}/histogram", params={"bins": 3})
    return {"created": created.json(), "histogram": histogram.json()}
