#!/usr/bin/env python3
"""Unit tests for bench/effort.py — the effortmining benchmark harness.

Oracle of record (loop-protocol Tier 1): `python3 -m unittest` from the repo root
plus `python3 bench/effort.py selftest`. Both must stay green.

Covers: Wilson interval math against known values, Newcombe difference CI against
a published worked example + symmetry, the non-inferiority decision rule and its
edge cases, resumability (rerun skips completed cells), seeded-shuffle determinism,
the mock pipeline end-to-end, atomic-write crash-safety, env sanitization, answer
parsing/canonicalization, bootstrap determinism, and the exact / pytest graders.
"""
import argparse
import glob
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BENCH = os.path.join(os.path.dirname(HERE), "bench")
sys.path.insert(0, BENCH)
import effort as e  # noqa: E402

TASKS_DIR = os.path.join(BENCH, "tasks")


def _ns(root, **over):
    base = dict(root=root, tasks_dir=TASKS_DIR, seed=e.SEED_DEFAULT, model=e.MODEL,
               mock=True, scale="pilot", parallel=1, rerun_failed=False, regrade=False)
    base.update(over)
    return argparse.Namespace(**base)


class WilsonTest(unittest.TestCase):
    def test_known_values(self):
        # Textbook Wilson 95% score-interval values.
        for k, n, lo, hi in [(0, 10, 0.0, 0.2775), (5, 10, 0.2366, 0.7634),
                             (10, 10, 0.7225, 1.0)]:
            wl, wh = e.wilson_interval(k, n)
            self.assertAlmostEqual(wl, lo, places=3, msg=f"{k}/{n} lower")
            self.assertAlmostEqual(wh, hi, places=3, msg=f"{k}/{n} upper")

    def test_zero_n_is_full_interval(self):
        self.assertEqual(e.wilson_interval(0, 0), (0.0, 1.0))

    def test_clamped_to_unit(self):
        for k in range(0, 6):
            lo, hi = e.wilson_interval(k, 5)
            self.assertGreaterEqual(lo, 0.0)
            self.assertLessEqual(hi, 1.0)
            self.assertLessEqual(lo, hi)


class NewcombeTest(unittest.TestCase):
    def test_published_worked_example(self):
        # Newcombe (1998) method 10: 56/70 vs 48/80 -> ~(0.0524, 0.3339).
        lo, hi = e.newcombe_diff_ci(56, 70, 48, 80)
        self.assertAlmostEqual(lo, 0.0524, places=3)
        self.assertAlmostEqual(hi, 0.3339, places=3)

    def test_symmetry(self):
        # CI(p1-p2) == -reversed CI(p2-p1).
        lo12, hi12 = e.newcombe_diff_ci(7, 12, 4, 11)
        lo21, hi21 = e.newcombe_diff_ci(4, 11, 7, 12)
        self.assertAlmostEqual(lo12, -hi21, places=9)
        self.assertAlmostEqual(hi12, -lo21, places=9)

    def test_identical_samples_center_zero(self):
        lo, hi = e.newcombe_diff_ci(6, 9, 6, 9)
        self.assertAlmostEqual((lo + hi) / 2.0, 0.0, places=9)


class NonInferiorityTest(unittest.TestCase):
    def test_identical_high_pass_small_n_cannot_clear_interval(self):
        # Two 9/9 samples: point guard holds, interval guard cannot at n=9.
        d = e.noninferiority(9, 9, 9, 9)
        self.assertTrue(d["point_ok"])
        self.assertFalse(d["interval_ok"])
        self.assertFalse(d["noninferior"])

    def test_cheaper_at_least_as_good_clears(self):
        # Candidate strictly better than max clears both guards.
        d = e.noninferiority(9, 9, 6, 9)
        self.assertTrue(d["point_ok"])
        self.assertTrue(d["interval_ok"])
        self.assertTrue(d["noninferior"])
        self.assertGreaterEqual(d["diff_lo"], -e.DELTA)

    def test_clearly_worse_fails_point_guard(self):
        d = e.noninferiority(3, 9, 9, 9)
        self.assertFalse(d["point_ok"])
        self.assertFalse(d["noninferior"])

    def test_point_guard_boundary(self):
        # p_t = p_max - delta exactly -> point guard holds (>=).
        d = e.noninferiority(9, 10, 10, 10)  # 0.9 vs 1.0, delta 0.10
        self.assertTrue(d["point_ok"])

    def test_max_is_reference_for_itself(self):
        d = e.noninferiority(7, 9, 7, 9)
        self.assertTrue(d["point_ok"])  # zero difference always passes the point guard


class PercentileTest(unittest.TestCase):
    def test_endpoints_and_median(self):
        v = [1.0, 2.0, 3.0, 4.0, 5.0]
        self.assertEqual(e.percentile(v, 0), 1.0)
        self.assertEqual(e.percentile(v, 100), 5.0)
        self.assertEqual(e.percentile(v, 50), 3.0)

    def test_interpolation(self):
        self.assertAlmostEqual(e.percentile([0.0, 10.0], 25), 2.5)


class BootstrapTest(unittest.TestCase):
    def setUp(self):
        self.cells = {("a", "low"): [100, 110, 90], ("b", "low"): [200, 190, 210]}

    def _stat(self, cells):
        return sum(sum(v) / len(v) for v in cells.values())

    def test_seeded_determinism(self):
        r1 = e.bootstrap_ci(self.cells, self._stat, b=500, seed=42)
        r2 = e.bootstrap_ci(self.cells, self._stat, b=500, seed=42)
        self.assertEqual(r1, r2)

    def test_different_seed_differs(self):
        r1 = e.bootstrap_ci(self.cells, self._stat, b=500, seed=1)
        r2 = e.bootstrap_ci(self.cells, self._stat, b=500, seed=2)
        self.assertNotEqual((r1[1], r1[2]), (r2[1], r2[2]))

    def test_point_within_ci(self):
        point, lo, hi = e.bootstrap_ci(self.cells, self._stat, b=1000, seed=7)
        self.assertLessEqual(lo, point)
        self.assertLessEqual(point, hi)


class ShuffleTest(unittest.TestCase):
    def setUp(self):
        self.tasks = e.load_tasks(TASKS_DIR)
        self.cells = e.build_cells(self.tasks, "pilot")

    def test_matrix_size(self):
        self.assertEqual(len(self.cells), 12 * 5 * 3)  # 12 tasks x 5 tiers x 3 reps

    def test_same_seed_same_order(self):
        a = e.seeded_shuffle(self.cells, 20260706)
        b = e.seeded_shuffle(self.cells, 20260706)
        keys_a = [(c["task"]["id"], c["tier"], c["rep"]) for c in a]
        keys_b = [(c["task"]["id"], c["tier"], c["rep"]) for c in b]
        self.assertEqual(keys_a, keys_b)

    def test_different_seed_different_order(self):
        a = e.seeded_shuffle(self.cells, 1)
        b = e.seeded_shuffle(self.cells, 2)
        keys_a = [(c["task"]["id"], c["tier"], c["rep"]) for c in a]
        keys_b = [(c["task"]["id"], c["tier"], c["rep"]) for c in b]
        self.assertNotEqual(keys_a, keys_b)

    def test_is_permutation(self):
        shuffled = e.seeded_shuffle(self.cells, 20260706)
        orig = sorted((c["task"]["id"], c["tier"], c["rep"]) for c in self.cells)
        got = sorted((c["task"]["id"], c["tier"], c["rep"]) for c in shuffled)
        self.assertEqual(orig, got)


class CanonicalizeParseTest(unittest.TestCase):
    def test_canonicalize_strips_outer_and_trailing(self):
        self.assertEqual(e.canonicalize("  \n a  \n b   \n  "), "a\n b")

    def test_answer_tags_first_match(self):
        txt = "pre <answer>X\nY</answer> mid <answer>Z</answer>"
        self.assertEqual(e.extract_answer_tags(txt), "X\nY")

    def test_answer_tags_absent(self):
        self.assertIsNone(e.extract_answer_tags("no tags here"))

    def test_code_block_prefers_last_python(self):
        txt = "```python\nold=1\n```\ntext\n```python\nnew=2\n```"
        self.assertIn("new=2", e.extract_code_block(txt))
        self.assertNotIn("old=1", e.extract_code_block(txt))

    def test_code_block_fallback_any_lang(self):
        txt = "```\nplain=1\n```"
        self.assertIn("plain=1", e.extract_code_block(txt))

    def test_code_block_absent(self):
        self.assertIsNone(e.extract_code_block("no fences"))


class GraderTest(unittest.TestCase):
    def test_exact_pass(self):
        raw = "result:\n<answer>\na|b|c\n</answer>"
        ok, fc, _ = e.grade_exact(raw, ["a|b|c"])
        self.assertTrue(ok)
        self.assertEqual(fc, "none")

    def test_exact_wrong(self):
        ok, fc, _ = e.grade_exact("<answer>x</answer>", ["y"])
        self.assertFalse(ok)
        self.assertEqual(fc, "wrong_answer")

    def test_exact_parse_fail(self):
        ok, fc, _ = e.grade_exact("no tags", ["y"])
        self.assertFalse(ok)
        self.assertEqual(fc, "parse_fail")

    def test_pytest_pass_with_reference_solution(self):
        # Use the embedded mock solution + the real shipped asserts.
        checker = {"asserts": ["assert normalize_phone('415-555-2671') == '(415) 555-2671'",
                              "assert normalize_phone('12345') == 'INVALID'"],
                   "timeout_s": 5, "entrypoint": "normalize_phone"}
        raw = "```python\n" + e._MOCK_SOLUTIONS["normalize_phone"] + "```"
        ok, fc, _ = e.grade_pytest(raw, checker)
        self.assertTrue(ok)
        self.assertEqual(fc, "none")

    def test_pytest_wrong_answer(self):
        checker = {"asserts": ["assert f(1) == 2"], "timeout_s": 5, "entrypoint": "f"}
        raw = "```python\ndef f(x):\n    return 0\n```"
        ok, fc, _ = e.grade_pytest(raw, checker)
        self.assertFalse(ok)
        self.assertEqual(fc, "wrong_answer")

    def test_pytest_parse_fail(self):
        ok, fc, _ = e.grade_pytest("no code block", {"asserts": [], "timeout_s": 5,
                                                     "entrypoint": "f"})
        self.assertFalse(ok)
        self.assertEqual(fc, "parse_fail")

    def test_sandbox_runs_in_isolated_cwd(self):
        # Model code executes in a fresh sandbox tempdir (containing only prog.py),
        # never the harness's real working directory — proves cwd isolation.
        checker = {"asserts": ["assert 'prog.py' in f()",
                              "assert 'bench' not in f() and 'tests' not in f()"],
                   "timeout_s": 5, "entrypoint": "f"}
        raw = "```python\nimport os\ndef f():\n    return os.listdir('.')\n```"
        ok, fc, _ = e.grade_pytest(raw, checker)
        self.assertTrue(ok)
        self.assertEqual(fc, "none")


class EnvSanitizationTest(unittest.TestCase):
    def test_strips_effort_override(self):
        parent = {"PATH": "/bin", e.EFFORT_ENV_OVERRIDE: "max"}
        env, audit = e.build_child_env(parent)
        self.assertNotIn(e.EFFORT_ENV_OVERRIDE, env)
        self.assertTrue(audit["effort_level_override_present"])

    def test_strips_extra_body_with_effort(self):
        parent = {e.EXTRA_BODY_ENV: '{"output_config":{"effort":"low"}}'}
        env, audit = e.build_child_env(parent)
        self.assertNotIn(e.EXTRA_BODY_ENV, env)
        self.assertTrue(audit["extra_body_stripped"])

    def test_keeps_extra_body_without_effort(self):
        parent = {e.EXTRA_BODY_ENV: '{"metadata":{"user":"x"}}'}
        env, _ = e.build_child_env(parent)
        self.assertIn(e.EXTRA_BODY_ENV, env)

    def test_strips_max_output_tokens_and_api_key(self):
        parent = {e.MAX_OUTPUT_TOKENS_ENV: "128", e.API_KEY_ENV: "sk-xxx"}
        env, audit = e.build_child_env(parent)
        self.assertNotIn(e.MAX_OUTPUT_TOKENS_ENV, env)
        self.assertNotIn(e.API_KEY_ENV, env)
        self.assertTrue(audit["api_key_stripped"])


class AtomicWriteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="effort-atomic-")
        self.path = os.path.join(self.tmp, "sub", "file.json")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_full_write_replaces(self):
        e.atomic_write_json(self.path, {"v": 1})
        e.atomic_write_json(self.path, {"v": 2})
        self.assertEqual(e.load_json(self.path)["v"], 2)

    def test_crash_before_replace_leaves_original_intact(self):
        e.atomic_write_json(self.path, {"v": "original"})
        orig_replace = e.os.replace

        def boom(src, dst):
            raise OSError("simulated crash before replace")

        e.os.replace = boom
        try:
            with self.assertRaises(OSError):
                e.atomic_write_json(self.path, {"v": "new"})
        finally:
            e.os.replace = orig_replace
        # Original content survived; no partial file at the destination.
        self.assertEqual(e.load_json(self.path)["v"], "original")
        # No leftover temp swap files in the directory.
        strays = glob.glob(os.path.join(os.path.dirname(self.path), ".tmp-*"))
        self.assertEqual(strays, [])

    def test_jsonl_append_and_quarantine(self):
        p = os.path.join(self.tmp, "log.jsonl")
        e.append_jsonl(p, {"a": 1})
        e.append_jsonl(p, {"a": 2})
        # Simulate a torn trailing line from an interrupted append.
        with open(p, "a", encoding="utf-8") as f:
            f.write('{"a": 3, partial')
        recs, bad = e.read_jsonl(p)
        self.assertEqual([r["a"] for r in recs], [1, 2])
        self.assertEqual(bad, 1)


class ResumabilityTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="effort-resume-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_rerun_skips_completed(self):
        ns = _ns(self.tmp, scale="reduced")  # smaller matrix for speed
        paths = e.Paths(self.tmp, TASKS_DIR)
        e.cmd_run(ns)
        first = len(e.read_jsonl(paths.results)[0])
        e.cmd_run(ns)
        second = len(e.read_jsonl(paths.results)[0])
        self.assertEqual(first, second, "resume must append zero new records")
        # Every matrix cell present exactly once (via latest_by_key).
        tasks = e.load_tasks(TASKS_DIR)
        expected = len(e.build_cells(tasks, "reduced"))
        self.assertEqual(first, expected)

    def test_latest_by_key_prefers_non_error(self):
        err = {"task_id": "T1a", "tier": "low", "rep": 1, "api_error": True,
               "exit_status": 1}
        ok = {"task_id": "T1a", "tier": "low", "rep": 1, "api_error": False,
              "exit_status": 0, "output_tokens": 5, "fidelity_ok": True}
        latest = e.latest_by_key([err, ok])
        self.assertFalse(latest[("T1a", "low", 1)]["api_error"])


class MockPipelineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="effort-e2e-")
        self.paths = e.Paths(self.tmp, TASKS_DIR)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_full_offline_pipeline(self):
        ns = _ns(self.tmp, scale="reduced")
        self.assertEqual(e.cmd_validate(ns), 0)
        e.cmd_run(ns)
        e.cmd_grade(ns)
        e.cmd_analyze(ns)
        e.cmd_report(ns)
        e.cmd_calibrate(ns)

        # phase0 gate
        self.assertTrue(e.load_json(self.paths.phase0)["gate_passed"])
        # analysis structure
        analysis = e.load_json(self.paths.analysis)
        for cls, info in analysis["per_class"].items():
            self.assertIn(info["recommended_tier"], e.TIERS)
            for t, ti in info["tiers"].items():
                lo, hi = ti["wilson"]
                self.assertTrue(0.0 <= lo <= hi <= 1.0)
        # calibration is valid and covers the reduced-scale classes
        cal = e.load_json(self.paths.calibration)
        self.assertEqual(cal["version"], 1)
        for c in cal["classes"].values():
            self.assertIn(c["tier"], e.TIERS)
        # report exists, non-empty, no emoji
        with open(self.paths.results_md, encoding="utf-8") as f:
            md = f.read()
        self.assertIn("Policy headline", md)
        self.assertFalse(any(0x1F000 <= ord(ch) <= 0x1FAFF for ch in md))

    def test_mock_is_deterministic(self):
        tasks = {t["id"]: t for t in e.load_tasks(TASKS_DIR)}
        t1a = tasks["T1a"]
        env1 = e.mock_envelope(t1a, "high", 1, e.SEED_DEFAULT)
        env2 = e.mock_envelope(t1a, "high", 1, e.SEED_DEFAULT)
        self.assertEqual(env1["usage"]["output_tokens"], env2["usage"]["output_tokens"])
        self.assertEqual(env1["result"], env2["result"])

    def test_mock_modulation_holds(self):
        # median(max out) >= 2x median(low out) on the mock probe scaling.
        self.assertGreaterEqual(e.MOCK_BASE_OUT["max"], 2 * e.MOCK_BASE_OUT["low"])


class CalibrateGuardTest(unittest.TestCase):
    def test_single_step_toward_target(self):
        self.assertEqual(e._step_toward("low", "max"), "medium")
        self.assertEqual(e._step_toward("max", "low"), "xhigh")
        self.assertEqual(e._step_toward("high", "high"), "high")

    def test_step_clamped(self):
        self.assertEqual(e._step_toward("low", "low"), "low")
        self.assertEqual(e._step_toward("max", "max"), "max")


def _graded(cls, tier, passed, out, tid=None):
    return {"task_id": tid or (cls + "-t"), "class": cls, "tier": tier,
            "pass": bool(passed), "output_tokens": out, "seed": 1,
            "scale": "test", "model": "m", "cli_version": "v"}


class AnalyzeCeilingTest(unittest.TestCase):
    """Reference = empirical quality-ceiling tier (arg-max pass), not mechanically max."""

    def test_ceiling_is_argmax_pass_and_overthinking_flagged(self):
        cls = "T4-hard-reasoning"
        tasks = {cls + "-t": {"id": cls + "-t", "class": cls}}
        g = []
        counts = {"low": 3, "medium": 5, "high": 8, "xhigh": 9, "max": 6}  # /9
        outs = {"low": 120, "medium": 400, "high": 1000, "xhigh": 2200, "max": 4500}
        for tier, k in counts.items():
            for i in range(9):
                g.append(_graded(cls, tier, i < k, outs[tier]))
        a = e.analyze_core(tasks, g, seed=1)
        info = a["per_class"][cls]
        # xhigh (9/9) beats max (6/9): ceiling anchors to xhigh, not the degraded max.
        self.assertEqual(info["ceiling_tier"], "xhigh")
        # H3: max pass <= xhigh pass AND max tokens > xhigh tokens.
        self.assertTrue(info["overthinking"])

    def test_tie_breaks_to_cheaper_tier(self):
        cls = "T1-mechanical"
        tasks = {cls + "-t": {"id": cls + "-t", "class": cls}}
        g = [_graded(cls, t, True, {"low": 120, "high": 1000, "max": 4500}[t])
             for t in ("low", "high", "max") for _ in range(9)]
        a = e.analyze_core(tasks, g, seed=1)
        # all perfect -> ceiling ties -> cheapest present tier wins.
        self.assertEqual(a["per_class"][cls]["ceiling_tier"], "low")

    def test_perfect_tie_pilot_recommends_low_not_max(self):
        # Orchestrator rework oracle (rework-log.md, B2 analyze): a perfect-tie pilot
        # (every tier at ceiling) must recommend `low` everywhere, NOT the degenerate
        # `max` everywhere the original max-referenced rule produced. Ratchet: the
        # number of classes recommending max must be 0.
        classes = ["T1-mechanical", "T2-simple-transform",
                   "T3-moderate-reasoning", "T4-hard-reasoning"]
        tasks = {c + "-t": {"id": c + "-t", "class": c} for c in classes}
        outs = {"low": 120, "medium": 400, "high": 1000, "xhigh": 2200, "max": 4500}
        g = [_graded(c, t, True, outs[t])
             for c in classes for t in e.TIERS for _ in range(9)]
        a = e.analyze_core(tasks, g, seed=1)
        recs = {c: a["per_class"][c]["recommended_tier"] for c in classes}
        self.assertTrue(all(r == "low" for r in recs.values()), recs)
        self.assertEqual(sum(1 for r in recs.values() if r == "max"), 0)


class TOSTEquivalenceTest(unittest.TestCase):
    def test_equivalence_confirmed_at_large_n(self):
        cls = "T1-mechanical"  # an easy class -> TOST applies
        tasks = {cls + "-t": {"id": cls + "-t", "class": cls}}
        g = []
        for i in range(100):
            g.append(_graded(cls, "low", i < 98, 120))   # 0.98
            g.append(_graded(cls, "max", True, 4500))     # 1.00 -> ceiling
        a = e.analyze_core(tasks, g, seed=1)
        info = a["per_class"][cls]
        self.assertTrue(info["equivalence_low"])          # 90% CI within +/-10pp
        self.assertEqual(info["confidence"], "high(equiv)")

    def test_hard_class_has_no_equivalence(self):
        cls = "T4-hard-reasoning"  # not an easy class
        tasks = {cls + "-t": {"id": cls + "-t", "class": cls}}
        g = [_graded(cls, t, True, 100) for t in ("low", "max") for _ in range(9)]
        a = e.analyze_core(tasks, g, seed=1)
        self.assertIsNone(a["per_class"][cls]["equivalence_low"])


class DispatchLogTest(unittest.TestCase):
    KNOWN = {"T1-mechanical", "T2-simple-transform", "T3-moderate-reasoning",
             "T4-hard-reasoning"}

    def test_effortmine_record_resolves(self):
        rec = {"source": "effortmine", "task_class": "T3-moderate-reasoning",
               "tier": "high", "accepted": True}
        self.assertEqual(e.normalize_dispatch_record(rec, self.KNOWN),
                         ("T3-moderate-reasoning", "high", True))

    def test_hook_record_agent_type_only_is_unresolvable(self):
        rec = {"source": "posttooluse-hook", "agent_type": "miner-high",
               "session_id": "x"}
        # tier derivable from miner-high, but CLASS is not -> skip.
        self.assertIsNone(e.normalize_dispatch_record(rec, self.KNOWN))

    def test_load_counts_consumed_and_skipped(self):
        tmp = tempfile.mkdtemp(prefix="effort-dlog-")
        try:
            p = os.path.join(tmp, "dispatch-log.jsonl")
            with open(p, "w", encoding="utf-8") as f:
                f.write(json.dumps({"source": "effortmine", "task_class": "T1-mechanical",
                                    "tier": "low", "accepted": True}) + "\n")
                f.write(json.dumps({"source": "effortmine", "task_class": "T1-mechanical",
                                    "tier": "low", "accepted": False}) + "\n")
                f.write(json.dumps({"source": "posttooluse-hook",
                                    "agent_type": "miner-low"}) + "\n")
            graded, consumed, skipped = e.load_dispatch_log(p, self.KNOWN)
            self.assertEqual((consumed, skipped), (2, 1))
            self.assertEqual(graded[("T1-mechanical", "low")], {"k": 1, "n": 2})
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_missing_log_is_safe(self):
        graded, consumed, skipped = e.load_dispatch_log("/nonexistent/x.jsonl", self.KNOWN)
        self.assertEqual((graded, consumed, skipped), ({}, 0, 0))


class EffortFidelityTest(unittest.TestCase):
    def _task(self):
        return {"id": "T1a", "class": "T1-mechanical", "checker": {"type": "exact"}}

    def test_record_valid_requires_match_and_source(self):
        env = {"usage": {"input_tokens": 10, "output_tokens": 20}, "session_id": "s"}
        rec = e.envelope_to_record(env, self._task(), "high", 1, scale="pilot", seed=1,
                                   nonce="n", model="m", cli_version="v", ts_start="t",
                                   exit_status=0, retries=0, raw_answer_path="p",
                                   effort_effective="high", effort_effective_source="hook")
        self.assertTrue(rec["fidelity_ok"])
        self.assertTrue(e.record_valid(rec))

    def test_downgrade_is_invalid(self):
        env = {"usage": {}, "session_id": "s"}
        rec = e.envelope_to_record(env, self._task(), "max", 1, scale="pilot", seed=1,
                                   nonce="n", model="m", cli_version="v", ts_start="t",
                                   exit_status=0, retries=0, raw_answer_path="p",
                                   effort_effective="high", effort_effective_source="hook")
        self.assertFalse(rec["fidelity_ok"])       # requested max != effective high
        self.assertFalse(e.record_valid(rec))

    def test_unverified_is_invalid(self):
        env = {"usage": {}, "session_id": "s"}
        rec = e.envelope_to_record(env, self._task(), "high", 1, scale="pilot", seed=1,
                                   nonce="n", model="m", cli_version="v", ts_start="t",
                                   exit_status=0, retries=0, raw_answer_path="p",
                                   effort_effective="unverified",
                                   effort_effective_source="unverified")
        self.assertFalse(e.record_valid(rec))

    def test_envelope_bound_field_names(self):
        env = {"usage": {"input_tokens": 5, "output_tokens": 7,
                         "cache_read_input_tokens": 3, "cache_creation_input_tokens": 1},
               "total_cost_usd": 0.01, "session_id": "s", "modelUsage": {"m": {}}}
        rec = e.envelope_to_record(env, self._task(), "low", 1, scale="pilot", seed=1,
                                   nonce="n", model="m", cli_version="v", ts_start="t",
                                   exit_status=0, retries=0, raw_answer_path="p",
                                   effort_effective="low", effort_effective_source="mock")
        for field in ("effort_requested", "effort_effective", "input_tokens",
                      "output_tokens", "total_tokens", "cache_read_input_tokens",
                      "cache_creation_input_tokens", "total_cost_usd", "model_usage"):
            self.assertIn(field, rec)
        self.assertEqual(rec["total_tokens"], 12)

    def test_sidecar_join_by_session_id(self):
        tmp = tempfile.mkdtemp(prefix="effort-side-")
        try:
            settings_path, sidecar = e.setup_effort_capture(tmp)
            cfg = e.load_json(settings_path)
            self.assertIn("Stop", cfg["hooks"])          # capture hook on Stop
            with open(sidecar, "w", encoding="utf-8") as f:
                f.write(json.dumps({"session_id": "s1", "effort_level": "xhigh"}) + "\n")
                f.write(json.dumps({"session_id": "s2", "effort_level": "low"}) + "\n")
            self.assertEqual(e.effective_from_sidecar(sidecar, "s1"), "xhigh")
            self.assertEqual(e.effective_from_sidecar(sidecar, "s2"), "low")
            self.assertIsNone(e.effective_from_sidecar(sidecar, "absent"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
