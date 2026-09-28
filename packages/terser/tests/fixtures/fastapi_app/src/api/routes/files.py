from __future__ import annotations

import tempfile
from typing import Any

import anyio
import anyio.to_thread
import xattr
from alpha93.commons import enumerate as aenumerate
from fastapi import APIRouter
from terser_hints import preserve_annotations, preserve_docstring

from ..models import Attributes

router = APIRouter(prefix="/files", tags=["files"])


def _attributes(path: str, attrs: dict[str, str]) -> dict[str, str]:
    handle = xattr.xattr(path)
    for key, value in attrs.items():
        handle.set(f"user.{key}", value.encode())
    return {key.removeprefix("user."): handle.get(key).decode() for key in sorted(handle.list())}


@router.post("/attributes")
@preserve_annotations
@preserve_docstring
async def attributes(body: Attributes) -> dict[str, Any]:
    """Write a file, tag it with extended attributes, and read them back."""
    with tempfile.TemporaryDirectory() as tmp:
        path = anyio.Path(tmp) / f"{body.name}.txt"
        await path.write_text(body.name)
        stored = await anyio.to_thread.run_sync(_attributes, str(path), body.attrs)
        return {"name": path.name, "size": (await path.stat()).st_size, "attrs": stored}


async def _produce(send: anyio.abc.ObjectSendStream[int], count: int) -> None:
    async with send:
        for i in range(count):
            await send.send(i)


@router.get("/pipeline")
@preserve_annotations
@preserve_docstring
async def pipeline(count: int = 10, workers: int = 3) -> dict[str, Any]:
    """Fan numbers out to `workers` tasks through a memory stream, and gather their squares."""
    send, receive = anyio.create_memory_object_stream[int](max_buffer_size=count)
    results: dict[int, list[int]] = {w: [] for w in range(workers)}

    async def consume(worker: int, stream: anyio.abc.ObjectReceiveStream[int]) -> None:
        async with stream:
            async for value in stream:
                results[worker].append(value * value)
                await anyio.sleep(0)

    async with anyio.create_task_group() as tg:
        tg.start_soon(_produce, send, count)
        for w in range(workers):
            tg.start_soon(consume, w, receive.clone())
        receive.close()

    squares = sorted(v for values in results.values() for v in values)
    indexed = [(i, v) async for i, v in aenumerate(_aiter(squares), 1)]
    with anyio.fail_after(5):
        total = await anyio.to_thread.run_sync(sum, squares)
    return {"squares": squares, "indexed": indexed[:3], "total": total}


async def _aiter(values: list[int]):
    for value in values:
        yield value
