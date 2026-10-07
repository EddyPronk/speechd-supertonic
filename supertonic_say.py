#!/usr/bin/python3
"""Client for supertonic_server.py, run by speech-dispatcher's sd_generic module.

Reads text on stdin, asks the server for audio and plays it with pw-play. Exits
when playback is done, so speech-dispatcher knows when to send the next
utterance. Standard library only, so it starts instantly.

    printf %s 'Hello' | supertonic_say.py --voice F1-en

Exit status: 0 after successful playback (or when stopped by the player going
away), 1 if the server can't be reached, sends no audio, or the player fails. Errors go to
stderr; speech-dispatcher's module config appends that to the log, followed by
"playback finished" only after a successful run.

--output - writes the raw audio (mono float32 little-endian, 44100 Hz) to stdout
instead of playing it. --player (or $SUPERTONIC_PLAYER) replaces the player
command; it reads that raw audio on stdin.
"""

import argparse
import ctypes
import datetime
import json
import os
import shlex
import signal
import socket
import subprocess
import sys

PLAYER = os.environ.get("SUPERTONIC_PLAYER", "pw-play --raw --format f32 --rate 44100 --channels 1 -")
# Errors that mean "the other side went away", e.g. speech was stopped.
DISCONNECTED = (BrokenPipeError, ConnectionResetError)


def socket_path():
    """The server's socket, in the private per-user runtime directory."""
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if not runtime:
        sys.exit("supertonic_say: XDG_RUNTIME_DIR is not set (needs a systemd user session)")
    return os.path.join(runtime, "supertonic-tts.sock")


def die_with_parent():
    """Run in the player's child process: if this client is killed (speech-dispatcher
    stops speech with SIGKILL), the player is killed too instead of finishing its buffer."""
    PR_SET_PDEATHSIG = 1
    ctypes.CDLL(None, use_errno=True).prctl(PR_SET_PDEATHSIG, signal.SIGKILL)


def log(message):
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S,%f")[:-3]
    print(f"{stamp} [player] INFO {message}", file=sys.stderr, flush=True)


def main():
    parser = argparse.ArgumentParser(description="Speak via supertonic_server.py")
    parser.add_argument("--voice", "-v", default="F1")
    parser.add_argument("--lang", "-l", default="en")
    parser.add_argument("--rate", "-r", type=int, default=0, help="-100..100, 0 = normal")
    parser.add_argument("--volume", type=int, default=0, help="-100..100, 0 = normal")
    parser.add_argument("--player", default=PLAYER, help=f"player command (default: {PLAYER})")
    parser.add_argument("--output", "-o", choices=["-"],
                        help="'-' writes raw audio to stdout instead of playing it")
    args = parser.parse_args()

    req = {"text": sys.stdin.read(), "voice": args.voice, "lang": args.lang,
           "rate": args.rate, "volume": args.volume}
    path = socket_path()

    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        try:
            sock.connect(path)
            sock.sendall(json.dumps(req).encode() + b"\n")
        except OSError as e:
            sys.exit(f"supertonic_say: can't reach server at {path}: {e}")

        if args.output == "-":
            player, out = None, sys.stdout.buffer
        else:
            try:
                player = subprocess.Popen(shlex.split(args.player), stdin=subprocess.PIPE,
                                          preexec_fn=die_with_parent)
            except OSError as e:
                sys.exit(f"supertonic_say: can't start player {args.player!r}: {e}")
            out = player.stdin

        stopped = False
        received = 0
        try:
            while data := sock.recv(65536):
                received += len(data)
                out.write(data)
                out.flush()
        except DISCONNECTED:
            # The player went away (speech stopped) or the server reset the
            # connection; closing the socket tells the server to stop.
            stopped = True

        if player:
            try:
                player.stdin.close()
            except DISCONNECTED:
                stopped = True
            status = player.wait()
            if received == 0 and req["text"].strip() and not stopped:
                sys.exit("supertonic_say: server sent no audio; see the server's log")
            if status != 0 and not stopped:
                sys.exit(f"supertonic_say: player {args.player!r} failed with exit status {status}")
            if status == 0:
                log("playback finished")


if __name__ == "__main__":
    main()
