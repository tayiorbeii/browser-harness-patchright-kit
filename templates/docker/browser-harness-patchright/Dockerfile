ARG PYTHON_IMAGE=python:3.12-bookworm
FROM ${PYTHON_IMAGE}

ARG PATCHRIGHT_VERSION=1.61.1

ENV PYTHONUNBUFFERED=1

USER root

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    chromium \
    curl \
    fonts-liberation \
    tigervnc-standalone-server \
    tigervnc-tools \
    xvfb \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip install --no-cache-dir "patchright==${PATCHRIGHT_VERSION}"

# Mapping browser localhost traffic to Docker's host gateway is intentional for
# testing host dev servers. Suppress Chromium's generic dangerous-flag banner
# with its supported machine policy instead of test-only browser switches.
RUN install -d -m 0755 /etc/chromium/policies/managed \
    && printf '%s\n' '{"CommandLineFlagSecurityWarningsEnabled":false}' \
        > /etc/chromium/policies/managed/browser-harness.json \
    && chmod 0644 /etc/chromium/policies/managed/browser-harness.json

RUN useradd --create-home --shell /bin/bash pwuser \
    && mkdir -p /app /data/profile /data/downloads \
    && chown -R pwuser:pwuser /app /data

WORKDIR /app

COPY launch_patchright_cdp.py /app/launch_patchright_cdp.py
RUN chmod 0755 /app/launch_patchright_cdp.py \
    && chown pwuser:pwuser /app/launch_patchright_cdp.py

USER pwuser

ENV DISPLAY=:99 \
    CDP_PORT=9222 \
    PATCHRIGHT_HEADLESS=0 \
    PATCHRIGHT_DOWNLOADS_DIR=/data/downloads \
    PATCHRIGHT_BROWSER_EXECUTABLE=/usr/bin/chromium \
    CHROMIUM_SANDBOX=0

EXPOSE 9222 5900

# Playwright/Patchright containers should be run with Docker's init process
# (`docker run --init` or Compose `init: true`) so Chrome/Xvfb children are
# reaped correctly. The wrapper/compose slices should enforce that runtime flag.
#
# CDP is bound to 0.0.0.0 inside the container only. Host publishing must stay
# loopback-only (for example 127.0.0.1:9222:9222) and is intentionally not
# decided by this image.
#
# Headed runs use Xvfb unless BH_VNC_ENABLED=1, when Xtigervnc becomes the X
# server so clipboard exchange uses TigerVNC's native modern-X11 support. VNC
# exists only for one-time interactive work inside the isolated profile (for
# example signing in to a service the harness must not sign in to). Like CDP,
# its host publishing must stay loopback-only.
#
# Docker Desktop vs native Linux notes:
# - Prefer `--shm-size=1g` (or larger) for headed Chrome stability. Avoid
#   relying on host `/dev/shm` mounts because Docker Desktop VM sharing differs
#   from native Linux.
# - The image installs Debian's system Chromium so it works on both amd64 and
#   arm64 Docker engines. Projects that require the Google Chrome channel can
#   build an amd64-specific variant and set PATCHRIGHT_BROWSER_CHANNEL=chrome.
# - The portable default keeps Chromium's sandbox disabled. On native Linux,
#   an optional stronger-sandbox path can set CHROMIUM_SANDBOX=1 and run with an
#   appropriate seccomp profile; see templates/seccomp_userns_allow.fragment.json
#   in this kit for the documented fragment. Docker Desktop seccomp/userns
#   behavior differs, so keep that opt-in outside the image.

CMD ["python", "/app/launch_patchright_cdp.py"]
