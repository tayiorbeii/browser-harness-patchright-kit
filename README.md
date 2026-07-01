# Browser Harness + Patchright Container Project Kit

Last reviewed: 2026-06-30.

This kit is for adding **project-isolated browser-harness automation** to a codebase without letting the agent take over the logged-in user's normal browser session.

The design is:

1. Build one reusable Docker image that has Patchright and Chrome.
2. Run one named container per project.
3. Give each project its own persistent Chrome profile volume.
4. Expose the container Chrome DevTools endpoint only on host loopback.
5. Wrap `browser-harness` with a project script that:
   - checks whether the project's container is running;
   - starts it if needed;
   - waits for Chrome CDP to be ready;
   - exports `BU_NAME` and `BU_CDP_URL`;
   - invokes `browser-harness` against the isolated container browser.

## Contents

```text
docs/
  01-requirements.md
  02-architecture.md
  03-configuration-model.md
  04-implementation-plan.md
  05-security-and-operations.md
  06-testing-and-acceptance.md
  07-risks-and-open-questions.md

prompts/
  implementation-prompt.md
  implementation-checklist.md

templates/
  .browser-harness.env.template
  docker-compose.browser-harness.yml
  docker/browser-harness-patchright/Dockerfile
  docker/browser-harness-patchright/launch_patchright_cdp.py
  scripts/bh
  skills/browser-harness/SKILL.md
  seccomp_profile.json
```

## Fast implementation path

Copy the template files into the project root:

```bash
cp templates/.browser-harness.env.template .browser-harness.env
mkdir -p docker/browser-harness-patchright scripts .codex/skills/browser-harness
cp templates/docker/browser-harness-patchright/Dockerfile docker/browser-harness-patchright/Dockerfile
cp templates/docker/browser-harness-patchright/launch_patchright_cdp.py docker/browser-harness-patchright/launch_patchright_cdp.py
cp templates/scripts/bh scripts/bh
cp templates/skills/browser-harness/SKILL.md .codex/skills/browser-harness/SKILL.md
chmod +x scripts/bh
```

Edit `.browser-harness.env` so each project has unique values:

```bash
BH_PROJECT_SLUG=my-app
BH_CONTAINER_NAME=bh-my-app
BH_HOST_PORT=19322
BH_BU_NAME=my-app
BH_PROFILE_VOLUME=bh-my-app-profile
```

Then smoke test:

```bash
./scripts/bh run <<'PY'
print(page_info())
new_tab("https://example.com")
wait_for_load()
print(page_info())
PY
```

## Source notes

The browser-harness repository documents CDP-based browser control, `BU_NAME`, `BU_CDP_URL`, `BU_CDP_WS`, and `--reload`. Patchright's Python docs describe it as a Chromium-only Playwright replacement and recommend launching a persistent Chrome context with `channel="chrome"`, `headless=False`, and `no_viewport=True`. Chrome's own security guidance says remote debugging should use a non-default user data dir. Playwright's Docker documentation recommends `--init`, gives Chromium IPC/sandbox guidance, and shows the host-gateway pattern for reaching host services from inside a browser container.

See the planning docs for implementation detail and cautions.

## Browser automation

For browser automation, use `./scripts/bh run`, never plain `browser-harness`. The wrapper uses the project's isolated Patchright Chrome container and will not attach to the user's normal browser.

Full agent rules live in `.codex/skills/browser-harness/SKILL.md`; copy or adapt the skill from `templates/skills/browser-harness/SKILL.md` when installing this kit. Use `.browser-harness.env.example` for configuration values and keep any personal `.browser-harness.env` uncommitted.

Configuration notes:

- Docker Desktop: keep Chrome CDP published on loopback only, for example `127.0.0.1:${BH_HOST_PORT}:9222`, and use the Docker Desktop host gateway pattern when the browser must reach host services.
- Native Linux: keep the same loopback-only CDP binding and prefer the minimal Docker options from the templates; use documented shared-memory/sandbox settings (for example `--ipc=host` or a complete seccomp profile) only when the project documents a specific need. Do not use host networking for CDP.
- Do not use browser-harness cloud browsers, do not copy cookies from the user's real browser, and keep generated files to templates/examples rather than personal configuration.
