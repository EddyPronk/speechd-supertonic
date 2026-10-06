#!/usr/bin/python3
"""Client for supertonic_server.py, used by speech-dispatcher's sd_generic module.

Reads text on stdin, sends it to the server and writes the raw float32 audio it
streams back to stdout. Standard library only, so it starts instantly. Pipe it
into a player:

    printf %s 'Hello' | supertonic_say.py --voice F1 | \\
        pw-play --raw --format f32 --rate 44100 --channels 1 -

Exits 1 (message on stderr) if the server can't be reached.
"""

import argparse
import json
import os
import socket
import sys
from pathlib import Path

SOCKET_PATH = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "supertonic-tts.sock"


def main():
    parser = argparse.ArgumentParser(description="Speak via supertonic_server.py")
    parser.add_argument("--voice", "-v", default="F1")
    parser.add_argument("--lang", "-l", default="en")
    parser.add_argument("--rate", "-r", type=int, default=0, help="-100..100, 0 = normal")
    parser.add_argument("--volume", type=int, default=0, help="-100..100, 0 = normal")
    args = parser.parse_args()

    req = {"text": sys.stdin.read(), "voice": args.voice, "lang": args.lang,
           "rate": args.rate, "volume": args.volume}

    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        try:
            sock.connect(str(SOCKET_PATH))
        except OSError as e:
            sys.exit(f"supertonic_say: can't reach server at {SOCKET_PATH}: {e}")
        sock.sendall(json.dumps(req).encode() + b"\n")
        out = sys.stdout.buffer
        try:
            while data := sock.recv(65536):
                out.write(data)
                out.flush()
        except BrokenPipeError:
            pass  # the player went away (speech stopped); closing tells the server to stop


if __name__ == "__main__":
    main()
