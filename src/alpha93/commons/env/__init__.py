from __future__ import annotations

from os import environ


def get(name: str, default: str | None = None, /):
    return environ.get(name, default)

def __getattr__(name: str, /):
    return environ[name]
