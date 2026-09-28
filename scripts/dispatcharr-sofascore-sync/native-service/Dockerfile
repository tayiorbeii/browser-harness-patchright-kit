# Lightweight CDP *client* only -- no browser binaries, no playwright/
# patchright package. The actual browser lives in the sibling
# sofascore-browser service (see ../browser/); this container just speaks
# WebSocket JSON-RPC (Chrome DevTools Protocol) to it over the docker
# network, via cdp_client.py + the small pure-Python `websocket-client`
# package (no C extension, no heavy deps).
FROM python:3.12-slim

RUN pip install --no-cache-dir "websocket-client==1.8.0"

RUN useradd --create-home --shell /usr/sbin/nologin syncuser
WORKDIR /app
COPY cdp_client.py sync_daemon.py ./
RUN chown -R syncuser:syncuser /app
USER syncuser

HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import os,sys,time; p='/tmp/sofascore-sync.heartbeat'; sys.exit(0 if os.path.isfile(p) and time.time()-os.path.getmtime(p) < 1200 else 1)"

CMD ["python", "sync_daemon.py"]
