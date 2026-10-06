#!/usr/bin/python3
"""Timing summary of the latest supertonic_server.py run, from its log.

    speechd_timing.py [~/.cache/speechd_supertonic.log]

One row per utterance (paragraph):
  sent       sentences (chunks) in it
  1st synth  synthesis time of the first chunk
  silence    previous `playback finished` -> this utterance's first audio sent
             (what the listener hears as a pause between paragraphs)
  min ahead  smallest "ready Ns before needed" of the later chunks
             (no gap inside the paragraph while this is positive)
  end err    `playback finished` minus the server's predicted end
             (near 0 = no unexpected gaps or player delays)
Flags: LATE [s] = audible gaps inside the paragraph, STOPPED = stopped/skipped.
"""
import os
import re, sys
from datetime import datetime
path = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/.cache/speechd_supertonic.log")
lines = open(path, encoding="utf-8").read().splitlines()
lines = lines[max(i for i, l in enumerate(lines) if "model loaded" in l):]
ts = lambda l: datetime.strptime(l[:23], "%Y-%m-%d %H:%M:%S,%f")
reqs, last = [], None
for l in lines:
    # text='...' with the server's --debug, otherwise text=<N chars>
    m = re.search(r"\[(\d+)\] start .*?text=(?:(['\"])(.*)\2|<(\d+) chars>)$", l)
    if m:
        text = m[3] if m[3] is not None else f"({m[4]} chars, text not logged)"
        chars = len(m[3]) if m[3] is not None else int(m[4])
        reqs.append(dict(id=int(m[1]), text=text, chars=chars, prev=last, n=0, late=[], ahead=[], trims=[], stopped=False))
        continue
    if "playback finished" in l:
        last = ts(l)
        if reqs: reqs[-1]["fin"] = last
        continue
    if not reqs: continue
    r = reqs[-1]
    m = re.search(r"chunk (\d+)/(\d+) synthesized in ([\d.]+)s \(([\d.]+)s audio after trimming ([\d.]+)s\+([\d.]+)s", l)
    if m:
        r["n"] = int(m[2]); r["trims"].append((float(m[5]), float(m[6])))
        if m[1] == "1": r["first"] = ts(l); r["synth1"] = float(m[3])
        mm = re.search(r"LATE by ([\d.]+)", l)
        if mm: r["late"].append(float(mm[1]))
        mm = re.search(r"ready ([\d.]+)s", l)
        if mm: r["ahead"].append(float(mm[1]))
    if "should end in" in l:
        r["est_end"] = ts(l).timestamp() + float(re.search(r"end in ~([\d.]+)s", l)[1])
    if "stopped by client" in l: r["stopped"] = True
print(f"{'req':>4} {'chars':>5} {'sent':>4} {'1st synth':>9} {'silence':>8} {'min ahead':>9} {'end err':>8}  text")
gaps = []
for r in reqs:
    sil = (r["first"] - r["prev"]).total_seconds() if r.get("first") and r["prev"] else None
    if sil is not None and sil < 30: gaps.append(sil)
    err = (r["fin"].timestamp() - r["est_end"]) if r.get("fin") and r.get("est_end") else None
    sil_s = f"{sil:.2f}s" if sil is not None else "-"
    ahead_s = f"{min(r['ahead']):.1f}s" if r["ahead"] else "-"
    err_s = f"{err:+.2f}s" if err is not None else "-"
    flags = ("STOPPED " if r["stopped"] else "") + (f"LATE {r['late']} " if r["late"] else "")
    print(f"{r['id']:>4} {r['chars']:>5} {r['n']:>4} {r.get('synth1', 0):>8.2f}s {sil_s:>8} {ahead_s:>9} {err_s:>8}  {flags}{r['text'][:50]}")
t = [x for r in reqs for x in r["trims"]]
if gaps:
    g = sorted(gaps)
    print(f"\nsilence between utterances: min {g[0]:.2f}s  median {g[len(g)//2]:.2f}s  max {g[-1]:.2f}s  (n={len(g)})")
if t: print(f"trimmed per chunk: lead avg {sum(a for a,_ in t)/len(t):.2f}s, trail avg {sum(b for _,b in t)/len(t):.2f}s")
print("LATE chunks:", sum(len(r["late"]) for r in reqs))
