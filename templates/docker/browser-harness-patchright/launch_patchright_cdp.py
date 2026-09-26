#!/usr/bin/env python3
"""Launch Patchright Chrome with a CDP endpoint for browser-harness.

The container process stays alive while the persistent browser context is open.
browser-harness connects to Chrome DevTools Protocol (CDP), not to Patchright
itself.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shlex
import signal
import socket
import stat
import struct
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from patchright.sync_api import sync_playwright

CDP_HOST = "0.0.0.0"
CHROME_CDP_HOST = "127.0.0.1"
USER_DATA_DIR = Path("/data/profile")
DOWNLOADS_DIR = Path(os.environ.get("PATCHRIGHT_DOWNLOADS_DIR", "/data/downloads"))
PROC_ROOT = Path("/proc")
TMP_ROOT = Path("/tmp")


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def parse_host_resolver_rules(raw: str) -> str | None:
    """Validate the dedicated Chromium host resolver setting.

    Keep the Chromium rule expression as one launch argument. The supported
    contract accepts comma-separated MAP and EXCLUDE directives, including the
    common rule `MAP localhost host.docker.internal`.
    """

    value = raw.strip()
    if not value:
        return None
    if value.startswith("--") or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("BH_HOST_RESOLVER_RULES must be a single Chromium rule expression")

    for rule in value.split(","):
        fields = rule.strip().split()
        if not fields:
            raise ValueError("BH_HOST_RESOLVER_RULES contains an empty rule")
        directive = fields[0].upper()
        if directive == "MAP" and len(fields) == 3:
            continue
        if directive == "EXCLUDE" and len(fields) == 2:
            continue
        raise ValueError(
            "BH_HOST_RESOLVER_RULES accepts MAP <source> <target> or EXCLUDE <host> directives"
        )

    return value


def build_launch_args(extra_args_raw: str, host_resolver_rules_raw: str) -> list[str]:
    """Build and validate Chromium arguments owned by the harness contract."""

    launch_args = [
        f"--remote-debugging-address={CHROME_CDP_HOST}",
        # The browser listens on loopback; a container-local TCP proxy publishes
        # CDP on the container interface for Docker's loopback-only host mapping.
        "--no-first-run",
        "--no-default-browser-check",
    ]

    parsed_extra_args = shlex.split(extra_args_raw) if extra_args_raw.strip() else []
    forbidden: list[str] = []
    for arg in parsed_extra_args:
        if arg.startswith(("--remote-debugging", "--user-data-dir")):
            forbidden.append(arg)
        elif arg == "--host-resolver-rules" or arg.startswith("--host-resolver-rules="):
            forbidden.append(arg)
        elif arg == "--ignore-certificate-errors" or arg.startswith("--ignore-certificate-errors="):
            forbidden.append(arg)

    if forbidden:
        raise ValueError(
            "PATCHRIGHT_EXTRA_ARGS contains harness-owned or broad certificate flags: "
            f"{forbidden}"
        )

    resolver_rules = parse_host_resolver_rules(host_resolver_rules_raw)
    if resolver_rules is not None:
        launch_args.append(f"--host-resolver-rules={resolver_rules}")

    launch_args.extend(parsed_extra_args)
    return launch_args


def process_args(pid: int, proc_root: Path = PROC_ROOT) -> list[str]:
    try:
        raw = (proc_root / str(pid) / "cmdline").read_bytes()
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        return []
    return [part.decode(errors="replace") for part in raw.split(b"\0") if part]


def display_process_alive(display: str, proc_root: Path = PROC_ROOT) -> bool:
    for process_dir in proc_root.iterdir():
        if not process_dir.name.isdigit():
            continue
        args = process_args(int(process_dir.name), proc_root)
        if args and Path(args[0]).name in {"Xvfb", "Xtigervnc"} and display in args[1:]:
            return True
    return False


def clear_stale_display_artifacts(
    display: str,
    proc_root: Path = PROC_ROOT,
    tmp_root: Path = TMP_ROOT,
) -> list[Path]:
    """Remove X lock/socket artifacts only when no display server owns them."""
    match = re.fullmatch(r":(\d+)(?:\.\d+)?", display)
    if not match or display_process_alive(display, proc_root):
        return []

    display_number = match.group(1)
    candidates = (
        (tmp_root / f".X{display_number}-lock", stat.S_ISREG),
        (tmp_root / ".X11-unix" / f"X{display_number}", stat.S_ISSOCK),
    )
    removed: list[Path] = []
    for path, expected_type in candidates:
        try:
            mode = path.lstat().st_mode
            if expected_type(mode):
                path.unlink()
                removed.append(path)
        except FileNotFoundError:
            pass
    return removed


def start_display_server(headless: bool) -> subprocess.Popen[bytes] | None:
    """Start Xvfb normally, or TigerVNC's X server for interactive access.

    TigerVNC owns the X display when VNC is enabled so its native clipboard
    implementation can exchange modern X11 clipboard targets with VNC clients.
    The host side must still publish the VNC port on loopback only.
    """

    if headless:
        return None

    display = os.environ.get("DISPLAY", ":99")
    screen = os.environ.get("XVFB_SCREEN", "1920x1080x24")
    vnc_enabled = env_bool("BH_VNC_ENABLED", False)
    removed = clear_stale_display_artifacts(display)
    if removed:
        print(
            json.dumps({"status": "stale-display-cleared", "display": display, "paths": [str(path) for path in removed]}),
            flush=True,
        )

    if not vnc_enabled:
        display_args = ["Xvfb", display, "-screen", "0", screen, "-nolisten", "tcp"]
    else:
        try:
            width, height, depth = (int(part) for part in screen.split("x"))
        except (TypeError, ValueError):
            raise RuntimeError("XVFB_SCREEN must use WIDTHxHEIGHTxDEPTH format") from None
        if width <= 0 or height <= 0 or depth not in {16, 24, 32}:
            raise RuntimeError("XVFB_SCREEN must use positive dimensions and depth 16, 24, or 32")

        port = int(os.environ.get("BH_VNC_CONTAINER_PORT", "5900"))
        display_args = [
            "Xtigervnc",
            display,
            "-geometry",
            f"{width}x{height}",
            "-depth",
            str(depth),
            "-rfbport",
            str(port),
            "-interface",
            "0.0.0.0",
            "-AlwaysShared",
            "-AcceptCutText=1",
            "-SendCutText=1",
            "-SendPrimary=0",
            "-SetPrimary=0",
            "-UseIPv6=0",
        ]
        password_file = os.environ.get("BH_VNC_PASSWORD_FILE")
        if password_file:
            password_path = Path(password_file)
            if not password_path.is_file() or not os.access(password_path, os.R_OK):
                raise RuntimeError("BH_VNC_PASSWORD_FILE is not a readable regular file")
            display_args.extend(["-SecurityTypes", "VncAuth", "-PasswordFile", str(password_path)])
        else:
            display_args.extend(["-SecurityTypes", "None"])

    proc = subprocess.Popen(
        display_args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    time.sleep(0.5)
    if proc.poll() is not None:
        raise RuntimeError(f"display server exited during startup: {display_args[0]}")

    if vnc_enabled:
        print(
            json.dumps({"status": "vnc", "server": "tigervnc", "display": display, "port": port}),
            flush=True,
        )
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
            except OSError:
                break
            try:
                target = socket.create_connection((CHROME_CDP_HOST, target_port))
            except OSError:
                # Chrome is down or still restarting. Drop this client only: breaking
                # out here would permanently wedge the published port, so that even a
                # successfully relaunched browser stayed unreachable from outside.
                try:
                    client.close()
                except OSError:
                    pass
                time.sleep(0.25)
                continue
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


def websocket_frame(payload: bytes, opcode: int = 1) -> bytes:
    mask = os.urandom(4)
    length = len(payload)
    if length < 126:
        header = bytes((0x80 | opcode, 0x80 | length))
    elif length < 65536:
        header = bytes((0x80 | opcode, 0x80 | 126)) + struct.pack("!H", length)
    else:
        header = bytes((0x80 | opcode, 0x80 | 127)) + struct.pack("!Q", length)
    masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
    return header + mask + masked


def read_exact(connection: socket.socket, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = connection.recv(remaining)
        if not chunk:
            raise ConnectionError("CDP WebSocket closed before responding")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def read_websocket_message(connection: socket.socket) -> tuple[int, bytes]:
    first, second = read_exact(connection, 2)
    opcode = first & 0x0F
    length = second & 0x7F
    if length == 126:
        length = struct.unpack("!H", read_exact(connection, 2))[0]
    elif length == 127:
        length = struct.unpack("!Q", read_exact(connection, 8))[0]
    mask = read_exact(connection, 4) if second & 0x80 else None
    payload = read_exact(connection, length)
    if mask is not None:
        payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
    return opcode, payload


class RemoteDownloadController:
    """Hold the remote-CDP download policy for one Chromium lifetime."""

    def __init__(self, port: int) -> None:
        self.port = port
        self.connection: socket.socket | None = None
        self.browser_context_id = ""
        self.next_id = 0

    def connect(self) -> None:
        with urllib.request.urlopen(
            f"http://{CHROME_CDP_HOST}:{self.port}/json/version", timeout=2
        ) as response:
            websocket_url = json.loads(response.read().decode("utf-8"))["webSocketDebuggerUrl"]
        parsed = urlparse(websocket_url)
        if parsed.hostname != CHROME_CDP_HOST or parsed.port != self.port:
            raise RuntimeError("Chrome returned an unexpected CDP WebSocket endpoint")

        key = base64.b64encode(os.urandom(16)).decode("ascii")
        expected_accept = base64.b64encode(
            hashlib.sha1(f"{key}258EAFA5-E914-47DA-95CA-C5AB0DC85B11".encode()).digest()
        ).decode("ascii")
        connection = socket.create_connection((CHROME_CDP_HOST, self.port), timeout=2)
        request = (
            f"GET {parsed.path} HTTP/1.1\r\n"
            f"Host: {CHROME_CDP_HOST}:{self.port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        connection.sendall(request.encode("ascii"))
        response = b""
        while b"\r\n\r\n" not in response:
            response += connection.recv(4096)
        header = response.decode("latin-1").split("\r\n")
        if not header[0].startswith("HTTP/1.1 101 "):
            raise RuntimeError(f"CDP WebSocket handshake failed: {header[0]}")
        accept = next((line.split(":", 1)[1].strip() for line in header[1:] if line.lower().startswith("sec-websocket-accept:")), "")
        if accept != expected_accept:
            connection.close()
            raise RuntimeError("CDP WebSocket handshake returned an invalid accept key")
        self.connection = connection
        browser_contexts = self.send("Target.getBrowserContexts")
        self.browser_context_id = browser_contexts["defaultBrowserContextId"]
        self.apply()

    def send(self, method: str, params: dict[str, object] | None = None) -> dict[str, object]:
        if self.connection is None:
            raise ConnectionError("Remote download controller is not connected")
        self.next_id += 1
        command_id = self.next_id
        command: dict[str, object] = {"id": command_id, "method": method}
        if params is not None:
            command["params"] = params
        self.connection.sendall(websocket_frame(json.dumps(command).encode()))
        while True:
            opcode, payload = read_websocket_message(self.connection)
            if opcode == 9:
                self.connection.sendall(websocket_frame(payload, opcode=10))
                continue
            message = json.loads(payload)
            if message.get("id") == command_id:
                if "error" in message:
                    raise RuntimeError(message["error"].get("message", "CDP command failed"))
                return message.get("result", {})

    def apply(self) -> None:
        self.send(
            "Browser.setDownloadBehavior",
            {
                "behavior": "allow",
                "downloadPath": str(DOWNLOADS_DIR),
                "eventsEnabled": True,
                "browserContextId": self.browser_context_id,
            },
        )

    def close(self) -> None:
        if self.connection is None:
            return
        try:
            self.connection.sendall(websocket_frame(b"", opcode=8))
        except OSError:
            pass
        self.connection.close()
        self.connection = None


# Chrome can die while the launcher keeps idling, which leaves the container
# "running" with a dead CDP port and makes every browser client fail for reasons
# of its own. Probe the endpoint and recycle the browser when it stops answering.
BROWSER_PROBE_INTERVAL_S = 5.0
BROWSER_PROBE_MISSES = 3
BROWSER_RELAUNCH_LIMIT = 5
BROWSER_RELAUNCH_GRACE_S = 60.0
DOWNLOAD_BEHAVIOR_REFRESH_S = 1.0


def clear_stale_profile_locks() -> None:
    """Drop singleton locks left behind by a crashed Chrome.

    This profile volume belongs only to this project container, so a lock with no
    live browser behind it would otherwise block a safe restart.
    """
    for stale_lock in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
        try:
            (USER_DATA_DIR / stale_lock).unlink()
        except FileNotFoundError:
            pass


def cdp_alive(port: int) -> bool:
    """True while the local Chrome DevTools endpoint still answers."""
    try:
        with urllib.request.urlopen(
            f"http://{CHROME_CDP_HOST}:{port}/json/version", timeout=2
        ):
            return True
    except Exception:
        return False


def find_browser_pid(user_data_dir: Path, proc_root: Path = PROC_ROOT) -> int | None:
    expected_arg = f"--user-data-dir={user_data_dir}"
    for process_dir in proc_root.iterdir():
        if not process_dir.name.isdigit():
            continue
        args = process_args(int(process_dir.name), proc_root)
        if not args or expected_arg not in args or any(arg.startswith("--type=") for arg in args):
            continue
        if "chrom" in Path(args[0]).name.lower():
            return int(process_dir.name)
    return None


def decode_wait_status(wait_status: int) -> tuple[int | None, int | None]:
    if os.WIFEXITED(wait_status):
        return os.WEXITSTATUS(wait_status), None
    if os.WIFSIGNALED(wait_status):
        return None, os.WTERMSIG(wait_status)
    return None, None


class BrowserProcessMonitor:
    """Retain best-effort Linux process exit details before the driver reaps Chrome."""

    def __init__(self, pid: int | None, proc_root: Path = PROC_ROOT) -> None:
        self.pid = pid
        self.proc_root = proc_root
        self.process_state = "unknown" if pid is None else "running"
        self.exit_status: int | None = None
        self.exit_signal: int | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self.pid is None:
            return
        self._thread = threading.Thread(target=self._watch, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=0.2)

    def snapshot(self) -> dict[str, int | str | None]:
        return {
            "browser_pid": self.pid,
            "process_state": self.process_state,
            "exit_status": self.exit_status,
            "exit_signal": self.exit_signal,
        }

    def _watch(self) -> None:
        assert self.pid is not None
        stat_path = self.proc_root / str(self.pid) / "stat"
        while not self._stop.wait(0.05):
            try:
                fields = stat_path.read_text().rsplit(") ", 1)[1].split()
            except (FileNotFoundError, PermissionError, ProcessLookupError, IndexError):
                self.process_state = "exited"
                return
            self.process_state = fields[0]
            if fields[0] == "Z" and len(fields) >= 50:
                self.exit_status, self.exit_signal = decode_wait_status(int(fields[49]))
                return


def next_failure_count(current: int, browser_uptime_s: float | None) -> int:
    if browser_uptime_s is not None and browser_uptime_s >= BROWSER_RELAUNCH_GRACE_S:
        return 0
    return current + 1


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
    clear_stale_profile_locks()

    display_server = start_display_server(headless)
    context = None

    def shutdown(*_: object) -> None:
        try:
            if context is not None:
                context.close()
        finally:
            if display_server is not None:
                display_server.terminate()
            sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    # Keep launch args minimal. Do not add stealth/anti-bot flags here; let
    # Patchright provide its own behavior so browser-harness does not diverge.
    launch_args = build_launch_args(
        os.environ.get("PATCHRIGHT_EXTRA_ARGS", ""),
        os.environ.get("BH_HOST_RESOLVER_RULES", ""),
    )
    launch_args.insert(1, f"--remote-debugging-port={chrome_cdp_port}")

    with sync_playwright() as playwright:
        launch_options = {}
        if browser_executable:
            launch_options["executable_path"] = browser_executable
        else:
            launch_options["channel"] = browser_channel or "chrome"

        proxy = None
        consecutive_failures = 0
        while True:
            attempt = consecutive_failures + 1
            context = None
            browser_ready_at: float | None = None
            browser_monitor = BrowserProcessMonitor(None)
            download_controller: RemoteDownloadController | None = None
            try:
                clear_stale_profile_locks()
                context = playwright.chromium.launch_persistent_context(
                    user_data_dir=str(USER_DATA_DIR),
                    **launch_options,
                    headless=headless,
                    no_viewport=True,
                    accept_downloads=False,
                    downloads_path=str(DOWNLOADS_DIR),
                    chromium_sandbox=env_bool("CHROMIUM_SANDBOX", False),
                    args=launch_args,
                )

                if not context.pages:
                    context.new_page()

                wait_for_cdp(chrome_cdp_port)
                download_controller = RemoteDownloadController(chrome_cdp_port)
                download_controller.connect()
                browser_ready_at = time.monotonic()
                browser_monitor = BrowserProcessMonitor(find_browser_pid(USER_DATA_DIR))
                browser_monitor.start()

                # The proxy lives for the container lifetime and opens a fresh upstream
                # connection per client, so it survives browser relaunches.
                if proxy is None:
                    proxy = start_tcp_proxy(cdp_port, chrome_cdp_port)

                print(
                    json.dumps(
                        {
                            "status": "browser-ready",
                            "attempt": attempt,
                            "browser_pid": browser_monitor.pid,
                            "cdp": f"http://{CDP_HOST}:{cdp_port}",
                            "target": f"http://{CHROME_CDP_HOST}:{chrome_cdp_port}",
                        }
                    ),
                    flush=True,
                )

                misses = 0
                last_probe_at = time.monotonic()
                while misses < BROWSER_PROBE_MISSES:
                    time.sleep(DOWNLOAD_BEHAVIOR_REFRESH_S)
                    alive = cdp_alive(chrome_cdp_port)
                    if alive:
                        try:
                            download_controller.apply()
                        except Exception as exc:
                            print(
                                json.dumps({"status": "download-behavior-error", "error": str(exc)[:200]}),
                                flush=True,
                            )
                    if time.monotonic() - last_probe_at < BROWSER_PROBE_INTERVAL_S:
                        continue
                    last_probe_at = time.monotonic()
                    if alive:
                        misses = 0
                    else:
                        misses += 1
                        print(
                            json.dumps({"status": "browser-probe-failed", "misses": misses}),
                            flush=True,
                        )
                browser_uptime_s = time.monotonic() - browser_ready_at
                print(
                    json.dumps(
                        {
                            "status": "browser-lost",
                            "attempt": attempt,
                            "browser_uptime_s": round(browser_uptime_s, 3),
                            **browser_monitor.snapshot(),
                        }
                    ),
                    flush=True,
                )
                consecutive_failures = next_failure_count(consecutive_failures, browser_uptime_s)
            except Exception as exc:
                consecutive_failures += 1
                print(
                    json.dumps(
                        {
                            "status": "browser-error",
                            "attempt": attempt,
                            "browser_uptime_s": round(time.monotonic() - browser_ready_at, 3) if browser_ready_at is not None else None,
                            **browser_monitor.snapshot(),
                            "error": str(exc)[:200],
                        }
                    ),
                    flush=True,
                )
            finally:
                browser_monitor.stop()
                if download_controller is not None:
                    download_controller.close()
                try:
                    if context is not None:
                        context.close()
                except Exception:
                    pass

            if consecutive_failures >= BROWSER_RELAUNCH_LIMIT:
                print(json.dumps({"status": "giving-up", "attempts": consecutive_failures}), flush=True)
                break
            time.sleep(2)

    # Exit non-zero so the container restart policy recreates it with a clean X
    # server, profile lock and CDP proxy.
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
