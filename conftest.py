import pytest
from playwright.sync_api import sync_playwright, Browser, Page


# ---------------------------------------------------------------------------
# Browser lifecycle — scoped to the session for speed.
# A single browser process is shared across all tests in a run.
# Each test gets its own isolated BrowserContext (and therefore its own
# cookies, local storage, and auth state).
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def browser():
    """Launch a single Chromium browser for the entire test session."""
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",           # Required inside Docker / Lambda
                "--disable-dev-shm-usage" # Prevents /dev/shm OOM in containers
            ]
        )
        yield browser
        browser.close()


@pytest.fixture(scope="function")
def context(browser: Browser):
    """
    Each test gets a fresh BrowserContext — isolated cookies and storage.
    This is the Playwright equivalent of a clean browser profile per test.
    """
    ctx = browser.new_context(
        viewport={"width": 1280, "height": 720},
        ignore_https_errors=True  # Useful in staging environments
    )
    yield ctx
    ctx.close()


@pytest.fixture(scope="function")
def page(context) -> Page:
    """Open a single tab inside the isolated context."""
    page = context.new_page()
    yield page
    page.close()


# ---------------------------------------------------------------------------
# Credentials — read from environment variables so secrets are never
# hard-coded. In Lambda, these are injected via the function's environment
# or AWS Secrets Manager.
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def credentials():
    import os
    return {
        "email":    os.environ["TEST_EMAIL"],
        "password": os.environ["TEST_PASSWORD"]
    }
