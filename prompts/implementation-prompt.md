# Implementation Prompt

Use this prompt with Codex, Claude Code, or another coding agent to start implementation in a target repository.

```text
You are implementing project-isolated browser automation for this repository.

Goal:
Add a project-local Browser Harness wrapper that uses a Chrome instance launched by Patchright inside a Docker container, so browser automation never attaches to or interrupts the user's real Chrome session.

Context:
- browser-harness controls Chromium-family browsers through CDP.
- browser-harness supports BU_NAME for daemon naming and BU_CDP_URL / BU_CDP_WS for explicit CDP endpoints.
- Patchright is a patched Playwright-compatible driver. For this project, use Patchright only to launch the persistent Chrome instance inside Docker.
- browser-harness should connect to the Chrome CDP endpoint exposed by that container.
- This is primarily for project isolation, not a guarantee of full Patchright stealth semantics.

Implement these files:

1. `.browser-harness.env.example`
   - Contains documented project settings:
     - BH_PROJECT_SLUG
     - BH_CONTAINER_NAME
     - BH_IMAGE
     - BH_HOST_PORT
     - BH_BU_NAME
     - BH_PROFILE_VOLUME
     - BH_DOWNLOADS_DIR
     - BH_DOCKER_EXTRA_ARGS
     - PATCHRIGHT_HEADLESS
     - PATCHRIGHT_EXTRA_ARGS
   - Do not commit a real `.browser-harness.env` with secrets or personal state.

2. `docker/browser-harness-patchright/Dockerfile`
   - Based on a Playwright Python Docker image for browser OS dependencies.
   - Installs Patchright.
   - Runs `patchright install chrome`.
   - Copies `launch_patchright_cdp.py`.
   - Runs as a non-root browser user when practical.
   - Exposes 9222.

3. `docker/browser-harness-patchright/launch_patchright_cdp.py`
   - Starts Xvfb when not headless.
   - Uses `patchright.sync_api.sync_playwright`.
   - Launches a persistent Chromium context with:
     - `user_data_dir=/data/profile`
     - `channel="chrome"`
     - `headless` from environment
     - `no_viewport=True`
     - `accept_downloads=True`
     - downloads path `/data/downloads`
     - args for `--remote-debugging-address=0.0.0.0` and `--remote-debugging-port=9222`
   - Waits for `http://127.0.0.1:9222/json/version`.
   - Prints readiness JSON.
   - Keeps process alive and handles SIGTERM/SIGINT cleanly.

4. `scripts/bh`
   - Shell wrapper with commands:
     - `run`: start/reuse the container, wait for CDP, then exec browser-harness with project env.
     - `url`: start/reuse and print CDP URL.
     - `status`: print container and project settings.
     - `reload`: run browser-harness `--reload` for this project daemon.
     - `stop`: stop the project daemon and Docker container.
     - `logs`: follow Docker logs.
     - `shell`: open shell in the container.
   - Loads `.browser-harness.env`.
   - Builds image if missing.
   - Creates the Docker profile volume if missing.
   - Binds CDP as `127.0.0.1:${BH_HOST_PORT}:9222`; never bind to public interfaces.
   - Adds `--add-host=host.docker.internal:host-gateway`.
   - Mounts project root to the same absolute path in the container.
   - Mounts downloads to `.browser-harness/downloads`.
   - Exports:
     - BU_NAME=${BH_BU_NAME}
     - BU_CDP_URL=http://127.0.0.1:${BH_HOST_PORT}
     - BH_HOME=${project_root}/.browser-harness/home
     - BH_RUNTIME_DIR=${project_root}/.browser-harness/runtime
     - BH_TMP_DIR=${project_root}/.browser-harness/tmp
   - If `.browser-harness.env` changes, reload the project daemon before use.

5. `.codex/skills/browser-harness/SKILL.md` or the equivalent agent skill path
   - Tell agents to use `./scripts/bh run`, never plain `browser-harness`, in this project.
   - Include short examples using `page_info()`, `new_tab()`, `wait_for_load()`, and `host.docker.internal`.

6. README/AGENTS documentation
   - Add a short "Browser automation" section explaining:
     - use `./scripts/bh run`;
     - each project has an isolated container/profile;
     - host dev servers are reachable as `host.docker.internal`;
     - use `./scripts/bh stop` to stop the container.

Acceptance tests:
- `./scripts/bh url` starts the container and returns `http://127.0.0.1:<port>`.
- `curl -fsS "$(./scripts/bh url)/json/version"` returns JSON containing `webSocketDebuggerUrl`.
- `./scripts/bh run <<'PY'\nprint(page_info())\nPY` works.
- `./scripts/bh run` can open `https://example.com`.
- The user's normal Chrome browser is not focused, navigated, or modified.
- Running two projects with different `.browser-harness.env` files creates two different containers and does not cross-control browsers.
- `./scripts/bh stop` stops the container and the project daemon.

Constraints:
- Do not use browser-harness cloud browsers for this implementation.
- Do not copy cookies from the user's real browser.
- Do not expose CDP publicly.
- Keep Chrome launch args minimal.
- Include clear comments for Docker Desktop vs native Linux settings.
- Be conservative with generated files; prefer templates and examples over personal config.

After implementing, show:
- changed files;
- exact smoke-test commands run;
- any failures and fixes;
- follow-up TODOs.
```
