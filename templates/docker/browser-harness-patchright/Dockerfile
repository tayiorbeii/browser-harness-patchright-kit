ARG PLAYWRIGHT_IMAGE=mcr.microsoft.com/playwright/python:v1.60.0-noble
FROM ${PLAYWRIGHT_IMAGE}

ARG PATCHRIGHT_VERSION=1.61.1

USER root

RUN apt-get update && apt-get install -y --no-install-recommends \
    xvfb \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip install --no-cache-dir "patchright==${PATCHRIGHT_VERSION}"

# Patchright recommends Chrome for its best-practice persistent-context setup.
RUN patchright install chrome

RUN mkdir -p /app /data/profile /data/downloads \
    && chown -R pwuser:pwuser /app /data

COPY launch_patchright_cdp.py /app/launch_patchright_cdp.py
RUN chmod +x /app/launch_patchright_cdp.py

USER pwuser

ENV DISPLAY=:99 \
    CDP_HOST=0.0.0.0 \
    CDP_PORT=9222 \
    PATCHRIGHT_CHANNEL=chrome \
    PATCHRIGHT_HEADLESS=0 \
    PATCHRIGHT_USER_DATA_DIR=/data/profile \
    PATCHRIGHT_DOWNLOADS_DIR=/data/downloads \
    CHROMIUM_SANDBOX=0

EXPOSE 9222

ENTRYPOINT ["python", "/app/launch_patchright_cdp.py"]
