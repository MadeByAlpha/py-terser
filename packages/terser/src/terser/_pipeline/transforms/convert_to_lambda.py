from typing import override

from terser.ast import ast, ref
from terser.ast.ref import ref_or_none
from terser.ast.ref._node import NodeRef
from terser.config import TransformConfig
from ..resolver.util import arg_rename_in_place
from ._suite import SuiteTransformer, TransformerFlag


def _is_annotated(args: ast.arguments, returns: ast.expr | None) -> bool:
    # A lambda has no syntax for annotations at all - converting a function that still
    # has one (e.g. `Annotated[...]` protected from removal) would produce invalid code.
    all_args = [*getattr(args, 'posonlyargs', []), *args.args, *args.kwonlyargs]
    if args.vararg is not None:
        all_args.append(args.vararg)
    if args.kwarg is not None:
        all_args.append(args.kwarg)

    return returns is not None or any(a.annotation is not None for a in all_args)


class ConvertToLambda(SuiteTransformer):
    """
    Convert a single-expression function to a lambda assignment:
    `def foo(...): return expr` -> `foo = lambda ...: expr`

    Registered after `RemoveAnnotations` (same FLAGS stage) so that by the time this runs,
    any annotation that's going to be removed already has been - what's left is exactly
    what would survive as invalid syntax on a lambda.
    """
    FLAGS = TransformerFlag.REQUIRES_IMPORT_RESOLVE

    @override
    @classmethod
    def is_enabled(cls, config: TransformConfig, /) -> bool:
        return config.convert_to_lambda

    @override
    def visit_FunctionDef(self, node: ast.FunctionDef):
        node: ast.FunctionDef = self.generic_visit(node)

        if isinstance(node, ast.AsyncFunctionDef) or node.decorator_list or len(node.body) != 1:
            return node

        if _is_annotated(node.args, getattr(node, 'returns', None)):
            return node

        if any(binding.preserved for binding in ref(node).bindings):
            # named by `preserve_locals`, whose `module::qualname` patterns match the function's
            # `__qualname__` - a lambda's is `<lambda>`
            return node

        stmt = node.body[0]
        if not isinstance(stmt, ast.Return) or stmt.value is None:
            # a bare `Expr` body isn't equivalent as a lambda: it always
            # implicitly returns None, but a lambda returns the expression's value
            return node

        # `node.args`/`body` are reused, already-bound subtrees (this runs post-resolve) -
        # a full `add_child` walk would call `bind_names` on them again, double-counting
        # every reference they hold (e.g. inflating a builtin's reference count enough to
        # make renaming it look worthwhile when it isn't). Only `new_node`/`lam` are
        # genuinely new and need a fresh `NodeRef`; the reused ones just need reparenting.
        body = stmt.value
        args = node.args
        parent = ref(node).parent
        # The new statement takes `node`'s exact place in the tree, so it belongs to
        # exactly the scope `node` already resolved to - no need to recompute it (and
        # `ref(parent).namespace` would be wrong: `parent` here is itself a scope node,
        # so that would walk one level too far up, to the scope *containing* it).
        namespace = ref(node).namespace

        lam = ast.Lambda(args=args, body=body)
        new_node = ast.Assign(targets=[], value=lam)

        for new in (new_node, lam):
            NodeRef.new(new, parent if new is new_node else new_node)
            ref(new).namespace = namespace

        ref(args).parent = lam
        ref(body).parent = lam

        # The lambda is the function's namespace now: move its bindings over (or its parameters
        # and locals are never mangled, since the FunctionDef is no longer in the tree), and point
        # what resolved to the function at the lambda
        lam_ref, func_ref = ref(lam), ref(node)
        lam_ref.bindings, lam_ref.globals, lam_ref.nonlocals = func_ref.bindings, func_ref.globals, func_ref.nonlocals
        for root in (args, body):
            for child in ast.walk(root):
                if (child_ref := ref_or_none(child)) is not None and child_ref.namespace is node:
                    child_ref.namespace = lam

        # a keyword-callable parameter can't be renamed in place, and a lambda has no body to alias
        # it to a shorter name in (see the resolver's `visit_arg`)
        for binding in lam_ref.bindings:
            if any(isinstance(other, ast.arg) and not arg_rename_in_place(other) for other in binding.references):
                binding.disallow_rename()

        # The new target replaces `node` (the FunctionDef) as what the function's own
        # binding points at. `add_child`'s `bind_names` has no case for a plain local
        # Store (it only resolves references to *existing* bindings, e.g. nonlocals) -
        # it would silently leave this new Name with no binding at all, so the rename
        # that already touched every other reference would miss this one. Move the
        # reference over directly instead.
        target = ast.Name(id=node.name, ctx=ast.Store())
        NodeRef.new(target, new_node)
        ref(target).namespace = namespace

        binding = ref(node).binding
        binding.remove_reference(node)
        binding.add_reference(target)

        new_node.targets = [target]
        return new_node
