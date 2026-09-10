# Patchright Turnstile/Cloudflare challenge-loop investigation — denniskirk A7 container E2E

Date: 2026-09-10 · Kit: browser_harness_patchright_project_kit · Context: PR #685 A7 (denniskirk deep-audit E2E) blocked by Cloudflare managed-challenge loop in the container browser.

## Versions checked

| Artifact | Installed (start) | Upstream latest | Delta |
|---|---|---|---|
| patchright (python, in-container pip) | 1.61.1 (2026-06-29) | 1.62.3 (2026-09-02) | bumped |
| patchright driver (playwright-core) | 1.61.1-beta | 1.62.3 | bumped |
| patchright (npm/node) | — | 1.63.0 (2026-09-08) | n/a (python launcher) |
| Browser | Debian chromium 151.0.7922.173 (arm64) | — | 152.0.7977.82 after rebuild |
| Kit image | browser-harness-patchright:1.61.1-vnc-clipboard | — | :1.62.3-vnc-clipboard |

Upstream repos (pip metadata, corrected from the task brief): driver `Kaliiiiiiiiii-Vinyzu/patchright`, python `Kaliiiiiiiiii-Vinyzu/patchright-python`, node `Kaliiiiiiiiii-Vinyzu/patchright-nodejs`.

## Upstream changes 1.61.1 → 1.63.0 (driver commits)

- #222 (2026-07-11) fix old driver bugs, refactor/formatting, test workflows
- #229 (2026-08-17) Playwright v1.62.1 release-failure fix; new distribution channel
- #237 (2026-08-29) Fix Closed Shadow Roots, new custom tests
- #240 (2026-09-02) Fix negative nth selector boundary
- #242 (2026-09-08) Playwright v1.63.0 release-failure fix

**No commits touching turnstile/cloudflare/detection between 1.61.1 and 1.63.0** (keyword search: 0 hits). Patchright's Cloudflare claim in the README is tied to its `channel="chrome"` best practice, not to recent releases.

Most relevant issue: [#224 "Cloudflare Challenge Fails in GitHub Actions / Docker Containers but Succeeds Locally"](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright/issues/224) (2026-07-19, closed unconfirmed, no fix) — same signature as ours: identical config passes on the author's local Windows machine, loops in Linux CI/Docker. Upstream treats container-vs-local CF failure as environmental.

## Experiments and evidence

1. **Driver bump 1.61.1 → 1.62.3** (in-container, then baked into image). CDP healthy, Seer extension SW loads, denniskirk virgin load still instant-managed-challenge. Version is not the axis — matches #224.
2. **WebGL was entirely absent** (`getContext('webgl')` → null): without `--enable-unsafe-swiftshader`, Chromium refuses software WebGL. Restored the flag → `UNMASKED_RENDERER_WEBGL = ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (LLVM 16.0.0)), SwiftShader driver)`. Challenge still loops. SwiftShader-only GPU is unavoidable in Docker on macOS (no GPU passthrough).
3. **UA-CH brand leak**: UA string says `Chrome/151…` but `navigator.userAgentData.brands = [Chromium 151, Not=A?Brand 99]` — Debian Chromium is not branded Google Chrome. This is upstream's #1 documented leak driver ("We recommend using Google Chrome instead of Chromium"; best practice = `channel="chrome"`, headed, persistent context — we already do headed + persistent + no fingerprint injection).
4. **Chrome-channel attempt (amd64 + Rosetta)**: built `browser-harness-patchright:1.62.3-vnc-clipboard-chrome` (amd64, Google Chrome 153.0.8010.36). Chrome SIGKILLs at startup under Docker Desktop Rosetta (crashpad `prctl: EINVAL` → exit 137; reproduc headless; also with `--disable-crashpad` and `--security-opt seccomp=unconfined`; Rosetta confirmed installed and enabled). Google publishes no linux/arm64 Chrome, so the Chrome channel is **blocked on this Mac host** — viable only on a native amd64 Linux box.

## Residual bot signals (post-all-changes)

1. `navigator.userAgentData` brands say **Chromium** (no Google-Chrome build exists for linux/arm64).
2. **SwiftShader** WebGL renderer string (software GPU; no passthrough on macOS Docker).
3. **Container/Linux fingerprint cluster** matching upstream #224 (works locally, loops in container).
4. IP reputation unchanged (same egress as host; apparently fine for the user's real browser).

## Kit changes kept (local, tested)

- `docker/browser-harness-patchright/Dockerfile`: pin `PATCHRIGHT_VERSION=1.62.3`; new dormant `ARG INSTALL_GOOGLE_CHROME=0` block (opt-in Google Chrome install for native-amd64 Chrome-channel variants).
- `.browser-harness.env` (local-only, gitignored): `--enable-unsafe-swiftshader` restored in `PATCHRIGHT_EXTRA_ARGS` (WebGL parity with real browsers). Image tag now `browser-harness-patchright:1.62.3-vnc-clipboard` (rebuild: `docker build -t <tag> docker/browser-harness-patchright/`, then `./scripts/bh reload`).
- Chrome-channel image kept locally (`:1.62.3-vnc-clipboard-chrome`) for a future native-amd64 host; unused here.

## Conclusion / next steps

No upstream release fixes the loop; it is environment-bound (Chromium brand + SwiftShader + container signals per #224). A7's solve→resume leg must be verified in a **real browser**. If a native amd64 Linux host becomes available, rebuild with `--build-arg INSTALL_GOOGLE_CHROME=1 --platform linux/amd64` and set `PATCHRIGHT_BROWSER_EXECUTABLE=/opt/google/chrome/chrome` + `BH_DOCKER_PLATFORM=linux/amd64` — that is the one untested upstream-recommended lever.

---

## Addendum (same day, later): A7 container E2E + four extension defects

### Outcome

The Deep audit now completes end-to-end in the container: run `c20f2c12-79b7-4b0e-8d37-a2c08b0ba0ed`
→ state `COMPLETE`, with **U-DISC-01 (`/robots.txt`) and U-DISC-02 (`/sitemap.xml`) measured
same-origin** (real graded findings, not `runner_unavailable`). The genuine-challenge pause path was
also exercised live: pause with structural signals only (`cf-ray`, `challenge_platform_script`), user
solves in VNC, `cf_clearance` honored on reload.

### Extension defects found and fixed (seer repo, PR #685 branch `feat/denniskirk-error-sitemap-fix`)

| Commit | Defect |
|---|---|
| `21297c8a2c` | Challenge detector scanned **raw HTML** for generic CAPTCHA language, so a healthy page carrying `data-recaptcha="false"` produced a bogus `js_challenge_present` and mis-paused every Deep run. Generic markers now scan visible text only; structural Cloudflare markers (challenge-platform script, cf-turnstile class, interstitial titles) still catch real interstitials. |
| `9f67bc6b81` | Resume could never work in a real browser: `readPause` destructured `chrome.storage.local.get` off its StorageArea and invoked it detached → `Illegal invocation` → generic "The audit could not start." Also `recoverStaleDeepRuns` swept PAUSED runs after 5 minutes, deleting the checkpoint **while the user was still solving**. |
| `a839f50efb` | A paused run whose tab no longer exists (browser restart / user closed it) now retires as `ERROR/navigation_failed` with an actionable message and clears the pause key, instead of falling through the generic capture-failure path. |
| `d9cfb6d29e` | Resume/cancel pre-checks read durable state **outside** `start()`'s error mapping, so any rejection (IndexedDB read, malformed checkpoint URL, pause-key cleanup) still surfaced as the generic message. Now typed (`storage_unavailable` / `navigation_failed`); terminal-path cleanup is best-effort. |

### Operational gotcha: extension changes need a service-worker script-cache clear

Chrome executed a **cached copy of the extension's service worker** (old bundle) while the on-disk and
`chrome.runtime.getURL`-served file was the new build — and the cache **survives browser restarts**.
Evidence: the live exception stack pointed at bundle offset 66263, which in the current bundle is
audit-engine access-outcome code, not a storage call; the `Illegal invocation` disappeared only after
deleting the profile's `Default/Service Worker` directory. A plain container/browser restart is NOT enough.

Procedure after `bun scripts/sync-seer-extension.ts <extension-dir>`:

1. `docker stop bh-browser_harness_patchright_project_kit`
2. `docker run --rm -u root -v bh-browser_harness_patchright_project_kit-profile:/p --platform linux/arm64 --entrypoint sh browser-harness-patchright:1.62.3-vnc-clipboard -c 'rm -rf "/p/Default/Service Worker"'`
3. `docker start bh-browser_harness_patchright_project_kit` (CDP ready in ~10s)
4. Verify the staged bundle hash matches the worktree dist hash, and that `/json/list` shows the extension service worker.

Extension storage (`chrome.storage`, IndexedDB checkpoints, cookies) is preserved by this procedure, so a
paused run stays resumable. Candidate kit improvement: teach `scripts/bh reload` to clear the SW script
cache when the staged extension changed.
