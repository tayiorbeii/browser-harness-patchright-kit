# 01. Requirements

## Problem

`browser-harness` is useful because it lets an agent directly control a real browser. The drawback is that default local browser-harness usage can attach to the user's normal Chrome/Chromium session, which interrupts active work and can expose personal profile state.

## Goal

Create a project-level setup where an agent can use `browser-harness` through a Chrome instance running inside a Docker container.

## Functional requirements

1. Each project can declare its own browser container configuration.
2. Different projects can use different containers and different browser profiles.
3. A wrapper command starts the right container when missing.
4. If the container is already running, the wrapper reuses it.
5. The wrapper waits until the container's Chrome CDP endpoint is ready.
6. `browser-harness` receives:
   - a unique `BU_NAME` for the project daemon;
   - a `BU_CDP_URL` pointing at the container browser.
7. The browser profile persists between runs for the same project.
8. The project browser does not use or modify the user's real Chrome profile.
9. Local development sites on the host are reachable from inside the container.
10. Downloads and file uploads are predictable from the project.

## Non-functional requirements

1. Minimal disruption to developer workflow.
2. No public exposure of the CDP port.
3. Works from coding agents through a repeatable project skill.
4. Mostly shell/Docker based; avoid requiring agents to understand the full setup each time.
5. Safe enough defaults for local project work.

## Out of scope for first implementation

1. Full fleet/orchestration support across remote machines.
2. Guaranteed bot-detection bypass.
3. A GUI/VNC viewer, although the design can add one later.
4. Support for Firefox or WebKit through Patchright. Patchright only covers Chromium-family browsers.
5. Automatically copying cookies from the user's real Chrome profile into the container.
