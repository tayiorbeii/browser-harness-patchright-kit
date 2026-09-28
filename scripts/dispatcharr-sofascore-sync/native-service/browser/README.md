# sofascore-browser

Verbatim copy of this project's own
`docker/browser-harness-patchright/{Dockerfile,launch_patchright_cdp.py}` --
the exact same image used for interactive browser-harness work on this Mac,
reused as-is on blackpearl.local as a headless, CDP-only sidecar for the
sofascore sync.

Do not diverge these two copies without a reason -- if the parent project's
browser-harness image gets a real fix (a new Patchright version, a Cloudflare
workaround, etc.), re-copy both files here rather than hand-patching.

Run headless, no VNC, CDP exposed only on the internal `upstream` docker
network (never published to the host) -- see compose-service.yml.snippet
in the parent directory for the exact service definition:

```yaml
environment:
  PATCHRIGHT_HEADLESS: "1"
  CDP_PORT: "9222"
```

Verified (2026-09-15, this Mac, plain Playwright smoke test before this CDP
rewrite): loading https://www.sofascore.com/ and calling its internal
api.sofascore.com endpoints via in-page fetch() clears Cloudflare's
TLS-fingerprint gate on that API host from inside ANY real browser network
stack -- no stealth flags, no Xvfb/VNC, no special anti-detection needed
for this specific target. Patchright is used here only because it's this
project's already-built, already-tested CDP-exposing image, not because
sofascore.com specifically requires Patchright's stealth patches.
