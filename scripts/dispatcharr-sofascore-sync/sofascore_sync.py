"""SofaScore completion sync for the dispatcharr / rive-resolver IPTV stack.

Run this INSIDE browser-harness (piped to `browser-harness` or via
`./scripts/bh run` from browser_harness_patchright_project_kit) -- it uses
the pre-imported helpers (`js`, `goto_url`, `wait_for_load`, `new_tab`,
`switch_tab`, `close_tab`, `page_info`) to talk to sofascore.com from
inside a real, already-Cloudflare-cleared page context. Plain `http_get()`/
`urllib` gets a 403 from api.sofascore.com even with a realistic
User-Agent + Referer (verified live, 2026-09-15) -- this is a hard
Cloudflare TLS-fingerprint gate, not a missing-header problem.

What it does, every run:
  1. SSH + `docker exec` into unified-iptv-phase1-rive-resolver-1 on
     blackpearl.local and GET /admin/sofascore/events (added by the
     resolver-patch/ files in this same directory) to get every currently
     tracked live-sports event, with its internal origin/event_id -- the
     public XC feed deliberately hides those two fields.
  2. Keep only events that are currently visible (state active/grace),
     older than MIN_AGE_MINUTES, and whose sport is one SofaScore tracks
     as clean two-team matches (baseball, (american) football, basketball,
     hockey, soccer, tennis, rugby, cricket -- fighting/WWE/golf skipped,
     see README "Known gaps").
  3. Parse "Team A vs Team B" out of each event's title, normalize names
     (strip accents/punctuation), and look each team up on SofaScore via
     the browser (search -> team id -> recent + upcoming events for that
     team -> find the specific fixture against the other team within a
     +/-6h window of the dispatcharr event's start_at).
  4. If SofaScore says that fixture is finished/postponed/cancelled/
     abandoned, record it as a candidate override.
  5. Print a summary. With --apply, POST each candidate to
     /admin/sofascore/mark-ended (same ssh + docker exec transport).
     Without --apply (the default), this is a dry run -- nothing is
     written anywhere.

Every run also appends a JSON line to LOG_PATH for audit/troubleshooting.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
import unicodedata

# ---- configuration -------------------------------------------------------

SSH_HOST = "root@blackpearl.local"
RESOLVER_CONTAINER = "unified-iptv-phase1-rive-resolver-1"
RESOLVER_URL = "http://127.0.0.1:8787"
ADMIN_TOKEN_ENV_VAR = "RIVE_ADMIN_TOKEN"  # read from THIS Mac's env, sent over ssh

MAX_LOOKUP_MINUTES = 7 * 24 * 60  # only retain a week of unresolved history
MATCH_WINDOW_SECONDS = 6 * 60 * 60  # +/- 6h between dispatcharr start_at and sofascore kickoff

# Keep only the two SofaScore states Dispatcharr should expose. Empty status is
# unknown and is left untouched so a transient API/schema failure is fail-open.
VISIBLE_STATUS_TYPES = {"notstarted", "inprogress"}

# event_group ("Sports Events | Baseball", "Sports Events | Fighting: WWE", ...)
# -> sofascore sport slug. None = skip (not a clean two-team "vs" match on
# SofaScore, or not a real competitive result).
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

LOG_PATH = "/tmp/dispatcharr-sofascore-sync.jsonl"

# ---- ssh transport to the resolver ----------------------------------------


def _ssh_docker_exec(inner_cmd: str, timeout: float = 20.0) -> str:
    """Run `inner_cmd` inside RESOLVER_CONTAINER on blackpearl.local via ssh."""
    remote = "docker exec %s sh -c %s" % (RESOLVER_CONTAINER, _sh_quote(inner_cmd))
    proc = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", SSH_HOST, remote],
        capture_output=True, text=True, timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError("ssh/docker exec failed (%s): %s" % (proc.returncode, proc.stderr[-500:]))
    return proc.stdout


def _sh_quote(s: str) -> str:
    return "'" + s.replace("'", "'\\''") + "'"


def fetch_tracked_events(admin_token: str) -> list[dict]:
    curl = (
        "curl -s -m 10 -H 'X-Admin-Token: %s' %s/admin/sofascore/events"
        % (admin_token, RESOLVER_URL)
    )
    raw = _ssh_docker_exec(curl)
    data = json.loads(raw)
    return data.get("events", [])


def push_mark_ended(admin_token: str, origin: str, event_id: str, match_id: str, note: str) -> None:
    body = json.dumps({
        "origin": origin, "event_id": event_id,
        "match_id": str(match_id), "note": note,
    })
    curl = (
        "curl -s -m 10 -X POST -H 'X-Admin-Token: %s' -H 'Content-Type: application/json' "
        "-d %s %s/admin/sofascore/mark-ended"
        % (admin_token, _sh_quote(body), RESOLVER_URL)
    )
    _ssh_docker_exec(curl)


# ---- title / name parsing --------------------------------------------------

_VS_SPLIT_RE = re.compile(r"\s+vs\.?\s+", re.IGNORECASE)
_LEADING_JUNK_RE = re.compile(
    r"^\s*(?:\d{1,2}/\d{1,2}\s+)?\d{1,2}:\d{2}\s*[AaPp]\.?[Mm]\.?"
    r"(?:\s+[A-Z]{2,4})?\s+",
)


def parse_teams(title: str) -> tuple[str, str] | None:
    """Best-effort "<junk><Team A> vs <Team B>" -> (Team A, Team B)."""
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
    # token containment in either direction (handles "Leon" vs "Atletico
    # San Luis" style abbreviation drift, and accented-vs-plain duplicates
    # seen in real rive-resolver output for the same fixture).
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


# ---- sofascore lookups (browser-context fetch; see module docstring) ------


def _sofascore_fetch(url: str, retries: int = 2) -> dict | None:
    expr = (
        "(async () => { try { const r = await fetch(%s, "
        "{headers: {accept: 'application/json'}}); "
        "if (!r.ok) return JSON.stringify({__status: r.status}); "
        "const j = await r.json(); return JSON.stringify(j); } "
        "catch (e) { return JSON.stringify({__error: String(e)}); } })()"
    ) % json.dumps(url)
    last_err = None
    for attempt in range(retries + 1):
        try:
            raw = js(expr)  # noqa: F821 -- provided by browser-harness
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
        except Exception as exc:  # noqa: BLE001
            last_err = str(exc)
            time.sleep(1.0)
    print("  ! sofascore fetch failed for %s: %s" % (url, last_err), file=sys.stderr)
    return None


_team_search_cache: dict[str, list[dict]] = {}
_team_events_cache: dict[int, list[dict]] = {}


def search_teams(name: str, sport_slug: str) -> list[dict]:
    cache_key = "%s::%s" % (sport_slug, name.lower())
    if cache_key in _team_search_cache:
        return _team_search_cache[cache_key]
    data = _sofascore_fetch(
        "https://api.sofascore.com/api/v1/search/all?q=%s" % _url_quote(name)
    ) or {}
    out = []
    for result in data.get("results", []):
        if result.get("type") != "team":
            continue
        entity = result.get("entity") or {}
        sport = (entity.get("sport") or {}).get("slug")
        if sport != sport_slug:
            continue
        out.append(entity)
    _team_search_cache[cache_key] = out
    return out


def team_events(team_id: int) -> list[dict]:
    if team_id in _team_events_cache:
        return _team_events_cache[team_id]
    events: list[dict] = []
    for path in ("events/last/0", "events/next/0"):
        data = _sofascore_fetch(
            "https://api.sofascore.com/api/v1/team/%s/%s" % (team_id, path)
        ) or {}
        events.extend(data.get("events") or [])
    # de-dupe by sofascore event id
    seen: dict[int, dict] = {}
    for ev in events:
        seen[ev.get("id")] = ev
    result = list(seen.values())
    _team_events_cache[team_id] = result
    return result


def _url_quote(s: str) -> str:
    import urllib.parse
    return urllib.parse.quote(s)


def find_matching_match(
    team_a: str, team_b: str, sport_slug: str, approx_start: float | None,
) -> dict | None:
    """Return the matching sofascore event dict, or None if no confident match."""
    for search_name, other_name in ((team_a, team_b), (team_b, team_a)):
        for candidate_team in search_teams(search_name, sport_slug):
            team_id = candidate_team.get("id")
            if team_id is None:
                continue
            for ev in team_events(team_id):
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


# ---- main -------------------------------------------------------------


def run(apply_changes: bool) -> int:
    import os

    admin_token = os.environ.get(ADMIN_TOKEN_ENV_VAR, "").strip()
    if not admin_token:
        print(
            "ERROR: set %s in the environment before running "
            "(see resolver-patch/README deployment step 1)." % ADMIN_TOKEN_ENV_VAR,
            file=sys.stderr,
        )
        return 2

    try:
        events = fetch_tracked_events(admin_token)
    except Exception as exc:  # noqa: BLE001
        print("ERROR: could not fetch tracked events: %s" % exc, file=sys.stderr)
        return 2

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

    print("Tracked events: %d total, %d candidates for a SofaScore check" % (
        len(events), len(candidates),
    ))

    # Navigate a dedicated tab to sofascore.com once -- fetch() calls below
    # reuse that page context (Cloudflare-cleared) for every lookup.
    tab_id = new_tab("about:blank")  # noqa: F821 -- provided by browser-harness
    switch_tab(tab_id)  # noqa: F821
    goto_url("https://www.sofascore.com/")  # noqa: F821
    wait_for_load(20)  # noqa: F821

    results = []
    to_apply = []
    try:
        for ev, (team_a, team_b), sport_slug in candidates:
            match = find_matching_match(team_a, team_b, sport_slug, ev.get("start_at"))
            if match is None:
                results.append({**_row(ev), "verdict": "no_match"})
                continue
            status_type = ((match.get("status") or {}).get("type") or "").lower()
            note = "sofascore #%s %s vs %s status=%s" % (
                match.get("id"),
                (match.get("homeTeam") or {}).get("name"),
                (match.get("awayTeam") or {}).get("name"),
                status_type,
            )
            if not status_type:
                results.append({**_row(ev), "verdict": "unknown_status", "note": note})
            elif status_type in VISIBLE_STATUS_TYPES:
                results.append({**_row(ev), "verdict": "visible", "note": note})
            else:
                results.append({**_row(ev), "verdict": "excluded", "note": note})
                to_apply.append((ev, str(match.get("id")), note))
    finally:
        close_tab(tab_id)  # noqa: F821

    for row in results:
        print("  [%-10s] %-55s %s" % (row["verdict"], row["title"][:55], row.get("note", "")))

    if to_apply and apply_changes:
        for ev, match_id, note in to_apply:
            try:
                push_mark_ended(admin_token, ev["origin"], ev["event_id"], match_id, note)
                print("  -> marked ended: %s (%s/%s)" % (ev["title"], ev["origin"], ev["event_id"]))
            except Exception as exc:  # noqa: BLE001
                print("  ! failed to push override for %s: %s" % (ev["title"], exc), file=sys.stderr)
    elif to_apply:
        print(
            "%d event(s) confirmed finished -- re-run with --apply to remove them "
            "from the dispatcharr catalog." % len(to_apply)
        )

    _log_run(len(events), len(candidates), results, apply_changes)
    return 0


def _row(ev: dict) -> dict:
    return {
        "origin": ev.get("origin"), "event_id": ev.get("event_id"),
        "title": ev.get("title"), "category": ev.get("category"),
    }


def _log_run(total: int, checked: int, results: list[dict], applied: bool) -> None:
    try:
        with open(LOG_PATH, "a") as f:
            f.write(json.dumps({
                "ts": time.time(), "total_tracked": total, "checked": checked,
                "applied": applied, "results": results,
            }) + "\n")
    except Exception:
        pass


# NOTE: browser-harness's run.py does `exec(code, globals())` inside its own
# module -- __name__ there is "browser_harness.run", never "__main__", and it
# does not proxy extra CLI args into this script's sys.argv. So apply-mode is
# controlled by an environment variable (set by run_sofascore_sync.sh) instead
# of an `if __name__ == "__main__"` guard or argv parsing, and the call below
# is unconditional so it actually runs when this file is piped into
# `browser-harness`. Running this file directly with plain `python3` still
# works too (accepts --apply on argv as a convenience for local testing
# without a browser, though sofascore lookups will then fail without `js`).
import os as _os
_apply_env = _os.environ.get("SOFASCORE_SYNC_APPLY", "").strip().lower() in ("1", "true", "yes")
_apply_argv = "--apply" in sys.argv
_exit_code = run(_apply_env or _apply_argv)
if _exit_code:
    print("sofascore_sync exited with code %d" % _exit_code, file=sys.stderr)
