#!/usr/bin/env bash
# Run all tests. Needs uv (for the server's Python dependencies; no model is
# downloaded: the tests use a fake engine). Doesn't touch your configuration.
#
#   tests/run.sh
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
DEPS=(--with "supertonic>=1.3.1" --with numpy)
status=0

echo "== Python unit tests"
uv run -q "${DEPS[@]}" python -m unittest discover -s . -p 'test_*.py' || status=1

echo "== installer"
bash test_install.sh || status=1

echo "== speech-dispatcher end-to-end"
uv run -q "${DEPS[@]}" bash test_speechd.sh || status=1

[ $status = 0 ] && echo "ALL TESTS PASSED" || echo "SOME TESTS FAILED"
exit $status
