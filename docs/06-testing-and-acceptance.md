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

## Repository-static acceptance

Before Docker or browser smoke tests, run:

```bash
python3 scripts/check_repository_integrity.py --mirrors
./scripts/test-repository-integrity
./scripts/test-https-localhost-integration
```

The declarative checker verifies all live/template content and required regular-file modes (`100644` or `100755`). Seven pairs are exact; `.browser-harness.env.example` is normalized to its starter template using only the four declared project-identity assignment substitutions. The acceptance script also proves exact and normalized drift failures, unilateral and bilateral content/mode drift rejection, omitted or unstaged integrity-infrastructure rejection, allowed examples/templates and SSH public keys, force-added forbidden paths, paths containing spaces or newlines, and staged deletion behavior. Hook scenarios run in a temporary Git repository and do not touch this checkout's index.

The tracked `.githooks/pre-commit` invokes the same policy against staged mirror blobs/modes and the complete staged path index. Install it locally with:

```bash
git config core.hooksPath .githooks
```

## Smoke tests

### Focused image-to-browser-harness connection test

Use this repeatable test when validating a newly built browser image:

```bash
./scripts/test-browser-harness-connection
```

The script builds the configured `BH_IMAGE` from `docker/browser-harness-patchright/`, recreates the named browser container through `./scripts/bh reload`, checks `$(./scripts/bh url)/json/version` for `webSocketDebuggerUrl`, runs `browser-harness` through the wrapper, reuses one work tab for `https://example.com`, prints `page_info()`, and stops the container while preserving the project Chrome profile volume.

Useful variants:

```bash
./scripts/test-browser-harness-connection --image-mode skip   # rely on scripts/bh auto-build if image is missing
./scripts/test-browser-harness-connection --no-stop           # leave the container running for log inspection
```

### 1. Container readiness

```bash
./scripts/bh url
curl -fsS "$(./scripts/bh url)/json/version" | python -m json.tool
```

### 2. Browser-harness connection

```bash
./scripts/bh run -c 'print(page_info())'
```

### 3. External navigation

```bash
./scripts/bh run -c $'reuse_tab("https://example.com", close_others=True)\nwait_for_load()\nprint(page_info())'
```

### 4. Host dev server

On host:

```bash
python3 -m http.server 8765
```

In another terminal:

```bash
./scripts/bh run -c $'reuse_tab("http://host.docker.internal:8765", close_others=True)\nwait_for_load()\nprint(page_info())'
```

### 5. Multi-project isolation

In project A:

```bash
./scripts/bh run -c $'reuse_tab("https://example.com/?project=A", close_others=True)\nwait_for_load()\nprint(page_info())'
```

In project B:

```bash
./scripts/bh run -c $'reuse_tab("https://example.com/?project=B", close_others=True)\nwait_for_load()\nprint(page_info())'
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
./scripts/bh run -c $'import os\nprint(os.environ.get("BU_NAME"))\nprint(os.environ.get("BU_CDP_URL"))\nprint(page_info())'
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
