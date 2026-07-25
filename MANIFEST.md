# Manifest

## Planning docs

- `docs/01-requirements.md`
- `docs/02-architecture.md`
- `docs/03-configuration-model.md`
- `docs/04-implementation-plan.md`
- `docs/05-security-and-operations.md`
- `docs/06-testing-and-acceptance.md`
- `docs/07-risks-and-open-questions.md`
- `docs/09-oracle-integration.md`

## Prompts

- `prompts/implementation-prompt.md`
- `prompts/implementation-checklist.md`

## Starter templates

- `templates/.browser-harness.env.template`
- `templates/docker-compose.browser-harness.yml`
- `templates/docker/browser-harness-patchright/Dockerfile`
- `templates/docker/browser-harness-patchright/launch_patchright_cdp.py`
- `templates/scripts/bh`
- `templates/scripts/oracle`
- `templates/.oracle/config.json`
- `templates/skills/browser-harness/SKILL.md`
- `templates/seccomp_userns_allow.fragment.json`

## Suggested target repo layout

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
