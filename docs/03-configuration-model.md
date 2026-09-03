# 03. Configuration Model

## Project config file

Each project gets a `.browser-harness.env` file.

Minimum required values:

```bash
BH_PROJECT_SLUG=my-app
BH_CONTAINER_NAME=bh-my-app
BH_IMAGE=browser-harness-patchright:1.61.1
BH_HOST_PORT=19322
BH_BU_NAME=my-app
BH_PROFILE_VOLUME=bh-my-app-profile
BH_DOWNLOADS_DIR=.browser-harness/downloads
BH_DOCKER_EXTRA_ARGS=--shm-size=2g
PATCHRIGHT_HEADLESS=0
```

## Required uniqueness

These must be unique per project:

- `BH_CONTAINER_NAME`
- `BH_HOST_PORT`
- `BH_BU_NAME`
- `BH_PROFILE_VOLUME`

Recommended naming:

```bash
BH_PROJECT_SLUG=<repo-name>
BH_CONTAINER_NAME=bh-<repo-name>
BH_HOST_PORT=193xx
BH_BU_NAME=<repo-name>
BH_PROFILE_VOLUME=bh-<repo-name>-profile
```

## Ports

The wrapper maps:

```bash
127.0.0.1:${BH_HOST_PORT} -> container:9222
```

Use host loopback only. Do not expose the container's DevTools port on public interfaces.

## Browser-harness state isolation

The wrapper exports:

```bash
BH_HOME=.browser-harness/home
BH_RUNTIME_DIR=.browser-harness/runtime
BH_TMP_DIR=.browser-harness/tmp
BU_NAME=${BH_BU_NAME}
BU_CDP_URL=http://127.0.0.1:${BH_HOST_PORT}
```

This isolates the project daemon, logs, temp files, and agent workspace.

## Container browser profile

The Chrome profile lives in a Docker named volume:

```bash
-v ${BH_PROFILE_VOLUME}:/data/profile
```

This lets login state persist for a single project without touching the user's real Chrome profile.

## Downloads

Downloads are mounted into the project:

```bash
-v ${project_root}/${BH_DOWNLOADS_DIR}:/data/downloads
```

Default:

```text
.browser-harness/downloads/
```

## Localhost inside Docker

From the browser running in Docker, `localhost` means the container itself. Use:

```text
http://host.docker.internal:<port>
```

The wrapper adds:

```bash
--add-host=host.docker.internal:host-gateway
```

This lets the container reach local dev servers running on the host.

## Optional knobs

```bash
# Run Chrome headless instead of headed under Xvfb.
PATCHRIGHT_HEADLESS=1

# Extra Chrome flags. Keep this minimal.
PATCHRIGHT_EXTRA_ARGS='--lang=en-US'

# Use a proxy from inside Chrome.
PATCHRIGHT_EXTRA_ARGS='--proxy-server=http://host.docker.internal:8080'

# Stronger Linux sandboxing path when you wire a complete seccomp profile.
BH_DOCKER_EXTRA_ARGS='--ipc=host --security-opt seccomp=/absolute/path/to/seccomp_profile.json'
CHROMIUM_SANDBOX=1

# Loopback-only VNC view of the container display for one-time interactive work
# (sign-in, captcha). Requires headed Chrome. Leave unset when not in use.
BH_VNC_PORT=15900
# Optional tigervncpasswd file for clients that require VNCAuth.
BH_VNC_PASSWORD_FILE=/absolute/path/to/tigervnc-password-file

# Informational browser origin shown by ./scripts/bh status. Never navigates Chrome.
BH_BROWSER_ORIGIN=https://localhost:3443

# Dedicated Chromium host resolver rules, passed as one browser argument.
BH_HOST_RESOLVER_RULES='MAP localhost host.docker.internal'

# Oracle consult model and extra flags for ./scripts/oracle.
BH_ORACLE_MODEL=gpt-5.5-pro
BH_ORACLE_EXTRA_ARGS=--heartbeat 30
```

See `docs/08-https-localhost-integration.md` for resolver and origin contract details, and `docs/09-oracle-integration.md` for Oracle setup.
