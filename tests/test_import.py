"""
Import every module, so an annotation that only works with Python 3.14's lazy annotations
(e.g. a name imported under `if TYPE_CHECKING:`) fails on the oldest supported Python.
"""

import importlib
import pkgutil

import pytest

import alpha93
import terser


def all_modules():
    for package in (terser, alpha93):
        yield package.__name__
        for module in pkgutil.walk_packages(package.__path__, package.__name__ + "."):
            yield module.name


@pytest.mark.parametrize("name", sorted(all_modules()))
def test_import(name):
    importlib.import_module(name)
