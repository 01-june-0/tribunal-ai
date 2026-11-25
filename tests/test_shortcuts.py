"""Phase 3 of docs/PACKAGING.md: the install one-liners and the icons (core/shortcuts.py, install.sh, install.ps1).

Every shortcut here is made under TRIBUNAL_SHORTCUTS_HOME in a temporary folder - never on the real Desktop - and no
dialog is ever shown. The installers themselves run for real only in GitHub Actions (the `installer` job)."""
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import click
import pytest
from click.testing import CliRunner

import tribunal_cli
from core import pythons, shortcuts

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def place(monkeypatch, tmp_path):
    monkeypatch.setenv("TRIBUNAL_SHORTCUTS_HOME", str(tmp_path))
    return tmp_path


def test_where_each_system_puts_them(place):
    assert shortcuts.locations("mac") == [place / "Applications" / "Tribunal AI.app"]
    assert shortcuts.locations("linux") == [place / ".local" / "share" / "applications" / "tribunal-ai.desktop"]
    assert shortcuts.locations("windows") == [place / "Start Menu" / "Tribunal AI.lnk", place / "Desktop" / "Tribunal AI.lnk"]


def test_a_relative_test_home_is_refused(monkeypatch):
    monkeypatch.setenv("TRIBUNAL_SHORTCUTS_HOME", "relative")
    with pytest.raises(ValueError):
        shortcuts.locations("mac")


def test_the_mac_app_runs_this_python_and_says_what_it_is():
    files = shortcuts.mac_files(["/Users/o'brien/my tools/python", "-m", "tribunal_cli", "open", "--from-shortcut"])
    script = files["Contents/MacOS/tribunal-launch"]
    assert script.startswith("#!/bin/sh\n") and shortcuts.MARK in script
    assert "exec '/Users/o'\\''brien/my tools/python' '-m' 'tribunal_cli' 'open' '--from-shortcut'" in script
    plist = files["Contents/Info.plist"]
    assert "<key>CFBundleExecutable</key><string>tribunal-launch</string>" in plist and shortcuts.MARK in plist
    if shutil.which("sh"):                                                     # the shell reads it back as written
        line = next(l for l in script.splitlines() if l.startswith("exec "))
        out = subprocess.run(["sh", "-c", "set -- " + line[5:] + '; printf "%s|" "$@"'], capture_output=True, text=True)
        assert out.stdout == "/Users/o'brien/my tools/python|-m|tribunal_cli|open|--from-shortcut|"


def test_the_linux_entry_quotes_its_command():
    entry = shortcuts.desktop_entry(['/home/a "b"/$x/100%/python', "-m", "tribunal_cli", "open", "--from-shortcut"])
    exec_line = next(line for line in entry.splitlines() if line.startswith("Exec="))
    # quoted for Exec (\" \$), then every backslash doubled for the string the value is first
    assert exec_line == 'Exec="/home/a \\\\"b\\\\"/\\\\$x/100%%/python" "-m" "tribunal_cli" "open" "--from-shortcut"'
    assert "Terminal=false" in entry and shortcuts.MARK in entry and "Comment[ko]=" in entry


def test_the_shortcut_command_is_this_environment(monkeypatch, tmp_path):
    exe = tmp_path / "Scripts" / "python.exe"
    exe.parent.mkdir()
    exe.write_text("")
    monkeypatch.setattr(shortcuts.sys, "executable", str(exe))
    assert shortcuts.launch_command("windows")[0] == str(exe)                      # no pythonw: the plain one
    (tmp_path / "Scripts" / "pythonw.exe").write_text("")
    assert shortcuts.launch_command("windows") == [str(tmp_path / "Scripts" / "pythonw.exe"), "-I", "-m",
                                                   "tribunal_cli", "app", "--from-shortcut"]
    assert shortcuts.launch_command("mac")[0] == str(exe)


def test_a_console_started_from_a_windows_icon_runs_under_python_exe(monkeypatch, tmp_path):
    (tmp_path / "python.exe").write_text("")
    (tmp_path / "pythonw.exe").write_text("")
    monkeypatch.setattr(pythons.sys, "executable", str(tmp_path / "pythonw.exe"))
    assert pythons.tribunal_python() == str(tmp_path / "python.exe")


@pytest.mark.parametrize("sysname", ["mac", "linux"])
def test_make_and_remove_mac_and_linux(place, sysname):
    done = shortcuts.create(sysname)
    path = shortcuts.locations(sysname)[0]
    assert done == {"made": [str(path)], "skipped": []}
    if sysname == "mac":
        launcher = path / "Contents" / "MacOS" / "tribunal-launch"
        assert launcher.is_file() and sys.executable in launcher.read_text(encoding="utf-8")
        if os.name != "nt":
            assert os.access(launcher, os.X_OK)
    else:
        assert "Exec=" in path.read_text(encoding="utf-8")
    assert shortcuts.create(sysname)["made"] == [str(path)]                         # made again over its own
    assert shortcuts.remove(sysname) == {"removed": [str(path)], "kept": []}
    assert not path.exists()
    assert shortcuts.remove(sysname) == {"removed": [], "kept": []}


@pytest.mark.parametrize("sysname", ["mac", "linux"])
def test_something_else_of_the_same_name_is_never_touched(place, sysname):
    path = shortcuts.locations(sysname)[0]
    path.parent.mkdir(parents=True)
    if sysname == "mac":
        (path / "Contents").mkdir(parents=True)
        (path / "Contents" / "Info.plist").write_text("<plist>someone else's app</plist>", encoding="utf-8")
    else:
        path.write_text("[Desktop Entry]\nName=Mine\n", encoding="utf-8")
    assert shortcuts.create(sysname) == {"made": [], "skipped": [str(path)]}
    assert shortcuts.remove(sysname) == {"removed": [], "kept": [str(path)]}
    assert path.exists()


@pytest.mark.skipif(os.name == "nt", reason="links need extra rights on Windows")
def test_a_link_in_its_place_is_left_alone(place, tmp_path):
    path = shortcuts.locations("linux")[0]
    path.parent.mkdir(parents=True)
    real = tmp_path / "elsewhere.desktop"
    real.write_text(shortcuts.desktop_entry(["x"]), encoding="utf-8")                # ours in content, but a link
    path.symlink_to(real)
    assert shortcuts.create("linux")["skipped"] == [str(path)]
    assert shortcuts.remove("linux")["kept"] == [str(path)]


@pytest.mark.skipif(os.name != "nt", reason="a Windows shortcut needs Windows")
def test_windows_shortcuts_for_real(place):
    done = shortcuts.create("windows")
    assert done["made"] == [str(p) for p in shortcuts.locations("windows")] and not done["skipped"]
    for path in shortcuts.locations("windows"):
        assert path.is_file() and shortcuts._is_ours(path)
    other = place / "Desktop" / "Tribunal AI.lnk"
    assert shortcuts.remove("windows")["removed"] == [str(p) for p in shortcuts.locations("windows")]
    assert not other.exists()


def test_a_windows_lnk_is_recognised_by_its_mark(tmp_path):
    ours, theirs = tmp_path / "a.lnk", tmp_path / "b.lnk"
    ours.write_bytes(b"L\x00\x00\x00" + ("Tribunal AI (" + shortcuts.MARK + ")").encode("utf-16-le"))
    theirs.write_bytes(b"L\x00\x00\x00" + "Tribunal AI".encode("utf-16-le"))
    assert shortcuts._is_ours(ours) and not shortcuts._is_ours(theirs)


@pytest.mark.skipif(os.name == "nt", reason="a login shell is a macOS / Linux thing")
def test_the_terminals_path_is_read_past_what_start_up_files_print(monkeypatch, tmp_path):
    shell = tmp_path / "fakeshell"
    shell.write_text('#!/bin/sh\necho "welcome back!"\nPATH=/from/login:/usr/bin\nexport PATH\nshift\neval "$1"\n',
                     encoding="utf-8")
    shell.chmod(0o755)
    monkeypatch.setenv("SHELL", str(shell))
    assert shortcuts.login_shell_path() == "/from/login:/usr/bin"
    monkeypatch.setenv("SHELL", str(tmp_path / "missing"))
    assert shortcuts.login_shell_path() is None


def test_widen_path_puts_the_terminals_path_first_and_loses_nothing(monkeypatch):
    sep = os.pathsep
    monkeypatch.setenv("PATH", sep.join(["/usr/bin", "/bin"]))
    monkeypatch.setattr(shortcuts, "login_shell_path", lambda: sep.join(["/opt/homebrew/bin", "/usr/bin"]))
    from core import setup
    monkeypatch.setattr(setup, "refresh_path", lambda: None)
    shortcuts.widen_path()
    assert os.environ["PATH"].split(sep) == ["/opt/homebrew/bin", "/usr/bin", "/bin"]


def test_an_icon_start_that_fails_says_so_on_screen(monkeypatch, tmp_path):
    monkeypatch.setenv("TRIBUNAL_HOME", str(tmp_path))
    shown, opened = [], []
    monkeypatch.setattr(shortcuts, "widen_path", lambda: None)
    monkeypatch.setattr(shortcuts, "show_error", shown.append)
    monkeypatch.setattr(tribunal_cli.webbrowser, "open", opened.append)

    def broken(wait=30.0):
        raise click.ClickException("콘솔이 30초 안에 준비되지 않았습니다.")
    monkeypatch.setattr(tribunal_cli, "start_console", broken)
    out = CliRunner().invoke(tribunal_cli.cli, ["open", "--from-shortcut"])
    assert out.exit_code == 1 and not opened
    assert len(shown) == 1 and "30초" in shown[0] and str(tmp_path) in shown[0]

    monkeypatch.setattr(tribunal_cli, "start_console", lambda wait=30.0: "http://127.0.0.1:9")
    out = CliRunner().invoke(tribunal_cli.cli, ["open", "--from-shortcut"])
    assert out.exit_code == 0 and opened == ["http://127.0.0.1:9"] and len(shown) == 1


def test_the_shortcut_command(place, monkeypatch):
    monkeypatch.setattr(shortcuts, "system", lambda: "linux")
    out = CliRunner().invoke(tribunal_cli.cli, ["shortcut"])
    assert out.exit_code == 0 and "tribunal-ai.desktop" in out.output
    out = CliRunner().invoke(tribunal_cli.cli, ["shortcut", "--remove"])
    assert out.exit_code == 0 and "removed" in out.output
    assert "no shortcuts to remove" in CliRunner().invoke(tribunal_cli.cli, ["shortcut", "--remove"]).output


# ---- the install and uninstall scripts ----------------------------------------------------------------------------

ARCHIVE = "https://github.com/01-june-0/tribunal-ai/archive/refs/heads/main.zip"
SCRIPTS = ("install.sh", "uninstall.sh", "install.ps1", "uninstall.ps1")


def _text(name):
    return (ROOT / name).read_text(encoding="utf-8")


@pytest.mark.skipif(not shutil.which("sh"), reason="needs sh")
@pytest.mark.parametrize("name", ["install.sh", "uninstall.sh"])
def test_the_shell_scripts_parse_and_run_only_when_complete(name):
    assert subprocess.run(["sh", "-n", str(ROOT / name)]).returncode == 0
    lines = _text(name).rstrip().splitlines()
    assert lines[-1] == 'main "$@"'                                           # a cut-off download runs nothing


@pytest.mark.parametrize("name", ["install.ps1", "uninstall.ps1"])
def test_the_powershell_scripts_stay_ascii_and_never_close_the_window(name):
    text = _text(name)
    text.encode("ascii")                                                   # irm | iex and Windows PowerShell 5.1
    code = "\n".join(line.split("#", 1)[0] for line in text.splitlines())
    assert not re.search(r"\bexit\b", code)
    for modern in ("&&", "||", "??", "?."):
        assert modern not in code
    assert text.rstrip().splitlines()[-1] in ("Install-TribunalAI", "Uninstall-TribunalAI")


def test_both_installers_install_the_same_thing_the_same_way():
    for name in ("install.sh", "install.ps1"):
        text = _text(name)
        assert ARCHIVE in text and "TRIBUNAL_SOURCE" in text
        assert "tool install --force --reinstall" in text and "--python 3.13" in text
        assert "--managed-python" in text and "--python-preference=only-managed" in text       # older uv too
        assert "https://astral.sh/uv/install." in text
        assert "shortcut" in text and "TRIBUNAL_NO_OPEN" in text and "TRIBUNAL_NO_MODIFY_PATH" in text


@pytest.mark.parametrize("name", ["uninstall.sh", "uninstall.ps1"])
def test_uninstall_stops_then_removes_icons_then_the_program_and_keeps_records(name):
    text = _text(name)
    stop, icons, program = text.index(" stop"), text.index("shortcut --remove"), text.index("tool uninstall tribunal-ai")
    assert stop < icons < program
    assert "rm -rf" not in text and "Remove-Item" not in text                  # records and projects stay


def test_the_readme_shows_the_one_liners():
    readme = _text("README.md")
    assert "raw.githubusercontent.com/01-june-0/tribunal-ai/main/install.sh | sh" in readme
    assert "raw.githubusercontent.com/01-june-0/tribunal-ai/main/install.ps1 | iex" in readme
