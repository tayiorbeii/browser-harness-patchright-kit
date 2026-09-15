# Research: Route one container's egress (sofascore-browser) through Windscribe VPN

> Method: manual evidence loop via the authenticated octocode CLI
> (`ghSearch` / `cache fetch` materialization / `gh repo view`), after the
> automated research-orchestrator run produced an inconclusive result (see
> `inconclusive-run1/` for that run's diagnostics — its probe derivation
> extracted generic keywords and selected irrelevant repos).
>
> All GitHub citations below were verified against locally materialized
> clones (exact commit SHAs in `evidence.json`). Windscribe account-side
> behavior is cited from gluetun's official wiki where possible; it is the
> de-facto maintained documentation for using Windscribe with containers.

## Context

SofaScore (fronted by Fastly/Varnish) returns an edge-level 403 to
blackpearl.local's public IP (65.129.5.149, CenturyLink/AS209) for both
the homepage and API, over IPv4 and IPv6. The native `sofascore-browser` /
`sofascore-sync` pair is deployed and healthy but cannot fetch real data.
Goal: route ONLY `sofascore-browser`'s egress through Taylor's Windscribe
account, leaving every other service on the `upstream` docker network
untouched.

## Option comparison

### (a) VPN gateway sidecar (gluetun) + `network_mode: service:<vpn>` — RECOMMENDED

**What it is:** a purpose-built VPN gateway container (gluetun) holds the
tunnel; the target container shares gluetun's network namespace.

Evidence:
- **First-class Windscribe support, both WireGuard and OpenVPN.**
  `qdm12/gluetun-wiki @ 888ab89` `setup/providers/windscribe.md`:
  - lines 15–23: `docker run` with `VPN_SERVICE_PROVIDER=windscribe`,
    `VPN_TYPE=wireguard`, `WIREGUARD_PRIVATE_KEY`,
    `WIREGUARD_ADDRESSES="10.64.222.21/32"`, `WIREGUARD_PRESHARED_KEY`,
    `SERVER_REGIONS=Netherlands`.
  - lines 25–41: the same as a docker-compose service block.
  - lines 43–46: required env list; "Build a Plan" subscriptions must set
    `SERVER_REGIONS` to entitled regions.
  - line 65: `WIREGUARD_ENDPOINT_PORT` may be `53`, `80`, `123`, `443`,
    `1194`, `65142`.
- **The attachment pattern is the official documented method.**
  `qdm12/gluetun-wiki` `setup/connect-a-container-to-gluetun.md` lines
  9–21: "Add `network_mode: "service:gluetun"` to your second container so
  that it uses the gluetun network stack" (same compose file);
  `network_mode: "container:gluetun"` for containers in another compose
  project.
- **Spec-level guarantee.** `compose-spec/compose-spec @ ed4c08a`
  `05-services.md:1283–1299`: `network_mode: "service:[service name]"`
  gives the container access to that service's network stack only, and
  **when set, the `networks` attribute is not allowed** (compose rejects
  files containing both). This is what makes "only this container moves"
  structurally true: the browser leaves the `upstream` network as a
  first-class member and lives inside the gateway's stack.
- **Kill-switch is built in and default-on.** `passteque/gluetun @ 56a3da3`
  `README.md:74`: "Built in firewall kill switch to allow traffic only
  with needed the VPN servers and LAN devices". The firewall settings are
  configurable: `internal/configuration/settings/firewall.go:119–135` —
  `FIREWALL_VPN_INPUT_PORTS`, `FIREWALL_INPUT_PORTS`,
  `FIREWALL_OUTBOUND_SUBNETS` (retro key `EXTRA_SUBNETS`), and
  `FIREWALL_ENABLED_DISABLING_IT_SHOOTS_YOU_IN_YOUR_FOOT` (the name itself
  signals it should never be disabled).
- **Health checking is built in.**
  `internal/configuration/settings/health.go:87`: health server defaults
  to `127.0.0.1:9999`; lines 127–135: `HEALTH_SERVER_ADDRESS`,
  `HEALTH_TARGET_ADDRESSES`, `HEALTH_RESTART_VPN` (restart the tunnel when
  the healthcheck fails).
- **DNS goes through the tunnel.**
  `internal/configuration/settings/dns.go:260–319`: gluetun runs its own
  DNS resolver (DoT/`DNS_SERVER`, plaintext fallback `DNS_UPSTREAM_PLAIN_ADDRESSES`,
  caching) inside its network namespace — a shared container inherits that
  resolver via `/etc/resolv.conf`, so Chromium's DNS resolution follows the
  tunnel.
- **Real-world production pattern.** `Haxxnet/Compose-Examples @ 0669e41`
  `examples/arr-suite/docker-compose.yml:174–216`: gluetun service
  (`container_name: arr-suite-gluetun`, `cap_add: NET_ADMIN`, published
  port `8080:8080` for the tunnelled app's web UI) and the attached
  service qbittorrent at line 216:
  `network_mode: container:arr-suite-gluetun # use the gluetun container network (vpn killswitch)`.
  Note how qbittorrent's UI port is published on **gluetun's** `ports:` —
  ports of an attached container must be published through the gateway.
- **Port/CDP reachability for sibling containers.** Because the browser
  will live inside gluetun's netns, `sofascore-sync` reaches CDP via
  gluetun's IP on the `upstream` network. gluetun's firewall drops inbound
  traffic by default; `FIREWALL_INPUT_PORTS=9222` (firewall.go:124) opens
  CDP to sibling containers. The browser's own heartbeat healthcheck uses
  `127.0.0.1:9222` inside the shared netns and keeps working unchanged.
- **Unraid-compatible.** gluetun's own README (`README.md:46`) links the
  Unraid template fix discussion
  (`passteque/gluetun/discussions/550`) — Unraid runs it as a normal
  Docker container.

Caveats found:
- The repo has moved (`qmcgaw/gluetun` now 404s; verified via
  `gh api repos/qmcgaw/gluetun` → 404 on 2026-09-15); the image name
  `qmcgaw/gluetun` is still the one used in the wiki and examples. Pin the
  image tag at implementation time and re-check the current canonical
  location (`passteque/gluetun` is the current code home, ★15.5k).
- Windscribe WG credential generation ("Build a Plan" WG config, preshared
  key, region entitlements) is a manual account-side step — the wiki's
  env values are examples, not universal.
- Restart-order: an attached container shares the gateway's netns, so a
  gluetun restart disrupts the browser's network until it is restarted.
  Mitigation: `restart: unless-stopped` on both + `depends_on:
  condition: service_healthy` on the browser (stronger than the wiki's
  "no need for depends_on", which concerns name resolution, not startup
  ordering).

### (b) Windscribe's official Linux CLI inside the target container — NOT recommended

- The Windscribe CLI is a closed-source binary distributed via Windscribe's
  package repos; there is **no official Docker image**.
- Only third-party wrappers exist, found via GitHub code search
  (`ghSearch`, filename:Dockerfile, keyword "windscribe", 2026-09-15):
  `wiorca/docker-windscribe` (**30 stars, last pushed 2022-09-22** —
  verified stale), `BlkLeg/CircuitBreaker`,
  `dumbasPL/windscribe-ephemeral-port-torrent`, `Kabe0/deluge-windscribe`,
  `jay-to-the-dee/Windscribe-HTTPproxy-dockerized`.
- The CLI is TUI/systemd-oriented; wrapping it in a headless container
  means maintaining login-token + daemon lifecycle plumbing inside the
  same image as Chromium, with **no kill-switch guarantee** documented and
  no health contract. Rejected: unmaintained dependencies, no health
  story, per-image coupling.

### (c) Plain WireGuard sidecar (linuxserver/wireguard or bare wg-quick) — viable fallback

- `linuxserver/docker-wireguard @ fee041b` README.md:
  - line 60: "can be run as a server or a client, based on the parameters
    used"; line 68: server mode only when `PEERS` is set.
  - line 82: client mode = drop your `wg0.conf` into
    `/config/wg_confs/` — i.e., paste the Windscribe-generated WG config.
  - lines 98–106: the known gotcha when "routing via Wireguard from
    another container using the `service` option" — you lose local LAN/webUI
    access unless you add `PostUp`/`PreDown` route rules for RFC1918
    subnets (their example adds 192.168.0.0/16, 10.0.0.0/8, 172.16.0.0/12
    routes back).
  - lines 146–148: needs `cap_add: NET_ADMIN` (and optional `SYS_MODULE`).
- Compared to (a): lighter image, but you hand-roll the kill switch
  (iptables), DNS containment, healthcheck semantics, and restart behavior
  yourself. For exactly one container to gate, gluetun's opinionated
  firewall + health + DNS story is worth the extra image weight.
- Kernel-level `wg-quick` on the Unraid host is server/VPN-manager
  oriented (Unraid's built-in WireGuard is peer/server oriented and does
  not do per-container policy routing); no official Windscribe Unraid
  integration exists.

### (d) Unraid-specific approaches — rejected (no first-party path)

- No Windscribe-specific Community Applications template was found
  (repository searches for windscribe+unraid templates returned nothing
  relevant, 2026-09-15).
- gluetun itself is the Unraid-community pattern (gluetun README.md:46
  links the Unraid template discussion), which collapses (d) into (a).
- A br0/macvlan approach would give the browser its own LAN IP with
  **direct** egress — the opposite of the goal — and burns a DHCP lease.

## Decision

Option (a): gluetun sidecar with Windscribe WireGuard, browser attached
via `network_mode`, CDP exposed to `sofascore-sync` through gluetun's
`FIREWALL_INPUT_PORTS`. Concrete changes for this stack are in `plan.md`,
`implementation-checklist.md`, and `SUMMARY.md`.
