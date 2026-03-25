from pages.base_page import BasePage
from playwright.sync_api import Page


class DashboardPage(BasePage):
    """
    Page Object for the application instructor dashboard.
    Covers the primary post-login landing surface.
    """

    # Selectors
    WELCOME_HEADER    = "[data-testid='dashboard-header']"
    CREATE_ROOM_BTN   = "[data-testid='create-room-button']"
    ROOM_TITLE_INPUT  = "[data-testid='room-title-input']"
    CONFIRM_BTN       = "[data-testid='confirm-button']"
    ROOM_CARD         = "[data-testid='room-card']"
    USER_MENU         = "[data-testid='user-menu']"
    LOGOUT_OPTION     = "[data-testid='logout-option']"

    def __init__(self, page: Page):
        super().__init__(page)

    def wait_for_load(self):
        """Block until the dashboard header is visible."""
        self.wait_for_selector(self.WELCOME_HEADER)

    def get_welcome_text(self) -> str:
        return self.get_text(self.WELCOME_HEADER)

    def create_room(self, title: str):
        """
        Generic interaction: open the room creation dialog,
        fill in a title, and confirm.
        """
        self.click(self.CREATE_ROOM_BTN)
        self.wait_for_selector(self.ROOM_TITLE_INPUT)
        self.fill(self.ROOM_TITLE_INPUT, title)
        self.click(self.CONFIRM_BTN)

        # Wait for the new room card to appear in the list
        self.page.wait_for_selector(
            f"{self.ROOM_CARD}:has-text('{title}')", timeout=10000
        )

    def room_exists(self, title: str) -> bool:
        return self.page.locator(
            f"{self.ROOM_CARD}:has-text('{title}')"
        ).count() > 0

    def logout(self):
        """
        Open the user menu and click logout.
        Waits for redirect back to the login page to confirm success.
        """
        self.click(self.USER_MENU)
        self.wait_for_selector(self.LOGOUT_OPTION)
        self.click(self.LOGOUT_OPTION)
        self.page.wait_for_url("**/login**", timeout=10000)
