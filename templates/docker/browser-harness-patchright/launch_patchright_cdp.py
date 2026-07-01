#!/usr/bin/env python3
"""Launch Patchright Chrome with a CDP endpoint for browser-harness.

The container process stays alive while the persistent browser context is open.
browser-harness connects to the exposed Chrome DevTools endpoint, not to
Patchright directly.
"""

from __future__ import annotations

import json
import os
import shlex
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from patchright.sync_api import sync_playwright


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def start_xvfb() -> subprocess.Popen[bytes] | None:
    if env_bool("PATCHRIGHT_HEADLESS", False):
        return None

    display = os.environ.get("DISPLAY", ":99")
    screen = os.environ.get("XVFB_SCREEN", "1920x1080x24")

    proc = subprocess.Popen(
        ["Xvfb", display, "-screen", "0", screen, "-nolisten", "tcp"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    time.sleep(0.5)
    return proc


def wait_for_cdp(port: int, timeout_s: int = 30) -> None:
    url = f"http://127.0.0.1:{port}/json/version"
    deadline = time.time() + timeout_s
    last_error: Exception | None = None

    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                data = json.loads(response.read().decode("utf-8"))
            print(
                json.dumps(
                    {
                        "status": "ready",
                        "cdp": url,
                        "webSocketDebuggerUrl": data.get("webSocketDebuggerUrl"),
                    }
                ),
                flush=True,
            )
            return
        except Exception as exc:  # noqa: BLE001 - readiness loop should keep retrying
            last_error = exc
            time.sleep(0.5)

    raise RuntimeError(f"CDP did not become ready at {url}: {last_error}")


def main() -> int:
    cdp_host = os.environ.get("CDP_HOST", "0.0.0.0")
    cdp_port = int(os.environ.get("CDP_PORT", "9222"))
    channel = os.environ.get("PATCHRIGHT_CHANNEL", "chrome")
    headless = env_bool("PATCHRIGHT_HEADLESS", False)
    user_data_dir = Path(os.environ.get("PATCHRIGHT_USER_DATA_DIR", "/data/profile"))
    downloads_dir = Path(os.environ.get("PATCHRIGHT_DOWNLOADS_DIR", "/data/downloads"))

    user_data_dir.mkdir(parents=True, exist_ok=True)
    downloads_dir.mkdir(parents=True, exist_ok=True)

    xvfb = start_xvfb()
    context = None

    def shutdown(*_: object) -> None:
        try:
            if context is not None:
                context.close()
        finally:
            if xvfb is not None:
                xvfb.terminate()
            sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    launch_args = [
        f"--remote-debugging-address={cdp_host}",
        f"--remote-debugging-port={cdp_port}",
        "--no-first-run",
        "--no-default-browser-check",
    ]

    extra_args = os.environ.get("PATCHRIGHT_EXTRA_ARGS", "").strip()
    if extra_args:
        launch_args.extend(shlex.split(extra_args))

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(user_data_dir),
            channel=channel,
            headless=headless,
            no_viewport=True,
            accept_downloads=True,
            downloads_path=str(downloads_dir),
            chromium_sandbox=env_bool("CHROMIUM_SANDBOX", False),
            args=launch_args,
        )

        if not context.pages:
            context.new_page()

        wait_for_cdp(cdp_port)

        while True:
            time.sleep(3600)


if __name__ == "__main__":
    raise SystemExit(main())
