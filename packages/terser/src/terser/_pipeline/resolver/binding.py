from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, override

from terser.ast import ast, ref
from .util import arg_rename_in_place, insert

if TYPE_CHECKING:
    from typing import Any

    from terser.ast import ModuleRef


class Binding(ABC):
    """
    Represents the binding of a name

    :param name: A name for this binding
    :type name: str or None
    :param bool allow_rename: If this binding may be renamed

    """

    _name: str | None
    _allow_rename: bool
    _exported: bool
    _reserved: str | None
    _references: list[ast.AST]

    def __init__(self, name: str | None = None, allow_rename: bool = True):
        self._name = name
        self._allow_rename = allow_rename
        self._exported = False
        self._reserved = None
        self._references = []

    def __repr__(self):
        return self.__class__.__name__ + '()'

    @property
    def name(self) -> str | None:
        """
        The name for this binding

        This may be changed using the mangler() method.
        If this binding doesn't currently have a name, this returns None.
        """
        return self._name

    @property
    def allow_rename(self) -> bool:
        """
        Is it allowed to mangler this binding
        """
        return self._allow_rename

    def disallow_rename(self):
        """
        Prevent this binding from being renamed
        """
        self._allow_rename = False

    @property
    def reserved(self) -> str | None:
        """
        A reserved name for this binding

        This may be a name which this binding reserves in it's reservation scope,
        regardless of if it is renamed.
        """
        return self._reserved

    @property
    def references(self) -> list[ast.AST]:
        """
        The ast Nodes that reference this binding
        """
        return self._references

    @property
    def name_references(self) -> int:
        """
        The number of times the name is used
        """
        return len(self._references)

    @property
    def exported(self) -> bool:
        """
        Part of the module's public interface (listed in `__all__`, or not
        `__`-prefixed if there is no `__all__`), independent of whether anything
        in the project actually imports it.
        """
        return self._exported

    def mark_exported(self):
        """
        Mark this binding is exported (used in another module)
        """
        self._exported = True

    def additional_byte_cost(self):
        """
        How many additional bytes would be used, if this was renamed
        """

        arg_rename = False
        additional_bytes = 0

        for node in self._references:
            if isinstance(node, ast.Name):
                if isinstance(node.ctx, (ast.Load, ast.Store, ast.Del)):
                    pass
                else:
                    # Python 2 Param context
                    if not arg_rename_in_place(node):
                        arg_rename = True
            elif isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                pass
            elif isinstance(node, ast.ExceptHandler):
                pass
            elif isinstance(node, (ast.Global, ast.Nonlocal)):
                pass
            elif isinstance(node, ast.alias):
                if node.asname is None:
                    additional_bytes += 4  # ' as '
            elif isinstance(node, ast.arguments):
                if node.vararg == self._name:
                    pass
                if node.kwarg == self._name:
                    pass
            elif isinstance(node, ast.arg):
                if not arg_rename_in_place(node):
                    arg_rename = True

            elif isinstance(node, ast.MatchAs):
                if node.name is None:
                    additional_bytes += 4  # ' as '
            elif isinstance(node, ast.MatchStar):
                pass
            elif isinstance(node, ast.MatchMapping):
                pass
            elif isinstance(node, ast.TypeVar):
                pass
            elif isinstance(node, ast.TypeVarTuple):
                pass
            elif isinstance(node, ast.ParamSpec):
                pass

            else:
                raise AssertionError('Unknown reference node')

        return additional_bytes + (2 if arg_rename else 0)

    def old_mention_count(self):
        """
        The number of times the old name would be mentioned in the source code, if this binding was renamed
        """

        arg_rename = False
        mentions = 0

        for node in self._references:
            if isinstance(node, ast.Name):
                if isinstance(node.ctx, (ast.Load, ast.Store, ast.Del)):
                    pass
                else:
                    # Python 2 Param context
                    if not arg_rename_in_place(node):
                        mentions += 1
                        arg_rename = True

            elif isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                pass
            elif isinstance(node, ast.ExceptHandler):
                pass
            elif isinstance(node, (ast.Global, ast.Nonlocal)):
                pass
            elif isinstance(node, ast.alias):
                if node.asname is None:
                    # import foo -> import foo as bar
                    mentions += 1
            elif isinstance(node, ast.arguments):
                pass
            elif isinstance(node, ast.arg):
                if not arg_rename_in_place(node):
                    mentions += 1
                    arg_rename = True

            elif isinstance(node, ast.MatchAs):
                pass
            elif isinstance(node, ast.MatchStar):
                pass
            elif isinstance(node, ast.MatchMapping):
                pass
            elif isinstance(node, ast.TypeVar):
                pass
            elif isinstance(node, ast.TypeVarTuple):
                pass
            elif isinstance(node, ast.ParamSpec):
                pass

            else:
                raise AssertionError('Unknown reference node')

        return mentions + (1 if arg_rename else 0)

    def new_mention_count(self):
        """
        The number of times a new name would be mentioned in the source code
        """

        arg_rename = False
        mentions = 0

        for node in self._references:
            if isinstance(node, ast.Name):
                if isinstance(node.ctx, (ast.Load, ast.Store, ast.Del)):
                    mentions += 1
                else:
                    # Python 2 Param context
                    arg_rename = True
            elif isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                mentions += 1
            elif isinstance(node, ast.ExceptHandler):
                mentions += 1
            elif isinstance(node, (ast.Global, ast.Nonlocal)):
                mentions += len([n for n in node.names if n == self._name])
            elif isinstance(node, ast.alias):
                mentions += 1
            elif isinstance(node, ast.arguments):
                if node.vararg == self._name:
                    mentions += 1
                if node.kwarg == self._name:
                    mentions += 1
            elif isinstance(node, ast.arg):
                arg_rename = True

            elif isinstance(node, ast.MatchAs):
                mentions += 1
            elif isinstance(node, ast.MatchStar):
                mentions += 1
            elif isinstance(node, ast.MatchMapping):
                mentions += 1
            elif isinstance(node, ast.TypeVar):
                mentions += 1
            elif isinstance(node, ast.TypeVarTuple):
                mentions += 1
            elif isinstance(node, ast.ParamSpec):
                mentions += 1

            else:
                raise AssertionError('Unknown reference node')

        return mentions + (1 if arg_rename else 0)

    def add_reference(self, node: ast.AST, allow_rename: bool = True, reserved: str | None = None):
        """
        Add a new reference to this binding

        :param node: The node that references this binding
        :type node: :class:`ast.AST`
        :param bool allow_rename: If this binding may be renamed
        :param str reserved: A name used by the node, even if the binding is renamed.
        """

        self._references.append(node)
        ref(node)._binding = self

        if not allow_rename:
            self.disallow_rename()

        if reserved is not None:
            self._reserved = reserved

    @abstractmethod
    def should_rename(self, new_name: str) -> bool:
        """
        Is it space efficient to mangler this binding

        :param str new_name: The candidate name
        """

    @abstractmethod
    def rename(self, new_name: str) -> None:
        """
        Rename this binding and all nodes that reference it

        :param str new_name: The new name to use
        """


class NameBinding(Binding):
    """
    Represents the binding of a defined name

    A NameBinding will be attached to the local namespace that defines it.

    :param str name: The original bound name
    :param bool allow_rename: If this binding may be renamed
    :param int rename_cost: The cost of renaming this binding in bytes

    """

    _name: str

    def __init__(self, name: str, *args, **kwargs):
        super().__init__(name, *args, **kwargs)

        if name.startswith('__') and name.endswith('__'):
            # System defined name
            self.disallow_rename()

    @override
    @property
    def name(self) -> str:
        return self._name

    @override
    def __repr__(self):
        args = f"{self.name=}, {self.allow_rename=}, {self.exported=}"
        return self.__class__.__name__ + f"({args}) <references={self.name_references}>"

    @override
    def should_rename(self, new_name: str):
        current_cost = len(self.references) * len(self.name)

        old_mentions = self.old_mention_count()
        new_mentions = self.new_mention_count()
        additional_bytes = self.additional_byte_cost()
        rename_cost = (old_mentions * len(self.name)) + (new_mentions * len(new_name)) + additional_bytes

        return rename_cost <= current_cost

    @override
    def disallow_rename(self):
        super().disallow_rename()
        self._reserved = self._name

    @override
    def rename(self, new_name: str):
        func_namespace_binding = None

        for node in self.references:
            if isinstance(node, ast.Name):
                node.id = new_name
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                node.name = new_name
            elif isinstance(node, ast.ClassDef):
                node.name = new_name
            elif isinstance(node, ast.alias):
                node.asname = None if new_name == node.name else new_name
            elif isinstance(node, ast.arg):
                if arg_rename_in_place(node):
                    node.arg = new_name
                    continue

                if func_namespace_binding is None:
                    func_namespace_binding: Any = ref(node).namespace
                else:
                    assert func_namespace_binding is ref(node).namespace

            elif isinstance(node, ast.ExceptHandler):
                node.name = new_name
            elif isinstance(node, (ast.Global, ast.Nonlocal)):
                node.names = [new_name if n == self._name else n for n in node.names]
            elif isinstance(node, ast.arguments):

                if (vararg := node.vararg) and (vararg.arg == self.name) and not getattr(node, "vararg_renamed", False):
                    vararg.arg = new_name
                    setattr(node, "vararg_renamed", True)
                if (kwarg := node.vararg) and (kwarg.arg == self.name) and not getattr(node, "kwarg_renamed", False):
                    kwarg.arg = new_name
                    setattr(node, "kwarg_renamed", True)

            elif isinstance(node, ast.MatchAs):
                node.name = new_name
            elif isinstance(node, ast.MatchStar):
                node.name = new_name
            elif isinstance(node, ast.MatchMapping):
                node.rest = new_name
            elif isinstance(node, ast.TypeVar):
                node.name = new_name
            elif isinstance(node, ast.TypeVarTuple):
                node.name = new_name
            elif isinstance(node, ast.ParamSpec):
                node.name = new_name

        if func_namespace_binding:
            func_namespace_binding.body = list(
                insert(
                    func_namespace_binding.body,
                    ast.Assign(
                        targets=[ast.Name(id=new_name, ctx=ast.Store())],
                        value=ast.Name(id=self._name, ctx=ast.Load()),
                    ),
                )
            )

        self._name = new_name


class ImportBinding(NameBinding):
    """
    Represents the binding of a name introduced by an import

    :param str name: The locally bound name
    :param node: The ast.alias this binding was created for, or the ast.ImportFrom for names
        introduced by `from x import *` (there is no per-name alias node in that case)
    :type node: ast.alias or ast.ImportFrom

    `target`/`target_name` are only filled in by `link_imports`, once every module in the project
    has been bound. Until then (and for imports that resolve outside the project - stdlib,
    third-party), `target` stays None. The path resolved by `resolve_imports` in the meantime is
    tracked separately, in `ModuleRef.import_targets`.
    """

    target: ModuleRef | None
    target_name: str | None

    def __init__(self, name, node, module_ref: ModuleRef, *args, **kwargs):
        super().__init__(name, *args, **kwargs)
        self.node = node
        self.target = None
        self.target_name = None
        self._module_ref = module_ref

    @override
    def __repr__(self):
        args = f"self.name={self.source_module}.{self.name}, {self.allow_rename=}, {self.exported=}"
        return self.__class__.__name__ + f"({args}) <references={self.name_references}>"

    @property
    def source_module(self) -> str | None:
        """
        The dotted module path this name was imported from (e.g. "typing" for
        `from typing import cast`, or the imported dotted path itself for a plain `import x.y`).

        None if `resolve_imports` hasn't run yet, or the import couldn't be resolved (e.g. a
        relative import climbing above the project root). Unaffected by whether the target
        resolves within the project - unlike `target`, this is set for stdlib/third-party imports
        too.
        """
        ref = self._module_ref.import_targets.get(self)
        return ref.path if ref is not None else None


class UnresolvedBinding(NameBinding):
    """
    Represents the usage of a name with no local definition, import, or builtin found anywhere in
    scope - e.g. a typo, or a name provided dynamically at runtime.

    Distinguished from a plain NameBinding so later passes can tell a genuinely local name apart
    from one that couldn't be resolved.
    """

    def __init__(self, name: str, *args, **kwargs):
        super().__init__(name, *args, **kwargs)
        self.disallow_rename()


class BuiltinBinding(NameBinding):
    """
    Represents the usage of a builtin

    :param str name: The name of the builtin
    :param namespace: The module the builtin is used in
    :type namespace: :class:`ast.Module`

    """

    def __init__(self, name, namespace, *args, **kwargs):
        super(BuiltinBinding, self).__init__(name, *args, **kwargs)
        self.namespace = namespace

        # These builtins actually act like keywords, so should not be changed
        if name == 'super':
            # If we replace 'super' with another name the compiler will neglect to create the
            # __class__ implicit closure reference, breaking the zero argument super() call.
            self.disallow_rename()
        elif name == 'object':
            # Classes must inherit from object to become a new-style class in python2
            self.disallow_rename()

    def new_mention_count(self):
        # All mentions must be Names, which would be replaced
        # Plus an Assign with the new name
        return len(self.references) + 1

    def old_mention_count(self):
        # The old name would be mentioned in the Assign
        return 1

    def additional_byte_cost(self):
        return 2  # '=' + '\n'

    def rename(self, new_name):
        builtin = self._name
        super(BuiltinBinding, self).rename(new_name)
        self.namespace.body = list(
            insert(
                self.namespace.body,
                ast.Assign(
                    targets=[ast.Name(id=new_name, ctx=ast.Store())], value=ast.Name(id=builtin, ctx=ast.Load())
                ),
            )
        )

    def is_redefined(self):
        """
        Do one of the references to this builtin name redefine it?

        Could some references actually not be references to the builtin?

        This can happen with code like:

        class MyClass:
            IndexError = IndexError

        """

        for node in self.references:
            if not isinstance(node, ast.Name):
                return True

            if not isinstance(node.ctx, ast.Load):
                return True

        return False
