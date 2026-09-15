"""Minimal CDP client -- no playwright/patchright import in this process.

This process is a pure CDP *consumer*. The browser itself (Chromium, driven
by Patchright at container-boot time only, see ../browser/) exposes the
Chrome DevTools Protocol on the docker network; everything this module does
from here on is plain JSON-RPC over one WebSocket connection, the same
protocol browser-harness's own helpers.py speaks. Only dependency beyond the
stdlib is `websocket-client` (small, pure-Python, no C extension).
"""
from __future__ import annotations

import itertools
import json
import logging
import threading
import time
import urllib.request

import websocket  # pip: websocket-client

logger = logging.getLogger("cdp")


class CDPError(RuntimeError):
    pass


class CDPClient:
    """One browser-level WebSocket connection, flattened sessions per target.

    Mirrors the shape browser-harness's helpers.py uses (Target.attachToTarget
    with flatten=True, then every subsequent command carries `sessionId`) --
    proven against real CDP traffic in this project already.
    """

    def __init__(self, cdp_http_base: str, connect_timeout: float = 20.0) -> None:
        self._http_base = cdp_http_base.rstrip("/")
        self._ws: websocket.WebSocket | None = None
        self._id_counter = itertools.count(1)
        self._lock = threading.Lock()
        self._pending: dict[int, dict] = {}
        self._events: list[dict] = []
        self._recv_thread: threading.Thread | None = None
        self._stop = False
        self._connect(connect_timeout)

    def _discover_ws_url(self, timeout: float) -> str:
        deadline = time.time() + timeout
        last_err: Exception | None = None
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(
                    self._http_base + "/json/version", timeout=3,
                ) as resp:
                    data = json.loads(resp.read().decode())
                url = data.get("webSocketDebuggerUrl")
                if url:
                    return url
            except Exception as exc:  # noqa: BLE001
                last_err = exc
            time.sleep(1.0)
        raise CDPError("CDP endpoint never became reachable at %s: %s" % (self._http_base, last_err))

    def _connect(self, timeout: float) -> None:
        ws_url = self._discover_ws_url(timeout)
        # Chrome's CDP WebSocket handshake rejects connections carrying an
        # Origin header it doesn't recognize (DNS-rebinding protection --
        # confirmed live: default websocket-client behavior gets a 403
        # "Rejected an incoming WebSocket connection from the http://...
        # origin" here). suppress_origin=True omits the header entirely,
        # which Chrome accepts, matching how legitimate CDP clients connect.
        self._ws = websocket.create_connection(
            ws_url, timeout=timeout, suppress_origin=True,
        )
        self._recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._recv_thread.start()

    def _recv_loop(self) -> None:
        while not self._stop:
            try:
                raw = self._ws.recv()
            except Exception:  # noqa: BLE001
                break
            if not raw:
                continue
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            with self._lock:
                if "id" in msg:
                    self._pending[msg["id"]] = msg
                else:
                    self._events.append(msg)

    def send(self, method: str, params: dict | None = None, session_id: str | None = None,
              timeout: float = 30.0) -> dict:
        req_id = next(self._id_counter)
        payload: dict = {"id": req_id, "method": method, "params": params or {}}
        if session_id:
            payload["sessionId"] = session_id
        self._ws.send(json.dumps(payload))

        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                msg = self._pending.pop(req_id, None)
            if msg is not None:
                if "error" in msg:
                    raise CDPError("%s failed: %s" % (method, msg["error"]))
                return msg.get("result", {})
            time.sleep(0.02)
        raise CDPError("%s timed out after %.0fs" % (method, timeout))

    def close(self) -> None:
        self._stop = True
        try:
            if self._ws is not None:
                self._ws.close()
        except Exception:  # noqa: BLE001
            pass


class CDPPage:
    """One target (tab), attached in flatten mode -- create, use, close."""

    def __init__(self, client: CDPClient, target_id: str, session_id: str) -> None:
        self._client = client
        self.target_id = target_id
        self.session_id = session_id

    @classmethod
    def open(cls, client: CDPClient, url: str = "about:blank") -> "CDPPage":
        target = client.send("Target.createTarget", {"url": url})
        target_id = target["targetId"]
        attach = client.send(
            "Target.attachToTarget", {"targetId": target_id, "flatten": True},
        )
        return cls(client, target_id, attach["sessionId"])

    def navigate(self, url: str, timeout: float = 30.0) -> None:
        self._client.send("Page.enable", session_id=self.session_id)
        self._client.send("Page.navigate", {"url": url}, session_id=self.session_id)
        deadline = time.time() + timeout
        while time.time() < deadline:
            state = self.evaluate("document.readyState")
            if state == "complete":
                return
            time.sleep(0.25)
        raise CDPError("navigation to %s did not reach readyState=complete in %.0fs" % (url, timeout))

    def evaluate(self, expression: str, timeout: float = 30.0, await_promise: bool = False):
        result = self._client.send(
            "Runtime.evaluate",
            {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": await_promise,
            },
            session_id=self.session_id,
            timeout=timeout,
        )
        exc_details = result.get("exceptionDetails")
        if exc_details:
            raise CDPError("Runtime.evaluate threw: %s" % exc_details)
        return result.get("result", {}).get("value")

    def close(self) -> None:
        try:
            self._client.send("Target.closeTarget", {"targetId": self.target_id})
        except Exception:  # noqa: BLE001
            pass
