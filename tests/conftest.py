from pathlib import Path

import pytest

PW_FALLBACK = Path("/opt/pw-browsers/chromium")     # a pre-installed build whose revision may not match the pin


def launch_chromium(pw):
    """The bundled build first; a pre-installed Chromium second (revision mismatches are common on CI images)."""
    try:
        return pw.chromium.launch()
    except Exception:
        if not PW_FALLBACK.exists():
            raise
        return pw.chromium.launch(executable_path=str(PW_FALLBACK))


@pytest.fixture(scope="session")
def chromium_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            launch_chromium(pw).close()
        return True
    except Exception:
        return False


@pytest.fixture
def browser(chromium_available):
    if not chromium_available:
        pytest.skip("Playwright Chromium cannot launch (uv run playwright install chromium)")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = launch_chromium(pw)
        yield b
        b.close()
