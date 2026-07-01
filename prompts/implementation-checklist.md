# Implementation Checklist

## Files to add

- [ ] `.browser-harness.env.example`
- [ ] `docker/browser-harness-patchright/Dockerfile`
- [ ] `docker/browser-harness-patchright/launch_patchright_cdp.py`
- [ ] `scripts/bh`
- [ ] `.codex/skills/browser-harness/SKILL.md` or equivalent agent skill file
- [ ] README or AGENTS.md section
- [ ] `.gitignore` entries for `.browser-harness/` and `.browser-harness.env`

## Configuration

- [ ] Pick a unique `BH_PROJECT_SLUG`.
- [ ] Pick a unique `BH_CONTAINER_NAME`.
- [ ] Pick a unique `BH_HOST_PORT`.
- [ ] Pick a unique `BH_BU_NAME`.
- [ ] Pick a unique `BH_PROFILE_VOLUME`.
- [ ] Confirm Docker is available.
- [ ] Confirm `browser-harness` is installed on the host.

## Validation

- [ ] `./scripts/bh status`
- [ ] `./scripts/bh url`
- [ ] `curl -fsS "$(./scripts/bh url)/json/version"`
- [ ] `./scripts/bh run` with `page_info()`
- [ ] `./scripts/bh run` with navigation to `https://example.com`
- [ ] host dev server test through `host.docker.internal`
- [ ] download path test
- [ ] stop/restart persistence test
- [ ] two-project isolation test

## Security review

- [ ] CDP bound only to `127.0.0.1`.
- [ ] Browser profile is a named Docker volume, not a host Chrome profile.
- [ ] Project root mount is acceptable for intended tasks.
- [ ] `.browser-harness.env` is ignored if it may contain personal values.
- [ ] No secrets are baked into the Docker image.
- [ ] If enabling Chromium sandbox, a complete seccomp profile is used, not only the fragment.
