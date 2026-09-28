# Task: deploy the native sofascore-sync container to blackpearl.local

Context: `scripts/dispatcharr-sofascore-sync/README.md`, section "Native
deployment on blackpearl.local (Unraid) -- 2026-09-15 update". Read that
section first -- it has the full reasoning. This task makes it concrete.

You already deployed the resolver-side admin patch to blackpearl.local
earlier (backups exist at
`rive-resolver/app/events.py.bak-20260914T221344` and
`main.py.bak-20260914T221344`; `RIVE_ADMIN_TOKEN` is already in
`.env.unified` and the rive-resolver `environment:` block). Do not touch
those again -- this task only ADDS one new service.

You have root SSH to blackpearl.local (key-based, already verified working).

## Steps

1. **Copy the new service directory** from this repo to blackpearl.local:
   ```
   scp -r scripts/dispatcharr-sofascore-sync/native-service        root@blackpearl.local:/mnt/user/appdata/unified-iptv/stack/sofascore-sync
   ```
   Verify with `ssh root@blackpearl.local 'ls -la
   /mnt/user/appdata/unified-iptv/stack/sofascore-sync'` -- should contain
   `Dockerfile`, `sync_daemon.py`, `compose-service.yml.snippet`.

2. **Add the service block** from
   `sofascore-sync/compose-service.yml.snippet` (now on blackpearl.local,
   copied in step 1) into
   `/mnt/user/appdata/unified-iptv/stack/docker-compose.unified.phase1.candidate.yml`,
   in the same top-level services list as `rive-resolver:`, `tuliprox:`,
   `dispatcharr:` (read the snippet file for the exact block -- copy it
   verbatim as a new `sofascore-sync:` service entry). Confirm no other
   service already uses IP `172.30.91.14` on the `upstream` network before
   adding (there shouldn't be any -- `.10`-`.13` are already taken by
   rive-resolver/tuliprox/dispatcharr/dispatcharr-celery).

3. **Start in dry-run mode first.** Before building, confirm
   `SOFASCORE_SYNC_APPLY` is either unset (defaults to `0` per the snippet)
   or explicitly `0` in `.env.unified` -- do NOT set it to `1` yet.
   ```
   cd /mnt/user/appdata/unified-iptv/stack
   docker compose --env-file .env.unified      -f docker-compose.unified.phase1.candidate.yml      -f docker-compose.unified.operator-access.yml      build sofascore-sync
   docker compose --env-file .env.unified      -f docker-compose.unified.phase1.candidate.yml      -f docker-compose.unified.operator-access.yml      up -d sofascore-sync
   ```

4. **Watch the first cycle.** It should complete within roughly 30-60
   seconds of container start (Chromium launch + page load + N SofaScore
   lookups). Tail logs:
   ```
   docker logs -f --tail 200 unified-iptv-phase1-sofascore-sync-1
   ```
   Look for, in order:
   - `starting: resolver=http://rive-resolver:8787 interval=900s apply=False`
   - `tracked=<N> candidates=<M>` (N and M should be plausible, not 0/0 --
     if `tracked=0`, the container likely can't reach rive-resolver over
     the internal network or the admin token is wrong; if `candidates=0`
     that alone is fine, it just means nothing is currently old enough /
     the right sport to check)
   - zero or more `finished: <title> | sofascore #... status=...` lines
   - `cycle complete: tracked=<N> candidates=<M> marked_ended=0` (must be 0
     while apply=False -- if it's nonzero something is wrong, stop and
     report)
   - `sleeping ~900s until next cycle`

   Also confirm the container reports healthy after ~30-90s:
   ```
   docker ps --filter name=sofascore-sync --format '{{.Names}} {{.Status}}'
   ```

5. **If the dry-run cycle looks correct**, flip it live:
   - Set `SOFASCORE_SYNC_APPLY=1` in `.env.unified`.
   - Re-run the `up -d sofascore-sync` command from step 3 (compose will
     recreate just this one container with the new env var; nothing else
     restarts).
   - Watch one more cycle's logs. This time any `finished:` line should be
     followed by a successful push (no `failed to push override for ...`
     errors), and `marked_ended` in the "cycle complete" line should equal
     the number of `finished:` lines from that cycle.

6. **Cross-check against the resolver's own overrides endpoint** (same
   token you already have):
   ```
   docker exec unified-iptv-phase1-rive-resolver-1 sh -c      'curl -s -H "X-Admin-Token: 4682ac3c50f80f522c9ae4014e9c1a7dc4eb8a37415f96bb"       http://127.0.0.1:8787/admin/sofascore/overrides' | python3 -m json.tool
   ```
   New entries should appear here matching what sofascore-sync logged as
   `marked_ended`.

7. **Do not touch** dispatcharr, dispatcharr-celery, dispatcharr-db,
   dispatcharr-redis, tuliprox, or the rive-resolver container itself in
   this task -- only build/start the new `sofascore-sync` service and
   confirm the others remain untouched (uptimes unchanged) at the end.

8. **Report back**: exact log excerpts for steps 4-6, the final container
   status/health, and whether you left `SOFASCORE_SYNC_APPLY=1` (should be
   yes, if everything checked out) or reverted to `0` and why. End your
   final message with "NATIVE DEPLOY DONE" or "NATIVE DEPLOY BLOCKED:
   <reason>".
