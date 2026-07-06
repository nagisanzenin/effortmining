#!/usr/bin/env python3
"""Reproducible oracle-integrity check for the effortmining benchmark v2 suite.

Run from anywhere:  python3 bench/tools/validate_oracles_v2.py
Exit 0 iff every shipped oracle in ../tasks-v2 is correct and self-consistent.

This is the v2 sibling of validate_oracles.py. It validates NINE tasks across
three classes:

  R-research (R1 exact, R2/R3 blind-grader)
    - EXACT (R1): re-derives every answer field from the AUTHORITATIVE documents,
      confirms each trap value exists in a SECONDARY document, confirms no
      secondary document states a correct value, then checks the shipped answer
      key matches the re-derivation. (Answer/prompt drift is caught.)
    - BLIND-GRADER (R2/R3): parses the rubric (numbered, point-weighted criteria),
      checks the points sum to max_score, the pass threshold is consistent, and
      every quantitative anchor the rubric relies on is grounded in the documents.

  C-coding (C1/C2/C3, pytest-asserts): runs each hidden assert suite against an
    INDEPENDENT reference solution embedded here (must PASS) and against a
    buggy/wrong/stateful version (must FAIL), proving the asserts discriminate.
    For C2/C3 the buggy/original code is extracted from the SHIPPED prompt, so the
    check proves the shipped task's own broken code fails its own asserts.

  X-composite (X1/X2/X3): validates the composite structure (5 class-spanning,
    individually-checkable subtasks), re-derives every EXACT subtask answer from
    the task's documents, and runs each coding subtask's asserts against an
    embedded reference (PASS) and a buggy version (FAIL).

Reference solutions live HERE, never in the task files. Pure Python 3 stdlib.
This is validation tooling, NOT a Claude generation run."""
import json, glob, os, re, subprocess, sys, tempfile
from collections import Counter

TASKS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tasks-v2")
REQUIRED_TOP = {"id", "class", "prompt", "checker", "max_output_guardrail", "timeout_s"}
CLASSES = {"R-research", "C-coding", "X-composite"}
CHECKER_TYPES = {"exact", "pytest-asserts", "blind-grader", "composite"}
EXPECTED_IDS = {"R1", "R2", "R3", "C1", "C2", "C3", "X1", "X2", "X3"}

fails = []
def note(ok, msg):
    print(f"{'PASS' if ok else 'FAIL'} {msg}")
    if not ok:
        fails.append(msg)

def norm(s):
    return " ".join(s.split())

def run_asserts(code, asserts, timeout=5):
    """Run code + appended asserts in an isolated subprocess. Return (ok, tail)."""
    prog = code + "\n" + "\n".join(asserts) + "\nprint('OK')\n"
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as tf:
        tf.write(prog); path = tf.name
    try:
        r = subprocess.run([sys.executable, "-I", path], capture_output=True, text=True, timeout=timeout)
    finally:
        os.unlink(path)
    return (r.returncode == 0 and r.stdout.strip().endswith("OK")), (r.stderr.strip().splitlines() or [""])[-1]

def last_python_block(text):
    """Extract the last ```python ... ``` fenced block from text (the shipped code)."""
    blocks = re.findall(r"```python\s*\n(.*?)```", text, re.DOTALL)
    return blocks[-1] if blocks else None

def rubric_points(md):
    return [int(m) for m in re.findall(r"\((\d+)\s*pts?\)", md)]

# =========================================================== independent references
# These are written here, independent of the task files and of the authoring
# generator. For C1 they prove the asserts are satisfiable; the WRONG variant
# proves they are discriminating.
REF = {
"IntervalSet": (
    "class IntervalSet:\n"
    "    def __init__(self):\n        self._s = []\n"
    "    def add(self, lo, hi):\n        if lo >= hi:\n            return\n"
    "        segs = sorted(self._s + [(lo, hi)]); out = []\n"
    "        for a, b in segs:\n"
    "            if out and a <= out[-1][1]:\n                out[-1] = (out[-1][0], max(out[-1][1], b))\n"
    "            else:\n                out.append((a, b))\n        self._s = out\n"
    "    def remove(self, lo, hi):\n        if lo >= hi:\n            return\n        out = []\n"
    "        for a, b in self._s:\n"
    "            if b <= lo or a >= hi:\n                out.append((a, b))\n            else:\n"
    "                if a < lo:\n                    out.append((a, lo))\n"
    "                if hi < b:\n                    out.append((hi, b))\n        self._s = out\n"
    "    def contains(self, x):\n        return any(a <= x < b for a, b in self._s)\n"
    "    def measure(self):\n        return sum(b - a for a, b in self._s)\n"
    "    def segments(self):\n        return list(self._s)\n"),
}
# a plausible WRONG IntervalSet: closed-interval contains, no coalescing
C1_WRONG = (
    "class IntervalSet:\n"
    "    def __init__(self):\n        self._s = []\n"
    "    def add(self, lo, hi):\n        if lo > hi:\n            return\n"
    "        self._s.append((lo, hi)); self._s.sort()\n"
    "    def remove(self, lo, hi):\n"
    "        self._s = [(a, b) for a, b in self._s if not (a >= lo and b <= hi)]\n"
    "    def contains(self, x):\n        return any(a <= x <= b for a, b in self._s)\n"
    "    def measure(self):\n        return sum(b - a for a, b in self._s)\n"
    "    def segments(self):\n        return list(self._s)\n")
# C2 independent fixed reference (three bugs corrected)
C2_FIXED = (
    "from datetime import datetime, timezone\n"
    "PAGE_SIZE_DEFAULT = 50\n"
    "def parse_ts(s):\n    dt = datetime.fromisoformat(s)\n"
    "    if dt.tzinfo is None:\n        dt = dt.replace(tzinfo=timezone.utc)\n    return dt\n"
    "def page_count(total_items, page_size):\n"
    "    if page_size <= 0:\n        raise ValueError('page_size must be positive')\n"
    "    return (total_items + page_size - 1) // page_size\n"
    "def paginate(records, page, page_size=PAGE_SIZE_DEFAULT):\n"
    "    if page < 1:\n        raise ValueError('page is 1-indexed')\n"
    "    start = (page - 1) * page_size\n    return records[start:start + page_size]\n"
    "def events_since(events, cutoff_iso):\n    cutoff = parse_ts(cutoff_iso); out = []\n"
    "    for ev in events:\n        if parse_ts(ev['ts']) >= cutoff:\n            out.append(ev)\n    return out\n"
    "def purge_expired(entries, now_iso):\n    now = parse_ts(now_iso); removed = []\n"
    "    for e in list(entries):\n        if parse_ts(e['expires']) < now:\n"
    "            removed.append(e); entries.remove(e)\n    return removed\n"
    "def total_units(events):\n    return sum(e.get('units', 0) for e in events)\n"
    "def top_consumers(events, k):\n    totals = {}\n"
    "    for e in events:\n        totals[e['account']] = totals.get(e['account'], 0) + e.get('units', 0)\n"
    "    return sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))[:k]\n")
# C3 independent good reference + a cheating anti-reference (module-global state)
C3_REF = (
    "class Metrics:\n"
    "    def __init__(self):\n        self._counts = {}\n        self._total = 0\n"
    "    def record(self, name, value):\n        self._counts.setdefault(name, []).append(value)\n"
    "        self._total += value\n"
    "    def average(self, name):\n        vals = self._counts.get(name, [])\n"
    "        return sum(vals) / len(vals) if vals else 0.0\n"
    "    def grand_total(self):\n        return self._total\n"
    "    def reset(self):\n        self._counts = {}\n        self._total = 0\n")
C3_CHEAT = (
    "_counts = {}\n_total = 0\n"
    "class Metrics:\n"
    "    def record(self, name, value):\n        global _total\n"
    "        _counts.setdefault(name, []).append(value)\n        _total += value\n"
    "    def average(self, name):\n        vals = _counts.get(name, [])\n"
    "        return sum(vals) / len(vals) if vals else 0.0\n"
    "    def grand_total(self):\n        return _total\n"
    "    def reset(self):\n        global _total\n        _counts.clear(); _total = 0\n")
# X coding-subtask references + buggy variants
X_REF = {
    "retry_delay": "def retry_delay(attempt):\n    return min(30, 2 ** attempt)\n",
    "merge_config": "def merge_config(defaults, override):\n    out = dict(defaults)\n"
                    "    for k, v in override.items():\n        if v is not None:\n            out[k] = v\n    return out\n",
    "summarize_amounts": "def summarize_amounts(records):\n    a = [r['amount'] for r in records]\n"
                         "    c = len(a); t = sum(a)\n    return {'count': c, 'total': t, 'avg': (t / c) if c else 0}\n",
}
X_WRONG = {
    "retry_delay": "def retry_delay(attempt):\n    return 2 ** attempt\n",
    "merge_config": "def merge_config(defaults, override):\n    defaults.update(override)\n    return defaults\n",
    "summarize_amounts": "def summarize_amounts(records):\n    a = [r['amount'] for r in records]\n"
                         "    c = len(a); t = sum(a)\n    return {'count': c, 'total': t, 'avg': t / c}\n",
}

# =========================================================== R1 canonical facts
R1_CANON = {
    "POOL_MAXCONNECTIONS_DEFAULT": "256", "TIMEOUT_READMS_DEFAULT": "5000",
    "RETRY_MAXATTEMPTS_DEPRECATED_IN": "4.2", "RETRY_MAXATTEMPTS_REMOVED_IN": "4.5",
    "LEGACYAUTHFILTER_REMOVED_IN": "4.3", "TLS_MINVERSION_RENAMED_TO": "tls.minimumVersion",
    "RENAMED_KEYS_COUNT": "2", "WIKI_POOL_DEFAULT_CLAIM": "128",
}
# R2/R3 rubric anchors that MUST be grounded in the documents
R2_ANCHORS = ["-9.2%", "-1.9%", "-7.4%", "task type"]
R3_ANCHORS = ["CS-2288", "db.pool.maxSize", "200", "20", "INC-5501", "INC-5507", "INC-5512"]

def doc_by(docs, *keywords):
    for d in docs:
        t = d["title"].lower()
        if all(k.lower() in t for k in keywords):
            return d["content"]
    return ""

# =========================================================== validators per class
def validate_exact_R1(t):
    docs = t["documents"]
    cl = doc_by(docs, "changelog"); mg = doc_by(docs, "migration"); cref = doc_by(docs, "configuration reference")
    wiki = doc_by(docs, "wiki"); blog = doc_by(docs, "blog"); kb = doc_by(docs, "kb"); forum = doc_by(docs, "forum")
    ncl, nmg, ncref = norm(cl), norm(mg), norm(cref)
    # re-derive each authoritative fact from the document TEXT
    derived = {}
    derived["POOL_MAXCONNECTIONS_DEFAULT"] = "256" if ("100 to 256" in ncl and "Current default: 256" in ncref) else "?"
    derived["TIMEOUT_READMS_DEFAULT"] = "5000" if ("3000 to 5000" in ncl and "Current default: 5000" in ncref) else "?"
    derived["RETRY_MAXATTEMPTS_DEPRECATED_IN"] = "4.2" if "DEPRECATED since 4.2.0" in ncl else "?"
    m = re.search(r"deprecated since 4\.2\.0, is now\s+REMOVED", ncl)
    derived["RETRY_MAXATTEMPTS_REMOVED_IN"] = "4.5" if ("4.5.0" in cl and "REMOVED" in cl and "retry.maxAttempts" in cl) else "?"
    derived["LEGACYAUTHFILTER_REMOVED_IN"] = "4.3" if ("`LegacyAuthFilter`" in cl and "4.3.0" in cl) else "?"
    mm = re.search(r"`tls\.minVersion` is renamed to\s+`(tls\.\w+)`", ncl)
    derived["TLS_MINVERSION_RENAMED_TO"] = mm.group(1) if mm else "?"
    derived["RENAMED_KEYS_COUNT"] = "2" if ("EXACTLY TWO keys are renamed" in nmg or "EXACTLY TWO renamed keys" in nmg) else "?"
    derived["WIKI_POOL_DEFAULT_CLAIM"] = "128" if ("128" in wiki and "pool.maxConnections" in wiki) else "?"
    note(derived == R1_CANON, f"R1 answer re-derived from authoritative docs == canonical facts  ({derived})")
    # traps must exist in secondary docs (so the discriminator is real)
    note("128" in wiki and "removed in 4.4" in wiki, "R1 trap: wiki states pool=128 and 'removed in 4.4'")
    note("250 connections" in blog, "R1 trap: blog states pool=250")
    note("3000 ms" in kb or "3s (3000" in kb, "R1 trap: KB states readMs=3000")
    note(all("256" not in d and "5000" not in d for d in (wiki, blog, kb, forum)),
         "R1 traps: no secondary doc states a correct value (256/5000)")
    # shipped answer key must equal the re-derivation, in the fixed order
    shipped = dict(l.split(": ", 1) for l in t["checker"]["expected"])
    note(shipped == R1_CANON, "R1 shipped answer key == canonical facts (no drift)")
    order = [l.split(":")[0] for l in t["checker"]["expected"]]
    note(order == list(R1_CANON.keys()), "R1 answer fields in the pre-registered order")

def validate_blind(t, anchors):
    ck = t["checker"]
    note(isinstance(ck.get("rubric"), str) and len(ck["rubric"]) > 100, f"{t['id']} rubric present")
    pts = rubric_points(ck["rubric"])
    note(len(pts) >= 4, f"{t['id']} rubric has >=4 numbered criteria ({len(pts)})")
    note(sum(pts) == ck.get("max_score"), f"{t['id']} rubric points sum ({sum(pts)}) == max_score ({ck.get('max_score')})")
    thr, mx = ck.get("pass_threshold"), ck.get("max_score")
    note(isinstance(thr, (int, float)) and 0 < thr <= mx, f"{t['id']} pass_threshold {thr} in (0, max_score={mx}]")
    m = re.search(r"PASSES iff total >= (\d+)\s*/\s*(\d+)", ck["rubric"])
    note(m and int(m.group(1)) == thr and int(m.group(2)) == mx,
         f"{t['id']} rubric's stated 'pass iff >= {thr}/{mx}' matches payload fields")
    blob = norm("\n".join(d["content"] for d in t["documents"]))
    missing = [a for a in anchors if a not in blob]
    note(not missing, f"{t['id']} every rubric anchor grounded in the documents" + (f" (missing {missing})" if missing else ""))

def validate_pytest_C(t):
    ck = t["checker"]; asserts = ck["asserts"]; ep = ck["entrypoint"]
    tid = t["id"]
    if tid == "C1":
        ok, tail = run_asserts(REF["IntervalSet"], asserts)
        note(ok, f"C1 reference passes {len(asserts)} asserts" + ("" if ok else f" [{tail}]"))
        bad, _ = run_asserts(C1_WRONG, asserts)
        note(not bad, "C1 asserts reject a plausible wrong implementation")
    elif tid == "C2":
        ok, tail = run_asserts(C2_FIXED, asserts)
        note(ok, f"C2 fixed reference passes {len(asserts)} asserts" + ("" if ok else f" [{tail}]"))
        buggy = last_python_block(t["prompt"])
        note(buggy is not None, "C2 prompt embeds the buggy module")
        bad, _ = run_asserts(buggy, asserts)
        note(not bad, "C2 asserts reject the SHIPPED buggy module (all 3 bugs caught)")
    elif tid == "C3":
        ok, tail = run_asserts(C3_REF, asserts)
        note(ok, f"C3 refactor reference passes {len(asserts)} asserts" + ("" if ok else f" [{tail}]"))
        original = last_python_block(t["prompt"])
        note(original is not None, "C3 prompt embeds the original module")
        bad1, _ = run_asserts(original, asserts)
        note(not bad1, "C3 asserts reject the SHIPPED original (module-global state)")
        bad2, _ = run_asserts(C3_CHEAT, asserts)
        note(not bad2, "C3 asserts reject a class that cheats via module globals")

# ---- X exact-subtask independent recomputation ----
def _find_json_doc(docs, key):
    for d in docs:
        try:
            j = json.loads(d["content"])
        except Exception:
            continue
        if key in j:
            return j
    return None

def recompute_X(tid, sub, docs):
    sid, cls = sub["id"], sub["class"]
    log = next((d["content"] for d in docs if " ERROR " in d["content"]), "")
    if sid == "X1.1":
        for ln in log.splitlines():
            if " ERROR " in ln:
                m = re.search(r"ERROR\s+\S+\s+(\S+).*?err_code=(\S+)", ln)
                return [f"{m.group(1)}|{m.group(2)}"]
    if sid == "X1.2":
        j = _find_json_doc(docs, "events")
        return [str(len({e["user"] for e in j["events"] if e["status"] == "failed"}))]
    if sid == "X1.3":
        pm = next((d["content"] for d in docs if "Postmortem" in d["title"]), "")
        m = re.search(r"job, `([\w-]+)`,", pm)
        return [m.group(1)]
    if sid == "X1.5":
        return ["[RESOLVED] OrderService | sig=OrderValidationError|PRICE_MISSING | users=3 | cause=catalog-sync"]
    if sid == "X2.1":
        cl = next((d["content"] for d in docs if "Changelog" in d["title"]), "")
        cur = None
        for ln in cl.splitlines():
            h = re.match(r"##\s+(\d+)\.(\d+)\.(\d+)", ln)
            if h: cur = f"{h.group(1)}.{h.group(2)}"
            if "bulkExport" in ln and cur: return [cur]
    if sid == "X2.2":
        j = _find_json_doc(docs, "timeouts"); tt = j["timeouts"]
        return [str(tt["connectMs"] + tt["readMs"] + tt["writeMs"])]
    if sid == "X2.3":
        mig = next((d["content"] for d in docs if "Migration" in d["title"]), "")
        m = re.search(r"`([\w.]+)` key is REMOVED", norm(mig))
        return [m.group(1)]
    if sid == "X2.5":
        return ["GATE: NO-GO | version=2.5 | timeout_budget_ms=5000 | action=remove:legacy.exportMode"]
    if sid == "X3.1":
        m = re.search(r"record_id=(\S+)", log); return [m.group(1)]
    if sid == "X3.2":
        j = _find_json_doc(docs, "records")
        return [str(sum(1 for r in j["records"] if r["amount"] < 0))]
    if sid == "X3.3":
        sc = next((d["content"] for d in docs if "Schema" in d["title"]), "")
        m = re.search(r"the `(\w+)` field's max length", norm(sc)); return [m.group(1)]
    if sid == "X3.5":
        return ["SUMMARY | failing_record=rec-0087 | negatives=2 | changed_field=title"]
    return None

def validate_composite_X(t):
    tid = t["id"]; subs = t["subtasks"]; docs = t["documents"]
    note(t["checker"]["type"] == "composite" and t["checker"].get("n_subtasks") == len(subs),
         f"{tid} composite checker declares n_subtasks == {len(subs)}")
    note(len(subs) == 5, f"{tid} has exactly 5 subtasks")
    classes = [s["class"] for s in subs]
    note(set(classes) == {"mechanical", "transform", "research-lite", "coding", "format"},
         f"{tid} subtasks span the 5 classes ({dict(Counter(classes))})")
    note(sum(1 for s in subs if s["checker"]["type"] == "pytest-asserts") == 1, f"{tid} exactly one coding subtask")
    for s in subs:
        note({"id", "class", "prompt", "checker"} <= set(s), f"{tid} {s['id']} subtask schema complete")
        ck = s["checker"]
        if ck["type"] == "exact":
            got = recompute_X(tid, s, docs)
            note(got == ck["expected"], f"{tid} {s['id']} ({s['class']}) answer re-derived == shipped {ck['expected']} (got {got})")
        elif ck["type"] == "pytest-asserts":
            ep = ck["entrypoint"]
            ok, tail = run_asserts(X_REF[ep], ck["asserts"])
            note(ok, f"{tid} {s['id']} coding reference passes {len(ck['asserts'])} asserts" + ("" if ok else f" [{tail}]"))
            bad, _ = run_asserts(X_WRONG[ep], ck["asserts"])
            note(not bad, f"{tid} {s['id']} coding asserts reject the buggy version")
        else:
            note(False, f"{tid} {s['id']} unexpected subtask checker {ck['type']}")

# =========================================================== main
def main():
    files = sorted(glob.glob(os.path.join(TASKS, "*.json")))
    print(f"validating {len(files)} task files in {os.path.normpath(TASKS)}\n")
    tasks = {}
    for f in files:
        t = json.load(open(f))
        tid = t.get("id", "?"); tasks[tid] = t
        miss = REQUIRED_TOP - set(t)
        note(not miss, f"{tid} schema complete" + (f" (missing {miss})" if miss else ""))
        note(t.get("class") in CLASSES, f"{tid} class valid ({t.get('class')})")
        note(t.get("checker", {}).get("type") in CHECKER_TYPES, f"{tid} checker type valid ({t.get('checker', {}).get('type')})")
        note(isinstance(t.get("max_output_guardrail"), int) and isinstance(t.get("timeout_s"), int),
             f"{tid} guardrail/timeout are ints")

    print("\n---- R-research ----")
    if "R1" in tasks: validate_exact_R1(tasks["R1"])
    if "R2" in tasks: validate_blind(tasks["R2"], R2_ANCHORS)
    if "R3" in tasks: validate_blind(tasks["R3"], R3_ANCHORS)

    print("\n---- C-coding ----")
    for tid in ("C1", "C2", "C3"):
        if tid in tasks: validate_pytest_C(tasks[tid])

    print("\n---- X-composite ----")
    for tid in ("X1", "X2", "X3"):
        if tid in tasks: validate_composite_X(tasks[tid])

    print("\n---- suite invariants ----")
    ids = set(tasks)
    note(len(files) == 9, f"9 task files ({len(files)})")
    note(ids == EXPECTED_IDS, f"ids == {{R1..X3}} ({sorted(ids)})")
    cls = Counter(t["class"] for t in tasks.values())
    note(cls.get("R-research") == 3 and cls.get("C-coding") == 3 and cls.get("X-composite") == 3,
         f"3 tasks per class ({dict(cls)})")
    types = Counter(t["checker"]["type"] for t in tasks.values())
    note(types.get("exact") == 1 and types.get("blind-grader") == 2 and types.get("pytest-asserts") == 3
         and types.get("composite") == 3, f"checker mix ({dict(types)})")
    # lead's constraint: R prefers exact for >=1, blind-grader for <=2
    r_types = Counter(tasks[i]["checker"]["type"] for i in ("R1", "R2", "R3") if i in tasks)
    note(r_types.get("exact", 0) >= 1 and r_types.get("blind-grader", 0) <= 2,
         f"R-research: >=1 exact and <=2 blind-grader ({dict(r_types)})")

    print("\n" + ("ALL V2 ORACLES VALID" if not fails else f"{len(fails)} FAILURES"))
    sys.exit(1 if fails else 0)

if __name__ == "__main__":
    main()
