#!/bin/bash
# Runs sofascore_sync.py inside browser-harness against the project's
# isolated Patchright/VNC Chrome container. Safe to run every 15 minutes
# from cron or launchd.
#
# Secrets: put RIVE_ADMIN_TOKEN in ~/.config/dispatcharr-sofascore-sync/env
# (chmod 600, not committed to git) as:
#   RIVE_ADMIN_TOKEN=<the token you generated for blackpearl's .env.unified>
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SECRETS_FILE="$HOME/.config/dispatcharr-sofascore-sync/env"

if [ -f "$SECRETS_FILE" ]; then
  # shellcheck disable=SC1090
  source "$SECRETS_FILE"
fi

if [ -z "${RIVE_ADMIN_TOKEN:-}" ]; then
  echo "ERROR: RIVE_ADMIN_TOKEN not set. Create $SECRETS_FILE (chmod 600) with:" >&2
  echo "  RIVE_ADMIN_TOKEN=<token>" >&2
  exit 2
fi
export RIVE_ADMIN_TOKEN

export BU_NAME="browser_harness_patchright_project_kit"
export BU_CDP_URL="http://127.0.0.1:19322"

# Ensure Docker's CLI is reachable even from launchd's minimal PATH.
export PATH="/Applications/Docker.app/Contents/Resources/bin:/usr/local/bin:/opt/homebrew/bin:$PATH"

# Make sure the project browser container is up (idempotent).
"$PROJECT_ROOT/scripts/bh" status >/dev/null 2>&1 || true
if ! curl -s -o /dev/null -m 3 "$BU_CDP_URL/json/version"; then
  echo "Project browser container not reachable at $BU_CDP_URL -- attempting to (re)start it"
  "$PROJECT_ROOT/scripts/bh" run <<'PY' >/dev/null 2>&1 || true
print(page_info())
PY
  sleep 3
fi

for _ in 1 2 3 4 5 6; do
  if curl -s -o /dev/null -m 3 "$BU_CDP_URL/json/version"; then
    break
  fi
  sleep 5
done

if [[ " $* " == *" --apply "* ]]; then
  export SOFASCORE_SYNC_APPLY=1
fi

browser-harness < "$SCRIPT_DIR/sofascore_sync.py" 2>&1
