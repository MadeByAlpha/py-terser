from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import ast
    from .ast.ref import ModuleSpec


class InvalidTransformError(RuntimeError):
    """
    Raised when a minified module differs from the original module in an unexpected way.

    This is raised when the minifier generates source code that doesn't parse back into the
    original module (after known transformations).
    This should never occur and is a bug.
    """

    def __init__(self, exception: Exception, spec: ModuleSpec | str, source: str | None, module: ast.AST):
        self.exception = exception
        self.source = source
        self.module = module
        self.spec, self.path = (None, spec) if isinstance(spec, str) else (spec, spec.path)

    def __str__(self):
        return 'Minification was unstable! Please create an issue at https://github.com/dflook/python-minifier/issues'

class UnbeneficialMinificationError(Exception):
    """Raised when minification results in larger output than the original."""
    pass
