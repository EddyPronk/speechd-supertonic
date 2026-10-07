"""Run supertonic_server.py's Server with the fake engine (no model needed).

    python tests/fake_server.py [--delay SECONDS] [--fail]

Listens on $XDG_RUNTIME_DIR/supertonic-tts.sock until killed. Used by the shell
tests to exercise the real client and speech-dispatcher without the model.
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fakes import FakeEngine, server  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--delay", type=float, default=0.0, help="seconds per synthesized chunk")
    parser.add_argument("--fail", action="store_true", help="fail every synthesis")
    parser.add_argument("--fail-after", type=int, help="fail after this many sentences")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                        format="%(asctime)s [server] %(levelname)s %(message)s")
    logging.getLogger("supertonic_server").propagate = True  # fakes.py turns it off for unit tests
    with server.Server(FakeEngine(delay=args.delay, fail=args.fail, fail_after=args.fail_after)) as srv:
        srv.serve_forever()


if __name__ == "__main__":
    main()
