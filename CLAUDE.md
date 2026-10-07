# speechd-supertonic

Supertonic TTS as a speech-dispatcher output module (for Firefox Read aloud).
`supertonic_server.py` keeps the model loaded; `supertonic_say.py` is the client
that speech-dispatcher's sd_generic runs per utterance; `install.sh` writes the
module config and systemd user units. User docs: README.md, docs/how-it-works.md.

## Rules for any change

- `supertonic_say.py` stays standard-library only (it must start instantly).
- Protocol frames (`A` audio, `D` done, `E` error) are defined in both server and
  client; change both. Only `D` means success.
- The module command keeps `$DATA` single-quoted (`\'$DATA\'`) and stays a single
  command: sd_generic runs it with `/bin/bash -c "set -o pipefail ; ..."` and its
  exit status is the client's.
- AddVoice types must be FEMALE1-3, MALE1-3 or CHILD_*; others are silently dropped.
- The text being read is logged only with `--debug`; don't add it to the default log.
- Docs and tests are in English. Mark claims *verified* only against a stated setup.

## Read when needed

- Running, writing or debugging tests, or speech-dispatcher version differences:
  read docs/dev/testing.md first.
- Changing the GitHub Actions workflow or reading CI results: read docs/dev/ci.md first.
