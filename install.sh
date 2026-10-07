#!/usr/bin/env bash
# Install (or uninstall) speechd-supertonic for the current user.
#
#   ./install.sh                          # voices for English + your locale's language
#   ./install.sh --languages "en nl de"   # choose the voice languages
#   ./install.sh --no-default             # don't make Supertonic speech-dispatcher's default
#   ./install.sh --debug                  # also log the text being read (default: length only)
#   ./install.sh --uninstall
#
# Everything goes into your home directory; no root needed. See README.md.
set -euo pipefail

NAME=speechd-supertonic
SRC=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
CONFIG=${XDG_CONFIG_HOME:-$HOME/.config}
APPDIR=${XDG_DATA_HOME:-$HOME/.local/share}/$NAME
LOG=${XDG_CACHE_HOME:-$HOME/.cache}/speechd_supertonic.log
SPEECHD=$CONFIG/speech-dispatcher
UNITS=$CONFIG/systemd/user
# Overridable for tests and unusual layouts:
SYSTEM_SPEECHD_CONF=${SPEECHD_SYSTEM_CONF:-/etc/speech-dispatcher/speechd.conf}
MODULE_DIR_CANDIDATES=(/usr/lib/speech-dispatcher-modules /usr/lib/x86_64-linux-gnu/speech-dispatcher-modules
                       /usr/lib/aarch64-linux-gnu/speech-dispatcher-modules /usr/lib64/speech-dispatcher-modules
                       /usr/libexec/speech-dispatcher-modules)
[ -n "${SPEECHD_MODULES_DIR:-}" ] && MODULE_DIR_CANDIDATES=("$SPEECHD_MODULES_DIR")
BEGIN="# >>> $NAME (added by install.sh; removed by install.sh --uninstall)"
END="# <<< $NAME"
# Languages the Supertonic model supports (supertonic.AVAILABLE_LANGUAGES minus "na").
SUPPORTED="en ko ja ar bg cs da de el es et fi fr hi hr hu id it lt lv nl pl pt ro ru sk sl sv tr uk vi"

if [ -t 1 ]; then BOLD=$'\033[1m' YELLOW=$'\033[33m' RED=$'\033[31m' RESET=$'\033[0m'
else BOLD="" YELLOW="" RED="" RESET=""; fi
say() { printf '%s==>%s %s\n' "$BOLD" "$RESET" "$*"; }
warn() { printf '%swarning:%s %s\n' "$YELLOW" "$RESET" "$*" >&2; }
die() { printf '%serror:%s %s\n' "$RED" "$RESET" "$*" >&2; exit 1; }

# Speech-dispatcher picks up config changes when it restarts; it is started on
# demand, so stopping it is enough. (Process names are cut to 15 characters.)
restart_speechd() { pkill -u "$(id -u)" -x speech-dispatch 2>/dev/null || true; }

# Paths end up inside a shell command (single-quoted) and a systemd unit
# (double-quoted, % is special), so refuse the few characters that can't be
# quoted safely there.
check_path() {
    case $2 in
        *[\'\"\\%$'\n']*) die "$1 contains a quote, backslash, % or newline, which isn't supported: $2" ;;
    esac
}

# Replace @NAME@ placeholders without sed: values are inserted literally
# (quoting the replacement keeps bash 5.2's patsub_replacement from treating & specially).
fill() {
    local text=$1
    text=${text//@SAY@/"$APPDIR/supertonic_say.py"}
    text=${text//@APPDIR@/"$APPDIR"}
    text=${text//@LOG@/"$LOG"}
    text=${text//@UV@/"$UV"}
    text=${text//@SERVER_ARGS@/"$SERVER_ARGS"}
    printf '%s\n' "$text"
}

# Remove our marked block from speechd.conf, if any.
remove_block() {
    [ -f "$1" ] || return 0
    sed -i "\|^$BEGIN\$|,\|^$END\$|d" "$1"
}

uninstall() {
    say "Stopping and removing the systemd units"
    systemctl --user disable --now supertonic-tts.socket 2>/dev/null || true
    systemctl --user stop supertonic-tts.service 2>/dev/null || true
    rm -f "$UNITS/supertonic-tts.socket" "$UNITS/supertonic-tts.service"
    systemctl --user daemon-reload

    say "Removing the speech-dispatcher module"
    rm -f "$SPEECHD/modules/supertonic.conf"
    remove_block "$SPEECHD/speechd.conf"
    # If install.sh created speechd.conf from the system copy, remove it again.
    if [ -f "$SPEECHD/.$NAME-created-speechd.conf" ]; then
        if cmp -s "$SPEECHD/speechd.conf" "$SYSTEM_SPEECHD_CONF"; then
            rm -f "$SPEECHD/speechd.conf"
        else
            warn "kept $SPEECHD/speechd.conf: it was changed after install"
        fi
        rm -f "$SPEECHD/.$NAME-created-speechd.conf"
    fi
    restart_speechd

    say "Removing $APPDIR"
    rm -rf "$APPDIR"

    say "Done. Left in place: the log ($LOG) and the downloaded model (~/.cache/supertonic3)."
    echo "Restart Firefox so it drops the Supertonic voices."
}

# --- arguments ---------------------------------------------------------------

LANGUAGES=""
SET_DEFAULT=1
SERVER_ARGS=""
while [ $# -gt 0 ]; do
    case $1 in
        --uninstall) uninstall; exit 0 ;;
        --languages) LANGUAGES=${2:?--languages needs a value, e.g. \"en nl\"}; shift ;;
        --no-default) SET_DEFAULT=0 ;;
        --debug) SERVER_ARGS=" --debug" ;;
        -h|--help) sed -n '2,10s/^# \{0,1\}//p' "$0"; exit 0 ;;
        *) die "unknown option: $1 (see --help)" ;;
    esac
    shift
done

if [ -z "$LANGUAGES" ]; then
    # English plus the language of your locale, if Supertonic supports it.
    LANGUAGES=en
    loc=${LC_ALL:-${LC_MESSAGES:-${LANG:-}}}
    loc=${loc%%[_.@]*}
    case " $SUPPORTED " in *" $loc "*) [ "$loc" != en ] && LANGUAGES="en $loc" ;; esac
fi
for lang in $LANGUAGES; do
    case " $SUPPORTED " in *" $lang "*) ;; *) die "unsupported language: $lang (supported: $SUPPORTED)" ;; esac
done

# --- requirements ------------------------------------------------------------

UV=$(command -v uv) || die "uv not found; install it: https://docs.astral.sh/uv/getting-started/installation/"
command -v pw-play >/dev/null || die "pw-play not found (PipeWire); on Debian/Ubuntu: sudo apt install pipewire-bin"
command -v python3 >/dev/null || die "python3 not found"
command -v speech-dispatcher >/dev/null || die "speech-dispatcher not found; on Debian/Ubuntu: sudo apt install speech-dispatcher"
MODULES_DIR=""
for dir in "${MODULE_DIR_CANDIDATES[@]}"; do
    if [ -x "$dir/sd_generic" ]; then MODULES_DIR=$dir; break; fi
done
[ -n "$MODULES_DIR" ] || die "speech-dispatcher's sd_generic module not found in: ${MODULE_DIR_CANDIDATES[*]} (set SPEECHD_MODULES_DIR)"
command -v systemctl >/dev/null && systemctl --user show-environment >/dev/null 2>&1 \
    || die "needs a systemd user session (systemctl --user)"

check_path "install directory" "$APPDIR"
check_path "log file" "$LOG"
check_path "uv" "$UV"

if [ -f "$SPEECHD/speechd.conf" ] && sed "\|^$BEGIN\$|,\|^$END\$|d" "$SPEECHD/speechd.conf" \
        | grep -q '^[[:space:]]*AddModule[[:space:]]*"supertonic"'; then
    die "$SPEECHD/speechd.conf already has an AddModule \"supertonic\" line (a manual setup?); remove it and rerun"
fi

# --- files -------------------------------------------------------------------

say "Installing the server and client to $APPDIR"
mkdir -p "$APPDIR"
# The module command appends to the log; a missing directory would make every
# utterance fail (and speech-dispatcher then gives up on the module).
mkdir -p "$(dirname "$LOG")"
install -m 755 "$SRC/supertonic_server.py" "$SRC/supertonic_say.py" "$SRC/speechd_timing.py" "$APPDIR/"

say "Writing the speech-dispatcher module ($SPEECHD/modules/supertonic.conf, voices: $LANGUAGES)"
mkdir -p "$SPEECHD/modules"
first_lang=${LANGUAGES%% *}
module_conf=$(
    cat <<'EOF'
# speech-dispatcher module for Supertonic TTS, written by speechd-supertonic's
# install.sh (rerun it to change the voice languages). See docs/how-it-works.md.
#
# Per utterance, sd_generic runs supertonic_say.py: it asks the Supertonic server
# (supertonic-tts.service, model stays loaded) for audio and plays it with
# pw-play. It is a single command, so its exit status is the command's: non-zero
# if the server can't be reached or playback fails. Its stderr (errors, and a
# "playback finished" line) goes to the log.
#
# $DATA is single-quoted on purpose: sd_generic escapes single quotes in the
# text, so web pages can't inject shell commands.
GenericExecuteSynth "printf %s \'$DATA\' | \'@SAY@\' --voice \'$VOICE\' --lang \'$LANGUAGE\' --rate $RATE --volume $VOLUME 2>>\'@LOG@\'"
GenericCmdDependency "pw-play"

# Pass speech-dispatcher's raw -100..100 values; the server maps them.
GenericRateAdd 0
GenericRateMultiply 1
GenericRateForceInteger 1
GenericVolumeAdd 0
GenericVolumeMultiply 1
GenericVolumeForceInteger 1

# Send whole paragraphs, not sentences: the server splits them itself and
# synthesizes the next sentence while the current one plays. With sentence
# splitting here, every sentence waits for its own synthesis (audible pause).
GenericMaxChunkLength 100000
GenericDelimiters ""

# Without these sd_generic recodes text to iso-8859-1 and curly quotes, dashes,
# emoji etc. arrive as "?". One line per language tag used below.
EOF
    for lang in $LANGUAGES; do
        echo "GenericLanguage \"$lang\" \"$lang\" \"utf-8\""
        for g in f m; do for n in 1 2 3 4 5; do
            echo "GenericLanguage \"$lang-x-$g$n\" \"$lang\" \"utf-8\""
        done; done
    done
    cat <<'EOF'

# Firefox picks a voice by name only, so names are unique per language ("M2-nl";
# the server reads the language from the suffix). The language tags are unique
# too ("nl-x-m2") because Firefox's voice menu on Linux shows only the tag:
# "Dutch (nl-x-m2)" is voice M2 in Dutch.
EOF
    for lang in $LANGUAGES; do
        for n in 1 2 3 4 5; do echo "AddVoice \"$lang-x-f$n\" \"FEMALE$n\" \"F$n-$lang\""; done
        for n in 1 2 3 4 5; do echo "AddVoice \"$lang-x-m$n\" \"MALE$n\" \"M$n-$lang\""; done
    done
    echo
    echo "DefaultVoice \"F1-$first_lang\""
)
fill "$module_conf" > "$SPEECHD/modules/supertonic.conf"

say "Registering the module in $SPEECHD/speechd.conf"
conf=$SPEECHD/speechd.conf
if [ ! -f "$conf" ]; then
    # A user speechd.conf replaces the system one entirely, so start from a copy
    # of it to keep its defaults (log level, symbol dictionaries, client rules).
    if [ -f "$SYSTEM_SPEECHD_CONF" ]; then cp "$SYSTEM_SPEECHD_CONF" "$conf"; else : > "$conf"; fi
    touch "$SPEECHD/.$NAME-created-speechd.conf"
fi
remove_block "$conf"
{
    echo "$BEGIN"
    echo "# Listing any module turns off auto-detection, so the others must be listed too."
    echo 'AddModule "supertonic" "sd_generic" "supertonic.conf"'
    if [ -x "$MODULES_DIR/sd_espeak-ng" ] && ! grep -q '^[[:space:]]*AddModule[[:space:]]*"espeak-ng"' "$conf"; then
        echo 'AddModule "espeak-ng" "sd_espeak-ng" "espeak-ng.conf"'
    fi
    [ "$SET_DEFAULT" = 1 ] && echo 'DefaultModule supertonic'
    echo "$END"
} >> "$conf"

say "Installing the systemd user units (socket starts the server on first use)"
mkdir -p "$UNITS"
install -m 644 "$SRC/systemd/supertonic-tts.socket" "$UNITS/"
fill "$(cat "$SRC/systemd/supertonic-tts.service.in")" > "$UNITS/supertonic-tts.service"
systemctl --user daemon-reload
systemctl --user enable --now supertonic-tts.socket
# Pick up a new server version if it was already running.
systemctl --user try-restart supertonic-tts.service

restart_speechd

say "First request: downloads Python packages and the model (~400 MB) on first install"
if printf %s 'Test.' | "$APPDIR/supertonic_say.py" --voice "F1-$first_lang" --output - > /dev/null; then
    say "Server is working. Try:  spd-say -o supertonic -y F1-$first_lang \"Hello\""
else
    warn "the test request failed; see $LOG and: journalctl --user -u supertonic-tts.service"
fi

cat <<EOF

Next: set up Firefox (README.md, "Firefox"):
  1. Restart Firefox.
  2. Open an article in Reader View, click the headphones icon, and under Voice
     pick a Supertonic voice: they are listed as "<Language> (${first_lang}-x-f1)",
     where f1..f5 / m1..m5 are the voices F1..F5 / M1..M5.
EOF
