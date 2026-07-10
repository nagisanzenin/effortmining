#!/usr/bin/env bash
# effortmining - PostToolUse(Task) hook.
# Appends one telemetry line per subagent dispatch to dispatch-log.jsonl:
# {ts, source, tool_name, agent_type, session_effort, session_id}. The calibrate
# subcommand refits the calibration table from this log. Fail-open ALWAYS: this
# hook must never block or delay the Task tool. No network. Best-effort latency.
set -u

# Resolve plugin root (env, else self-locate relative to this script).
ROOT="${CLAUDE_PLUGIN_ROOT:-}"
if [ -z "$ROOT" ]; then
  ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)" 2>/dev/null || exit 0
fi

# python3 does the safe JSON parse plus escaped append; if absent, fail-open.
command -v python3 >/dev/null 2>&1 || exit 0

# Build the python program into a variable via a quoted heredoc (no shell
# expansion inside), then run it with `-c` so the hook's JSON payload stays on
# stdin for python to read. Passing the program as one quoted argument means the
# shell never re-parses it, and the untrusted payload never touches a command
# line. python builds the record with json.dumps (which escapes every field) and
# validates the effort level and agent-type slug before writing. Any error at
# all degrades to a silent exit 0.
read -r -d '' EFFORT_PYPROG <<'PY' || true
import json, os, re, sys, datetime

try:
    raw = sys.stdin.read()
except Exception:
    raw = ""
try:
    payload = json.loads(raw) if raw.strip() else {}
except Exception:
    payload = {}

tool_name = payload.get("tool_name")
if tool_name not in ("Task", "Agent"):
    # The matcher should guarantee this, but be defensive: only log dispatches.
    sys.exit(0)

tool_input = payload.get("tool_input") or {}

def bare(v):
    # A plugin-installed agent is addressed as "<plugin>:<agent>" (live:
    # "effortmining:miner-low"). Built-in agents carry no namespace.
    return v.rsplit(":", 1)[-1] if isinstance(v, str) else ""

# Field spelling varies across CLI surfaces (observed live: subagent_type absent
# on an Agent-tool dispatch). Try known spellings, then fall back to scanning
# string values for a tier-pinned worker name — the only value calibrate needs.
agent_type = (tool_input.get("subagent_type") or tool_input.get("subagentType")
              or tool_input.get("agent_type") or tool_input.get("agentType")
              or next((v for v in tool_input.values()
                       if bare(v).startswith("miner-")), None))
session_id = payload.get("session_id")

# Prefer effort.level from the payload; fall back to the env var. Note this is
# the PARENT turn's active effort (a PostToolUse hook fires in the caller), not
# the spawned subagent's effort; the dispatched tier is derivable from
# agent_type (miner-<tier>). Named session_effort so it does not overclaim.
effort = None
lvl = payload.get("effort")
if isinstance(lvl, dict):
    effort = lvl.get("level")
if effort is None:
    effort = os.environ.get("CLAUDE_EFFORT") or None

def slug(v):
    return v if isinstance(v, str) and re.fullmatch(r"[A-Za-z0-9._-]{1,64}", v) else None

def agent_slug(v):
    # Same bounded charset as slug(), plus one optional "<plugin>:" namespace.
    # Log the namespaced name verbatim rather than stripping it: it records which
    # plugin owned the dispatch, and readers normalize (see
    # normalize_dispatch_record). A bare slug() here silently nulls every
    # plugin-installed dispatch, which is the documented install path.
    return v if isinstance(v, str) and re.fullmatch(
        r"(?:[A-Za-z0-9._-]{1,64}:)?[A-Za-z0-9._-]{1,64}", v) else None

VALID_EFFORT = {"low", "medium", "high", "xhigh", "max"}
rec = {
    "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "source": "posttooluse-hook",
    "tool_name": tool_name,
    "agent_type": agent_slug(agent_type),
    "session_effort": effort if effort in VALID_EFFORT else None,
    "session_id": slug(session_id),
}

root = os.environ.get("EFFORT_ROOT", "")
state = os.path.join(root, "bench", "state")
try:
    os.makedirs(state, exist_ok=True)
    line = json.dumps(rec, ensure_ascii=True)
    with open(os.path.join(state, "dispatch-log.jsonl"), "a") as fh:
        fh.write(line + "\n")
except Exception:
    sys.exit(0)
sys.exit(0)
PY

EFFORT_ROOT="$ROOT" CLAUDE_EFFORT="${CLAUDE_EFFORT:-}" python3 -c "$EFFORT_PYPROG" 2>/dev/null || exit 0
exit 0
