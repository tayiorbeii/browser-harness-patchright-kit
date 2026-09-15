# SUMMARY — concrete recommendation for this stack

**Recommendation: route `sofascore-browser` through a gluetun VPN gateway
sidecar using Windscribe WireGuard, attached via
`network_mode: "service:sofascore-vpn"`. Confidence: high on the mechanism
(official gluetun wiki pattern, compose-spec semantics, widely-used
production examples), medium-high on end-to-end for this exact stack
(Windscribe WG credential generation + region entitlements are manual
account-side steps; the gluetun repo has moved, so pin the image tag
fresh at implementation time).**

Why this one:

1. **Only the browser moves.** `network_mode: "service:X"` shares the
   gateway's network namespace; the compose spec explicitly forbids
   combining it with `networks:`, so the browser structurally leaves the
   shared network as a routed member while every other service
   (rive-resolver, dispatcharr*, tuliprox, sofascore-sync) keeps direct
   egress — exactly the isolation Taylor asked for.
2. **Windscribe is first-class in gluetun** — documented WireGuard env
   contract (`VPN_SERVICE_PROVIDER=windscribe`, `VPN_TYPE=wireguard`,
   `WIREGUARD_PRIVATE_KEY/ADDRESSES/PRESHARED_KEY`, `SERVER_REGIONS`).
   The alternatives don't compete: the Windscribe CLI has no official
   image and only stale community wrappers (30★, 2022); a plain WG sidecar
   works but leaves kill-switch/DNS/health as DIY; nothing
   Unraid-specific exists (gluetun IS the Unraid-community pattern).
3. **Operational hard parts are solved for us**: default-on firewall
   kill-switch (if the tunnel drops, traffic stops rather than leaking
   the blocked IP), tunnel-local DNS (Chromium's lookups follow the
   tunnel), built-in health server for `depends_on: service_healthy`
   gating, and `HEALTH_RESTART_VPN` self-healing.

The three concrete mechanics that matter for THIS stack (all covered in
`plan.md` + `implementation-checklist.md`):

- **CDP stays reachable**: gluetun takes over `172.30.91.14` on the
  `upstream` network (the IP sofascore-sync already targets), and
  `FIREWALL_INPUT_PORTS=9222` lets the sync container's CDP calls through
  the gateway's firewall into the shared netns. The browser's own
  heartbeat healthcheck (127.0.0.1:9222) keeps working unchanged.
- **Everything else is untouched**: one new service, one service's
  networking edited, zero changes to resolver/dispatcharr/tuliprox/sync —
  their `upstream` memberships and direct egress are unaffected.
- **Dry-run first**: the follow-up task should keep
  `SOFASCORE_SYNC_APPLY=0` until the tunnel proves out — the success gate
  is simple: page-context fetch to `api.sofascore.com` from inside the
  browser returns 200 instead of 403, and a full sync cycle logs a real
  `tracked=N` with `marked_ended=0`.

Rejected alternatives in one line each: (b) Windscribe CLI in-container =
closed binary, unmaintained wrappers, no health/kill-switch story;
(c) plain WireGuard sidecar = fine but hand-rolls exactly the parts
(firewall, DNS, healthcheck) that make (a) safe; (d) Unraid-specific =
nothing first-party exists, macvlan would bypass the VPN (wrong
direction).

Artifacts: `research.md` (full comparison + citations),
`evidence.json` (claim → repo/commit/path/line ledger),
`plan.md` (target compose shape + verification),
`implementation-checklist.md` (step-by-step for the follow-up task),
`inconclusive-run1/` (the automated orchestrator run's diagnostics,
preserved for audit).
