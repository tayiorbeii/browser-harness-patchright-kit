# Browser Harness + Patchright Container Project Kit

Last reviewed: 2026-07-24.

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

The same container also backs [Oracle](https://github.com/steipete/oracle) second-opinion consults — see [Oracle consults](#oracle-consults).

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
  08-https-localhost-integration.md
  09-oracle-integration.md

prompts/
  implementation-prompt.md
  implementation-checklist.md

templates/
  .browser-harness.env.template
  .gitignore.additions
  .oracle/config.json
  docker-compose.browser-harness.yml
  docker/browser-harness-patchright/Dockerfile
  docker/browser-harness-patchright/launch_patchright_cdp.py
  scripts/bh
  scripts/oracle
  skills/browser-harness/SKILL.md
  seccomp_userns_allow.fragment.json
```

## Repository maintenance invariants

The operational files at the repository root are the canonical kit implementation. Files under `templates/` are explicit starter snapshots for copying into target repositories; they are not generated and are never silently overwritten. `scripts/check_repository_integrity.py` declares every live/template pair and checks both content and its required regular-file mode (`100644` or `100755`). Seven pairs are exact. The environment pair permits only these full-line identity substitutions:

- `BH_PROJECT_SLUG=browser_harness_patchright_project_kit` → `BH_PROJECT_SLUG=my-app`
- `BH_CONTAINER_NAME=bh-browser_harness_patchright_project_kit` → `BH_CONTAINER_NAME=bh-my-app`
- `BH_BU_NAME=browser_harness_patchright_project_kit` → `BH_BU_NAME=my-app`
- `BH_PROFILE_VOLUME=bh-browser_harness_patchright_project_kit-profile` → `BH_PROFILE_VOLUME=bh-my-app-profile`

Run the Docker-free integrity acceptance suite with:

```bash
./scripts/test-repository-integrity
```

The pre-commit hook runs the same checker against staged mirror blobs/modes and every path in Git's staged index. It also requires the staged hook, checker, and acceptance-test bytes/modes to match the worktree copies being run. This catches partial infrastructure or mirror staging, force-added ignored files, and forbidden artifacts already present in the index; staged deletions are naturally absent and remain allowed. Enable the tracked hook with `git config core.hooksPath .githooks`.

## Requirements

- Docker Desktop, Colima, or a native Linux Docker daemon, running and reachable by your user.
- `python3`, `curl`, and `bash` on the host (the wrapper uses them for readiness probes and CDP parsing).
- `browser-harness` on `$PATH` for `./scripts/bh run`.
- Optional: [`oracle`](https://github.com/steipete/oracle) (Node 24+) for consults — `npm install -g @steipete/oracle` or `brew install steipete/tap/oracle`.

Roughly 2 GB of free memory for the container; headed Chrome under Xvfb is the default.

## Fast implementation path

Copy the template files into the project root:

```bash
cp templates/.browser-harness.env.template .browser-harness.env
mkdir -p docker/browser-harness-patchright scripts .codex/skills/browser-harness .oracle
cp templates/docker/browser-harness-patchright/Dockerfile docker/browser-harness-patchright/Dockerfile
cp templates/docker/browser-harness-patchright/launch_patchright_cdp.py docker/browser-harness-patchright/launch_patchright_cdp.py
cp templates/scripts/bh scripts/bh
cp templates/scripts/oracle scripts/oracle          # optional, for Oracle consults
cp templates/.oracle/config.json .oracle/config.json # optional, for Oracle consults
cp templates/skills/browser-harness/SKILL.md .codex/skills/browser-harness/SKILL.md
chmod +x scripts/bh scripts/oracle
```

Edit `.browser-harness.env` so each project has unique values:

```bash
BH_PROJECT_SLUG=my-app
BH_CONTAINER_NAME=bh-my-app
BH_HOST_PORT=19322
BH_BU_NAME=my-app
BH_PROFILE_VOLUME=bh-my-app-profile
```

Then run the focused image/browser-harness smoke test:

```bash
./scripts/test-browser-harness-connection
```

Or run the wrapper manually:

```bash
./scripts/bh run -c $'new_tab("https://example.com")\nwait_for_load()\nprint(page_info())'
```

## Building and running the container

### What the image contains

`docker/browser-harness-patchright/Dockerfile` starts from `python:3.12-bookworm` and installs Debian's system Chromium (portable across amd64 and arm64), `xvfb` for a headed display, `x11vnc` for optional interactive access, and `patchright` pinned by the `PATCHRIGHT_VERSION` build arg. `launch_patchright_cdp.py` is the container entrypoint: it launches a persistent Chrome context against `/data/profile`, waits for CDP, and publishes it on the container interface through a small TCP proxy.

### Building

You normally never build by hand. `./scripts/bh url` builds the image if the tag in `BH_IMAGE` is not present locally, then creates and starts the container:

```bash
./scripts/bh url
```

Build explicitly when you want to see the output, or after editing the Dockerfile or launcher:

```bash
docker build -t browser-harness-patchright:1.61.1 docker/browser-harness-patchright
```

**The wrapper only builds when the tag is absent.** After changing the Dockerfile or `launch_patchright_cdp.py`, either bump `BH_IMAGE` in `.browser-harness.env` to a new tag, or remove the existing image first:

```bash
./scripts/bh stop
docker rmi browser-harness-patchright:1.61.1
./scripts/bh url                # rebuilds, then recreates the container
```

On Apple Silicon, leave `BH_DOCKER_PLATFORM` unset — the image's system-Chromium default works natively. Set `BH_DOCKER_PLATFORM=linux/amd64` only when building a Chrome-channel variant on native Linux amd64.

### How the container is created

`./scripts/bh url` runs the equivalent of:

```bash
docker run -d \
  --name "$BH_CONTAINER_NAME" \
  --init \
  --shm-size=2g \
  -p "127.0.0.1:${BH_HOST_PORT}:9222" \
  --add-host=host.docker.internal:host-gateway \
  -v "${BH_PROFILE_VOLUME}:/data/profile" \
  -v "<downloads dir>:/data/downloads" \
  -v "<project root>:<project root>:rw" \
  "$BH_IMAGE"
```

Notes on each piece:

- **`-p 127.0.0.1:...`** — CDP grants full control of the browser. It is published on loopback only, never `0.0.0.0`.
- **`--init`** — reaps Chrome/Xvfb children correctly.
- **`--shm-size=2g`** — headed Chrome crashes on Docker's default 64 MB `/dev/shm`. Native Linux may prefer `BH_DOCKER_EXTRA_ARGS='--ipc=host'`.
- **profile volume** — a Docker named volume, never a bind mount of a real browser profile. It survives `stop`, `reload`, and container recreation; it is destroyed only by `docker volume rm`.
- **project bind mount** — mounted at the *same absolute path* inside the container, so file paths in harness scripts resolve identically on both sides.

The container is recreated automatically whenever a config value that affects `docker run` changes; `./scripts/bh` stores a config signature as a container label and compares it on each launch.

### Lifecycle commands

| Command | Effect |
| --- | --- |
| `./scripts/bh status` | Print project settings, CDP URL, and container state. Never starts anything. |
| `./scripts/bh url` | Build/start/reuse the container, wait for CDP, print the loopback CDP URL. |
| `./scripts/bh run -c '<python>'` | Run browser-harness code against the container. |
| `./scripts/bh logs` | Follow container logs. |
| `./scripts/bh shell` | Bash shell inside the container. |
| `./scripts/bh reload` | Remove and recreate the container; keeps the profile volume. |
| `./scripts/bh stop` | Stop the container; keeps the profile volume. |
| `./scripts/bh purge` | **Destructive.** Delete the container, the profile volume, and local runtime state. |

### Purging browser state

The container profile accumulates real browsing data — cookies, history, localStorage, and any logins you completed inside it. It lives in a Docker named volume and survives `stop`, `reload`, and container recreation. `.browser-harness/` on the host likewise accumulates downloads, screenshots, and any scratch scripts a session wrote.

Before sharing a checkout, handing the repo to someone else, or resetting a profile that picked up personal data:

```bash
./scripts/bh purge          # prompts for the project slug to confirm
./scripts/bh purge --yes    # non-interactive
```

This removes the container, the profile volume, and `.browser-harness/`. The Docker image is kept; the next `./scripts/bh url` starts from a clean profile. Nothing under `.browser-harness/` is tracked by git, but it is still real data on your disk — purge is what actually gets rid of it.

### Using the browser

Always go through the wrapper — never plain `browser-harness`:

```bash
./scripts/bh run -c 'print(page_info())'
./scripts/bh run -c $'reuse_tab("https://example.com", close_others=True)\nwait_for_load()\nprint(page_info())'
./scripts/bh run -c $'screenshot("/data/downloads/page.png")'
```

One work tab is the default. Start a task with `reuse_tab(url, close_others=True)`, navigate later with `goto_url(url)`, and reserve `new_tab()` for genuinely needing two pages at once. Bulk tab cleanup is safe here *because* the container is project-isolated — never do it against a real browser.

Host services are not `localhost` from inside the container. Use the gateway:

```bash
./scripts/bh run -c 'reuse_tab("http://host.docker.internal:3000", close_others=True)'
```

Downloads land in `BH_DOWNLOADS_DIR` on the host (`/data/downloads` in the container).

### Optional: interactive access to the container display

Chrome runs headed on a virtual display with no window on your desktop. For one-time interactive work — signing in to a service, clearing a challenge — expose the display over loopback VNC:

```bash
# in .browser-harness.env
PATCHRIGHT_HEADLESS=0
XVFB_SCREEN=1440x900x24
PATCHRIGHT_EXTRA_ARGS=--window-size=1400,840
BH_VNC_PORT=15900
```

```bash
./scripts/bh reload
./scripts/bh status | grep vnc     # vnc://127.0.0.1:15900
```

Connect with any VNC client (macOS: open that URL in Screen Sharing). Requires headed Chrome; the wrapper refuses `BH_VNC_PORT` when `PATCHRIGHT_HEADLESS` is not `0`. The image must include `x11vnc` — rebuild if yours predates it. For clients that require password authentication, set `BH_VNC_PASSWORD_FILE` to an absolute host path containing an x11vnc `-storepasswd` file; the wrapper mounts it read-only and advertises VNCAuth. **Unset `BH_VNC_PORT` when finished**.

## Oracle consults

[Oracle](https://github.com/steipete/oracle) ([npm](https://www.npmjs.com/package/@steipete/oracle)) sends a prompt plus files to a second-opinion model. Its browser engine drives a signed-in ChatGPT session over CDP, so a subscription substitutes for an API key — but by default it launches *your* Chrome and reads cookies from *your* profile. `scripts/oracle` routes it into this project's container instead, using Oracle's `--remote-chrome` mode, which attaches to a running browser and never touches a local profile.

```bash
./scripts/oracle status                        # wrapper, container target, oracle readiness
./scripts/oracle check                         # is the container profile signed in to ChatGPT?
./scripts/oracle plan -p "Review this design"  # dry run; prints Oracle's browser control plan
./scripts/oracle run -p "Review this design" --file "docs/**/*.md"
```

Setup:

1. Install Oracle (`npm install -g @steipete/oracle`, Node 24+).
2. Keep `.oracle/config.json` in the project — it pins workflow defaults and forbids Oracle from touching a local Chrome profile. Optionally set `BH_ORACLE_MODEL` / `BH_ORACLE_EXTRA_ARGS` in `.browser-harness.env`.
3. Sign the **container** profile into ChatGPT once, over VNC (see above), via `./scripts/oracle login`. Remote-chrome mode does no cookie sync, so an unauthenticated container profile means an unauthenticated consult. Never import cookies from your real browser.

Two things to know: Oracle owns its own tab during a consult, so don't run `close_others=True` while one is in flight; and `browser.remoteChrome` is not a config key in Oracle, which is the reason the wrapper appends `--remote-chrome` per run.

API-mode consults (`oracle --engine api ...`) need no browser and can be run directly.

Full detail, flag rejections, and failure modes: [`docs/09-oracle-integration.md`](docs/09-oracle-integration.md).

## Verifying an installation

Run these from the project root.

### 1. Confirm the wrapper configuration

```bash
./scripts/bh status
```

Expected fields (values reflect your `.browser-harness.env`):

```text
project_root=<your project root>
project_slug=my-app
container=bh-my-app
cdp_url=http://127.0.0.1:19322
bu_name=my-app
docker_available=yes
```

`running=no` is acceptable before the first launch; `./scripts/bh url` starts the container if needed.

### 2. Start or verify the container/CDP endpoint

```bash
./scripts/bh url
curl -fsS "$(./scripts/bh url)/json/version" | python3 -m json.tool
```

Expected output includes a loopback-only CDP URL and a browser WebSocket URL:

```text
http://127.0.0.1:19322
```

```json
{
  "Browser": "Chrome/...",
  "Protocol-Version": "1.3",
  "webSocketDebuggerUrl": "ws://127.0.0.1:19322/devtools/browser/..."
}
```

If `curl` is unavailable or blocked by the agent harness, use Python for the same check:

```bash
python3 - <<'PY'
import json, subprocess, urllib.request

cdp_url = subprocess.check_output(["./scripts/bh", "url"], text=True).strip()
with urllib.request.urlopen(cdp_url + "/json/version", timeout=10) as r:
    data = json.load(r)

print(json.dumps(data, indent=2, sort_keys=True))
assert data.get("webSocketDebuggerUrl"), "missing webSocketDebuggerUrl"
print("webSocketDebuggerUrl OK")
PY
```

### 3. Verify browser-harness connects through the wrapper

```bash
./scripts/bh run -c 'print(page_info())'
```

Expected output resembles:

```text
{'url': 'about:blank', 'title': '', 'w': ..., 'h': ..., ...}
```

Then verify navigation:

```bash
./scripts/bh run -c $'new_tab("https://example.com")\nwait_for_load()\nprint(page_info())'
```

Expected output resembles:

```text
{'url': 'https://example.com/', 'title': '🟢 Example Domain', ...}
```

### 4. Verify project isolation environment

```bash
./scripts/bh run -c $'import os\nprint("BU_NAME=", os.environ.get("BU_NAME"))\nprint("BU_CDP_URL=", os.environ.get("BU_CDP_URL"))\nprint(page_info())'
```

Expected values match `BH_BU_NAME` and the loopback CDP URL:

```text
BU_NAME= my-app
BU_CDP_URL= http://127.0.0.1:19322
```

These values confirm the agent is using the project browser-harness namespace and the container CDP endpoint, not the user's normal Chrome.

### 5. Run the full smoke test

```bash
./scripts/test-browser-harness-connection
```

Expected final line:

```text
PASS: browser image CDP endpoint and browser-harness wrapper connection verified.
```

To leave the container running for inspection:

```bash
./scripts/test-browser-harness-connection --no-stop
```

To stop the project browser container while preserving the Chrome profile volume:

```bash
./scripts/bh stop
```

## Pi/agent skill discovery

Pi discovers skills at startup. To make this agent discover Claude Code skills, the pi settings should include `~/.claude/skills`, for example:

```json
{
  "skills": [
    "~/.claude/skills"
  ]
}
```

After changing skill settings, start a new pi session from this project root. If automatic discovery is not available, launch pi with the skill explicitly:

```bash
pi --skill ~/.claude/skills/browser-harness
```

The loaded `browser-harness` skill should direct this project to use:

```bash
./scripts/bh run -c '<browser-harness python code>'
```

It should not run plain `browser-harness` in this repository unless it has first run `./scripts/bh url` and explicitly set the project environment:

```bash
BU_NAME=<BH_BU_NAME>
BU_CDP_URL=http://127.0.0.1:<BH_HOST_PORT>
```

## Troubleshooting

- **Skill not found in pi**: restart pi after adding `~/.claude/skills`, or launch with `pi --skill ~/.claude/skills/browser-harness`.
- **Container not running**: run `./scripts/bh url` or `./scripts/bh reload`.
- **CDP endpoint not ready**: run `./scripts/bh logs`, fix the reported Docker/Chrome issue, then retry `./scripts/bh reload`.
- **Port collision**: change `BH_HOST_PORT`, then `./scripts/bh stop && ./scripts/bh reload`. If an old container owns the mapping, `docker rm -f "$BH_CONTAINER_NAME"` first.
- **Chrome crashes before CDP is ready**: usually memory or `/dev/shm`. Keep or raise `BH_DOCKER_EXTRA_ARGS='--shm-size=2g'`; on native Linux consider `--ipc=host`.
- **Dockerfile changes not taking effect**: the wrapper only builds when the image tag is absent. Bump `BH_IMAGE` or `docker rmi` the tag.
- **Browser-harness appears to attach to the wrong browser**: verify `BU_NAME` and `BU_CDP_URL` with the environment check above and ensure commands use `./scripts/bh run -c`.
- **Do not use heredoc/stdin examples for this wrapper**; `browser-harness` expects code through `-c`.

## Source notes

The browser-harness repository documents CDP-based browser control, `BU_NAME`, `BU_CDP_URL`, `BU_CDP_WS`, and `--reload`. Patchright's Python docs describe it as a Chromium-only Playwright replacement and recommend launching a persistent Chrome context with `channel="chrome"`, `headless=False`, and `no_viewport=True`. Chrome's own security guidance says remote debugging should use a non-default user data dir. Playwright's Docker documentation recommends `--init`, gives Chromium IPC/sandbox guidance, and shows the host-gateway pattern for reaching host services from inside a browser container. Oracle's `--remote-chrome` mode is documented at [steipete/oracle](https://github.com/steipete/oracle).

See the planning docs for implementation detail and cautions.

## HTTPS localhost integrations

Projects that must preserve a localhost HTTPS origin may opt into dedicated metadata and Chromium resolver configuration:

```bash
BH_BROWSER_ORIGIN=https://localhost:3443
BH_HOST_RESOLVER_RULES='MAP localhost host.docker.internal'
```

`BH_BROWSER_ORIGIN` is status metadata only; it never navigates Chrome or starts an app. `BH_HOST_RESOLVER_RULES` becomes exactly one harness-owned Chromium argument. Do not also place `--host-resolver-rules` in `PATCHRIGHT_EXTRA_ARGS`. Broad `--ignore-certificate-errors` is forbidden; project-owned narrow SPKI trust remains allowed.

Run the focused contract and mirror check with:

```bash
./scripts/test-https-localhost-integration
```

Application-specific startup, operational constraints, evidence, rollback, and remaining native-Linux/OAuth acceptance work are recorded in `docs/08-https-localhost-integration.md`.

## Browser automation

For browser automation, use `./scripts/bh run`, never plain `browser-harness`. The wrapper uses the project's isolated Patchright Chrome container and will not attach to the user's normal browser.

Full agent rules live in `.codex/skills/browser-harness/SKILL.md`; copy or adapt the skill from `templates/skills/browser-harness/SKILL.md` when installing this kit. Use `.browser-harness.env.example` for configuration values and keep any personal `.browser-harness.env` uncommitted.

Configuration notes:

- Docker Desktop: keep Chrome CDP published on loopback only, for example `127.0.0.1:${BH_HOST_PORT}:9222`, and use the Docker Desktop host gateway pattern when the browser must reach host services.
- Native Linux: keep the same loopback-only CDP binding and prefer the minimal Docker options from the templates; use documented shared-memory/sandbox settings (for example `--ipc=host` or a complete seccomp profile) only when the project documents a specific need. Do not use host networking for CDP.
- Do not use browser-harness cloud browsers, do not copy cookies from the user's real browser, and keep generated files to templates/examples rather than personal configuration.
