"""
Browser tools — Playwright-powered headed browser automation.

Architecture:
  All Playwright calls run inside a single dedicated daemon thread via
  `_BROWSER_EXECUTOR` (a ThreadPoolExecutor with max_workers=1).
  This guarantees that:
    1. sync_playwright objects are never shared across threads.
    2. We never call asyncio.run() inside an already-running event loop
       (the FastAPI / uvicorn SelectorEventLoop on Windows).
    3. No NotImplementedError from SelectorEventLoop.subprocess_exec.

Set PLAYWRIGHT_HEADLESS=1 to run headless (useful for CI/testing).
"""
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from playwright.sync_api import sync_playwright
from tools.registry import tool

logger = logging.getLogger(__name__)

# Single-threaded executor — ALL browser calls run on this one thread
_BROWSER_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="playwright")

# Playwright singletons (owned exclusively by the browser thread)
_browser = None
_playwright = None
_page = None


def _is_headless() -> bool:
    val = os.environ.get("PLAYWRIGHT_HEADLESS", "false").strip().lower()
    return val in ("1", "true", "yes")


def _get_page():
    """Must be called only from within _BROWSER_EXECUTOR thread."""
    global _browser, _playwright, _page

    if _playwright is None:
        _playwright = sync_playwright().start()
        
    if _browser is None:
        _browser = _playwright.chromium.launch(headless=_is_headless())

    if _page is None or _page.is_closed():
        context = _browser.new_context()
        _page = context.new_page()

    return _page


def _run_in_browser_thread(fn, *args, **kwargs):
    """Submit fn to the browser thread and block until it returns."""
    future = _BROWSER_EXECUTOR.submit(fn, *args, **kwargs)
    return future.result(timeout=60)


# ─── Tool registrations ───────────────────────────────────────────────────────

@tool(
    name="open_url",
    description="Open a URL in the Playwright headed browser.",
    parameters={"url": {"type": "string", "description": "Full URL including https://"}},
    risk_level="moderate",
)
def open_url(url: str) -> dict:
    def _do():
        logger.info(f"Opening URL: {url}")
        page = _get_page()
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        return {"success": True, "url": url, "title": page.title()}
    return _run_in_browser_thread(_do)


@tool(
    name="search_web",
    description="Search the web using Google or Bing.",
    parameters={
        "query": {"type": "string", "description": "Search query"},
        "engine": {"type": "string", "description": "'google' or 'bing' (default: google)"},
    },
    risk_level="safe",
)
def search_web(query: str, engine: str = "google") -> dict:
    def _do():
        logger.info(f"Searching web: {query} (engine={engine})")
        engines = {
            "google": f"https://www.google.com/search?q={query.replace(' ', '+')}",
            "bing":   f"https://www.bing.com/search?q={query.replace(' ', '+')}",
        }
        url = engines.get(engine, engines["google"])
        page = _get_page()
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        return {"success": True, "url": url, "title": page.title()}
    return _run_in_browser_thread(_do)


@tool(
    name="browser_click",
    description="Click an element in the browser by CSS selector.",
    parameters={"selector": {"type": "string", "description": "CSS selector of the element to click"}},
    risk_level="safe",
)
def browser_click(selector: str) -> dict:
    def _do():
        page = _get_page()
        page.click(selector, timeout=10000)
        return {"success": True, "selector": selector}
    return _run_in_browser_thread(_do)


@tool(
    name="browser_type",
    description="Type text into a browser input field identified by CSS selector.",
    parameters={
        "selector": {"type": "string", "description": "CSS selector of the input field"},
        "text": {"type": "string", "description": "Text to type"},
    },
    risk_level="safe",
)
def browser_type(selector: str, text: str) -> dict:
    def _do():
        page = _get_page()
        page.fill(selector, text)
        return {"success": True, "selector": selector, "text": text}
    return _run_in_browser_thread(_do)


@tool(
    name="get_page_text",
    description="Extract readable text content from the current browser page.",
    parameters={},
    risk_level="safe",
)
def get_page_text() -> dict:
    def _do():
        page = _get_page()
        text = page.inner_text("body")
        return {"success": True, "text": text[:5000]}
    return _run_in_browser_thread(_do)


@tool(
    name="get_clickable_elements",
    description="Get all clickable elements on the current browser page with their text/aria-labels and a suggested CSS selector.",
    parameters={},
    risk_level="safe",
)
def get_clickable_elements() -> dict:
    def _do():
        page = _get_page()
        script = """
        () => {
            const elements = document.querySelectorAll('button, a, input, [role="button"], [role="tab"], [role="menuitem"], [role="textbox"], [contenteditable="true"]');
            const data = [];
            for (let el of elements) {
                const rect = el.getBoundingClientRect();
                if (rect.width === 0 || rect.height === 0) continue; 
                let text = (el.innerText || el.getAttribute('aria-label') || el.value || el.title || el.placeholder || '').trim();
                text = text.replace(/\\n/g, ' ').substring(0, 50);
                if (!text && el.tagName.toLowerCase() !== 'input') continue;
                
                let selector = `text="${text}"`;
                if (el.title) {
                    selector = `${el.tagName.toLowerCase()}[title="${el.title}"]`;
                } else if (el.getAttribute('aria-label')) {
                    selector = `${el.tagName.toLowerCase()}[aria-label="${el.getAttribute('aria-label')}"]`;
                }
                
                data.push({
                    text: text || '<empty input>',
                    tag: el.tagName.toLowerCase(),
                    selector: selector
                });
            }
            
            const seen = new Set();
            const unique = [];
            for (let d of data) {
                if (!seen.has(d.selector)) {
                    seen.add(d.selector);
                    unique.push(d);
                }
            }
            return unique;
        }
        """
        elements = page.evaluate(script)
        return {"success": True, "elements": elements}
    return _run_in_browser_thread(_do)


@tool(
    name="close_browser",
    description="Close the browser and free resources.",
    parameters={},
    risk_level="safe",
)
def close_browser() -> dict:
    def _do():
        global _browser, _playwright, _page
        if _page is not None:
            if not _page.is_closed():
                _page.close()
            _page = None
        if _browser:
            _browser.close()
            _browser = None
        if _playwright:
            _playwright.stop()
            _playwright = None
        return {"success": True}
    return _run_in_browser_thread(_do)
