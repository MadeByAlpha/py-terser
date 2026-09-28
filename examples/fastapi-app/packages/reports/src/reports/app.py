from __future__ import annotations

from typing import Annotated

import numpy as np
import yaml
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import PlainTextResponse
from terser_hints import preserve_annotations, preserve_docstring

from .models import Histogram, Sample, Summary

app = FastAPI(title="reports", version="0.1.0")

_SAMPLES: dict[str, Sample] = {}


def _summarize(sample: Sample) -> Summary:
    values = np.asarray(sample.values, dtype=np.float64)
    return Summary(
        name=sample.name,
        unit=sample.unit,
        count=int(values.size),
        total=round(float(values.sum()), 6),
        mean=round(float(values.mean()), 6),
        minimum=float(values.min()),
        maximum=float(values.max()),
    )


@app.post("/samples", status_code=201)
@preserve_annotations
@preserve_docstring
async def create_sample(sample: Sample) -> Summary:
    """Store a sample and return its summary."""
    _SAMPLES[sample.name] = sample
    return _summarize(sample)


@app.get("/samples/{name}")
@preserve_annotations
async def read_sample(name: str) -> Summary:
    if (sample := _SAMPLES.get(name.lower())) is None:
        raise HTTPException(status_code=404, detail=f"no sample named {name!r}")
    return _summarize(sample)


@app.get("/samples/{name}/histogram")
@preserve_annotations
async def histogram(name: str, bins: Annotated[int, Query(ge=1, le=64)] = 4) -> Histogram:
    if (sample := _SAMPLES.get(name.lower())) is None:
        raise HTTPException(status_code=404, detail=f"no sample named {name!r}")
    counts, edges = np.histogram(np.asarray(sample.values), bins=bins)
    return Histogram(edges=[round(float(e), 6) for e in edges], counts=counts.tolist(), bins=bins)


@app.get("/export.yaml", response_class=PlainTextResponse)
@preserve_annotations
async def export() -> str:
    data = {name: _summarize(sample).model_dump() for name, sample in sorted(_SAMPLES.items())}
    return yaml.safe_dump(data, sort_keys=True)
