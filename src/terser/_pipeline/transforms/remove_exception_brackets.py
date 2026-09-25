"""
Remove Call nodes that are only used to raise exceptions with no arguments

If a Raise statement is used on a Name and the name refers to an exception, it is automatically instantiated with no arguments
We can remove any Call nodes that are only used to raise exceptions with no arguments and let the Raise statement do the instantiation.
When printed, this essentially removes the brackets from the exception name.

We can't generally know if a name refers to an exception, so we only do this for builtin exceptions
"""

from __future__ import annotations

from typing import override

from terser.ast import ast, ref

from ..resolver.binding import BuiltinBinding
from ._suite import SuiteTransformer, TransformerFlag

# Builtin exceptions in every supported Python version (3.13+)
builtin_exceptions = frozenset({
    'SyntaxError', 'Exception', 'ValueError', 'BaseException', 'MemoryError', 'RuntimeError', 'DeprecationWarning', 'UnicodeEncodeError', 'KeyError', 'LookupError', 'TypeError', 'BufferError',
    'ImportError', 'OSError', 'StopIteration', 'ArithmeticError', 'UserWarning', 'PendingDeprecationWarning', 'RuntimeWarning', 'IndentationError', 'UnicodeTranslateError', 'UnboundLocalError',
    'AttributeError', 'EOFError', 'UnicodeWarning', 'BytesWarning', 'NameError', 'IndexError', 'TabError', 'SystemError', 'OverflowError', 'FutureWarning', 'SystemExit', 'Warning',
    'FloatingPointError', 'ReferenceError', 'UnicodeError', 'AssertionError', 'SyntaxWarning', 'UnicodeDecodeError', 'GeneratorExit', 'ImportWarning', 'KeyboardInterrupt', 'ZeroDivisionError',
    'NotImplementedError',
    # 3.3+
    'ChildProcessError', 'ConnectionError', 'BrokenPipeError', 'ConnectionAbortedError', 'ConnectionRefusedError', 'ConnectionResetError', 'FileExistsError', 'FileNotFoundError',
    'InterruptedError', 'IsADirectoryError', 'NotADirectoryError', 'PermissionError', 'ProcessLookupError', 'TimeoutError', 'ResourceWarning',
    # 3.5+
    'StopAsyncIteration', 'RecursionError',
    # 3.6+
    'ModuleNotFoundError',
    # 3.10+
    'EncodingWarning',
    # 3.11+
    'BaseExceptionGroup', 'ExceptionGroup',
})


def _remove_empty_call(binding: BuiltinBinding):
    for name_node in binding.references:
        # For this to be a builtin, all references must be name nodes as it is not defined anywhere
        assert isinstance(name_node, ast.Name)
        assert isinstance(name_node.ctx, ast.Load)

        if not isinstance(call_node := ref(name_node).parent, ast.Call):
            # This is not a call
            continue

        if not isinstance(raise_node := ref(call_node).parent, ast.Raise):
            # This is not a raise statement
            continue

        if len(call_node.args) > 0 or len(call_node.keywords) > 0:
            # This is a call with arguments
            continue

        # This is an instance of the exception being called with no arguments
        # let's replace it with just the name, cutting out the Call node

        if raise_node.exc is call_node:
            raise_node.exc = name_node
        elif raise_node.cause is call_node:
            raise_node.cause = name_node
        ref(name_node).parent = raise_node


class RemoveExceptionBrackets(SuiteTransformer):
    """
    Remove the brackets of builtin exceptions raised without arguments: `raise ValueError()` -> `raise ValueError`

    Needs the module linked, since a `from x import *` may provide a name that otherwise looks like a builtin.
    """
    FLAGS = TransformerFlag.REQUIRES_MODULE_RESOLVE

    @override
    @classmethod
    def is_enabled(cls, config, /) -> bool:
        return config.remove_empty_exc_brackets

    @override
    def visit_Module(self, node: ast.Module):
        module_ref = ref(node)
        if module_ref.tainted:
            # exec(), an external wildcard import, ... - any builtin name could be redefined
            return node

        for binding in module_ref.bindings:
            if isinstance(binding, BuiltinBinding) and not binding.is_redefined() and binding.name in builtin_exceptions:
                _remove_empty_call(binding)

        return node
