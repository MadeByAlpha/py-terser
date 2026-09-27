"""What the transforms need to know of the classes of a project, followed through its linked imports."""

from __future__ import annotations

from terser.ast import ast, ref
from terser.ast.ref import ref_or_none
from ..resolver.binding import BuiltinBinding, ImportBinding, UnresolvedBinding

if __debug__ and __import__("typing").TYPE_CHECKING:
    from terser.ast import ModuleRef


def class_definition(module_ref: ModuleRef, node: ast.expr) -> tuple[ModuleRef, ast.ClassDef] | None:
    """
    Where the class `node` (a name or `module.name` in `module_ref`) is defined, as far as the
    project tells: through imports only once the project is linked.
    """

    while isinstance(node, ast.Subscript):  # `Base[T]`
        node = node.value

    if isinstance(node, ast.Attribute):
        # `module.Class`, of an imported module
        if (
            isinstance(node.value, ast.Name) and (value_ref := ref_or_none(node.value)) is not None
            and isinstance(binding := getattr(value_ref, 'binding', None), ImportBinding)
            and binding.target is not None and binding.target_name is None
        ):
            return _lookup(binding.target, node.attr, set())
        return None

    if not isinstance(node, ast.Name) or (node_ref := ref_or_none(node)) is None:
        return None

    binding = getattr(node_ref, 'binding', None)
    if isinstance(binding, ImportBinding):
        if binding.target is not None and binding.target_name is not None:
            return _lookup(binding.target, binding.target_name, set())
        return None

    if binding is None or isinstance(binding, (BuiltinBinding, UnresolvedBinding)):
        return None
    return _class_of(module_ref, binding)


def _lookup(module_ref: ModuleRef, name: str, seen: set[tuple[int, str]]) -> tuple[ModuleRef, ast.ClassDef] | None:
    """The class `name` is in `module_ref`, following re-exports"""

    if (id(module_ref), name) in seen:
        return None
    seen.add((id(module_ref), name))

    for binding in module_ref.bindings:
        if binding.name != name:
            continue
        if isinstance(binding, ImportBinding):
            if binding.target is not None and binding.target_name is not None:
                return _lookup(binding.target, binding.target_name, seen)
            return None
        return _class_of(module_ref, binding)
    return None


def _class_of(module_ref: ModuleRef, binding) -> tuple[ModuleRef, ast.ClassDef] | None:
    """The class statement binding `binding`, if that is what binds it"""

    classes = [node for node in binding.references if isinstance(node, ast.ClassDef)]
    return (module_ref, classes[0]) if len(classes) == 1 else None


def subclassed(module_ref: ModuleRef) -> set[int]:
    """`id()` of the classes the classes of `module_ref` derive from directly, wherever they are defined"""

    bases = set()
    for node in ast.walk(module_ref.ast):
        if isinstance(node, ast.ClassDef):
            for base in node.bases:
                if (found := class_definition(module_ref, base)) is not None:
                    bases.add(id(found[1]))
    return bases


def mark_classes(project: dict[str, ModuleRef]) -> None:
    """
    Tell the transforms what they need to know of the classes of `project`, once it's linked and
    before any module is transformed further (a class looked into may be changed by then, a
    `TypedDict` turned into `dict` say): `reads_annotations` for `RemoveAnnotations`, and
    `subclassed` (by a class anywhere in the project) for `RemoveTypingClasses`.
    """

    from .remove_annotations import _Readers

    readers = _Readers()
    bases = set().union(*map(subclassed, project.values()))
    for module_ref in project.values():
        for node in ast.walk(module_ref.ast):
            if isinstance(node, ast.ClassDef):
                node_ref = ref(node)
                node_ref.reads_annotations = readers(module_ref, node)
                node_ref.subclassed = id(node) in bases
