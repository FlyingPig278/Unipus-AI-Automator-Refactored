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


def playwright_download_hosts() -> list[str]:
    configured_hosts = os.environ.get("PLAYWRIGHT_DOWNLOAD_HOSTS")
    if configured_hosts is not None:
        hosts = [host.strip() for host in configured_hosts.split(",")]
    else:
        current_host = os.environ.get("PLAYWRIGHT_DOWNLOAD_HOST")
        hosts = [current_host] if current_host else ["https://npmmirror.com/mirrors/playwright"]

    # 空字符串表示使用 Playwright 官方默认下载源，作为最后兜底。
    if "" not in hosts:
        hosts.append("")

    normalized = []
    for host in hosts:
        if host not in normalized:
            normalized.append(host)
    return normalized


def run_playwright_install(download_host: str) -> bool:
    command = [sys.executable, "-m", "playwright", "install", "chromium"]
    env = os.environ.copy()
    if download_host:
        env["PLAYWRIGHT_DOWNLOAD_HOST"] = download_host
        env.pop("PLAYWRIGHT_CHROMIUM_DOWNLOAD_HOST", None)
        log(f"Installing/checking Playwright Chromium via mirror: {download_host}")
    else:
        env.pop("PLAYWRIGHT_DOWNLOAD_HOST", None)
        env.pop("PLAYWRIGHT_CHROMIUM_DOWNLOAD_HOST", None)
        log("Installing/checking Playwright Chromium via official source...")

    result = subprocess.run(command, env=env)
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
    hosts = playwright_download_hosts()
    attempts_per_host = 2
    total_attempts = len(hosts) * attempts_per_host
    attempt = 0

    for host in hosts:
        for host_attempt in range(1, attempts_per_host + 1):
            attempt += 1
            host_label = host or "official"
            log(f"Browser repair attempt {attempt}/{total_attempts} ({host_label}, {host_attempt}/{attempts_per_host}).")
            if run_playwright_install(host) and await validate_chromium():
                return 0

            if attempt < total_attempts:
                remove_browser_cache()

    log("Browser setup is still broken after repair attempts.")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
