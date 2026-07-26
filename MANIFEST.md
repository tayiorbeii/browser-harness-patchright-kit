# Manifest

This manifest enumerates the 37 intended repository files after the integrity-checker work. Runtime state, personal configuration, prompt-chain artifacts, transcripts, reports, caches, and generated outputs are intentionally excluded. The pre-commit invariant requires both new integrity scripts and the hook itself to be present in the staged index with their declared bytes and modes.

## Repository support (4)

- `.githooks/pre-commit`
- `.gitignore`
- `MANIFEST.md`
- `README.md`

## Planning docs (9)

- `docs/01-requirements.md`
- `docs/02-architecture.md`
- `docs/03-configuration-model.md`
- `docs/04-implementation-plan.md`
- `docs/05-security-and-operations.md`
- `docs/06-testing-and-acceptance.md`
- `docs/07-risks-and-open-questions.md`
- `docs/08-https-localhost-integration.md`
- `docs/09-oracle-integration.md`

## Prompts (2)

- `prompts/implementation-prompt.md`
- `prompts/implementation-checklist.md`

## Operational implementation and validation (12)

- `.browser-harness.env.example`
- `.codex/skills/browser-harness/SKILL.md`
- `.oracle/config.json`
- `docker-compose.browser-harness.yml`
- `docker/browser-harness-patchright/Dockerfile`
- `docker/browser-harness-patchright/launch_patchright_cdp.py`
- `scripts/bh`
- `scripts/check_repository_integrity.py`
- `scripts/oracle`
- `scripts/test-browser-harness-connection`
- `scripts/test-https-localhost-integration`
- `scripts/test-repository-integrity`

## Starter templates (10)

- `templates/.browser-harness.env.template`
- `templates/.gitignore.additions`
- `templates/.oracle/config.json`
- `templates/docker-compose.browser-harness.yml`
- `templates/docker/browser-harness-patchright/Dockerfile`
- `templates/docker/browser-harness-patchright/launch_patchright_cdp.py`
- `templates/scripts/bh`
- `templates/scripts/oracle`
- `templates/seccomp_userns_allow.fragment.json`
- `templates/skills/browser-harness/SKILL.md`

## Suggested target repository layout

Copy only the integration files a target repository needs; the kit-maintenance checker and its tests remain in this kit.

```text
.browser-harness.env.example
docker/browser-harness-patchright/Dockerfile
docker/browser-harness-patchright/launch_patchright_cdp.py
scripts/bh
scripts/oracle
scripts/test-browser-harness-connection
.oracle/config.json
.codex/skills/browser-harness/SKILL.md
```
