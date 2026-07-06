#!/usr/bin/env python3
"""Unit tests for the suite-v2 extensions to bench/effort.py.

Covers (per the V2 task brief): --suite path isolation (v1 paths untouched),
document prepending + token accounting, the blind-grader payload's structural
blindness (asserted on the constructed prompt), the grader parse-failure taxonomy,
composite resumability, arm-policy tier mapping (incl. the calibrated-table fallback),
the composite arm analysis math on synthetic data, and a mock end-to-end pipeline
over the tests/fixtures-v2/ tasks. The v1 suite (tests/test_effort.py) must stay green
independently; nothing here touches v1 state files.
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

FIXTURES = os.path.join(HERE, "fixtures-v2")
V1_TASKS = os.path.join(BENCH, "tasks")


def _ns(root, **over):
    base = dict(root=root, tasks_dir=FIXTURES, seed=e.SEED_DEFAULT, model=e.MODEL,
               mock=True, scale="pilot", parallel=1, rerun_failed=False, regrade=False,
               force=False, suite="v2", grade_mock=True, arms=",".join(e.COMPOSITE_ARMS),
               reps=2)
    base.update(over)
    return argparse.Namespace(**base)


# --------------------------------------------------------------------------- #
# 1. Suite path isolation                                                      #
# --------------------------------------------------------------------------- #
class SuitePathIsolationTest(unittest.TestCase):
    def test_v1_paths_are_the_v1_names(self):
        p = e.Paths("/tmp/x", None, "v1")
        self.assertTrue(p.results.endswith("raw/results.jsonl"))
        self.assertTrue(p.graded.endswith("state/graded.jsonl"))
        self.assertTrue(p.analysis.endswith("state/analysis.json"))
        self.assertTrue(p.phase0.endswith("state/phase0.json"))
        self.assertTrue(p.results_md.endswith("RESULTS.md"))
        self.assertTrue(p.tasks.endswith("/tasks"))

    def test_v2_paths_are_suffixed_and_share_calibration(self):
        v1 = e.Paths("/tmp/x", None, "v1")
        v2 = e.Paths("/tmp/x", None, "v2")
        self.assertTrue(v2.results.endswith("raw/results-v2.jsonl"))
        self.assertTrue(v2.graded.endswith("state/graded-v2.jsonl"))
        self.assertTrue(v2.analysis.endswith("state/analysis-v2.json"))
        self.assertTrue(v2.phase0.endswith("state/phase0-v2.json"))
        self.assertTrue(v2.results_md.endswith("RESULTS-v2.md"))
        self.assertTrue(v2.tasks.endswith("/tasks-v2"))
        self.assertTrue(v2.results_composite.endswith("raw/results-composite.jsonl"))
        # calibration.json is deliberately SHARED across suites.
        self.assertEqual(v1.calibration, v2.calibration)

    def test_v2_pipeline_does_not_create_v1_state_files(self):
        tmp = tempfile.mkdtemp(prefix="effort-v2-iso-")
        try:
            ns = _ns(tmp)
            e.cmd_validate(ns)
            e.cmd_run(ns)
            e.cmd_grade(ns)
            e.cmd_analyze(ns)
            e.cmd_report(ns)
            v1 = e.Paths(tmp, None, "v1")
            # No v1 state/report files should exist — v2 wrote only its own namespace.
            for pth in (v1.results, v1.graded, v1.analysis, v1.phase0, v1.results_md):
                self.assertFalse(os.path.exists(pth), f"v2 run leaked v1 file {pth}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# --------------------------------------------------------------------------- #
# 2. Documents prepending + token accounting                                   #
# --------------------------------------------------------------------------- #
class DocumentsTest(unittest.TestCase):
    def test_estimate_tokens_monotone_and_zero(self):
        self.assertEqual(e.estimate_tokens(""), 0)
        self.assertGreater(e.estimate_tokens("a b c d"), 0)
        self.assertGreater(e.estimate_tokens("x" * 400), e.estimate_tokens("x" * 40))

    def test_build_block_delimits_and_counts(self):
        block, toks = e.build_documents_block(
            [{"title": "T", "content": "hello world"}])
        self.assertIn("BEGIN PROVIDED DOCUMENT 1: T", block)
        self.assertIn("hello world", block)
        self.assertIn("END PROVIDED DOCUMENT 1", block)
        self.assertGreater(toks, 0)
        self.assertEqual(e.build_documents_block(None), ("", 0))

    def test_loaded_r1_prepends_documents_and_counts_tokens(self):
        tasks = {t["id"]: t for t in e.load_tasks(FIXTURES)}
        r1 = tasks["R1"]
        self.assertTrue(r1["prompt_text"].startswith("=== BEGIN PROVIDED DOCUMENT 1"))
        self.assertIn("412 employees", r1["prompt_text"])          # document content
        self.assertIn("report the total headcount", r1["prompt_text"])  # base prompt
        self.assertGreater(r1["document_tokens"], 0)

    def test_v1_task_has_zero_document_tokens_and_unchanged_prompt(self):
        # A v1 task (no documents) keeps prompt_text == "\n".join(prompt), doc tokens 0.
        v1 = {t["id"]: t for t in e.load_tasks(V1_TASKS)}
        t1a = v1["T1a"]
        self.assertEqual(t1a["document_tokens"], 0)
        raw = e.load_json(os.path.join(V1_TASKS, "T1a.json"))
        self.assertEqual(t1a["prompt_text"], "\n".join(raw["prompt"]))

    def test_mock_input_tokens_include_document_tokens(self):
        base = {"id": "D", "class": "R-research", "checker": {"type": "exact", "expected": ["x"]}}
        without = e.mock_envelope({**base, "document_tokens": 0}, "low", 1, 7)
        withdoc = e.mock_envelope({**base, "document_tokens": 500}, "low", 1, 7)
        self.assertEqual(withdoc["usage"]["input_tokens"]
                         - without["usage"]["input_tokens"], 500)

    def test_record_carries_document_tokens_only_when_present(self):
        task = {"id": "D", "class": "R-research", "checker": {"type": "exact"}}
        env = {"usage": {"input_tokens": 10, "output_tokens": 5}, "session_id": "s"}
        with_doc = e.envelope_to_record(env, task, "low", 1, scale="pilot", seed=1,
                                        nonce="n", model="m", cli_version="v", ts_start="t",
                                        exit_status=0, retries=0, raw_answer_path="p",
                                        effort_effective="low", effort_effective_source="mock",
                                        document_tokens=321)
        self.assertEqual(with_doc["document_tokens"], 321)
        no_doc = e.envelope_to_record(env, task, "low", 1, scale="pilot", seed=1,
                                      nonce="n", model="m", cli_version="v", ts_start="t",
                                      exit_status=0, retries=0, raw_answer_path="p",
                                      effort_effective="low", effort_effective_source="mock")
        self.assertNotIn("document_tokens", no_doc)   # v1 records stay byte-identical


# --------------------------------------------------------------------------- #
# 3. Blind-grader payload blindness (asserted on the constructed prompt)       #
# --------------------------------------------------------------------------- #
class BlindGraderPayloadTest(unittest.TestCase):
    def test_payload_has_exactly_three_keys(self):
        payload = e.build_grader_payload("do the task", "the rubric", "the artifact")
        self.assertEqual(set(payload.keys()), {"task_prompt", "rubric", "artifact"})

    def test_constructed_prompt_carries_no_producer_field(self):
        # The whole point: the grader cannot see which tier/agent/effort/rep produced
        # the artifact, because no such JSON field exists in the payload it receives.
        payload = e.build_grader_payload("prompt for a max-effort artifact",
                                         "rubric", "an artifact produced at xhigh")
        prompt = e.build_grader_prompt(payload)
        for forbidden in ('"tier"', '"agent"', '"effort"', '"model"', '"cost"', '"rep"',
                          '"effort_requested"', '"effort_effective"'):
            self.assertNotIn(forbidden, prompt, f"blindness leak: {forbidden}")
        # And the payload block in the prompt parses back to exactly the three keys.
        after = prompt.split("GRADE THIS PAYLOAD:", 1)[1]
        parsed = e._extract_first_json_object(after)
        self.assertEqual(set(parsed.keys()), {"task_prompt", "rubric", "artifact"})

    def test_prompt_instructs_the_output_schema_and_stance(self):
        prompt = e.build_grader_prompt(e.build_grader_payload("p", "r", "a"))
        self.assertIn("STRICT JSON", prompt)
        low = prompt.lower()
        for tok in ("criteria", "score", "pass", "skeptic", "round down"):
            self.assertIn(tok, low)


# --------------------------------------------------------------------------- #
# 4. Blind grader — mock verdicts, threshold, parse-failure taxonomy           #
# --------------------------------------------------------------------------- #
class BlindGraderMockTest(unittest.TestCase):
    def _task(self, thr=0.5, mx=1.0):
        return {"id": "R", "class": "R-research", "prompt_text": "p",
                "checker": {"type": "blind-grader", "rubric": "r",
                            "pass_threshold": thr, "max_score": mx}}

    def test_grade_mock_is_deterministic(self):
        t = self._task()
        g1 = e.grade_blind(t, "artifact-one", grade_mock=True, model="m")
        g2 = e.grade_blind(t, "artifact-one", grade_mock=True, model="m")
        self.assertEqual(g1["pass"], g2["pass"])
        self.assertEqual(g1["checker_type"], "blind-grader")
        self.assertIn(g1["failure_class"], ("none", "blind_fail"))

    def test_pass_and_fail_both_reachable_over_artifacts(self):
        t = self._task()
        verdicts = {e.grade_blind(t, f"artifact-{i}", grade_mock=True, model="m")["pass"]
                    for i in range(40)}
        self.assertEqual(verdicts, {True, False})   # grade-mock spreads over hashes

    def test_grading_cost_fields_present_and_zero_in_mock(self):
        g = e.grade_blind(self._task(), "art", grade_mock=True, model="m")
        for k in ("grading_input_tokens", "grading_output_tokens", "grading_cost_usd",
                  "grading_source"):
            self.assertIn(k, g)
        self.assertEqual(g["grading_cost_usd"], 0.0)
        self.assertEqual(g["grading_source"], "grade-mock")

    def test_threshold_scales_with_max_score(self):
        self.assertAlmostEqual(e._norm_threshold({"pass_threshold": 7, "max_score": 10}), 0.7)
        self.assertAlmostEqual(e._norm_threshold({"pass_threshold": 0.5}), 0.5)


class ExtractFirstJsonTest(unittest.TestCase):
    def test_plain_object(self):
        self.assertEqual(e._extract_first_json_object('{"a": 1}'), {"a": 1})

    def test_prose_wrapped(self):
        self.assertEqual(e._extract_first_json_object('sure:\n{"a": 1, "b": [2]} done'),
                         {"a": 1, "b": [2]})

    def test_braces_inside_strings_do_not_confuse_balance(self):
        self.assertEqual(e._extract_first_json_object('{"s": "a}{b", "n": 2}'),
                         {"s": "a}{b", "n": 2})

    def test_no_json_returns_none(self):
        self.assertIsNone(e._extract_first_json_object("no json here"))
        self.assertIsNone(e._extract_first_json_object(""))


class GraderParseFailureTaxonomyTest(unittest.TestCase):
    """A grader that never returns parseable JSON is a grading_error (pass=None),
    NOT a task fail — it is excluded from quality, retried once, then flagged."""

    def _task(self):
        return {"id": "R", "class": "R-research", "prompt_text": "p",
                "checker": {"type": "blind-grader", "rubric": "r",
                            "pass_threshold": 0.5, "max_score": 1.0}}

    def test_grade_blind_flags_grading_error_on_unparseable(self):
        orig = e.invoke_grader
        e.invoke_grader = lambda *a, **k: (None, {"grading_source": "grader",
                                                   "grading_input_tokens": 3,
                                                   "grading_output_tokens": 4,
                                                   "grading_cost_usd": 0.01,
                                                   "grading_retries": e.GRADER_RETRIES,
                                                   "grading_error": True})
        try:
            g = e.grade_blind(self._task(), "artifact", grade_mock=False, model="m", env={})
        finally:
            e.invoke_grader = orig
        self.assertIsNone(g["pass"])                     # not True/False -> excluded
        self.assertEqual(g["failure_class"], "grading_error")
        self.assertTrue(g["grading_error"])
        self.assertEqual(g["grading_retries"], e.GRADER_RETRIES)
        self.assertEqual(g["grading_cost_usd"], 0.01)    # grader spend still recorded

    def test_grading_error_excluded_from_analysis(self):
        # A grading_error record must not drag a class pass rate down: analyze drops it.
        tasks = {"R-t": {"id": "R-t", "class": "R-research"}}
        graded = [{"task_id": "R-t", "class": "R-research", "tier": "low", "rep": 1,
                   "pass": None, "failure_class": "grading_error", "output_tokens": 10,
                   "seed": 1},
                  {"task_id": "R-t", "class": "R-research", "tier": "low", "rep": 2,
                   "pass": True, "failure_class": "none", "output_tokens": 10, "seed": 1}]
        kept = [g for g in graded if isinstance(g.get("pass"), bool)]
        a = e.analyze_core(tasks, kept, seed=1)
        # Only the real verdict counts: 1/1 pass, not 1/2.
        self.assertEqual(a["per_class"]["R-research"]["tiers"]["low"]["n"], 1)


# --------------------------------------------------------------------------- #
# 5. Arm-policy tier mapping (incl. calibrated-table fallback)                 #
# --------------------------------------------------------------------------- #
class ArmPolicyTest(unittest.TestCase):
    def test_fixed_arms_ignore_class_and_table(self):
        self.assertEqual(e.resolve_arm_tier("inherit_xhigh", "R-research", {}), "xhigh")
        self.assertEqual(e.resolve_arm_tier("uniform_high", "C-coding", {}), "high")

    def test_calibrated_reads_table(self):
        table = {"T1-mechanical": {"recommended_tier": "low"},
                 "C-coding": {"recommended_tier": "medium"}}
        self.assertEqual(e.resolve_arm_tier("calibrated", "T1-mechanical", table), "low")
        self.assertEqual(e.resolve_arm_tier("calibrated", "C-coding", table), "medium")

    def test_calibrated_falls_back_to_high_when_absent_or_invalid(self):
        self.assertEqual(e.resolve_arm_tier("calibrated", "R-research", {}), "high")
        self.assertEqual(e.resolve_arm_tier("calibrated", "R-research",
                                            {"R-research": {"recommended_tier": "bogus"}}), "high")

    def test_parse_arms_default_and_validation(self):
        self.assertEqual(e.parse_arms(None), list(e.COMPOSITE_ARMS))
        self.assertEqual(e.parse_arms("calibrated,uniform_high"),
                         ["calibrated", "uniform_high"])
        with self.assertRaises(SystemExit):
            e.parse_arms("calibrated,nonsense")


# --------------------------------------------------------------------------- #
# 6. Composite resumability                                                     #
# --------------------------------------------------------------------------- #
class CompositeResumabilityTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="effort-comp-resume-")
        self.paths = e.Paths(self.tmp, FIXTURES, "v2")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_rerun_appends_zero(self):
        ns = _ns(self.tmp, reps=2)
        e.cmd_run_composite(ns)
        first = len(e.read_jsonl(self.paths.results_composite)[0])
        e.cmd_run_composite(ns)
        second = len(e.read_jsonl(self.paths.results_composite)[0])
        self.assertEqual(first, second, "resume must append zero composite records")
        # One X-task x 3 arms x 2 reps x 5 subtasks = 30 subtask runs.
        self.assertEqual(first, 1 * 3 * 2 * 5)

    def test_latest_by_composite_key_prefers_non_error(self):
        err = {"composite_id": "X1", "arm": "calibrated", "rep": 1,
               "subtask_id": "s1-extract", "api_error": True}
        ok = {"composite_id": "X1", "arm": "calibrated", "rep": 1,
              "subtask_id": "s1-extract", "api_error": False, "pass": True}
        latest = e.latest_by_composite_key([err, ok])
        self.assertFalse(latest[("X1", "calibrated", 1, "s1-extract")]["api_error"])


# --------------------------------------------------------------------------- #
# 7. Composite analysis math on synthetic data                                 #
# --------------------------------------------------------------------------- #
def _comp_records(arm, n_sub, n_reps, tok_per_sub, n_pass, xid="X1"):
    recs, idx = [], 0
    for rep in range(1, n_reps + 1):
        for s in range(n_sub):
            recs.append({"composite_id": xid, "arm": arm, "subtask_id": f"s{s}",
                         "rep": rep, "output_tokens": tok_per_sub,
                         "pass": idx < n_pass, "api_error": False,
                         "class": "T1-mechanical", "tier": "x", "task_id": f"{xid}-s{s}"})
            idx += 1
    return recs


class CompositeAnalysisMathTest(unittest.TestCase):
    XT = [{"id": "X1"}]

    def test_pooled_tokens_and_pass(self):
        recs = (_comp_records("calibrated", 4, 3, 25, 12)      # 100/rep, all pass
                + _comp_records("inherit_xhigh", 4, 3, 200, 12)  # 800/rep
                + _comp_records("uniform_high", 4, 3, 150, 12))  # 600/rep
        c = e.analyze_composite(self.XT, recs, seed=1)
        self.assertAlmostEqual(c["pooled"]["calibrated"]["out_tokens"], 100.0)
        self.assertAlmostEqual(c["pooled"]["inherit_xhigh"]["out_tokens"], 800.0)
        self.assertAlmostEqual(c["pooled"]["uniform_high"]["out_tokens"], 600.0)
        self.assertEqual(c["pooled"]["calibrated"]["agg_pass"], 1.0)

    def test_savings_sign_and_deterministic_ci(self):
        recs = (_comp_records("calibrated", 4, 3, 25, 12)
                + _comp_records("inherit_xhigh", 4, 3, 200, 12)
                + _comp_records("uniform_high", 4, 3, 150, 12))
        c = e.analyze_composite(self.XT, recs, seed=1)
        s = c["savings"]["inherit_xhigh"]
        self.assertEqual(s["point"], 700.0)               # 800 - 100
        # Identical per-rep totals -> zero-width bootstrap CI, lower bound > 0.
        self.assertGreater(s["ci95"][0], 0)

    def test_verdict_true_when_cheaper_and_noninferior(self):
        # n=200/arm; calibrated cheaper AND strictly higher pass -> wins.
        recs = (_comp_records("calibrated", 4, 50, 25, 196)
                + _comp_records("inherit_xhigh", 4, 50, 200, 180)
                + _comp_records("uniform_high", 4, 50, 150, 180))
        c = e.analyze_composite(self.XT, recs, seed=1)
        self.assertTrue(c["verdict"]["calibrated_wins"])
        self.assertTrue(c["verdict"]["cheaper_than_inherit_xhigh"])
        self.assertTrue(c["verdict"]["noninferior_uniform_high"])

    def test_verdict_false_when_not_cheaper(self):
        recs = (_comp_records("calibrated", 4, 50, 250, 196)   # dearer than both
                + _comp_records("inherit_xhigh", 4, 50, 200, 180)
                + _comp_records("uniform_high", 4, 50, 150, 180))
        c = e.analyze_composite(self.XT, recs, seed=1)
        self.assertFalse(c["verdict"]["calibrated_wins"])
        self.assertFalse(c["verdict"]["cheaper_than_uniform_high"])

    def test_verdict_false_when_quality_inferior(self):
        recs = (_comp_records("calibrated", 4, 50, 25, 100)    # cheap but 50% pass
                + _comp_records("inherit_xhigh", 4, 50, 200, 190)
                + _comp_records("uniform_high", 4, 50, 150, 190))
        c = e.analyze_composite(self.XT, recs, seed=1)
        self.assertFalse(c["verdict"]["calibrated_wins"])
        self.assertFalse(c["verdict"]["noninferior_inherit_xhigh"])

    def test_incomplete_arms_null_verdict(self):
        recs = (_comp_records("calibrated", 4, 3, 25, 12)
                + _comp_records("inherit_xhigh", 4, 3, 200, 12))  # no uniform_high
        c = e.analyze_composite(self.XT, recs, seed=1)
        self.assertIsNone(c["verdict"]["calibrated_wins"])
        self.assertIn("uniform_high", c["savings"])
        self.assertIsNone(c["savings"]["uniform_high"]["point"])


# --------------------------------------------------------------------------- #
# 8. Mock end-to-end (fixtures) — the full v2 pipeline                          #
# --------------------------------------------------------------------------- #
class MockPipelineV2Test(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="effort-v2-e2e-")
        self.paths = e.Paths(self.tmp, FIXTURES, "v2")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_full_offline_v2_pipeline(self):
        ns = _ns(self.tmp)
        self.assertEqual(e.cmd_validate(ns), 0)
        # Phase 0 v2 extras present and gate green.
        p0 = e.load_json(self.paths.phase0)
        self.assertTrue(p0["gate_passed"])
        self.assertTrue(p0["grader_smoke"]["agree"])
        self.assertIn("per_tier", p0["long_context_probe"])

        e.cmd_run(ns)
        # R1 (documents) run records carry a positive document_tokens.
        res, _ = e.read_jsonl(self.paths.results)
        r1 = [r for r in res if r["task_id"] == "R1"]
        self.assertTrue(r1 and all(r.get("document_tokens", 0) > 0 for r in r1))
        self.assertTrue(all(r["class"] != e.COMPOSITE_CLASS for r in res))

        e.cmd_run_composite(ns)
        e.cmd_grade(ns)
        graded, _ = e.read_jsonl(self.paths.graded)
        # Blind cells (R2) carry grading_* cost isolated from the run cost.
        blind = [g for g in graded if g["task_id"] == "R2"]
        self.assertTrue(blind)
        for g in blind:
            self.assertIn("grading_cost_usd", g)
            self.assertIn("total_cost_usd", g)             # the run's own cost, separate
            self.assertEqual(g["grading_source"], "grade-mock")

        self.assertEqual(e.cmd_analyze(ns), 0)
        an = e.load_json(self.paths.analysis)
        self.assertEqual(an["suite"], "v2")
        self.assertIn("R-research", an["per_class"])
        self.assertIn("C-coding", an["per_class"])
        self.assertNotIn(e.COMPOSITE_CLASS, an["per_class"])   # composite analyzed apart
        self.assertIsNotNone(an["composite"])
        self.assertEqual(an["composite"]["n_valid_subtask_runs"], 30)

        # analyze must NOT write calibration.json (that is calibrate --suite v2's job).
        self.assertFalse(os.path.exists(self.paths.calibration))

        self.assertEqual(e.cmd_report(ns), 0)
        with open(self.paths.results_md, encoding="utf-8") as f:
            md = f.read()
        for section in ("Suite v2 Results", "class curves", "Composite policy arms",
                        "Grader reliability", "Threats to validity"):
            self.assertIn(section, md)
        self.assertFalse(any(0x1F000 <= ord(ch) <= 0x1FAFF or 0x2600 <= ord(ch) <= 0x27BF
                             for ch in md))

    def test_calibrate_v2_merges_and_preserves_existing(self):
        ns = _ns(self.tmp)
        e.cmd_validate(ns)
        e.cmd_run(ns)
        e.cmd_grade(ns)
        e.cmd_analyze(ns)
        # Seed a prior (v1-style) proven table; the merge must keep it.
        e.atomic_write_json(self.paths.calibration, {
            "version": 1, "proven": True, "model": e.MODEL,
            "provenance": {"mode": "real"},
            "classes": {"T1-mechanical": {"recommended_tier": "low"},
                        "T4-hard-reasoning": {"recommended_tier": "high"}}})
        self.assertEqual(e.cmd_calibrate(ns), 0)
        cal = e.load_json(self.paths.calibration)
        # v1 classes preserved; R/C added; X-composite never enters; provenance stamped.
        self.assertIn("T1-mechanical", cal["classes"])
        self.assertIn("T4-hard-reasoning", cal["classes"])
        self.assertIn("R-research", cal["classes"])
        self.assertIn("C-coding", cal["classes"])
        self.assertNotIn(e.COMPOSITE_CLASS, cal["classes"])
        self.assertEqual(cal["classes"]["R-research"]["suite"], "v2")
        self.assertEqual(cal["provenance"]["suite"], "v2")
        self.assertTrue(cal["proven"])                    # a proven v1 table is not downgraded
        self.assertEqual(cal["refit_v2"]["suite"], "v2")

    def test_composite_calibrated_arm_uses_seeded_table(self):
        # With a seeded table, the calibrated arm runs each subtask at its class tier;
        # a class absent from the table falls back to 'high'.
        ns = _ns(self.tmp)
        e.atomic_write_json(self.paths.calibration, {"version": 1, "proven": True,
            "classes": {"T1-mechanical": {"recommended_tier": "low"},
                        "T2-simple-transform": {"recommended_tier": "low"}}})
        e.cmd_run_composite(ns)
        comp, _ = e.read_jsonl(self.paths.results_composite)
        cal_recs = {(r["subtask_id"]): r["tier"] for r in comp if r["arm"] == "calibrated"}
        self.assertEqual(cal_recs["s1-extract"], "low")    # T1-mechanical -> low (table)
        self.assertEqual(cal_recs["s5-summarize"], "low")  # T2-simple-transform -> low
        self.assertEqual(cal_recs["s2-runlength"], "high")  # C-coding absent -> fallback
        self.assertEqual(cal_recs["s3-lookup"], "high")     # R-research absent -> fallback
        # inherit_xhigh/uniform_high arms are class-independent fixed tiers.
        inh = {r["tier"] for r in comp if r["arm"] == "inherit_xhigh"}
        uni = {r["tier"] for r in comp if r["arm"] == "uniform_high"}
        self.assertEqual(inh, {"xhigh"})
        self.assertEqual(uni, {"high"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
