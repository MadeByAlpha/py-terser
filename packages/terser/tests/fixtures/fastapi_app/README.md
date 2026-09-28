# fastapi_app

A FastAPI app bundled with [rollup-py](https://github.com/MadeByAlpha/rollup-py) and minified with py-terser (from
this checkout), to check that minifying keeps its behavior: `tests/test_fastapi_app.py` builds and runs it (deselected
by default, `uv run --all-groups pytest -m e2e` from `packages/terser`). It's a uv workspace of its own, left out of
py-terser's.

- `api` (this directory) is the main app: `api.main:app`. It mounts `reports`, a separate project of the uv
  workspace (`packages/reports`), under `/reports`.
- `api.crons` serves one endpoint per package in it named by a UUID, imported by the name of its directory: no job
  is named in the code.
- The bundle uses alpha93, anyio, Cython (pure Python mode), FastAPI, httpx, numpy, Playwright, pydantic, PyYAML,
  the Vercel SDK and xattr. What the Vercel Python runtime (`vercel-runtime`) brings is left out of it: itself, and
  the packages it vendors (uvicorn, click, colorama, h11, wsproto, werkzeug, markupsafe).

## Build

uv doesn't tell a free-threaded interpreter's environment from a GIL one's, so the free-threaded build gets its
own:

```shell
export UV_PROJECT_ENVIRONMENT=.venv-3.14t
uv run --python 3.14t hatch build -t rollup
```

The `terser` hook (`[tool.hatch.build.targets.rollup.hooks.terser]`) minifies the whole bundle, vendored packages
included, with every transform on and tree-shaking from `entry`. `uv tree` shows what goes into the bundle: of the
packages `vercel-runtime` brings, only `h11` is a dependency (of `httpcore` and `httpcore2`), and `websockets` only
comes with `vercel`.

## Verify

```shell
export UV_PROJECT_ENVIRONMENT=.venv-3.14t
# Playwright's Chromium, if not the one this Playwright version downloads
export CHROMIUM_EXECUTABLE=/path/to/chromium
uv run --python 3.14t scripts/verify.py
```

`scripts/verify.py` builds the bundle twice, without the hook (from a copy of the workspace) and with it, installs
each wheel into a virtual environment of its own with uvicorn, imports every module of the minified wheel in both
(none may fail only once minified), and sends both servers the same requests: statuses, content types and bodies
must be the same, `/openapi.json` included. `--build-dir` puts the wheels, environments and logs elsewhere than
`build/`. A build taking over an hour fails: minifying numpy's `numpy.testing.overrides` once never ended.

## Exceptions

What only reflection or code outside the bundle reaches is kept by name, in the hook's configuration and in the code:

| What                                                   | Why                                                                          |
|--------------------------------------------------------|------------------------------------------------------------------------------|
| `entry`: `api.main`, the cron job packages             | uvicorn loads the app by name; `api.crons` imports each job by its directory |
| `entry`: `anyio._backends._asyncio`                    | `import_module(f"anyio._backends._{name}")`                                  |
| `entry`: `websockets` and the modules of it uvicorn imports | uvicorn (outside the bundle) uses `websockets` when it can import it   |
| `preserve_type_checking`: `anyio`, `anyio.abc`         | anyio's lazy importer parses the imports under `if TYPE_CHECKING`            |
| `keep_future_annotations`                              | pydantic evaluates `ConfigDict.__annotations__`                              |
| `preserve_locals`: `**extra` of pydantic's `Field`     | read back through `inspect.signature()`                                      |
| `preserve_globals`, `preserve_modules`                 | names looked up by string (for when mangling is on)                          |
| `@terser_hints.preserve_annotations`                   | FastAPI reads the signatures of endpoints, pydantic the fields of models     |
| `@terser_hints.preserve_docstring`                     | FastAPI and pydantic put docstrings in the OpenAPI schema                    |

Mangling (`hoist_literals`, `rename_*`) is off for now: the transforms and tree-shaking are verified first.
