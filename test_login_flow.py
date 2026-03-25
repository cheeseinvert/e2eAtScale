"""
test_login_flow.py
------------------
End-to-end login, interaction, and logout flow for the application under test.

Design decisions:
  - Uses Page Object Model (POM) — selectors live in page classes, not here.
  - Login is idempotent: if the session is already authenticated, the login
    step is skipped rather than failing.
  - Each test is independent: it receives a fresh browser context via the
    `page` fixture in conftest.py.
  - Credentials are injected via environment variables — never hardcoded.
"""

import pytest
from pages.login_page import LoginPage
from pages.dashboard_page import DashboardPage


class TestLoginFlow:

    def test_successful_login(self, page, credentials):
        """
        Verify that a valid user can authenticate and land on the dashboard.
        """
        login_page = LoginPage(page)
        login_page.login(credentials["email"], credentials["password"])

        dashboard = DashboardPage(page)
        dashboard.wait_for_load()

        welcome_text = dashboard.get_welcome_text()
        assert welcome_text, "Dashboard header should be visible after login"

    def test_create_room_after_login(self, page, credentials):
        """
        Verify the primary post-login interaction: creating a room.
        Confirms that the new room card appears in the dashboard list.
        """
        login_page = LoginPage(page)
        login_page.login(credentials["email"], credentials["password"])

        dashboard = DashboardPage(page)
        dashboard.wait_for_load()

        room_title = "Automated Test Room"
        dashboard.create_room(room_title)

        assert dashboard.room_exists(room_title), (
            f"Room '{room_title}' should appear in the dashboard after creation"
        )

    def test_logout(self, page, credentials):
        """
        Verify that a logged-in user can successfully log out and is
        redirected back to the login page.
        """
        login_page = LoginPage(page)
        login_page.login(credentials["email"], credentials["password"])

        dashboard = DashboardPage(page)
        dashboard.wait_for_load()
        dashboard.logout()

        # After logout, the URL should contain /login
        assert "/login" in page.url, (
            f"Expected redirect to login page after logout, got: {page.url}"
        )

    def test_invalid_login_shows_error(self, page):
        """
        Verify that bad credentials produce a visible error message
        rather than a silent failure or crash.
        """
        login_page = LoginPage(page)
        login_page.load()
        login_page.fill(LoginPage.EMAIL_INPUT, "invalid@example.com")
        login_page.fill(LoginPage.PASSWORD_INPUT, "wrongpassword")
        login_page.click(LoginPage.SUBMIT_BUTTON)

        error = login_page.get_error_message()
        assert error, "An error banner should appear for invalid credentials"
