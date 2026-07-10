#!/usr/bin/env python3
"""Unit tests for hooks/log-dispatch.sh — the PostToolUse dispatch telemetry hook.

Why this file exists: the hook is deterministic core, but neither oracle used to
execute it. `python3 -m unittest` imported bench/effort.py and `effort.py selftest`
ran the mock pipeline; nothing ever fed a payload to the shell script. So a field
spelling could rot silently. It did, twice — 0.5.2 fixed `agent_type: null` against
a payload shape nobody replayed, and shipped a fallback scan that still missed the
namespaced `subagent_type` a marketplace install actually sends (issue #1).

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
        proc = subprocess.run(["bash", HOOK], input=raw, env=env,
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
        """A --plugin-dir dev load sends the bare name."""
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

    def test_fallback_scan_finds_namespaced_miner(self):
        """When subagent_type is absent entirely, scan values for a tier worker.

        0.5.2 added this scan with a bare startswith('miner-'), which a namespaced
        value fails for the same reason the slug regex did.
        """
        rc, recs = self.fire({"tool_name": "Agent",
                              "tool_input": {"description": "d",
                                             "worker": "effortmining:miner-xhigh"}})
        self.assertEqual(recs[0]["agent_type"], "effortmining:miner-xhigh")

    def test_no_agent_type_anywhere_is_null_not_crash(self):
        rc, recs = self.fire({"tool_name": "Agent",
                              "tool_input": {"prompt": "just a prompt"}})
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


if __name__ == "__main__":
    unittest.main()
