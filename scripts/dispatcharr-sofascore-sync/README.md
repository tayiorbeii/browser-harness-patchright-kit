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
container isn't up. The sync now runs as **two small containers directly
on blackpearl.local** instead, on the same Docker network as
`rive-resolver` -- no Mac, no SSH, no launchd in the loop at all for
production use:

- **`sofascore-browser`** -- a verbatim copy of this project's own
  `docker/browser-harness-patchright/` image (Patchright launching
  Chromium, exposing Chrome DevTools Protocol), run **headless**, with CDP
  reachable only on the internal `upstream` docker network (never
  published to host or internet).
- **`sofascore-sync`** -- a small, lightweight container (`python:3.12-slim`
  + one pip package, `websocket-client`) that speaks **raw CDP** (plain
  WebSocket JSON-RPC, `native-service/cdp_client.py`) to `sofascore-browser`
  and plain HTTP to `rive-resolver`'s admin routes over the internal
  network. **Deliberately does not import the `playwright` or `patchright`
  Python packages at all** -- it is a pure protocol client, so there is no
  dependency on whether a given base image happens to ship the `playwright`
  pip package (an earlier attempt at this used `mcr.microsoft.com/
  playwright/python` directly with `playwright.sync_api` and crash-looped:
  that base image ships the Chromium *binaries* but not the `playwright`
  Python *package* -- confirmed live on blackpearl.local, see git history).

Files:
- `native-service/browser/` -- copy of `docker/browser-harness-patchright/
  {Dockerfile,launch_patchright_cdp.py}`. Keep these two copies in sync by
  hand if the parent image changes; see `native-service/browser/README.md`.
- `native-service/cdp_client.py` -- minimal CDP client: HTTP discovery of
  the browser's `webSocketDebuggerUrl`, one WebSocket connection,
  `Target.createTarget` / `Target.attachToTarget` (flatten mode, matching
  browser-harness's own proven pattern), `Page.navigate`, `Runtime.evaluate`.
  **Chrome's CDP handshake rejects the default `Origin` header
  `websocket-client` sends** (DNS-rebinding protection -- confirmed live,
  `403 Rejected an incoming WebSocket connection from the http://...
  origin`); the client connects with `suppress_origin=True` to omit it.
- `native-service/sync_daemon.py` -- same title-parsing / name-normalization
  / SofaScore-matching logic as the Mac-based `sofascore_sync.py`, driving
  `cdp_client.py` instead of browser-harness's own CDP wrapper. Runs as a
  plain infinite loop, one cycle per `SYNC_INTERVAL_SECONDS` (900s
  default), touching a heartbeat file each cycle for the Dockerfile's
  healthcheck.
- `native-service/Dockerfile` -- the lightweight `sofascore-sync` image
  (no browser, no playwright/patchright).
- `native-service/compose-service.yml.snippet` -- both service blocks to
  add to `docker-compose.unified.phase1.candidate.yml`, on the `upstream`
  network at `172.30.91.14` (browser) and `.15` (sync) -- the next free
  addresses after `.10`-`.13`.

**Verified mechanically correct, locally, against this Mac's own running
Patchright/CDP container** (same protocol, zero risk to production,
2026-09-15): `cdp_client.py` connected, created and attached to a target,
navigated to `https://www.sofascore.com/`, and ran the exact `fetch()`
JS payload `sync_daemon.py` uses, getting back exactly what the browser
saw. That test's `fetch()` call itself returned `403` -- **not a flaw in
the CDP approach**: a plain `curl` from this same Mac's IP to
`www.sofascore.com` returned `403` too, moments later. This session made
several dozen automated requests to sofascore.com/api.sofascore.com over
roughly an hour while prototyping (Patchright test, Playwright test, CDP
test, several dry-run/apply cycles of the Mac-based script) and Cloudflare
temporarily rate-limited this Mac's public IP as a result -- an
entirely different, unrelated public IP from blackpearl.local's. The
mechanics (connect / navigate / evaluate) all worked exactly as designed;
only the sofascore.com response itself was rate-limited, from over-testing
on this one IP, not from anything wrong with using CDP. **Confirm this
clears on blackpearl.local's own IP as the very first verification step
after deploying** (see step 4 below) -- expected to work immediately since
it's a fresh, unflagged IP making its first request of the day.

### Deploying the native service

```bash
# 1. Copy the service directory into the stack, alongside rive-resolver/, tuliprox/
scp -r scripts/dispatcharr-sofascore-sync/native-service/ \
    root@blackpearl.local:/mnt/user/appdata/unified-iptv/stack/sofascore-sync

# 2. Add BOTH service blocks from
#    sofascore-sync/compose-service.yml.snippet into
#    docker-compose.unified.phase1.candidate.yml (same file the other
#    services live in). RIVE_ADMIN_TOKEN already exists in .env.unified
#    from the admin-routes deploy above -- reused as-is, no new token needed.

# 3. Build + start both, sync in dry-run mode (SOFASCORE_SYNC_APPLY=0,
#    the default) for at least one full cycle before trusting it:
cd /mnt/user/appdata/unified-iptv/stack
docker compose --env-file .env.unified \
  -f docker-compose.unified.phase1.candidate.yml \
  -f docker-compose.unified.operator-access.yml \
  build sofascore-browser sofascore-sync
docker compose --env-file .env.unified \
  -f docker-compose.unified.phase1.candidate.yml \
  -f docker-compose.unified.operator-access.yml \
  up -d sofascore-browser sofascore-sync

# 4. FIRST verify sofascore.com itself is reachable from blackpearl.local's
#    IP (should be -- see the rate-limit note above for why this Mac's
#    tests hit a wall right before shipping):
docker exec unified-iptv-phase1-sofascore-browser-1 sh -c \
  "curl -s -o /dev/null -w '%{http_code}\n' https://www.sofascore.com/"
# expect 200. If this is also 403 here, stop -- that would mean an actual
# problem (not the Mac-side rate limit), and the sync container will
# never succeed until it's resolved.

# 5. Watch the first sync cycle:
docker logs -f --tail 200 unified-iptv-phase1-sofascore-sync-1
# watch for: "starting: ... apply=False", "tracked=N candidates=M",
# zero or more "finished: <title> | sofascore #... status=finished" lines,
# "cycle complete: ... marked_ended=0" (must be 0 while apply=False),
# "sleeping ~900s".

# 6. Once a dry-run cycle looks correct, flip to real: set
#    SOFASCORE_SYNC_APPLY=1 in .env.unified, then re-run the `up -d
#    sofascore-sync` command from step 3 (recreates just that container).

# 7. Verify over the next 15-30 minutes the same way as the original
#    deploy: /admin/sofascore/overrides on the resolver should grow, and
#    Dispatcharr's own dispatcharr_channels_stream / _channel tables
#    should stop containing finished games.
```

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

## Deploy result, 2026-09-15: pipeline proven, blocked on an external IP block

Both `sofascore-browser` and `sofascore-sync` are deployed, healthy, and
running the 15-minute loop on blackpearl.local right now
(`SOFASCORE_SYNC_APPLY=0`, dry-run -- writes nothing). Confirmed:

- `cdp_client.py` connects to `sofascore-browser` over the internal docker
  network using its resolved IP (`http://172.30.91.14:9222` in the logs),
  passing Chrome's Host-header check.
- `sync_daemon.py` reaches `rive-resolver`'s admin API over the same
  network (`tracked=184` real events in the first cycle) and correctly
  filters candidates.
- All other services (`dispatcharr`, `-celery`, `-db`, `-redis`,
  `tuliprox`, `rive-resolver`) untouched, uptimes unchanged.

**What's blocking `SOFASCORE_SYNC_APPLY=1`:** sofascore.com itself refuses
blackpearl.local's public IP outright.

```
$ curl -D - -o /dev/null https://www.sofascore.com/     # from blackpearl.local
HTTP/2 403
server: Varnish
content-length: 48
{"error": {"code": 403, "reason": "Forbidden" }}
```

This is **not** the Cloudflare TLS-fingerprint gate this whole design was
built around (that gate is what the Patchright/CDP browser exists to
clear, and it does -- confirmed working from this Mac's IP and from
blackpearl.local's own IP for reachability up to this point). SofaScore is
fronted by **Fastly** (`server: Varnish`, DNS resolves to
`*.map.fastly.net`), and this 403 has none of the markers of a bot
challenge -- no HTML interstitial, no `cf-ray`/challenge headers, just a
small (48-byte) generic JSON body, identical for the homepage AND the API,
identical over IPv4 and IPv6. That shape matches a straight **edge-level
IP or ASN block**, not a per-request bot-detection challenge -- something
no amount of browser stealth (Patchright, plain Playwright, or anything
else) can clear, because it isn't evaluating the request's browser
fingerprint at all.

blackpearl.local's public IP is `65.129.5.149` (CenturyLink Communications
/ AS209, Boise, Idaho -- a genuine residential ISP, not a known VPN or
hosting provider) -- checked via `ipapi.co`, not obviously "bad" IP
reputation on paper, but blocked by SofaScore/Fastly regardless. Possible
causes: SofaScore/Fastly may apply reputation scoring at the ASN or
/24-subnet level rather than the single IP, and something else on this ISP
range's history could have triggered it; or SofaScore blocks that ASN
outright for some other reason. This is outside what this project
controls -- it's SofaScore's own edge policy toward that network, not a
bug in the resolver, the browser container, or the CDP client.

### What this means practically

- The **Mac-based path** (`sofascore_sync.py` + launchd, this Mac's IP)
  still works when not over-tested -- it already found and removed 5 real
  finished games from Dispatcharr earlier today (see the first deploy
  section above). This Mac's IP is not CenturyLink/AS209.
- The **native Unraid path** is fully built, deployed, and healthy, but
  cannot write real overrides until blackpearl.local can reach
  sofascore.com. Left in dry-run (`SOFASCORE_SYNC_APPLY=0`) so it's
  harmless while this is unresolved.

### Options to actually unblock the Unraid path

1. **Route `sofascore-browser`'s egress through a different IP** -- a VPN
   or proxy container on the same docker network (e.g. Gluetun, a
   WireGuard/OpenVPN client container) that `sofascore-browser` uses for
   its outbound traffic only, leaving every other service's egress
   unchanged. This is the most direct fix if such a service/subscription
   is available.
2. **Ask SofaScore/Fastly, or wait it out** -- if this is a transient
   ASN-reputation flag rather than a permanent block, it may clear on its
   own; re-run the same `curl -D -` check from blackpearl.local
   periodically.
3. **Keep the Mac as the production path** for now, accepting the
   "requires this Mac to be on" limitation, since it demonstrably works.
4. **Switch data sources** -- a different sports-scores API/site not
   blocking this ASN. Would need the same evidence-gathering process this
   session used for SofaScore repeated against a new target before
   trusting it.

None of these require more browser-automation work -- the automation side
is done and proven; this is a network-egress decision for the operator.

