# Developer notes: tests

## Running

Run everything with `tests/run.sh`. Exit status: 0 passed, 1 a test failed,
2 the environment can't run the tests (uv missing, uv can't prepare packages,
Unix sockets not allowed). If uv's cache isn't writable:
`UV_CACHE_DIR=/tmp/uv-cache tests/run.sh`.

- Python unit tests need only uv (fake engine in `tests/fakes.py`, no model
  download).
- `tests/test_install.sh` runs `install.sh` with `PATH=$T/bin:/usr/bin:/bin`, so it
  needs `python3` in `/usr/bin` or `/bin`. A uv-managed Python elsewhere on PATH
  is not enough: you get "python3 not found" failures that aren't real.
- `tests/test_speechd.sh` needs speech-dispatcher, `spd-say` and a
  PulseAudio/PipeWire socket at `$XDG_RUNTIME_DIR/pulse/native`; without them it
  prints SKIPPED and exits 0. Run on its own, it needs the server's packages:
  `uv run --with 'supertonic>=1.3.1' --with numpy bash tests/test_speechd.sh`.

## Pitfalls

- `pgrep -f PATTERN` also matches any shell whose command line contains PATTERN,
  including the one running your check. Use exact (`-x`) or anchored patterns,
  as `tests/test_speechd.sh` does.
- A player run as `sh -c 'sleep ...; cat'` leaves its `sleep` child running when
  `sh` is killed, which looks like a surviving player. Use a single-process fake
  player (the real one, `pw-play`, is one process).
- Don't restart the installed server or speech-dispatcher while audio is playing
  (`pgrep -x pw-play`): it cuts off the user's narration.

## speech-dispatcher versions

- sd_generic before 0.12.0-rc3 (e.g. Ubuntu 24.04's 0.12.0~rc2) reports a failed
  command as a finished utterance: no module exit, no eSpeak fallback. From rc3
  on, the module exits and speech-dispatcher falls back. The end-to-end test
  checks the behaviour for the installed version.
- `speech-dispatcher -v` drops the rc suffix (rc2 prints "0.12.0"), so the test
  reads the package version (dpkg/rpm) first.
- When the module dies, speech-dispatcher logs either "terminated abnormally" or
  "Output module not running", depending on a race (`output_check_module` in its
  `src/server/output.c`). Match both.
- Modules open the sound server at startup even though our command plays the
  audio itself; the end-to-end test points them at the real one with
  `PULSE_SERVER`.
