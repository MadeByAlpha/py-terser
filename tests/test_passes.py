from functools import partial

import anyio
import pytest

from helpers import write_tree
from terser import TransformConfig, minify, minify_project
from terser._pipeline import mangler, parser, transforms
from terser._pipeline.transforms._suite import SuiteTransformer, TransformCache, TransformerFlag
from terser.ast import ast, ref

pytestmark = pytest.mark.xfail(strict=True, reason="pass tracking is not implemented (TransformCache.passes is never filled)")


def renamer(old: str, new: str, flags: int = 0):
    """A transform that renames every `old` name to `new`, counting how many times it ran."""

    class Rename(SuiteTransformer):
        FLAGS = flags
        runs = 0

        @classmethod
        def is_enabled(cls, config, /):
            return True

        def __init__(self, ctx, /):
            super().__init__(ctx)
            type(self).runs += 1

        def visit_Name(self, node):
            if node.id == old:
                node.id = new
            return node

    Rename.__name__ = Rename.__qualname__ = f"Rename_{old}_{new}"
    return Rename


def chain(depth: int = 2):
    # `b -> a` runs before `c -> b` (and so on), so `c` needs two passes to become `a`
    letters = "abcdefghij"[:depth + 1]
    return [renamer(new_name, old_name) for old_name, new_name in zip(letters, letters[1:])]


def names(module: ast.Module) -> list[str]:
    return [node.id for node in ast.walk(module) if isinstance(node, ast.Name)]


def run_passes(source: str, transform_list, passes: int, max_flags: int = 4):
    module = parser.parse(source, "test_module.py")
    cache = TransformCache(TransformConfig(passes=passes), transform_list)
    for _ in range(passes):
        module, changed = cache.run(module, max_flags)
        if not changed:
            break
    return module


def test_runs_until_fixed_point():
    assert names(run_passes("c", chain(), passes=5)) == ["a"]


def test_respects_pass_limit():
    assert names(run_passes("c", chain(), passes=1)) == ["b"]


def test_skips_transforms_when_nothing_changed():
    first, second = transform_list = chain()
    run_passes("c", transform_list, passes=10)
    # pass 1: `c -> b` changes the module; pass 2: `b -> a` changes it; pass 3: nothing left to do
    assert (first.runs, second.runs) == (2, 2)


def test_reports_modification():
    module = parser.parse("x", "test_module.py")
    cache = TransformCache(TransformConfig(), chain())
    assert cache.run(module, 4) == (module, False)
    assert not any(cache.passes.values())


def test_max_flags():
    late = renamer("c", "b", flags=TransformerFlag.INFLUENCES_MANGLING)
    assert names(run_passes("c", [late], passes=5, max_flags=2)) == ["c"]
    assert names(run_passes("c", [late], passes=5, max_flags=4)) == ["b"]


def test_minify_runs_multiple_passes(monkeypatch):
    # deeper than the number of pipeline stages, so only repeated passes get it to `a`
    monkeypatch.setattr(transforms, "__transforms__", chain(depth=6))
    config = TransformConfig(passes=6)
    assert minify("g = 1\nprint(g)", config, rename_locals=False, hoist_literals=False) == "a=1\nprint(a)"


def test_project_transforms_every_module(monkeypatch, tmp_path):
    seen = []

    class Spy(SuiteTransformer):
        FLAGS = TransformerFlag.REQUIRES_MODULE_RESOLVE

        @classmethod
        def is_enabled(cls, config, /):
            return True

        def visit_Module(self, node):
            if phase:
                seen.append((phase[-1], str(ref(node).spec)))
            return node

    # record which modules go through the project transform phase: after module mangling (which
    # starts that phase), before global mangling (which ends it)
    phase = []

    def spy(name, func):
        def wrapper(*args, **kwargs):
            phase.append(name)
            return func(*args, **kwargs)
        monkeypatch.setattr(mangler, name, wrapper)

    spy("mangle_modules", mangler.mangle_modules)
    spy("mangle_globals", mangler.mangle_globals)
    monkeypatch.setattr(transforms, "__transforms__", [Spy])
    root = write_tree(tmp_path / "app", {"a.py": "import b\nx = 1", "b.py": "y = 2", "c.py": "z = 3"})
    anyio.run(partial(minify_project, TransformConfig(), {str(root)}, output=anyio.Path(tmp_path / "out")))
    assert {module for name, module in seen if name == "mangle_modules"} == {"a", "b", "c"}
