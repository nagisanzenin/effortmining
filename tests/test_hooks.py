#!/usr/bin/env python3
"""Unit tests for hooks/log-dispatch.sh — the PostToolUse dispatch telemetry hook.

Why this file exists: the hook is deterministic core, but neither oracle used to
execute it. `python3 -m unittest` imported bench/effort.py and `effort.py selftest`
ran the mock pipeline; nothing ever fed a payload to the shell script. So an
assumption about the payload could never be checked against a payload. It wasn't,
for three releases: 0.5.1 logged `agent_type: null` because slug() rejected the
colon in `effortmining:miner-low`, 0.5.2 read that null as "the field is absent"
and added a value-scan to compensate, and the field had been there all along
(issue #1). Every plugin-loaded agent is namespaced, under `--plugin-dir` and
`plugin install` alike; the bare form has never been seen on the wire.

The contract under test has two halves, and the last test here checks the seam:
the hook WRITES agent_type, and normalize_dispatch_record() in bench/effort.py
READS it. A change to either that does not survive the round trip is the bug.

Every test pins CLAUDE_PLUGIN_ROOT to a temp dir. The hook self-locates its root
from BASH_SOURCE when that env var is unset, so a test that forgot would append to
the real bench/state/dispatch-log.jsonl.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(REPO, "hooks", "log-dispatch.sh")
# Absolute: one test empties PATH to simulate a machine without python3, and a
# bare "bash" would then fail to resolve for the test runner itself.
BASH = shutil.which("bash") or "/bin/bash"
sys.path.insert(0, os.path.join(REPO, "bench"))
from effort import normalize_dispatch_record  # noqa: E402


class HookHarness(unittest.TestCase):
    """Replays payloads through the real hook in a throwaway plugin root."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="effort-hooktest-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def fire(self, payload, effort_env=""):
        """Run the hook on one payload. Returns (returncode, [records])."""
        env = dict(os.environ)
        env["CLAUDE_PLUGIN_ROOT"] = self.root
        env["CLAUDE_EFFORT"] = effort_env  # never inherit the caller's session effort
        raw = payload if isinstance(payload, str) else json.dumps(payload)
        proc = subprocess.run([BASH, HOOK], input=raw, env=env,
                              capture_output=True, text=True, timeout=20)
        log = os.path.join(self.root, "bench", "state", "dispatch-log.jsonl")
        recs = []
        if os.path.exists(log):
            with open(log, encoding="utf-8") as fh:
                recs = [json.loads(ln) for ln in fh if ln.strip()]
        return proc.returncode, recs

    def agent_type_of(self, subagent_type):
        rc, recs = self.fire({"tool_name": "Agent", "session_id": "s",
                              "tool_input": {"subagent_type": subagent_type}})
        self.assertEqual(rc, 0)
        self.assertEqual(len(recs), 1)
        return recs[0]["agent_type"]


class TestAgentTypeExtraction(HookHarness):
    def test_namespaced_subagent_type_is_logged(self):
        """A marketplace install sends '<plugin>:<agent>'. Regression: issue #1."""
        self.assertEqual(self.agent_type_of("effortmining:miner-medium"),
                         "effortmining:miner-medium")

    def test_bare_subagent_type_still_logged(self):
        """Defensive: no live payload has ever carried a bare worker name."""
        self.assertEqual(self.agent_type_of("miner-low"), "miner-low")

    def test_builtin_agent_logged(self):
        self.assertEqual(self.agent_type_of("general-purpose"), "general-purpose")

    def test_foreign_plugin_namespace_preserved(self):
        """The namespace says which plugin owned the dispatch; don't discard it."""
        self.assertEqual(self.agent_type_of("engram:engram-assessor"),
                         "engram:engram-assessor")

    def test_camelcase_field_spelling(self):
        rc, recs = self.fire({"tool_name": "Agent",
                              "tool_input": {"subagentType": "effortmining:miner-high"}})
        self.assertEqual(recs[0]["agent_type"], "effortmining:miner-high")

    def test_free_text_value_is_never_mistaken_for_the_worker(self):
        """0.5.2 scanned tool_input's VALUES for a 'miner-' prefix. 0.5.3 does not.

        A description that merely mentions a worker must not be logged as the
        dispatched worker — that is a fabricated audit trail, worse than a null.
        """
        rc, recs = self.fire({"tool_name": "Agent",
                              "tool_input": {"description": "foo:miner-low",
                                             "prompt": "miner-max"}})
        self.assertEqual(rc, 0)
        self.assertIsNone(recs[0]["agent_type"])

    def test_no_agent_type_anywhere_is_null_not_crash(self):
        rc, recs = self.fire({"tool_name": "Agent",
                              "tool_input": {"prompt": "just a prompt"}})
        self.assertEqual(rc, 0)
        self.assertIsNone(recs[0]["agent_type"])

    def test_non_dict_tool_input_is_null_not_crash(self):
        rc, recs = self.fire({"tool_name": "Agent", "tool_input": ["a", "b"]})
        self.assertEqual(rc, 0)
        self.assertIsNone(recs[0]["agent_type"])


class TestAgentTypeValidation(HookHarness):
    def test_quote_and_newline_injection_rejected(self):
        self.assertIsNone(self.agent_type_of('a"b:c\nd'))

    def test_multiple_colons_rejected(self):
        """One optional '<plugin>:' namespace, not arbitrary colons."""
        self.assertIsNone(self.agent_type_of("plugin:with:extra:colons"))

    def test_overlong_value_rejected(self):
        self.assertIsNone(self.agent_type_of("x" * 65))

    def test_overlong_namespace_rejected(self):
        self.assertIsNone(self.agent_type_of("y" * 65 + ":miner-low"))

    def test_space_rejected(self):
        self.assertIsNone(self.agent_type_of("miner low"))

    def test_written_line_is_always_valid_json(self):
        """json.dumps escapes, but the record must survive a hostile agent name."""
        rc, recs = self.fire({"tool_name": "Agent", "session_id": 'x"\n{}',
                              "tool_input": {"subagent_type": '{"injected": true}'}})
        self.assertEqual(rc, 0)
        self.assertEqual(len(recs), 1)  # parsed back out of the file == valid JSON
        self.assertIsNone(recs[0]["agent_type"])
        self.assertIsNone(recs[0]["session_id"])


class TestEffortAndScope(HookHarness):
    def test_effort_from_payload(self):
        rc, recs = self.fire({"tool_name": "Agent", "effort": {"level": "xhigh"},
                              "tool_input": {"subagent_type": "miner-low"}})
        self.assertEqual(recs[0]["session_effort"], "xhigh")

    def test_effort_falls_back_to_env(self):
        rc, recs = self.fire({"tool_name": "Agent",
                              "tool_input": {"subagent_type": "miner-low"}},
                             effort_env="medium")
        self.assertEqual(recs[0]["session_effort"], "medium")

    def test_invalid_effort_is_null(self):
        rc, recs = self.fire({"tool_name": "Agent", "effort": {"level": "turbo"},
                              "tool_input": {"subagent_type": "miner-low"}})
        self.assertIsNone(recs[0]["session_effort"])

    def test_unhashable_effort_level_does_not_drop_the_record(self):
        """`[] in VALID_EFFORT` raises TypeError; the record must survive it.

        Fail-open at the shell level hid this: python exited non-zero, `|| exit 0`
        swallowed it, and a dispatch with a perfectly good agent_type vanished.
        """
        rc, recs = self.fire({"tool_name": "Agent", "effort": {"level": []},
                              "tool_input": {"subagent_type": "effortmining:miner-low"}})
        self.assertEqual(rc, 0)
        self.assertEqual(len(recs), 1, "record was dropped, not degraded")
        self.assertEqual(recs[0]["agent_type"], "effortmining:miner-low")
        self.assertIsNone(recs[0]["session_effort"])

    def test_unhashable_effort_falls_back_to_env(self):
        rc, recs = self.fire({"tool_name": "Agent", "effort": {"level": {"a": 1}},
                              "tool_input": {"subagent_type": "miner-low"}},
                             effort_env="high")
        self.assertEqual(recs[0]["session_effort"], "high")

    def test_non_dispatch_tool_writes_nothing(self):
        rc, recs = self.fire({"tool_name": "Bash",
                              "tool_input": {"subagent_type": "miner-low"}})
        self.assertEqual(rc, 0)
        self.assertEqual(recs, [])

    def test_task_tool_name_accepted(self):
        rc, recs = self.fire({"tool_name": "Task",
                              "tool_input": {"subagent_type": "miner-max"}})
        self.assertEqual(recs[0]["tool_name"], "Task")


class TestFailOpen(HookHarness):
    """The hook must never block or delay a dispatch. Exit 0, always."""

    def test_malformed_json_exits_zero(self):
        rc, recs = self.fire("not json at all")
        self.assertEqual(rc, 0)
        self.assertEqual(recs, [])

    def test_empty_stdin_exits_zero(self):
        rc, recs = self.fire("")
        self.assertEqual(rc, 0)
        self.assertEqual(recs, [])

    def test_null_tool_input_exits_zero(self):
        rc, recs = self.fire({"tool_name": "Agent", "tool_input": None})
        self.assertEqual(rc, 0)
        self.assertIsNone(recs[0]["agent_type"])

    def test_exits_zero_without_python3(self):
        """`command -v python3 || exit 0`. A python-less machine must still dispatch."""
        env = dict(os.environ)
        env["CLAUDE_PLUGIN_ROOT"] = self.root
        env["PATH"] = os.path.join(self.root, "empty-path")  # no python3 here
        os.makedirs(env["PATH"], exist_ok=True)
        proc = subprocess.run([BASH, HOOK], input="{}", env=env,
                              capture_output=True, text=True, timeout=20)
        self.assertEqual(proc.returncode, 0)

    def test_exits_zero_when_state_dir_cannot_be_created(self):
        """os.makedirs raises on an unwritable root; the hook swallows it."""
        os.chmod(self.root, 0o500)  # r-x: cannot create bench/
        self.addCleanup(os.chmod, self.root, 0o700)
        rc, _ = self.fire({"tool_name": "Agent",
                           "tool_input": {"subagent_type": "miner-low"}})
        self.assertEqual(rc, 0)

    def test_never_writes_to_stdout(self):
        """PostToolUse stdout is interpreted by the harness; the hook must stay mute."""
        env = dict(os.environ)
        env["CLAUDE_PLUGIN_ROOT"] = self.root
        env["CLAUDE_EFFORT"] = ""
        proc = subprocess.run(
            [BASH, HOOK],
            input=json.dumps({"tool_name": "Agent",
                              "tool_input": {"subagent_type": "miner-low"}}),
            env=env, capture_output=True, text=True, timeout=20)
        self.assertEqual(proc.stdout, "")

    def test_appends_rather_than_truncates(self):
        for tier in ("low", "high"):
            self.fire({"tool_name": "Agent",
                       "tool_input": {"subagent_type": f"effortmining:miner-{tier}"}})
        _, recs = self.fire({"tool_name": "Agent",
                             "tool_input": {"subagent_type": "miner-max"}})
        self.assertEqual([r["agent_type"] for r in recs],
                         ["effortmining:miner-low", "effortmining:miner-high",
                          "miner-max"])


class TestHookReaderSeam(HookHarness):
    """The contract: what the hook writes, normalize_dispatch_record() must read.

    Issue #1 lived exactly here — the writer emitted a value the reader could not
    resolve a tier from. Assert the round trip, not each side in isolation.
    """

    KNOWN = {"T1-mechanical", "T3-moderate-reasoning", "C-coding"}

    def tier_from_hook(self, subagent_type):
        _, recs = self.fire({"tool_name": "Agent",
                             "tool_input": {"subagent_type": subagent_type}})
        # The hook appends; a test that fires more than once wants the last line.
        rec = dict(recs[-1], task_class="T1-mechanical")  # class comes from effortmine
        norm = normalize_dispatch_record(rec, self.KNOWN)
        return norm[1] if norm else None

    def test_namespaced_dispatch_round_trips_to_tier(self):
        self.assertEqual(self.tier_from_hook("effortmining:miner-medium"), "medium")

    def test_bare_dispatch_round_trips_to_tier(self):
        self.assertEqual(self.tier_from_hook("miner-xhigh"), "xhigh")

    def test_every_tier_round_trips(self):
        for tier in ("low", "medium", "high", "xhigh", "max"):
            with self.subTest(tier=tier):
                self.assertEqual(self.tier_from_hook(f"effortmining:miner-{tier}"), tier)

    def test_non_miner_agent_resolves_no_tier(self):
        """A general-purpose dispatch carries no tier; it must not fake one."""
        self.assertIsNone(self.tier_from_hook("general-purpose"))

    def test_unknown_tier_name_resolves_no_tier(self):
        self.assertIsNone(self.tier_from_hook("effortmining:miner-turbo"))


class TestReaderTolerance(unittest.TestCase):
    """A corrupt dispatch-log line must be skipped, never abort a refit.

    read_jsonl quarantines only JSONDecodeErrors, so a syntactically valid but
    wrongly-shaped line reaches normalize_dispatch_record() intact.
    """

    KNOWN = {"T1-mechanical", "C-coding"}

    def norm(self, rec):
        return normalize_dispatch_record(rec, self.KNOWN)

    def test_non_dict_record_is_skipped(self):
        for junk in (42, "x", None, ["a"]):
            with self.subTest(junk=junk):
                self.assertIsNone(self.norm(junk))

    def test_non_string_agent_type_is_skipped(self):
        self.assertIsNone(self.norm({"task_class": "T1-mechanical", "agent_type": 5}))

    def test_non_string_tier_is_skipped(self):
        self.assertIsNone(self.norm({"task_class": "T1-mechanical", "tier": []}))

    def test_non_string_task_class_is_skipped(self):
        self.assertIsNone(self.norm({"task_class": {"a": 1}, "tier": "low"}))

    def test_legacy_null_agent_type_is_skipped_not_crashed(self):
        """0.5.1 and 0.5.2 wrote agent_type: null for every real dispatch."""
        self.assertIsNone(self.norm({"source": "posttooluse-hook",
                                     "agent_type": None, "session_id": "x"}))

    def test_load_dispatch_log_survives_a_corrupt_line(self):
        """The end-to-end path the review flagged: `calibrate` must not traceback."""
        from effort import load_dispatch_log
        tmp = tempfile.mkdtemp(prefix="effort-log-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        path = os.path.join(tmp, "dispatch-log.jsonl")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write('42\n')                                              # valid JSON, not an object
            fh.write('{"agent_type": 5}\n')                               # wrong type
            fh.write('{"source":"posttooluse-hook","agent_type":null}\n')  # 0.5.1 legacy
            fh.write('not json at all\n')                                 # quarantined by read_jsonl
            fh.write('{"source":"effortmine","task_class":"C-coding",'
                     '"tier":"medium","accepted":true}\n')                 # the one good record
        graded, consumed, skipped = load_dispatch_log(path, self.KNOWN)
        self.assertEqual(consumed, 1)
        self.assertEqual(skipped, 3)
        self.assertEqual(graded[("C-coding", "medium")], {"k": 1, "n": 1})


if __name__ == "__main__":
    unittest.main()
