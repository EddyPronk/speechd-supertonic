# Testing speech timing (Supertonic in Firefox)

How to measure what you hear when Firefox Reader View reads a page through
speech-dispatcher and `supertonic_server.py`, what was measured so far, and the
experiments still to run. Setup and log format are described in
[how-it-works.md](how-it-works.md).

## How to measure

1. Open the article in Reader View, pick a voice for the page language in the
   Narrate menu (e.g. "Dutch (nl-x-f1)" = F1-nl, see the README), press play.
2. Afterwards (or while it plays):

   ```
   ~/.local/share/speechd-supertonic/speechd_timing.py
   ```

   It summarizes the latest server run from `~/.cache/speechd_supertonic.log`,
   one row per utterance:

   | Column | Meaning |
   |--------|---------|
   | `sent` | sentences (chunks) in the utterance |
   | `1st synth` | synthesis time of the first chunk |
   | `silence` | previous `playback finished` → first audio of this one: the pause between paragraphs |
   | `min ahead` | smallest "ready Ns before needed" of the later chunks; positive = no gap inside the paragraph |
   | `end err` | actual `playback finished` minus the predicted end; near 0 = no unexpected gaps |
   | `LATE [..]` | audible gaps inside the paragraph (should never appear) |

   The `text` column shows the text only if the server runs with `--debug`
   (`./install.sh --debug`); otherwise "(N chars, text not logged)". Timing
   works either way.

   Footer: min/median/max silence between utterances (pauses over 30s, i.e.
   pausing in Firefox, are left out), average silence trimmed per chunk, and the
   number of LATE chunks.

3. Check the voice: `start` lines must show `lang=nl` for a Dutch page
   (`voice=F1 lang=nl (speechd voice=F1-nl ...)`). `lang=en` means an English
   or "Default" voice is selected in Firefox.

To test without disturbing playback (no sound, synthesis times only):

```
printf %s 'One sentence. Another sentence.' | ~/.local/share/speechd-supertonic/supertonic_say.py --voice F1-en > /dev/null
```

The `ready`/`LATE` numbers are still valid that way; the "silence since previous
audio" figure is not, because nothing actually plays.

Restart the server only when nothing is playing, or the current paragraph is cut
off (`pgrep -x`, not `pgrep -f`, which matches its own command line):

```
until ! pgrep -x pw-play >/dev/null; do sleep 0.5; done; systemctl --user restart supertonic-tts.service
```

## Results so far (2026-10-06, Dutch article on writteninmusic.com, voice F1-nl)

Measured over 21 utterances: the end of the article, the setlist, then the top
of the page again.

- **No gaps inside paragraphs:** 0 LATE chunks; each next sentence was ready at
  least 5.3s before it was needed.
- **Predicted vs actual end** within 0.07s for every utterance, so the silence
  figures are what was heard.
- **Padding:** Supertonic adds silence to every chunk; trimmed on average 0.41s
  in front and 0.53s behind.
- **Pauses:** 0.45s between sentences (inserted), and between utterances:

  | Utterance | Example | Silence |
  |-----------|---------|---------|
  | short items (setlist) | "Thin Places", "Brasil" | 0.58–1.1s |
  | header items | title, byline, "6–8 minutes" | 0.7–1.6s |
  | paragraphs with a long first sentence | an opening sentence of 20–25 words | 2.5–3.9s |

  Median over all utterances: 0.86s.

The remaining pauses are all synthesis time of an utterance's first sentence
(about 26–30% of its spoken length). They can't be prefetched, because Firefox
sends the next paragraph only after the previous one has finished playing.

## How we got here

| Problem heard | Cause (found in logs) | Fix |
|---------------|------------------------|-----|
| Robotic "Atari SAM" voice | Supertonic module had crashed and speech-dispatcher fell back to espeak-ng; also an eSpeak "anikaRobot" voice pinned in Firefox | Restart daemon, pick a Supertonic voice |
| ~3s before every sentence | Model loaded per utterance | `supertonic_server.py` keeps it loaded |
| Pause after every sentence | sd_generic split paragraphs into sentences and waited for each one to finish playing before synthesizing the next | `GenericMaxChunkLength 100000`, `GenericDelimiters ""`; the server splits and synthesizes ahead |
| Gaps inside long paragraphs (paragraphs ended 0.6–3.7s late) | Socket write blocked until the player had nearly finished, so synthesis didn't run ahead | Separate sender thread |
| Dutch read with English pronunciation | Firefox picks by voice name only; plain `M2` resolved to the English entry | Voice names `M2-nl`; server takes language from the name |
| All voices listed as "Dutch (nl)" | Firefox labels Linux voices by language tag only | Unique tags `nl-x-m2` |
| 1.4s pause at a comma | Tried splitting the first sentence at a comma to start sooner; Supertonic's padding (~0.6s each side) made the cut obvious, and the intonation broke | Dropped: one sentence per call |
| ~1.5s between sentences | The same padding | Trim each chunk to its audible part (0.04s margin), insert 0.45s |

## To test later

### 1. Fewer quality steps for a paragraph's first sentence

Goal: shorten the 2.5–3.9s pause before paragraphs that open with a long
sentence, without splitting sentences. With 4 steps instead of 8, the first
sentence should synthesize in about half the time (roughly 1.3–2s instead of
2.5–3.9s). Only that sentence uses fewer steps; the rest of the paragraph stays
at 8.

The server has an option for it (default 8, i.e. off):

```
systemctl --user edit supertonic-tts.service
```

and add:

```
[Service]
ExecStart=
ExecStart=%h/.local/bin/uv run --script %h/.local/share/speechd-supertonic/supertonic_server.py --first-steps 4
```

Copy the `uv` path from the existing `ExecStart` line
(`systemctl --user cat supertonic-tts.service`) if yours isn't in `~/.local/bin`.
Then restart it (when nothing is playing). The log's first line confirms it:
`quality steps: 8, first chunk of a paragraph: 4`.

What to check:

- **By ear:** does the first sentence of each paragraph sound worse than the
  rest (rougher, slurred, odd intonation)? Try 4, and 5 or 6 if 4 is too rough.
- **In `speechd_timing.py`:** `1st synth` and `silence` for long paragraphs,
  compared with the table above (2.5–3.9s). `min ahead` must stay positive: the
  second sentence still synthesizes at 8 steps while the shorter first one plays.

To undo: `systemctl --user revert supertonic-tts.service`, then restart.

### 2. Pause lengths

`SILENCE_SECONDS = 0.45` (between sentences) and `TRIM_MARGIN = 0.04` in
`supertonic_server.py` (in the repo; rerun `./install.sh` to install it) were chosen from measurements, not by ear. If sentences
run together or feel too far apart, adjust and restart. For comparison, a comma
inside a sentence was measured at about 0.34s.

### 3. Things not tested yet

- An English page with an `en-x-…` voice.
- Narrate's speed slider (rate is mapped to Supertonic speed 0.7–2.0).
- Skip forward/back in Narrate while a long paragraph is still synthesizing
  (log should show `stopped by client`, and the next paragraph should start
  within one sentence's synthesis time).
- Mixed-language text: Firefox's own English strings ("6–8 minutes") are read
  with the Dutch voice because Narrate uses one voice per page.
