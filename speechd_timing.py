#!/usr/bin/python3
"""Timing summary of the latest supertonic_server.py run, from its log.

    speechd_timing.py [~/.cache/speechd_supertonic.log]

One row per utterance (paragraph). All times come from log timestamps, so they
are estimates of what the listener heard, not measurements at the speaker:

  sent        sentences (chunks) in the utterance
  1st synth   synthesis time of the first chunk
  est. gap    previous "playback finished" -> first audio of this utterance sent
              to the client. Player startup and buffering make the audible
              pause somewhat longer.
  min ahead   smallest "ready Ns before needed" of the later chunks: positive
              means no gap inside the paragraph, assuming playback started when
              the first audio was sent.
  end vs est  "playback finished" (when the player exited) minus the server's
              predicted end. Near 0 means no unpredicted gaps.
Flags: LATE [s] = predicted gaps inside the paragraph, STOPPED = stopped/skipped.
"""
import os
import re
import sys
from datetime import datetime

LOG = os.path.expanduser("~/.cache/speechd_supertonic.log")
IGNORE_GAPS_OVER = 30.0  # seconds; longer means paused in the browser, not a gap

START = re.compile(r"\[(\d+)\] start .*?text=(?:(['\"])(.*)\2|<(\d+) chars>)$")
CHUNK = re.compile(r"\[(\d+)\] chunk (\d+)/(\d+) synthesized in ([\d.]+)s "
                   r"\(([\d.]+)s audio(?: after trimming ([\d.]+)s\+([\d.]+)s silence)?")
DONE = re.compile(r"\[(\d+)\] synthesis done: .*audio should end in ~([\d.]+)s")


def timestamp(line):
    try:
        return datetime.strptime(line[:23], "%Y-%m-%d %H:%M:%S,%f")
    except ValueError:
        return None


def latest_run(lines):
    """Lines since the last server start ("model loaded"), or all lines if none."""
    starts = [i for i, line in enumerate(lines) if "model loaded" in line]
    return lines[starts[-1]:] if starts else lines


def parse(lines):
    """Turn log lines into one dict per utterance. Unknown or malformed lines are skipped."""
    reqs, last_finish = [], None
    for line in latest_run(lines):
        ts = timestamp(line)
        if ts is None:
            continue  # tracebacks, client error messages, ...
        if m := START.search(line):
            if m[3] is not None:  # server ran with --debug
                text, chars = m[3], len(m[3])
            else:
                chars = int(m[4])
                text = f"({chars} chars, text not logged)"
            reqs.append(dict(id=int(m[1]), text=text, chars=chars, prev_finish=last_finish,
                             chunks=0, first=None, synth1=None, late=[], ahead=[], trims=[],
                             est_end=None, finish=None, stopped=False))
            continue
        if "playback finished" in line:
            last_finish = ts
            r = reqs[-1] if reqs else None
            # Belongs to the latest utterance, unless that one never played (e.g.
            # a test with --output -) and this line comes from much later.
            if r and r["finish"] is None and (
                    r["est_end"] is None or ts.timestamp() - r["est_end"] < IGNORE_GAPS_OVER):
                r["finish"] = ts
            continue
        if not reqs:
            continue
        r = reqs[-1]
        if (m := CHUNK.search(line)) and int(m[1]) == r["id"]:
            r["chunks"] = int(m[3])
            if m[6] is not None:
                r["trims"].append((float(m[6]), float(m[7])))
            if m[2] == "1":
                r["first"], r["synth1"] = ts, float(m[4])
            if late := re.search(r"LATE by ([\d.]+)", line):
                r["late"].append(float(late[1]))
            if ahead := re.search(r"ready ([\d.]+)s before needed", line):
                r["ahead"].append(float(ahead[1]))
        elif (m := DONE.search(line)) and int(m[1]) == r["id"]:
            r["est_end"] = ts.timestamp() + float(m[2])
        elif f"[{r['id']}] stopped by client" in line:
            r["stopped"] = True
    return reqs


def gap(r):
    if r["first"] is None or r["prev_finish"] is None:
        return None
    return (r["first"] - r["prev_finish"]).total_seconds()


def report(reqs, out=sys.stdout):
    if not reqs:
        print("No utterances in this log (yet).", file=out)
        return
    print(f"{'req':>4} {'chars':>5} {'sent':>4} {'1st synth':>9} {'est. gap':>8} "
          f"{'min ahead':>9} {'end vs est':>10}  text", file=out)
    for r in reqs:
        g = gap(r)
        end = r["finish"].timestamp() - r["est_end"] if r["finish"] and r["est_end"] else None
        flags = ("STOPPED " if r["stopped"] else "") + (f"LATE {r['late']} " if r["late"] else "")
        synth = f"{r['synth1']:.2f}s" if r["synth1"] is not None else "-"
        gap_s = f"{g:.2f}s" if g is not None else "-"
        ahead = f"{min(r['ahead']):.1f}s" if r["ahead"] else "-"
        end_s = f"{end:+.2f}s" if end is not None else "-"
        print(f"{r['id']:>4} {r['chars']:>5} {r['chunks']:>4} {synth:>9} {gap_s:>8} {ahead:>9} "
              f"{end_s:>10}  {flags}{r['text'][:50]}", file=out)

    gaps = sorted(g for r in reqs if (g := gap(r)) is not None and g < IGNORE_GAPS_OVER)
    if gaps:
        print(f"\nest. gap between utterances: min {gaps[0]:.2f}s  median {gaps[len(gaps) // 2]:.2f}s"
              f"  max {gaps[-1]:.2f}s  (n={len(gaps)}; pauses over {IGNORE_GAPS_OVER:.0f}s left out)",
              file=out)
    trims = [t for r in reqs for t in r["trims"]]
    if trims:
        print(f"trimmed per chunk: lead avg {sum(a for a, _ in trims) / len(trims):.2f}s, "
              f"trail avg {sum(b for _, b in trims) / len(trims):.2f}s", file=out)
    print("LATE chunks:", sum(len(r["late"]) for r in reqs), file=out)


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else LOG
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except OSError as e:
        sys.exit(f"speechd_timing: {e}")
    report(parse(lines))


if __name__ == "__main__":
    main()
