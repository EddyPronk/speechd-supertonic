"""Tests for the Claude Code hook example (examples/claude-code/speak.py)."""

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "examples" / "claude-code" / "speak.py"
spec = importlib.util.spec_from_file_location("speak", SCRIPT)
speak = importlib.util.module_from_spec(spec)
spec.loader.exec_module(speak)


class TestToSpeech(unittest.TestCase):
    def test_markdown_becomes_plain_speech(self):
        md = ("## Done\n\nI committed **two** files (`a.py`, [docs](https://x.y)).\n\n"
              "```\ncode here\n```\n\n| a | b |\n|---|---|\n\n- First point\n- Second point\n"
              "1. Third, numbered")
        self.assertEqual(speak.to_speech(md),
                         "Done. I committed two files (a.py, docs). First point. Second point. "
                         "Third, numbered.")

    def test_bare_urls(self):
        self.assertEqual(speak.to_speech("See https://example.com/x for more."),
                         "See a link for more.")

    def test_long_reply_cut_at_sentence(self):
        text = "This is a sentence. " * 200
        out = speak.to_speech(text, max_chars=300)
        self.assertLessEqual(len(out), 300 + len(" The rest is on screen."))
        self.assertTrue(out.endswith("sentence. The rest is on screen."))

    def test_short_reply_untouched(self):
        self.assertEqual(speak.to_speech("Hello there."), "Hello there.")


class TestBuildCommand(unittest.TestCase):
    def cmd(self, data, **env):
        return speak.build_command(data, env=env)

    def test_reply_uses_text_priority(self):
        cmd = self.cmd({"hook_event_name": "Stop", "last_assistant_message": "All **done**."})
        self.assertEqual(cmd, ["spd-say", "-o", "supertonic", "-y", "F1-en", "-P", "text", "--", "All done."])

    def test_idle_notification_uses_notification_priority(self):
        for data in ({"message": "Claude is waiting for your input"},
                     {"message": "Anything", "notification_type": "idle_prompt"}):
            cmd = self.cmd({"hook_event_name": "Notification", **data})
            self.assertEqual(cmd[cmd.index("-P") + 1], "notification", data)

    def test_other_notifications_use_message_priority(self):
        cmd = self.cmd({"hook_event_name": "Notification",
                        "message": "Claude needs your permission to use Bash"})
        self.assertEqual(cmd[cmd.index("-P") + 1], "message")
        self.assertEqual(cmd[-1], "Claude needs your permission to use Bash")

    def test_voice_and_disable(self):
        data = {"hook_event_name": "Stop", "last_assistant_message": "Hi."}
        self.assertEqual(self.cmd(data, SPEAK_VOICE="M2-en")[4], "M2-en")
        self.assertIsNone(self.cmd(data, SPEAK_DISABLE="1"))

    def test_nothing_to_say(self):
        self.assertIsNone(self.cmd({"hook_event_name": "Stop", "last_assistant_message": "```\nx\n```"}))
        self.assertIsNone(self.cmd({"hook_event_name": "Notification", "message": ""}))
        self.assertIsNone(self.cmd({}))

    def test_reply_from_transcript(self):
        lines = [
            {"type": "user", "message": {"content": "question"}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "First reply."}]}},
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash"}]}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "Final reply."}]}},
            "not an object",
        ]
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
            for line in lines:
                f.write(json.dumps(line) + "\n")
            f.write("{broken json\n")
        try:
            cmd = self.cmd({"hook_event_name": "Stop", "transcript_path": f.name})
        finally:
            Path(f.name).unlink()
        self.assertEqual(cmd[-1], "Final reply.")

    def test_missing_transcript(self):
        self.assertIsNone(self.cmd({"hook_event_name": "Stop", "transcript_path": "/nonexistent.jsonl"}))


class TestScript(unittest.TestCase):
    def run_script(self, stdin, **env):
        return subprocess.run([sys.executable, str(SCRIPT)], input=stdin, capture_output=True,
                              text=True, env={"PATH": "/usr/bin:/bin", **env}, timeout=30)

    def test_dry_run_prints_command(self):
        r = self.run_script('{"hook_event_name":"Notification","message":"Test"}', SPEAK_DRY_RUN="1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)[-1], "Test")

    def test_bad_input_is_ignored(self):
        for stdin in ("not json", "[1, 2]", ""):
            r = self.run_script(stdin, SPEAK_DRY_RUN="1")
            self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""), stdin)


if __name__ == "__main__":
    unittest.main()
