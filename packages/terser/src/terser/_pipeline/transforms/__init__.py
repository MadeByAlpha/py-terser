from ._suite import TransformCache
from .contracts import Contracts
from .combine_imports import CombineImports
from .constant_folding import FoldConstants
from .fold_type_checking import FoldTypeChecking
from ._classes import mark_classes
from .remove_annotations import RemoveAnnotations
from .remove_asserts import RemoveAsserts
from .remove_dead_code import RemoveDeadCode
from .remove_debug import RemoveDebug
from .remove_exception_brackets import RemoveExceptionBrackets
from .remove_explicit_return_none import RemoveExplicitReturnNone
from .remove_literal_statements import RemoveLiteralStatements
from .remove_object_base import RemoveObject
from .remove_pass import RemovePass
from .remove_posargs import ConvertPosargs
from .unfold_iife import UnfoldIIFE
from .remove_type_statements import RemoveTypeStatements
from .convert_typing_extensions import ConvertTypingExtensions
from .convert_early_exits import ConvertEarlyExits
from .convert_to_inline import ConvertToInline
from .convert_to_lambda import ConvertToLambda
from .remove_dummy_assignments import RemoveDummyAssignments
from .remove_docstrings import RemoveDocstrings
from .cleanup_local_imports import CleanupLocalImports
from .remove_overloads import RemoveOverloads
from .remove_typing_decorators import RemoveTypingDecorators
from .remove_generics import RemoveGenerics
from .remove_typing_classes import RemoveTypingClasses
from .convert_typing_constructors import ConvertTypingConstructors
from .convert_dynamic_attribute_access import ConvertDynamicAttributeAccess
from .remove_all import RemoveAll
from .apply_constant_decorator import ApplyConstantDecorator


__transforms__ = [
    # FLAGS = 0 (pre-resolve, pure syntax)
    UnfoldIIFE,
    ConvertTypingExtensions,
    CombineImports,
    RemovePass,
    RemoveObject,
    RemoveAsserts,
    RemoveDebug,
    RemoveExplicitReturnNone,
    ConvertEarlyExits,

    # FLAGS = REQUIRES_IMPORT_RESOLVE
    RemoveLiteralStatements,
    Contracts,
    ApplyConstantDecorator,
    ConvertToLambda,
    RemoveDummyAssignments,
    RemoveDocstrings,
    CleanupLocalImports,
    RemoveOverloads,
    RemoveTypingDecorators,
    RemoveGenerics,
    ConvertTypingConstructors,
    ConvertDynamicAttributeAccess,
    FoldTypeChecking,
    FoldConstants,
    RemoveDeadCode,
    ConvertToInline,

    # FLAGS = REQUIRES_MODULE_RESOLVE
    RemoveAnnotations,
    RemoveTypeStatements,
    RemoveTypingClasses,
    RemoveExceptionBrackets,

    # FLAGS = INFLUENCES_MANGLING
    ConvertPosargs,
    RemoveAll,
]

__all__ = ("TransformCache", "__transforms__", "mark_classes")
