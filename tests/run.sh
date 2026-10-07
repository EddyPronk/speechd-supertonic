#!/usr/bin/env bash
# Run all tests. Needs uv (for the server's Python dependencies; no model is
# downloaded: the tests use a fake engine). Doesn't touch your configuration.
#
#   tests/run.sh
#
# Exit status: 0 all passed, 1 a test failed, 2 the environment can't run the
# tests (see the message: uv's cache not writable, Unix sockets not allowed, ...).
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
DEPS=(--with "supertonic>=1.3.1" --with numpy)

setup_problem() {
    echo "SETUP PROBLEM: $*" >&2
    echo "The tests didn't run; this is about the environment, not the code." >&2
    exit 2
}

echo "== checking the environment"
command -v uv >/dev/null || setup_problem "uv not found (https://docs.astral.sh/uv/)"
if ! out=$(uv run -q "${DEPS[@]}" python -c "import supertonic, numpy" 2>&1); then
    setup_problem "uv couldn't prepare the Python packages:
$out
If uv's cache isn't writable (e.g. in a sandbox), point it elsewhere:
  UV_CACHE_DIR=/tmp/uv-cache tests/run.sh"
fi
if ! out=$(python3 -c '
import os, socket, tempfile
with tempfile.TemporaryDirectory() as d:
    s = socket.socket(socket.AF_UNIX)
    s.bind(os.path.join(d, "test.sock"))
    s.listen(1)
' 2>&1); then
    setup_problem "can't create a Unix socket here (sandbox or seccomp restriction?):
$out"
fi

status=0
echo "== Python unit tests"
uv run -q "${DEPS[@]}" python -m unittest discover -s . -p 'test_*.py' || status=1

echo "== installer"
bash test_install.sh || status=1

echo "== speech-dispatcher end-to-end"
uv run -q "${DEPS[@]}" bash test_speechd.sh || status=1

[ $status = 0 ] && echo "ALL TESTS PASSED" || echo "SOME TESTS FAILED"
exit $status
