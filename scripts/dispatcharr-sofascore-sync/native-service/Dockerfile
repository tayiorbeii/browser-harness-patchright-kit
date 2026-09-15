# Same base image as rive-resolver itself (mcr.microsoft.com/playwright/python)
# -- Chromium + all OS deps are already present, nothing extra to install.
# Pin to the exact tag rive-resolver already uses so this image is already
# cached/fast to build on blackpearl.local (see rive-resolver/Dockerfile).
ARG SOFASCORE_SYNC_BASE_IMAGE=mcr.microsoft.com/playwright/python:v1.62.0-noble
FROM ${SOFASCORE_SYNC_BASE_IMAGE}
WORKDIR /app
COPY sync_daemon.py .

# DOCK-1 parity with rive-resolver: run as a non-root user, not root.
RUN groupadd -r appuser && useradd -r -u 999 -g appuser -d /home/appuser -m appuser \
    && mkdir -p /tmp && chown -R appuser:appuser /app /tmp
USER appuser:appuser

# No FastAPI/uvicorn here -- this is a bare long-running loop with no HTTP
# surface of its own. Liveness is a heartbeat file the loop touches once
# per cycle (before AND after each attempt, so a hung/crashing cycle still
# shows up as a stale heartbeat rather than a false-healthy status). Using
# python for the check instead of `pgrep`/`find -mmin` keeps this portable
# across whatever coreutils/procps subset the base image ships with.
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import os,sys,time; p='/tmp/sofascore-sync.heartbeat'; sys.exit(0 if os.path.isfile(p) and time.time()-os.path.getmtime(p) < 1200 else 1)"

CMD ["python", "sync_daemon.py"]
