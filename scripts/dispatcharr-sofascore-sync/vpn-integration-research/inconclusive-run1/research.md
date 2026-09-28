# Research: single Docker container network route docker-compose (INCONCLUSIVE)

> ⚠ **This run is INCONCLUSIVE.** No fully evidence-backed conclusion was reached.
> The sections below describe what was searched and why proof remained incomplete — they are
> diagnostics, not verified findings. Do not present this as completed research.

## Goal

Best way to route a single Docker container's network egress through a Windscribe VPN account, on a docker-compose stack running on Unraid, without affecting the other containers on the same stack. Compare: (a) a VPN gateway/sidecar container (e.g. qmcgaw/gluetun, which has documented Windscribe WireGuard support) with the target container attached via network_mode: service:<vpn-container> or container:<vpn-container>, (b) Windscribe's own official Linux CLI running inside the target container itself, (c) a WireGuard config generated from Windscribe's account and used directly with a wireguard/wg-quick sidecar, (d) Unraid-specific approaches (Unraid Docker's built-in custom network / br0 macvlan patterns, or Windscribe-specific Unraid Community Applications templates). For each, find real docker-compose.yml examples on GitHub, note exact environment variables / config file formats needed, how healthchecks and DNS resolution behave through the tunnel, and known gotchas (kill-switch behavior if the VPN drops, port/health-check reachability from sibling containers, restart-order dependencies). Recommend the one best suited for gating exactly one lightweight headless-Chromium container's egress in an existing docker-compose project, while leaving all other services on that same external/upstream docker network completely unaffected.

## Status

- **Status:** `inconclusive`
- **Reasons:** missing_required_proof
- Candidates evaluated: 30
- Repositories selected: 3
- Evidence anchors: 41

## Summary

Run `run_single_docker_container_route_1789469480767` evaluated 30 candidate(s), selected
3 repository/repositories, and captured 41
evidence anchor(s), but did not satisfy the complete proof contract. This is
**not** proof that the answer is negative. Treat these artifacts as diagnostics,
not completed findings.

## What was searched

- [high_precision] "single" "Docker" — Find exact anchors for: Each named system/project has a real repository or official documentation.
- [high_precision] "route" "docker-compose" — Find exact anchors for: The central behavior/concept is documented or implemented in source material.
- [high_precision] "single" "route" — Find single material that mentions route.
- [high_precision] "single" "docker-compose" — Find single material that mentions docker-compose.
- [high_precision] "Docker" "route" — Find Docker material that mentions route.
- [high_precision] "Docker" "docker-compose" — Find Docker material that mentions docker-compose.
- [high_precision] "container" "route" — Find container material that mentions route.
- [high_precision] "container" "docker-compose" — Find container material that mentions docker-compose.
- [recall] "single Docker container network route docker-compose" "single" — Broad recall probe combining the feature phrase with single.
- [repo_search] single — Discover the official single repository/project by name/topic/readme.
- [repo_search] Docker — Discover the official Docker repository/project by name/topic/readme.
- [repo_search] container — Discover the official container repository/project by name/topic/readme.

## Open questions (unresolved)

- Which required proof role or named system is still unsupported by proved anchors?

## Recovery steps

- Inspect research.md "What was searched" to confirm probes targeted the right entities.
- If discovery missed the project, add the official repo/docs URL as an explicit hint or candidate.
- Provide structured hints (requiredConcepts, likelyFiles, proofRequirements) for novel domains.
- Re-run into a new output directory and compare; do not overwrite inconclusive artifacts.

## Diagnostics (warnings)

- Repo discovery returned 9 repo(s) across 3 repo_search probe(s).

## Skeptic notes

- An inconclusive run must never be presented as completed research.
- Re-run after fixing the highest-priority reason above before drawing any conclusion.
