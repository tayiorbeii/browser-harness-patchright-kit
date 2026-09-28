# Implementation checklist (follow-up task — do NOT run during this research task)

> Prereq: review `research.md`, `plan.md`, `SUMMARY.md`. All compose edits
> happen in `/mnt/user/appdata/unified-iptv/stack/` on blackpearl.local
> (candidate + operator-access compose files), dry-run first.

## Account side (Windscribe web UI)
- [ ] Generate a WireGuard config ("Build a Plan" → WG config) for the
      desired location; record PrivateKey / Address / PresharedKey.
- [ ] Note entitled regions for `SERVER_REGIONS`.

## blackpearl.local filesystem
- [ ] Add `WINDSCRIBE_WG_PRIVATE_KEY`, `WINDSCRIBE_WG_ADDRESSES`,
      `WINDSCRIBE_WG_PRESHARED_KEY` (optional), `WINDSCRIBE_SERVER_REGIONS`
      to `.env.unified` (chmod 600).
- [ ] Add the `sofascore-vpn` service block (see plan.md) to
      `docker-compose.unified.phase1.candidate.yml`; pin the gluetun image
      tag after verifying the canonical repo/tag (repo moved — see
      research.md N1).
- [ ] Edit the `sofascore-browser` service: remove its `networks:` block
      (spec: networks + network_mode are mutually exclusive), add
      `network_mode: "service:sofascore-vpn"` and
      `depends_on: {sofascore-vpn: {condition: service_healthy}}`.
      Keep its heartbeat healthcheck unchanged.
- [ ] Leave `sofascore-sync` untouched (its `BROWSER_CDP_URL` still points
      at `172.30.91.14:9222`, which is now the vpn gateway's upstream IP).

## Validation sequence
- [ ] `docker compose --env-file .env.unified -f docker-compose.unified.phase1.candidate.yml -f docker-compose.unified.operator-access.yml config` — validate.
- [ ] Confirm no other service uses 172.30.91.14 (browser gave it up) and .15 (sync) is still unique.
- [ ] `up -d sofascore-vpn` first; logs show tunnel up + exit IP is a Windscribe IP (not 65.129.5.149).
- [ ] `up -d sofascore-browser`; wait healthy; heartbeat healthcheck green.
- [ ] From browser container: `curl -s -o /dev/null -w '%{http_code}' https://www.sofascore.com/` → 200 (was 403).
- [ ] CDP probe (page-context fetch to api.sofascore.com) → 200 (was 403).
- [ ] IPv6 leak check inside browser container (no v6 egress with the blocked IP).
- [ ] Watch one full dry-run cycle of `sofascore-sync`: `tracked=N` real,
      `cycle complete ... marked_ended=0`.
- [ ] Regression: rive-resolver / dispatcharr / tuliprox egress + uptimes
      unchanged; no other container's upstream IP changed.
- [ ] Flip `SOFASCORE_SYNC_APPLY=1`, watch one cycle, verify
      `marked_ended` == number of `finished:` lines, cross-check
      `GET /admin/sofascore/overrides` (token-gated) matches.

## Rollback
- [ ] `git`-style revert = remove `sofascore-vpn` block, restore the
      browser's `networks: upstream` + IP `.14` block (documented in git
      history of the compose edit), `up -d` both. `.env.unified` keys can
      stay (unused).
