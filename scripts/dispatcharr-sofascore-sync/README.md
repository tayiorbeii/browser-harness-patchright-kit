# Dispatcharr / rive-resolver SofaScore completion sync

## Where things live

- `blackpearl.local` (Unraid, root SSH): runs the actual IPTV stack --
  `unified-iptv-phase1-dispatcharr-1` (Dispatcharr, the app that groups
  streaming sources into channel lists) and
  `unified-iptv-phase1-rive-resolver-1` (`rive-resolver`, a custom
  Dispatcharr-compatible XC/M3U resolver that discovers live sports events
  from five origins -- `dlhd`, `streamdc`, `rblive`, `cdnlivetv`, `fixture`
  -- and feeds Dispatcharr its catalog).
- This Mac (`browser_harness_patchright_project_kit`): where the SofaScore
  browser automation actually runs, on a schedule, via the project's
  isolated Patchright/VNC Chrome container.

## The problem

Dispatcharr trusts whatever rive-resolver's XC feed says. rive-resolver's
`EventLifecyclePolicy` (`app/events.py`) decides an event is over purely
from **scheduled** timing:

```
RIVE_EVENT_DEFAULT_DURATION_MINUTES=240   # 4h assumed length when no real end time
RIVE_EVENT_GRACE_MINUTES=120              # +2h "grace" after that
```
(both confirmed set in `.env.unified` on blackpearl.local, 2026-09-15)

A 3-hour baseball game that goes to extra innings, or gets rained out, can
stay listed for **up to 6 hours** after it's actually over. Dispatcharr
itself re-pulls the resolver's catalog every 90 seconds
(`DISPATCHARR_PLAYLIST_REFRESH_INTERVAL_SECONDS=90`) with zero stale-day
retention (`DISPATCHARR_LIVE_STALE_STREAM_DAYS=0`) -- so **whatever the
resolver stops publishing disappears from Dispatcharr within ~90 seconds.**
The only missing piece is something telling the resolver a game is
*actually* over, in real time, using a real source of truth.

## The fix

1. `sofascore_sync.py` -- a browser-harness script, run every 15 minutes --
   pulls every currently-tracked event from the resolver, checks real
   scores on sofascore.com, and for any event SofaScore confirms is
   finished/postponed/cancelled/abandoned, tells the resolver so.
2. `resolver-patch/` -- one small, additive, fail-safe patch to
   rive-resolver: a JSON-file overlay + two admin-only HTTP routes + a
   4-line hook in the one function (`EventPublicationService.
   list_publications`) that every origin's visibility already flows
   through. Nothing about the existing scrapers, DB schema, or lifecycle
   math changes; the hook is wrapped in `try/except` so a bug in the new
   code can never break normal catalog output.

```
sofascore.com (real scores)
        |  every 15 min, via browser-harness (Cloudflare-cleared page context)
        v
sofascore_sync.py  --reads-->  GET /admin/sofascore/events        (new, token-gated)
                   --writes--> POST /admin/sofascore/mark-ended
        v
rive-resolver: EventPublicationService.list_publications() now returns
ENDED for that (origin, event_id) instead of waiting out 4h+2h
        v
Dispatcharr's next <=90s refresh: stream/channel is gone (stale_stream_days=0)
        v
Finished events no longer show up in Dispatcharr's channel lists
```

## Verified live, 2026-09-15

- **Cloudflare gate is real and TLS-fingerprint-based**, not header-based:
  `http_get()` (plain `urllib`) against `api.sofascore.com` returns 403
  even with a realistic `User-Agent`/`Referer`/`Origin`. The identical
  request via `fetch()` from inside a loaded `https://www.sofascore.com/`
  tab (browser-harness `js(...)`) returns 200. `sofascore_sync.py` always
  does its lookups the second way.
- **Confirmed working, unauthenticated SofaScore endpoints:**
  - `GET /api/v1/search/all?q={name}` -> `results[].entity.{id,name,slug,
    sport.slug}` (`type == "team"` filters to teams)
  - `GET /api/v1/team/{id}/events/last/0` -> recent/finished matches
  - `GET /api/v1/team/{id}/events/next/0` -> upcoming/live matches
  - Each event: `homeTeam.name`, `awayTeam.name`, `startTimestamp` (unix
    seconds), `status.type` in `notstarted|inprogress|finished` (also saw
    `postponed`/`cancelled`/`abandoned`/`interrupted` in the wild --
    `interrupted` = temporarily paused, deliberately NOT treated as ended).
- **Confirmed real production data shape** (245 XC stream rows / 196
  distinct events pulled from rive-resolver, 2026-09-15): titles look like
  `"9/14 7:40 PM Chicago Cubs vs Atlanta Braves"`; the "-- ADMIN/GOLF/
  DELTA/ECHO" suffix seen on the public XC feed is a per-source display
  suffix added later and is NOT part of the durable `Event.title` the new
  admin endpoint returns -- `sofascore_sync.py`'s title parsing is written
  and unit-checked against this exact real shape (see "Local checks" below).
- **`app/events.py`'s central registry is `EventPublicationService`**
  (`list_publications()` / `apply_snapshot()`), already used uniformly by
  all five origins via the shared `_event_publications` singleton wired in
  `main.py`. This is the one safe place to hook a cross-origin override --
  confirmed by reading the full class, not guessed.
- **rive-resolver's `app/` source is baked into its Docker image at build
  time** (`build: context: ./rive-resolver`, immutable
  `RIVE_RESOLVER_SOURCE_SHA` build arg from `scripts/
  resolver_source_sha.py`), not bind-mounted -- confirmed from the compose
  file. So this patch needs an explicit rebuild to take effect; it is
  **not applied to blackpearl.local automatically by this session**. See
  "Deploying" below.
- The project's browser container (`bh-browser_harness_patchright_project_kit`)
  went briefly unresponsive mid-session (Runtime.evaluate timeouts on every
  tab, `Browser.getVersion` still instant -- a hung renderer, not a hung
  daemon) and came back after a restart. `run_sofascore_sync.sh` checks CDP
  reachability and restarts the container if needed before each run; a
  stuck run should just be skipped and retried at the next 15-minute tick.

## Local checks already run (no live systems touched)

```
python3 -m py_compile sofascore_sync.py                      # OK
python3 -m py_compile resolver-patch/sofascore_overlay.py    # OK
python3 -m py_compile resolver-patch/admin_sofascore.py      # OK
bash -n run_sofascore_sync.sh                                 # OK
```
Plus an interactive smoke test of `parse_teams` / `names_match` /
`sport_slug_for_category` against real title strings pulled from
production (see git history of this session for the exact test), e.g.:

```
'9/14 7:40 PM Chicago Cubs vs Atlanta Braves' -> ('Chicago Cubs', 'Atlanta Braves')
'5:40 PM MT Chicago Cubs vs Atlanta Braves'   -> ('Chicago Cubs', 'Atlanta Braves')
names_match('León', 'Leon') -> True
names_match('Atlético de San Luis', 'Atletico San Luis') -> True
sport_slug_for_category('Sports Events | Baseball') -> 'baseball'
sport_slug_for_category('Sports Events | Fighting: WWE') -> None  (skipped)
```

What is **not** yet verified end-to-end: an actual finished game being
removed from Dispatcharr, because that requires the resolver-side patch to
be built and deployed first (see below), which this session deliberately
did not do unattended.

## Deploying the resolver patch (deliberate, not automatic)

I have root SSH to blackpearl.local and could do this myself, but a source
change to a production media backend -- one that requires an explicit
image rebuild -- should be reviewed before it ships. When you're ready:

```bash
# 1. Generate a token (or reuse the one already generated this session:
#    ask me, I did not print it in any file) and add it in TWO places:
ssh root@blackpearl.local 'openssl rand -hex 24'

# a) /mnt/user/appdata/unified-iptv/stack/.env.unified -- add a line:
#    RIVE_ADMIN_TOKEN=<generated>

# b) docker-compose.unified.phase1.candidate.yml, in the rive-resolver
#    service's `environment:` block, add:
#    RIVE_ADMIN_TOKEN: ${RIVE_ADMIN_TOKEN:?set RIVE_ADMIN_TOKEN}

# 2. Copy the two new files into the resolver's build context
scp resolver-patch/sofascore_overlay.py resolver-patch/admin_sofascore.py \
    root@blackpearl.local:/mnt/user/appdata/unified-iptv/stack/rive-resolver/app/

# 3. Apply the two diffs by hand (small, 2 hunks each -- this is a heavily
#    hand-patched fork, `patch -p1` is riskier than just editing the two
#    call sites directly; see resolver-patch/events.py.diff and
#    resolver-patch/main.py.diff for the exact 3 insertion points)

# 4. Recompute the reviewed source digest and rebuild (this repo already
#    has exactly this workflow built in -- see scripts/resolver_source_sha.py)
ssh root@blackpearl.local
cd /mnt/user/appdata/unified-iptv/stack
python3 scripts/resolver_source_sha.py   # -> new RIVE_RESOLVER_SOURCE_SHA
# put that value in .env.unified, then:
docker compose -f docker-compose.unified.phase1.candidate.yml \
  -f docker-compose.unified.operator-access.yml build rive-resolver
docker compose -f docker-compose.unified.phase1.candidate.yml \
  -f docker-compose.unified.operator-access.yml up -d rive-resolver

# 5. Verify
docker exec unified-iptv-phase1-rive-resolver-1 sh -c \
  'curl -s -H "X-Admin-Token: $RIVE_ADMIN_TOKEN" http://127.0.0.1:8787/admin/sofascore/events' \
  | python3 -m json.tool
```

Put the same token on this Mac in `~/.config/dispatcharr-sofascore-sync/env`
(chmod 600):

```
RIVE_ADMIN_TOKEN=<the same generated token>
```

## Scheduling on this Mac (every 15 minutes)

```bash
mkdir -p ~/Library/LaunchAgents
cp com.taylor.dispatcharr-sofascore-sync.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.taylor.dispatcharr-sofascore-sync.plist
```

Or cron: `*/15 * * * * /path/to/run_sofascore_sync.sh --apply`.

**Run it by hand first, WITHOUT `--apply`** (the default -- it only writes
overrides when `--apply` is passed or `SOFASCORE_SYNC_APPLY=1` is set), and
read the per-event verdicts before trusting it unattended:

```bash
./run_sofascore_sync.sh            # dry run, prints verdicts, writes nothing
./run_sofascore_sync.sh --apply    # actually marks confirmed-finished events
```

Every run appends one JSON line to `/tmp/dispatcharr-sofascore-sync.jsonl`
for audit (timestamp, counts, and each event's verdict/match note).

## Known gaps / deliberately out of scope for v1

- **Fighting (UFC/WWE/boxing)** and **Golf** are skipped
  (`SPORT_SLUG_BY_LABEL` maps them to `None`) -- they aren't clean
  two-team "vs" results tracked the same way on SofaScore, and WWE
  specifically is scripted, not a real sporting outcome.
- Matching is name-normalization + sport + a +/-6h start-time window
  around the event's `start_at`, no manual confirmation step. Each
  override's `note` field records exactly which SofaScore fixture it
  matched (`GET /admin/sofascore/overrides` on the resolver, or the local
  `.jsonl` log) so a bad match is easy to spot and undo (`POST
  /admin/sofascore/clear`).
- `interrupted` status (rain delay, etc.) is deliberately NOT treated as
  ended -- only `finished`/`postponed`/`cancelled`/`canceled`/`abandoned`.

## Native deployment on blackpearl.local (Unraid) -- 2026-09-15 update

The original design ran the browser side from this Mac (browser-harness +
launchd, every 15 minutes) and reached the resolver over SSH + `docker
exec`. That works, but it means the "check every 15 minutes" requirement
silently stops if this Mac is off, asleep, or its Docker Desktop / browser
container isn't up. Since the whole point is unattended reliability, the
sync now also runs as **its own small container directly on
blackpearl.local**, on the same Docker network as `rive-resolver` --
no Mac, no SSH, no launchd in the loop at all for production use.

- `native-service/sync_daemon.py` -- same matching logic as
  `sofascore_sync.py` (title parsing, name normalization, SofaScore search
  + team-events lookups, finished/postponed/cancelled/abandoned detection),
  rewritten against Playwright's Python API directly instead of
  browser-harness's CDP wrapper, and calling the resolver's admin routes
  over the internal docker network (`http://rive-resolver:8787/admin/...`)
  instead of ssh + `docker exec`. Runs as a plain infinite loop (one cycle
  every `SYNC_INTERVAL_SECONDS`, default 900 = 15 minutes), not a cron job.
- `native-service/Dockerfile` -- built `FROM
  mcr.microsoft.com/playwright/python:v1.62.0-noble`, **the exact same
  base image `rive-resolver` itself already uses** (see
  `rive-resolver/Dockerfile`), so Chromium and every OS dependency are
  already present -- nothing extra to install, and the image layer is
  already cached on blackpearl.local from building rive-resolver.
- `native-service/compose-service.yml.snippet` -- the exact service block
  to add to `docker-compose.unified.phase1.candidate.yml`, on the shared
  `upstream` network at `172.30.91.14` (the next free address after
  `.10`=rive-resolver, `.11`=tuliprox, `.12`/`.13`=dispatcharr/celery).

**Verified locally before shipping to production** (2026-09-15, this Mac,
plain `playwright.sync_api`, not Patchright): launching headless Chromium
via bare Playwright, loading `https://www.sofascore.com/` (1.9s), and
calling `find_finished_match()` from inside that page context correctly
resolved the same real fixture (`Minnesota Twins vs New York Yankees`,
sofascore id `15508077`, `status.type: finished`) that the original
Patchright-based prototype found. **This confirms plain Playwright is
sufficient** -- the earlier 403 from `api.sofascore.com` against a raw
`urllib` client is a Cloudflare TLS-fingerprint gate on that API host, not
a headless-Chromium detection gate on the page itself, so no stealth
patching is needed to clear it from inside a real browser's own `fetch()`.

The Mac-based `sofascore_sync.py` / `run_sofascore_sync.sh` / launchd job
described above is **kept as a secondary/manual path** -- useful for an
interactive dry run or spot-check from a terminal -- but is no longer the
thing responsible for the unattended 15-minute cadence once the native
service is deployed and confirmed. Consider disabling the launchd job
(`launchctl bootout gui/$(id -u)
~/Library/LaunchAgents/com.taylor.dispatcharr-sofascore-sync.plist`) once
the native service has run cleanly for a few cycles, to avoid two
processes racing to mark the same events (harmless since the overlay write
is idempotent, but redundant).

### Deploying the native service

```bash
# 1. Copy the service directory into the stack, alongside rive-resolver/, tuliprox/
scp -r scripts/dispatcharr-sofascore-sync/native-service/ \
    root@blackpearl.local:/mnt/user/appdata/unified-iptv/stack/sofascore-sync

# 2. Add the service block from native-service/compose-service.yml.snippet
#    into docker-compose.unified.phase1.candidate.yml (same file the other
#    services live in). RIVE_ADMIN_TOKEN already exists in .env.unified
#    from the admin-routes deploy above -- reused as-is, no new token needed.

# 3. Build + start with SOFASCORE_SYNC_APPLY=0 first (dry run -- logs
#    matches, writes nothing) for at least one full cycle before trusting it:
cd /mnt/user/appdata/unified-iptv/stack
docker compose --env-file .env.unified \
  -f docker-compose.unified.phase1.candidate.yml \
  -f docker-compose.unified.operator-access.yml \
  build sofascore-sync
docker compose --env-file .env.unified \
  -f docker-compose.unified.phase1.candidate.yml \
  -f docker-compose.unified.operator-access.yml \
  up -d sofascore-sync
docker logs -f --tail 100 unified-iptv-phase1-sofascore-sync-1
# watch for: "starting: ... apply=False", then "tracked=N candidates=M",
# "finished: <title> | sofascore #... status=finished" lines (with no
# "marked_ended" jump since apply is off), then "sleeping ~900s".

# 4. Once a dry-run cycle looks correct, flip to real:
#    set SOFASCORE_SYNC_APPLY=1 in .env.unified, then:
docker compose --env-file .env.unified \
  -f docker-compose.unified.phase1.candidate.yml \
  -f docker-compose.unified.operator-access.yml \
  up -d sofascore-sync

# 5. Verify over the next 15-30 minutes: /admin/sofascore/overrides on the
#    resolver should grow, and the public XC feed / Dispatcharr's own
#    dispatcharr_channels_stream / dispatcharr_channels_channel tables
#    should stop containing finished games (same verification queries used
#    in the original deploy, above).
```

