---
name: browser-harness
description: Use project-isolated browser-harness through the project's Patchright Chrome container.
---

# browser-harness, project-isolated

For browser work in this project, do not run plain `browser-harness`.

Always run browser code through:

```bash
./scripts/bh run -c 'print(page_info())'
./scripts/bh run -c $'reuse_tab("https://example.com", close_others=True)\nwait_for_load()\nprint(page_info())'
```

The wrapper:

- starts the project's Patchright Chrome container if needed;
- reuses it if already running;
- sets `BU_NAME` to the project daemon name;
- sets `BU_CDP_URL` to the project container's CDP endpoint;
- keeps the browser profile separate from the user's real Chrome session.

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

For local dev servers running on the host, use `host.docker.internal` by default. A project may instead preserve an HTTPS localhost origin only when it explicitly configures `BH_HOST_RESOLVER_RULES` and `BH_BROWSER_ORIGIN`. In that mode, do not mix `localhost` and `host.docker.internal` during one authentication session, and require the app/proxy to be running before browser work.

```python
reuse_tab("http://host.docker.internal:3000", close_others=True)
reuse_tab("https://localhost:3443", close_others=True)  # only with the explicit resolver contract
```

Reject broad `--ignore-certificate-errors`. Never print SPKI values, private keys, credentials, tokens, cookie values, or full environment contents. Use only dedicated development accounts/test users; cookie inspection may report metadata only.

## Oracle consults (optional)

If the project ships `scripts/oracle`, run steipete/oracle browser consults through it — it boots/reuses the container and appends `--engine browser --remote-chrome 127.0.0.1:${BH_HOST_PORT}`:

```bash
./scripts/oracle check                        # is the container profile signed in to ChatGPT?
./scripts/oracle plan -p "Review this design" # dry run
./scripts/oracle run -p "Review this design" --file "docs/**/*.md"
```

Never run plain `oracle` with the browser engine here, and never pass `--remote-chrome`, `--remote-host`, `--browser-attach-running`, `--browser-chrome-path`, `--browser-cookie-path`, `--copy-profile`, or `--browser-inline-cookies*`. Remote-chrome mode does not sync cookies, so the container profile must already be signed in; if it is not, ask the user to run `./scripts/oracle login` and sign in themselves. Oracle owns its own tab during a consult — do not use `close_others=True` or `close_other_tabs(...)` while one is running.

If the browser seems stale after changing `.browser-harness.env`, run:

```bash
./scripts/bh reload
```

`./scripts/bh purge` is destructive: it deletes the container, the Chrome profile volume, and local `.browser-harness/` state. Only run it when the user explicitly asks to wipe browser state.

Do not write scratch scripts, screenshots, or test files into `.browser-harness/` and leave them there. That directory is browser runtime state, not a scratch space: anything left in it persists across sessions and follows the checkout around. Use a temp directory, and clean up after yourself.

When browser work is done and the user asks to close it:

```bash
./scripts/bh stop
```
