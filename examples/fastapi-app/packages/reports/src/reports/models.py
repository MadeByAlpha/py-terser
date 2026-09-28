from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator
from terser_hints import preserve_annotations, preserve_docstring


@preserve_annotations
@preserve_docstring
class Sample(BaseModel):
    """A named series of measurements."""

    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=32)
    unit: Literal["ms", "s", "count"] = "ms"
    values: Annotated[list[float], Field(min_length=1, alias="data")]

    @field_validator("name")
    @classmethod
    def lower_name(cls, value: str) -> str:
        return value.lower()


@preserve_annotations
class Summary(BaseModel):
    name: str
    unit: str
    count: int
    total: float
    mean: float
    minimum: float
    maximum: float

    @computed_field
    @property
    def spread(self) -> float:
        return round(self.maximum - self.minimum, 6)


@preserve_annotations
class Histogram(BaseModel):
    edges: list[float]
    counts: list[int]
    bins: int = Field(ge=1, le=64)
