import pytest

from helpers import apply_transform, assert_code, only
from terser._pipeline.transforms import Contracts
from terser.utils import contracts


@pytest.mark.parametrize("source,expected", [
    ("from typing import cast\nx = cast(int, y)", "from typing import cast\nx = y"),
    ("from typing import cast as c\nx = c(int, y)", "from typing import cast as c\nx = y"),
    ("from typing import assert_type\nx = assert_type(y, int)", "from typing import assert_type\nx = y"),
    ("from typing import assert_never\nassert_never(y)", "from typing import assert_never\nNone"),
    # not the contracted function
    ("def cast(a, b): return b\nx = cast(int, y)", "def cast(a, b): return b\nx = cast(int, y)"),
])
def test_default_contracts(source, expected):
    assert_code(apply_transform(source, Contracts, only("apply_contracts")), expected)


def test_custom_contract():
    config = only("apply_contracts", contracts=["mylib.identity(value) -> value"])
    actual = apply_transform("from mylib import identity\nx = identity(1 + 2)", Contracts, config)
    assert_code(actual, "from mylib import identity\nx = 1 + 2")


@pytest.mark.parametrize("rule,name,args,convert_to", [
    ("typing.cast(_, value) -> value", "typing.cast", [None, "value"], "value"),
    ("typing.assert_never(_) -> None", "typing.assert_never", [None], None),
    ("a.b.c(...) -> 0", "a.b.c", ..., "0"),
])
def test_parse_contract(rule, name, args, convert_to):
    contract = contracts.parse(rule)
    assert (contract.name, contract.args, contract.convert_to) == (name, args, convert_to)


@pytest.mark.parametrize("rule", ["typing.cast(_, value)", "typing.cast -> value", "f(1) -> x"])
def test_parse_invalid_contract(rule):
    with pytest.raises(ValueError):
        contracts.parse(rule)
