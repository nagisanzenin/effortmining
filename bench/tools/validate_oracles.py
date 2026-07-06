#!/usr/bin/env python3
"""Reproducible oracle-integrity check for the effortmining pilot task suite.

Run from anywhere:  python3 bench/tools/validate_oracles.py
Exit 0 iff every shipped oracle in ../tasks is correct and self-consistent.

For EXACT tasks it recomputes the expected answer from first principles and
compares to the shipped 'expected' (and confirms the input still appears in the
prompt, so answer/prompt drift is caught). For PYTEST tasks it runs the file's
own asserts against an independent reference solution in a sandboxed subprocess.
Pure Python 3 stdlib. This is validation tooling, NOT a claude generation run."""
import json, glob, os, subprocess, sys, tempfile, itertools, datetime, re
from collections import Counter

TASKS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tasks")
REQUIRED = {"id","class","title","prompt","answer_convention","checker","max_output_tokens","difficulty_rationale"}
fails = []

def note(ok, msg):
    print(f"{'PASS' if ok else 'FAIL'} {msg}")
    if not ok: fails.append(msg)

# ---- independent recomputation of each EXACT answer ----
def recompute_exact(tid):
    if tid == "T1a":
        log = ["2026-03-01T08:12:04Z INFO  auth-svc      user login ok uid=4471",
               "2026-03-01T08:12:05Z ERROR billing-svc   charge failed code=5012 uid=4471",
               "2026-03-01T08:12:06Z WARN  auth-svc      slow response code=0",
               "2026-03-01T08:12:09Z ERROR ledger-svc    write conflict code=4090 txn=88123",
               "2026-03-01T08:12:10Z INFO  billing-svc   retry scheduled code=0",
               "2026-03-01T08:12:11Z ERROR billing-svc   charge failed code=5012 uid=4472"]
        out = []
        for ln in log:
            m = re.match(r"(\S+)\s+ERROR\s+(\S+).*?code=(\d+)", ln)
            if m: out.append(f"{m.group(1)}|{m.group(2)}|{m.group(3)}")
        return out
    if tid == "T1b":
        b = {"order":{"id":"A-91","items":[{"sku":"X1","qty":3},{"sku":"X2","qty":1}],
             "customer":{"name":"Ree","tier":"gold"}},"ts":"2026-05"}
        tq = sum(i["qty"] for i in b["order"]["items"])
        ds = len({i["sku"] for i in b["order"]["items"]})
        return sorted([f"distinct_skus={ds}", f"tier={b['order']['customer']['tier']}", f"total_qty={tq}"])
    if tid == "T1c":
        raw = "Blue, red, GREEN, blue,  Yellow,red , green"
        return [",".join(sorted({t.strip().lower() for t in raw.split(",")}))]
    if tid == "T3b":
        ppl, dr = ["Ada","Ben","Cy","Dot"], ["tea","cola","water","juice"]
        sols = []
        for perm in itertools.permutations(dr):
            a = dict(zip(ppl, perm))
            if a["Ada"] in ("tea","water"): continue
            if a["Ben"] in ("cola","juice"): continue
            if a["Cy"] != "water": continue
            jp = next(p for p in ppl if a[p]=="juice"); cp = next(p for p in ppl if a[p]=="cola")
            if not jp < cp: continue
            sols.append(a)
        assert len(sols) == 1, f"T3b not unique: {len(sols)} solutions"
        a = sols[0]
        return [f"Ada={a['Ada']},Ben={a['Ben']},Cy={a['Cy']},Dot={a['Dot']}"]
    if tid == "T3c":
        def process(seq):
            st = []
            for x in seq:
                if x == 'D' and st: st.pop()
                elif x == 'X' and st: st[-1] += 1
                else: st.append(1)
            return sum(st)
        return [str(process("AADXDA"))]
    if tid == "T4b":
        c = sum(1 for cmb in itertools.product("HT", repeat=6)
                if "HHH" not in "".join(cmb) and "TTT" not in "".join(cmb))
        return [str(c)]
    raise KeyError(tid)

# ---- independent reference solutions for PYTEST tasks ----
REF = {
"normalize_phone": "def normalize_phone(s):\n d=''.join(c for c in s if c.isdigit())\n if len(d)<10: return 'INVALID'\n d=d[-10:]\n return '('+d[0:3]+') '+d[3:6]+'-'+d[6:10]\n",
"rle": "def rle(s):\n if not s: return ''\n out=[]; c=s[0]; n=1\n for ch in s[1:]:\n  if ch==c: n+=1\n  else:\n   out.append(c+(str(n) if n>1 else '')); c=ch; n=1\n out.append(c+(str(n) if n>1 else ''))\n return ''.join(out)\n",
"business_days": "import datetime\ndef business_days(a,b):\n s=datetime.date.fromisoformat(a); e=datetime.date.fromisoformat(b); n=0; d=s\n while d<=e:\n  if d.weekday()<5: n+=1\n  d+=datetime.timedelta(days=1)\n return n\n",
"median": "def median(nums):\n s=sorted(nums); n=len(s)\n return s[n//2] if n%2 else (s[n//2-1]+s[n//2])/2\n",
"final_balance": "def final_balance(ev):\n bal=0; h=0\n for k,a in ev:\n  if k=='deposit': bal+=a\n  elif k=='withdraw':\n   if bal-h>=a: bal-=a\n  elif k=='hold': h+=a\n  elif k=='release': h=max(0,h-a)\n return bal-h\n",
"resolve": "def resolve(deps):\n done=[]; ds=set(); rem=set(deps)\n while True:\n  ready=sorted(t for t in rem if all(p in ds for p in deps[t]))\n  if not ready: break\n  p=ready[0]; done.append(p); ds.add(p); rem.discard(p)\n return done\n",
}
# tokens that MUST still appear in an exact task's prompt (drift guard)
INPUT_MARKERS = {
"T1a": "2026-03-01T08:12:05Z ERROR billing-svc",
"T1b": "\"sku\":\"X1\",\"qty\":3",
"T1c": "Blue, red, GREEN, blue,  Yellow,red , green",
"T3b": "Ada ordered neither tea nor water",
"T3c": "print(process('AADXDA'))",
"T4b": "length 6",
}

files = sorted(glob.glob(os.path.join(TASKS, "*.json")))
print(f"validating {len(files)} task files in {os.path.normpath(TASKS)}\n")
ids, classes, types = [], [], []
for f in files:
    t = json.load(open(f))
    tid = t.get("id","?"); ids.append(tid); classes.append(t.get("class")); types.append(t.get("checker",{}).get("type"))
    miss = REQUIRED - set(t)
    note(not miss, f"{tid} schema complete" + (f" (missing {miss})" if miss else ""))
    ck = t["checker"]; prompt = "\n".join(t["prompt"])
    if ck["type"] == "exact":
        got = recompute_exact(tid)
        note(ck["expected"] == got, f"{tid} exact expected == independently recomputed")
        note(INPUT_MARKERS[tid] in prompt, f"{tid} prompt still contains its input marker")
    elif ck["type"] == "pytest-asserts":
        prog = REF[ck["entrypoint"]] + "\n" + "\n".join(ck["asserts"]) + "\nprint('OK')\n"
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as tf:
            tf.write(prog); path = tf.name
        r = subprocess.run([sys.executable,"-I",path], capture_output=True, text=True, timeout=ck.get("timeout_s",5))
        os.unlink(path)
        note(r.returncode==0 and r.stdout.strip().endswith("OK"),
             f"{tid} {len(ck['asserts'])} asserts satisfied by reference "
             + ("" if r.returncode==0 else f"[{(r.stderr.strip().splitlines() or [''])[-1]}]"))
    else:
        note(False, f"{tid} unknown checker type {ck['type']}")

print("\n---- suite invariants ----")
note(len(ids)==12, f"12 tasks ({len(ids)})")
note(len(set(ids))==12, "unique ids")
note(all(v==3 for v in Counter(classes).values()) and len(Counter(classes))==4, f"3 tasks/class {dict(Counter(classes))}")
note(types.count("blind-grader")==0, f"blind-grader count 0 (mix {dict(Counter(types))})")
print("\n" + ("ALL ORACLES VALID" if not fails else f"{len(fails)} FAILURES"))
sys.exit(1 if fails else 0)
