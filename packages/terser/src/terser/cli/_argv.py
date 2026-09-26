from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Annotated, Any

from alpha93.commons.pydantic import dataclasses as pydantic_dataclasses
from pydantic import BaseModel, ConfigDict, Field

from terser.config import TransformConfig, RemoveAnnotationOptions
from ._argparse import MutuallyExclusive

if TYPE_CHECKING:
    from argparse import Namespace


_config = ConfigDict(use_attribute_docstrings=True)
PydanticTransformOptions = pydantic_dataclasses.to_model(TransformConfig)


def parse_preserve(args: set[str]) -> dict[str, list[str]]:
    """
    Parse `--preserve-locals`/`--preserve-globals` values into a glob-pattern -> names map.

    Each argument is either "name[,name...]" (applies to every module, pattern "*") or
    "pattern:name[,name...]" (applies only to modules whose dotted path, or filename in
    single-file mode, matches the glob pattern), e.g. "foo.bar:baz,qux".
    """

    result: dict[str, list[str]] = {}
    for arg in args:
        pattern, sep, names = arg.partition(':')
        if not sep:
            pattern, names = '*', pattern
        pattern = pattern.strip() or '*'

        for name in names.split(','):
            name = name.strip()
            if name:
                result.setdefault(pattern, []).append(name)

    return result


class OutputOptions(BaseModel):
    model_config = _config

    output: str | None = None
    """Path to write minified output. Defaults to stdout."""

    in_place: bool = False
    """Overwrite existing files."""


class ManglingOptions(BaseModel):
    model_config = _config

    hoist_literals: bool = True
    """Replace frequently used constant literals with variables that have shorter name."""

    rename_locals: bool = True
    """Mangle local (including nonlocal) names"""

    preserve_locals: Annotated[set[str], Field(default_factory=set)]
    """Comma-separated list of local names that will not be mangled. Prefix with a
    glob pattern and ':' to scope to matching modules, e.g. 'foo.bar:baz,qux'"""

    rename_globals: bool = False
    """Mangle global (module-level) names. In project mode, references from other modules follow the rename"""

    preserve_globals: Annotated[set[str], Field(default_factory=set)]
    """Comma-separated list of global names that will not be mangled. Prefix with a
    glob pattern and ':' to scope to matching modules, e.g. 'foo.bar:baz,qux'"""

    rename_modules: bool = False
    """Mangle module/package file and directory names (requires --output, since renamed files
    can't be written back in-place)"""

    preserve_modules: Annotated[set[str], Field(default_factory=set)]
    """Glob patterns matched against a module's dotted path - matching modules keep their name"""


class TerserArguments(BaseModel):
    model_config = _config

    output_options: MutuallyExclusive[OutputOptions]

    preserve_shebang: bool = True
    """Preserve any shebang line from the source code."""

    prefer_single_line: bool = False
    """
    Prefer multiple statements on a single line separated by semicolons instead of newlines,
    even when there is no difference in output size.
    """

    transform_options: TransformConfig
    """Options that affect how the source is minified"""

    mangling_options: ManglingOptions

    workers: int | None = None
    """Number of worker threads to process modules with in project mode. Defaults to the
    interpreter's default thread pool sizing."""

    entry: Annotated[set[str], Field(default_factory=set)]
    """Entry point modules (dotted module path or file path). Requires a directory, multiple
    paths, or --in-place. If given, modules unreachable from these are dropped from the output
    (tree-shaking), and these modules are never renamed by --rename-modules"""

def _given(namespace: Namespace, names, /) -> dict[str, Any]:
    """Values of `names` that were set on the command line (unset collection options are None)."""

    return {name: value for name in names if (value := getattr(namespace, name)) is not None}


class TerserParsedArguments(TerserArguments):
    path: set[str]

    @classmethod
    def from_argparse(cls, namespace: Namespace, /) -> TerserParsedArguments:
        output_options = OutputOptions(
            output=None if namespace.in_place else namespace.output,
            in_place=namespace.in_place,
        )

        remove_annotations = RemoveAnnotationOptions(
            **_given(namespace, (f.name for f in dataclasses.fields(RemoveAnnotationOptions)))
        )

        # every other TransformConfig field maps 1:1 to an option of the same name
        transform_options = TransformConfig(**_given(
            namespace,
            (f.name for f in dataclasses.fields(TransformConfig) if f.name != "remove_annotations"),
        ), remove_annotations=(
            (remove_annotations if remove_annotations != RemoveAnnotationOptions() else True)
            if namespace.remove_annotations else False
        ))

        mangling_options = ManglingOptions(**_given(namespace, ManglingOptions.model_fields))

        return cls(
            path=set(namespace.path),
            output_options=output_options,
            transform_options=transform_options,
            mangling_options=mangling_options,
            **_given(namespace, ("preserve_shebang", "prefer_single_line", "workers", "entry")),
        )
