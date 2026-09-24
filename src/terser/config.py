from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass()
class RemoveAnnotationOptions:
    """Options that affect how annotations are removed"""

    remove_variable_annotations: bool = True
    """Remove variable annotations"""

    remove_return_annotations: bool = True
    """Remove return annotations"""

    remove_argument_annotations: bool = True
    """Remove argument annotations"""

    remove_attribute_annotations: bool = False
    """Remove class attribute annotations"""


@dataclass()
class TransformConfig:
    passes: int = 5
    optimize: Literal[-1, 0, 1, 2] = -1

    contracts: list[str] = field(default_factory=lambda: [
        "typing.cast(_, value) -> value",
        "typing.assert_never(_) -> None",
        "typing.assert_type(x, _) -> x",
    ])

    apply_contracts: bool = True

    remove_literal_statements: bool = False
    """Remove statements consisting of a single literal that does nothing"""

    combine_imports: bool = True
    """Combine adjacent import statements where possible"""

    remove_annotations: bool | RemoveAnnotationOptions = True
    """Options that affect how annotations are removed"""

    remove_explicit_base: bool = True
    """Remove explicit base classes"""

    remove_explicit_return_none: bool = True
    """Replace explicit `return None` statements with bare `return`"""

    fold_constants: bool = True
    """Evaluate and shrink constant literals"""

    remove_debug: bool = True
    """Remove conditional statements that test __debug__ is True (part of FoldConstants)"""

    remove_asserts: bool = True

    convert_pass: bool = True
    """Remove or convert `pass` statements to the smallest literal statement, like `0`"""

    ### requires binding
    remove_empty_exc_brackets: bool = True
    """Remove brackets with empty arguments from built-in exception raise statements"""

    ### mangle-sensitive transforms
    convert_posargs: bool = True
    """Convert positional-only arguments to normal arguments"""
