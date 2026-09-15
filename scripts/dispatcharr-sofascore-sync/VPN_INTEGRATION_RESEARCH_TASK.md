# Task: research the best way to route sofascore-browser's egress through Windscribe VPN

## Context

`scripts/dispatcharr-sofascore-sync/README.md`, section "Deploy result,
2026-09-15" -- read it first. Summary: SofaScore/Fastly returns a clean
edge-level 403 (no bot-challenge markers) to blackpearl.local's public IP
(CenturyLink/AS209, Boise ID) for both the homepage and the API, over both
IPv4 and IPv6. This blocks the native `sofascore-sync` /
`sofascore-browser` pair (already deployed, healthy, currently in
dry-run) from ever writing real overrides from Unraid.

Taylor has a **Windscribe VPN** account and wants to route ONLY the
`sofascore-browser` container's egress through it -- not the rest of the
`unified-iptv` stack (`rive-resolver`, `dispatcharr`, `tuliprox`, etc. must
keep their current direct egress; those services resolve upstream sports
streams that are sometimes host-allowlisted, e.g.
`RIVE_UPSTREAM_ALLOWED_HOSTS`/`DISPATCHARR_UPSTREAM_ALLOWED_HOSTS` in
`.env.unified` on blackpearl.local, and routing them all through a VPN
could break that or trip rate limits elsewhere).

## What to do

Use the **research-orchestrator** project at
`/Users/taylor/Documents/Projects/00-in-progress/research_orchestrator_planning_kit`
to research this, live (not mock mode -- we need real, current, grounded
answers with evidence, not the deterministic example-data mock mode).

The octocode CLI is already authenticated in this environment (`npx -y
octocode@latest auth status` shows `Authenticated as tayiorbeii`,
`Token: present`, `Source: gh cli`) -- credentials live at
`~/.octocode/credentials.json`. research-orchestrator's live octocode
bridge (`bridges/octocode-mcp.ts`) spawns its own MCP server subprocess
per `.env` config (see `.env.example` -- default
`RESEARCH_OCTOCODE_COMMAND=npx`, `RESEARCH_OCTOCODE_ARGS=["-y",
"@octocodeai/mcp@latest"]`). That default package name may or may not
match what's actually authenticated/available in this environment (which
uses the `octocode` CLI package, not necessarily `@octocodeai/mcp`) --
you may need to adjust `RESEARCH_OCTOCODE_ARGS` to spawn the right
package/subcommand (check `npx -y octocode@latest --help` for an
MCP-server-mode subcommand, e.g. something under `install`/`context`, and
wire that into a local `.env` copied from `.env.example`).

Steps:

1. `cd /Users/taylor/Documents/Projects/00-in-progress/research_orchestrator_planning_kit`
2. Confirm/create `node_modules` (`npm install` if missing -- check first,
   it may already be present) and confirm the project builds/runs
   (`npx tsx src/cli.ts --help`).
3. Copy `.env.example` to `.env` and wire up the octocode bridge to
   actually work in this environment (see above). Verify with a trivial
   smoke run first if the project has one (check `npm run smoke:octocode`
   / `scripts/smoke-octocode-bridge.ts`) before spending a full `find` run
   on a broken bridge.
4. Run the real research query, live mode:
   ```
   npx tsx src/cli.ts find      --goal "Best way to route a single Docker container's network egress through a Windscribe VPN account, on a docker-compose stack running on Unraid, without affecting the other containers on the same stack. Compare: (a) a VPN gateway/sidecar container (e.g. qmcgaw/gluetun, which has documented Windscribe WireGuard support) with the target container attached via network_mode: service:<vpn-container> or container:<vpn-container>, (b) Windscribe's own official Linux CLI running inside the target container itself, (c) a WireGuard config generated from Windscribe's account and used directly with a wireguard/wg-quick sidecar, (d) Unraid-specific approaches (Unraid Docker's built-in custom network / br0 macvlan patterns, or Windscribe-specific Unraid Community Applications templates). For each, find real docker-compose.yml examples on GitHub, note exact environment variables / config file formats needed, how healthchecks and DNS resolution behave through the tunnel, and known gotchas (kill-switch behavior if the VPN drops, port/health-check reachability from sibling containers, restart-order dependencies). Recommend the one best suited for gating exactly one lightweight headless-Chromium container's egress in an existing docker-compose project, while leaving all other services on that same external/upstream docker network completely unaffected."      --mode octocode      --max-candidates 30      --out /Users/taylor/Documents/Projects/00-in-progress/browser_harness_patchright_project_kit/scripts/dispatcharr-sofascore-sync/vpn-integration-research
   ```
   If octocode mode genuinely cannot be made to work after a reasonable
   troubleshooting effort (document exactly what you tried and why it
   failed), fall back to doing the equivalent research directly yourself
   via the `octocode-research` skill / `npx -y octocode@latest search ...`
   CLI (already authenticated) and hand-write the same four output
   artifacts research-orchestrator would have produced
   (`research.md`, `plan.md`, `evidence.json`,
   `implementation-checklist.md`) into that same output directory, with
   real citations (repo/file/line) for every claim -- do not fabricate
   evidence or present a guess as a grounded finding.
5. Read the resulting `research.md` / `plan.md` yourself once produced and
   sanity-check: does the recommendation actually address "only this one
   container's egress, others untouched, on Unraid, with Windscribe
   specifically"? If the tool's output drifted generic, add a short
   `SUMMARY.md` in the same output directory in your own words with the
   concrete recommendation and the exact docker-compose changes needed for
   *this* stack (service name `sofascore-browser`, network `upstream`,
   compose files `docker-compose.unified.phase1.candidate.yml` +
   `docker-compose.unified.operator-access.yml` on blackpearl.local).
6. **Do not deploy or change anything on blackpearl.local in this task** --
   research only. A follow-up task will implement whatever this
   recommends, after review.
7. Report back: which mode you ended up running in (octocode live, or the
   manual fallback), the path to the output artifacts, and a 5-10 line
   summary of the recommended approach with your confidence level. End
   your final message with "VPN RESEARCH DONE" or "VPN RESEARCH BLOCKED:
   <reason>".
