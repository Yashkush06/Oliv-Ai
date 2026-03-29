"""
Unit tests for tools/browser_tools.py (dedicated-thread sync_playwright architecture).

All Playwright calls and thread-executor calls are mocked so tests run instantly.
"""
import os
import pytest
from unittest.mock import MagicMock, patch


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_page(inner_text: str = "Hello World") -> MagicMock:
    page = MagicMock()
    page.is_closed.return_value = False
    page.title.return_value = "Test Page"
    page.inner_text.return_value = inner_text
    return page


def _make_playwright_and_browser(page: MagicMock):
    ctx = MagicMock()
    ctx.new_page.return_value = page
    browser = MagicMock()
    browser.new_context.return_value = ctx
    pw = MagicMock()
    pw.chromium.launch.return_value = browser
    # sync_playwright() returns a context manager whose __enter__ returns pw
    sp_cm = MagicMock()
    sp_cm.__enter__ = MagicMock(return_value=pw)
    sp_cm.__exit__ = MagicMock(return_value=False)
    sp_cm.start.return_value = pw
    return sp_cm, browser, pw


def _run_directly(fn):
    """
    Patch _run_in_browser_thread so it just calls fn() synchronously.
    This lets us test the inner _do() closures without a real thread pool.
    """
    return patch("tools.browser_tools._run_in_browser_thread", side_effect=lambda f, *a, **kw: f())


# ── fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_globals():
    import tools.browser_tools as bt
    bt._browser = None
    bt._playwright = None
    bt._page = None
    os.environ["PLAYWRIGHT_HEADLESS"] = "true"
    yield
    bt._browser = None
    bt._playwright = None
    bt._page = None
    os.environ.pop("PLAYWRIGHT_HEADLESS", None)


# ── _is_headless ─────────────────────────────────────────────────────────────

class TestIsHeadless:
    def test_true_when_1(self):
        from tools.browser_tools import _is_headless
        os.environ["PLAYWRIGHT_HEADLESS"] = "1"
        assert _is_headless() is True

    def test_true_when_true(self):
        from tools.browser_tools import _is_headless
        os.environ["PLAYWRIGHT_HEADLESS"] = "true"
        assert _is_headless() is True

    def test_false_when_false(self):
        from tools.browser_tools import _is_headless
        os.environ["PLAYWRIGHT_HEADLESS"] = "false"
        assert _is_headless() is False

    def test_false_when_unset(self):
        from tools.browser_tools import _is_headless
        os.environ.pop("PLAYWRIGHT_HEADLESS", None)
        assert _is_headless() is False


# ── open_url ─────────────────────────────────────────────────────────────────

class TestOpenUrl:
    def test_success(self):
        page = _make_page()
        sp_cm, browser, pw = _make_playwright_and_browser(page)
        with _run_directly(None):
            with patch("tools.browser_tools.sync_playwright", return_value=sp_cm):
                from tools.browser_tools import open_url
                result = open_url("https://example.com")
        assert result["success"] is True
        assert result["url"] == "https://example.com"
        assert result["title"] == "Test Page"

    def test_goto_args(self):
        page = _make_page()
        sp_cm, _, _ = _make_playwright_and_browser(page)
        with _run_directly(None):
            with patch("tools.browser_tools.sync_playwright", return_value=sp_cm):
                from tools.browser_tools import open_url
                open_url("https://example.com")
        page.goto.assert_called_once_with(
            "https://example.com", wait_until="domcontentloaded", timeout=30000
        )


# ── search_web ───────────────────────────────────────────────────────────────

class TestSearchWeb:
    def _run(self, query, engine="google"):
        page = _make_page()
        sp_cm, _, _ = _make_playwright_and_browser(page)
        with _run_directly(None):
            with patch("tools.browser_tools.sync_playwright", return_value=sp_cm):
                from tools.browser_tools import search_web
                result = search_web(query, engine)
        return result, page

    def test_google_url(self):
        result, page = self._run("vite docs", "google")
        assert result["success"] is True
        url = page.goto.call_args[0][0]
        assert "google.com/search" in url
        assert "vite+docs" in url

    def test_bing_url(self):
        _, page = self._run("weather", "bing")
        url = page.goto.call_args[0][0]
        assert "bing.com/search" in url

    def test_unknown_engine_falls_back_to_google(self):
        _, page = self._run("foo", "yahoo")
        url = page.goto.call_args[0][0]
        assert "google.com/search" in url


# ── browser_click ─────────────────────────────────────────────────────────────

class TestBrowserClick:
    def test_click(self):
        page = _make_page()
        sp_cm, _, _ = _make_playwright_and_browser(page)
        with _run_directly(None):
            with patch("tools.browser_tools.sync_playwright", return_value=sp_cm):
                from tools.browser_tools import browser_click
                result = browser_click("#btn")
        assert result["success"] is True
        page.click.assert_called_once_with("#btn", timeout=10000)


# ── browser_type ─────────────────────────────────────────────────────────────

class TestBrowserType:
    def test_type(self):
        page = _make_page()
        sp_cm, _, _ = _make_playwright_and_browser(page)
        with _run_directly(None):
            with patch("tools.browser_tools.sync_playwright", return_value=sp_cm):
                from tools.browser_tools import browser_type
                result = browser_type("#inp", "hello")
        assert result["success"] is True
        page.fill.assert_called_once_with("#inp", "hello")


# ── get_page_text ─────────────────────────────────────────────────────────────

class TestGetPageText:
    def test_returns_text(self):
        page = _make_page(inner_text="Welcome!")
        sp_cm, _, _ = _make_playwright_and_browser(page)
        with _run_directly(None):
            with patch("tools.browser_tools.sync_playwright", return_value=sp_cm):
                from tools.browser_tools import get_page_text
                result = get_page_text()
        assert result["success"] is True
        assert "Welcome!" in result["text"]

    def test_text_capped(self):
        page = _make_page(inner_text="A" * 10_000)
        sp_cm, _, _ = _make_playwright_and_browser(page)
        with _run_directly(None):
            with patch("tools.browser_tools.sync_playwright", return_value=sp_cm):
                from tools.browser_tools import get_page_text
                result = get_page_text()
        assert len(result["text"]) == 5000


# ── close_browser ─────────────────────────────────────────────────────────────

class TestCloseBrowser:
    def test_close(self):
        import tools.browser_tools as bt
        page = MagicMock()
        page.is_closed.return_value = False
        browser = MagicMock()
        pw = MagicMock()
        bt._page, bt._browser, bt._playwright = page, browser, pw

        with _run_directly(None):
            from tools.browser_tools import close_browser
            result = close_browser()

        assert result["success"] is True
        page.close.assert_called_once()
        browser.close.assert_called_once()
        pw.stop.assert_called_once()

    def test_close_when_nothing_open(self):
        with _run_directly(None):
            from tools.browser_tools import close_browser
            result = close_browser()
        assert result["success"] is True
