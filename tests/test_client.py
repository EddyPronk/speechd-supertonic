"""Tests for supertonic_say.py, run as a subprocess against the fake server."""

import os
import socket
import struct
import subprocess
import sys
import tempfile
import threading
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
            r = say("Nobody listens.", rt, "--player", "sh -c 'cat > /dev/null'")
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

    def test_server_error_fails(self):
        with running_server(FakeEngine(fail=True)) as (_, _, rt):
            r = say("Synthesis fails.", rt, "--player", "sh -c 'cat > /dev/null'")
        self.assertEqual(r.returncode, 1)
        self.assertIn(b"server error: synthesis failed", r.stderr)

    def test_failure_after_partial_audio_fails(self):
        # One sentence arrives and plays, then synthesis fails: not a success.
        with running_server(FakeEngine(fail_after=1)) as (_, _, rt), tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "played.raw"
            r = say("First sentence. Second sentence.", rt, "--player", f"sh -c 'cat > {out}'")
            played = out.stat().st_size
        self.assertEqual(r.returncode, 1)
        self.assertGreater(played, 0)
        self.assertIn(b"server error", r.stderr)
        self.assertNotIn(b"playback finished", r.stderr)

    def test_connection_closed_before_done_fails(self):
        # A server that sends one audio frame and then just closes the connection.
        with tempfile.TemporaryDirectory() as rt:
            listener = socket.socket(socket.AF_UNIX)
            listener.bind(os.path.join(rt, "supertonic-tts.sock"))
            listener.listen(1)

            def serve_truncated():
                conn, _ = listener.accept()
                conn.makefile("rb").readline()
                conn.sendall(struct.pack(">cI", b"A", 8) + b"\0" * 8)
                conn.close()

            thread = threading.Thread(target=serve_truncated)
            thread.start()
            r = say("Cut short.", rt, "--player", "sh -c 'cat > /dev/null'")
            thread.join()
            listener.close()
        self.assertEqual(r.returncode, 1)
        self.assertIn(b"before the end of the utterance", r.stderr)
        self.assertNotIn(b"playback finished", r.stderr)

    def test_player_stopping_early_fails_cleanly(self):
        # The player quits after a little audio: a failure, but without a traceback.
        text = " ".join(f"Sentence {i} with some words." for i in range(20))
        with running_server(FakeEngine(delay=0.05)) as (_, _, rt):
            r = say(text, rt, "--player", "head -c 1000")
        self.assertEqual(r.returncode, 1)
        self.assertIn(b"stopped reading before the end", r.stderr)
        self.assertNotIn(b"Traceback", r.stderr)

    def test_output_into_closed_pipe_is_quiet(self):
        text = " ".join(f"Sentence {i} with some words." for i in range(20))
        with running_server() as (_, _, rt):
            r = subprocess.run(
                ["bash", "-c", f'printf %s "$1" | "{sys.executable}" "{CLIENT}" --output - | head -c 10 > /dev/null;'
                               ' echo "${PIPESTATUS[1]}"', "_", text],
                capture_output=True, env=dict(os.environ, XDG_RUNTIME_DIR=rt), timeout=30)
        self.assertEqual(r.stdout.strip(), b"0")
        self.assertEqual(r.stderr, b"")

    def test_empty_text_is_fine(self):
        with running_server() as (_, _, rt):
            r = say("  ", rt, "--player", "sh -c 'cat > /dev/null'")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_requires_runtime_dir(self):
        env = {k: v for k, v in os.environ.items() if k != "XDG_RUNTIME_DIR"}
        r = subprocess.run([sys.executable, CLIENT], input=b"x", capture_output=True, env=env, timeout=30)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn(b"XDG_RUNTIME_DIR is not set", r.stderr)


if __name__ == "__main__":
    unittest.main()
