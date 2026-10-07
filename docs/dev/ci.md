# Developer notes: CI

`.github/workflows/tests.yml` has two jobs, both running `tests/run.sh`:

- Ubuntu 24.04 (speech-dispatcher 0.12.0~rc2, the old failure behaviour). Its
  sound-server setup is `continue-on-error`, so the end-to-end test may skip there.
- Debian trixie container (0.12.0, the setup the project was verified on), hosted
  on `ubuntu-24.04` (pinned rather than `ubuntu-latest`, which moves to Ubuntu 26
  from 2026-10-19). Runs as an unprivileged user (PulseAudio refuses root) and
  fails if the end-to-end test was skipped.

The workflow token is read-only (`permissions: contents: read`).

## Actions

- `actions/checkout` is on a major tag (`@v7`).
- `astral-sh/setup-uv` no longer publishes major-version tags; it is pinned to a
  release (`@v10.2.0`) and has to be bumped by hand. Its cache is keyed on
  `cache-dependency-glob` (`supertonic_server.py`, `tests/run.sh`): the files
  that declare the Python dependencies. Update it if they move.
- Keep actions on releases that declare `using: node24` in their `action.yml`;
  Node 20 actions are deprecated on GitHub's runners.

## Reading results with gh

- `gh run list --commit SHA` needs the full SHA; a short one returns nothing.
  After a push, poll until the run exists before `gh run watch`.
- Job results: `gh run view ID --json jobs -q '.jobs[] | "\(.name): \(.conclusion)"'`.
- Failures only: `gh run view ID --log-failed`.
- Warnings and notices (deprecations etc.) are check-run annotations:
  `gh api repos/EddyPronk/speechd-supertonic/check-runs/JOB_ID/annotations`.
