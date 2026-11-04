"""Opt-in test of the built site in a real browser with real Pyodide.

Needs network access (Pyodide and mediabunny come from a CDN) and Chrome or
Chromium; set `BROWSER_EXECUTABLE` to use an installed browser.
"""

import os
from collections.abc import Iterator
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Any

import pytest

from scripts.build_pages import build_pages

pytestmark = [
    pytest.mark.browser,
    pytest.mark.fonts,
    pytest.mark.skipif(
        os.environ.get("RUN_BROWSER_TESTS") != "1",
        reason="set RUN_BROWSER_TESTS=1 to load the site in a browser",
    ),
]


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        pass


@pytest.fixture
def site_url(tmp_path: Path) -> Iterator[str]:
    # A nested path, like a GitHub Pages project site, catches absolute URLs.
    build_pages(tmp_path / "chat_to_cloud" / "_site")
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), partial(_QuietHandler, directory=str(tmp_path))
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/chat_to_cloud/_site/"
    server.shutdown()
    server.server_close()
    thread.join()


def test_generates_image_and_video_from_a_chat(
    site_url: str, sample_chat: Path, tmp_path: Path
) -> None:
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=os.environ.get("BROWSER_EXECUTABLE")
        )
        page = browser.new_page(accept_downloads=True)
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(site_url)
        expect(page.locator("#app")).to_be_visible(timeout=300_000)

        page.locator("#chat-file").set_input_files(str(sample_chat))
        expect(page.locator("#chat-summary")).to_contain_text("8 messages")

        page.locator("#language").select_option("fa")
        page.locator("#size").select_option("960x720")
        page.locator("#generate").click()
        expect(page.locator("#result-image")).to_be_visible(timeout=60_000)
        with page.expect_download() as image_download:
            page.locator("#download").click()
        assert image_download.value.suggested_filename == "sample_chat_fa_wc.png"

        page.locator("#language").select_option("emoji")
        page.locator("#kind").select_option("stable")
        page.locator("#generate").click()
        expect(page.locator("#result-video")).to_be_visible(timeout=120_000)
        with page.expect_download() as video_download:
            page.locator("#download").click()
        name = video_download.value.suggested_filename
        assert name.startswith("sample_chat_emoji_wc_animation.")
        video_path = tmp_path / name
        video_download.value.save_as(video_path)
        assert video_path.stat().st_size > 1000
        assert page.locator("#emoji-credit").is_visible()
        assert not errors
        browser.close()
