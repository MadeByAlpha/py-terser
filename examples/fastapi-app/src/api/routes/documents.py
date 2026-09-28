from __future__ import annotations

from typing import Annotated, Any

import yaml
from alpha93.collections import accessor
from alpha93.commons import catch
from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import ValidationError
from terser_hints import preserve_annotations

from ..models import Manifest, ServerModel

router = APIRouter(prefix="/documents", tags=["documents"])


class Point(yaml.YAMLObject):
    """`!point` nodes: PyYAML builds these from the class attributes below, by reflection."""

    yaml_tag = "!point"
    yaml_loader = yaml.SafeLoader
    yaml_dumper = yaml.SafeDumper

    def __init__(self, x: float, y: float) -> None:
        self.x = x
        self.y = y

    def __repr__(self) -> str:
        return f"Point(x={self.x}, y={self.y})"


def _jsonable(value: Any) -> Any:
    if isinstance(value, Point):
        return {"point": [value.x, value.y]}
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    return value


@catch(yaml.YAMLError, coro=False)
def _load(text: str) -> Any:
    return yaml.safe_load(text)


@router.post("/manifest")
@preserve_annotations
def manifest(text: Annotated[str, Body(media_type="application/yaml")]) -> dict[str, Any]:
    data, error = _load(text)
    if error is not None:
        raise HTTPException(status_code=400, detail=f"{type(error).__name__}: {error}")
    try:
        parsed = Manifest.model_validate(data)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=exc.errors(include_url=False, include_context=False, include_input=False),
        ) from None

    view = accessor(parsed.model_dump())
    return {
        "manifest": parsed.model_dump(mode="json"),
        "address": f"{view.server.host}:{view.server.port}",
        "extra": _jsonable(parsed.extra),
        "yaml": yaml.safe_dump(parsed.model_dump(mode="json", exclude={"extra"}), sort_keys=True),
    }


@router.get("/schema")
@preserve_annotations
def schema() -> dict[str, Any]:
    return {"manifest": Manifest.model_json_schema(), "server": ServerModel.model_json_schema()}


@router.get("/points", response_class=PlainTextResponse)
@preserve_annotations
def points(count: int = 3) -> str:
    return yaml.dump([Point(i, i * i / 2) for i in range(count)], Dumper=yaml.SafeDumper, sort_keys=True)
