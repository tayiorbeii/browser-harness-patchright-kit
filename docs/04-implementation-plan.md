# 04. Implementation Plan

## Phase 1: Add templates to a project

Copy these files into the project:

```text
.browser-harness.env
docker/browser-harness-patchright/Dockerfile
docker/browser-harness-patchright/launch_patchright_cdp.py
scripts/bh
.codex/skills/browser-harness/SKILL.md
```

Make the wrapper executable:

```bash
chmod +x scripts/bh
```

## Phase 2: Configure project identity

Edit `.browser-harness.env`:

```bash
BH_PROJECT_SLUG=<repo-name>
BH_CONTAINER_NAME=bh-<repo-name>
BH_HOST_PORT=<unused localhost port>
BH_BU_NAME=<repo-name>
BH_PROFILE_VOLUME=bh-<repo-name>-profile
```

A good first port range is `19322`, `19323`, `19324`, etc.

## Phase 3: Build and launch

Run:

```bash
./scripts/bh status
./scripts/bh url
```

`url` should start the container if needed and print:

```text
http://127.0.0.1:<BH_HOST_PORT>
```

Check CDP manually:

```bash
curl -fsS "$(./scripts/bh url)/json/version" | python -m json.tool
```

## Phase 4: Smoke test browser-harness

Run:

```bash
./scripts/bh run -c $'reuse_tab("https://example.com", close_others=True)\nwait_for_load()\nprint(page_info())'
```

Expected result:

- container starts if missing;
- browser-harness daemon starts under `BU_NAME`;
- a page opens in the container browser;
- the user's normal Chrome session is untouched.

## Phase 5: Agent integration

Install the project skill in the agent's skill directory.

For Codex-style project skills:

```bash
mkdir -p .codex/skills/browser-harness
cp templates/skills/browser-harness/SKILL.md .codex/skills/browser-harness/SKILL.md
```

For Claude Code or another agent, place the skill body wherever that tool expects skills/instructions.

## Phase 6: Add developer docs

Add this short note to the project README or AGENTS.md:

```markdown
For browser automation, use `./scripts/bh run`, never plain `browser-harness`.
The wrapper uses the project's isolated Patchright Chrome container and will not attach to the user's normal browser.
```

## Phase 7: Validation matrix

Test:

1. First run, no image.
2. First run, image exists, no container.
3. Reuse existing running container.
4. Stop and restart container.
5. Change `.browser-harness.env` and confirm `./scripts/bh reload`.
6. Navigate to `https://example.com`.
7. Navigate to a host dev server via `host.docker.internal`.
8. Download a file and confirm it lands in `.browser-harness/downloads`.
9. Run two projects simultaneously with different ports and container names.
