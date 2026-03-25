from playwright.sync_api import Page


class BasePage:
    """
    Base class for all Page Object Models.
    Provides shared utilities: navigation, waiting, and element helpers.
    """

    def __init__(self, page: Page):
        self.page = page

    def navigate(self, url: str):
        self.page.goto(url, wait_until="networkidle")

    def wait_for_selector(self, selector: str, timeout: int = 10000):
        self.page.wait_for_selector(selector, timeout=timeout)

    def click(self, selector: str):
        self.page.locator(selector).click()

    def fill(self, selector: str, value: str):
        self.page.locator(selector).fill(value)

    def get_text(self, selector: str) -> str:
        return self.page.locator(selector).inner_text()

    def is_visible(self, selector: str) -> bool:
        return self.page.locator(selector).is_visible()
