#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "supertonic>=1.3.1",
#     "numpy",
# ]
# ///
"""Supertonic TTS server for speech-dispatcher: keeps the model loaded.

Listens on a Unix socket ($XDG_RUNTIME_DIR/supertonic-tts.sock, or the socket
systemd passes in). Protocol, one request per connection:

    client -> server   one JSON line: {"text": ..., "voice": "F1", "lang": "en-AU",
                                       "rate": 0, "volume": 0}
    server -> client   raw mono float32 little-endian PCM at 44100 Hz, streamed
                       chunk by chunk as it is synthesized, then EOF

If the client goes away (speech-dispatcher killed it to stop speech) the server
stops synthesizing that request. See supertonic_say.py for the client.

Run by systemd (~/.config/systemd/user/supertonic-tts.{socket,service}) or by hand:
    uv run supertonic_server.py
"""

import argparse
import itertools
import json
import logging
import os
import queue
import re
import select
import socket
import socketserver
import sys
import threading
import time
from pathlib import Path

import numpy as np
from supertonic import AVAILABLE_LANGUAGES, TTS
from supertonic.utils import chunk_text

DEFAULT_VOICE = "F1"
SAMPLE_RATE = 44100  # what supertonic_say.py tells the player to expect
# Supertonic pads every chunk with ~0.55-0.65s of silence in front and ~0.6-0.7s
# behind. Left in, a comma split sounded like a 1.4s pause (a comma inside one
# chunk is ~0.3s) and sentences were 1.5s apart. So each chunk is trimmed to its
# audible part and this pause is put back in between sentences instead:
SILENCE_SECONDS = 0.45
STEPS = 8  # quality steps per chunk: more is better but slower
# Steps for a paragraph's first chunk, the only one the listener waits for.
# Set with --first-steps (e.g. 4 to roughly halve the wait); see docs/testing.md.
first_steps = STEPS
TRIM_THRESHOLD = 0.01      # samples quieter than this count as silence...
TRIM_MARGIN = 0.04         # ...but keep this much around the audible part (soft consonants)
SOCKET_PATH = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "supertonic-tts.sock"
LOG_FILE = Path(os.environ.get("SPEECHD_SUPERTONIC_LOG",
                               Path.home() / ".cache" / "speechd_supertonic.log"))

log = logging.getLogger("supertonic_server")
request_ids = itertools.count(1)


def speechd_rate_to_speed(rate):
    """Map speech-dispatcher's rate (-100..100, 0 = normal) to Supertonic speed (0.7..2.0)."""
    rate = max(-100, min(100, rate))
    if rate < 0:
        return 1.05 + rate / 100 * 0.35
    return 1.05 + rate / 100 * 0.95


def split_voice(voice):
    """'M2-nl' -> ('M2', 'nl'); 'M2' -> ('M2', None).

    The speech-dispatcher voice names carry the language because Firefox picks a
    voice by name only, and plain 'M2' would always resolve to the English entry.
    """
    name, _, lang = voice.partition("-")
    return name, (lang or None)


# Sentence end: . ! ? or … (optionally followed by a closing quote/bracket), then
# whitespace, then something that looks like the start of a new sentence.
SENTENCE_END = re.compile(r"""(?<=[.!?…])["'”’)\]]*\s+(?=["'“‘(\[]?[A-Z0-9À-ÖØ-Þ])""")


def split_sentences(text):
    """Split into sentences (each synthesized in one call, so its intonation stays
    intact), and only split a sentence further if it is too long for the model.
    Sentences after the first are synthesized while earlier ones play."""
    chunks = []
    for sentence in SENTENCE_END.split(text):
        chunks.extend(c.strip() for c in chunk_text(sentence.strip()) if c.strip())
    return chunks


def trim_silence(audio):
    """Cut leading/trailing silence; returns (audio, seconds cut in front, seconds cut behind)."""
    loud = np.flatnonzero(np.abs(audio) > TRIM_THRESHOLD)
    if loud.size == 0:
        return audio, 0.0, 0.0
    margin = int(TRIM_MARGIN * SAMPLE_RATE)
    start = max(0, loud[0] - margin)
    end = min(audio.size, loud[-1] + 1 + margin)
    return audio[start:end], start / SAMPLE_RATE, (audio.size - end) / SAMPLE_RATE


def speechd_lang(language):
    """'en-US' / 'en_GB' / 'nl' -> a Supertonic language code, or 'na' if unsupported."""
    code = language.replace("_", "-").split("-")[0].lower()
    return code if code in AVAILABLE_LANGUAGES else "na"


class Engine:
    """The loaded model plus cached voice styles. One synthesis at a time."""

    def __init__(self):
        start = time.perf_counter()
        self.tts = TTS()
        if self.tts.sample_rate != SAMPLE_RATE:
            sys.exit(f"model sample rate {self.tts.sample_rate} != {SAMPLE_RATE}; "
                     "update SAMPLE_RATE here and in supertonic_say.py")
        self.voices = set(self.tts.voice_style_names)
        self._styles = {}
        self.lock = threading.Lock()
        log.info("model loaded in %.2fs, voices: %s", time.perf_counter() - start,
                 " ".join(sorted(self.voices)))

    def style(self, voice):
        if voice not in self.voices:
            log.warning("unknown voice %r, using %s", voice, DEFAULT_VOICE)
            voice = DEFAULT_VOICE
        if voice not in self._styles:
            self._styles[voice] = self.tts.get_voice_style(voice)
        return self._styles[voice]


class Handler(socketserver.StreamRequestHandler):
    def client_gone(self):
        """True if the client hung up (speech-dispatcher stopped the speech)."""
        readable, _, _ = select.select([self.connection], [], [], 0)
        return bool(readable) and not self.connection.recv(1, socket.MSG_PEEK)

    def handle(self):
        req_id = next(request_ids)
        try:
            req = json.loads(self.rfile.readline())
            text = str(req.get("text", "")).strip()
            voice = str(req.get("voice", DEFAULT_VOICE))
            lang_in = str(req.get("lang", "en"))
            rate = int(req.get("rate", 0))
            volume = int(req.get("volume", 0))
        except (ValueError, TypeError) as e:
            log.error("[%s] bad request: %s", req_id, e)
            return

        received = time.monotonic()
        name, voice_lang = split_voice(voice)
        lang = speechd_lang(voice_lang or lang_in)
        log.info("[%s] start voice=%s lang=%s (speechd voice=%s language=%s) rate=%s volume=%s text=%r",
                 req_id, name, lang, voice, lang_in, rate, volume, text)
        if not text:
            log.info("[%s] done (empty text)", req_id)
            return

        engine = self.server.engine
        speed = speechd_rate_to_speed(rate)
        gain = 1 + min(0, max(-100, volume)) / 100  # 0 (default) and up = full volume
        pieces = split_sentences(text)

        # Sending happens in its own thread: a write blocks until the player has
        # room, which for a long sentence is nearly the end of its playback.
        # Synthesizing in this thread meanwhile keeps the next sentence ready.
        outbox = queue.Queue()
        gone = threading.Event()
        sender = threading.Thread(target=self.send_audio, args=(outbox, gone), daemon=True)
        sender.start()

        audio_seconds = 0.0  # audio handed to the sender so far
        synth_seconds = 0.0
        first_audio = None   # when playback (approximately) started
        with engine.lock:
            waited = time.monotonic() - received
            if waited > 0.05:
                log.info("[%s] waited %.2fs for the previous request to finish", req_id, waited)
            style = engine.style(name)
            for i, piece in enumerate(pieces):
                if gone.is_set() or self.client_gone():
                    log.info("[%s] stopped by client before chunk %d/%d", req_id, i + 1, len(pieces))
                    outbox.put(None)
                    self.server.audio_ends = None
                    return
                t = time.monotonic()
                steps = first_steps if i == 0 else STEPS
                wav, _ = engine.tts.synthesize(piece, voice_style=style, total_steps=steps,
                                               speed=speed, lang=lang)
                now = time.monotonic()
                synth = now - t
                synth_seconds += synth
                audio, cut_lead, cut_trail = trim_silence(wav.squeeze().astype(np.float32) * gain)
                length = audio.size / SAMPLE_RATE
                if first_audio is None:
                    first_audio = now
                    timing = self.first_audio_timing(received)
                else:
                    # Positive: ready before the previous audio runs out. Negative: the
                    # player ran dry and the listener heard a gap of that length.
                    ahead = first_audio + audio_seconds - now
                    if ahead >= 0:
                        timing = f"ready {ahead:.2f}s before needed"
                    else:
                        timing = f"LATE by {-ahead:.2f}s (audible gap)"
                        first_audio -= ahead  # playback resumes now
                log.info("[%s] chunk %d/%d synthesized in %.2fs (%.2fs audio after trimming "
                         "%.2fs+%.2fs silence, %.0f%% of real time), %s: %r",
                         req_id, i + 1, len(pieces), synth, length, cut_lead, cut_trail,
                         100 * synth / max(length, 1e-6), timing, piece)
                if i < len(pieces) - 1:
                    audio = np.concatenate([audio, np.zeros(int(SILENCE_SECONDS * SAMPLE_RATE), dtype=np.float32)])
                audio_seconds += audio.size / SAMPLE_RATE
                self.server.audio_ends = first_audio + audio_seconds
                outbox.put(audio.astype("<f4").tobytes())
        outbox.put(None)
        log.info("[%s] synthesis done: %d chunks, %.2fs audio in %.2fs; audio should end in ~%.2fs",
                 req_id, len(pieces), audio_seconds, synth_seconds,
                 max(0.0, self.server.audio_ends - time.monotonic()))
        sender.join()
        if gone.is_set():
            log.info("[%s] stopped by client while sending", req_id)
            self.server.audio_ends = None

    def send_audio(self, outbox, gone):
        while (data := outbox.get()) is not None:
            try:
                self.wfile.write(data)
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                gone.set()
                return

    def first_audio_timing(self, received):
        """How long the listener waited for the first audio of this utterance:
        since the request, and since the previous utterance's audio (estimated) ended."""
        now = time.monotonic()
        text = f"first audio {now - received:.2f}s after request"
        if self.server.audio_ends is not None:
            text += f", ~{now - self.server.audio_ends:.2f}s silence since previous audio"
        return text


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True

    def __init__(self, engine):
        self.engine = engine
        self.audio_ends = None  # monotonic time the last sent audio should finish playing
        # LISTEN_PID is uv's PID when started via `uv run`, so accept our parent too.
        listen_pid = os.environ.get("LISTEN_PID")
        if os.environ.get("LISTEN_FDS") == "1" and listen_pid in (str(os.getpid()), str(os.getppid())):
            # Socket activation: systemd already created and bound the socket (fd 3).
            super().__init__(str(SOCKET_PATH), Handler, bind_and_activate=False)
            self.socket.close()
            self.socket = socket.socket(fileno=3)
            log.info("listening on socket from systemd")
        else:
            SOCKET_PATH.unlink(missing_ok=True)
            super().__init__(str(SOCKET_PATH), Handler)
            log.info("listening on %s", SOCKET_PATH)


def main():
    global first_steps
    parser = argparse.ArgumentParser(description="Supertonic TTS server for speech-dispatcher")
    parser.add_argument("--first-steps", type=int, default=STEPS,
                        help=f"quality steps for each paragraph's first chunk (default: {STEPS})")
    first_steps = parser.parse_args().first_steps

    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [server] %(levelname)s %(message)s",
        handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()],
    )
    # Supertonic logs every model detail at INFO; keep the log about requests.
    logging.getLogger("supertonic").setLevel(logging.WARNING)

    log.info("quality steps: %d, first chunk of a paragraph: %d", STEPS, first_steps)
    with Server(Engine()) as server:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
