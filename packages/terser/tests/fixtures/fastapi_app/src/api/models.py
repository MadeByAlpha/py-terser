from __future__ import annotations

from dataclasses import dataclass, field
from typing import Annotated, Any

from alpha93.commons.pydantic import to_model
from pydantic import BaseModel, Field, model_validator
from terser_hints import preserve_annotations, preserve_docstring


@preserve_annotations
class Matrices(BaseModel):
    a: list[list[float]]
    b: list[list[float]]

    @model_validator(mode="after")
    def check_shapes(self) -> Matrices:
        if len(self.a[0]) != len(self.b):
            raise ValueError(f"cannot multiply {len(self.a)}x{len(self.a[0])} by {len(self.b)}x{len(self.b[0])}")
        return self


@preserve_annotations
class Page(BaseModel):
    html: str = Field(max_length=10_000)
    script: str = "document.title"


@preserve_annotations
class Attributes(BaseModel):
    name: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]*$")]
    attrs: dict[str, str] = Field(default_factory=dict, max_length=8)


@preserve_annotations
@preserve_docstring
@dataclass
class Server:
    host: str = "127.0.0.1"
    """Address the server binds to."""

    port: int = 8000
    """TCP port."""

    tags: list[str] = field(default_factory=list)
    """Free-form labels."""


# pydantic reads the attribute docstrings above back from the source (`use_attribute_docstrings`)
ServerModel = to_model(Server)


@preserve_annotations
class Manifest(BaseModel):
    name: str
    version: tuple[int, int, int]
    server: ServerModel = Field(default_factory=ServerModel)  # type: ignore[valid-type]
    extra: dict[str, Any] = {}
