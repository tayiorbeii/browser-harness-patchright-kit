# 02. Architecture

## Recommended architecture

Use:

- one reusable Docker image: `browser-harness-patchright`;
- one named Docker container per project;
- one named Docker volume per project for the Chrome profile;
- one host loopback port per project for CDP;
- one project wrapper script: `scripts/bh`;
- one project-specific browser-harness skill that tells agents to call `./scripts/bh run`.

```text
agent
  |
  | ./scripts/bh run -c $'reuse_tab("https://example.com", close_others=True)\nwait_for_load()\nprint(page_info())'
  v
scripts/bh
  |
  | ensures Docker container exists/runs
  | waits for http://127.0.0.1:${BH_HOST_PORT}/json/version
  | exports BU_NAME + BU_CDP_URL + BH_HOME/BH_RUNTIME_DIR/BH_TMP_DIR
  v
browser-harness daemon for BU_NAME
  |
  | CDP WebSocket resolved from BU_CDP_URL
  v
Chrome launched by Patchright inside Docker
  |
  | persistent profile volume
  v
Docker volume: bh-<project>-profile
```

## Why this works

`browser-harness` attaches to a Chromium-family browser through CDP. It can use a dedicated remote CDP endpoint through `BU_CDP_URL` or `BU_CDP_WS`.

Patchright is not the protocol endpoint used by browser-harness. Patchright is used here to launch a patched Chromium/Chrome browser process with a persistent context and a remote-debugging port. `browser-harness` then connects directly to Chrome through CDP.

## Important compatibility caveat

This design means browser-harness may still send CDP commands that Patchright itself tries to avoid when Patchright is in full control of automation. For example, Patchright documents avoidance of `Runtime.enable`, while browser-harness enables CDP domains including Runtime in its daemon. So this setup provides:

- project isolation;
- a containerized Chrome instance;
- Patchright-managed Chrome launch defaults;
- browser-harness ergonomics.

It does **not** guarantee the full stealth properties Patchright aims for when Patchright alone drives the page.

## Kit source ownership

Root-level operational files are canonical within this kit. Their `templates/` counterparts are distributable starter snapshots copied into target repositories, not generated sources. `scripts/check_repository_integrity.py` holds the single declarative mirror map: seven pairs must match byte-for-byte, and every side must have its declared regular-file mode (`100644` or `100755`), while the environment pair allows only four complete identity-assignment substitutions (`BH_PROJECT_SLUG`, `BH_CONTAINER_NAME`, `BH_BU_NAME`, and `BH_PROFILE_VOLUME`). The checker reports drift but never rewrites either side.

The pre-commit hook reads mirror content and modes from Git's staged index, so partially staging one side cannot commit drift. It also requires the staged hook, checker, and acceptance test to byte-match the worktree copies with mode `100755`, preventing a commit from installing a hook whose checker or proof suite was omitted. Docker-free acceptance checks use the same map against the working tree.

## Components

### Docker image

The image installs Patchright and Chrome, then runs a Python launcher that starts a persistent Chrome context with:

- project-specific user data directory;
- remote debugging address and port;
- optional Xvfb for headed Chrome without taking over the host desktop;
- a long-running process to keep the browser alive.

### Per-project `.browser-harness.env`

This file declares the project slug, container name, profile volume, host port, and browser-harness daemon name.

### Wrapper script

The wrapper:

1. loads `.browser-harness.env`;
2. builds the image if missing;
3. creates the profile volume if missing;
4. starts/reuses the container;
5. waits for `/json/version`;
6. runs browser-harness with project-scoped environment;
7. provides commands for status, logs, shell, reload, stop, and url.

### Skill

The skill tells agents to never call plain `browser-harness` in this project. They should always call `./scripts/bh run`.
