# Claude Code speaks its replies

A [Claude Code](https://code.claude.com/docs/en/hooks) hook script, `speak.py`,
that reads Claude's replies and notifications aloud with a Supertonic voice.
Needs speechd-supertonic installed (`spd-say -o supertonic -y F1-en "Hello"`
should speak).

## Set up

1. Copy the script:

   ```
   mkdir -p ~/.claude/hooks
   cp examples/claude-code/speak.py ~/.claude/hooks/speak.py
   chmod +x ~/.claude/hooks/speak.py
   ```

2. Add the hooks to `~/.claude/settings.json` (for all projects; use a project's
   `.claude/settings.json` to limit it to one). Merge with what's already there:

   ```json
   {
     "hooks": {
       "Stop": [
         { "hooks": [ { "type": "command", "command": "~/.claude/hooks/speak.py", "async": true, "timeout": 15 } ] }
       ],
       "Notification": [
         { "hooks": [ { "type": "command", "command": "~/.claude/hooks/speak.py", "async": true, "timeout": 15 } ] }
       ]
     }
   }
   ```

   `"async": true` lets Claude Code carry on without waiting for the hook.

3. Open `/hooks` in Claude Code once (or restart it) so it picks up the change.

## How it works

Three parts are involved. Only the middle one is this script; the others are how
Claude Code and speech-dispatcher behave, which the script relies on.

### 1. Claude Code: when the hook runs

From the [hooks documentation](https://code.claude.com/docs/en/hooks):

- **Stop** runs when Claude finishes a turn. Its JSON input includes
  `last_assistant_message`, the final reply text.
- **Notification** runs when Claude Code sends a notification. Its input includes
  `message` and `notification_type`, for example `permission_prompt`,
  `idle_prompt` ("Claude is waiting for your input"), `auth_success`,
  `agent_completed` or one of the `quota_auto_resume_*` types.

Observed, not documented: the `idle_prompt` notification came 60 seconds after
a reply finished (seen once, Claude Code on Linux, October 2026).

### 2. This script: what it says, and how

Everything here is a choice made in `speak.py`, covered by
`tests/test_claude_hook.py`.

**Which text.** For Stop, `last_assistant_message`. If it is missing (older
Claude Code versions), the text of the last assistant message in the session
transcript (`transcript_path`) instead. For Notification, `message` as it is.

Only a turn's final message is spoken. Short remarks Claude makes between tool
calls during a turn ("I'll check the log first") are not, because Stop runs once,
at the end of the turn, and gets only the final text. Verified on this setup: a
turn with a remark before its tool calls was spoken from its final summary only.

**Reply text is rewritten for listening**, because Markdown read aloud is noise:

- code blocks and tables are left out;
- headings, list markers, emphasis (`**bold**`, `_italic_`), inline-code
  backticks and link targets are removed, keeping the words;
- bare URLs become "a link";
- list items and paragraphs end with a full stop, so the voice pauses between them.

**Length cap.** A reply longer than `SPEAK_MAX_CHARS` (default 1500) characters
is cut at the last sentence end before the limit, followed by "The rest is on
screen." Reasoning: a long reply takes minutes to hear and is easier to read.

**Priority per event**, which decides what happens when speech overlaps (see 3):

| Hook input | Priority | Why |
|------------|----------|-----|
| Stop (a reply) | `text` | A newer reply makes an older one that is still playing stale |
| Notification with `notification_type` `idle_prompt` | `notification` | Only useful when nothing else is being said |
| Any other notification | `message` | Usually needs you (e.g. a permission prompt), so it is spoken even over a reply |

The first version sent everything at speech-dispatcher's default, `text`. The
idle notification then replaced a long reply 60 seconds in, cutting off its last
third. With `notification` it is dropped instead: tested by sending it 3 seconds
into a reply, which then played to the end.

If `notification_type` is missing, a message containing "waiting for your input"
is treated as the idle notification.

**No waiting.** The script hands the text to `spd-say`, which returns once
speech-dispatcher has queued it.

**Never in the way.** Input that isn't a JSON object, or a reply with nothing
left to say (only code, say), is ignored without output or error.

### 3. speech-dispatcher: overlapping speech

From speech-dispatcher's manual (*Message priorities*), for the three
priorities used here:

- `text` interrupts itself: a new `text` message cancels the one playing.
- `message` is not interrupted by `text`, and cancels `text` messages that are
  playing or waiting.
- `notification` is cancelled if anything else is playing or waiting.

Firefox's Read aloud also uses `text`, so by these rules a reply and Firefox
narration interrupt each other (not tested).

## Settings

Set these under `"env"` in `settings.json`:

| Variable | Default | Meaning |
|----------|---------|---------|
| `SPEAK_VOICE` | `F1-en` | Any voice from `spd-say -o supertonic -L`, e.g. `M2-en` |
| `SPEAK_MAX_CHARS` | `1500` | Length cap for replies |
| `SPEAK_DISABLE` | unset | `1` mutes without removing the hooks |

To see the `spd-say` command the script would run, without speaking:

```
echo '{"hook_event_name":"Notification","message":"Test"}' | SPEAK_DRY_RUN=1 ~/.claude/hooks/speak.py
```
