"""Tests for speechd_timing.py against representative log fixtures."""

import io
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(ROOT))
import speechd_timing as timing  # noqa: E402


def parse(name):
    lines = (FIXTURES / name).read_text(encoding="utf-8", errors="replace").splitlines()
    return timing.parse(lines)


class TestParse(unittest.TestCase):
    def test_non_debug_log(self):
        r1, r2 = parse("nodebug.log")
        self.assertEqual((r1["id"], r1["chars"], r1["chunks"]), (1, 64, 1))
        self.assertEqual(r1["text"], "(64 chars, text not logged)")
        self.assertIsNone(timing.gap(r1))  # nothing played before it
        self.assertAlmostEqual(timing.gap(r2), 2.06, places=2)  # 23,980 -> 26,040
        self.assertEqual(r2["ahead"], [6.45])
        self.assertEqual(r2["trims"], [(0.50, 0.70), (0.40, 0.60)])
        self.assertAlmostEqual(r2["finish"].timestamp() - r2["est_end"], 0.009, places=3)

    def test_debug_stopped_late_incomplete(self):
        r1, r2, r3 = parse("debug_stopped_late.log")
        self.assertEqual(r1["text"], "Hello there. A second sentence.")
        self.assertEqual(r1["chars"], len("Hello there. A second sentence."))
        self.assertEqual(r1["late"], [0.25])
        self.assertTrue(r2["stopped"])
        self.assertIsNone(r2["finish"])
        self.assertIsNone(r2["est_end"])
        # Started but never synthesized: no crash, just empty fields.
        self.assertEqual((r3["chunks"], r3["synth1"], r3["first"]), (0, None, None))

    def test_old_format_without_trimming_or_model_line(self):
        (r,) = parse("old_format.log")
        self.assertEqual((r["id"], r["chunks"], r["trims"]), (2, 1, []))
        self.assertAlmostEqual(r["synth1"], 1.40)

    def test_empty_and_garbage(self):
        self.assertEqual(parse("empty.log"), [])
        self.assertEqual(parse("garbage.log"), [])

    def test_only_latest_server_run(self):
        lines = (FIXTURES / "nodebug.log").read_text().splitlines()
        lines += (FIXTURES / "debug_stopped_late.log").read_text().splitlines()
        self.assertEqual(len(timing.parse(lines)), 3)  # the second file's run

    def test_finish_from_much_later_is_not_attached(self):
        lines = (FIXTURES / "nodebug.log").read_text().splitlines()[:-1]  # [2] never finished
        lines.append("2026-10-06 23:59:00,000 [player] INFO playback finished")
        r2 = timing.parse(lines)[-1]
        self.assertIsNone(r2["finish"])


class TestReport(unittest.TestCase):
    def report(self, name):
        out = io.StringIO()
        timing.report(parse(name), out)
        return out.getvalue()

    def test_report_columns_and_summary(self):
        text = self.report("nodebug.log")
        self.assertIn("est. gap", text)
        self.assertIn("end vs est", text)
        self.assertIn("2.06s", text)
        self.assertIn("LATE chunks: 0", text)
        self.assertIn("(64 chars, text not logged)", text)

    def test_report_flags(self):
        text = self.report("debug_stopped_late.log")
        self.assertIn("LATE [0.25]", text)
        self.assertIn("STOPPED", text)
        self.assertIn("LATE chunks: 1", text)

    def test_report_empty(self):
        self.assertIn("No utterances", self.report("empty.log"))

    def test_command_line(self):
        script = str(ROOT / "speechd_timing.py")
        ok = subprocess.run([sys.executable, script, str(FIXTURES / "garbage.log")],
                            capture_output=True, text=True, timeout=30)
        self.assertEqual(ok.returncode, 0, ok.stderr)
        missing = subprocess.run([sys.executable, script, str(FIXTURES / "nope.log")],
                                 capture_output=True, text=True, timeout=30)
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("No such file", missing.stderr)
        self.assertNotIn("Traceback", missing.stderr)


if __name__ == "__main__":
    unittest.main()
