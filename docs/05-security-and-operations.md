# 05. Security and Operations

## CDP is powerful

Chrome DevTools Protocol can inspect and control the browser. Treat the CDP endpoint as sensitive.

Required default:

```bash
-p 127.0.0.1:${BH_HOST_PORT}:9222
```

Do not bind CDP to `0.0.0.0` on the host.

## Use non-default browser profiles

The container uses:

```text
/data/profile
```

as the Chrome user data directory. This prevents the agent from touching the real host browser profile and aligns with Chrome's current remote-debugging security model.

## Keep mounts narrow

Default mounts:

- project root at the same absolute path, read/write;
- project downloads directory to `/data/downloads`;
- named profile volume to `/data/profile`.

Avoid mounting the user's home directory unless a task explicitly requires it.

## Browser profile hygiene

The project profile may store cookies and session state for sites visited by the agent. Treat the Docker volume as sensitive.

Useful commands:

```bash
docker volume ls | grep browser-harness
docker volume inspect bh-<project>-profile
docker volume rm bh-<project>-profile
```

Delete the volume to reset the project browser.

## Runtime commands

```bash
./scripts/bh status   # print project/container/CDP status
./scripts/bh url      # start if needed and print CDP URL
./scripts/bh logs     # follow container logs
./scripts/bh shell    # shell inside container
./scripts/bh reload   # stop project browser-harness daemon
./scripts/bh stop     # stop daemon and Docker container
```

## Sandbox notes

The template runs as `pwuser`. For trusted local project testing, `--shm-size=2g` is a practical Docker Desktop default.

For untrusted browsing or scraping, prefer a stronger Linux configuration using a complete seccomp profile that allows Chromium user namespaces.

```bash
BH_DOCKER_EXTRA_ARGS='--ipc=host --security-opt seccomp=/absolute/path/to/seccomp_profile.json'
CHROMIUM_SANDBOX=1
```

The included `templates/seccomp_userns_allow.fragment.json` is only the extra allow-rule fragment. Do not pass that fragment directly to Docker. Merge it into Docker's default seccomp profile or download the official Playwright `utils/docker/seccomp_profile.json` and reference that complete file.

## Privacy boundaries

This setup avoids taking over the user's normal browser, but it does not guarantee privacy from the sites visited by the container browser. Sites can still observe normal browser/network properties, IP address, logged-in state, and automation-related behavior.

## Operational recommendation

Add these to `.gitignore`:

```gitignore
.browser-harness/
.browser-harness.env
```

Commit a sample environment file instead:

```text
.browser-harness.env.example
```
