---
name: browser-harness
description: Hard guardrail: use project-isolated browser-harness through ./scripts/bh run and the Patchright Chrome container.
---

# browser-harness, project-isolated guardrail

In this project, **NEVER** run plain `browser-harness`.

Always run browser code through the project wrapper:

```bash
./scripts/bh run <<'PY'
print(page_info())
PY
```

## Why this rule exists

`./scripts/bh run` drives this repository's isolated Patchright Chrome container. The wrapper starts or reuses the project container, waits for its local CDP endpoint, and launches browser-harness with the correct project-scoped environment.

This prevents agents from accidentally attaching to the user's normal Chrome session. The container uses a separate browser profile and a loopback-only CDP endpoint for this project.

## Environment exported by the wrapper

When you use `./scripts/bh run`, the wrapper exports:

- `BU_NAME` — the project-specific browser-harness daemon name.
- `BU_CDP_URL` — the loopback HTTP CDP URL for the Patchright Chrome container.
- `BU_CDP_WS` — the loopback WebSocket CDP URL for the Patchright Chrome container.

Use normal browser-harness helpers after that:

- first navigation: `new_tab(url)`;
- inspect visible state with `capture_screenshot()`;
- use `page_info()`, `wait_for_load()`, `js(...)`, and CDP helpers as usual.

For local dev servers running on the host:

- Docker Desktop: use `host.docker.internal` from inside the browser container.
- Native Linux: use the host-gateway address configured by the project wrapper/container; do not assume container `localhost` is the host.

Example:

```python
new_tab("http://host.docker.internal:3000")
```

## Runtime subcommands

Use the project wrapper subcommands, not direct browser-harness process management:

- `./scripts/bh status` — show container/runtime status.
- `./scripts/bh url` — print the loopback CDP URL.
- `./scripts/bh run` — run browser-harness code against the project container.
- `./scripts/bh logs` — show container logs.
- `./scripts/bh shell` — open a shell in the browser container.
- `./scripts/bh reload` — restart/reload the browser container after config changes.
- `./scripts/bh stop` — stop the project browser container when asked.

If the browser seems stale after changing `.browser-harness.env`, run:

```bash
./scripts/bh reload
```

When browser work is done and the user asks to close it:

```bash
./scripts/bh stop
```

## Security and privacy warnings

- Do **not** use browser-harness cloud browsers for this project.
- Do **not** copy cookies, profiles, or session data from the user's real browser.
- Do **not** expose CDP publicly; CDP must stay loopback-only (`127.0.0.1` / local-only).
- Keep Chrome launch args minimal and project-controlled. Prefer templates and documented examples over personal config.
