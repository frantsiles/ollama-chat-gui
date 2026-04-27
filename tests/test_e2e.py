"""E2E tests for the file explorer using Playwright.

Covered flows:
  - Page loads and shows explorer panel (smoke test)
  - File tree renders workspace contents
  - Quick Open (Ctrl+P): opens, filters, closes with Escape
  - FileViewer: opens on double-click, shows content, closes
  - Create file via context menu + dialog
  - Rename file via context menu + dialog
  - Delete to trash via context menu + confirmation dialog
  - Search panel (activity bar button): opens and finds content

Run with:
    pytest tests/test_e2e.py -v --headed          # visible browser
    pytest tests/test_e2e.py -v                   # headless (default)
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest
import requests as _requests
from playwright.sync_api import Page, expect

ROOT = Path(__file__).parent.parent
_PORT = 8791
_BASE = f"http://127.0.0.1:{_PORT}"


# ---------------------------------------------------------------------------
# Session-scoped fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def live_server():
    """Start uvicorn in a subprocess; kill it after all tests finish."""
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn", "web.server:app",
            "--host", "127.0.0.1", "--port", str(_PORT),
            "--log-level", "error",
        ],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            _requests.get(_BASE, timeout=1)
            break
        except Exception:
            time.sleep(0.4)
    else:
        proc.terminate()
        pytest.fail(f"Server did not start within 20 s on port {_PORT}")
    yield _BASE
    proc.terminate()
    proc.wait(timeout=5)


@pytest.fixture(scope="session")
def workspace(tmp_path_factory):
    """Temp workspace with predictable files used across all E2E tests."""
    ws = tmp_path_factory.mktemp("e2e_ws")
    (ws / "hello.py").write_text('print("hello world")\n')
    (ws / "notes.md").write_text("# Notes\nSome content here.\n")
    (ws / "data.json").write_text('{"key": "value"}\n')
    sub = ws / "subdir"
    sub.mkdir()
    (sub / "nested.txt").write_text("nested file content\n")
    return ws


# ---------------------------------------------------------------------------
# Per-test fixture: fresh page with workspace set and tree fully loaded
# ---------------------------------------------------------------------------

@pytest.fixture()
def explorer_page(live_server, workspace, page: Page):
    """
    Navigate to the app, wait for initial WS/session setup to complete,
    then override the workspace with our test directory.
    """
    page.goto(live_server)
    # Wait for the whole app init (WS connect + Sidebar.onConnected) to settle
    page.wait_for_load_state("networkidle", timeout=15000)

    ws_path = str(workspace)
    # Set workspace; this is the public method (no WS session required)
    page.evaluate(f"Explorer.setWorkspace({ws_path!r})")

    # Wait until data.json appears — proves the tree loaded our workspace.
    # We use data.json because CRUD tests never modify it.
    page.wait_for_selector(".tree-item-row[aria-label='data.json']", timeout=8000)

    # Silence FileWatcher tree reloads during tests to prevent DOM detach races
    page.evaluate("if (window.FileWatcher) FileWatcher._watchPath = '__test_disabled__';")

    return page


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row(page: Page, name: str):
    """Locate a tree row by its aria-label (exact filename)."""
    return page.locator(f".tree-item-row[aria-label='{name}']")


def _right_click_item(page: Page, name: str):
    """Right-click the tree row for the given filename."""
    _row(page, name).click(button="right")
    page.wait_for_selector(".context-menu", state="visible")


def _confirm_dialog(page: Page, text: str | None = None):
    """Optionally fill dialog input then click the confirm button."""
    if text is not None:
        page.locator("#explorer-dialog-input").fill(text)
    page.locator("#explorer-dialog-confirm").click()
    page.wait_for_selector("#explorer-dialog-overlay", state="hidden")


# ===========================================================================
# Tests
# ===========================================================================

class TestPageLoad:
    def test_title(self, live_server, page: Page):
        page.goto(live_server)
        expect(page).to_have_title("Ollama Chat")

    def test_activity_bar_visible(self, live_server, page: Page):
        page.goto(live_server)
        expect(page.locator(".activity-bar")).to_be_visible()

    def test_file_tree_present(self, live_server, page: Page):
        page.goto(live_server)
        expect(page.locator("#file-tree")).to_be_attached()

    def test_explorer_panel_active_by_default(self, live_server, page: Page):
        page.goto(live_server)
        expect(page.locator("#panel-explorer")).to_be_visible()


class TestExplorerTree:
    def test_workspace_files_appear(self, explorer_page: Page):
        """All top-level files of the workspace must appear in the tree."""
        page = explorer_page
        for name in ("hello.py", "notes.md", "data.json", "subdir"):
            expect(_row(page, name)).to_be_visible()

    def test_expand_folder(self, explorer_page: Page):
        """Clicking a folder row expands its children."""
        page = explorer_page
        _row(page, "subdir").click()
        expect(_row(page, "nested.txt")).to_be_visible(timeout=5000)

    def test_refresh_button_reloads_tree(self, explorer_page: Page):
        page = explorer_page
        page.locator("#explorer-refresh").click()
        page.wait_for_selector(".tree-item-row[aria-label='hello.py']", timeout=5000)
        expect(_row(page, "hello.py")).to_be_visible()

    def test_toggle_hidden_button_exists(self, explorer_page: Page):
        expect(explorer_page.locator("#explorer-toggle-hidden")).to_be_visible()


class TestQuickOpen:
    def test_ctrl_p_opens_overlay(self, explorer_page: Page):
        page = explorer_page
        # Click file-tree first to ensure document focus (not chat input)
        page.locator("#file-tree").click()
        page.keyboard.press("Control+p")
        expect(page.locator(".quick-open-overlay")).to_be_visible(timeout=3000)

    def test_filter_by_name(self, explorer_page: Page):
        page = explorer_page
        page.locator("#file-tree").click()
        page.keyboard.press("Control+p")
        page.wait_for_selector(".quick-open-overlay", state="visible")
        page.locator(".quick-open-input").fill("hello")
        expect(
            page.locator(".quick-open-item-name", has_text="hello.py")
        ).to_be_visible(timeout=5000)

    def test_escape_closes_overlay(self, explorer_page: Page):
        page = explorer_page
        page.locator("#file-tree").click()
        page.keyboard.press("Control+p")
        page.wait_for_selector(".quick-open-overlay", state="visible")
        page.keyboard.press("Escape")
        expect(page.locator(".quick-open-overlay")).to_be_hidden(timeout=3000)

    def test_click_item_opens_viewer(self, explorer_page: Page):
        """Clicking a Quick Open result opens the FileViewer."""
        page = explorer_page
        page.locator("#file-tree").click()
        page.keyboard.press("Control+p")
        page.wait_for_selector(".quick-open-overlay", state="visible")
        page.locator(".quick-open-input").fill("hello")
        page.wait_for_selector(".quick-open-item", timeout=5000)
        page.locator(".quick-open-item").first.click()
        expect(page.locator(".file-viewer-overlay")).to_be_visible(timeout=5000)
        page.locator("#file-viewer-close").click()


class TestFileViewer:
    def test_double_click_opens_viewer(self, explorer_page: Page):
        page = explorer_page
        _row(page, "notes.md").dblclick()
        expect(page.locator(".file-viewer-overlay")).to_be_visible(timeout=5000)

    def test_viewer_shows_filename(self, explorer_page: Page):
        page = explorer_page
        _row(page, "notes.md").dblclick()
        page.wait_for_selector(".file-viewer-overlay", state="visible")
        expect(page.locator("#file-viewer-name")).to_contain_text("notes.md")

    def test_viewer_shows_content(self, explorer_page: Page):
        page = explorer_page
        _row(page, "notes.md").dblclick()
        page.wait_for_selector(".file-viewer-content", state="visible", timeout=6000)
        expect(page.locator(".file-viewer-pre")).to_contain_text("Notes")

    def test_close_button(self, explorer_page: Page):
        page = explorer_page
        _row(page, "data.json").dblclick()
        page.wait_for_selector(".file-viewer-overlay", state="visible")
        page.locator("#file-viewer-close").click()
        expect(page.locator(".file-viewer-overlay")).to_be_hidden(timeout=3000)


class TestFileCRUD:
    def test_create_file(self, explorer_page: Page):
        page = explorer_page
        _right_click_item(page, "hello.py")
        page.locator("#ctx-new-file").click()
        page.wait_for_selector("#explorer-dialog-overlay:not([hidden])")
        _confirm_dialog(page, "created_by_test.txt")
        expect(_row(page, "created_by_test.txt")).to_be_visible(timeout=6000)

    def test_rename_file(self, explorer_page: Page, workspace: Path):
        # Create a dedicated rename-target so hello.py stays intact for other tests
        (workspace / "rename_me.py").write_text('# to be renamed\n')
        page = explorer_page
        page.locator("#explorer-refresh").click()
        page.wait_for_selector(".tree-item-row[aria-label='rename_me.py']", timeout=5000)

        _right_click_item(page, "rename_me.py")
        page.locator("#ctx-rename").click()
        page.wait_for_selector("#explorer-dialog-overlay:not([hidden])")
        _confirm_dialog(page, "renamed.py")
        expect(_row(page, "renamed.py")).to_be_visible(timeout=6000)

    def test_delete_to_trash(self, explorer_page: Page, workspace: Path):
        # Create a dedicated file to delete
        (workspace / "delete_me.md").write_text("to delete\n")
        page = explorer_page
        page.locator("#explorer-refresh").click()
        page.wait_for_selector(".tree-item-row[aria-label='delete_me.md']", timeout=5000)

        _right_click_item(page, "delete_me.md")
        page.locator("#ctx-delete").click()
        page.wait_for_selector("#explorer-dialog-overlay:not([hidden])")
        _confirm_dialog(page)
        expect(_row(page, "delete_me.md")).to_be_hidden(timeout=6000)
        # .trash is a hidden folder (not shown when show_hidden=false);
        # verify on disk instead
        trash_dir = workspace / ".trash"
        assert trash_dir.exists(), ".trash directory should have been created"
        assert any(trash_dir.iterdir()), ".trash should contain the moved file"


class TestSearchPanel:
    def test_activity_btn_opens_search_panel(self, explorer_page: Page):
        page = explorer_page
        page.locator(".activity-btn[data-panel='search']").click()
        expect(page.locator("#panel-search")).to_be_visible(timeout=3000)

    def test_grep_finds_content(self, explorer_page: Page, workspace: Path):
        # Ensure hello.py exists with known content
        (workspace / "hello.py").write_text('print("hello world")\n')
        page = explorer_page
        page.locator(".activity-btn[data-panel='search']").click()
        page.wait_for_selector("#panel-search", state="visible")
        page.locator(".search-panel-input").fill("hello world")
        expect(
            page.locator(".search-group-filename", has_text="hello")
        ).to_be_visible(timeout=8000)

    def test_switch_back_to_explorer(self, explorer_page: Page):
        page = explorer_page
        page.locator(".activity-btn[data-panel='search']").click()
        page.wait_for_selector("#panel-search", state="visible")
        page.locator(".activity-btn[data-panel='explorer']").click()
        expect(page.locator("#panel-explorer")).to_be_visible(timeout=3000)
