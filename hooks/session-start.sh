#!/usr/bin/env bash
# effortmining - SessionStart hook.
# Prints ONE ambient line when a calibration table exists; stays completely
# silent otherwise. Never blocks, never errors a session. Degrade-to-silence on
# every failure path. Any value echoed into the agent's context is validated
# first, because hook output is a prompt-injection surface (see 03 A2).
set -u

# Resolve plugin root: prefer the env the harness injects, else self-locate
# relative to this script (hooks/ -> plugin root).
ROOT="${CLAUDE_PLUGIN_ROOT:-}"
if [ -z "$ROOT" ]; then
  ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)" || exit 0
fi

CALIB="$ROOT/bench/state/calibration.json"

# No table yet -> nothing to say.
[ -f "$CALIB" ] || exit 0

# python3 is the JSON reader; if absent, degrade to silence.
command -v python3 >/dev/null 2>&1 || exit 0

# Compute the line in python (safe JSON parse plus output sanitization).
# The file path is passed via env, never on the command line.
CALIB="$CALIB" python3 - <<'PY' 2>/dev/null || exit 0
import json, os, re, sys

path = os.environ.get("CALIB", "")
try:
    with open(path, "r") as fh:
        data = json.load(fh)
except Exception:
    sys.exit(0)

classes = data.get("classes")
if not isinstance(classes, dict) or not classes:
    sys.exit(0)
n = len(classes)

version = data.get("version")
fitted = data.get("fitted_date")

# Sanitize before echoing into the agent's context.
if isinstance(fitted, str) and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", fitted):
    when = "fitted " + fitted
elif version in (0, None) or data.get("proven") is False:
    when = "pre-pilot defaults, unproven"
else:
    when = "fitted (date unknown)"

print(f"[effortmining] calibration table {n} cells, {when} · /effortmine to dispatch calibrated")
PY
exit 0
