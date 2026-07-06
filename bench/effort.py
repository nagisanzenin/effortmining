#!/usr/bin/env python3
"""effort.py — effortmining A/B benchmark harness (Python 3.14, stdlib only).

Produces the effortmining default calibration table: the cheapest reasoning-effort
tier per class of subagent task that is not measurably worse than `max`. Implements
the pre-registered protocol in docs/research/04-benchmark-methodology.md.

Subcommands
-----------
  validate    Phase 0 instrument gate (Section 4): per-tier probes, envelope
              enumeration, effort-modulation check, env sanitization, latency.
              Writes state/phase0.json. Gates `run`. `--mock` exercises plumbing.
  run         Execute the matrix (task x tier x rep). Seeded shuffle, concurrency,
              backoff, 300s timeout, env sanitization, resumable. Appends one
              record per run to raw/results.jsonl; raw answers to raw/answers/.
              `--mock` fabricates deterministic envelopes offline.
  grade       Apply each task's checker (exact / pytest-asserts sandbox) to the
              latest non-error result per cell. Writes state/graded.jsonl.
  analyze     Cell/class pass rates, Wilson & Newcombe CIs, non-inferiority calls,
              bootstrap CIs, RQ3 policy comparison. Writes state/analysis.json and
              state/calibration.json (v1).
  report      Render RESULTS.md from analysis.json (Section 8), no emoji.
  calibrate   Guarded refit (Section 7.2): min-N gate, single-step, clamped.
              Writes state/calibration.json.
  selftest    Run the mock pipeline end-to-end in a temp dir; assert invariants.

State-file map (paths are relative to --root, default = this file's directory)
-----------------------------------------------------------------------------
  raw/results.jsonl            append-only, one record per run          (gitignored)
  raw/answers/<run_id>.txt     raw model answer text                    (gitignored)
  state/phase0.json            Phase 0 instrument report + gate verdict (gitignored)
  state/graded.jsonl           graded outcomes, one per cell            (gitignored)
  state/analysis.json          full statistical analysis                (gitignored)
  state/calibration.json       the calibration table                    (COMMITTED)
  state/capture/               effort-fidelity capture hook + sidecar   (gitignored)
  state/dispatch-log.jsonl     B1 runtime dispatch receipts (dual-source, read by
                               calibrate; created lazily by the hook)   (gitignored)
  RESULTS.md                   human-readable report                    (committed)

Hard constraints honored: stdlib only; every write atomic (tempfile + os.replace);
results.jsonl append-only; model-generated code is executed ONLY inside grade's
sandbox; the only network call is the `claude` subprocess (never in --mock).
"""
from __future__ import annotations

import argparse
import concurrent.futures
import datetime as _dt
import glob
import hashlib
import json
import math
import os
import random
import secrets
import shlex
import shutil
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import uuid

# --------------------------------------------------------------------------- #
# Pre-registered constants (Appendix B of 04-benchmark-methodology.md).        #
# Fixed before any data is seen. Do not tune these to results.                 #
# --------------------------------------------------------------------------- #
TIERS = ["low", "medium", "high", "xhigh", "max"]
TIER_INDEX = {t: i for i, t in enumerate(TIERS)}
MODEL = "claude-opus-4-8"
SEED_DEFAULT = 20260706
PRICE_IN = 5.0 / 1_000_000      # $ / input token
PRICE_OUT = 25.0 / 1_000_000    # $ / output token
Z95 = 1.959963984540054         # normal quantile for a two-sided 95% interval
Z90 = 1.6448536269514722        # normal quantile for a two-sided 90% interval (TOST)
DELTA = 0.10                    # per-class non-inferiority margin (10 pp)
DELTA_AGG = 0.05               # policy-aggregate non-inferiority margin (5 pp)
DELTA_EQUIV = 0.10             # TOST equivalence margin for easy classes (10 pp)
EASY_CLASSES = {"T1-mechanical", "T2-simple-transform"}  # H1: equivalence-tested
RUN_TIMEOUT_S = 300            # per-run hard subprocess timeout
BOOTSTRAP_B = 10_000          # bootstrap resamples
MIN_N_REFIT = 9               # min graded outcomes per class-cell to move a tier
MODULATION_RATIO = 2.0        # Phase 0.3: median(max out) >= 2x median(low out)
MISCLASS_LOW_PASS = 0.80      # task flagged possibly-mis-classed if low pass >= this
GRADE_TIMEOUT_CEILING_S = 30  # hard ceiling on any task's pytest timeout
SANDBOX_AS_BYTES = 2 * 1024 ** 3  # best-effort address-space cap for the sandbox
BACKOFF_BASE = 2.0            # exponential backoff base (seconds)
BACKOFF_CAP = 60.0           # backoff cap (seconds)
MAX_RETRIES = 5              # retries on transient (rate-limit / 5xx / timeout) errors
FIDELITY_RETRIES = 2         # retries when requested != effective / unverified (04 4.6)

# Per-tier output-token estimates (04 Section 3.2), used ONLY by --mock to shape
# plausible envelopes. Real runs read tokens from the CLI envelope.
MOCK_BASE_OUT = {"low": 120, "medium": 400, "high": 1000, "xhigh": 2200, "max": 4500}

# Scale options (04 Section 3.2). `classes=None` means all four classes.
SCALES = {
    "pilot":    {"reps": 3, "classes": None},
    "fallback": {"reps": 2, "classes": None},
    "reduced":  {"reps": 3, "classes": {"T1-mechanical", "T2-simple-transform"}},
    "extended": {"reps": 5, "classes": None},
}

# Env vars that must never leak into a child `claude` process (04 Section 4.4).
EFFORT_ENV_OVERRIDE = "CLAUDE_CODE_EFFORT_LEVEL"   # overrides --effort; hard error
EXTRA_BODY_ENV = "CLAUDE_CODE_EXTRA_BODY"          # strip if it carries effort
MAX_OUTPUT_TOKENS_ENV = "CLAUDE_CODE_MAX_OUTPUT_TOKENS"  # must not be set by us
API_KEY_ENV = "ANTHROPIC_API_KEY"                  # must not be injected (billing)

_RESULTS_LOCK = threading.Lock()

# Detect transient failures worth an exponential-backoff retry.
_TRANSIENT_RE = None
def _transient(text: str) -> bool:
    import re
    global _TRANSIENT_RE
    if _TRANSIENT_RE is None:
        _TRANSIENT_RE = re.compile(
            r"(rate.?limit|429|overload|529|5\d\d\b|temporarily|timed?.?out|"
            r"timeout|connection|econn|socket|network|unavailable|eof)",
            re.IGNORECASE)
    return bool(_TRANSIENT_RE.search(text or ""))


def _is_transient_failure(res, env_json) -> bool:
    """Decide whether a failed `claude` invocation is worth a backoff retry.

    Rate-limit / overload / 5xx signatures are trusted ONLY from stderr or a
    parsed error field — never from stdout. Model output legitimately contains
    words like "timeout" or "429" as task data, and scanning it for transient
    patterns caused spurious retries (review L9). A timeout or an is_error
    envelope is transient regardless.
    """
    if getattr(res, "timed_out", False):
        return True
    err_field = ""
    if isinstance(env_json, dict):
        ef = env_json.get("error")
        if isinstance(ef, str):
            err_field = ef
        elif env_json.get("is_error"):
            err_field = str(env_json.get("result") or "")
    if _transient(getattr(res, "stderr", "") or "") or _transient(err_field):
        return True
    return bool(isinstance(env_json, dict) and env_json.get("is_error"))


# --------------------------------------------------------------------------- #
# Paths                                                                        #
# --------------------------------------------------------------------------- #
class Paths:
    """Resolves all harness file locations from a single root."""

    def __init__(self, root: str, tasks_dir: str | None = None):
        self.root = os.path.abspath(root)
        self.tasks = os.path.abspath(tasks_dir) if tasks_dir else os.path.join(self.root, "tasks")
        self.state = os.path.join(self.root, "state")
        self.raw = os.path.join(self.root, "raw")
        self.answers = os.path.join(self.raw, "answers")
        self.results = os.path.join(self.raw, "results.jsonl")
        self.phase0 = os.path.join(self.state, "phase0.json")
        self.graded = os.path.join(self.state, "graded.jsonl")
        self.analysis = os.path.join(self.state, "analysis.json")
        self.calibration = os.path.join(self.state, "calibration.json")
        self.results_md = os.path.join(self.root, "RESULTS.md")

    def ensure(self) -> None:
        for d in (self.state, self.raw, self.answers):
            os.makedirs(d, exist_ok=True)


def default_root() -> str:
    return os.path.dirname(os.path.abspath(__file__))


# --------------------------------------------------------------------------- #
# Atomic IO (tempfile + os.replace) and corruption-quarantining JSONL reader   #
# --------------------------------------------------------------------------- #
def atomic_write_text(path: str, text: str) -> None:
    """Write `text` to `path` atomically: full-content temp file then os.replace.

    A crash before os.replace leaves the original untouched and no partial file
    at the destination; the temp file is removed on any error.
    """
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-", suffix=".swap")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            if os.path.exists(tmp):
                os.unlink(tmp)
        finally:
            raise


def atomic_write_json(path: str, obj) -> None:
    atomic_write_text(path, json.dumps(obj, indent=2) + "\n")


def append_jsonl(path: str, record: dict) -> None:
    """Append one JSON record as a line. Serialized across threads by a lock.

    Append-only: never rewrites existing lines. A crash mid-write can leave a
    partial trailing line, which read_jsonl() quarantines on the next read.
    """
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    line = json.dumps(record) + "\n"
    with _RESULTS_LOCK:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())


def read_jsonl(path: str) -> tuple[list[dict], int]:
    """Read a JSONL file, skipping (quarantining) any unparseable line.

    Returns (records, quarantined_count). A quarantined partial trailing line is
    copied to `<path>.corrupt` for forensics and skipped, so a torn append never
    aborts a resume.
    """
    if not os.path.exists(path):
        return [], 0
    records, bad, bad_lines = [], 0, []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            try:
                records.append(json.loads(s))
            except json.JSONDecodeError:
                bad += 1
                bad_lines.append(line)
    if bad_lines:
        try:
            with open(path + ".corrupt", "a", encoding="utf-8") as cf:
                cf.writelines(bad_lines)
        except OSError:
            pass
    return records, bad


def load_json(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# --------------------------------------------------------------------------- #
# Task loading, matrix, seeded shuffle                                         #
# --------------------------------------------------------------------------- #
def load_tasks(tasks_dir: str) -> list[dict]:
    files = sorted(glob.glob(os.path.join(tasks_dir, "*.json")))
    if not files:
        raise SystemExit(f"no task files found in {tasks_dir}")
    tasks = []
    for f in files:
        t = load_json(f)
        t["prompt_text"] = "\n".join(t["prompt"])
        tasks.append(t)
    return tasks


def build_cells(tasks: list[dict], scale: str) -> list[dict]:
    """Build the (task, tier, rep) run list for a scale (before shuffling)."""
    if scale not in SCALES:
        raise SystemExit(f"unknown scale {scale!r}; choose from {list(SCALES)}")
    spec = SCALES[scale]
    reps, class_filter = spec["reps"], spec["classes"]
    cells = []
    for t in tasks:
        if class_filter is not None and t["class"] not in class_filter:
            continue
        for tier in TIERS:
            for rep in range(1, reps + 1):
                cells.append({"task": t, "tier": tier, "rep": rep})
    return cells


def seeded_shuffle(items: list, seed: int) -> list:
    """Return a deterministic shuffle: same seed -> same permutation."""
    out = list(items)
    random.Random(seed).shuffle(out)
    return out


def cell_key(task_id: str, tier: str, rep: int) -> tuple[str, str, int]:
    return (task_id, tier, int(rep))


def run_id_of(task_id: str, tier: str, rep: int) -> str:
    return f"{task_id}__{tier}__r{rep}"


# --------------------------------------------------------------------------- #
# Environment sanitization (04 Section 4.4)                                    #
# --------------------------------------------------------------------------- #
def build_child_env(parent: dict | None = None) -> tuple[dict, dict]:
    """Construct the sanitized child env for a `claude` subprocess.

    Returns (env, audit). Guarantees:
      - CLAUDE_CODE_EFFORT_LEVEL removed (it overrides --effort).
      - CLAUDE_CODE_EXTRA_BODY removed iff it carries an output_config/effort key.
      - CLAUDE_CODE_MAX_OUTPUT_TOKENS never set by us (removed if present, so a
        tight cap cannot truncate the thinking tokens the effort dimension moves).
      - ANTHROPIC_API_KEY removed (inheriting it would switch billing off-plan).
    """
    src = dict(os.environ if parent is None else parent)
    audit = {
        "effort_level_override_present": EFFORT_ENV_OVERRIDE in src,
        "extra_body_stripped": False,
        "max_output_tokens_stripped": MAX_OUTPUT_TOKENS_ENV in src,
        "api_key_stripped": API_KEY_ENV in src,
    }
    src.pop(EFFORT_ENV_OVERRIDE, None)
    src.pop(MAX_OUTPUT_TOKENS_ENV, None)
    src.pop(API_KEY_ENV, None)
    if EXTRA_BODY_ENV in src:
        val = src[EXTRA_BODY_ENV]
        if "effort" in val or "output_config" in val:
            src.pop(EXTRA_BODY_ENV, None)
            audit["extra_body_stripped"] = True
    return src, audit


# --------------------------------------------------------------------------- #
# Statistics (stdlib implementations; no scipy/numpy)                          #
# --------------------------------------------------------------------------- #
def wilson_interval(k: int, n: int, z: float = Z95) -> tuple[float, float]:
    """Wilson score 95% interval for a binomial proportion k/n, clamped to [0,1]."""
    if n <= 0:
        return (0.0, 1.0)
    p = k / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = (p + z2 / (2 * n)) / denom
    margin = (z / denom) * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n))
    return (max(0.0, center - margin), min(1.0, center + margin))


def newcombe_diff_ci(k1: int, n1: int, k2: int, n2: int, z: float = Z95) -> tuple[float, float]:
    """Newcombe (1998) method-10 95% CI for the difference p1 - p2.

    Square-and-add of the two Wilson intervals (MOVER). Reference worked example
    (56/70 vs 48/80) yields ~(0.0524, 0.3339), matching the published value.
    """
    p1 = k1 / n1 if n1 else 0.0
    p2 = k2 / n2 if n2 else 0.0
    l1, u1 = wilson_interval(k1, n1, z)
    l2, u2 = wilson_interval(k2, n2, z)
    d = p1 - p2
    lo = d - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2)
    hi = d + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2)
    return (max(-1.0, lo), min(1.0, hi))


def percentile(sorted_vals: list[float], q: float) -> float:
    """Linear-interpolation percentile (q in [0,100]) over a sorted list."""
    if not sorted_vals:
        raise ValueError("percentile of empty sequence")
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    rank = (q / 100.0) * (len(sorted_vals) - 1)
    lo_i = int(math.floor(rank))
    hi_i = int(math.ceil(rank))
    if lo_i == hi_i:
        return float(sorted_vals[lo_i])
    frac = rank - lo_i
    return float(sorted_vals[lo_i] * (1 - frac) + sorted_vals[hi_i] * frac)


def bootstrap_ci(cells: dict, stat_fn, b: int = BOOTSTRAP_B, seed: int = SEED_DEFAULT
                 ) -> tuple[float, float, float]:
    """Stratified bootstrap: resample values *within each cell*, recompute stat_fn.

    `cells` maps cell-key -> list of per-run values. Returns (point, lo95, hi95).
    Seeded for reproducibility (same seed -> identical draws).
    """
    point = stat_fn(cells)
    if point is None:
        return (None, None, None)
    rng = random.Random(seed)
    # Sorted so the seeded resample sequence is independent of dict insertion /
    # graded.jsonl append order (review M1).
    keys = sorted(cells.keys())
    draws = []
    for _ in range(b):
        resampled = {}
        for kk in keys:
            vals = cells[kk]
            if vals:
                resampled[kk] = [vals[rng.randrange(len(vals))] for _ in vals]
            else:
                resampled[kk] = []
        v = stat_fn(resampled)
        if v is not None:
            draws.append(v)
    if not draws:
        return (point, None, None)
    draws.sort()
    return (point, percentile(draws, 2.5), percentile(draws, 97.5))


def noninferiority(k_t: int, n_t: int, k_max: int, n_max: int, delta: float = DELTA) -> dict:
    """Pre-registered NI decision (04 Section 5.4): point guard AND interval guard.

    A tier is non-inferior to `max` iff p_t >= p_max - delta AND the Newcombe lower
    bound for (p_t - p_max) >= -delta.
    """
    p_t = k_t / n_t if n_t else 0.0
    p_max = k_max / n_max if n_max else 0.0
    point_ok = p_t >= p_max - delta
    diff_lo, diff_hi = newcombe_diff_ci(k_t, n_t, k_max, n_max)
    interval_ok = diff_lo >= -delta
    return {
        "p_t": p_t, "p_max": p_max,
        "point_ok": bool(point_ok),
        "diff_lo": diff_lo, "diff_hi": diff_hi,
        "interval_ok": bool(interval_ok),
        "noninferior": bool(point_ok and interval_ok),
    }


# --------------------------------------------------------------------------- #
# Answer parsing and canonicalization (04 Section 2.1)                         #
# --------------------------------------------------------------------------- #
def canonicalize(text: str) -> str:
    """strip_outer_ws ; rstrip_each_line — the pre-registered canonical form."""
    return "\n".join(line.rstrip() for line in text.strip().split("\n"))


def extract_answer_tags(text: str) -> str | None:
    """Return text between the first <answer> and the next </answer>, else None."""
    import re
    m = re.search(r"<answer>(.*?)</answer>", text, re.DOTALL | re.IGNORECASE)
    return m.group(1) if m else None


def extract_code_block(text: str) -> str | None:
    """Return the LAST ```python block; fall back to the last fenced block."""
    import re
    blocks = re.findall(r"```([A-Za-z0-9_+\-]*)[ \t]*\r?\n(.*?)```", text, re.DOTALL)
    if not blocks:
        return None
    py = [code for lang, code in blocks if lang.lower() in ("python", "py", "python3")]
    if py:
        return py[-1]
    return blocks[-1][1]


# --------------------------------------------------------------------------- #
# Graders                                                                      #
# --------------------------------------------------------------------------- #
def grade_exact(raw: str, expected_lines: list[str]) -> tuple[bool, str, str]:
    inner = extract_answer_tags(raw)
    if inner is None:
        return (False, "parse_fail", "no <answer> tags")
    got = canonicalize(inner)
    want = canonicalize("\n".join(expected_lines))
    if got == want:
        return (True, "none", "exact match")
    return (False, "wrong_answer", f"got {got[:120]!r} != {want[:120]!r}")


class _SandboxResult:
    __slots__ = ("returncode", "stdout", "stderr", "timed_out")

    def __init__(self, returncode, stdout, stderr, timed_out):
        self.returncode, self.stdout, self.stderr, self.timed_out = (
            returncode, stdout, stderr, timed_out)


def _sandbox_preexec(cpu_s: int):
    """preexec_fn factory: apply best-effort resource limits in the child."""
    def _apply():
        try:
            import resource
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_s, cpu_s + 1))
            try:
                resource.setrlimit(resource.RLIMIT_AS, (SANDBOX_AS_BYTES, SANDBOX_AS_BYTES))
            except (ValueError, OSError):
                pass  # some platforms (macOS) may reject RLIMIT_AS; wall timeout backstops
            try:
                resource.setrlimit(resource.RLIMIT_NPROC, (64, 64))
            except (ValueError, OSError):
                pass
        except Exception:
            pass
    return _apply


def run_sandboxed(program: str, timeout_s: int) -> _SandboxResult:
    """Run model-generated `program` in an isolated subprocess.

    Honest scope: this is subprocess isolation, NOT a jail. We use `python3 -I -S`
    (isolated mode: ignores env/PYTHONPATH/user-site), a fresh temp CWD, a minimal
    env, POSIX resource limits (CPU seconds, address space), and a wall-clock
    timeout. Network is not hard-blocked on macOS without a sandbox profile; the
    residual risk is low (benign, model-generated coding tasks) and documented in
    RESULTS.md. On Linux/CI, wrap the interpreter in `unshare -n` for true network
    isolation. Model code is executed ONLY here.
    """
    workdir = tempfile.mkdtemp(prefix="effort-sbx-")
    try:
        src = os.path.join(workdir, "prog.py")
        with open(src, "w", encoding="utf-8") as f:
            f.write(program)
        env = {"PATH": "/usr/bin:/bin", "HOME": workdir, "LC_ALL": "C", "TMPDIR": workdir}
        try:
            proc = subprocess.run(
                [sys.executable, "-I", "-S", src],
                cwd=workdir, env=env, capture_output=True, text=True,
                timeout=timeout_s, preexec_fn=_sandbox_preexec(timeout_s))
            return _SandboxResult(proc.returncode, proc.stdout, proc.stderr, False)
        except subprocess.TimeoutExpired as e:
            return _SandboxResult(-1, e.stdout or "", e.stderr or "", True)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def grade_pytest(raw: str, checker: dict) -> tuple[bool, str, str]:
    code = extract_code_block(raw)
    if code is None:
        return (False, "parse_fail", "no code block")
    asserts = checker["asserts"]
    tmo = min(int(checker.get("timeout_s", 5)), GRADE_TIMEOUT_CEILING_S)
    # Per-run unguessable success sentinel (review L1): model code cannot forge a
    # pass by printing a fixed token and exiting before our asserts run, because
    # the token it would have to print is randomized every grading call.
    sentinel = "__EFFORTMINING_OK_" + secrets.token_hex(8) + "__"
    program = code + "\n\n" + "\n".join(asserts) + f"\n\nprint({sentinel!r})\n"
    res = run_sandboxed(program, tmo)
    if res.timed_out:
        return (False, "timeout", f"exceeded {tmo}s")
    if res.returncode == 0 and res.stdout.strip().endswith(sentinel):
        return (True, "none", f"{len(asserts)}/{len(asserts)} asserts")
    last = (res.stderr.strip().splitlines() or [""])[-1]
    # Per 04 Section 2.1: AssertionError / exception / missing entrypoint all map
    # to wrong_answer (a valid code block was parsed but is incorrect).
    return (False, "wrong_answer", last[:160] or f"exit {res.returncode}")


def grade_record(task: dict, raw: str) -> dict:
    ck = task["checker"]
    if ck["type"] == "exact":
        passed, fclass, detail = grade_exact(raw, ck["expected"])
    elif ck["type"] == "pytest-asserts":
        passed, fclass, detail = grade_pytest(raw, ck)
    else:
        passed, fclass, detail = (False, "wrong_answer", f"unknown checker {ck['type']}")
    return {"pass": passed, "checker_type": ck["type"],
            "failure_class": fclass, "checker_detail": detail}


# --------------------------------------------------------------------------- #
# claude invocation (real) and mock envelope fabrication                       #
# --------------------------------------------------------------------------- #
def detect_cli_version() -> str:
    try:
        out = subprocess.run(["claude", "--version"], capture_output=True, text=True, timeout=15)
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def detect_effective_effort(envelope: dict) -> str | None:
    """Best-effort read of the *effective* effort from the CLI envelope.

    Headless JSON does not currently expose per-run effort (01-mechanism §6): effort
    is only observable via hooks / CLAUDE_EFFORT. We scan defensively for a future
    field; when absent, callers fall back to the requested tier (validated live by
    the Phase 0.3 modulation check).
    """
    for key in ("effort", "effort_level", "effortLevel"):
        if isinstance(envelope.get(key), str):
            return envelope[key]
    usage = envelope.get("usage", {})
    if isinstance(usage, dict):
        for key in ("effort", "effort_level", "effortLevel"):
            if isinstance(usage.get(key), str):
                return usage[key]
    return None


def invoke_claude(prompt: str, tier: str, model: str, timeout_s: int, env: dict,
                  settings_path: str | None = None) -> _SandboxResult:
    cmd = ["claude", "-p", "--effort", tier, "--model", model,
           "--output-format", "json"]
    if settings_path:
        cmd += ["--settings", settings_path]
    cmd += [prompt]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s, env=env)
        return _SandboxResult(proc.returncode, proc.stdout, proc.stderr, False)
    except subprocess.TimeoutExpired as e:
        return _SandboxResult(-1, e.stdout or "", e.stderr or "", True)
    except FileNotFoundError:
        return _SandboxResult(127, "", "claude CLI not found on PATH", False)


# ---- Effort-fidelity capture hook (04 Section 4.6) ------------------------- #
# Headless JSON carries no effort field, so a silent downgrade is invisible in
# the envelope. We install a Stop hook (via a dedicated --settings file) whose
# stdin payload carries effort.level + session_id, append it to a sidecar JSONL,
# and join it to each run by session_id to record the EFFECTIVE effort.
_CAPTURE_SCRIPT = r'''import json, sys, datetime
try:
    p = json.loads(sys.stdin.read() or "{}")
except Exception:
    sys.exit(0)
eff = None
lvl = p.get("effort")
if isinstance(lvl, dict):
    eff = lvl.get("level")
rec = {"session_id": p.get("session_id"), "effort_level": eff,
       "ts": datetime.datetime.now(datetime.timezone.utc).isoformat()}
try:
    with open(sys.argv[1], "a") as f:
        f.write(json.dumps(rec) + "\n")
except Exception:
    pass
sys.exit(0)
'''


def setup_effort_capture(dirpath: str) -> tuple[str, str]:
    """Write the capture script + a --settings file that runs it on Stop.

    Returns (settings_path, sidecar_path). Fail-open by design: if the hook never
    fires, the run is recorded as `unverified` and excluded from its cell.
    """
    os.makedirs(dirpath, exist_ok=True)
    script_path = os.path.join(dirpath, "capture_effort.py")
    atomic_write_text(script_path, _CAPTURE_SCRIPT)
    sidecar = os.path.join(dirpath, "effort-capture.jsonl")
    cmd = f"{shlex.quote(sys.executable)} {shlex.quote(script_path)} {shlex.quote(sidecar)}"
    settings = {"hooks": {"Stop": [{"hooks": [
        {"type": "command", "command": cmd, "timeout": 10}]}]}}
    settings_path = os.path.join(dirpath, "capture-settings.json")
    atomic_write_json(settings_path, settings)
    return settings_path, sidecar


def effective_from_sidecar(sidecar_path: str, session_id: str) -> str | None:
    """Return the last captured effective effort for session_id, else None."""
    if not session_id or not os.path.exists(sidecar_path):
        return None
    recs, _ = read_jsonl(sidecar_path)
    hit = None
    for r in recs:
        if r.get("session_id") == session_id and r.get("effort_level"):
            hit = r["effort_level"]
    return hit


def _h01(*parts) -> float:
    """Deterministic hash of parts -> float in [0, 1)."""
    s = "|".join(str(p) for p in parts).encode("utf-8")
    return int.from_bytes(hashlib.sha256(s).digest()[:8], "big") / 2 ** 64


# Mock-only reference solutions (logic identical to bench/tools/validate_oracles.py
# REF, proven to pass all shipped asserts). Used SOLELY by --mock to fabricate a
# passing pytest answer so the offline pipeline has realistic gradeable payloads.
# Real runs never use these; the model under test never sees them.
_MOCK_SOLUTIONS = {
    "normalize_phone": (
        "def normalize_phone(s):\n"
        "    d = ''.join(c for c in s if c.isdigit())\n"
        "    if len(d) < 10:\n"
        "        return 'INVALID'\n"
        "    d = d[-10:]\n"
        "    return '(' + d[0:3] + ') ' + d[3:6] + '-' + d[6:10]\n"),
    "rle": (
        "def rle(s):\n"
        "    if not s:\n"
        "        return ''\n"
        "    out = []\n"
        "    c = s[0]\n"
        "    n = 1\n"
        "    for ch in s[1:]:\n"
        "        if ch == c:\n"
        "            n += 1\n"
        "        else:\n"
        "            out.append(c + (str(n) if n > 1 else ''))\n"
        "            c = ch\n"
        "            n = 1\n"
        "    out.append(c + (str(n) if n > 1 else ''))\n"
        "    return ''.join(out)\n"),
    "business_days": (
        "import datetime\n"
        "def business_days(a, b):\n"
        "    s = datetime.date.fromisoformat(a)\n"
        "    e = datetime.date.fromisoformat(b)\n"
        "    n = 0\n"
        "    d = s\n"
        "    while d <= e:\n"
        "        if d.weekday() < 5:\n"
        "            n += 1\n"
        "        d += datetime.timedelta(days=1)\n"
        "    return n\n"),
    "median": (
        "def median(nums):\n"
        "    s = sorted(nums)\n"
        "    n = len(s)\n"
        "    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2\n"),
    "final_balance": (
        "def final_balance(ev):\n"
        "    bal = 0\n"
        "    h = 0\n"
        "    for k, a in ev:\n"
        "        if k == 'deposit':\n"
        "            bal += a\n"
        "        elif k == 'withdraw':\n"
        "            if bal - h >= a:\n"
        "                bal -= a\n"
        "        elif k == 'hold':\n"
        "            h += a\n"
        "        elif k == 'release':\n"
        "            h = max(0, h - a)\n"
        "    return bal - h\n"),
    "resolve": (
        "def resolve(deps):\n"
        "    done = []\n"
        "    ds = set()\n"
        "    rem = set(deps)\n"
        "    while True:\n"
        "        ready = sorted(t for t in rem if all(p in ds for p in deps[t]))\n"
        "        if not ready:\n"
        "            break\n"
        "        p = ready[0]\n"
        "        done.append(p)\n"
        "        ds.add(p)\n"
        "        rem.discard(p)\n"
        "    return done\n"),
}

# Mock pass-probability by (class, tier): monotone in tier, harder classes pass
# later. Shapes plausible curves so the offline pipeline is non-degenerate. This
# is synthetic plumbing data, never a benchmark result.
_MOCK_PASS_PROB = {
    "T1-mechanical":         {"low": 0.70, "medium": 0.92, "high": 0.97, "xhigh": 0.98, "max": 0.99},
    "T2-simple-transform":   {"low": 0.40, "medium": 0.75, "high": 0.90, "xhigh": 0.95, "max": 0.97},
    "T3-moderate-reasoning": {"low": 0.20, "medium": 0.50, "high": 0.80, "xhigh": 0.90, "max": 0.93},
    "T4-hard-reasoning":     {"low": 0.10, "medium": 0.30, "high": 0.62, "xhigh": 0.82, "max": 0.90},
}


def mock_answer(task: dict, passed: bool) -> str:
    ck = task["checker"]
    if ck["type"] == "exact":
        if passed:
            inner = "\n".join(ck["expected"])
        else:
            inner = "WRONG_ANSWER_PLACEHOLDER"
        return f"Here is the result.\n<answer>\n{inner}\n</answer>\n"
    entry = ck["entrypoint"]
    if passed and entry in _MOCK_SOLUTIONS:
        code = _MOCK_SOLUTIONS[entry]
    else:
        code = f"def {entry}(*args, **kwargs):\n    return None\n"
    return f"Here is the solution.\n\n```python\n{code}```\n"


def mock_envelope(task: dict, tier: str, rep: int, seed: int) -> dict:
    cls = task["class"]
    p_pass = _MOCK_PASS_PROB.get(cls, {}).get(tier, 0.5)
    passed = _h01(seed, "pass", task["id"], tier, rep) < p_pass
    jitter = 0.85 + 0.30 * _h01(seed, "tok", task["id"], tier, rep)
    out_tok = int(MOCK_BASE_OUT[tier] * jitter)
    in_tok = int(2600 * (0.9 + 0.2 * _h01(seed, "in", task["id"], tier, rep)))
    cache_read = int(in_tok * 0.72)
    cost = in_tok * PRICE_IN + out_tok * PRICE_OUT
    dur = int(500 + out_tok * 8 * (0.8 + 0.4 * _h01(seed, "dur", task["id"], tier, rep)))
    answer = mock_answer(task, passed)
    return {
        "type": "result", "subtype": "success", "is_error": False,
        "duration_ms": dur, "duration_api_ms": int(dur * 0.9), "num_turns": 1,
        "result": answer, "session_id": "mock-" + hashlib.sha256(
            f"{task['id']}{tier}{rep}".encode()).hexdigest()[:16],
        "total_cost_usd": round(cost, 6),
        "usage": {"input_tokens": in_tok, "output_tokens": out_tok,
                  "cache_read_input_tokens": cache_read, "cache_creation_input_tokens": 0},
        "modelUsage": {MODEL: {"inputTokens": in_tok, "outputTokens": out_tok,
                               "costUSD": round(cost, 6)}},
    }


# --------------------------------------------------------------------------- #
# Record helpers                                                               #
# --------------------------------------------------------------------------- #
def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def envelope_to_record(env: dict, task: dict, tier: str, rep: int, *, scale: str,
                       seed: int, nonce: str, model: str, cli_version: str,
                       ts_start: str, exit_status: int, retries: int,
                       raw_answer_path: str, effort_effective: str,
                       effort_effective_source: str) -> dict:
    # Field names are bound verbatim to the R1-confirmed envelope (04 Section 9.3):
    # input_tokens/output_tokens/cache_*/total_cost_usd/model_usage/session_id.
    usage = env.get("usage", {}) if isinstance(env, dict) else {}
    tin = int(usage.get("input_tokens", 0) or 0)
    tout = int(usage.get("output_tokens", 0) or 0)
    cost = env.get("total_cost_usd")
    if cost is None:
        cost = tin * PRICE_IN + tout * PRICE_OUT
    return {
        "run_id": run_id_of(task["id"], tier, rep),
        "task_id": task["id"], "class": task["class"],
        "tier": tier, "effort_requested": tier,
        "effort_effective": effort_effective,
        "effort_effective_source": effort_effective_source,
        # requested==effective AND verified by a capture hook (04 Section 4.6);
        # a mismatch or an unverified run does not count toward its cell.
        "fidelity_ok": bool(effort_effective == tier
                            and effort_effective_source in ("hook", "mock")),
        "rep": rep, "scale": scale, "seed": seed, "nonce": nonce,
        "model": model, "cli_version": cli_version,
        "ts_start": ts_start, "ts_end": _now(),
        "duration_ms": int(env.get("duration_ms", 0) or 0),
        "session_id": env.get("session_id", ""),
        "input_tokens": tin, "output_tokens": tout, "total_tokens": tin + tout,
        "cache_creation_input_tokens": int(usage.get("cache_creation_input_tokens", 0) or 0),
        "cache_read_input_tokens": int(usage.get("cache_read_input_tokens", 0) or 0),
        "total_cost_usd": float(cost),
        "model_usage": env.get("modelUsage", {}) if isinstance(env, dict) else {},
        "raw_answer_path": raw_answer_path,
        "exit_status": exit_status, "api_error": False, "retries": retries,
    }


def error_record(task: dict, tier: str, rep: int, *, scale: str, seed: int,
                 nonce: str, model: str, cli_version: str, ts_start: str,
                 exit_status: int, retries: int, detail: str,
                 effort_effective: str = "unverified",
                 effort_effective_source: str = "none") -> dict:
    return {
        "run_id": run_id_of(task["id"], tier, rep),
        "task_id": task["id"], "class": task["class"],
        "tier": tier, "effort_requested": tier,
        "effort_effective": effort_effective,
        "effort_effective_source": effort_effective_source, "fidelity_ok": False,
        "rep": rep, "scale": scale, "seed": seed, "nonce": nonce,
        "model": model, "cli_version": cli_version,
        "ts_start": ts_start, "ts_end": _now(), "duration_ms": 0,
        "session_id": "", "input_tokens": 0, "output_tokens": 0, "total_tokens": 0,
        "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
        "total_cost_usd": 0.0, "model_usage": {},
        "raw_answer_path": "", "exit_status": exit_status,
        "api_error": True, "retries": retries, "error_detail": detail[:200],
    }


def record_valid(rec: dict) -> bool:
    """A run counts toward its cell iff it is non-error AND effort-fidelity-verified
    (requested == effective, confirmed by the capture hook). 04 Sections 4.6, 5.1."""
    return (not rec.get("api_error")) and bool(rec.get("fidelity_ok"))


def latest_by_key(records: list[dict]) -> dict:
    """Collapse append-only records to one per (task,tier,rep): the last non-error
    record if any, else the last record (an error). Makes resume + reruns correct.
    """
    best: dict = {}
    for r in records:
        key = cell_key(r["task_id"], r["tier"], r["rep"])
        cur = best.get(key)
        if cur is None:
            best[key] = r
            continue
        # Prefer non-error; among same error-status prefer later (file order).
        if cur.get("api_error") and not r.get("api_error"):
            best[key] = r
        elif cur.get("api_error") == r.get("api_error"):
            best[key] = r
    return best


# --------------------------------------------------------------------------- #
# Subcommand: run                                                             #
# --------------------------------------------------------------------------- #
def execute_cell(cell: dict, *, mock: bool, scale: str, seed: int, model: str,
                 cli_version: str, env: dict, paths: Paths,
                 settings_path: str | None = None, sidecar: str | None = None) -> dict:
    task, tier, rep = cell["task"], cell["tier"], cell["rep"]
    nonce = uuid.uuid4().hex
    prompt = f"[run-id: {nonce}]\n\n" + task["prompt_text"]
    ts_start = _now()
    rel_answer = os.path.join("raw", "answers", run_id_of(task["id"], tier, rep) + ".txt")

    if mock:
        env_json = mock_envelope(task, tier, rep, seed)
        answer = env_json["result"]
        atomic_write_text(os.path.join(paths.root, rel_answer), answer)
        # Mock simulates a successful capture: effective == requested, source=mock.
        return envelope_to_record(env_json, task, tier, rep, scale=scale, seed=seed,
                                  nonce=nonce, model=model, cli_version=cli_version,
                                  ts_start=ts_start, exit_status=0, retries=0,
                                  raw_answer_path=rel_answer, effort_effective=tier,
                                  effort_effective_source="mock")

    retries = 0
    fidelity_retries = 0
    last_detail = ""
    while True:
        res = invoke_claude(prompt, tier, model, RUN_TIMEOUT_S, env, settings_path)
        env_json = None
        if res.returncode == 0 and res.stdout.strip():
            try:
                env_json = json.loads(res.stdout)
            except json.JSONDecodeError:
                env_json = None
        ok = env_json is not None and not env_json.get("is_error", False)
        if ok:
            # Join the capture-hook sidecar by session_id to read EFFECTIVE effort.
            session_id = env_json.get("session_id", "")
            eff = effective_from_sidecar(sidecar, session_id) if sidecar else None
            if eff is None:
                eff = detect_effective_effort(env_json)
            if eff is None:
                effective, source = "unverified", "unverified"
            else:
                effective, source = eff, "hook"
            fidelity_ok = (effective == tier and source == "hook")
            # A downgrade or an unverified capture invalidates the run for its cell
            # (04 4.6): discard and retry, bounded so we never burn the budget.
            if not fidelity_ok and fidelity_retries < FIDELITY_RETRIES:
                fidelity_retries += 1
                last_detail = f"fidelity mismatch: requested={tier} effective={effective} src={source}"
                time.sleep(min(BACKOFF_CAP, BACKOFF_BASE * fidelity_retries) * (0.5 + random.random()))
                continue
            answer = env_json.get("result", "")
            atomic_write_text(os.path.join(paths.root, rel_answer), answer)
            return envelope_to_record(env_json, task, tier, rep, scale=scale, seed=seed,
                                      nonce=nonce, model=model, cli_version=cli_version,
                                      ts_start=ts_start, exit_status=res.returncode,
                                      retries=retries + fidelity_retries,
                                      raw_answer_path=rel_answer,
                                      effort_effective=effective,
                                      effort_effective_source=source)
        # failure: decide transient vs permanent (review L9: transient signatures
        # are trusted from stderr / a parsed error field only, never from stdout).
        last_detail = ((res.stderr or "") + " " + (res.stdout or "")[:200]).strip()
        transient = _is_transient_failure(res, env_json)
        if transient and retries < MAX_RETRIES:
            retries += 1
            delay = min(BACKOFF_CAP, BACKOFF_BASE * (2 ** (retries - 1)))
            delay *= 0.5 + random.random()
            time.sleep(delay)
            continue
        return error_record(task, tier, rep, scale=scale, seed=seed, nonce=nonce,
                            model=model, cli_version=cli_version, ts_start=ts_start,
                            exit_status=res.returncode, retries=retries + fidelity_retries,
                            detail=last_detail.strip() or "unknown failure")


def cmd_run(args) -> int:
    paths = Paths(args.root, args.tasks_dir)
    paths.ensure()
    tasks = load_tasks(paths.tasks)
    cells = build_cells(tasks, args.scale)
    cells = seeded_shuffle(cells, args.seed)

    prior, bad = read_jsonl(paths.results)
    if bad:
        print(f"[run] quarantined {bad} corrupt line(s) in results.jsonl")
    latest = latest_by_key(prior)
    # A cell is "completed" only if its latest run is fidelity-valid (non-error and
    # requested==effective); mismatched/unverified/error runs are re-attempted.
    completed = {k for k, r in latest.items() if record_valid(r)}

    # Optional: with --rerun-failed also re-run cells whose graded verdict is fail.
    rerun = set()
    if args.rerun_failed:
        graded, _ = read_jsonl(paths.graded)
        for k, gr in latest_by_key(graded).items():
            if gr.get("pass") is False:
                rerun.add(k)

    todo = []
    for c in cells:
        k = cell_key(c["task"]["id"], c["tier"], c["rep"])
        if k in completed and k not in rerun:
            continue
        todo.append(c)

    print(f"[run] scale={args.scale} model={args.model} mock={args.mock} "
          f"parallel={args.parallel} seed={args.seed}")
    print(f"[run] matrix={len(cells)} completed={len(completed)} "
          f"rerun_failed={len(rerun)} to_run={len(todo)}")

    # Phase 0 is a hard gate (04 Section 4): real runs require a passed instrument
    # gate. --force overrides (loud warning); mock never blocks.
    if not args.mock:
        gate_ok = False
        if os.path.exists(paths.phase0):
            try:
                gate_ok = bool(load_json(paths.phase0).get("gate_passed"))
            except (OSError, json.JSONDecodeError):
                gate_ok = False
        if not gate_ok:
            if args.force:
                print("[run] WARNING: Phase 0 gate not passed (state/phase0.json "
                      "absent or gate_passed=false) — proceeding anyway due to --force.")
            else:
                print("[run] BLOCKED: Phase 0 gate not passed. Run "
                      "`effort.py validate --model claude-opus-4-8` first, or pass "
                      "--force to override. (04 Section 4 hard gate.)")
                return 2

    if not todo:
        print("[run] nothing to do; matrix already complete.")
        return 0

    env, audit = build_child_env()
    settings_path = sidecar = None
    if not args.mock:
        if audit["effort_level_override_present"]:
            print(f"[run] WARNING: {EFFORT_ENV_OVERRIDE} was set in the parent env; "
                  "stripped it for children (it overrides --effort).")
        settings_path, sidecar = setup_effort_capture(os.path.join(paths.state, "capture"))
        print(f"[run] effort-capture hook installed (sidecar: "
              f"{os.path.relpath(sidecar, paths.root)})")
    cli_version = "mock" if args.mock else detect_cli_version()

    done = 0
    errors = 0
    workers = 1 if args.mock else max(1, args.parallel)
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(execute_cell, c, mock=args.mock, scale=args.scale,
                          seed=args.seed, model=args.model, cli_version=cli_version,
                          env=env, paths=paths, settings_path=settings_path,
                          sidecar=sidecar): c for c in todo}
        invalid = 0
        for fut in concurrent.futures.as_completed(futs):
            rec = fut.result()
            append_jsonl(paths.results, rec)
            done += 1
            if rec.get("api_error"):
                errors += 1
            elif not rec.get("fidelity_ok"):
                invalid += 1  # requested != effective or unverified capture
            if done % 10 == 0 or done == len(todo):
                print(f"[run] {done}/{len(todo)} appended "
                      f"({errors} api_error, {invalid} fidelity-invalid)")
    print(f"[run] complete: {done} runs appended to {os.path.relpath(paths.results, paths.root)} "
          f"({errors} api_error, {invalid} fidelity-invalid — excluded from cells)")
    return 0


# --------------------------------------------------------------------------- #
# Subcommand: grade                                                           #
# --------------------------------------------------------------------------- #
def cmd_grade(args) -> int:
    paths = Paths(args.root, args.tasks_dir)
    paths.ensure()
    tasks = {t["id"]: t for t in load_tasks(paths.tasks)}
    results, bad = read_jsonl(paths.results)
    if bad:
        print(f"[grade] quarantined {bad} corrupt result line(s)")
    latest = latest_by_key(results)

    prior_graded, _ = read_jsonl(paths.graded)
    prior_by_key = latest_by_key(prior_graded) if prior_graded else {}

    graded_out = []
    n_pass = n_fail = n_reused = n_new = excluded_fidelity = 0
    tax = {"none": 0, "wrong_answer": 0, "parse_fail": 0, "timeout": 0, "api_error": 0}
    for key, rec in latest.items():
        if rec.get("api_error"):
            tax["api_error"] += 1
            continue  # nothing to grade; excluded from quality per 04 Section 5.1
        if not rec.get("fidelity_ok"):
            # requested != effective, or effective unverified: invalid for its cell
            # (04 Section 4.6) — excluded from quality just like api_error.
            excluded_fidelity += 1
            continue
        task = tasks.get(rec["task_id"])
        if task is None:
            continue
        prev = prior_by_key.get(key)
        if (not args.regrade and prev is not None and prev.get("nonce") == rec.get("nonce")
                and "pass" in prev):
            merged = dict(prev)
            n_reused += 1
        else:
            answer_path = os.path.join(paths.root, rec["raw_answer_path"])
            try:
                with open(answer_path, "r", encoding="utf-8") as f:
                    raw = f.read()
            except OSError:
                # answer file missing: treat as parse_fail so the cell still counts.
                g = {"pass": False, "checker_type": task["checker"]["type"],
                     "failure_class": "parse_fail", "checker_detail": "answer file missing"}
                merged = {**rec, **g}
                n_new += 1
                graded_out.append(merged)
                tax["parse_fail"] += 1
                n_fail += 1
                continue
            g = grade_record(task, raw)
            merged = {**rec, **g}
            n_new += 1
        graded_out.append(merged)
        tax[merged["failure_class"]] = tax.get(merged["failure_class"], 0) + 1
        if merged["pass"]:
            n_pass += 1
        else:
            n_fail += 1

    # graded.jsonl is a derived, full-rewrite file (results.jsonl remains the
    # append-only source of truth). Atomic whole-file write.
    body = "".join(json.dumps(r) + "\n" for r in graded_out)
    atomic_write_text(paths.graded, body)
    print(f"[grade] graded {len(graded_out)} cells: {n_pass} pass, {n_fail} fail "
          f"({n_new} new, {n_reused} reused; {excluded_fidelity} excluded: fidelity)")
    print(f"[grade] taxonomy: {tax}")
    print(f"[grade] wrote {os.path.relpath(paths.graded, paths.root)}")
    return 0


# --------------------------------------------------------------------------- #
# Subcommand: analyze                                                         #
# --------------------------------------------------------------------------- #
def _class_of(tid: str, tasks: dict) -> str:
    return tasks[tid]["class"]


def _step_toward(cur: str, target: str) -> str:
    ci, ti = TIER_INDEX[cur], TIER_INDEX[target]
    if ti == ci:
        return cur
    ni = ci + (1 if ti > ci else -1)
    ni = max(0, min(len(TIERS) - 1, ni))
    return TIERS[ni]


def analyze_core(tasks: dict, graded: list[dict], seed: int) -> dict:
    """Compute the full analysis object (04 Sections 5-6). Pure function of inputs."""
    classes = sorted({t["class"] for t in tasks.values()})
    task_ids = sorted(tasks.keys())
    tiers_present = [t for t in TIERS if any(g["tier"] == t for g in graded)]

    # Per-cell = (task, tier)
    per_cell = {}
    cell_pass_vals = {}   # (task,tier) -> list[int 0/1]
    cell_out_vals = {}    # (task,tier) -> list[out tokens]
    for g in graded:
        key = (g["task_id"], g["tier"])
        cell_pass_vals.setdefault(key, []).append(1 if g["pass"] else 0)
        cell_out_vals.setdefault(key, []).append(int(g.get("output_tokens", 0)))
    # Canonicalize within-cell value order so the seeded bootstrap (which indexes
    # into these lists) is independent of graded.jsonl append order (review M1).
    # Pass and out values are consumed independently — never paired per run — so
    # sorting each list on its own does not corrupt any statistic.
    for vals in cell_pass_vals.values():
        vals.sort()
    for vals in cell_out_vals.values():
        vals.sort()
    for key in sorted(cell_pass_vals.keys()):
        passes = cell_pass_vals[key]
        n = len(passes)
        k = sum(passes)
        lo, hi = wilson_interval(k, n)
        outs = cell_out_vals[key]
        per_cell[f"{key[0]}|{key[1]}"] = {
            "task_id": key[0], "tier": key[1], "n": n, "passes": k,
            "pass_rate": k / n if n else 0.0, "wilson": [lo, hi],
            "median_out": statistics.median(outs) if outs else 0,
        }

    def cell_mean_pass(tid, tier):
        v = cell_pass_vals.get((tid, tier))
        return (sum(v) / len(v)) if v else None

    def cell_mean_out(tid, tier):
        v = cell_out_vals.get((tid, tier))
        return (sum(v) / len(v)) if v else None

    # Per (class, tier) pooled — the calibration unit (9 trials/cell at n=3)
    pooled = {}  # (class,tier) -> {k,n, out_vals}
    for g in graded:
        cls = tasks[g["task_id"]]["class"]
        key = (cls, g["tier"])
        d = pooled.setdefault(key, {"k": 0, "n": 0, "out": []})
        d["k"] += 1 if g["pass"] else 0
        d["n"] += 1
        d["out"].append(int(g.get("output_tokens", 0)))

    def pooled_pass(cls, tier):
        d = pooled.get((cls, tier))
        return (d["k"] / d["n"]) if d and d["n"] else 0.0

    per_class = {}
    for cls in classes:
        # Reference = empirical quality-ceiling tier: arg-max pooled pass rate,
        # ties -> cheaper (lower-index) tier. Per H3 this may be xhigh, not max, so
        # we never anchor non-inferiority to a possibly-degraded max (04 Section 5.4).
        present = [t for t in TIERS if pooled.get((cls, t))]
        ref_tier = (max(present, key=lambda t: (pooled_pass(cls, t), -TIER_INDEX[t]))
                    if present else "max")
        dref = pooled.get((cls, ref_tier))
        k_ref = dref["k"] if dref else 0
        n_ref = dref["n"] if dref else 0

        tiers_info = {}
        candidates = []  # (median_out, total_out, tier_index, tier)
        for tier in TIERS:
            d = pooled.get((cls, tier))
            if not d:
                continue
            k, n = d["k"], d["n"]
            lo, hi = wilson_interval(k, n)
            ni = noninferiority(k, n, k_ref, n_ref)
            med_out = statistics.median(d["out"]) if d["out"] else 0
            tot_out = sum(d["out"])
            tiers_info[tier] = {
                "n": n, "passes": k, "pass_rate": k / n if n else 0.0,
                "wilson": [lo, hi], "median_out": med_out, "total_out": tot_out,
                "point_ok": ni["point_ok"], "interval_ok": ni["interval_ok"],
                "diff_lo": ni["diff_lo"], "diff_hi": ni["diff_hi"],
                "noninferior": ni["noninferior"],
            }
            # The reference tier is non-inferior to itself by definition (always a
            # candidate); other tiers must clear both guards. Guarantees a non-empty
            # candidate set even when small-n intervals never clear.
            if tier == ref_tier or ni["noninferior"]:
                candidates.append((med_out, tot_out, TIER_INDEX[tier], tier))
        recommended = min(candidates)[3] if candidates else ref_tier
        # Confidence: high only if the recommendation rests on real interval
        # evidence and no strictly-cheaper tier is point-OK-but-interval-ambiguous.
        rec_info = tiers_info.get(recommended, {})
        cheaper_ambiguous = any(
            info["point_ok"] and not info["interval_ok"]
            for tier, info in tiers_info.items()
            if TIER_INDEX[tier] < TIER_INDEX[recommended])
        confidence = "high" if (rec_info.get("interval_ok") and not cheaper_ambiguous) else "low"

        # H1 (easy classes): TOST equivalence of `low` vs the ceiling. `low` is
        # equivalent iff the 90% Newcombe CI of (p_low - p_ref) lies entirely within
        # [-DELTA_EQUIV, +DELTA_EQUIV]; passing upgrades confidence to high(equiv).
        equivalence_low = None
        dlow = pooled.get((cls, "low"))
        if cls in EASY_CLASSES and dlow and n_ref:
            lo90, hi90 = newcombe_diff_ci(dlow["k"], dlow["n"], k_ref, n_ref, Z90)
            equivalence_low = bool(lo90 >= -DELTA_EQUIV and hi90 <= DELTA_EQUIV)
            if equivalence_low:
                confidence = "high(equiv)"

        # H3 overthinking (04 Section 5.4). Surfaced split (review M4):
        #   flag              — pre-registered rule: p_max <= p_xhigh AND max tokens up
        #   strict_regression — the stronger p_max <  p_xhigh (quality actually drops)
        # strict_regression implies flag; the two are worded differently downstream.
        ot_flag = ot_strict = False
        dmax, dxh = pooled.get((cls, "max")), pooled.get((cls, "xhigh"))
        if dmax and dxh and dmax["n"] and dxh["n"]:
            m_max = statistics.median(dmax["out"]) if dmax["out"] else 0
            m_xh = statistics.median(dxh["out"]) if dxh["out"] else 0
            p_max, p_xh = dmax["k"] / dmax["n"], dxh["k"] / dxh["n"]
            tokens_up = m_max > m_xh
            ot_flag = bool(p_max <= p_xh and tokens_up)
            ot_strict = bool(p_max < p_xh and tokens_up)
        overthinking = {"flag": ot_flag, "strict_regression": ot_strict}

        # Mis-classed-task check: pooled low-tier pass >= 0.80 -> possibly too easy.
        misclassed = []
        for tid in task_ids:
            if tasks[tid]["class"] != cls:
                continue
            lowp = cell_mean_pass(tid, "low")
            if lowp is not None and lowp >= MISCLASS_LOW_PASS:
                misclassed.append({"task_id": tid, "low_pass": lowp})

        per_class[cls] = {
            "recommended_tier": recommended, "confidence": confidence,
            "ceiling_tier": ref_tier,
            "pass_rate_ref": (k_ref / n_ref) if n_ref else 0.0,
            "n_graded_recommended": tiers_info.get(recommended, {}).get("n", 0),
            "delta_vs_ref": (tiers_info.get(recommended, {}).get("pass_rate", 0.0)
                             - ((k_ref / n_ref) if n_ref else 0.0)),
            "median_out_recommended": tiers_info.get(recommended, {}).get("median_out", 0),
            "equivalence_low": equivalence_low, "overthinking": overthinking,
            "tiers": tiers_info, "misclassed_tasks": misclassed,
        }

    # ---- RQ3 policy comparison (04 Section 5.5) ----
    def policy_tier_for(tid, policy):
        if policy == "calibrated":
            return per_class[tasks[tid]["class"]]["recommended_tier"]
        return {"inherit_xhigh": "xhigh", "uniform_high": "high",
                "uniform_max": "max", "uniform_low": "low"}[policy]

    policy_names = ["inherit_xhigh", "uniform_high", "calibrated", "uniform_max", "uniform_low"]
    assign = {p: {tid: policy_tier_for(tid, p) for tid in task_ids} for p in policy_names}

    # Honest matrix (review M3): a task is comparable only if it has data under
    # EVERY policy's assigned tier. Otherwise per-policy token totals are summed
    # over different task sets and are not commensurable — a policy would look
    # cheap merely because the tasks it happens to cover are cheap. Totals, agg
    # pass, and every bootstrap stat are therefore computed over this fixed
    # intersection; tasks missing any policy's cell are dropped and reported.
    comparable_tasks = [tid for tid in task_ids
                        if all(cell_out_vals.get((tid, assign[p][tid]))
                               for p in policy_names)]
    dropped_tasks = [tid for tid in task_ids if tid not in comparable_tasks]
    incomplete_matrix = bool(dropped_tasks)

    def policy_tokens(tid_to_tier, cells_out):
        total = 0.0
        for tid in comparable_tasks:
            vals = cells_out.get((tid, tid_to_tier[tid]))
            if vals:
                total += sum(vals) / len(vals)
        return total

    def policy_pass(tid_to_tier, cells_pass):
        vals_mean = []
        for tid in comparable_tasks:
            v = cells_pass.get((tid, tid_to_tier[tid]))
            if v:
                vals_mean.append(sum(v) / len(v))
        return (sum(vals_mean) / len(vals_mean)) if vals_mean else None

    policies = {}
    for p in policy_names:
        policies[p] = {"tiers": assign[p],
                       "out_tokens": policy_tokens(assign[p], cell_out_vals),
                       "agg_pass": policy_pass(assign[p], cell_pass_vals)}

    # Bootstrap CIs on savings % (token) vs the two baselines, seeded.
    def savings_stat(baseline):
        def stat(cells):
            tb = policy_tokens(assign[baseline], cells)
            tc = policy_tokens(assign["calibrated"], cells)
            if tb <= 0:
                return None
            return (tb - tc) / tb * 100.0
        return stat

    sv_inherit = bootstrap_ci(cell_out_vals, savings_stat("inherit_xhigh"), seed=seed)
    sv_high = bootstrap_ci(cell_out_vals, savings_stat("uniform_high"), seed=seed)

    # Aggregate pass-rate difference CIs (calibrated - baseline), bootstrap on pass
    # bools within cells; non-inferior at DELTA_AGG if the lower bound >= -0.05.
    def passdiff_stat(baseline):
        def stat(cells):
            pc = policy_pass(assign["calibrated"], cells)
            pb = policy_pass(assign[baseline], cells)
            if pc is None or pb is None:
                return None
            return pc - pb
        return stat

    pd_inherit = bootstrap_ci(cell_pass_vals, passdiff_stat("inherit_xhigh"), seed=seed)
    pd_high = bootstrap_ci(cell_pass_vals, passdiff_stat("uniform_high"), seed=seed)
    pd_low = bootstrap_ci(cell_pass_vals, passdiff_stat("uniform_low"), seed=seed)

    # RQ3 Pareto victory (04 Section 5.5): calibrated is un-dominated by all three
    # baselines iff it saves tokens (CI excludes 0) at non-inferior quality vs
    # inherit@xhigh and uniform-high, AND strictly beats uniform-low on quality.
    ni_agg = (pd_inherit[1] is not None and pd_inherit[1] >= -DELTA_AGG
              and pd_high[1] is not None and pd_high[1] >= -DELTA_AGG)
    save_xhigh_ok = sv_inherit[1] is not None and sv_inherit[1] > 0
    save_high_ok = sv_high[1] is not None and sv_high[1] > 0
    gain_low_ok = pd_low[1] is not None and pd_low[1] > 0
    # An incomplete matrix cannot support a Pareto verdict: leave it null rather
    # than assert a false true/false from a partial task set (review M3).
    undominated = (None if incomplete_matrix
                   else bool(save_xhigh_ok and save_high_ok and ni_agg and gain_low_ok))

    seeds = {g.get("seed", seed) for g in graded}
    scales = {g.get("scale", "?") for g in graded}
    models = {g.get("model", MODEL) for g in graded}
    clis = {g.get("cli_version", "?") for g in graded}
    manifest = {
        "generated_at": _now(), "model": sorted(models),
        "cli_version": sorted(clis), "seed": sorted(seeds), "scale": sorted(scales),
        "classes": classes, "tiers_present": tiers_present,
        "n_graded": len(graded), "delta": DELTA, "delta_agg": DELTA_AGG,
        "delta_equiv": DELTA_EQUIV, "easy_classes": sorted(EASY_CLASSES),
        "bootstrap_resamples": BOOTSTRAP_B,
    }

    return {
        "manifest": manifest,
        "per_cell": per_cell,
        "per_class": per_class,
        "policies": policies,
        "policy_comparison": {
            "baselines": {"inherit_xhigh": "xhigh", "uniform_high": "high",
                          "uniform_low": "low"},
            "savings_pct_vs_inherit_xhigh": {"point": sv_inherit[0],
                                             "ci95": [sv_inherit[1], sv_inherit[2]]},
            "savings_pct_vs_uniform_high": {"point": sv_high[0],
                                            "ci95": [sv_high[1], sv_high[2]]},
            "quality_gain_vs_uniform_low": {"point": pd_low[0],
                                            "ci95": [pd_low[1], pd_low[2]]},
            "aggregate_pass_calibrated": policies["calibrated"]["agg_pass"],
            "aggregate_pass_inherit_xhigh": policies["inherit_xhigh"]["agg_pass"],
            "aggregate_pass_uniform_high": policies["uniform_high"]["agg_pass"],
            "aggregate_pass_uniform_low": policies["uniform_low"]["agg_pass"],
            "aggregate_pass_diff_vs_inherit_xhigh": {"point": pd_inherit[0],
                                                     "ci95": [pd_inherit[1], pd_inherit[2]]},
            "aggregate_pass_diff_vs_uniform_high": {"point": pd_high[0],
                                                    "ci95": [pd_high[1], pd_high[2]]},
            "noninferior_agg": bool(ni_agg),
            "incomplete_matrix": incomplete_matrix,
            "dropped_tasks": dropped_tasks,
            "comparable_task_count": len(comparable_tasks),
            "undominated": undominated,
        },
    }


def _policy_block(pc: dict) -> dict:
    """The calibration.json `policy` block (04 Section 7.1), from analysis."""
    return {
        "baselines": pc["baselines"],
        "savings_pct_vs_inherit_xhigh": pc["savings_pct_vs_inherit_xhigh"],
        "savings_pct_vs_uniform_high": pc["savings_pct_vs_uniform_high"],
        "quality_gain_vs_uniform_low": pc["quality_gain_vs_uniform_low"],
        "aggregate_pass_calibrated": pc["aggregate_pass_calibrated"],
        "noninferior_agg": pc["noninferior_agg"],
        "incomplete_matrix": pc.get("incomplete_matrix", False),
        "undominated": pc["undominated"],
    }


def _is_mock_manifest(manifest: dict) -> bool:
    """Mock runs stamp cli_version="mock" (cmd_run / cmd_validate); a real run
    never does. This is the manifest-level record of run.mock=True."""
    return "mock" in list(manifest.get("cli_version") or [])


def build_provenance(manifest: dict, fitted_from: str, runs: int | None = None) -> dict:
    """Stamp where a calibration table came from (review H1). `fitted_from` is
    "analysis" for a fresh fit or "refit" for a guarded refit."""
    clis = list(manifest.get("cli_version") or [])
    models = list(manifest.get("model") or [])
    graded = int(manifest.get("n_graded", 0) or 0)
    return {
        "mode": "mock" if _is_mock_manifest(manifest) else "real",
        "model": models[0] if models else MODEL,
        "cli_version": clis[0] if clis else "unknown",
        "runs": int(runs) if runs is not None else graded,
        "graded": graded,
        "fitted_from": fitted_from,
    }


def build_calibration_warnings(per_class: dict, mode: str) -> list:
    """Sanity guard (review H1): a real fit in which every class's quality ceiling
    is a perfect 1.0 AND a *hard* class collapses to `low` is almost certainly
    resting on tasks too easy for their class. Keep the fit, but surface the caveat
    — sourced from the misclassed_tasks field — so the ceiling-referenced rule is
    not trusted blindly."""
    warnings = []
    if mode != "real":
        return warnings
    ceilings = [info.get("pass_rate_ref", 0.0) for info in per_class.values()]
    if not (ceilings and all(abs(c - 1.0) < 1e-9 for c in ceilings)):
        return warnings
    for cls, info in per_class.items():
        if ("hard" in cls.lower() and info.get("recommended_tier") == "low"
                and info.get("misclassed_tasks")):
            warnings.append(f"class {cls} fit rests on tasks flagged misclassed")
    return warnings


def _overthinking_flag(ot) -> bool:
    """Read the pre-registered (<=) overthinking flag from either the new
    {flag, strict_regression} dict or the legacy bare bool (review M4 back-compat)."""
    return bool(ot.get("flag")) if isinstance(ot, dict) else bool(ot)


def build_calibration(analysis: dict, tasks: dict, runs: int | None = None) -> dict:
    per_class = analysis["per_class"]
    pc = analysis["policy_comparison"]
    manifest = analysis["manifest"]
    prov = build_provenance(manifest, "analysis", runs=runs)
    mock = prov["mode"] == "mock"
    classes = {}
    for cls, info in per_class.items():
        rec = info["recommended_tier"]
        classes[cls] = {
            "recommended_tier": rec,
            "confidence": info["confidence"],
            "n_graded": info["n_graded_recommended"],
            "fitted": True,
            "pass_rate": info["tiers"].get(rec, {}).get("pass_rate", 0.0),
            "ceiling_tier": info["ceiling_tier"],
            "pass_rate_ref": info["pass_rate_ref"],
            "delta_vs_ref": info["delta_vs_ref"],
            "median_out_tokens": info["median_out_recommended"],
            "equivalence_low": info["equivalence_low"],
            # Kept as the legacy <= flag bool for any external reader (review M4).
            "overthinking": _overthinking_flag(info["overthinking"]),
        }
    out = {
        # Mock never earns a proven table: version 0 / proven false regardless of
        # anything else (review H1). Real fits stamp version >= 1 / proven true.
        "version": 0 if mock else 1,
        "proven": (not mock),
        "provenance": prov,
        "fitted_date": None if mock else _dt.date.today().isoformat(),
        "model": (manifest["model"] or [MODEL])[0] if manifest["model"] else MODEL,
        "suite_version": "pilot-12",
        "margin_delta": DELTA,
        "classes": classes,
        "policy": _policy_block(pc),
    }
    warnings = build_calibration_warnings(per_class, prov["mode"])
    if warnings:
        out["warnings"] = warnings
    return out


def cmd_analyze(args) -> int:
    paths = Paths(args.root, args.tasks_dir)
    paths.ensure()
    tasks = {t["id"]: t for t in load_tasks(paths.tasks)}
    graded, bad = read_jsonl(paths.graded)
    if bad:
        print(f"[analyze] quarantined {bad} corrupt graded line(s)")
    if not graded:
        print("[analyze] no graded records; run grade first.")
        return 1
    # Analyze over one graded record per cell.
    raw_graded_count = len(graded)
    graded = list(latest_by_key(graded).values())
    seed = graded[0].get("seed", SEED_DEFAULT)
    analysis = analyze_core(tasks, graded, seed)
    atomic_write_json(paths.analysis, analysis)
    calibration = build_calibration(analysis, tasks, runs=raw_graded_count)
    atomic_write_json(paths.calibration, calibration)

    print(f"[analyze] {analysis['manifest']['n_graded']} cells over "
          f"{len(analysis['manifest']['classes'])} classes")
    for cls, info in analysis["per_class"].items():
        ot = " overthinking" if _overthinking_flag(info["overthinking"]) else ""
        print(f"[analyze]   {cls}: rec={info['recommended_tier']} "
              f"({info['confidence']}) ceiling={info['ceiling_tier']} "
              f"delta_vs_ref={info['delta_vs_ref']:+.3f}{ot}")
    sv = analysis["policy_comparison"]["savings_pct_vs_inherit_xhigh"]
    pt = 0.0 if sv["point"] is None else sv["point"]
    lo = float("nan") if sv["ci95"][0] is None else sv["ci95"][0]
    hi = float("nan") if sv["ci95"][1] is None else sv["ci95"][1]
    print(f"[analyze] savings vs inherit@xhigh: {pt:.1f}% CI[{lo:.1f}, {hi:.1f}]  "
          f"undominated={analysis['policy_comparison']['undominated']}")
    print(f"[analyze] wrote {os.path.relpath(paths.analysis, paths.root)} and "
          f"{os.path.relpath(paths.calibration, paths.root)}")
    return 0


# --------------------------------------------------------------------------- #
# Subcommand: report                                                          #
# --------------------------------------------------------------------------- #
def _bar(frac: float, width: int = 20) -> str:
    frac = max(0.0, min(1.0, frac))
    filled = int(round(frac * width))
    return "█" * filled + "░" * (width - filled)


def _fmt_pct(x) -> str:
    return "  n/a" if x is None else f"{x * 100:5.1f}%"


def render_report(analysis: dict, tasks: dict) -> str:
    m = analysis["manifest"]
    L = []
    L.append("# effortmining — Benchmark Results")
    L.append("")
    L.append("Auto-generated by `effort.py report` from `state/analysis.json`. "
             "Numbers are computed from graded runs; this file fabricates nothing.")
    L.append("")

    # 1. Run manifest
    L.append("## 1. Run manifest")
    L.append("")
    L.append(f"- Model: {', '.join(m['model'])}")
    L.append(f"- CLI version: {', '.join(str(c) for c in m['cli_version'])}")
    L.append(f"- Seed: {', '.join(str(s) for s in m['seed'])}")
    L.append(f"- Scale: {', '.join(str(s) for s in m['scale'])}")
    L.append(f"- Generated: {m['generated_at']}")
    L.append(f"- Graded cells: {m['n_graded']} · classes: {len(m['classes'])} · "
             f"tiers: {', '.join(m['tiers_present'])}")
    L.append(f"- Non-inferiority margin delta = {m['delta']} (per class), "
             f"{m['delta_agg']} (aggregate)")
    L.append("")

    # 2. Matrix table (pass rate + median out tokens per task x tier)
    L.append("## 2. Matrix — pass rate and median output tokens per (task, tier)")
    L.append("")
    tiers = m["tiers_present"]
    header = "task   " + "".join(f"| {t:^13}" for t in tiers)
    L.append("```")
    L.append(header)
    L.append("-------" + "".join("+" + "-" * 14 for _ in tiers))
    for tid in sorted(tasks.keys()):
        row = f"{tid:<7}"
        for t in tiers:
            c = analysis["per_cell"].get(f"{tid}|{t}")
            if c:
                row += f"| {c['pass_rate']*100:4.0f}% {c['median_out']:>6}t "
            else:
                row += f"| {'--':^13}"
        L.append(row)
    L.append("```")
    L.append("(cell = pass% and median output tokens; `--` = no data / excluded)")
    L.append("")

    # 3. Per-class curves (ASCII sparklines with Wilson CIs)
    L.append("## 3. Per-class curves (pass rate and output tokens vs tier)")
    L.append("")
    for cls in m["classes"]:
        info = analysis["per_class"][cls]
        L.append(f"### {cls}")
        L.append("")
        L.append("```")
        L.append(f"{'tier':<7} {'pass':>6}  {'Wilson 95%':<16} {'n':>3}  "
                 f"{'med.out':>8}  bar")
        for t in TIERS:
            ti = info["tiers"].get(t)
            if not ti:
                continue
            lo, hi = ti["wilson"]
            L.append(f"{t:<7} {ti['pass_rate']*100:5.0f}%  "
                     f"[{lo*100:4.0f},{hi*100:4.0f}]%      {ti['n']:>3}  "
                     f"{ti['median_out']:>8}  {_bar(ti['pass_rate'])}")
        L.append("```")
        rec = info["recommended_tier"]
        extra = []
        if info.get("ceiling_tier") and info["ceiling_tier"] != "max":
            extra.append(f"ceiling tier is {info['ceiling_tier']} (not max)")
        if info.get("equivalence_low") is True:
            extra.append("low is statistically equivalent to ceiling (TOST)")
        ot = info.get("overthinking") or {}
        if _overthinking_flag(ot):
            if isinstance(ot, dict) and ot.get("strict_regression"):
                extra.append("quality regression at max")
            else:
                extra.append("saturated: max buys no quality at higher cost")
        suffix = ("; " + "; ".join(extra)) if extra else ""
        L.append(f"Recommended: **{rec}** (confidence: {info['confidence']}, "
                 f"delta vs ceiling: {info['delta_vs_ref']:+.3f}{suffix})")
        if info["misclassed_tasks"]:
            names = ", ".join(f"{x['task_id']} (low pass {x['low_pass']*100:.0f}%)"
                              for x in info["misclassed_tasks"])
            L.append(f"Possibly mis-classed (pooled low-tier pass >= "
                     f"{MISCLASS_LOW_PASS:.0%}): {names}")
        L.append("")

    # 4. Calibration table + hypothesis scorecard
    L.append("## 4. Calibration table (RQ2)")
    L.append("")
    L.append("```")
    L.append(f"{'class':<24} {'tier':<7} {'confidence':<14} {'n':>3} {'pass':>6} "
             f"{'ceil':>5} {'p_ref':>6} {'delta':>7} {'med.out':>8} flags")
    for cls in m["classes"]:
        info = analysis["per_class"][cls]
        rec = info["recommended_tier"]
        ti = info["tiers"].get(rec, {})
        flags = []
        if info.get("equivalence_low") is True:
            flags.append("equiv")
        ot = info.get("overthinking") or {}
        if _overthinking_flag(ot):
            flags.append("regress" if (isinstance(ot, dict) and ot.get("strict_regression"))
                         else "saturate")
        L.append(f"{cls:<24} {rec:<7} {info['confidence']:<14} "
                 f"{ti.get('n', 0):>3} {ti.get('pass_rate', 0)*100:5.0f}% "
                 f"{info['ceiling_tier']:>5} {info['pass_rate_ref']*100:5.0f}% "
                 f"{info['delta_vs_ref']:+7.3f} {ti.get('median_out', 0):>8} "
                 f"{','.join(flags)}")
    L.append("```")
    L.append("(ceil = empirical quality-ceiling tier, arg-max pass; p_ref = its pass "
             "rate; delta = recommended pass - ceiling pass)")
    L.append("")
    L.append("Hypothesis scorecard (04 Section 1.2):")
    easy = m.get("easy_classes", [])
    h1_conf = [c for c in m["classes"]
               if c in easy and analysis["per_class"][c].get("equivalence_low") is True]
    tested = [c for c in m["classes"] if c in easy]
    L.append(f"- H1 (easy classes: low equivalent to ceiling, TOST): "
             + (f"confirmed for {', '.join(h1_conf)}" if h1_conf
                else "not confirmed at this power")
             + (f" (tested: {', '.join(tested)})" if tested else "") + ".")
    L.append("- H2 (hard classes: saturating gains): descriptive — see the per-class "
             "curves; a recommended tier below the ceiling indicates saturation.")
    ot = [c for c in m["classes"]
          if _overthinking_flag(analysis["per_class"][c].get("overthinking"))]
    L.append("- H3 (overthinking tail at max): "
             + (f"flagged for {', '.join(ot)}" if ot else "not observed") + ".")
    L.append("")

    # 5. Policy headline (RQ3 — three-baseline Pareto A/B)
    pc = analysis["policy_comparison"]
    sv_i = pc["savings_pct_vs_inherit_xhigh"]
    sv_h = pc["savings_pct_vs_uniform_high"]
    qg_l = pc["quality_gain_vs_uniform_low"]
    pd_i = pc["aggregate_pass_diff_vs_inherit_xhigh"]
    L.append("## 5. Policy headline (RQ3 — three-baseline Pareto A/B)")
    L.append("")

    def _ci_pct(d):
        c = d["ci95"]
        lo = "n/a" if c[0] is None else f"{c[0]:.1f}"
        hi = "n/a" if c[1] is None else f"{c[1]:.1f}"
        pt = "n/a" if d["point"] is None else f"{d['point']:.1f}"
        return pt, lo, hi

    def _ci_pp(d):
        c = d["ci95"]
        lo = "n/a" if c[0] is None else f"{c[0] * 100:+.1f}"
        hi = "n/a" if c[1] is None else f"{c[1] * 100:+.1f}"
        pt = "n/a" if d["point"] is None else f"{d['point'] * 100:+.1f}"
        return pt, lo, hi

    pt, lo, hi = _ci_pct(sv_i)
    L.append(f"- vs **inherit@xhigh** (status quo): **{pt}% fewer output tokens** "
             f"(95% CI [{lo}, {hi}]).")
    pt2, lo2, hi2 = _ci_pct(sv_h)
    L.append(f"- vs **uniform-high** (model default): {pt2}% fewer output tokens "
             f"(95% CI [{lo2}, {hi2}]).")
    qpt, qlo, qhi = _ci_pp(qg_l)
    L.append(f"- vs **uniform-low** (Anthropic subagent heuristic): {qpt}pp aggregate "
             f"pass (95% CI [{qlo}, {qhi}]pp) — calibrated must buy back the hard-class "
             f"quality that blanket-low sacrifices.")
    ipt, ilo, ihi = _ci_pp(pd_i)
    L.append(f"- Aggregate pass: calibrated {_fmt_pct(pc['aggregate_pass_calibrated'])} "
             f"vs inherit@xhigh {_fmt_pct(pc['aggregate_pass_inherit_xhigh'])} "
             f"(diff {ipt}pp, 95% CI [{ilo}, {ihi}]pp; non-inferior at "
             f"delta_agg={DELTA_AGG}: {'yes' if pc['noninferior_agg'] else 'no'}).")
    L.append("")
    if pc.get("incomplete_matrix"):
        dropped = pc.get("dropped_tasks", [])
        L.append("> **INCOMPLETE MATRIX** — the policy comparison is restricted to the "
                 f"{pc.get('comparable_task_count', 0)} task(s) with data under every "
                 "policy" + (f"; dropped: {', '.join(dropped)}" if dropped else "")
                 + ". Token totals below cover only those tasks, and the Pareto verdict "
                 "is indeterminate until the missing cells run.")
        L.append("")
    if pc["undominated"] is None:
        verdict = "INDETERMINATE — incomplete matrix (see banner above)"
    elif pc["undominated"]:
        verdict = "UN-DOMINATED — calibrated wins"
    else:
        verdict = "NOT un-dominated — at least one leg fails at this power"
    L.append(f"**Pareto verdict: {verdict}.** Victory requires token savings vs both "
             "high-effort baselines (CI excludes 0) at non-inferior aggregate quality, "
             "AND a strictly positive quality gain over uniform-low.")
    L.append("")
    L.append("Policy token totals (sum of per-task cell-mean output tokens over the "
             "12-task workload):")
    L.append("")
    L.append("```")
    L.append(f"{'policy':<18} {'out tokens':>12} {'agg pass':>9}")
    for p in ["uniform_low", "uniform_high", "calibrated", "inherit_xhigh", "uniform_max"]:
        pol = analysis["policies"][p]
        L.append(f"{p:<18} {pol['out_tokens']:>12.0f} {_fmt_pct(pol['agg_pass']):>9}")
    L.append("```")
    L.append("")

    # 6. Threats to validity
    L.append("## 6. Threats to validity")
    L.append("")
    L.append("- **Small n.** Class-level pooling gives 9 trials/cell at the pilot "
             "scale; Wilson/Newcombe intervals are correspondingly wide. A "
             "\"non-inferior\" tier means *no evidence of >10pp degradation*, not "
             "proof of parity. Low-confidence classes are the priority for an n=5 "
             "extension.")
    any_lowconf = [c for c in m["classes"]
                   if analysis["per_class"][c]["confidence"] == "low"]
    if any_lowconf:
        L.append(f"  - Low-confidence classes this run: {', '.join(any_lowconf)}.")
    L.append("- **Single model.** Calibration is specific to "
             f"{', '.join(m['model'])}; re-fit per model.")
    L.append("- **Effort fidelity.** Each run's requested effort is verified against "
             "the effective effort captured by a Stop hook (`effort.level`); "
             "mismatched or unverified runs are excluded from their cell (04 Section "
             "4.6), because headless JSON carries no effort field to confirm it landed.")
    L.append("- **Adaptive thinking is a constant background factor** — it "
             "self-regulates within every tier and cannot be disabled on Opus 4.8, so "
             "measured tier effects are net of it, not independent of it.")
    ot_threat = [c for c in m["classes"]
                 if _overthinking_flag(analysis["per_class"][c].get("overthinking"))]
    if ot_threat:
        L.append(f"- **Overthinking tail (H3)** flagged for {', '.join(ot_threat)}: "
                 "`max` spends more tokens without beating `xhigh` on pass rate, so the "
                 "non-inferiority reference is the empirical ceiling tier, not "
                 "mechanically `max`.")
    L.append("- **No temperature control.** The CLI exposes no `--seed`; run-to-run "
             "nondeterminism is the object of replication, not a nuisance removed. "
             "Run order is seeded-shuffled to de-correlate tier from wall-clock.")
    L.append("- **Exact-match strictness.** `parse_fail` is tracked separately from "
             "`wrong_answer`, so format-only failures are distinguished from "
             "reasoning failures.")
    L.append("- **Sandbox honesty.** pytest checks run under subprocess isolation "
             "(`python3 -I -S`, minimal env, CPU/address-space limits, wall "
             "timeout) — not a jail. Network is not hard-blocked on macOS; residual "
             "risk is low for benign model-generated code. Wrap in `unshare -n` on "
             "Linux/CI for true isolation.")
    misclassed_all = [(cls, x["task_id"])
                      for cls in m["classes"]
                      for x in analysis["per_class"][cls]["misclassed_tasks"]]
    if misclassed_all:
        L.append("- **Possibly mis-classed tasks** (pooled low-tier pass >= "
                 f"{MISCLASS_LOW_PASS:.0%}): "
                 + ", ".join(f"{t} in {c}" for c, t in misclassed_all)
                 + ". Surfaced, not silently moved.")
    L.append("- **Subscription billing.** Dollar figures are API-price equivalents "
             "($5/M in, $25/M out); real runs consume the user's plan.")
    L.append("")
    return "\n".join(L)


def cmd_report(args) -> int:
    paths = Paths(args.root, args.tasks_dir)
    if not os.path.exists(paths.analysis):
        print("[report] no analysis.json; run analyze first.")
        return 1
    tasks = {t["id"]: t for t in load_tasks(paths.tasks)}
    analysis = load_json(paths.analysis)
    md = render_report(analysis, tasks)
    atomic_write_text(paths.results_md, md)
    print(f"[report] wrote {os.path.relpath(paths.results_md, paths.root)} "
          f"({len(md.splitlines())} lines)")
    return 0


# --------------------------------------------------------------------------- #
# Subcommand: calibrate (guarded refit, 04 Section 7.2)                        #
# --------------------------------------------------------------------------- #
def normalize_dispatch_record(rec: dict, known_classes: set) -> tuple | None:
    """Normalize a dispatch-log record to (class, tier, accepted), else None.

    Tolerates the two writers B1 emits into bench/state/dispatch-log.jsonl:
      - source="effortmine": carries task_class + tier -> resolvable.
      - source="posttooluse-hook": carries agent_type only (a `miner-<tier>` worker),
        from which the CLASS is not derivable -> skipped (counted).
    A class is derived from agent_type only if the agent_type IS a known class name
    (unambiguous); a tier-named worker never resolves a class.
    """
    cls = rec.get("task_class")
    tier = rec.get("tier")
    agent = rec.get("agent_type") or ""
    if not tier and agent.startswith("miner-"):
        cand = agent.split("miner-", 1)[1]
        tier = cand if cand in TIERS else None
    if cls is None and agent in known_classes:
        cls = agent  # unambiguous: agent_type literally names a class
    if cls in known_classes and tier in TIERS:
        return (cls, tier, rec.get("accepted"))
    return None


def load_dispatch_log(path: str, known_classes: set) -> tuple[dict, int, int]:
    """Fold real-usage receipts into graded counts per (class, tier).

    Returns (graded_by_cell, consumed, skipped). Only records whose `accepted` is a
    bool contribute graded outcomes; dispatches with accepted=null count as consumed
    but add no graded-N. bench/state may not exist yet (hook creates it lazily).
    """
    graded: dict = {}
    consumed = skipped = 0
    if not path or not os.path.exists(path):
        return graded, consumed, skipped
    recs, _ = read_jsonl(path)
    for r in recs:
        norm = normalize_dispatch_record(r, known_classes)
        if norm is None:
            skipped += 1
            continue
        consumed += 1
        cls, tier, accepted = norm
        if accepted is True or accepted is False:
            d = graded.setdefault((cls, tier), {"k": 0, "n": 0})
            d["n"] += 1
            d["k"] += 1 if accepted else 0
    return graded, consumed, skipped


def cmd_calibrate(args) -> int:
    paths = Paths(args.root, args.tasks_dir)
    paths.ensure()
    if not os.path.exists(paths.analysis):
        print("[calibrate] no analysis.json; run analyze first.")
        return 1
    analysis = load_json(paths.analysis)
    tasks = {t["id"]: t for t in load_tasks(paths.tasks)}
    per_class = analysis["per_class"]
    known_classes = set(per_class.keys())

    current = None
    if os.path.exists(paths.calibration):
        try:
            current = load_json(paths.calibration).get("classes", {})
        except (OSError, json.JSONDecodeError):
            current = None

    # Fold accumulated real-usage receipts (B1's dual-source dispatch log) into the
    # graded-N used by the min-N gate. Absent/lazy dir is fine.
    dispatch_path = os.path.join(paths.state, "dispatch-log.jsonl")
    disp_graded, disp_consumed, disp_skipped = load_dispatch_log(dispatch_path, known_classes)

    print("[calibrate] guarded refit (min-N gate={}, single-step, clamped low..max)"
          .format(MIN_N_REFIT))
    if os.path.exists(dispatch_path):
        print(f"[calibrate] dispatch-log: consumed {disp_consumed}, skipped "
              f"{disp_skipped} (unresolved class), graded-augmented cells "
              f"{len(disp_graded)}")
    new_classes = {}
    moved = 0
    for cls in sorted(per_class.keys()):
        info = per_class[cls]
        candidate = info["recommended_tier"]
        tiers_info = info["tiers"]
        cur_tier = (current.get(cls, {}).get("recommended_tier")
                    if current else None) or candidate

        # Min-N gate: >= MIN_N_REFIT graded for BOTH current and candidate cells,
        # counting benchmark cells AND real-usage graded receipts from the log.
        def eff_n(tier):
            return (tiers_info.get(tier, {}).get("n", 0)
                    + disp_graded.get((cls, tier), {}).get("n", 0))
        n_cur, n_cand = eff_n(cur_tier), eff_n(candidate)
        gate_ok = (n_cur >= MIN_N_REFIT and n_cand >= MIN_N_REFIT)

        proposed = cur_tier
        reason = "hold"
        if cur_tier == candidate:
            reason = "no-change (candidate == current)"
        elif not gate_ok:
            reason = f"gated (n_cur={n_cur}, n_cand={n_cand} < {MIN_N_REFIT})"
        else:
            proposed = _step_toward(cur_tier, candidate)  # single-step, clamped
            reason = ("moved one step toward candidate"
                      + ("" if proposed == candidate else f" (candidate {candidate} is >1 step away)"))
            moved += 1

        rec_info = tiers_info.get(proposed, {})
        pr = rec_info.get("pass_rate", 0.0)
        prref = info["pass_rate_ref"]
        arrow = "->" if proposed != cur_tier else "=="
        flag = "moved" if proposed != cur_tier else "hold "
        print(f"[calibrate] {cls:<24} {cur_tier:>6} {arrow} {proposed:<6} "
              f"[{flag}] (n={eff_n(proposed)}, pass {pr:.2f} vs ceiling {prref:.2f}, "
              f"delta={pr - prref:+.2f} <= {DELTA}) {reason}")

        new_classes[cls] = {
            "recommended_tier": proposed,
            "confidence": info["confidence"],
            "n": eff_n(proposed), "n_graded": eff_n(proposed),
            "fitted": proposed != cur_tier,
            "pass_rate": pr, "ceiling_tier": info["ceiling_tier"],
            "pass_rate_ref": prref, "delta_vs_ref": pr - prref,
            "median_out_tokens": rec_info.get("median_out", 0),
            "equivalence_low": info.get("equivalence_low"),
            "overthinking": _overthinking_flag(info.get("overthinking", False)),
        }

    pc = analysis["policy_comparison"]
    policy = _policy_block(pc)
    policy["note"] = ("policy block reflects the analyze-time recommendation; guarded "
                      "single-step tier moves may lag the NI-optimal tier")
    prov = build_provenance(analysis["manifest"], "refit")
    mock = prov["mode"] == "mock"
    out = {
        # Same provenance discipline as a fresh fit (review H1): a refit off mock
        # data is version 0 / proven false; a real refit is version >= 1 / proven true.
        "version": 0 if mock else 1,
        "proven": (not mock),
        "provenance": prov,
        "fitted_date": None if mock else _dt.date.today().isoformat(),
        "model": (analysis["manifest"]["model"] or [MODEL])[0]
                 if analysis["manifest"]["model"] else MODEL,
        "suite_version": "pilot-12",
        "margin_delta": DELTA,
        "refit": {"min_n_gate": MIN_N_REFIT, "single_step": True,
                  "classes_moved": moved, "dispatch_consumed": disp_consumed,
                  "dispatch_skipped": disp_skipped},
        "classes": new_classes,
        "policy": policy,
    }
    warnings = build_calibration_warnings(per_class, prov["mode"])
    if warnings:
        out["warnings"] = warnings
    atomic_write_json(paths.calibration, out)
    print(f"[calibrate] {moved} class(es) moved; wrote "
          f"{os.path.relpath(paths.calibration, paths.root)}")
    return 0


# --------------------------------------------------------------------------- #
# Subcommand: validate (Phase 0, 04 Section 4)                                #
# --------------------------------------------------------------------------- #
_PROBE = ("Consider a 4x4 grid of switches, each on or off. A 'quiet' grid has no "
          "row and no column with all four switches on. Reason step by step, then "
          "state how many of the 65536 configurations are quiet. End with the count "
          "on its own line.")


def cmd_validate(args) -> int:
    paths = Paths(args.root, args.tasks_dir)
    paths.ensure()
    env, audit = build_child_env()
    cli_version = "mock" if args.mock else detect_cli_version()

    report = {
        "ran_at": _now(), "mock": bool(args.mock), "model": args.model,
        "cli_version": cli_version, "tiers": TIERS,
        "flag_acceptance": {}, "envelope_fields": [], "modulation": {},
        "env": {}, "latency": {}, "gate_passed": False, "abort_code": None,
    }

    # 4.4 Env sanitization audit. CLAUDE_CODE_EFFORT_LEVEL set in parent is a hard
    # error for the gate (its per-run level cannot be trusted); we also strip it for
    # every child regardless.
    sanitized_keys = sorted(k for k in env.keys()
                            if k.startswith(("CLAUDE", "ANTHROPIC", "PATH", "HOME")))
    report["env"] = {
        "effort_level_override_present": audit["effort_level_override_present"],
        "extra_body_stripped": audit["extra_body_stripped"],
        "max_output_tokens_stripped": audit["max_output_tokens_stripped"],
        "api_key_stripped": audit["api_key_stripped"],
        "api_key_injected": False,
        "sanitized_env_keys_sample": sanitized_keys[:20],
    }
    env_ok = not audit["effort_level_override_present"]
    if not env_ok:
        report["abort_code"] = "effort_env_override_present"
        print(f"[validate] HARD ERROR: {EFFORT_ENV_OVERRIDE} is set in the parent "
              "environment; it overrides --effort and per-run effort cannot be "
              "trusted. Unset it before running the matrix.")

    tiers_accepted = {}
    envelope_fields: set[str] = set()
    modulation_out = {t: [] for t in TIERS}
    fidelity_obs = {t: [] for t in TIERS}   # tier -> effective levels observed via hook
    cap_sidecar = None

    if args.mock:
        for t in TIERS:
            tiers_accepted[t] = True
            fidelity_obs[t] = [t, t, t]   # mock: effective == requested for all tiers
        # Fabricate a probe envelope per tier x3 for the modulation check.
        for t in TIERS:
            for rep in range(1, 4):
                jitter = 0.85 + 0.30 * _h01(args.seed, "probe", t, rep)
                out_tok = int(MOCK_BASE_OUT[t] * jitter)
                modulation_out[t].append(out_tok)
                envelope_fields.update(
                    ["type", "subtype", "is_error", "duration_ms", "result",
                     "session_id", "total_cost_usd", "usage"])
        report["latency"] = {t: {"mean_ms": MOCK_BASE_OUT[t] * 8} for t in TIERS}
    else:
        # 4.6 install the effort-capture hook so probes also record EFFECTIVE effort.
        cap_settings, cap_sidecar = setup_effort_capture(os.path.join(paths.state, "capture"))

        def _observe_effective(ev):
            if not isinstance(ev, dict):
                return
            eff = effective_from_sidecar(cap_sidecar, ev.get("session_id", ""))
            if eff is None:
                eff = detect_effective_effort(ev)
            if eff:
                fidelity_obs[t].append(eff)

        # 4.1 flag acceptance + 4.2 envelope enumeration
        for t in TIERS:
            res = invoke_claude("Reply with the single word: ok", t, args.model, 120,
                                env, cap_settings)
            ev = None
            if res.returncode == 0 and res.stdout.strip():
                try:
                    ev = json.loads(res.stdout)
                except json.JSONDecodeError:
                    ev = None
            tiers_accepted[t] = ev is not None and res.returncode == 0
            if isinstance(ev, dict):
                envelope_fields.update(ev.keys())
                if isinstance(ev.get("usage"), dict):
                    envelope_fields.update(f"usage.{k}" for k in ev["usage"].keys())
            _observe_effective(ev)
        # 4.3 effort-modulation probe (x3 per tier) + 4.6 fidelity capture
        for t in TIERS:
            for _ in range(3):
                res = invoke_claude(_PROBE, t, args.model, RUN_TIMEOUT_S, env, cap_settings)
                if res.returncode == 0 and res.stdout.strip():
                    try:
                        ev = json.loads(res.stdout)
                        modulation_out[t].append(int(ev.get("usage", {}).get("output_tokens", 0)))
                        _observe_effective(ev)
                    except json.JSONDecodeError:
                        pass
        # 4.5 latency sizing on two tiers
        for t in ("low", "max"):
            times = []
            for _ in range(3):
                s = time.time()
                invoke_claude("Reply with the single word: ok", t, args.model, 120, env)
                times.append((time.time() - s) * 1000)
            report["latency"][t] = {"mean_ms": statistics.mean(times) if times else 0}

    report["flag_acceptance"] = tiers_accepted
    report["envelope_fields"] = sorted(envelope_fields)

    med_low = statistics.median(modulation_out["low"]) if modulation_out["low"] else 0
    med_max = statistics.median(modulation_out["max"]) if modulation_out["max"] else 0
    ratio = (med_max / med_low) if med_low > 0 else 0.0
    monotone = True
    prev = -1
    for t in TIERS:
        vals = modulation_out[t]
        if vals:
            med = statistics.median(vals)
            if med + 1e-9 < prev:
                monotone = False
            prev = med
    modulation_ok = (ratio >= MODULATION_RATIO)
    report["modulation"] = {
        "probe": _PROBE, "per_tier_median_out": {t: (statistics.median(v) if v else 0)
                                                 for t, v in modulation_out.items()},
        "median_low": med_low, "median_max": med_max, "ratio_max_over_low": ratio,
        "threshold": MODULATION_RATIO, "roughly_monotone": monotone, "passed": modulation_ok,
    }
    if not modulation_ok and report["abort_code"] is None:
        report["abort_code"] = "effort_not_modulating"
        print(f"[validate] ABORT: median(max out)/median(low out) = {ratio:.2f} < "
              f"{MODULATION_RATIO}. Effort may be a no-op in headless mode; do not "
              "run the matrix. See 04 Section 4.6 fallbacks.")

    all_accepted = all(tiers_accepted.get(t) for t in TIERS)
    if not all_accepted and report["abort_code"] is None:
        report["abort_code"] = "tier_rejected"

    # 4.6 Effort-fidelity gate: for every tier, requested must == effective (captured
    # by the hook). A downgrade or an unverifiable tier is a hard gate failure.
    fidelity = {}
    fidelity_ok = True
    for t in TIERS:
        obs = fidelity_obs.get(t, [])
        if obs and all(o == t for o in obs):
            eff, ok_t = t, True
        elif obs:
            eff, ok_t = obs[-1], False       # a genuine downgrade
        else:
            eff, ok_t = "unverified", False   # hook never fired for this tier
        fidelity[t] = {"requested": t, "effective": eff, "observations": obs, "ok": ok_t}
        if not ok_t:
            fidelity_ok = False
    report["effort_fidelity"] = {
        "per_tier": fidelity, "passed": fidelity_ok,
        "capture": "mock" if args.mock else "stop-hook",
        "note": ("requested==effective for all five tiers confirms opus-4-8 honors "
                 "each level; mismatched/unverified tiers must be dropped (04 4.6/4.7)"),
    }
    if not fidelity_ok and report["abort_code"] is None:
        report["abort_code"] = "effort_downgrade_or_unverified"
        print("[validate] ABORT: effort fidelity failed — at least one tier's "
              "effective effort could not be confirmed equal to requested. "
              "See state/phase0.json effort_fidelity; do not run the matrix.")

    # 4.5 timeout headroom
    max_lat = report["latency"].get("max", {}).get("mean_ms", 0)
    report["latency"]["timeout_headroom_ok"] = (RUN_TIMEOUT_S * 1000) > (max_lat * 3 + 1)

    report["gate_passed"] = bool(env_ok and modulation_ok and all_accepted and fidelity_ok)
    atomic_write_json(paths.phase0, report)

    print(f"[validate] mock={args.mock} tiers_accepted="
          f"{sum(1 for v in tiers_accepted.values() if v)}/{len(TIERS)} "
          f"modulation_ratio={ratio:.2f} (>= {MODULATION_RATIO}: {modulation_ok}) "
          f"env_ok={env_ok} fidelity_ok={fidelity_ok}")
    print(f"[validate] envelope fields: {len(report['envelope_fields'])} captured")
    print(f"[validate] gate_passed={report['gate_passed']} "
          f"abort_code={report['abort_code']}")
    print(f"[validate] wrote {os.path.relpath(paths.phase0, paths.root)}")
    return 0 if report["gate_passed"] else 2


# --------------------------------------------------------------------------- #
# Subcommand: selftest (mock pipeline end-to-end + invariants)                #
# --------------------------------------------------------------------------- #
def cmd_selftest(args) -> int:
    real_tasks = args.tasks_dir or os.path.join(default_root(), "tasks")
    tmp = tempfile.mkdtemp(prefix="effort-selftest-")
    fails = []

    def check(ok, msg):
        print(f"  {'PASS' if ok else 'FAIL'} {msg}")
        if not ok:
            fails.append(msg)

    try:
        ns = argparse.Namespace(root=tmp, tasks_dir=real_tasks, seed=SEED_DEFAULT,
                                model=MODEL, mock=True, scale="pilot", parallel=1,
                                rerun_failed=False, regrade=False, force=False)
        paths = Paths(tmp, real_tasks)

        print("[selftest] 1. validate --mock")
        rc = cmd_validate(ns)
        check(os.path.exists(paths.phase0), "phase0.json written")
        p0 = load_json(paths.phase0)
        check(p0["gate_passed"] is True, "Phase 0 gate passed (mock)")
        check(p0["modulation"]["ratio_max_over_low"] >= MODULATION_RATIO,
              "modulation ratio >= 2x")
        check(p0["effort_fidelity"]["passed"] is True,
              "Phase 0.6 effort-fidelity gate passed (mock)")
        check(all(p0["effort_fidelity"]["per_tier"][t]["effective"] == t for t in TIERS),
              "every tier requested == effective (mock)")
        check(rc == 0, "validate exit 0")

        print("[selftest] 2. run --mock")
        cmd_run(ns)
        results, bad = read_jsonl(paths.results)
        tasks = load_tasks(real_tasks)
        expected_cells = len(build_cells(tasks, "pilot"))
        check(bad == 0, "no corrupt result lines")
        check(len(results) == expected_cells,
              f"results count == matrix ({len(results)} == {expected_cells})")
        required_fields = {"run_id", "task_id", "tier", "effort_requested",
                           "effort_effective", "effort_effective_source", "fidelity_ok",
                           "output_tokens", "total_cost_usd", "model_usage", "nonce",
                           "raw_answer_path", "api_error", "seed"}
        check(all(required_fields <= set(r) for r in results),
              "every record has the required (envelope-bound) schema fields")
        check(all(r["fidelity_ok"] for r in results if not r["api_error"]),
              "every non-error run is fidelity-verified (mock)")
        check(all(os.path.exists(os.path.join(tmp, r["raw_answer_path"]))
                  for r in results if not r["api_error"]),
              "every raw answer file exists")

        print("[selftest] 3. run --mock again (resumability)")
        before = len(read_jsonl(paths.results)[0])
        cmd_run(ns)
        after = len(read_jsonl(paths.results)[0])
        check(after == before, f"resume appended 0 records ({before} -> {after})")

        print("[selftest] 4. grade")
        cmd_grade(ns)
        graded, _ = read_jsonl(paths.graded)
        latest_res = {k for k, r in latest_by_key(results).items() if not r["api_error"]}
        latest_grd = set(latest_by_key(graded).keys())
        check(latest_res <= latest_grd, "every non-error cell graded")
        valid_fc = {"none", "wrong_answer", "parse_fail", "timeout"}
        check(all(g["failure_class"] in valid_fc for g in graded),
              "all failure classes valid")
        # Re-grade a known-correct exact cell to confirm the grader agrees.
        check(any(g["pass"] for g in graded), "at least one cell passed")
        check(any(not g["pass"] for g in graded), "at least one cell failed (spread)")

        print("[selftest] 5. analyze")
        cmd_analyze(ns)
        check(os.path.exists(paths.analysis), "analysis.json written")
        check(os.path.exists(paths.calibration), "calibration.json written")
        cal0 = load_json(paths.calibration)
        check(cal0["provenance"]["mode"] == "mock" and cal0["version"] == 0
              and cal0["proven"] is False and cal0["fitted_date"] is None,
              "mock analyze stamped provenance.mode=mock, version=0, proven=false (review H1)")
        check("tier" not in next(iter(cal0["classes"].values())),
              "calibration class has no duplicate tier key (review L5)")
        analysis = load_json(paths.analysis)
        for cls, info in analysis["per_class"].items():
            check(info["recommended_tier"] in TIERS,
                  f"{cls} recommended tier valid ({info['recommended_tier']})")
            check(info["ceiling_tier"] in TIERS, f"{cls} ceiling tier valid")
            for t, ti in info["tiers"].items():
                lo, hi = ti["wilson"]
                if not (0.0 <= lo <= hi <= 1.0):
                    check(False, f"{cls}/{t} Wilson CI in [0,1] and ordered")
        # Easy classes carry a TOST result (bool); hard classes carry the overthink flag.
        for cls in EASY_CLASSES:
            if cls in analysis["per_class"]:
                check(analysis["per_class"][cls]["equivalence_low"] in (True, False),
                      f"{cls} TOST equivalence computed")
        pcmp = analysis["policy_comparison"]
        for key in ("savings_pct_vs_inherit_xhigh", "savings_pct_vs_uniform_high",
                    "quality_gain_vs_uniform_low", "undominated", "noninferior_agg"):
            check(key in pcmp, f"policy_comparison has {key}")
        check(pcmp["savings_pct_vs_inherit_xhigh"]["point"] is not None,
              "savings point estimate present")
        check(isinstance(pcmp["undominated"], bool), "Pareto undominated verdict is bool")
        check(pcmp.get("incomplete_matrix") is False,
              "pilot mock matrix complete (incomplete_matrix false, review M3)")
        for cls, info in analysis["per_class"].items():
            ot = info["overthinking"]
            check(isinstance(ot, dict) and set(ot) == {"flag", "strict_regression"}
                  and isinstance(ot["flag"], bool) and isinstance(ot["strict_regression"], bool),
                  f"{cls} overthinking split into flag+strict_regression bools (review M4)")

        print("[selftest] 6. report")
        cmd_report(ns)
        check(os.path.exists(paths.results_md), "RESULTS.md written")
        with open(paths.results_md, encoding="utf-8") as f:
            md = f.read()
        for section in ["Run manifest", "Matrix", "Per-class", "Calibration table",
                        "Policy headline", "Threats to validity"]:
            check(section in md, f"RESULTS.md has '{section}' section")
        # No emoji (scan for common emoji codepoint ranges).
        has_emoji = any(0x1F000 <= ord(ch) <= 0x1FAFF or 0x2600 <= ord(ch) <= 0x27BF
                        for ch in md)
        check(not has_emoji, "RESULTS.md contains no emoji")

        print("[selftest] 7. calibrate (guarded refit + dual-source dispatch log)")
        # Seed a dual-source dispatch log: one resolvable effortmine record and one
        # unresolvable posttooluse-hook record (agent_type only) that must be skipped.
        os.makedirs(paths.state, exist_ok=True)
        with open(os.path.join(paths.state, "dispatch-log.jsonl"), "w", encoding="utf-8") as f:
            f.write(json.dumps({"source": "effortmine", "task_class": "T1-mechanical",
                                "tier": "low", "accepted": True}) + "\n")
            f.write(json.dumps({"source": "posttooluse-hook", "agent_type": "miner-low",
                                "session_id": "x"}) + "\n")
        cmd_calibrate(ns)
        cal = load_json(paths.calibration)
        check(set(cal["classes"].keys()) == {t["class"] for t in tasks},
              "calibration covers all classes")
        check(all(c["recommended_tier"] in TIERS for c in cal["classes"].values()),
              "all calibrated tiers valid")
        check("tier" not in next(iter(cal["classes"].values())),
              "no duplicate tier/recommended_tier key (review L5)")
        check(cal["provenance"]["mode"] == "mock" and cal["version"] == 0
              and cal["proven"] is False,
              "mock refit stamped provenance.mode=mock, version=0, proven=false (review H1)")
        check(cal["refit"]["dispatch_consumed"] == 1 and cal["refit"]["dispatch_skipped"] == 1,
              "dispatch-log: 1 consumed (effortmine), 1 skipped (hook agent_type only)")

        print("[selftest] 8. no stray temp files left in state/raw")
        strays = (glob.glob(os.path.join(paths.state, ".tmp-*"))
                  + glob.glob(os.path.join(paths.raw, ".tmp-*")))
        check(not strays, "no leftover .tmp-*.swap files")

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if fails:
        print(f"[selftest] {len(fails)} FAILURE(S)")
        return 1
    print("[selftest] ALL INVARIANTS HELD")
    return 0


# --------------------------------------------------------------------------- #
# argparse                                                                     #
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="effort.py",
        description="effortmining A/B benchmark harness (stdlib only).")
    p.add_argument("--root", default=default_root(),
                   help="base dir for state/, raw/, RESULTS.md (default: this file's dir)")
    p.add_argument("--tasks-dir", default=None,
                   help="task JSON dir (default: <root>/tasks)")
    sub = p.add_subparsers(dest="cmd", required=True)

    v = sub.add_parser("validate", help="Phase 0 instrument gate")
    v.add_argument("--mock", action="store_true", help="fabricate probes, no real calls")
    v.add_argument("--model", default=MODEL)
    v.add_argument("--seed", type=int, default=SEED_DEFAULT)
    v.set_defaults(func=cmd_validate)

    r = sub.add_parser("run", help="execute the matrix")
    r.add_argument("--mock", action="store_true", help="fabricate envelopes offline")
    r.add_argument("--scale", default="pilot", choices=list(SCALES))
    r.add_argument("--model", default=MODEL)
    r.add_argument("--seed", type=int, default=SEED_DEFAULT)
    r.add_argument("--parallel", type=int, default=3)
    r.add_argument("--rerun-failed", action="store_true",
                   help="also re-run cells whose graded verdict is fail")
    r.add_argument("--force", action="store_true",
                   help="bypass the Phase 0 hard gate (loud warning)")
    r.set_defaults(func=cmd_run)

    g = sub.add_parser("grade", help="apply checkers to results")
    g.add_argument("--regrade", action="store_true", help="re-grade all cells")
    g.set_defaults(func=cmd_grade)

    a = sub.add_parser("analyze", help="stats, NI decisions, policy comparison")
    a.add_argument("--seed", type=int, default=SEED_DEFAULT)
    a.set_defaults(func=cmd_analyze)

    rp = sub.add_parser("report", help="render RESULTS.md")
    rp.set_defaults(func=cmd_report)

    c = sub.add_parser("calibrate", help="guarded refit of the calibration table")
    c.set_defaults(func=cmd_calibrate)

    s = sub.add_parser("selftest", help="mock pipeline end-to-end + invariants")
    s.set_defaults(func=cmd_selftest)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    # Normalize attrs that some subcommands don't define but shared code reads.
    for attr, default in (("mock", False), ("scale", "pilot"), ("parallel", 1),
                          ("seed", SEED_DEFAULT), ("model", MODEL),
                          ("rerun_failed", False), ("regrade", False),
                          ("force", False), ("tasks_dir", None)):
        if not hasattr(args, attr):
            setattr(args, attr, default)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
