# 09. Oracle Integration

[steipete/oracle](https://github.com/steipete/oracle) is a CLI that sends a bundle of prompt + files to a second-opinion model. It has two engines:

- **API engine** — talks to OpenAI/Gemini/Anthropic/Azure with API keys. No browser involved; nothing in this document applies.
- **Browser engine** — drives a signed-in ChatGPT (or Gemini) web session over CDP, so a ChatGPT subscription substitutes for an API key.

The browser engine is the part that concerns this kit. By default Oracle launches or attaches to the operator's real Chrome and copies cookies out of their profile, which is exactly what this project forbids. This integration routes it into the project's isolated Patchright container instead.

## How the attachment works

Oracle's `--remote-chrome <host:port>` mode connects to an already-running browser over CDP and takes a different code path (`runRemoteBrowserMode`) from its local-launch flow:

- It never launches Chrome, never reads a local Chrome profile, and never syncs cookies. The remote session's own login is used as-is.
- Local-Chrome flags are ignored in this mode: `--browser-headless`, `--browser-hide-window`, `--browser-keep-browser`, and `--browser-chrome-path`. Oracle logs a note when they are passed.
- It acquires a tab lease, opens its own tab, and closes that tab when the run finishes. Incomplete runs leave the tab open so `oracle session <id>` can reattach.

That maps cleanly onto the container: `./scripts/bh url` already publishes CDP on `127.0.0.1:${BH_HOST_PORT}`, so Oracle attaches to the same endpoint browser-harness uses.

```text
oracle (host) ──┐
                ├─→ 127.0.0.1:${BH_HOST_PORT} → container CDP proxy → Patchright Chrome
browser-harness ┘
```

## Configuration model

Oracle layers `~/.oracle/config.json` (user) under `.oracle/config.json` (project), both JSON5.

**`browser.remoteChrome` is not a config key** — not in the user config, not in the project config, and there is no environment variable for it (`ORACLE_BROWSER_PORT` / `ORACLE_BROWSER_DEBUG_PORT` set the port Oracle uses when it *launches* Chrome, not a remote target). The CDP target can only be passed per run as `--remote-chrome host:port`. That is the entire reason `scripts/oracle` exists.

Project configs are also sanitized by Oracle: they may set workflow defaults only. `apiBaseUrl`, `modelOverrides`, `azure`, `browser.remoteHost`, `browser.remoteToken`, `browser.chromePath`, and `browser.chromeCookiePath` are ignored in `.oracle/config.json` and read only from the user config, environment, or CLI flags. Keep secrets and machine-local paths out of this repo.

`.oracle/config.json` in this repo pins the safe workflow defaults and explicitly sets `attachRunning: false` and `manualLogin: false`, so a user-level config cannot cause a project run to touch a local Chrome profile.

Optional per-project knobs live in `.browser-harness.env`:

```bash
# Oracle model and extra flags for ./scripts/oracle
BH_ORACLE_MODEL=gpt-5.5-pro
BH_ORACLE_EXTRA_ARGS=--heartbeat 30

# Loopback-only interactive view of the container display (sign-in only)
BH_VNC_PORT=15900
```

## Usage

```bash
./scripts/oracle status                        # wrapper, container target, oracle readiness
./scripts/oracle check                         # is the container profile signed in to ChatGPT?
./scripts/oracle plan -p "Review this design"  # dry run; prints Oracle's browser control plan
./scripts/oracle run -p "Review this design" --file "docs/**/*.md"
```

`run` and `plan` boot or reuse the container (via `./scripts/bh url`), then exec `oracle` with `--engine browser --remote-chrome 127.0.0.1:${BH_HOST_PORT}` plus anything from `BH_ORACLE_MODEL` / `BH_ORACLE_EXTRA_ARGS`.

The wrapper rejects flags that would break the isolation boundary:

| Rejected | Why |
| --- | --- |
| `--remote-chrome` | Set by the wrapper. |
| `--remote-host`, `--remote-token` | `oracle serve` bridges are out of scope for this kit. |
| `--browser-attach-running`, `--browser-chrome-path`, `--browser-cookie-path`, `--copy-profile`, `--browser-manual-login`, `--browser-keep-browser`, `--browser-headless`, `--browser-hide-window` | Target a locally launched Chrome; ignored or wrong against the container. |
| `--browser-inline-cookies`, `--browser-inline-cookies-file` | Would import a session from another browser. |

## First-time sign-in

Remote-chrome mode does no cookie sync, so the **container profile** has to be signed in to ChatGPT once. The profile lives in the project's Docker volume (`BH_PROFILE_VOLUME`), so this survives container restarts and `./scripts/bh reload`; it is lost only if that volume is removed.

The container runs headed Chrome on a virtual X display with no visible window, so the sign-in needs a temporary view of the display. It uses Xvfb normally and switches to TigerVNC's X server only when `BH_VNC_ENABLED=1`, which also provides bidirectional clipboard support.

1. Set `BH_VNC_PORT=15900` in `.browser-harness.env`.
2. Use a new `BH_IMAGE` tag and rebuild if the image predates TigerVNC clipboard support — `./scripts/bh` only builds when the image tag is absent.
3. `./scripts/bh reload`
4. `./scripts/oracle login` — opens chatgpt.com in the container and prints the VNC URL.
5. Connect to `vnc://127.0.0.1:15900` (macOS: Screen Sharing) and **sign in yourself**.
6. `./scripts/oracle check` — expect `"signedIn": true`.
7. Unset `BH_VNC_PORT` and `./scripts/bh reload` when finished.

Rules that do not bend:

- Agents must not type credentials, and must not read or copy cookies out of the operator's real browser to seed the container. If `check` reports a signed-out session, that is an operator task.
- VNC publishing stays on `127.0.0.1`, never `0.0.0.0`. It is unauthenticated, on the same trust boundary as CDP — which already grants full control of the browser — so it must not outlive the sign-in.
- `BH_VNC_PORT` requires headed Chrome; the wrapper refuses it when `PATCHRIGHT_HEADLESS` is not `0`.

## Tab lifecycle: Oracle vs. the harness

Both Oracle and browser-harness drive tabs in the same container.

- Oracle opens its own tab per run and closes it at the end.
- The harness rule for this project is `reuse_tab(url, close_others=True)` — which would close Oracle's tab mid-consult.

While a consult is in flight, use `reuse_tab(url)` **without** `close_others`, and do not call `close_other_tabs(...)`.

If a project routinely runs consults and browser automation at the same time, give Oracle its own container: copy `.browser-harness.env` with a distinct `BH_PROJECT_SLUG`, `BH_CONTAINER_NAME`, `BH_HOST_PORT`, `BH_BU_NAME`, and `BH_PROFILE_VOLUME`, and point `scripts/oracle` at it via `BH_PROJECT_ROOT`. That also keeps the ChatGPT-logged-in profile separate from the profile used to test the app.

## Failure modes and fixes

**`Remote Chrome configuration missing`** — `--remote-chrome` was dropped. Use `./scripts/oracle run`, not plain `oracle`.

**`The remote Chrome session is not signed into ChatGPT`** — the container profile is signed out. Follow *First-time sign-in*. Do not work around it with inline cookies.

**Connection refused on `127.0.0.1:${BH_HOST_PORT}`** — the container is not up. `./scripts/bh url` boots and waits for CDP; check `./scripts/bh logs` if it fails.

**Cloudflare/bot challenge on chatgpt.com** — the portable image uses Debian's system Chromium. Patchright's patches help, but a Chrome-channel image variant (`PATCHRIGHT_BROWSER_CHANNEL=chrome`, amd64) is the fallback if challenges persist. See `docs/02-architecture.md` for the caveat.

**Consult appears to hang** — Pro-model browser consults running for many minutes is expected. Check `oracle status` / `oracle session <id>` before retrying; a duplicate run just contends for the tab lease.

**Oracle's tab vanished mid-run** — harness cleanup closed it. See *Tab lifecycle* above.

## Scope notes

- This integration covers the browser engine only. `oracle --engine api` needs no container and is unaffected.
- `oracle serve` / `oracle bridge` remote-browser modes are deliberately not wired up: they exist to share a signed-in host browser, which is the boundary this kit maintains.
- `oracle-mcp` resolves its own browser config, and its documented `consult` inputs expose no remote-chrome target, so MCP browser consults would fall back to a locally launched Chrome. Route browser consults through `./scripts/oracle`; use `engine: "api"` for MCP.
