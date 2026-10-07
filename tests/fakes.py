"""Test doubles: a fake Supertonic engine and a server running it in a thread.

The fake engine produces a 440 Hz tone whose length depends on the text, padded
with silence like the real model, so the server's splitting, trimming, pausing
and streaming can be tested without downloading the model.
"""

import contextlib
import logging
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import supertonic_server as server  # noqa: E402

# The server's log output isn't wanted on the test console (tests that check it use
# assertLogs, which still sees everything).
logging.getLogger("supertonic_server").addHandler(logging.NullHandler())
logging.getLogger("supertonic_server").propagate = False

RATE = server.SAMPLE_RATE
PAD = 0.2           # seconds of silence the fake model puts before and after speech
PER_CHAR = 0.01     # seconds of "speech" per character


class FakeTTS:
    def __init__(self, delay=0.0, fail=False, fail_after=None):
        self.delay = delay   # seconds per synthesize() call, to simulate a slow model
        self.fail = fail
        self.fail_after = fail_after  # fail from this call on (0-based), e.g. 1 = after one sentence
        self.calls = []      # (text, steps, speed, lang)

    def synthesize(self, text, voice_style, total_steps, speed, lang):
        self.calls.append((text, total_steps, speed, lang))
        if self.fail or (self.fail_after is not None and len(self.calls) > self.fail_after):
            raise RuntimeError("fake synthesis failure")
        time.sleep(self.delay)
        n = int(len(text) * PER_CHAR * RATE)
        tone = 0.5 * np.sin(2 * np.pi * 440 * np.arange(n) / RATE)
        pad = np.zeros(int(PAD * RATE))
        wav = np.concatenate([pad, tone, pad]).astype(np.float32)[np.newaxis, :]
        return wav, None


class FakeEngine:
    def __init__(self, **kwargs):
        self.tts = FakeTTS(**kwargs)
        self.lock = threading.Lock()
        self.styles = []

    def style(self, voice):
        self.styles.append(voice)
        return voice


def expected_samples(text):
    """Samples the server should send for `text`: each sentence's fake audio,
    trimmed, plus the pauses between sentences."""
    pieces = server.split_sentences(text)
    tts = FakeTTS()
    total = sum(server.trim_silence(tts.synthesize(p, None, 8, 1.0, "en")[0].squeeze())[0].size
                for p in pieces)
    return total + (len(pieces) - 1) * int(server.SILENCE_SECONDS * RATE)


@contextlib.contextmanager
def running_server(engine=None, runtime_dir=None):
    """Run a Server with a fake engine on $runtime_dir/supertonic-tts.sock."""
    engine = engine or FakeEngine()
    tmp = None
    if runtime_dir is None:
        tmp = tempfile.TemporaryDirectory()
        runtime_dir = tmp.name
        os.chmod(runtime_dir, 0o700)
    path = Path(runtime_dir) / server.SOCKET_NAME
    srv = server.Server(engine, path=path)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield srv, engine, runtime_dir
    finally:
        srv.shutdown()
        srv.server_close()
        path.unlink(missing_ok=True)
        if tmp:
            tmp.cleanup()
