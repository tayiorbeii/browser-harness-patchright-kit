# Task: deploy the SofaScore resolver patch to blackpearl.local

You have root SSH access to `blackpearl.local` (key-based, no password needed --
`ssh root@blackpearl.local` just works, already verified this session).

Context: `scripts/dispatcharr-sofascore-sync/README.md` in this repo has the
full background. Read it first. This task is exactly its "Deploying the
resolver patch" section, made concrete with a specific token and exact
instructions -- do not regenerate the token or invent your own values.

## Token

Use exactly this value everywhere below:

```
RIVE_ADMIN_TOKEN=4682ac3c50f80f522c9ae4014e9c1a7dc4eb8a37415f96bb
```

(This matches the token already placed in
`~/.config/dispatcharr-sofascore-sync/env` on this Mac for the sync script --
do not change it.)

## Steps

1. **Backup first.** On blackpearl.local:
   ```
   cd /mnt/user/appdata/unified-iptv/stack/rive-resolver/app
   cp events.py events.py.bak-$(date +%Y%m%dT%H%M%S)
   cp main.py main.py.bak-$(date +%Y%m%dT%H%M%S)
   ```

2. **Copy the two new files** from this repo's
   `scripts/dispatcharr-sofascore-sync/resolver-patch/` directory to
   `blackpearl.local:/mnt/user/appdata/unified-iptv/stack/rive-resolver/app/`:
   - `sofascore_overlay.py`
   - `admin_sofascore.py`

   Use `scp` from this Mac, or read the local files and write the same
   content over ssh -- either is fine, just make sure the bytes match
   exactly what's in this repo.

3. **Apply the two diffs.** They're in
   `scripts/dispatcharr-sofascore-sync/resolver-patch/events.py.diff` and
   `main.py.diff` in this repo. Read them for the exact intent, but apply
   them as **direct string edits against the live files on blackpearl**
   (read the current file content over ssh first and match on the exact
   surrounding lines you find there -- don't blindly `patch -p1`, this is
   a heavily hand-patched fork and the diffs above are context-only, not
   line-numbered).

   Concretely, in `app/events.py`:
   - Add this import right after `from app.registry import EntityKey, StreamIdRegistry`:
     ```python
     from app.sofascore_overlay import overlay as _sofascore_overlay
     ```
   - Inside `EventPublicationService.list_publications()`, find this exact
     line:
     ```python
             state = EventState.STALE if stale else self._policy.state(event, current)
     ```
     and insert immediately after it (same indentation, 12 spaces):
     ```python
             if state not in (EventState.STALE, EventState.CANCELLED, EventState.ENDED):
                 # SofaScore-confirmed completion overrides the scheduled-
                 # duration/grace math immediately, instead of waiting out
                 # RIVE_EVENT_DEFAULT_DURATION_MINUTES + RIVE_EVENT_GRACE_MINUTES.
                 # Never let a bug here affect normal catalog visibility.
                 try:
                     if _sofascore_overlay.is_confirmed_ended(event.origin, event.event_id):
                         state = EventState.ENDED
                 except Exception:
                     pass
     ```

   In `app/main.py`:
   - Add this import right after `from app.dlhd_proxy import router as dlhd_proxy_router`:
     ```python
     from app.admin_sofascore import router as admin_sofascore_router
     ```
   - Inside `_wire_router_injectors()`, right after `import app.proxy as proxy_mod`,
     add:
     ```python
         import app.admin_sofascore as admin_sofascore_mod
     ```
   - In the same function's injector list (the `for name, fn_name, arg in [...]`
     list), right after the `(xc_mod, "set_event_playback", event_playback),`
     line, add:
     ```python
             (admin_sofascore_mod, "set_event_publications", event_publications),
     ```
   - Near the bottom, right after
     `app.include_router(dlhd_proxy_router, tags=["dlhd-proxy"])`, add:
     ```python
     app.include_router(admin_sofascore_router, tags=["admin-sofascore"])
     ```

   After editing, run `python3 -m py_compile events.py main.py` on
   blackpearl.local (inside `/mnt/user/appdata/unified-iptv/stack/rive-resolver/app`)
   to confirm both files are still syntactically valid before doing anything else.

4. **Add the admin token to the resolver's environment.**
   - In `/mnt/user/appdata/unified-iptv/stack/.env.unified`, add a new line:
     ```
     RIVE_ADMIN_TOKEN=4682ac3c50f80f522c9ae4014e9c1a7dc4eb8a37415f96bb
     ```
   - In `/mnt/user/appdata/unified-iptv/stack/docker-compose.unified.phase1.candidate.yml`,
     find the `rive-resolver:` service's `environment:` block (it has lines like
     `RIVE_XC_USERNAME: ${RIVE_XC_USERNAME:?set RIVE_XC_USERNAME}`) and add one
     more line in that same block:
     ```yaml
           RIVE_ADMIN_TOKEN: ${RIVE_ADMIN_TOKEN:?set RIVE_ADMIN_TOKEN}
     ```

5. **Recompute the build digest and rebuild.** The resolver's `app/` source
   is baked into its Docker image at build time (not bind-mounted), gated by
   an immutable `RIVE_RESOLVER_SOURCE_SHA` build arg. On blackpearl.local:
   ```
   cd /mnt/user/appdata/unified-iptv/stack
   python3 scripts/resolver_source_sha.py
   ```
   Take that output hash and set/update `RIVE_RESOLVER_SOURCE_SHA=<hash>` in
   `.env.unified`. Then:
   ```
   docker compose -f docker-compose.unified.phase1.candidate.yml      -f docker-compose.unified.operator-access.yml build rive-resolver
   docker compose -f docker-compose.unified.phase1.candidate.yml      -f docker-compose.unified.operator-access.yml up -d rive-resolver
   ```
   Watch `docker logs -f --tail 100 unified-iptv-phase1-rive-resolver-1` briefly
   after restart to confirm it starts cleanly (no import errors from the two
   new files, no crash loop). It should become `healthy` within ~30s
   (`docker ps` shows health status).

6. **Verify.** Once healthy:
   ```
   docker exec unified-iptv-phase1-rive-resolver-1 sh -c      'curl -s -H "X-Admin-Token: 4682ac3c50f80f522c9ae4014e9c1a7dc4eb8a37415f96bb"       http://127.0.0.1:8787/admin/sofascore/events' | python3 -m json.tool | head -60

   docker exec unified-iptv-phase1-rive-resolver-1 sh -c      'curl -s -H "X-Admin-Token: 4682ac3c50f80f522c9ae4014e9c1a7dc4eb8a37415f96bb"       http://127.0.0.1:8787/admin/sofascore/overrides'

   # confirm the token gate actually rejects wrong/missing tokens (403):
   docker exec unified-iptv-phase1-rive-resolver-1 sh -c      'curl -s -o /dev/null -w "%{http_code}
" http://127.0.0.1:8787/admin/sofascore/events'

   # confirm the public XC/M3U output still works normally (no regression):
   docker exec unified-iptv-phase1-rive-resolver-1 sh -c      "curl -s -m 8 'http://127.0.0.1:8787/player_api.php?username=rivelive_e2958bbe&password=kHNgiIcBksGtflhlqnaiAKS19wE2&action=get_live_events_streams'"      | python3 -c "import json,sys; print('rows:', len(json.load(sys.stdin)))"

   # confirm Dispatcharr itself is still healthy after the resolver restart:
   docker ps --filter name=dispatcharr --format '{{.Names}} {{.Status}}'
   ```

7. **Report back concisely**: whether every step succeeded, the exact output
   of the 5 verification commands above, and anything that deviated from
   this plan (e.g. if a file's surrounding lines didn't match exactly --
   stop and report rather than guessing). Do not proceed past step 3 if
   `py_compile` fails. Do not restart/rebuild anything beyond the
   `rive-resolver` service -- leave dispatcharr, tuliprox, and everything
   else untouched.
