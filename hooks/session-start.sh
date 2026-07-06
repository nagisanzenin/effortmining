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

# Ambient dispatch policy — a compact, model-facing nudge derived from the
# table itself, so a refit automatically changes the policy. Every echoed
# token is allowlist-sanitized (class slugs, tier names) per 03 A2.
TIERS = {"low", "medium", "high", "xhigh", "max"}
pairs = []
caveated = []
warnings = data.get("warnings") or []
warn_text = " ".join(w for w in warnings if isinstance(w, str))
for cls in sorted(classes):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,31}", cls):
        continue
    tier = (classes[cls] or {}).get("recommended_tier")
    if tier not in TIERS:
        continue
    mark = ""
    if cls in warn_text:
        mark = "*"
        caveated.append(cls)
    pairs.append(f"{cls}->miner-{tier}{mark}")

if pairs:
    policy = ("[effortmining] ambient dispatch policy: when delegating a subtask "
              "to a subagent, prefer the tier-pinned worker for its difficulty "
              "class instead of a default agent: " + " · ".join(pairs) + ".")
    if caveated:
        policy += (" (*fit rests on tasks flagged too easy; prefer miner-xhigh "
                   "for genuinely hard work in that class.)")
    policy += (" Classify by the /effortmine rubric; an explicit user effort "
               "request always overrides this policy.")
    print(policy)
PY
exit 0
