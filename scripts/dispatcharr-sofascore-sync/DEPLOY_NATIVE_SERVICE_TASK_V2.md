# Task: redeploy sofascore-sync as TWO services (CDP-based, no playwright)

Supersedes `DEPLOY_NATIVE_SERVICE_TASK.md`. The previous attempt used the
`playwright` Python package directly inside a single `sofascore-sync`
container and crash-looped (`ModuleNotFoundError: No module named
'playwright'` -- the `mcr.microsoft.com/playwright/python` base image ships
Chromium binaries but not the pip package). You already correctly diagnosed
this and stopped the crash loop -- thank you, that diagnosis was right.

**The design has changed, not just the Dockerfile.** Read
`scripts/dispatcharr-sofascore-sync/README.md`, section "Native deployment
on blackpearl.local (Unraid) -- 2026-09-15 update" (it was rewritten) before
doing anything. Summary: it is now **two containers**, and the sync
container never imports playwright/patchright at all:

- `sofascore-browser` -- Patchright/Chromium, exposes CDP internally only.
  This is a straight copy of this repo's own
  `docker/browser-harness-patchright/{Dockerfile,launch_patchright_cdp.py}`,
  now vendored at `scripts/dispatcharr-sofascore-sync/native-service/browser/`.
- `sofascore-sync` -- lightweight `python:3.12-slim` + `websocket-client`
  only. Speaks raw CDP (WebSocket JSON-RPC) to `sofascore-browser` via
  `cdp_client.py`, and plain HTTP to `rive-resolver`'s admin routes. No
  playwright, no patchright, no browser binaries in this container.

`RIVE_ADMIN_TOKEN` is already correct in `.env.unified` and the
rive-resolver `environment:` block from the earlier deploy -- do not touch
those.

## Steps

1. **Clean out the stale partial deploy** from the previous attempt:
   ```
   ssh root@blackpearl.local 'rm -rf /mnt/user/appdata/unified-iptv/stack/sofascore-sync'
   ```
   (The stopped `unified-iptv-phase1-sofascore-sync-1` container and its
   image can stay or be pruned later -- `docker compose ... rm -f
   sofascore-sync` after the clean copy is fine, not required first.)

2. **Copy the updated service directory fresh:**
   ```
   scp -r scripts/dispatcharr-sofascore-sync/native-service        root@blackpearl.local:/mnt/user/appdata/unified-iptv/stack/sofascore-sync
   ```
   Verify it now contains: `Dockerfile`, `cdp_client.py`, `sync_daemon.py`,
   `compose-service.yml.snippet`, and a `browser/` subdirectory with its own
   `Dockerfile` + `launch_patchright_cdp.py` + `README.md`. There should be
   **no `requirements.txt`** in this directory (that was a leftover from the
   abandoned playwright-pip-install fix -- if you see one, it means the copy
   picked up something stale; re-copy).

3. **Replace the compose service block(s).** Open
   `/mnt/user/appdata/unified-iptv/stack/docker-compose.unified.phase1.candidate.yml`
   and find the `sofascore-sync:` service block added by the previous
   attempt (single service, `build: context: ./sofascore-sync` with no
   `browser` involved). **Delete that entire block** and replace it with
   BOTH blocks from the freshly-copied
   `sofascore-sync/compose-service.yml.snippet` (`sofascore-browser:` and
   `sofascore-sync:`) -- copy them verbatim into the same services list as
   `rive-resolver:`/`tuliprox:`/`dispatcharr:`. Confirm IPs `172.30.91.14`
   (browser) and `.15` (sync) aren't used elsewhere in the file.

4. **Build both, start both:**
   ```
   cd /mnt/user/appdata/unified-iptv/stack
   docker compose --env-file .env.unified      -f docker-compose.unified.phase1.candidate.yml      -f docker-compose.unified.operator-access.yml      build sofascore-browser sofascore-sync
   docker compose --env-file .env.unified      -f docker-compose.unified.phase1.candidate.yml      -f docker-compose.unified.operator-access.yml      up -d sofascore-browser sofascore-sync
   ```
   Wait for `sofascore-browser` to report healthy first
   (`docker ps --filter name=sofascore-browser --format '{{.Names}}
   {{.Status}}'`) -- `sofascore-sync` depends on it and won't start
   cleanly otherwise.

5. **Important context before you judge the first result:** this Mac's own
   IP got temporarily rate-limited by Cloudflare on sofascore.com/
   api.sofascore.com during earlier prototyping today (dozens of automated
   requests in under an hour -- confirmed via a plain `curl` from this Mac
   also returning 403). blackpearl.local has a different public IP and
   should NOT be affected. As your FIRST verification, confirm that
   directly, from inside the new browser container:
   ```
   docker exec unified-iptv-phase1-sofascore-browser-1 sh -c      "curl -s -o /dev/null -w '%{http_code}
' https://www.sofascore.com/"
   ```
   Expect `200`. If this is `403` here too, stop and report -- that would
   be a real, different problem (not the Mac-side rate limit), and
   `sofascore-sync` cannot work until it's resolved. If it's `200`,
   proceed normally.

6. **Watch the first sync cycle** (should complete within roughly a
   minute of `sofascore-sync` starting: connect to the browser's CDP,
   open a target, navigate, run lookups):
   ```
   docker logs -f --tail 200 unified-iptv-phase1-sofascore-sync-1
   ```
   Look for, in order:
   - `starting: resolver=http://rive-resolver:8787 browser_cdp=http://sofascore-browser:9222 interval=900s apply=False`
   - `tracked=<N> candidates=<M>` (if `tracked=0`, the sync container
     likely can't reach rive-resolver over the internal network or the
     admin token is wrong -- stop and report; `candidates=0` alone is
     fine, it just means nothing is currently old enough / the right sport
     to check)
   - zero or more `finished: <title> | sofascore #... status=...` lines
   - `cycle complete: tracked=<N> candidates=<M> marked_ended=0` (must be
     0 while apply=False)
   - `sleeping ~900s until next cycle`

   If a cycle raises an exception, the log will show
   `sync cycle failed -- will retry next interval` with a traceback --
   read it, it's expected to be either a CDP connection issue (wrong
   `BROWSER_CDP_URL` / browser not ready yet) or a resolver-auth issue
   (wrong token / wrong `RIVE_RESOLVER_BASE_URL`), both easy to diagnose
   from the traceback. Fix obvious misconfguration yourself; stop and
   report anything that looks like a real bug in the code.

7. **If the dry-run cycle looks correct**, flip it live:
   - Set `SOFASCORE_SYNC_APPLY=1` in `.env.unified`.
   - Re-run the `up -d sofascore-browser sofascore-sync` command from step
     4 (compose recreates only `sofascore-sync`, since only its env
     changed).
   - Watch one more cycle. Any `finished:` line should be followed by a
     successful push (no `failed to push override for ...` errors), and
     `marked_ended` should equal the number of `finished:` lines from that
     cycle.

8. **Cross-check** against the resolver's own overrides endpoint (same
   token as before):
   ```
   docker exec unified-iptv-phase1-rive-resolver-1 sh -c      'curl -s -H "X-Admin-Token: 4682ac3c50f80f522c9ae4014e9c1a7dc4eb8a37415f96bb"       http://127.0.0.1:8787/admin/sofascore/overrides' | python3 -m json.tool
   ```
   New entries should match what `sofascore-sync` logged as `marked_ended`.

9. **Do not touch** dispatcharr, dispatcharr-celery, dispatcharr-db,
   dispatcharr-redis, tuliprox, or rive-resolver in this task -- confirm
   their uptimes are unchanged at the end.

10. **Report back**: log excerpts for steps 5, 6, 8, final container
    statuses for both new services, and whether `SOFASCORE_SYNC_APPLY` was
    left at `1` (expected, if everything checked out). End your final
    message with "NATIVE DEPLOY V2 DONE" or "NATIVE DEPLOY V2 BLOCKED:
    <reason>".
