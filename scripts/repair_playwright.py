import asyncio
import os
import shutil
import subprocess
import sys
from pathlib import Path


def log(message: str) -> None:
    print(f"[runtime] {message}", flush=True)


def browser_dir() -> Path | None:
    configured = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if configured:
        return Path(configured)
    return None


def run_playwright_install() -> bool:
    command = [sys.executable, "-m", "playwright", "install", "chromium"]
    log("Installing/checking Playwright Chromium...")
    result = subprocess.run(command)
    return result.returncode == 0


async def validate_chromium() -> bool:
    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto("about:blank")
            await browser.close()
        log("Playwright Chromium launch check passed.")
        return True
    except Exception as exc:
        log(f"Playwright Chromium launch check failed: {exc}")
        return False


def remove_browser_cache() -> None:
    path = browser_dir()
    if not path or not path.exists():
        return
    log(f"Removing possibly corrupted browser cache: {path}")
    shutil.rmtree(path, ignore_errors=True)


async def main() -> int:
    attempts = 2
    for attempt in range(1, attempts + 1):
        log(f"Browser repair attempt {attempt}/{attempts}.")
        if run_playwright_install() and await validate_chromium():
            return 0

        if attempt < attempts:
            remove_browser_cache()

    log("Browser setup is still broken after repair attempts.")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
