"""SofaScore-confirmed completion overlay for the event lifecycle.

Additive, fail-safe override consulted by EventPublicationService so any
origin's event (dlhd, streamdc, rblive, cdnlivetv, fixture) can be force-
retired the moment an external verifier confirms the real-world match is
over, without waiting out RIVE_EVENT_DEFAULT_DURATION_MINUTES +
RIVE_EVENT_GRACE_MINUTES (which can run hours long for extra innings, rain
delays, or postponements).

Written by ../sofascore_sync.py (a browser-harness script that checks real
scores on sofascore.com every 15 minutes) via the admin_sofascore router.
Never written to by the resolver itself.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any


class SofaScoreOverlay:
    """JSON-file-backed, TTL'd override store keyed by (origin, event_id)."""

    def __init__(self, path: str | None = None, ttl_seconds: float = 24 * 60 * 60) -> None:
        self._path = Path(path) if path else None
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._ended: dict[tuple[str, str], dict[str, Any]] = {}
        self._load()

    @staticmethod
    def _key(origin: str, event_id: str) -> tuple[str, str]:
        return (str(origin).strip().lower(), str(event_id).strip())

    def _load(self) -> None:
        if not self._path or not self._path.is_file():
            return
        try:
            raw = json.loads(self._path.read_text())
        except Exception:
            return
        now = time.time()
        with self._lock:
            for entry in raw.get("ended", []):
                try:
                    key = self._key(entry["origin"], entry["event_id"])
                    if now - float(entry.get("verified_at", 0)) < self._ttl:
                        self._ended[key] = entry
                except Exception:
                    continue

    def _persist_locked(self) -> None:
        if not self._path:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"ended": list(self._ended.values())}
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, indent=2))
            tmp.replace(self._path)
        except Exception:
            pass

    def mark_ended(
        self, origin: str, event_id: str, *, match_id: str = "", note: str = "",
    ) -> None:
        key = self._key(origin, event_id)
        with self._lock:
            self._ended[key] = {
                "origin": key[0],
                "event_id": key[1],
                "verified_at": time.time(),
                "match_id": str(match_id),
                "note": str(note)[:500],
            }
            self._persist_locked()

    def clear(self, origin: str, event_id: str) -> bool:
        key = self._key(origin, event_id)
        with self._lock:
            existed = self._ended.pop(key, None) is not None
            if existed:
                self._persist_locked()
            return existed

    def is_confirmed_ended(self, origin: str, event_id: str) -> bool:
        key = self._key(origin, event_id)
        with self._lock:
            entry = self._ended.get(key)
            if entry is None:
                return False
            if time.time() - float(entry["verified_at"]) >= self._ttl:
                del self._ended[key]
                self._persist_locked()
                return False
            return True

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._ended.values())


# Single process-wide instance. /data is rive-resolver's existing writable,
# persisted volume (see RIVE_DB_PATH=/data/rive-resolver.db in compose).
overlay = SofaScoreOverlay(path="/data/sofascore_overrides.json")
