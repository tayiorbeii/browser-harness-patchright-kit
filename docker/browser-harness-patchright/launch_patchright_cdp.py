#!/usr/bin/env python3
"""Launch Patchright Chrome with a CDP endpoint for browser-harness.

The container process stays alive while the persistent browser context is open.
browser-harness connects to Chrome DevTools Protocol (CDP), not to Patchright
itself.
"""

from __future__ import annotations

import json
import os
import shlex
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

from patchright.sync_api import sync_playwright

CDP_HOST = "0.0.0.0"
CHROME_CDP_HOST = "127.0.0.1"
USER_DATA_DIR = Path("/data/profile")
DOWNLOADS_DIR = Path(os.environ.get("PATCHRIGHT_DOWNLOADS_DIR", "/data/downloads"))


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def start_xvfb(headless: bool) -> subprocess.Popen[bytes] | None:
    if headless:
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


def pipe_socket(src: socket.socket, dst: socket.socket) -> None:
    try:
        while True:
            data = src.recv(65536)
            if not data:
                break
            dst.sendall(data)
    except OSError:
        pass
    finally:
        try:
            dst.shutdown(socket.SHUT_WR)
        except OSError:
            pass


def start_tcp_proxy(listen_port: int, target_port: int) -> socket.socket:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((CDP_HOST, listen_port))
    server.listen(64)

    def accept_loop() -> None:
        while True:
            try:
                client, _ = server.accept()
                target = socket.create_connection((CHROME_CDP_HOST, target_port))
            except OSError:
                break
            threading.Thread(target=pipe_socket, args=(client, target), daemon=True).start()
            threading.Thread(target=pipe_socket, args=(target, client), daemon=True).start()

    threading.Thread(target=accept_loop, daemon=True).start()
    return server


def wait_for_cdp(port: int, timeout_s: int = 30) -> None:
    probe_url = f"http://127.0.0.1:{port}/json/version"
    deadline = time.time() + timeout_s
    last_error: Exception | None = None

    while time.time() < deadline:
        try:
            with urllib.request.urlopen(probe_url, timeout=2) as response:
                data = json.loads(response.read().decode("utf-8"))
            print(
                json.dumps(
                    {
                        "status": "ready",
                        "cdp": f"http://{CDP_HOST}:{port}",
                        "probe": probe_url,
                        "webSocketDebuggerUrl": data.get("webSocketDebuggerUrl"),
                    }
                ),
                flush=True,
            )
            return
        except Exception as exc:  # noqa: BLE001 - readiness loop should keep retrying
            last_error = exc
            time.sleep(0.5)

    raise RuntimeError(f"CDP did not become ready at {probe_url}: {last_error}")


def main() -> int:
    cdp_port = int(os.environ.get("CDP_PORT", "9222"))
    chrome_cdp_port = int(os.environ.get("CHROME_CDP_PORT", str(cdp_port + 1)))
    headless = env_bool("PATCHRIGHT_HEADLESS", False)
    browser_executable = os.environ.get("PATCHRIGHT_BROWSER_EXECUTABLE", "").strip() or None
    browser_channel = os.environ.get("PATCHRIGHT_BROWSER_CHANNEL", "").strip() or None

    # Chrome/Chromium remote-debugging security checks reject the default profile.
    # Always use this non-default persistent user data dir for CDP launches.
    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    # This profile volume belongs only to this project container. If Chrome or
    # emulated Chrome crashed previously, stale singleton locks can block a safe
    # restart even though no browser process exists in the fresh container.
    for stale_lock in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
        try:
            (USER_DATA_DIR / stale_lock).unlink()
        except FileNotFoundError:
            pass

    xvfb = start_xvfb(headless)
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

    # Keep launch args minimal. Do not add stealth/anti-bot flags here; let
    # Patchright provide its own behavior so browser-harness does not diverge.
    launch_args = [
        f"--remote-debugging-address={CHROME_CDP_HOST}",
        f"--remote-debugging-port={chrome_cdp_port}",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    extra_args = os.environ.get("PATCHRIGHT_EXTRA_ARGS", "").strip()
    if extra_args:
        parsed_extra_args = shlex.split(extra_args)
        forbidden_prefixes = ("--remote-debugging", "--user-data-dir")
        forbidden = [arg for arg in parsed_extra_args if arg.startswith(forbidden_prefixes)]
        if forbidden:
            raise ValueError(f"PATCHRIGHT_EXTRA_ARGS may not override CDP/profile flags: {forbidden}")
        launch_args.extend(parsed_extra_args)

    with sync_playwright() as playwright:
        launch_options = {}
        if browser_executable:
            launch_options["executable_path"] = browser_executable
        else:
            launch_options["channel"] = browser_channel or "chrome"

        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(USER_DATA_DIR),
            **launch_options,
            headless=headless,
            no_viewport=True,
            accept_downloads=True,
            downloads_path=str(DOWNLOADS_DIR),
            chromium_sandbox=env_bool("CHROMIUM_SANDBOX", False),
            args=launch_args,
        )

        if not context.pages:
            context.new_page()

        wait_for_cdp(chrome_cdp_port)
        proxy = start_tcp_proxy(cdp_port, chrome_cdp_port)
        print(json.dumps({"status": "proxy", "cdp": f"http://{CDP_HOST}:{cdp_port}", "target": f"http://{CHROME_CDP_HOST}:{chrome_cdp_port}"}), flush=True)

        while True:
            time.sleep(3600)


if __name__ == "__main__":
    raise SystemExit(main())
