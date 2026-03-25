from pages.base_page import BasePage
from playwright.sync_api import Page


class LoginPage(BasePage):
    """
    Page Object for the application login screen.
    Encapsulates all selectors and actions related to authentication.
    """

    URL = "https://app.example.com/login"

    # Selectors — centralised here so changes to the DOM only require
    # updates in one place, not scattered across test files.
    EMAIL_INPUT    = "[data-testid='email-input']"
    PASSWORD_INPUT = "[data-testid='password-input']"
    SUBMIT_BUTTON  = "[data-testid='login-submit']"
    ERROR_BANNER   = "[data-testid='login-error']"

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
        if self.page.url != self.URL and "/dashboard" in self.page.url:
            return  # Already logged in — nothing to do

        self.load()
        self.fill(self.EMAIL_INPUT, email)
        self.fill(self.PASSWORD_INPUT, password)
        self.click(self.SUBMIT_BUTTON)

        # Wait for navigation away from the login page
        self.page.wait_for_url("**/dashboard**", timeout=15000)

    def get_error_message(self) -> str:
        self.wait_for_selector(self.ERROR_BANNER)
        return self.get_text(self.ERROR_BANNER)
