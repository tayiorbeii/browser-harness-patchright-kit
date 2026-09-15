# Plan: Gate sofascore-browser's egress behind a gluetun (Windscribe WireGuard) gateway

> Grounded in `research.md` / `evidence.json`. Recommendation: option (a).
> This plan touches ONLY the `sofascore-browser` service's networking and
> ADDS one gateway service. `sofascore-sync`, `rive-resolver`, `dispatcharr*`,
> `tuliprox` keep their current networks and egress untouched.

## Objective

`sofascore-browser` fetches sofascore.com through Windscribe so the
Fastly/Varnish edge-level 403 on blackpearl.local's IP stops applying,
while CDP stays reachable from `sofascore-sync` on the internal
`upstream` network and no other service changes behavior.

## Target compose shape (docker-compose.unified.phase1.candidate.yml)

```yaml
  sofascore-vpn:
    image: qmcgaw/gluetun:<pinned tag>        # verify current tag/repo at impl time (repo moved: N1)
    container_name: sofascore-vpn
    cap_add:
      - NET_ADMIN
    devices:
      - /dev/net/tun:/dev/net/tun
    restart: unless-stopped
    environment:
      VPN_SERVICE_PROVIDER: windscribe
      VPN_TYPE: wireguard
      WIREGUARD_PRIVATE_KEY: ${WINDSCRIBE_WG_PRIVATE_KEY:?set WINDSCRIBE_WG_PRIVATE_KEY}
      WIREGUARD_ADDRESSES: ${WINDSCRIBE_WG_ADDRESSES:?set WINDSCRIBE_WG_ADDRESSES}   # e.g. 10.x.y.z/32 from the generated config
      WIREGUARD_PRESHARED_KEY: ${WINDSCRIBE_WG_PRESHARED_KEY:-}
      SERVER_REGIONS: ${WINDSCRIBE_SERVER_REGIONS:?set WINDSCRIBE_SERVER_REGIONS}    # e.g. United States
      # CDP reachability for sofascore-sync through the shared netns:
      FIREWALL_INPUT_PORTS: "9222"
      # keep LAN/upstream reachability rules explicit if needed:
      # FIREWALL_OUTBOUND_SUBNETS: 172.30.91.0/24
    volumes:
      - /mnt/user/appdata/unified-iptv/stack/sofascore-vpn:/gluetun
    networks:
      upstream:
        ipv4_address: ${SOFASCORE_BROWSER_UPSTREAM_IP:-172.30.91.14}   # takes over .14
    healthcheck:                                # gluetun health server, health.go:87 default 127.0.0.1:9999
      test: ["CMD", "wget", "-qO-", "http://127.0.0.1:9999/health"]
      interval: 30s
      timeout: 10s
      retries: 5
      start_period: 60s
    logging: *bounded-logging

  sofascore-browser:
    build:
      context: ./sofascore-sync/browser
    restart: unless-stopped
    init: true
    environment:
      PATCHRIGHT_HEADLESS: "1"
      CDP_PORT: "9222"
    network_mode: "service:sofascore-vpn"       # replaces the networks: block (spec forbids both)
    depends_on:
      sofascore-vpn:
        condition: service_healthy
    healthcheck:                                 # unchanged: 127.0.0.1:9222 works inside the shared netns
      test: ["CMD", "python3", "-c", "...existing heartbeat check..."]
      interval: 60s
      timeout: 10s
      retries: 3
      start_period: 30s
    logging: *bounded-logging
```

`sofascore-sync` keeps `ipv4_address: 172.30.91.15` and
`BROWSER_CDP_URL: http://${SOFASCORE_BROWSER_UPSTREAM_IP:-172.30.91.14}:9222`
— that IP now lands on the vpn gateway, which forwards 9222 into the
shared netns (allowed via `FIREWALL_INPUT_PORTS`).

## Account-side prerequisites (Windscribe)

1. Generate a WireGuard config for one location from Windscribe's account
   UI ("Build a Plan" → WireGuard config). Extract:
   `PrivateKey` → `WINDSCRIBE_WG_PRIVATE_KEY`; `Address` →
   `WINDSCRIBE_WG_ADDRESSES`; `PresharedKey` (if present) →
   `WINDSCRIBE_WG_PRESHARED_KEY`.
2. Choose `SERVER_REGIONS` matching entitled regions (wiki windscribe.md:46).
   Optionally pin the endpoint port via `WIREGUARD_ENDPOINT_PORT`
   (allowed: 53, 80, 123, 443, 1194, 65142 — wiki line 65).
3. Write the values into `/mnt/user/appdata/unified-iptv/stack/.env.unified`
   (chmod 600, same pattern as existing secrets).

## Ordering / restart semantics

- `sofascore-browser` depends on `sofascore-vpn` reaching `healthy` —
  guarantees the tunnel (and shared netns) exists before Chromium starts.
- If gluetun restarts, the browser's netns is disrupted; both have
  `restart: unless-stopped`. Verify during implementation that the browser
  recovers (docker compose recreates/restarts dependents on target
  restart; if flaky, add an explicit watchdog or rely on gluetun's
  `HEALTH_RESTART_VPN` to keep the tunnel alive without restarts).
- `sofascore-sync` needs no dependency change: it already gates on
  `rive-resolver` healthy, and CDP failures surface as
  `sync cycle failed -- will retry next interval` (retries next 15-min tick).

## Verification plan (post-implementation, before SOFASCORE_SYNC_APPLY=1)

1. `docker logs sofascore-vpn` — tunnel up, exit node IP matches a
   Windscribe location (gluetun logs the public IP on start).
2. From inside `sofascore-browser`:
   `curl https://www.sofascore.com/` → expect non-403 (200) via the VPN IP.
3. Repeat the CDP probe used during the blocked deploy:
   page-context `fetch('https://api.sofascore.com/api/v1/search/all?q=cubs')`
   → expect 200.
4. From `sofascore-sync`: CDP connect succeeds (cycle log shows
   `tracked=N` with real N).
5. Regression guard: rive-resolver/dispatcharr/tuliprox outbound behavior
   unchanged (their egress never touches gluetun), all other containers'
   IPs on `upstream` unchanged.
6. Only then run one apply=1 cycle and cross-check
   `/admin/sofascore/overrides`.

## Risks / open items

- **Windscribe WG quirks**: preshared key requirement, region entitlements,
  endpoint port filtering — mitigated by the env contract above; verify
  tunnel handshake in gluetun logs first.
- **Image provenance**: `qmcgaw/gluetun` repo moved (404 verified);
  re-check the canonical image/tag before pinning (research.md N1).
- **CDP latency through tunnel**: healthcheck intervals (60s heartbeat,
  1200s staleness) tolerate a slow tunnel; watch the first cycles.
- **IPv6**: WG tunnel is IPv4; ensure the browser's netns has no
  (or a blocked) IPv6 leak path so requests don't exit via the native v6
  address with the blocked IP. Verify with a v6 echo test inside the
  browser container during implementation.
- **Firewall/LAN rules**: if `sofascore-sync` → CDP still fails after
  `FIREWALL_INPUT_PORTS`, check `FIREWALL_OUTBOUND_SUBNETS` /
  interface binding of the CDP listener (0.0.0.0 vs 127.0.0.1) inside the
  browser container.
