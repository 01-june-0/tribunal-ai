#!/bin/sh
# Tribunal AI installer for macOS and Linux (docs/PACKAGING.md, phase 3). Paste into a terminal:
#
#   curl -LsSf https://raw.githubusercontent.com/01-june-0/tribunal-ai/main/install.sh | sh
#
# What it does, and nothing else:
#   1. uv (Astral's installer for Python programs) - only when it is not there yet, with Astral's own installer.
#      uv also fetches the Python that Tribunal runs on, so no Python needs to be installed first.
#   2. Tribunal AI itself: `uv tool install` puts the `tribunal` command in ~/.local/bin.
#   3. An icon: macOS ~/Applications/Tribunal AI.app, Linux the application menu (`tribunal shortcut`).
#   4. Opens the console in the browser; its start-up helper guides through git, the AI CLIs and signing in.
# Running it again updates Tribunal to the newest version; records stay. Remove it again with uninstall.sh.
#
# For checks only: TRIBUNAL_SOURCE (what to install instead of the GitHub archive), TRIBUNAL_NO_OPEN=1 (do not open
# the browser), TRIBUNAL_NO_MODIFY_PATH=1 (leave the shell's start-up files alone).
#
# Everything is inside main(), called on the last line: a download cut off half way runs nothing.

main() {
    set -eu
    source_url="${TRIBUNAL_SOURCE:-https://github.com/01-june-0/tribunal-ai/archive/refs/heads/main.zip}"
    say ""
    say "Tribunal AI 설치를 시작합니다 / Installing Tribunal AI"

    uv="$(find_uv)"
    if [ -z "$uv" ]; then
        say ""
        say "1/3 uv 설치 (Python 프로그램 설치 도구, https://docs.astral.sh/uv) / installing uv"
        if command -v curl >/dev/null 2>&1; then
            curl -LsSf https://astral.sh/uv/install.sh | sh
        elif command -v wget >/dev/null 2>&1; then
            wget -qO- https://astral.sh/uv/install.sh | sh
        else
            fail "curl이나 wget이 필요합니다 / curl or wget is needed"
        fi
        uv="$(find_uv)"
        [ -n "$uv" ] || fail "uv를 설치하지 못했습니다 / uv did not install"
    else
        say "1/3 uv가 있습니다 / uv found: $uv"
    fi

    old="$("$uv" tool dir --bin 2>/dev/null || true)/tribunal"
    if [ -x "$old" ]; then
        "$old" stop || true                                  # an update: the console restarts on the new version
    fi

    say ""
    say "2/3 Tribunal AI 설치 (처음에는 Python도 함께 받아 1~2분 걸립니다) / installing Tribunal AI"
    managed="--managed-python"                               # uv's own Python, never a macOS stub or an old system one
    if ! "$uv" tool install --help 2>/dev/null | grep -q -- "--managed-python"; then
        managed="--python-preference=only-managed"            # the same in uv releases before that option
    fi
    "$uv" tool install --force --reinstall "$managed" --python 3.13 "$source_url" \
        || fail "Tribunal AI를 설치하지 못했습니다. uv가 오래됐다면 'uv self update'(Homebrew는 'brew upgrade uv') 뒤에 다시 하세요 / Tribunal AI did not install; with an old uv, update it first ($("$uv" --version 2>/dev/null))"
    bin="$("$uv" tool dir --bin)"
    tribunal="$bin/tribunal"
    [ -x "$tribunal" ] || fail "설치는 끝났지만 $tribunal 이 없습니다 / $tribunal is missing"
    if [ -z "${TRIBUNAL_NO_MODIFY_PATH:-}" ]; then
        "$uv" tool update-shell >/dev/null 2>&1 || true      # so a new terminal knows `tribunal`
    fi

    say ""
    say "3/3 바로 가기 / shortcut"
    "$tribunal" shortcut || say "바로 가기는 만들지 못했습니다. 터미널에서 tribunal 로 열 수 있습니다 / no shortcut; run: tribunal"

    say ""
    say "설치했습니다 / Installed."
    say "  열기 / open      : Tribunal AI 아이콘, 또는 새 터미널에서 / or in a new terminal:  tribunal"
    say "  지우기 / remove  : curl -LsSf https://raw.githubusercontent.com/01-june-0/tribunal-ai/main/uninstall.sh | sh"
    if [ -z "${TRIBUNAL_NO_OPEN:-}" ]; then
        say ""
        say "콘솔을 엽니다 / opening the console…"
        "$tribunal" open || say "콘솔을 열지 못했습니다. 새 터미널에서 tribunal 을 실행해 보세요 / could not open; run: tribunal"
    fi
}

say() {
    printf '%s\n' "$1"
}

fail() {
    printf '\n오류 / error: %s\n' "$1" >&2
    exit 1
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
