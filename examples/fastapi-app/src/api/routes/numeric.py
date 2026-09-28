from __future__ import annotations

from typing import Annotated

import numpy as np
from fastapi import APIRouter, HTTPException, Query
from terser_hints import preserve_annotations, preserve_docstring

from .. import kernels
from ..models import Matrices

router = APIRouter(prefix="/numeric", tags=["numeric"])


def _parse(values: str) -> np.ndarray:
    try:
        return np.array([float(v) for v in values.split(",") if v.strip()], dtype=np.float64)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@router.get("/stats")
@preserve_annotations
@preserve_docstring
def stats(values: Annotated[str, Query(min_length=1)]) -> dict[str, float | int | list[float]]:
    """Descriptive statistics of comma-separated numbers."""
    data = _parse(values)
    if data.size == 0:
        raise HTTPException(status_code=400, detail="no values")
    return {
        "count": int(data.size),
        "mean": round(float(data.mean()), 6),
        "std": round(float(data.std(ddof=0)), 6),
        "median": float(np.median(data)),
        "percentiles": [round(float(p), 6) for p in np.percentile(data, [25, 50, 75])],
        "cumsum": [round(float(v), 6) for v in np.cumsum(data)],
    }


@router.post("/matrix")
@preserve_annotations
def matrix(body: Matrices) -> dict[str, object]:
    a, b = np.array(body.a), np.array(body.b)
    product = a @ b
    result: dict[str, object] = {"product": np.round(product, 6).tolist(), "shape": list(product.shape)}
    if product.shape[0] == product.shape[1]:
        det = float(np.linalg.det(product))
        result["det"] = round(det, 6)
        if abs(det) > 1e-12:
            result["inverse"] = np.round(np.linalg.inv(product), 6).tolist()
    return result


@router.get("/primes")
@preserve_annotations
def primes(limit: Annotated[int, Query(ge=2, le=10_000)] = 100) -> dict[str, object]:
    found = kernels.primes(limit)
    return {"count": len(found), "last": found[-5:], "kernel": kernels.describe()}


@router.get("/collatz/{n}")
@preserve_annotations
def collatz(n: int) -> dict[str, int]:
    if n < 1:
        raise HTTPException(status_code=422, detail="n must be positive")
    return {"n": n, "steps": kernels.collatz_length(n)}
