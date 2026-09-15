"""Native, always-on SofaScore completion sync for the unified-iptv stack.

Runs as its OWN small container on blackpearl.local, on the same Docker
network as rive-resolver -- no Mac, no browser-harness, no launchd, no SSH
transport. This replaces the Mac-based
scripts/dispatcharr-sofascore-sync/sofascore_sync.py + run_sofascore_sync.sh
+ launchd job for production use; that Mac-based path stays useful for
interactive dry-run debugging, but the thing that actually has to run every
15 minutes, unattended, forever, should live where the rest of the stack
lives.

Deliberately does NOT import playwright/patchright in this process. The
actual browser lives in a separate sidecar container (../browser/, the
same Dockerfile + launch_patchright_cdp.py this project already uses for
interactive browser-harness work), which uses Patchright internally only
to launch Chromium and expose a Chrome DevTools Protocol endpoint. This
process is a pure CDP client (cdp_client.py, stdlib + the small
websocket-client package) -- no browser binaries, no heavy image, and no
"does this base image actually ship the playwright pip package" surprises.

Why a real browser is needed at all: api.sofascore.com 403s a raw Python
HTTP client (urllib) even with a realistic User-Agent/Referer -- a
Cloudflare TLS-fingerprint gate on that API host, not a headless-detection
gate on the page itself. A real browser's own network stack (fetch()
called from a loaded page, via Runtime.evaluate) presents a legitimate
browser TLS fingerprint and clears it -- verified live against production
sofascore.com data, both via Patchright (original Mac-based prototype) and
plain Playwright (local smoke test before this CDP rewrite).
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request

from cdp_client import CDPClient, CDPPage, CDPError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("sofascore-sync")

# ---- configuration ---------------------------------------------------

RESOLVER_BASE_URL = os.environ.get("RIVE_RESOLVER_BASE_URL", "http://rive-resolver:8787")
ADMIN_TOKEN = os.environ.get("RIVE_ADMIN_TOKEN", "").strip()
RUN_INTERVAL_SECONDS = int(os.environ.get("SYNC_INTERVAL_SECONDS", "900"))
APPLY = os.environ.get("SOFASCORE_SYNC_APPLY", "0").strip().lower() in ("1", "true", "yes")
BROWSER_CDP_URL = os.environ.get("BROWSER_CDP_URL", "http://sofascore-browser:9222")
HEARTBEAT_PATH = os.environ.get("HEARTBEAT_PATH", "/tmp/sofascore-sync.heartbeat")

MAX_LOOKUP_MINUTES = 7 * 24 * 60  # only retain a week of unresolved history
MATCH_WINDOW_SECONDS = 6 * 60 * 60

# Dispatcharr should expose only events SofaScore says are upcoming or live.
# Any other explicit status (finished, cancelled, postponed, suspended, etc.)
# is removed through the resolver overlay. Empty status is treated as unknown
# and is left untouched so a transient API/schema failure cannot hide events.
VISIBLE_STATUS_TYPES = {"notstarted", "inprogress"}

SPORT_SLUG_BY_LABEL = {
    "baseball": "baseball",
    "american football": "american-football",
    "american-football": "american-football",
    "basketball": "basketball",
    "hockey": "ice-hockey",
    "ice hockey": "ice-hockey",
    "soccer": "football",
    "tennis": "tennis",
    "rugby": "rugby",
    "cricket": "cricket",
    "fighting": None,
    "golf": None,
    "racing": None,
    "volleyball": "volleyball",
    "handball": "handball",
    "sports": None,
}

# ---- resolver admin API (same docker network -- plain urllib is fine;
# this is our own internal service, not Cloudflare-gated like sofascore) --


def _resolver_request(method: str, path: str, body: dict | None = None) -> dict:
    url = RESOLVER_BASE_URL.rstrip("/") + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"X-Admin-Token": ADMIN_TOKEN, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def fetch_tracked_events() -> list[dict]:
    return _resolver_request("GET", "/admin/sofascore/events").get("events", [])


def push_mark_ended(origin: str, event_id: str, match_id: str, note: str) -> None:
    _resolver_request("POST", "/admin/sofascore/mark-ended", {
        "origin": origin, "event_id": event_id,
        "match_id": str(match_id), "note": note,
    })


# ---- title / name parsing (identical to the Mac-based prototype) ------

_VS_SPLIT_RE = re.compile(r"\s+vs\.?\s+", re.IGNORECASE)
_LEADING_JUNK_RE = re.compile(
    r"^\s*(?:\d{1,2}/\d{1,2}\s+)?\d{1,2}:\d{2}\s*[AaPp]\.?[Mm]\.?"
    r"(?:\s+[A-Z]{2,4})?\s+",
)


def parse_teams(title: str) -> tuple[str, str] | None:
    parts = _VS_SPLIT_RE.split(title, maxsplit=1)
    if len(parts) != 2:
        return None
    team_a = _LEADING_JUNK_RE.sub("", parts[0]).strip(" -\u2014")
    team_b = parts[1].strip(" -\u2014")
    if not team_a or not team_b:
        return None
    return team_a, team_b


def normalize_name(name: str) -> str:
    decomposed = unicodedata.normalize("NFKD", name)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    stripped = stripped.lower()
    stripped = re.sub(r"[^a-z0-9 ]+", " ", stripped)
    return re.sub(r"\s+", " ", stripped).strip()


def names_match(a: str, b: str) -> bool:
    na, nb = normalize_name(a), normalize_name(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    ta, tb = set(na.split()), set(nb.split())
    if not ta or not tb:
        return False
    overlap = ta & tb
    return len(overlap) >= max(1, min(len(ta), len(tb)) - 1) and (
        na in nb or nb in na or len(overlap) / max(len(ta), len(tb)) >= 0.6
    )


def sport_slug_for_category(category: str) -> str | None:
    label = category or ""
    label = re.sub(r"^Sports Events\s*\|\s*", "", label, flags=re.IGNORECASE)
    label = label.split(":", 1)[0].strip().lower()
    return SPORT_SLUG_BY_LABEL.get(label)


# ---- sofascore lookups, via CDP Runtime.evaluate (see module docstring) --


def _sofascore_fetch(page: CDPPage, url: str, retries: int = 2) -> dict | None:
    expr = (
        "(async () => { try { const r = await fetch(%s, "
        "{headers: {accept: 'application/json'}}); "
        "if (!r.ok) return JSON.stringify({__status: r.status}); "
        "const j = await r.json(); return JSON.stringify(j); } "
        "catch (e) { return JSON.stringify({__error: String(e)}); } })()"
    ) % json.dumps(url)
    last_err = None
    for _ in range(retries + 1):
        try:
            raw = page.evaluate(expr, await_promise=True)
            if raw is None:
                last_err = "null result"
                time.sleep(1.0)
                continue
            parsed = json.loads(raw)
            if isinstance(parsed, dict) and "__error" in parsed:
                last_err = parsed["__error"]
                time.sleep(1.0)
                continue
            if isinstance(parsed, dict) and parsed.get("__status") == 404:
                return None
            return parsed
        except (CDPError, Exception) as exc:  # noqa: BLE001
            last_err = str(exc)
            time.sleep(1.0)
    logger.warning("sofascore fetch failed for %s: %s", url, last_err)
    return None


def search_teams(page: CDPPage, cache: dict, name: str, sport_slug: str) -> list[dict]:
    cache_key = "%s::%s" % (sport_slug, name.lower())
    if cache_key in cache:
        return cache[cache_key]
    import urllib.parse
    data = _sofascore_fetch(
        page, "https://api.sofascore.com/api/v1/search/all?q=%s" % urllib.parse.quote(name),
    ) or {}
    out = []
    for result in data.get("results", []):
        if result.get("type") != "team":
            continue
        entity = result.get("entity") or {}
        if (entity.get("sport") or {}).get("slug") != sport_slug:
            continue
        out.append(entity)
    cache[cache_key] = out
    return out


def team_events(page: CDPPage, cache: dict, team_id: int) -> list[dict]:
    if team_id in cache:
        return cache[team_id]
    events: list[dict] = []
    for path in ("events/last/0", "events/next/0"):
        data = _sofascore_fetch(
            page, "https://api.sofascore.com/api/v1/team/%s/%s" % (team_id, path),
        ) or {}
        events.extend(data.get("events") or [])
    seen: dict[int, dict] = {}
    for ev in events:
        seen[ev.get("id")] = ev
    cache[team_id] = list(seen.values())
    return cache[team_id]


def find_matching_match(
    page: CDPPage, search_cache: dict, events_cache: dict,
    team_a: str, team_b: str, sport_slug: str, approx_start: float | None,
) -> dict | None:
    for search_name, other_name in ((team_a, team_b), (team_b, team_a)):
        for candidate_team in search_teams(page, search_cache, search_name, sport_slug):
            team_id = candidate_team.get("id")
            if team_id is None:
                continue
            for ev in team_events(page, events_cache, team_id):
                home = (ev.get("homeTeam") or {}).get("name", "")
                away = (ev.get("awayTeam") or {}).get("name", "")
                other_side = away if names_match(home, search_name) else home
                if not names_match(other_side, other_name):
                    continue
                start_ts = ev.get("startTimestamp")
                if approx_start is not None and start_ts is not None:
                    if abs(start_ts - approx_start) > MATCH_WINDOW_SECONDS:
                        continue
                return ev
    return None


# ---- one sync cycle -----------------------------------------------------


def run_once(page: CDPPage) -> None:
    try:
        events = fetch_tracked_events()
    except Exception as exc:  # noqa: BLE001
        logger.error("could not fetch tracked events from resolver: %s", exc)
        return

    now = time.time()
    candidates = []
    for ev in events:
        if ev.get("state") not in ("active", "grace"):
            continue
        if ev.get("already_overridden"):
            continue
        start_at = ev.get("start_at")
        if start_at is None:
            continue
        age_minutes = (now - float(start_at)) / 60.0
        if age_minutes > MAX_LOOKUP_MINUTES:
            continue
        sport_slug = sport_slug_for_category(ev.get("category") or "")
        if sport_slug is None:
            continue
        teams = parse_teams(ev.get("title") or "")
        if teams is None:
            continue
        candidates.append((ev, teams, sport_slug))

    logger.info("tracked=%d candidates=%d", len(events), len(candidates))

    search_cache: dict = {}
    events_cache: dict = {}
    ended = 0
    for ev, (team_a, team_b), sport_slug in candidates:
        match = find_matching_match(
            page, search_cache, events_cache, team_a, team_b, sport_slug, ev.get("start_at"),
        )
        if match is None:
            continue
        status_type = ((match.get("status") or {}).get("type") or "").lower()
        if not status_type or status_type in VISIBLE_STATUS_TYPES:
            continue
        note = "sofascore #%s %s vs %s status=%s" % (
            match.get("id"),
            (match.get("homeTeam") or {}).get("name"),
            (match.get("awayTeam") or {}).get("name"),
            status_type,
        )
        logger.info("excluded by SofaScore status: %s | %s", ev.get("title"), note)
        if APPLY:
            try:
                push_mark_ended(ev["origin"], ev["event_id"], str(match.get("id")), note)
                ended += 1
            except Exception as exc:  # noqa: BLE001
                logger.error("failed to push override for %s: %s", ev.get("title"), exc)
        else:
            logger.info("dry-run (SOFASCORE_SYNC_APPLY=0) -- not writing override")

    logger.info(
        "cycle complete: tracked=%d candidates=%d marked_ended=%d",
        len(events), len(candidates), ended,
    )


def _touch_heartbeat() -> None:
    try:
        with open(HEARTBEAT_PATH, "w") as f:
            f.write(str(time.time()))
    except Exception:  # noqa: BLE001
        pass


def main() -> int:
    if not ADMIN_TOKEN:
        logger.error("RIVE_ADMIN_TOKEN is not set -- exiting")
        return 2

    logger.info(
        "starting: resolver=%s browser_cdp=%s interval=%ds apply=%s",
        RESOLVER_BASE_URL, BROWSER_CDP_URL, RUN_INTERVAL_SECONDS, APPLY,
    )
    _touch_heartbeat()

    while True:
        cycle_start = time.time()
        client = None
        page = None
        try:
            client = CDPClient(BROWSER_CDP_URL)
            page = CDPPage.open(client, "about:blank")
            page.navigate("https://www.sofascore.com/", timeout=30.0)
            run_once(page)
        except Exception:  # noqa: BLE001
            logger.exception("sync cycle failed -- will retry next interval")
        finally:
            if page is not None:
                page.close()
            if client is not None:
                client.close()
            _touch_heartbeat()

        elapsed = time.time() - cycle_start
        sleep_for = max(5.0, RUN_INTERVAL_SECONDS - elapsed)
        logger.info("sleeping %.0fs until next cycle", sleep_for)
        time.sleep(sleep_for)


if __name__ == "__main__":
    sys.exit(main())
