# Research Recovery Checklist: single Docker container network route docker-compose

> ⚠ Run status: **inconclusive** (missing_required_proof).
> No implementation work should proceed from the previous run. Resolve the
> items below, then re-run research before building anything.

## Confirm the research specification
- [ ] Verify the normalized feature/key terms captured the real subject (see research.md "What was searched").
- [ ] If key entities were dropped, add structured `hints` (requiredConcepts, likelyFiles, proofRequirements).
- [ ] Confirm the goal was classified correctly (research/migration vs. application build).

## Verify the evidence provider
- [ ] Confirm the Octocode bridge is configured (RESEARCH_OCTOCODE_BRIDGE, transport, auth).
- [ ] Distinguish a transport/auth failure from a genuine empty result (see Diagnostics).
- [ ] Check rate limits / quotas if searches returned nothing.
- [ ] Re-run with RESEARCH_OCTOCODE_DEBUG=1 and inspect generated probes + provider responses.

## Broaden discovery
- [ ] Run each repo_search probe individually against ghSearchRepos and inspect results.
- [ ] For migration goals, add the source and target project repos/docs as explicit candidates.
- [ ] Add official documentation URLs as explicit hints if discovery keeps missing the project.

## Before re-running
- [ ] Back up or version the previous (inconclusive) artifacts for auditability.
- [ ] Re-run into a new output directory; do not overwrite until evidence is real.
- [ ] Only proceed to an implementation checklist once evidence anchors exist.
