# Release Protocol

The repeatable checklist for shipping an effortmining version. Follow every step, in
order. Do not skip the dogfood.

It exists because of a specific, embarrassing pattern: **the same field broke in two
consecutive releases.** `agent_type` logged `null` on a live dispatch, 0.5.2 fixed it
against a payload shape nobody replayed, and the fix was still wrong on the documented
install path. An outside user found it ([#1](https://github.com/nagisanzenin/effortmining/issues/1)),
not the 119 unit tests and not the 76 selftest checks — because **neither oracle
executed `hooks/*.sh` at all.** A release protocol that only runs the tests would have
shipped it a third time.

**Rule of thumb for the number** (semver): user-visible feature or a calibration-table
tier move → **minor** (`0.6.0`); bug fix, doc, or polish → **patch** (`0.5.3`); a
breaking change to `calibration.json`'s schema, the dispatch-log record shape, or the
skill/agent contract → **major**. When unsure, patch.

**What the world actually resolves.** Unlike a tag-pinned resolver: `claude plugin
install` clones the marketplace repo's **default branch** and reads
`.claude-plugin/plugin.json`'s `"version"` at that commit (it pins by `gitCommitSha`,
and caches into `~/.claude/plugins/cache/effortmining/effortmining/<version>/`). So
`main` + that one field *is* the release. The git tag and GitHub release are the
human-readable record — the changelog users read, and the only way to say later what
"0.5.2" was. Cut them anyway; they are how the project stays legible.

---

## 0 · Preconditions

```bash
cd ~/Documents/Github/effortmining
git checkout -b release/vX.Y.Z          # never work on main directly
python3 -m unittest discover -s tests   # must ALREADY be green before you start
python3 bench/effort.py selftest
```

- Work on a branch. `main` is what a fresh `claude plugin install` pulls, so it must
  never be half-broken — there is no tag to hide behind.
- Decide the version number `X.Y.Z` now; it appears in two files (step 2).

## 1 · Land the work

Make the change. Update the affected docs (`docs/`, `skills/`, `agents/`) in the same
branch.

**The deterministic core is `bench/effort.py` *and* `hooks/*.sh`.** New behavior in
either MUST be covered by a test that fails without it. The hooks were tacitly exempt
from this rule until 0.5.3, and that exemption is the whole reason this document has a
step 6. `tests/test_hooks.py` replays real payload shapes through the actual shell
script; extend it whenever you touch a hook.

If you cannot write a test that fails without your fix, you have not understood the bug.

## 2 · Bump the version — both locations

```bash
grep -rnE '"version"|badge/version-' .claude-plugin README.md
```

| File | What to change |
|---|---|
| `.claude-plugin/plugin.json` | `"version"` — **this is the one installs read** |
| `README.md` | version badge (`badge/version-X.Y.Z`) |

Re-run the grep after editing — zero stale hits, or the badge lies.

## 3 · Write the CHANGELOG

Add a new section at the **top** of `CHANGELOG.md`:

```
## [X.Y.Z] — YYYY-MM-DD

### Fixed / Added / Changed

- <what changed, and why. Credit outside reporters by issue number and handle.>
```

Two things every entry must state plainly, because they are what a user of a
*calibration* tool needs to know:

1. **Whether `calibration.json` moved**, and if so which class, from which tier to
   which, on how many graded runs.
2. **Whether calibration output is unchanged** when you touched telemetry. Say it
   outright — "calibration output unchanged; what returns is the audit trail" — so
   nobody re-derives the blast radius from the diff.

The release notes are generated from this section (step 8), so write it for a reader.

## 4 · The gates

```bash
python3 -m unittest discover -s tests      # 146 tests, must end OK
python3 bench/effort.py selftest           # "ALL INVARIANTS HELD"
python3 bench/effort.py selftest --suite v2 # "ALL INVARIANTS HELD"
bash -n hooks/*.sh                          # shell parses
git status --short                          # ONLY the files you meant to edit
```

That last line is a real invariant, not hygiene. The oracles run `validate`, `run`,
`grade`, `analyze`, `report` and `calibrate` against temp roots; if any of them ever
writes into the repo's `bench/state/` or `bench/RESULTS*.md`, a test run has quietly
mutated the committed deliverable. A dirty `calibration.json` after a test run is a
**stop-the-release bug in the harness**, not a file to `git add`.

Red anywhere here stops the release. No exceptions.

## 5 · The calibration guard (unique to this repo)

`bench/state/calibration.json` is the deliverable — the only tracked file under a
gitignored `bench/state/*`. Everything else in the plugin is machinery for producing
it. It changes **only** as the output of `calibrate` over real graded runs, never by
hand.

```bash
python3 - <<'PY'
import json
c = json.load(open("bench/state/calibration.json"))
p = c.get("provenance", {})
assert p.get("mode") == "real", f"mock calibration staged for release: {p}"
assert c.get("proven") is True, "unproven calibration staged for release"
assert c.get("version", 0) >= 1, "version reset to 0 — a mock refit overwrote it"
print("calibration OK: v%s, %d classes" % (c["version"], len(c["classes"])))
for k, v in c["classes"].items():
    print("  %-22s -> %s" % (k, v["recommended_tier"]))
PY
```

`selftest` runs `calibrate --mock`, which stamps `provenance.mode=mock`, `version=0`,
`proven=false`. It does this in a temp root. If those values ever appear in the tracked
file, a mock refit escaped its sandbox and you are about to ship a fabricated table.

**If a tier moved, the prose must move with it.** `hooks/session-start.sh` regenerates
the ambient-policy line from the JSON at runtime, so it self-heals. These do not:

```bash
grep -rlnE 'miner-(low|medium|high|xhigh|max)|recommended_tier' agents skills README.md docs
```

Every agent's `description:` frontmatter states which class it is calibrated for — that
text is what the dispatching model reads. A table that says `C-coding -> medium` while
`agents/miner-low.md` still claims C-coding is a stale, silent misroute.

## 6 · Hook replay against the real payload shape (never skip)

The automated version is `tests/test_hooks.py` (step 4). This step is the part a
synthetic payload **cannot** prove: that the field spellings the tests assume are the
ones the real CLI sends.

**Any plugin-loaded agent is addressed `<plugin>:<agent>`** — `effortmining:miner-low`.
This holds for `--plugin-dir` dev loads and for `claude plugin install` alike; the two
send the *same* spelling, verified live in the 0.5.3 dogfood. The bare `miner-low` form
has never been observed on the wire. The hook still handles it, defensively, but do not
mistake that branch for the one users exercise — assuming it was the live shape is
precisely how `agent_type: null` shipped twice.

```bash
# Confirm what the CLI actually put on the wire, from your own transcripts:
grep -ho '"subagent_type":"[^"]*"' ~/.claude/projects/*/*.jsonl | sort | uniq -c | sort -rn
```

If a spelling appears there that `tests/test_hooks.py` does not cover, add it before
you ship. Payload shapes are Claude Code's to change, not ours; the tests are a record
of what we have observed, and they go stale on someone else's schedule.

## 7 · The dogfood (never skip; green tests are not evidence)

Selftest proves the units. This proves the product: that an installed effortmining
routes a real subtask to the right tier and *records that it did*.

```bash
export EM_HOME=$(mktemp -d) && cp -R . "$EM_HOME/em" && cd "$EM_HOME/em"
# NEVER dogfood against the real installed plugin: its dispatch log is your telemetry.
```

Then, in Claude Code, in a scratch directory:

```bash
claude --plugin-dir "$EM_HOME/em" -p "Count the lines in filelist.txt, and separately
fix the off-by-one in second_largest(). Delegate each to a subagent."
```

Confirm with your own eyes, in this order:

1. The **SessionStart line** prints, and its ambient policy matches `calibration.json`.
2. The **transcript** (`~/.claude/projects/<proj>/<session>.jsonl`) shows the model
   dispatched via `Agent` with the tiers the policy prescribes — mechanical work to
   `miner-low`, the coding fix to `miner-medium`.
3. **`$EM_HOME/em/bench/state/dispatch-log.jsonl` records those tiers.** Not `null`.
   This line is the one that has lied in two releases.

```bash
cat "$EM_HOME/em/bench/state/dispatch-log.jsonl"
rm -rf "$EM_HOME"; unset EM_HOME
```

The 0.5.3 dogfood is the reference output — two dispatches, both resolved, tiers
matching the table:

```
{... "tool_name": "Agent", "agent_type": "effortmining:miner-low",    ...}   # T1 -> low
{... "tool_name": "Agent", "agent_type": "effortmining:miner-medium", ...}   # C  -> medium
```

**This step exists because it works.** Writing this protocol, I asserted that
`--plugin-dir` sends a bare `miner-low` while a marketplace install sends the
namespaced form, and built the reasoning for issue #1 on that distinction. The dogfood
run disproved it in one line of output: both send `effortmining:miner-low`. The real
root cause is duller and worse — `hooks/*.sh` had **no test coverage at all**, so an
assumption about the payload was never checked against a payload. No unit test and no
code review had found that in three releases. Only running the thing did.

A surprise here is not a reason to skip the release. It is the release.

## 8 · The adversarial review (never skip)

```bash
/code-review high        # against `git diff main...release/vX.Y.Z`
```

Name the diff and the risk areas: hook fail-open behavior, untrusted-payload handling,
the writer/reader seam between `log-dispatch.sh` and `normalize_dispatch_record()`,
and backward compatibility with dispatch logs written by older versions.

**Two rules, inherited from engram's v0.5.0 and confirmed here:**

1. **A green test suite means nothing about the design.** 119 passing tests coexisted
   with a telemetry field that was `null` for every real user.
2. **Never trust a review whose agents errored.** A run that dies on a session limit
   will cheerfully report "no findings survived verification." Check the failure list
   before you believe the verdict.

Every confirmed finding gets a fix **and** a test that fails without it.

## 9 · Merge, tag, release

```bash
V=X.Y.Z
git add -A && git commit    # "release: vX.Y.Z — <theme>" (+ Co-Authored-By trailer)
git checkout main && git pull origin main
git merge --no-ff "release/v$V" -m "Merge: vX.Y.Z — <theme>"
git push origin main        # <- the moment the release is live for new installs

# extract this version's CHANGELOG section as the release body:
python3 - "$V" > /tmp/relnotes.md <<'PY'
import sys
V = sys.argv[1]; on = False; out = []
for ln in open("CHANGELOG.md").read().splitlines():
    if ln.startswith(f"## [{V}]"): on = True; continue
    if on and ln.startswith("## "): break
    if on: out.append(ln)
sys.stdout.write("\n".join(out).strip() + "\n")
PY

git tag -a "v$V" -m "v$V — <theme>" && git push origin "v$V"
gh release create "v$V" --title "v$V — <theme>" --notes-file /tmp/relnotes.md --latest
```

Note the ordering: `git push origin main` is what ships. The tag and release are the
record, cut immediately after so the two never drift.

## 10 · Verify the release is real

```bash
gh release list -L 3                        # new vX.Y.Z shows "Latest"
git describe --tags --abbrev=0 origin/main  # == vX.Y.Z
git show origin/main:.claude-plugin/plugin.json | grep version   # == X.Y.Z
```

The third command is the one that matters. The first two can be perfect while `main`
still carries the old version — and `main` is what installs read.

## 11 · Tell existing users how to update

New installs pull `main` and are fine. Users who already installed must run:

```
claude plugin marketplace update effortmining && claude plugin update effortmining@effortmining
```

then restart Claude Code (or `/reload-plugins`). A plain `plugin update` before the
marketplace refresh reports "already current" against the stale cache.

**Say this in the release notes, with the telemetry caveat:** the plugin caches per
version (`cache/effortmining/effortmining/<version>/`), and `bench/state/dispatch-log.jsonl`
lives *inside* that directory. **Dispatch telemetry does not migrate across an update.**
A user who has been accumulating real-usage receipts to feed `calibrate` starts a fresh
log on every version bump; the old one remains in the old version's directory. If they
care about it, tell them to copy it forward before they update.

---

### One-glance checklist

- [ ] on a `release/` branch; both oracles green *before* starting
- [ ] work landed; new behavior in `bench/effort.py` **or `hooks/*.sh`** has a test that
      fails without the fix
- [ ] version bumped in `.claude-plugin/plugin.json` **and** the README badge (re-grep:
      zero stale)
- [ ] CHANGELOG section written; calibration impact stated outright
- [ ] `unittest` 146/146 OK · `selftest` v1 + v2 both "ALL INVARIANTS HELD" ·
      `bash -n hooks/*.sh` · **`git status` shows only intended files**
- [ ] calibration guard: `provenance.mode == "real"`, `proven == true`, `version >= 1`;
      any tier move mirrored in every agent/skill/README claim
- [ ] hook replay covers the spellings `subagent_type` actually takes in live transcripts
- [ ] **dogfood run against a plugin-shaped install**: ambient line prints, transcript
      shows the right tiers, `dispatch-log.jsonl` records them and is not `null`
- [ ] `/code-review high` on the branch diff; **no agent errored**; every confirmed
      finding fixed *and* covered by a test
- [ ] merged to main with `--no-ff` and **pushed** (this is what ships)
- [ ] annotated tag pushed **and** `gh release create … --latest`
- [ ] `git show origin/main:.claude-plugin/plugin.json` carries the new version
- [ ] update instructions noted, including that dispatch telemetry does not migrate

### Why the unusual steps exist (one line each)

- **Step 4's `git status` gate:** the harness writes the file it is testing. A test run
  that dirties `calibration.json` has mutated the deliverable.
- **Step 5's calibration guard:** `selftest` runs a mock refit that stamps
  `mode=mock, version=0, proven=false`. Shipping that ships a fabricated table.
- **Step 6's hook replay:** `hooks/*.sh` had zero coverage across three releases. The
  field that broke was the one the hook exists to capture.
- **Step 7's dogfood:** it caught a false claim *in this document* on its first run —
  that dev loads and marketplace installs send different `subagent_type` spellings. They
  do not. An untested assumption about a payload survives every test you write about it.
