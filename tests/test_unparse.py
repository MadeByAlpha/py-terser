import ast
import sys

import pytest

from terser import unparse
from terser.ast import compare_ast
from terser.exceptions import UnbeneficialMinificationError


def round_trip(source: str) -> str:
    module = ast.parse(source)
    printed = unparse("<test>", None, module)
    compare_ast(ast.parse(source), ast.parse(printed))
    return printed


@pytest.mark.parametrize("source", [
    "x = 1\ny = 'two'\nz = b'three'\nw = 4.5j",
    "a, *b = [*c, *d]\nf(*x, **y)\nd = {**e, 'k': 1}\ns = {1, 2}",
    "x = a if b else c\ny = not a and (b or c)\nz = -a ** -b",
    "x = [i for i in range(10) if i % 2]\ny = {k: v for k, v in z}\nw = (i async for i in a)",
    "lambda *a, b=1, **k: (a, b, k)",
    "def f(a, /, b, *, c=1): pass",
    "@a.b(c)\n@d[0]\n@(lambda f: f)\ndef f(): pass",
    "class A(B, metaclass=M):\n    x = 1\n    def f(self): return self.x",
    "if (n := len(a)) > 10:\n    print(n)",
    "for i in x:\n    break\nelse:\n    pass\nwhile y:\n    continue",
    "try:\n    pass\nexcept (A, B) as e:\n    raise C from e\nelse:\n    pass\nfinally:\n    pass",
    "try:\n    pass\nexcept* ValueError:\n    pass",
    "with a as b, c as d:\n    pass\nwith (a as b, c as d):\n    pass",
    "async def f():\n    async with a as b:\n        async for i in c:\n            await i",
    "def g():\n    yield 1\n    yield from h()\n    x = yield",
    "global a\ndef f():\n    nonlocal_ = 1\n    def g():\n        nonlocal nonlocal_",
    "del a, b[0], c.d",
    "x = a[1:2, ::3, ...]",
    "match p:\n    case [1, *rest] if rest: pass\n    case {'k': v, **kw}: pass\n    case Point(x=0) | None: pass\n    case str() as s: pass\n    case _: pass",
    "x = f'{a!r:>{w}} {b=} {c:.2f}'",
    "x = f'{\"nested\"} {f\"{inner}\"}'",
    "x = rb'\\d+' + b'\\x00'",
    "x = 'quote\\'s' + \"double\\\"s\" + '''tri\nple'''",
    "def f[T: int, *Ts, **P](x: T) -> T: return x\nclass C[T]: pass\ntype Alias[T] = list[T]",
])
def test_round_trip(source):
    round_trip(source)


@pytest.mark.skipif(sys.version_info < (3, 14), reason="template strings are new in Python 3.14")
@pytest.mark.parametrize("source", [
    "x = t'hello {name!r}'",
    "x = t'{a:>{w}} {b=}'",
])
def test_template_strings(source):
    round_trip(source)


def test_output_is_compact():
    assert round_trip("def f(a, b):\n    return a + b\n") == "def f(a,b):return a+b"


def test_prefer_single_line():
    module = ast.parse("a = 1\nb = 2\n")
    assert unparse("<test>", None, module, prefer_single_line=True) == "a=1;b=2"


def test_unbeneficial():
    with pytest.raises(UnbeneficialMinificationError):
        unparse("<test>", "x=1", ast.parse("x=1"))
