# Plan: single Docker container network route docker-compose — INCONCLUSIVE (no evidence-backed plan)

> ⚠ No implementation plan is safe until the proof contract is complete. This
> file lists recovery actions, not steps to implement. Do not build from it.

## Objective

Best way to route a single Docker container's network egress through a Windscribe VPN account, on a docker-compose stack running on Unraid, without affecting the other containers on the same stack. Compare: (a) a VPN gateway/sidecar container (e.g. qmcgaw/gluetun, which has documented Windscribe WireGuard support) with the target container attached via network_mode: service:<vpn-container> or container:<vpn-container>, (b) Windscribe's own official Linux CLI running inside the target container itself, (c) a WireGuard config generated from Windscribe's account and used directly with a wireguard/wg-quick sidecar, (d) Unraid-specific approaches (Unraid Docker's built-in custom network / br0 macvlan patterns, or Windscribe-specific Unraid Community Applications templates). For each, find real docker-compose.yml examples on GitHub, note exact environment variables / config file formats needed, how healthchecks and DNS resolution behave through the tunnel, and known gotchas (kill-switch behavior if the VPN drops, port/health-check reachability from sibling containers, restart-order dependencies). Recommend the one best suited for gating exactly one lightweight headless-Chromium container's egress in an existing docker-compose project, while leaving all other services on that same external/upstream docker network completely unaffected.

## Status: inconclusive

Reasons: missing_required_proof

## Why there is no plan

The run selected 3 repository/repositories and captured
41 evidence anchor(s) (41 proved), but the proof contract
is still incomplete. Resolve the reasons above and re-run before implementing.

## Recovery actions

1. Inspect research.md "What was searched" to confirm probes targeted the right entities.
2. If discovery missed the project, add the official repo/docs URL as an explicit hint or candidate.
3. Provide structured hints (requiredConcepts, likelyFiles, proofRequirements) for novel domains.
4. Re-run into a new output directory and compare; do not overwrite inconclusive artifacts.

## Probes attempted

- [high_precision] "single" "Docker"
- [high_precision] "route" "docker-compose"
- [high_precision] "single" "route"
- [high_precision] "single" "docker-compose"
- [high_precision] "Docker" "route"
- [high_precision] "Docker" "docker-compose"
- [high_precision] "container" "route"
- [high_precision] "container" "docker-compose"
- [recall] "single Docker container network route docker-compose" "single"
- [repo_search] single
- [repo_search] Docker
- [repo_search] container

## References

- jenkinsci/docker (partially supported; do not implement yet)
- nextcloud/docker (partially supported; do not implement yet)
- docker-library/docker (partially supported; do not implement yet)
