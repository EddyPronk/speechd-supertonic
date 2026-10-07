#!/usr/bin/python3
"""Claude Code hook: speak replies and notifications through speech-dispatcher.

Used from ~/.claude/settings.json for the Stop and Notification events (see
README.md next to this file). Reads the hook's JSON input on stdin and hands the
text to `spd-say` (Supertonic voice F1-en from speechd-supertonic) without
waiting for playback.

Stop: the last assistant reply, as plain speech: code blocks and tables are left
out, Markdown markup is removed, and long replies are cut after about
SPEAK_MAX_CHARS characters (default 1500) at a sentence end.
Notification: the notification message.

speech-dispatcher priorities decide what happens when speech overlaps:
- replies use "text": a newer reply replaces one that is still playing;
- the idle "waiting for your input" notification uses "notification": it is
  dropped while anything else is playing (otherwise it cut off long replies);
- other notifications (e.g. a permission request) use "message": they are spoken
  even while a reply is playing, which they interrupt.

Environment: SPEAK_VOICE (default F1-en), SPEAK_MAX_CHARS, SPEAK_DISABLE=1 to
mute, SPEAK_DRY_RUN=1 to print the spd-say command instead of running it.
Standard library only.
"""

import json
import os
import re
import subprocess
import sys


def last_reply_from_transcript(path):
    """Text of the last assistant message with text content in the JSONL transcript."""
    last = None
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(entry, dict) or entry.get("type") != "assistant":
                    continue
                content = (entry.get("message") or {}).get("content")
                if isinstance(content, str):
                    texts = [content]
                else:
                    texts = [c.get("text", "") for c in content or []
                             if isinstance(c, dict) and c.get("type") == "text"]
                text = "\n".join(t for t in texts if t.strip())
                if text:
                    last = text
    except OSError:
        return None
    return last


def to_speech(text, max_chars=1500):
    """Markdown to something pleasant to listen to."""
    text = re.sub(r"```.*?```", " ", text, flags=re.S)           # code blocks
    lines = []
    for line in text.splitlines():
        if line.lstrip().startswith("|"):                         # tables
            continue
        line = re.sub(r"^\s{0,3}#{1,6}\s*", "", line)             # headings
        line, is_item = re.subn(r"^\s*(?:[-*+]|\d+[.)])\s+", "", line)  # list markers
        if is_item and line.strip() and not re.search(r"[.!?:;,]\W*$", line):
            line += "."                                           # pause between items
        lines.append(line)
    text = "\n".join(lines)
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)        # links, images
    text = re.sub(r"`([^`]*)`", r"\1", text)                      # inline code
    text = re.sub(r"(\*\*|__|\*|_)(\S(?:.*?\S)?)\1", r"\2", text)  # emphasis
    text = re.sub(r"https?://\S+", "a link", text)
    text = re.sub(r"\s*\n\s*\n\s*", ". ", text)                   # paragraphs
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"([.!?:])\.\s", r"\1 ", text)                 # ". " after punctuation
    if len(text) > max_chars:
        cut = text.rfind(". ", 0, max_chars)
        text = text[:cut + 1 if cut > max_chars // 2 else max_chars] + " The rest is on screen."
    return text


def is_idle_notification(data):
    kind = data.get("notification_type", "")
    return kind == "idle_prompt" or "waiting for your input" in data.get("message", "").lower()


def build_command(data, env=os.environ):
    """The spd-say command for this hook input, or None if there's nothing to say."""
    if env.get("SPEAK_DISABLE") == "1":
        return None
    voice = env.get("SPEAK_VOICE", "F1-en")
    if data.get("hook_event_name") == "Notification":
        text = data.get("message", "")
        priority = "notification" if is_idle_notification(data) else "message"
    else:
        text = data.get("last_assistant_message") or ""
        if not text and data.get("transcript_path"):
            text = last_reply_from_transcript(data["transcript_path"]) or ""
        text = to_speech(text, int(env.get("SPEAK_MAX_CHARS", "1500")))
        priority = "text"
    if not text.strip():
        return None
    return ["spd-say", "-o", "supertonic", "-y", voice, "-P", priority, "--", text]


def main():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return
    if not isinstance(data, dict):
        return
    cmd = build_command(data)
    if cmd is None:
        return
    if os.environ.get("SPEAK_DRY_RUN") == "1":
        print(json.dumps(cmd))
        return
    # spd-say returns once the text is queued; speech-dispatcher plays it.
    subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL, timeout=10, check=False)


if __name__ == "__main__":
    main()
