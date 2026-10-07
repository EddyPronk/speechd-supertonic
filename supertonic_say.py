#!/usr/bin/python3
"""Client for supertonic_server.py, run by speech-dispatcher's sd_generic module.

Reads text on stdin, asks the server for audio and plays it with pw-play. Exits
when playback is done, so speech-dispatcher knows when to send the next
utterance. Standard library only, so it starts instantly.

    printf %s 'Hello' | supertonic_say.py --voice F1-en

Exit status: 0 after the whole utterance was played; 1 if the server can't be
reached, reports an error, or closes the connection before the end of the
utterance, or if the player fails or stops reading early. (A stop from
speech-dispatcher kills this process, and the player with it.) Errors go to
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
import struct
import subprocess
import sys

PLAYER = os.environ.get("SUPERTONIC_PLAYER", "pw-play --raw --format f32 --rate 44100 --channels 1 -")
AUDIO, DONE, ERROR = b"A", b"D", b"E"  # frame types, see supertonic_server.py


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


def recv_exact(sock, n):
    """Read exactly n bytes, or return None if the connection ends first."""
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return bytes(buf)


def receive(sock, out):
    """Copy audio frames to `out` until the server's done/error frame.

    Returns None on success, or a description of what went wrong. Raises
    BrokenPipeError if `out` stops accepting data."""
    try:
        while True:
            header = recv_exact(sock, 5)
            if header is None:
                return "server closed the connection before the end of the utterance"
            kind, length = struct.unpack(">cI", header)
            payload = recv_exact(sock, length) if length else b""
            if payload is None:
                return "server closed the connection in the middle of a frame"
            if kind == AUDIO:
                out.write(payload)
                out.flush()
            elif kind == DONE:
                return None
            elif kind == ERROR:
                return "server error: " + payload.decode(errors="replace")
            else:
                return f"unexpected frame type {kind!r} from server"
    except ConnectionResetError:
        return "server reset the connection before the end of the utterance"


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

        try:
            problem = receive(sock, out)
            player_gone = False
        except BrokenPipeError:
            problem, player_gone = None, True

    if player is None:
        if player_gone:
            # --output - into a pipe that closed early (e.g. "| head"): just stop,
            # without Python complaining when it flushes stdout at exit.
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        if problem:
            sys.exit(f"supertonic_say: {problem}")
        return

    try:
        player.stdin.close()
    except BrokenPipeError:
        player_gone = True
    status = player.wait()
    if problem:
        sys.exit(f"supertonic_say: {problem}")
    if status != 0:
        sys.exit(f"supertonic_say: player {args.player!r} failed with exit status {status}")
    if player_gone:
        sys.exit(f"supertonic_say: player {args.player!r} stopped reading before the end of the audio")
    log("playback finished")


if __name__ == "__main__":
    main()
