"""Admin-only routes for the SofaScore completion sync.

Not part of the public XC/M3U surface. Gated by a shared-secret header
(RIVE_ADMIN_TOKEN) so it is safe to reach from inside the docker network
(`docker exec ... curl http://127.0.0.1:8787/admin/...`) without exposing a
new host port. Read side (`/admin/sofascore/events`) deliberately returns
the internal `origin`/`event_id` identity that the public XC catalog strips
out (see the module docstring in events.py) -- that is fine here because
these two routes are for the maintenance script only, not IPTV clients.
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from app.sofascore_overlay import overlay

router = APIRouter()

_event_publications = None


def set_event_publications(service) -> None:
    global _event_publications
    _event_publications = service


def _check_token(x_admin_token: str | None) -> None:
    expected = os.environ.get("RIVE_ADMIN_TOKEN", "").strip()
    if not expected or not x_admin_token or x_admin_token != expected:
        raise HTTPException(status_code=403, detail="forbidden")


class MarkEndedRequest(BaseModel):
    origin: str
    event_id: str
    match_id: str = ""
    note: str = ""


class ClearRequest(BaseModel):
    origin: str
    event_id: str


@router.get("/admin/sofascore/events")
def list_events(x_admin_token: str | None = Header(default=None)) -> dict:
    _check_token(x_admin_token)
    if _event_publications is None:
        return {"events": []}
    rows = []
    for pub in _event_publications.list_publications(include_hidden=True):
        rows.append({
            "origin": pub.event.origin,
            "event_id": pub.event.event_id,
            "title": pub.event.title,
            "category": pub.event.category,
            "start_at": pub.event.start_at,
            "end_at": pub.event.end_at,
            "status": pub.event.status,
            "state": pub.state.value,
            "stale": pub.stale,
            "stream_id": pub.mapping.stream_id,
            "source_label": pub.source.label,
            "already_overridden": overlay.is_confirmed_ended(
                pub.event.origin, pub.event.event_id,
            ),
        })
    return {"events": rows}


@router.post("/admin/sofascore/mark-ended")
def mark_ended(
    payload: MarkEndedRequest, x_admin_token: str | None = Header(default=None),
) -> dict:
    _check_token(x_admin_token)
    overlay.mark_ended(
        payload.origin, payload.event_id,
        match_id=payload.match_id, note=payload.note,
    )
    return {"ok": True}


@router.post("/admin/sofascore/clear")
def clear_override(
    payload: ClearRequest, x_admin_token: str | None = Header(default=None),
) -> dict:
    _check_token(x_admin_token)
    cleared = overlay.clear(payload.origin, payload.event_id)
    return {"ok": True, "cleared": cleared}


@router.get("/admin/sofascore/overrides")
def list_overrides(x_admin_token: str | None = Header(default=None)) -> dict:
    _check_token(x_admin_token)
    return {"overrides": overlay.snapshot()}
