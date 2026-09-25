from ._suite import TransformCache
from .contracts import Contracts
from .combine_imports import CombineImports
from .constant_folding import FoldConstants
from .remove_annotations import RemoveAnnotations
from .remove_asserts import RemoveAsserts
from .remove_debug import RemoveDebug
from .remove_exception_brackets import RemoveExceptionBrackets
from .remove_explicit_return_none import RemoveExplicitReturnNone
from .remove_literal_statements import RemoveLiteralStatements
from .remove_object_base import RemoveObject
from .remove_pass import RemovePass
from .remove_posargs import ConvertPosargs


__transforms__ = [
    Contracts,
    RemoveLiteralStatements,
    CombineImports,
    RemoveAnnotations,
    RemovePass,
    RemoveObject,
    RemoveAsserts,
    RemoveDebug,
    RemoveExplicitReturnNone,
    RemoveExceptionBrackets,
    FoldConstants,
    ConvertPosargs,
]

__all__ = ("TransformCache", "__transforms__")
