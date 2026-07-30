---
name: browser-harness
description: Hard guardrail: use project-isolated browser-harness through ./scripts/bh run and the Patchright Chrome container.
---

# browser-harness, project-isolated guardrail

In this project, **NEVER** run plain `browser-harness`.

Always run browser code through the project wrapper:

```bash
./scripts/bh run -c 'print(page_info())'
./scripts/bh run -c $'reuse_tab("https://example.com", close_others=True)\nwait_for_load()\nprint(page_info())'
```

## Why this rule exists

`./scripts/bh run` drives this repository's isolated Patchright Chrome container. The wrapper starts or reuses the project container, waits for its local CDP endpoint, and launches browser-harness with the correct project-scoped environment.

This prevents agents from accidentally attaching to the user's normal Chrome session. The container uses a separate browser profile and a loopback-only CDP endpoint for this project.

## Environment exported by the wrapper

When you use `./scripts/bh run`, the wrapper exports:

- `BU_NAME` — the project-specific browser-harness daemon name.
- `BU_CDP_URL` — the loopback HTTP CDP URL for the Patchright Chrome container.
- `BU_CDP_WS` — the loopback WebSocket CDP URL for the Patchright Chrome container.

## Mandatory tab lifecycle

The container and `BU_NAME` persist across separate harness calls. Keep one remembered work tab instead of opening a tab per command:

- Start with `work = reuse_tab(url, close_others=True)`; this reuses the project work target and prunes stale page/about:blank tabs.
- Use `goto_url(url)` for later navigation in that work tab.
- Use `new_tab()` only for a genuinely simultaneous second page or when the user explicitly asks for another tab.
- Close a temporary tab with `close_tab(target_id)` as soon as it is no longer needed; when closing the active temporary tab it restores the remembered work target. Finish with `close_other_tabs(work["targetId"])`.
- Never call `new_tab()` merely because a new command, turn, or subagent invocation started.

Bulk cleanup is safe here because this is the project-isolated browser. Never use `close_others=True` or `close_other_tabs()` against the user's normal Chrome.

Use normal browser-harness helpers after acquiring the work tab:

- inspect visible state with `capture_screenshot()`;
- use `page_info()`, `wait_for_load()`, `js(...)`, and CDP helpers as usual.

For local dev servers running on the host:

- By default, use `host.docker.internal` from inside the browser container.
- When the project explicitly configures `BH_HOST_RESOLVER_RULES` to map `localhost` to `host.docker.internal`, use the configured `BH_BROWSER_ORIGIN` so HTTPS origin, SNI, cookies, and WebSockets stay on localhost.
- Do not mix `localhost` and `host.docker.internal` during one authentication session.
- The application and any project-owned HTTPS proxy must already be running; the browser wrapper never starts them.
- Native Linux host-gateway/resolver behavior must be accepted by the project before relying on it.

Examples:

```python
reuse_tab("http://host.docker.internal:3000", close_others=True)
reuse_tab("https://localhost:3443", close_others=True)  # only with the explicit resolver contract
```

## Runtime subcommands

Use the project wrapper subcommands, not direct browser-harness process management:

- `./scripts/bh status` — show container/runtime status.
- `./scripts/bh url` — print the loopback CDP URL.
- `./scripts/bh run -c '<python code>'` — run browser-harness code against the project container.
- `./scripts/bh logs` — show container logs.
- `./scripts/bh shell` — open a shell in the browser container.
- `./scripts/bh reload` — restart/reload the browser container after config changes.
- `./scripts/bh stop` — stop the project browser container when asked.
- `./scripts/bh purge` — **destructive**; deletes the container, the Chrome profile volume, and local `.browser-harness/` state. Only run it when the user explicitly asks to wipe browser state.

Do not write scratch scripts, screenshots, or test files into `.browser-harness/` and leave them there. That directory is browser runtime state, not a scratch space: anything left in it persists across sessions and follows the checkout around. Use a temp directory, and clean up after yourself.

If the browser seems stale after changing `.browser-harness.env`, run:

```bash
./scripts/bh reload
```

When browser work is done and the user asks to close it:

```bash
./scripts/bh stop
```

## Oracle consults through this container

`oracle` (steipete/oracle) browser consults must use the project container too, never the user's Chrome. Run them through `./scripts/oracle`, which boots/reuses the container and appends `--engine browser --remote-chrome 127.0.0.1:${BH_HOST_PORT}`:

```bash
./scripts/oracle status                       # wrapper + container + oracle readiness
./scripts/oracle check                        # is ChatGPT operational, not merely cookie-authenticated?
./scripts/oracle plan -p "Review this design" # dry run; prints the browser control plan
./scripts/oracle run -p "Review this design" --file "docs/**/*.md"
```

Rules:

- Never invoke plain `oracle` with the browser engine in this project, and never pass `--remote-chrome`, `--remote-host`, `--browser-attach-running`, `--browser-chrome-path`, `--browser-cookie-path`, `--copy-profile`, or `--browser-inline-cookies*`. The wrapper rejects them; they either fight the container target or read the user's real browser.
- `oracle` in remote-chrome mode does not sync cookies. The container profile must already be signed in and show a usable prompt composer. `./scripts/oracle check` must report `"ready": true` and exit 0; `"signedIn": true` alone proves only session-cookie presence. Otherwise stop and tell the user to run `./scripts/oracle login` and resolve sign-in or account-choice UI themselves over VNC. **Do not type credentials, and do not import cookies from any other browser.**
- Oracle opens and closes its own tab in this container. While a consult is running, do not call `reuse_tab(..., close_others=True)` or `close_other_tabs(...)` — that kills Oracle's tab mid-run. Use `reuse_tab(url)` without `close_others` for harness work during a consult, or give Oracle a dedicated container (separate `BH_PROJECT_SLUG`, `BH_HOST_PORT`, and `BH_PROFILE_VOLUME`).
- Browser consults on Pro models can run for many minutes. That is normal: use `oracle status` / `oracle session <id>` rather than starting a duplicate run.
- API-mode consults (`oracle --engine api ...`) need no browser and may be run directly.

Details and failure modes: `docs/09-oracle-integration.md`.

## Security and privacy warnings

- Reject broad `--ignore-certificate-errors`; use only project-owned narrow SPKI trust when documented.
- Never print SPKI values, certificate private keys, credentials, tokens, cookie values, or full environment contents.
- Cookie checks may report metadata only.
- Use only a dedicated development account or test user for authenticated browser work.
- Do **not** use browser-harness cloud browsers for this project.
- Do **not** copy cookies, profiles, or session data from the user's real browser.
- Do **not** expose CDP publicly; CDP must stay loopback-only (`127.0.0.1` / local-only). The optional `BH_VNC_PORT` view follows the same rule.
- Keep Chrome launch args minimal and project-controlled. Prefer templates and documented examples over personal config.
