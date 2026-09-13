"""Browser-based rendering fallback for JavaScript-dependent webpages.

Uses Playwright to fetch fully rendered page content when static extraction
is insufficient. Production-compatible with bounded timeouts and resource limits.
"""
import asyncio
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

from playwright.async_api import async_playwright, Browser, Page, TimeoutError as PlaywrightTimeoutError


@dataclass
class RenderConfig:
    """Configuration for browser rendering."""
    page_load_timeout_ms: int = 30_000
    network_idle_timeout_ms: int = 10_000
    max_wait_after_load_ms: int = 5_000
    viewport_width: int = 1280
    viewport_height: int = 720
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36 InquviaForensics/2.0"
    )
    headless: bool = True


@dataclass
class RenderResult:
    """Result of browser rendering."""
    success: bool = False
    html: str = ""
    text: str = ""
    title: str = ""
    status_code: Optional[int] = None
    final_url: str = ""
    load_time_ms: int = 0
    error: Optional[str] = None
    timed_out: bool = False
    resources_loaded: int = 0


class BrowserRenderer:
    """Headless browser renderer for dynamic content extraction."""

    def __init__(self, config: Optional[RenderConfig] = None):
        self.config = config or RenderConfig()
        self._browser: Optional[Browser] = None
        self._playwright = None

    async def _ensure_browser(self) -> Browser:
        if self._browser is None or not self._browser.is_connected():
            if self._playwright is None:
                self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=self.config.headless,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--no-first-run",
                    "--no-zygote",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-web-security",
                    "--disable-site-isolation-trials",
                ],
            )
        return self._browser

    async def close(self):
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

    async def render(self, url: str) -> RenderResult:
        """Render a URL and return the fully loaded page content."""
        start_time = asyncio.get_event_loop().time()
        browser = await self._ensure_browser()
        context = await browser.new_context(
            viewport={"width": self.config.viewport_width, "height": self.config.viewport_height},
            user_agent=self.config.user_agent,
            ignore_https_errors=True,
        )
        page = await context.new_page()
        page.set_default_timeout(self.config.page_load_timeout_ms)

        result = RenderResult(final_url=url)
        try:
            response = await page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=self.config.page_load_timeout_ms,
            )
            if response:
                result.status_code = response.status
                result.final_url = response.url or url

            # Wait for network to be mostly idle, but don't wait forever
            try:
                await page.wait_for_load_state("networkidle", timeout=self.config.network_idle_timeout_ms)
            except PlaywrightTimeoutError:
                # Network didn't go idle, but page might still be usable
                pass

            await asyncio.sleep(self.config.max_wait_after_load_ms / 1000)

            result.html = await page.content()
            result.text = await page.inner_text("body")
            result.title = await page.title()
            result.load_time_ms = int((asyncio.get_event_loop().time() - start_time) * 1000)
            result.success = True

        except PlaywrightTimeoutError:
            result.timed_out = True
            result.error = f"Page load timed out after {self.config.page_load_timeout_ms}ms"
            try:
                result.html = await page.content()
                result.text = await page.inner_text("body")
                result.title = await page.title()
            except Exception:
                pass

        except Exception as e:
            result.error = f"{type(e).__name__}: {e}"
            try:
                result.html = await page.content()
                result.text = await page.inner_text("body")
                result.title = await page.title()
            except Exception:
                pass

        finally:
            try:
                await context.close()
            except Exception:
                pass

        return result


async def render_page(url: str, config: Optional[RenderConfig] = None) -> RenderResult:
    """Convenience function to render a single page."""
    renderer = BrowserRenderer(config)
    try:
        return await renderer.render(url)
    finally:
        await renderer.close()


def should_render(
    html: str,
    extracted_text: str,
    js_detected: bool,
    content_quality: dict | None = None,
    min_text_threshold: int = 2000,
) -> bool:
    """Determine if browser rendering is needed based on static extraction results."""
    if not js_detected:
        return False
    if len(extracted_text) >= min_text_threshold:
        # Even if text is long enough, check quality signals
        if content_quality:
            completeness = content_quality.get("completeness", "complete")
            signals = content_quality.get("signals", {})
            # Render if content is incomplete or has suspicious signals
            if completeness in ("partial", "sparse", "empty"):
                return True
            if signals.get("labels_without_values") or signals.get("large_html_vs_text_gap"):
                return True
        return False
    if not extracted_text.strip():
        return True
    return True