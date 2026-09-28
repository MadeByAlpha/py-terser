from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter
from playwright.async_api import async_playwright
from terser_hints import preserve_annotations, preserve_docstring

from ..models import Page

router = APIRouter(prefix="/browser", tags=["browser"])


@router.post("/render")
@preserve_annotations
@preserve_docstring
async def render(page: Page) -> dict[str, Any]:
    """Load `html` in headless Chromium, and evaluate `script` in it."""
    async with async_playwright() as p:
        # `CHROMIUM_EXECUTABLE` picks a Chromium other than the one bundled for this Playwright version
        browser = await p.chromium.launch(executable_path=os.environ.get("CHROMIUM_EXECUTABLE") or None)
        try:
            tab = await browser.new_page()
            await tab.set_content(page.html)
            return {
                "title": await tab.title(),
                "text": await tab.inner_text("body"),
                "links": await tab.eval_on_selector_all("a", "nodes => nodes.map(n => n.href)"),
                "result": await tab.evaluate(page.script),
            }
        finally:
            await browser.close()
