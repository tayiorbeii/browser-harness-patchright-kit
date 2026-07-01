---
name: browser-harness
description: Use project-isolated browser-harness through the project's Patchright Chrome container.
---

# browser-harness, project-isolated

For browser work in this project, do not run plain `browser-harness`.

Always run browser code through:

```bash
./scripts/bh run <<'PY'
print(page_info())
PY
```

The wrapper:

- starts the project's Patchright Chrome container if needed;
- reuses it if already running;
- sets `BU_NAME` to the project daemon name;
- sets `BU_CDP_URL` to the project container's CDP endpoint;
- keeps the browser profile separate from the user's real Chrome session.

Use normal browser-harness helpers after that:

- first navigation: `new_tab(url)`;
- inspect visible state with `capture_screenshot()`;
- use `page_info()`, `wait_for_load()`, `js(...)`, and CDP helpers as usual.

For local dev servers running on the host, use `host.docker.internal`, not `localhost`, from the browser container. Example:

```python
new_tab("http://host.docker.internal:3000")
```

If the browser seems stale after changing `.browser-harness.env`, run:

```bash
./scripts/bh reload
```

When browser work is done and the user asks to close it:

```bash
./scripts/bh stop
```
