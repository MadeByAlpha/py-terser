from terser.ast import ast

# Callables recognized as dynamic-import forms. Extend here (not at each call site) when
# adding new forms - e.g. a future `__lazy_import__`, or `importlib.import_module`.
_DYNAMIC_IMPORT_CALLEES = ('__import__',)


def match_dynamic_import_call(node: ast.expr) -> str | None:
    """
    Recognize a dynamic-import call (`__import__("mod")`), returning the literal module
    name, or `None` if `node` isn't one.
    """
    if not isinstance(node, ast.Call) or len(node.args) != 1 or node.keywords:
        return None

    if not isinstance(node.func, ast.Name) or node.func.id not in _DYNAMIC_IMPORT_CALLEES:
        return None

    arg = node.args[0]
    if not isinstance(arg, ast.Constant) or not isinstance(arg.value, str):
        return None

    return arg.value


def match_dynamic_import_value(node: ast.expr) -> tuple[str, str | None] | None:
    """
    Recognize an assignable dynamic-import expression - `__import__("mod")` or
    `__import__("mod").attr` - returning `(source_module, remote_name)`, where
    `remote_name` is `None` for the bare (module-only) form.
    """
    remote_name = None
    call = node

    if isinstance(call, ast.Attribute):
        remote_name = call.attr
        call = call.value

    source_module = match_dynamic_import_call(call)
    if source_module is None:
        return None

    return source_module, remote_name
