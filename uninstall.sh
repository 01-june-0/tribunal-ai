#!/bin/sh
# Removes Tribunal AI from macOS or Linux (docs/PACKAGING.md, phase 3):
#
#   curl -LsSf https://raw.githubusercontent.com/01-june-0/tribunal-ai/main/uninstall.sh | sh
#
# Stops the console, takes away the icon and the `tribunal` command. Kept: the records (shown at the end, delete that
# folder yourself if you want them gone), your projects and the practice folder, uv and the AI CLIs.

main() {
    set -eu
    say ""
    say "Tribunal AI를 지웁니다 / Removing Tribunal AI"
    uv="$(find_uv)"
    tribunal=""
    if [ -n "$uv" ] && [ -x "$("$uv" tool dir --bin 2>/dev/null)/tribunal" ]; then
        tribunal="$("$uv" tool dir --bin)/tribunal"
    elif command -v tribunal >/dev/null 2>&1; then
        tribunal="$(command -v tribunal)"
    fi
    records=""
    if [ -n "$tribunal" ]; then
        records="$("$tribunal" doctor --json 2>/dev/null | sed -n 's/^ *"home": "\(.*\)",*$/\1/p' | head -n 1)" || records=""
        "$tribunal" stop || true
        "$tribunal" shortcut --remove || true
    fi
    if [ -n "$uv" ] && "$uv" tool list 2>/dev/null | grep -q '^tribunal-ai '; then
        "$uv" tool uninstall tribunal-ai
    else
        say "설치된 Tribunal AI가 없습니다 / Tribunal AI is not installed (uv tool list)."
    fi
    say ""
    say "지웠습니다 / Removed."
    if [ -n "$records" ]; then
        say "  기록은 남겨 두었습니다 / records kept: $records"
        say "  필요 없으면 그 폴더를 직접 지우세요 / delete that folder yourself if you want them gone."
    fi
}

say() {
    printf '%s\n' "$1"
}

find_uv() {
    if command -v uv >/dev/null 2>&1; then
        command -v uv
        return
    fi
    for candidate in "${XDG_BIN_HOME:-}/uv" "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv"; do
        if [ -x "$candidate" ]; then
            printf '%s\n' "$candidate"
            return
        fi
    done
}

main "$@"
