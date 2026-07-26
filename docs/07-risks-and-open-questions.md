# 07. Risks and Open Questions

## Risk: Patchright/browser-harness stealth mismatch

Patchright tries to avoid certain detectable Playwright/CDP behaviors. Browser-harness directly uses CDP and enables default CDP domains. This may reduce or eliminate stealth benefits on some sites.

Mitigation:

- Be clear that this project is primarily about session isolation.
- For sites where Patchright's stealth behavior is the main requirement, consider using Patchright directly instead of browser-harness.
- Add tests for target sites if stealth behavior matters.

## Risk: container Chrome launch arguments

Adding custom Chrome flags can change fingerprinting behavior. Keep flags minimal.

Required flags:

```text
--remote-debugging-address=0.0.0.0
--remote-debugging-port=9222
--no-first-run
--no-default-browser-check
```

Optional and situational:

```text
--lang=en-US
--proxy-server=...
--remote-allow-origins=*
```

Only use `--remote-allow-origins=*` if CDP WebSocket origin checks cause failures, and keep the host port loopback-bound.

## Risk: version mismatch

Patchright tracks Playwright but can lag or differ. The Dockerfile pins Patchright through a build arg and uses a Playwright Docker base image mostly for OS/browser dependencies.

Mitigation:

- Keep `PATCHRIGHT_VERSION` configurable.
- Rebuild the image when Patchright changes.
- Smoke test CDP and browser-harness after updates.

## Risk: Docker Desktop vs Linux differences

`--ipc=host` is common on native Linux. Docker Desktop users may prefer `--shm-size=2g`.

Mitigation:

- Default to `--shm-size=2g`.
- Document `--ipc=host` as an alternative.

## Risk: profile volume contains sensitive state

The project volume may contain cookies and login state.

Mitigation:

- Name volumes per project.
- Document reset commands.
- Do not mount or copy the user's real Chrome profile.
- Avoid committing `.browser-harness.env`.

## Resolved: VNC/debug viewing

x11vnc is installed in the image and started when `BH_VNC_ENABLED=1`. The host port is published on loopback only via `BH_VNC_PORT`. See README.md for interactive access instructions. A browser-based noVNC viewer remains a future option for operators who prefer a web UI over a native VNC client.

## Open question: shared image management

This kit assumes each project can build the image from local templates. A later improvement could centralize the image in a developer dotfiles repo or internal registry.

## Open question: automatic port allocation

The template uses explicit project ports. A later wrapper could allocate a free port and persist it into `.browser-harness.env`, but explicit ports are easier for agents to debug.
