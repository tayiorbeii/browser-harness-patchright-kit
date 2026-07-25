# 08. HTTPS Localhost Integration Plan

## Scope

This document records an application-specific HTTPS localhost integration layered on top of the generic Browser Harness kit. The generic requirements, architecture, configuration, implementation, security, testing, and risk documents remain authoritative for reusable kit behavior.

The harness owns Dockerized Patchright Chromium, the project-isolated browser profile, loopback-only CDP publication, and Browser Harness lifecycle through `./scripts/bh`. The application continues to own its Next.js server, HTTPS proxy, certificates, narrow SPKI trust configuration, authentication, Convex, OAuth, Inngest, and application secrets.

The harness must not bind or start the application or proxy, modify application origins, generate certificates, manage cookies, or rewrite OAuth callbacks.

## Accepted architecture

The preferred browser path is:

```text
Patchright Chromium in Docker
  -> https://localhost:3443
  -> application HTTPS proxy on the host
  -> http://127.0.0.1:3008
```

The opt-in resolver rule is:

```bash
BH_HOST_RESOLVER_RULES='MAP localhost host.docker.internal'
```

The launcher converts that setting to one Chromium argument:

```text
--host-resolver-rules=MAP localhost host.docker.internal
```

This keeps browser origin, TLS SNI, and HTTP host on `localhost:3443` while routing the connection to the host gateway from inside Docker. Compose and the primary wrapper retain:

```yaml
ports:
  - "127.0.0.1:${BH_HOST_PORT}:9222"
extra_hosts:
  - "host.docker.internal:host-gateway"
```

Host networking is not used.

## Configuration contract

An application-local `.browser-harness.env` may opt into:

```bash
BH_BROWSER_ORIGIN=https://localhost:3443
BH_HOST_RESOLVER_RULES='MAP localhost host.docker.internal'
```

`BH_BROWSER_ORIGIN` is validated metadata. `./scripts/bh status` reports it when configured, and it participates in wrapper configuration signatures. It never navigates Chrome, binds a port, changes application configuration, or starts an application process. The value must be an HTTP(S) origin with no credentials, path beyond `/`, query, or fragment.

`BH_HOST_RESOLVER_RULES` is also part of wrapper configuration signatures and is passed into the container by both Docker-run and Compose launch paths. It is absent unless explicitly configured.

The launcher:

- accepts comma-separated Chromium `MAP` and `EXCLUDE` directives;
- supports the exact rule above;
- emits at most one `--host-resolver-rules=...` argument;
- rejects resolver flags supplied through `PATCHRIGHT_EXTRA_ARGS`;
- continues to reject CDP and profile overrides;
- rejects broad `--ignore-certificate-errors` use;
- permits narrow `--ignore-certificate-errors-spki-list=...` trust;
- preserves unrelated shell-aware `PATCHRIGHT_EXTRA_ARGS`.

No generated SPKI value belongs in committed examples or documentation.

## One-time profile identity migration

The existing ignored local harness environment may still use the generic kit identity. Migrate it manually to unique project values when ready, for example:

```text
BH_PROJECT_SLUG=my-app
BH_CONTAINER_NAME=bh-my-app
BH_BU_NAME=my-app
BH_PROFILE_VOLUME=bh-my-app-profile
BH_HOST_PORT=<unused loopback CDP port>
```

Before editing, make a mode-`0600` backup without displaying its contents. Do not silently rewrite the ignored environment. Do not delete the old named profile volume. After migration, run `./scripts/bh reload`; the new identity intentionally uses a separate container, Browser Harness daemon identity, CDP mapping, and profile volume.

A temporary pre-experiment backup matching `/tmp/bh-env-pre-resolver-*` may exist. Its contents must not be displayed. Remove it only with explicit permission after confirming it is no longer needed.

## Local startup and use

Start the application-owned server and HTTPS proxy first:

```bash
cd <app-root>
bun run setup:https
bun run dev:https
```

Then operate the browser only through the project wrapper:

```bash
cd <kit-root>

./scripts/bh run -c $'work = reuse_tab("https://localhost:3443/signin", close_others=True)\nwait_for_load()\nprint(page_info())'
```

Operational rules:

- Keep one persisted work tab with `reuse_tab(..., close_others=True)`.
- Do not mix `localhost` and `host.docker.internal` during one authentication session.
- The app and proxy must already be running.
- Use only a dedicated development Google account or test user.
- Cookie inspection may report metadata such as name, domain, path, expiry, `secure`, and `sameSite`; never print cookie values.
- Certificate renewal or a changed SPKI trust argument may require `./scripts/bh reload`.
- Do not invoke `browser-harness` directly or launch Chrome ad hoc.

## Experimental evidence

The resolver design was exercised on:

```text
Host:      macOS arm64
Docker VM: Ubuntu 24.04 arm64
```

Observed results:

- `https://localhost:3443/signin` loaded without a certificate interstitial.
- `location.origin` remained `https://localhost:3443`.
- `wss://localhost:3443/_next/webpack-hmr` reached `open`.
- Exactly one persisted work tab remained.
- Google sign-in reached `accounts.google.com/v3/signin/identifier`.
- No visible `origin_mismatch` or `redirect_uri_mismatch` appeared.
- The OAuth request used the Convex deployment callback rather than a localhost callback.
- The ignored harness environment was restored byte-for-byte after the experiment.
- The app, proxy, browser container, and listeners on ports `3008`, `3443`, and the experimental CDP port were stopped.

This proves the HTTPS and WSS resolver path on the tested Docker Desktop environment. It does not prove complete OAuth authentication or native-Linux compatibility. Google permits an exact `https://localhost:3443` JavaScript origin, but the experiment did not establish whether that origin is currently registered in the relevant Google Console configuration. The OAuth callback remains on the Convex deployment and must not be replaced by a localhost callback.

### Post-implementation regression evidence

After implementing the dedicated settings, the same Docker Desktop environment was exercised again with temporary process-level resolver/origin overrides rather than rewriting the ignored harness environment. The rebuilt image loaded the application sign-in page at `https://localhost:3443/signin`; `location.origin` remained `https://localhost:3443`; the HMR WebSocket reported `open`; and CDP reported exactly one page target. The Browser Harness connection smoke test also passed against the rebuilt image.

Before running the application's HTTPS setup, the ignored harness environment was copied to a mode-`0600` temporary backup without displaying its contents. After browser testing it was restored to its exact pre-test hash. The backup and mode-`0600` setup/development logs were retained under `/tmp`; they were not deleted automatically. Application listeners and the browser container were stopped after the test.

Primary behavior references:

- Chromium `MappedHostResolver`: <https://chromium.googlesource.com/chromium/src/+/main/net/dns/mapped_host_resolver.cc#64>
- Chromium WebSocket networking: <https://chromium.googlesource.com/chromium/src/+/main/net/websockets/websocket_stream.cc#558>
- Docker host gateway: <https://docs.docker.com/reference/cli/docker/container/run/#add-host>
- Google OAuth origin validation: <https://developers.google.com/identity/protocols/oauth2/javascript-implicit-flow#javascript-origin-validation-rules>

## Focused verification

Static and contract checks:

```bash
bash -n scripts/bh
bash -n templates/scripts/bh
python3 -m py_compile docker/browser-harness-patchright/launch_patchright_cdp.py
python3 -m py_compile templates/docker/browser-harness-patchright/launch_patchright_cdp.py
./scripts/test-https-localhost-integration
```

Compose interpolation:

```bash
docker compose --env-file .browser-harness.env \
  -f docker-compose.browser-harness.yml config -q
```

Image/CDP/Browser Harness smoke test:

```bash
./scripts/test-browser-harness-connection
```

Browser-level acceptance, performed only with `./scripts/bh run`, must confirm:

1. HTTPS localhost loads without a certificate interstitial.
2. `location.origin` remains `https://localhost:3443`.
3. the HMR WSS connection opens;
4. one work tab remains;
5. narrow SPKI trust remains configured without displaying its value;
6. broad certificate bypass is rejected;
7. CDP is published only on host loopback; and
8. resolver configuration is absent when not opted in.

## Fallbacks and rollback

HTTP localhost is diagnostic fallback only because it loses secure-cookie and certificate coverage. A TCP relay is fallback only if resolver behavior fails on a supported platform.

To roll back the resolver integration without deleting state:

1. stop browser work with `./scripts/bh stop`;
2. manually remove `BH_HOST_RESOLVER_RULES` and, if desired, `BH_BROWSER_ORIGIN` from the ignored local harness environment;
3. run `./scripts/bh reload` to recreate the container with the changed signature; and
4. retain all named profile volumes unless the user separately authorizes deletion.

Rollback does not change application certificates, proxy configuration, OAuth settings, cookies, or application processes.

## Remaining acceptance work

- Test the host-gateway resolver path on supported native Linux, including bridge networking, firewall behavior, rootless Docker, and host-gateway availability.
- Confirm the exact `https://localhost:3443` JavaScript origin is registered for the dedicated development Google client where required.
- Complete a full authenticated redirect and persisted authenticated session back on `https://localhost:3443` with a dedicated development account.
- Re-run HTTPS, WSS, one-tab, loopback CDP, and no-broad-certificate-bypass checks after the final profile identity migration.
- Use TCP relay only if native-Linux evidence shows the resolver path cannot satisfy a supported configuration.
