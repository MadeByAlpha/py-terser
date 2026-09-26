"""
This package transforms python source code strings or ast.Module Nodes into
a 'minified' representation of the same source code.

"""

from ._minify import unparse
from .config import TransformConfig
from .terser import minify, minify_project

version = "0.1.1"

__all__ = (
    "TransformConfig",
    "minify",
    "minify_project",
    "unparse",
)
