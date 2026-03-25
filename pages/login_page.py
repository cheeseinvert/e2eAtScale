from pages.base_page import BasePage
from playwright.sync_api import Page


class LoginPage(BasePage):
    """
    Page Object for the application login screen.
    Encapsulates all selectors and actions related to authentication.
    """

    # example:
    ## URL = "https://app.example.com/login"
    # if running docs index.html and `python3 local_runner.py`
    ## URL = "http://host.docker.internal:8000/index.html#login"
    # if running docs index.html and `pytest_login_flow.py`
    URL = "http://localhost:8000/index.html#login"

    # Selectors — centralised here so changes to the DOM only require
    # updates in one place, not scattered across test files.
    EMAIL_INPUT = "[data-testid='email-input']"
    PASSWORD_INPUT = "[data-testid='password-input']"
    SUBMIT_BUTTON = "[data-testid='login-submit']"
    ERROR_BANNER = "[data-testid='login-error']"

    def __init__(self, page: Page):
        super().__init__(page)

    def load(self):
        """Navigate to the login page and confirm it is ready."""
        self.navigate(self.URL)
        self.wait_for_selector(self.EMAIL_INPUT)

    def login(self, email: str, password: str):
        """
        Idempotent login: if the user is already authenticated and
        lands on the dashboard, skip the login flow entirely.
        This prevents test failures when session cookies survive
        between runs in a shared browser context.
        """
        if "#dashboard" in self.page.url:
            return  # Already logged in — nothing to do

        self.load()
        self.fill(self.EMAIL_INPUT, email)
        self.fill(self.PASSWORD_INPUT, password)
        self.click(self.SUBMIT_BUTTON)

        # Hash-based SPA — wait for the hash to change rather than a page navigation
        self.page.wait_for_function(
            "window.location.hash === '#dashboard'", timeout=15000
        )

    def get_error_message(self) -> str:
        self.wait_for_selector(self.ERROR_BANNER)
        return self.get_text(self.ERROR_BANNER)
