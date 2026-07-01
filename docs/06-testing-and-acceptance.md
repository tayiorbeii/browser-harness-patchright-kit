# 06. Testing and Acceptance

## Acceptance criteria

The project is ready when all of these pass:

- `./scripts/bh status` prints the expected project settings.
- `./scripts/bh url` starts the container and returns a loopback CDP URL.
- `curl "$(./scripts/bh url)/json/version"` returns JSON with `webSocketDebuggerUrl`.
- `./scripts/bh run` can call `page_info()`.
- `./scripts/bh run` can open `https://example.com`.
- The user's normal browser session is not focused, navigated, or modified.
- Restarting the wrapper reuses the same project Chrome profile.
- Stopping the container and starting again preserves project cookies/session state.
- Two projects can run at the same time without port, daemon, or profile collision.
- A host dev server is reachable as `http://host.docker.internal:<port>` from container Chrome.

## Smoke tests

### 1. Container readiness

```bash
./scripts/bh url
curl -fsS "$(./scripts/bh url)/json/version" | python -m json.tool
```

### 2. Browser-harness connection

```bash
./scripts/bh run <<'PY'
print(page_info())
PY
```

### 3. External navigation

```bash
./scripts/bh run <<'PY'
new_tab("https://example.com")
wait_for_load()
print(page_info())
PY
```

### 4. Host dev server

On host:

```bash
python3 -m http.server 8765
```

In another terminal:

```bash
./scripts/bh run <<'PY'
new_tab("http://host.docker.internal:8765")
wait_for_load()
print(page_info())
PY
```

### 5. Multi-project isolation

In project A:

```bash
./scripts/bh run <<'PY'
new_tab("https://example.com/?project=A")
wait_for_load()
print(page_info())
PY
```

In project B:

```bash
./scripts/bh run <<'PY'
new_tab("https://example.com/?project=B")
wait_for_load()
print(page_info())
PY
```

Confirm:

```bash
docker ps --filter label=browser-harness.project
```

There should be two containers with different names and ports.

## Failure modes and fixes

### CDP endpoint not ready

Run:

```bash
./scripts/bh logs
```

Common causes:

- image build failed;
- Patchright Chrome install failed;
- port already in use;
- Chrome launch crashed due to Docker memory/shared-memory limits.

### Browser-harness still attaches to local Chrome

Check that the wrapper exports `BU_CDP_URL` and that agents are not running plain `browser-harness`.

Run:

```bash
./scripts/bh run <<'PY'
import os
print(os.environ.get("BU_NAME"))
print(os.environ.get("BU_CDP_URL"))
print(page_info())
PY
```

### Port collision

Change `BH_HOST_PORT` in `.browser-harness.env`, then run:

```bash
./scripts/bh stop
./scripts/bh reload
./scripts/bh url
```

If the old container has a fixed port mapping, remove/recreate it:

```bash
docker rm -f "$BH_CONTAINER_NAME"
./scripts/bh url
```

### Localhost does not resolve to host dev server

Use `host.docker.internal`, not `localhost`.
