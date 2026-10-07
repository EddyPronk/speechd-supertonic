"""Tests for supertonic_say.py, run as a subprocess against the fake server."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from fakes import FakeEngine, expected_samples, running_server

CLIENT = str(Path(__file__).resolve().parent.parent / "supertonic_say.py")


def say(text, runtime_dir, *args, env_extra=None):
    env = dict(os.environ, XDG_RUNTIME_DIR=runtime_dir)
    env.pop("SUPERTONIC_PLAYER", None)
    if env_extra:
        env.update(env_extra)
    return subprocess.run([sys.executable, CLIENT, "--voice", "F1-en", *args], input=text.encode(),
                          capture_output=True, env=env, timeout=30)


class TestClient(unittest.TestCase):
    def test_output_raw_audio(self):
        text = "Hello there. Second sentence."
        with running_server() as (_, _, rt):
            r = say(text, rt, "--output", "-")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(r.stdout) // 4, expected_samples(text))

    def test_plays_through_player_and_logs_finish(self):
        with running_server() as (_, _, rt), tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "played.raw"
            r = say("Played.", rt, "--player", f"sh -c 'cat > {out}'")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(out.stat().st_size // 4, expected_samples("Played."))
        self.assertIn(b"[player] INFO playback finished", r.stderr)

    def test_player_from_environment(self):
        with running_server() as (_, _, rt), tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "played.raw"
            r = say("Played.", rt, env_extra={"SUPERTONIC_PLAYER": f"sh -c 'cat > {out}'"})
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertGreater(out.stat().st_size, 0)

    def test_no_server_fails(self):
        with tempfile.TemporaryDirectory() as rt:
            r = say("Nobody listens.", rt, "--player", "cat")
        self.assertEqual(r.returncode, 1)
        self.assertIn(b"can't reach server", r.stderr)
        self.assertNotIn(b"playback finished", r.stderr)

    def test_player_failure_fails(self):
        with running_server() as (_, _, rt):
            r = say("Player breaks.", rt, "--player", "sh -c 'cat > /dev/null; exit 3'")
        self.assertEqual(r.returncode, 1)
        self.assertIn(b"failed with exit status 3", r.stderr)
        self.assertNotIn(b"playback finished", r.stderr)

    def test_missing_player_fails(self):
        with running_server() as (_, _, rt):
            r = say("No player.", rt, "--player", "/nonexistent/player")
        self.assertEqual(r.returncode, 1)
        self.assertIn(b"can't start player", r.stderr)

    def test_server_sends_nothing_fails(self):
        with running_server(FakeEngine(fail=True)) as (_, _, rt):
            r = say("Synthesis fails.", rt, "--player", "cat")
        self.assertEqual(r.returncode, 1)
        self.assertIn(b"server sent no audio", r.stderr)

    def test_player_stopping_early_is_not_an_error(self):
        # The player quits after a little audio, like a stop: no traceback, exit 0.
        text = " ".join(f"Sentence {i} with some words." for i in range(20))
        with running_server(FakeEngine(delay=0.05)) as (_, _, rt):
            r = say(text, rt, "--player", "head -c 1000")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn(b"Traceback", r.stderr)

    def test_empty_text_is_fine(self):
        with running_server() as (_, _, rt):
            r = say("  ", rt, "--player", "cat")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_requires_runtime_dir(self):
        env = {k: v for k, v in os.environ.items() if k != "XDG_RUNTIME_DIR"}
        r = subprocess.run([sys.executable, CLIENT], input=b"x", capture_output=True, env=env, timeout=30)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn(b"XDG_RUNTIME_DIR is not set", r.stderr)


if __name__ == "__main__":
    unittest.main()
