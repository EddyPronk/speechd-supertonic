"""Tests for supertonic_server.py: helpers, protocol, disconnects, logging, socket safety."""

import json
import os
import socket
import stat
import tempfile
import time
import unittest
from pathlib import Path

import numpy as np

from fakes import RATE, FakeEngine, expected_samples, running_server, server


def request(runtime_dir, text, voice="F1-en", lang="en", rate=0, volume=0, read=True):
    """Send one request; return the raw audio bytes (or the open socket if read=False)."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(os.path.join(runtime_dir, server.SOCKET_NAME))
    msg = {"text": text, "voice": voice, "lang": lang, "rate": rate, "volume": volume}
    sock.sendall(json.dumps(msg).encode() + b"\n")
    if not read:
        return sock
    data = b""
    while chunk := sock.recv(65536):
        data += chunk
    sock.close()
    return data


class TestHelpers(unittest.TestCase):
    def test_rate_to_speed(self):
        f = server.speechd_rate_to_speed
        self.assertAlmostEqual(f(0), 1.05)
        self.assertAlmostEqual(f(-100), 0.7)
        self.assertAlmostEqual(f(100), 2.0)
        self.assertAlmostEqual(f(-500), 0.7)   # clamped
        self.assertAlmostEqual(f(500), 2.0)
        self.assertLess(f(-50), f(0))
        self.assertGreater(f(50), f(0))

    def test_speechd_lang(self):
        f = server.speechd_lang
        self.assertEqual(f("en"), "en")
        self.assertEqual(f("en-AU"), "en")
        self.assertEqual(f("nl_NL"), "nl")
        self.assertEqual(f("NL"), "nl")
        self.assertEqual(f("nl-x-m2"), "nl")
        self.assertEqual(f("xx"), "na")
        self.assertEqual(f(""), "na")

    def test_split_voice(self):
        self.assertEqual(server.split_voice("M2-nl"), ("M2", "nl"))
        self.assertEqual(server.split_voice("F1"), ("F1", None))
        self.assertEqual(server.split_voice("F1-"), ("F1", None))

    def test_split_sentences(self):
        f = server.split_sentences
        self.assertEqual(f("One. Two! Three? Four…"), ["One.", "Two!", "Three?", "Four…"])
        self.assertEqual(f("He said “Wait.” Then left."), ["He said “Wait.”", "Then left."])
        # No split before a lowercase word (abbreviations, "(Really.) then").
        self.assertEqual(f("See e.g. the docs. Next one."), ["See e.g. the docs.", "Next one."])
        self.assertEqual(f("In 2015. 2016 was next."), ["In 2015.", "2016 was next."])
        # Commas never split a sentence.
        self.assertEqual(f("First, a long clause, and more."), ["First, a long clause, and more."])
        self.assertEqual(f("   "), [])
        self.assertEqual(f("No end punctuation"), ["No end punctuation"])

    def test_trim_silence(self):
        margin = int(server.TRIM_MARGIN * RATE)
        audio = np.concatenate([np.zeros(RATE), np.full(1000, 0.5), np.zeros(RATE // 2)]).astype(np.float32)
        trimmed, lead, trail = server.trim_silence(audio)
        self.assertEqual(trimmed.size, 1000 + 2 * margin)
        self.assertAlmostEqual(lead, (RATE - margin) / RATE)
        self.assertAlmostEqual(trail, (RATE // 2 - margin) / RATE)
        # Quiet but not silent samples are kept.
        self.assertTrue(np.all(np.abs(trimmed[margin:-margin]) == 0.5))

    def test_trim_silence_edges(self):
        silent = np.zeros(500, dtype=np.float32)
        self.assertIs(server.trim_silence(silent)[0], silent)
        loud = np.full(500, 0.5, dtype=np.float32)
        trimmed, lead, trail = server.trim_silence(loud)
        self.assertEqual((trimmed.size, lead, trail), (500, 0.0, 0.0))

    def test_shown(self):
        try:
            server.log_text = False
            self.assertEqual(server.shown("secret text"), "<11 chars>")
            server.log_text = True
            self.assertEqual(server.shown("secret text"), "'secret text'")
        finally:
            server.log_text = False


class TestProtocol(unittest.TestCase):
    def test_streams_trimmed_sentences_with_pauses(self):
        text = "First sentence here. Second one."
        with running_server() as (_, engine, rt):
            data = request(rt, text)
        self.assertEqual(len(data) % 4, 0)
        self.assertEqual(len(data) // 4, expected_samples(text))
        audio = np.frombuffer(data, dtype="<f4")
        self.assertLessEqual(np.abs(audio).max(), 0.5 + 1e-6)
        self.assertEqual([c[0] for c in engine.tts.calls], ["First sentence here.", "Second one."])

    def test_language_from_voice_name_and_parameters(self):
        with running_server() as (_, engine, rt):
            request(rt, "Hello.", voice="M2-nl", lang="en", rate=100)
        text, steps, speed, lang = engine.tts.calls[0]
        self.assertEqual((lang, speed, steps), ("nl", 2.0, server.STEPS))
        self.assertEqual(engine.styles, ["M2"])

    def test_language_falls_back_to_speechd_language(self):
        with running_server() as (_, engine, rt):
            request(rt, "Hello.", voice="M2", lang="nl-NL")
        self.assertEqual(engine.tts.calls[0][3], "nl")

    def test_volume_scales_audio(self):
        with running_server() as (_, _, rt):
            full = np.frombuffer(request(rt, "Loud."), dtype="<f4")
            half = np.frombuffer(request(rt, "Loud.", volume=-50), dtype="<f4")
        self.assertAlmostEqual(np.abs(half).max(), np.abs(full).max() / 2, places=3)

    def test_first_steps_only_for_first_chunk(self):
        try:
            server.first_steps = 4
            with running_server() as (_, engine, rt):
                request(rt, "One. Two. Three.")
        finally:
            server.first_steps = server.STEPS
        self.assertEqual([c[1] for c in engine.tts.calls], [4, server.STEPS, server.STEPS])

    def test_empty_text_sends_nothing(self):
        with running_server() as (_, engine, rt):
            self.assertEqual(request(rt, "   "), b"")
        self.assertEqual(engine.tts.calls, [])

    def test_bad_request_then_next_request_works(self):
        with running_server() as (_, _, rt):
            with self.assertLogs("supertonic_server", "ERROR"):
                with socket.socket(socket.AF_UNIX) as sock:
                    sock.connect(os.path.join(rt, server.SOCKET_NAME))
                    sock.sendall(b"not json\n")
                    self.assertEqual(sock.recv(10), b"")
            self.assertGreater(len(request(rt, "Still works.")), 0)

    def test_synthesis_error_is_logged_and_sends_nothing(self):
        with running_server(FakeEngine(fail=True)) as (_, _, rt):
            with self.assertLogs("supertonic_server", "ERROR") as logs:
                self.assertEqual(request(rt, "Fails."), b"")
        self.assertTrue(any("request failed" in line for line in logs.output))

    def test_client_disconnect_stops_synthesis(self):
        engine = FakeEngine(delay=0.2)
        text = " ".join(f"Sentence number {i}." for i in range(10))
        with running_server(engine) as (_, _, rt):
            with self.assertLogs("supertonic_server", "INFO") as logs:
                sock = request(rt, text, read=False)
                time.sleep(0.3)   # first chunk synthesized
                sock.close()
                deadline = time.monotonic() + 5
                while not any("stopped by client" in l for l in logs.output) and time.monotonic() < deadline:
                    time.sleep(0.05)
            # The next request is served normally afterwards.
            self.assertGreater(len(request(rt, "Next.")), 0)
        self.assertTrue(any("stopped by client" in line for line in logs.output))
        self.assertLess(len(engine.tts.calls), 10 + 1)  # the rest of the 10 sentences was skipped
        self.assertLess(len([c for c in engine.tts.calls if c[0].startswith("Sentence")]), 10)

    def test_log_hides_text_unless_debug(self):
        with running_server() as (_, _, rt):
            with self.assertLogs("supertonic_server", "INFO") as logs:
                request(rt, "Secret words.")
        joined = "\n".join(logs.output)
        self.assertNotIn("Secret", joined)
        self.assertIn("text=<13 chars>", joined)
        try:
            server.log_text = True
            with running_server() as (_, _, rt):
                with self.assertLogs("supertonic_server", "INFO") as logs:
                    request(rt, "Secret words.")
        finally:
            server.log_text = False
        self.assertIn("text='Secret words.'", "\n".join(logs.output))


class TestSocketSafety(unittest.TestCase):
    def test_requires_runtime_dir(self):
        old = os.environ.pop("XDG_RUNTIME_DIR", None)
        try:
            with self.assertRaises(SystemExit):
                server.default_socket_path()
        finally:
            if old is not None:
                os.environ["XDG_RUNTIME_DIR"] = old

    def test_socket_is_private(self):
        with running_server() as (_, _, rt):
            mode = os.stat(os.path.join(rt, server.SOCKET_NAME)).st_mode
        self.assertTrue(stat.S_ISSOCK(mode))
        self.assertEqual(stat.S_IMODE(mode) & 0o077, 0)

    def test_refuses_to_remove_non_socket(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / server.SOCKET_NAME
            path.write_text("not a socket")
            with self.assertRaises(SystemExit):
                server.remove_stale_socket(path)
            self.assertTrue(path.exists())

    def test_replaces_own_stale_socket(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / server.SOCKET_NAME
            stale = socket.socket(socket.AF_UNIX)
            stale.bind(str(path))
            stale.close()
            server.remove_stale_socket(path)
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
