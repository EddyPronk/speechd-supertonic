#!/usr/bin/env bash
# Installer tests: run install.sh in temporary XDG directories with stub system
# commands, and check the generated files. Never touches the real configuration.
#
# Also runs the generated speech-dispatcher command the way sd_generic does
# (/bin/bash, "set -o pipefail ; ", $DATA with single quotes escaped) to check
# quoting and exit-status propagation.
set -uo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
FAILS=0
PASSES=0
ok()   { PASSES=$((PASSES + 1)); }
fail() { FAILS=$((FAILS + 1)); printf '  FAIL: %s\n' "$*"; }
check() { if eval "$2"; then ok; else fail "$1"; fi; }

# A fresh fake home with stubbed systemctl/pkill/uv/pw-play/speech-dispatcher.
setup() {
    T=$(mktemp -d)
    HOME_DIR=$T/${1:-home}
    mkdir -p "$HOME_DIR" "$T/bin" "$T/modules" "$T/run"
    chmod 700 "$T/run"
    for cmd in systemctl pkill uv pw-play speech-dispatcher; do
        printf '#!/bin/sh\necho "%s $*" >> "%s/calls"\n' "$cmd" "$T" > "$T/bin/$cmd"
    done
    printf '#!/bin/sh\n' > "$T/modules/sd_generic"
    printf '#!/bin/sh\n' > "$T/modules/sd_espeak-ng"
    chmod +x "$T/bin/"* "$T/modules/"*
    printf 'LogLevel 3\nSymbolsPreproc "char"\n# AddModule "espeak-ng" ...\n' > "$T/system-speechd.conf"
    CONF=$HOME_DIR/.config
    APP=$HOME_DIR/.local/share/speechd-supertonic
}

# MODULES_ENV can replace the default SPEECHD_MODULES_DIR override, e.g. to test the search.
run_install() {
    env -i PATH="$T/bin:/usr/bin:/bin" HOME="$HOME_DIR" LANG="${LANG_FOR_TEST:-C}" \
        XDG_RUNTIME_DIR="$T/run" ${MODULES_ENV:-SPEECHD_MODULES_DIR=$T/modules} \
        SPEECHD_SYSTEM_CONF="$T/system-speechd.conf" \
        bash "$ROOT/install.sh" "$@" > "$T/out" 2>&1
}

teardown() { rm -rf "$T"; }

echo "default install (Dutch locale)"
setup
LANG_FOR_TEST=nl_NL.UTF-8 run_install; rc=$?
check "exit 0 (got $rc): $(tail -3 "$T/out")" '[ $rc = 0 ]'
M=$CONF/speech-dispatcher/modules/supertonic.conf
check "module conf exists" '[ -f "$M" ]'
check "20 voices for en+nl" '[ "$(grep -c "^AddVoice" "$M")" = 20 ]'
check "nl voice line" 'grep -qx "AddVoice \"nl-x-m2\" \"MALE2\" \"M2-nl\"" "$M"'
check "voice 5 uses a valid voice type" 'grep -qx "AddVoice \"nl-x-f5\" \"FEMALE3\" \"F5-nl\"" "$M"'
check "only voice types speech-dispatcher accepts" '! grep "^AddVoice" "$M" | grep -vqE "^AddVoice \"[^\"]+\" \"(FEMALE[123]|MALE[123]|CHILD_FEMALE|CHILD_MALE)\" "'
check "utf-8 for every tag" '[ "$(grep -c "^GenericLanguage" "$M")" = 22 ]'
check "single command, no pw-play pipeline" '! grep "^GenericExecuteSynth" "$M" | grep -q "pw-play"'
check "client path quoted" 'grep -q "| \\\\'"'"'$APP/supertonic_say.py\\\\'"'"' " "$M"'
S=$CONF/speech-dispatcher/speechd.conf
check "speechd.conf starts from system copy" 'grep -qx "SymbolsPreproc \"char\"" "$S"'
check "one marked block" '[ "$(grep -c "^# >>> speechd-supertonic" "$S")" = 1 ]'
check "module + fallback + default" 'grep -qx "AddModule \"supertonic\" \"sd_generic\" \"supertonic.conf\"" "$S" && grep -qx "AddModule \"espeak-ng\" \"sd_espeak-ng\" \"espeak-ng.conf\"" "$S" && grep -qx "DefaultModule supertonic" "$S"'
U=$CONF/systemd/user
check "socket unit, private" 'grep -qx "SocketMode=0600" "$U/supertonic-tts.socket"'
check "service ExecStart quoted, no --debug" 'grep -qx "ExecStart=\"$T/bin/uv\" run --script \"$APP/supertonic_server.py\"" "$U/supertonic-tts.service"'
check "socket enabled" 'grep -q "systemctl --user enable --now supertonic-tts.socket" "$T/calls"'
check "warm-up failure is only a warning" 'grep -q "warning: the test request failed" "$T/out"'

echo "reinstall is idempotent, --debug and --languages"
run_install --debug --languages "en de"; rc=$?
check "exit 0" '[ $rc = 0 ]'
check "still one block" '[ "$(grep -c "^# >>> speechd-supertonic" "$S")" = 1 ]'
check "--debug in ExecStart" 'grep -q "supertonic_server.py\" --debug$" "$U/supertonic-tts.service"'
check "de voices, no nl" 'grep -q "^AddVoice.*\"M2-de\"" "$M" && ! grep -q "^AddVoice.*-nl\"" "$M"'

echo "uninstall removes everything (speechd.conf was created by the installer)"
run_install --uninstall; rc=$?
check "exit 0" '[ $rc = 0 ]'
check "no files left" '[ -z "$(find "$HOME_DIR" -type f)" ]'
teardown

echo "existing speechd.conf is kept and edited in place"
setup
mkdir -p "$HOME_DIR/.config/speech-dispatcher"
printf 'LogLevel 5\nAddModule "espeak-ng" "sd_espeak-ng" "espeak-ng.conf"\n' > "$HOME_DIR/.config/speech-dispatcher/speechd.conf"
run_install; rc=$?
S=$CONF/speech-dispatcher/speechd.conf
check "exit 0" '[ $rc = 0 ]'
check "custom line kept" 'grep -qx "LogLevel 5" "$S"'
check "espeak-ng not added twice" '[ "$(grep -c "AddModule \"espeak-ng\"" "$S")" = 1 ]'
run_install --uninstall
check "after uninstall: file kept, block gone" '[ -f "$S" ] && grep -qx "LogLevel 5" "$S" && ! grep -q supertonic "$S"'
teardown

echo "manual setup is refused before anything is written"
setup
mkdir -p "$HOME_DIR/.config/speech-dispatcher"
echo 'AddModule "supertonic" "sd_generic" "supertonic.conf"' > "$HOME_DIR/.config/speech-dispatcher/speechd.conf"
run_install; rc=$?
check "non-zero exit" '[ $rc != 0 ]'
check "clear message" 'grep -q "already has an AddModule \"supertonic\"" "$T/out"'
check "nothing installed" '[ ! -e "$APP" ] && [ ! -e "$CONF/speech-dispatcher/modules/supertonic.conf" ]'
teardown

echo "unsupported language is refused"
setup
run_install --languages "en xx"; rc=$?
check "non-zero exit + message" '[ $rc != 0 ] && grep -q "unsupported language: xx" "$T/out"'
teardown

echo "paths with spaces, & and # are written literally"
setup 'my home & co #1'
run_install; rc=$?
check "exit 0 (got $rc): $(tail -2 "$T/out")" '[ $rc = 0 ]'
check "service has literal path" 'grep -qF "\"$APP/supertonic_server.py\"" "$CONF/systemd/user/supertonic-tts.service"'
check "module conf has literal path" 'grep -qF "$APP/supertonic_say.py" "$CONF/speech-dispatcher/modules/supertonic.conf"'
GEN_HOME=$HOME_DIR; GEN_T=$T  # used by the command test below

echo "paths with a quote or \$ are refused"
for bad in "it's home" 'home $USER' 'home ${HOME}'; do
    setup "$bad"
    run_install; rc=$?
    check "'$bad': non-zero exit + message" '[ $rc != 0 ] && grep -q "isn.t supported" "$T/out"'
    check "'$bad': nothing installed" '[ ! -e "$APP" ]'
    teardown
done

echo "a path containing a placeholder name is written literally"
setup 'home @LOG@ @UV@'
run_install; rc=$?
check "exit 0" '[ $rc = 0 ]'
check "service keeps the literal path" 'grep -qF "\"$APP/supertonic_server.py\"" "$CONF/systemd/user/supertonic-tts.service"'
check "log path literal" 'grep -qF "SPEECHD_SUPERTONIC_LOG=$HOME_DIR/.cache/speechd_supertonic.log" "$CONF/systemd/user/supertonic-tts.service"'
check "module conf keeps the literal path" 'grep -qF "$APP/supertonic_say.py" "$CONF/speech-dispatcher/modules/supertonic.conf"'
teardown

echo "modules found in a multiarch directory that isn't listed anywhere"
setup
mkdir -p "$T/root/usr/lib/riscv64-linux-gnu/speech-dispatcher-modules"
cp "$T/modules/"* "$T/root/usr/lib/riscv64-linux-gnu/speech-dispatcher-modules/"
MODULES_ENV="SPEECHD_SUPERTONIC_SYSROOT=$T/root" run_install; rc=$?
check "exit 0 (got $rc): $(tail -2 "$T/out")" '[ $rc = 0 ]'
check "espeak-ng found next to it" 'grep -q "AddModule \"espeak-ng\"" "$CONF/speech-dispatcher/speechd.conf"'
teardown

echo "no modules anywhere: clear error"
setup
MODULES_ENV="SPEECHD_SUPERTONIC_SYSROOT=$T/empty-root" run_install; rc=$?
check "non-zero exit + hint" '[ $rc != 0 ] && grep -q "set SPEECHD_MODULES_DIR" "$T/out"'
teardown

echo "generated command, run like sd_generic: quoting and exit status"
T=$GEN_T; HOME_DIR=$GEN_HOME; CONF=$HOME_DIR/.config; APP=$HOME_DIR/.local/share/speechd-supertonic
# Replace the installed client with a stub that records its input and arguments.
cat > "$APP/supertonic_say.py" <<EOF
#!/bin/sh
cat > "$T/stdin"
printf '%s\n' "\$@" > "$T/args"
exit \${STUB_EXIT:-0}
EOF
chmod +x "$APP/supertonic_say.py"
run_cmd() {  # $1 = text, like Firefox would send it
    python3 - "$CONF/speech-dispatcher/modules/supertonic.conf" "$1" > "$T/cmd" <<'PY'
import re, sys
conf, data = sys.argv[1], sys.argv[2]
line = next(l for l in open(conf) if l.startswith("GenericExecuteSynth"))
raw = line.split(None, 1)[1].strip()[1:-1]
cmd = re.sub(r"\\(.)", r"\1", raw)                    # dotconf: backslash escapes the next char
data = data.replace("'", "'\\''")                     # sd_generic escapes single quotes in $DATA
for var, val in {"$DATA": data, "$VOICE": "M2-nl", "$LANGUAGE": "en", "$RATE": "-70",
                 "$VOLUME": "0", "$PITCH": "0"}.items():
    cmd = cmd.replace(var, val)
print("set -o pipefail ; " + cmd)
PY
    (cd "$T" && /bin/bash -c "$(cat "$T/cmd")")
}
TEXT='It'"'"'s $(touch pwned) and `touch pwned2` and "quotes" & ; | done'
run_cmd "$TEXT"; rc=$?
check "exit 0" '[ $rc = 0 ]'
check "text arrives verbatim" '[ "$(cat "$T/stdin")" = "$TEXT" ]'
check "no command injection" '[ ! -e "$T/pwned" ] && [ ! -e "$T/pwned2" ]'
check "arguments passed" '[ "$(tr "\n" " " < "$T/args")" = "--voice M2-nl --lang en --rate -70 --volume 0 " ]'
STUB_EXIT=3 run_cmd "Failing."; rc=$?
check "client failure propagates (got $rc)" '[ $rc = 3 ]'
teardown

echo
echo "install tests: $PASSES passed, $FAILS failed"
[ "$FAILS" = 0 ]
