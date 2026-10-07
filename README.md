# speechd-supertonic

Natural-sounding [Supertonic](https://github.com/supertone-inc/supertonic) voices
for Firefox's "Read aloud" (Reader View Narrate) and anything else on Linux that
speaks through [speech-dispatcher](https://github.com/brailcom/speechd).

Supertonic is a fast, local, multilingual TTS model (31 languages, 5 female and
5 male voices). speechd-supertonic runs it as a small background server that keeps
the model loaded, and adds it to speech-dispatcher as an output module. Nothing
leaves your machine.

How it works, the log format and its known limits: [docs/how-it-works.md](docs/how-it-works.md).

## Tested with

Debian 13 (trixie) on x86_64, Firefox 157.0 (Mozilla's .deb), speech-dispatcher
0.12.0, PipeWire 1.4.2, supertonic 1.3.1, Python 3.12 via uv 0.11.8. Everything
marked *verified* below was checked on that setup (by hand, or by the automated
tests in [`tests/`](#tests)). Other distributions, versions, and Firefox as a
Snap or Flatpak have not been tried.

## Requirements

- Linux with a systemd user session and PipeWire (for `pw-play`)
- speech-dispatcher with its `sd_generic` module
- Python 3.10 or newer, and [uv](https://docs.astral.sh/uv/) (it installs the
  server's Python packages in a cached environment)
- About 400 MB of disk space for the model and 600 MB of RAM while the server runs.
  The model downloads from Hugging Face on first use.

On Debian/Ubuntu:

```
sudo apt install speech-dispatcher pipewire-bin python3
curl -LsSf https://astral.sh/uv/install.sh | sh      # or see the uv docs
```

## Install

> **What the installer changes.** It works only in your home directory, but it
> changes how speech-dispatcher behaves for your user:
>
> - If you have **no** `~/.config/speech-dispatcher/speechd.conf`, it creates one
>   by **copying the system file** (`/etc/speech-dispatcher/speechd.conf`),
>   because a user file replaces the system one entirely.
> - If you **have** one, it **edits it in place**: it appends a block between
>   `# >>> speechd-supertonic` and `# <<< speechd-supertonic`.
> - That block makes Supertonic speech-dispatcher's **default voice** for all
>   programs (skip with `--no-default`), and lists eSpeak NG next to it.
>
> `./install.sh --uninstall` removes the block again (and the file, if the
> installer created it and you haven't changed it).

```
git clone https://github.com/EddyPronk/speechd-supertonic.git
cd speechd-supertonic
./install.sh
```

By default you get voices for English plus your locale's language (for example
Dutch with `LANG=nl_NL.UTF-8`). To choose:

```
./install.sh --languages "en nl de"
```

Supported: en ko ja ar bg cs da de el es et fi fr hi hr hu id it lt lv nl pl pt
ro ru sk sl sv tr uk vi. Rerun `install.sh` any time to change languages or to
update after a `git pull`.

The log records timing and the length of what was read, not the text itself.
To log the text too (handy when something is mispronounced or skipped):

```
./install.sh --debug
```

Run `./install.sh` again without it to switch back.

Your home directory path (and `XDG_*` directories, if set) may contain spaces
and most other characters, but not quotes, backslashes, `$`, `%` or newlines:
those would need escaping in the generated shell command and systemd unit, so
the installer refuses them with a clear message. speech-dispatcher's modules
are searched in `lib*/[<arch>/]speech-dispatcher-modules` under `/usr`,
`/usr/local` and `/`; set `SPEECHD_MODULES_DIR` if yours are elsewhere.

What it does, all in your home directory (no root):

1. Copies the server and client to `~/.local/share/speechd-supertonic/`.
2. Writes the speech-dispatcher module `~/.config/speech-dispatcher/modules/supertonic.conf`.
3. Adds the marked block to `~/.config/speech-dispatcher/speechd.conf` (see the
   box above).
4. Installs and enables the systemd user units `supertonic-tts.socket` and
   `supertonic-tts.service`. The socket starts the server on first use.
5. Restarts speech-dispatcher and sends a silent test request, which downloads
   the packages and the model the first time (this can take a few minutes).

Check it from a terminal:

```
spd-say -o supertonic -y F1-en "Hello, this is Supertonic."
```

## Firefox

1. **Restart Firefox** after installing. It reads the list of voices only at
   startup.
2. Check that speech is enabled: in `about:config`, `media.webspeech.synth.enabled`
   and `narrate.enabled` must be `true` (the default).
3. Open an article and switch to **Reader View** (the page icon in the address
   bar, or Ctrl+Alt+R).
4. Click the **headphones** icon on the left (Read aloud).
5. Under **Voice**, pick a Supertonic voice for the page's language. Don't leave
   it on "Default": that may pick a voice for the wrong language, or eSpeak.

   Firefox on Linux labels voices by language tag only, so the Supertonic voices
   appear as, for example:

   | Menu entry | Voice |
   |------------|-------|
   | English (en-x-f1) … English (en-x-f5) | female voices F1–F5, English |
   | English (en-x-m1) … English (en-x-m5) | male voices M1–M5, English |
   | Dutch (nl-x-f1) … Dutch (nl-x-m5) | the same voices, Dutch |

   Entries without `-x-` in the tag are eSpeak voices.
6. Press play. The speed slider works too.

Firefox remembers the chosen voice per page language, so pick one once for each
language you read.

*Verified* on Firefox 157.0: the menu labels, choosing a voice per language,
Dutch and English pages, play/stop. *Not verified:* the speed slider and
skipping forward/back.

The same voices are available to web pages through the Web Speech API
(`speechSynthesis`).

Not tested yet: Firefox installed as a Snap or Flatpak (the sandbox may not be
able to reach speech-dispatcher), and other browsers.

## Other programs

Anything that speaks through speech-dispatcher can use the voices, for example
from a shell or script:

```
spd-say -o supertonic -y F1-en "Hello, this is Supertonic."
spd-say -o supertonic -y M2-en "A different voice."
```

`spd-say -o supertonic -L` lists the voices. [examples/claude-code](examples/claude-code)
has a hook that makes Claude Code read its replies and notifications aloud.

## Troubleshooting

The server logs every utterance to `~/.cache/speechd_supertonic.log` (timing
and length; the text itself only after `./install.sh --debug`). See
[docs/how-it-works.md](docs/how-it-works.md#logging) for how to read it.

| Symptom | Likely cause | What to do |
|---------|--------------|------------|
| No Supertonic voices in Firefox | Firefox wasn't restarted, or speech-dispatcher didn't load the module | Restart Firefox. Check `spd-say -O` lists `supertonic`. |
| Robotic voice, nothing new in the log | An eSpeak voice (or "Default") is selected, **or** an earlier utterance failed (see the next row) and speech-dispatcher switched to eSpeak | Pick an `-x-` voice. Look for errors in the log. Then restart speech-dispatcher: `pkill -u "$(id -u)" -x speech-dispatch` |
| Reading stops in the middle of an article; then the robotic voice | An utterance failed (server not running, player error): speech-dispatcher's module gives up, that paragraph never finishes, and later text goes to eSpeak *(verified by `tests/test_speechd.sh`)* | Fix the cause from the log (`can't reach server`, `player ... failed`), restart speech-dispatcher as above, press stop and play in Firefox. |
| Wrong pronunciation (e.g. Dutch read as English) | A voice for the wrong language is selected | Check the `start` line in the log: `lang=` must match the page. Pick the matching `-x-` voice. |
| `can't reach server` in the log | The socket or server isn't running | `systemctl --user status supertonic-tts.socket supertonic-tts.service` and `journalctl --user -u supertonic-tts.service` |
| A pause of a few seconds before some paragraphs | Synthesis of the paragraph's first sentence; long first sentences take longer | Expected; see "Known limits" in [docs/how-it-works.md](docs/how-it-works.md#known-limits). |
| `?` instead of quotes, dashes or accented letters | A language tag without a UTF-8 line in `supertonic.conf` | Rerun `./install.sh`. |

## Tests

```
tests/run.sh
```

Runs everything without the model (a fake engine stands in for Supertonic) and
without touching your configuration:

- **Unit tests** for the server (rate, volume, language and sentence handling,
  silence trimming, the socket protocol, disconnects, error logging, socket
  permissions), the client (exit status when the server, synthesis or player
  fails, including a failure after part of the audio), and `speechd_timing.py`
  (sample logs, including empty and malformed ones).
- **Installer tests** (`tests/test_install.sh`): install, reinstall, uninstall in
  temporary directories; existing configuration; paths with spaces, `&`, `#` and
  placeholder-like names, refused paths; module discovery in an unlisted
  multiarch directory; and the generated speech-dispatcher command run the way
  `sd_generic` runs it, to check quoting (no command injection from page text)
  and exit status.
- **End-to-end** (`tests/test_speechd.sh`): a private speech-dispatcher instance
  with the generated configuration, the real client and a fake server: an
  utterance completes; a stop ends the utterance at once, kills the client and
  player, and keeps the module working; a dead server leads to the eSpeak
  fallback (with speech-dispatcher 0.12.0-rc3 or later; older versions, such as
  Ubuntu 24.04's 0.12.0~rc2, report the failed utterance as finished instead,
  which the test checks for there). Skipped if speech-dispatcher or a sound
  server isn't available.

Needs uv (for the server's Python packages) and permission to create Unix
sockets. The runner checks both first and exits with status 2 and a
"SETUP PROBLEM" message if the environment can't run the tests, as opposed to
status 1 for a failing test. If uv's cache isn't writable (for example in a
sandbox), point it elsewhere:

```
UV_CACHE_DIR=/tmp/uv-cache tests/run.sh
```

## Uninstall

```
./install.sh --uninstall
```

Removes everything `install.sh` added (and `speechd.conf` itself, if the
installer created it and you haven't changed it). The log and the downloaded
model (`~/.cache/supertonic3`) are left in place; delete them by hand if you
like. Restart Firefox afterwards.

## Licenses

speechd-supertonic is licensed under the [Apache License 2.0](LICENSE).

It downloads and uses, but doesn't include:

- the [supertonic](https://github.com/supertone-inc/supertonic-py) Python
  package (MIT), and
- the [Supertonic model](https://huggingface.co/Supertone/supertonic-3), released
  under the BigScience **OpenRAIL-M** license, which restricts some uses. Read it
  before using the voices for anything beyond personal use.
