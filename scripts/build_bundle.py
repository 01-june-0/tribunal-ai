"""Build the double-click installer for this operating system (docs/PACKAGING.md, phase 5).

    python3 scripts/build_bundle.py [--out dist] [--offline] [--appimagetool PATH] [--iscc PATH]

    macOS    dist/Tribunal-AI-<version>-macos-<arch>.dmg       the app, dragged into Applications
    Windows  dist/Tribunal-AI-<version>-windows-x64-setup.exe  a per-user installer (no administrator rights)
    Linux    dist/Tribunal-AI-<version>-linux-<arch>.AppImage  one file, made executable and opened

Each carries its own Python: the same standalone CPython uv installs (python-build-standalone), copied whole, with
Tribunal AI and its packages installed into it. Nothing is frozen into a single executable, so the console runs exactly
as an installed copy does - a project's tests and the helper scripts get a real Python. Nothing here is signed yet
(that needs paid certificates); the ad-hoc signature on macOS only keeps Apple Silicon willing to run it.

Needs uv. Builds the wheel from this checkout, never from the internet. --offline uses only uv's cache.
"""
from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ICONS = ROOT / "console" / "icons"
NAME = "Tribunal AI"
BUNDLE_ID = "io.github.01-june-0.tribunal-ai"
PYTHON_VERSION = "3.13"
# -B: never write .pyc files into the app (its signature, a read-only AppImage). -I ignores PYTHONDONTWRITEBYTECODE,
# so the flag is given as well; the console's own process (started without -I) gets the environment variable.
LAUNCH_ARGS = ["-I", "-B", "-m", "tribunal_cli", "app", "--from-shortcut"]


def run(cmd, **kw):
    print("+", " ".join(str(c) for c in cmd), flush=True)
    return subprocess.run([str(c) for c in cmd], check=True, **kw)


def system() -> str:
    if sys.platform == "darwin":
        return "mac"
    return "windows" if os.name == "nt" else "linux"


def arch() -> str:
    machine = platform.machine().lower()
    return {"x86_64": "x64", "amd64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(machine, machine)


def version() -> str:
    try:
        import tomllib
    except ModuleNotFoundError:                     # Python 3.10 and older
        import re
        found = re.search(r'^version\s*=\s*"([^"]+)"', (ROOT / "pyproject.toml").read_text(encoding="utf-8"), re.M)
        return found.group(1)
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


# ---- the Python inside -------------------------------------------------------------------------------------------------

def standalone_python(work: Path, offline: bool) -> Path:
    """A private copy of uv's standalone CPython (its folder: bin/ or python.exe at the top)."""
    # One uv already manages is copied as it is; otherwise uv fetches one into a private folder.
    known = subprocess.run(["uv", "python", "find", "--managed-python", PYTHON_VERSION],
                           capture_output=True, text=True)
    source = None
    if known.returncode == 0 and known.stdout.strip():
        exe = Path(known.stdout.strip()).resolve()
        source = exe.parent if system() == "windows" else exe.parent.parent
    else:
        if offline:
            sys.exit(f"--offline: uv manages no Python {PYTHON_VERSION} yet")
        store = work / "pythons"
        # --no-bin / --no-registry: nothing outside this temporary folder points at it once it is gone
        run(["uv", "python", "install", PYTHON_VERSION, "--install-dir", store, "--no-bin"]
            + (["--no-registry"] if system() == "windows" else []))
        found = sorted(p for p in store.iterdir()
                       if p.is_dir() and p.name.startswith("cpython-") and "freethreaded" not in p.name)
        if not found:
            sys.exit("uv did not install a standalone CPython")
        source = found[-1]
    copy = work / "python"
    shutil.copytree(source, copy, symlinks=True)
    for marker in copy.rglob("EXTERNALLY-MANAGED"):  # uv marks its own copy read-only for pip; this one is ours
        marker.unlink()
    return copy


def python_exe(py: Path, window_less: bool = False) -> Path:
    if system() == "windows":
        return py / ("pythonw.exe" if window_less else "python.exe")
    return py / "bin" / f"python{PYTHON_VERSION}"


def install_tribunal(py: Path, work: Path, offline: bool) -> None:
    wheels = work / "wheel"
    run(["uv", "build", "--wheel", "--out-dir", wheels, ROOT] + (["--offline"] if offline else []))
    wheel = next(wheels.glob("tribunal_ai-*.whl"))
    run(["uv", "pip", "install", "--python", python_exe(py), wheel] + (["--offline"] if offline else []))
    # Console scripts carry the build machine's absolute path; the bundle always starts `python -I -m tribunal_cli`.
    scripts = py / ("Scripts" if system() == "windows" else "bin")
    for name in ("tribunal", "tribunal.exe"):
        (scripts / name).unlink(missing_ok=True)
    # Compiled now, and checked by hash instead of by file date: copying the app (or a file system that keeps no dates)
    # must never make Python compile again and write into it.
    # With the bundle's own Python: the .pyc files must be for its version, whatever Python runs this script.
    run([python_exe(py), "-I", "-m", "compileall", "-q", "-f", "-j", "0", "--invalidation-mode", "unchecked-hash",
         py / ("Lib" if system() == "windows" else "lib")], stdout=subprocess.DEVNULL)


def notices(py: Path, out: Path) -> None:
    """THIRD-PARTY-NOTICES.txt: the licence text of Python and of every package inside. A package without one stops
    the build - a silent gap would be worse."""
    script = r'''
import sys, importlib.metadata as md
from pathlib import Path
parts, missing = [], []
for dist in sorted(md.distributions(), key=lambda d: (d.metadata["Name"] or "").lower()):
    name, files = dist.metadata["Name"], dist.files or []
    texts = [f for f in files if any(k in f.name.upper() for k in ("LICENSE", "LICENCE", "COPYING", "NOTICE"))]
    if name == "tribunal-ai":
        continue
    if texts:
        body = "\n\n".join(Path(dist.locate_file(f)).read_text(encoding="utf-8", errors="replace").strip() for f in texts)
    else:                       # no licence file in the wheel: what its metadata says, and where its source is
        meta = dist.metadata
        kind = meta.get("License-Expression") or (meta.get("License") or "").strip() or ", ".join(
            c.split(" :: ")[-1] for c in meta.get_all("Classifier") or [] if c.startswith("License ::"))
        if not kind:
            missing.append(name); continue
        url = meta.get("Home-page") or next((u.split(",", 1)[1].strip() for u in meta.get_all("Project-URL") or []), "")
        body = f"Licence: {kind}" + (f"\nSource: {url}" if url else "") + "\n(the package carries no licence file)"
    parts.append(f"=== {name} {dist.version} ===\n{body}")
if missing:
    sys.exit("no licence file in: " + ", ".join(missing))
print("\n\n".join(parts))
'''
    # -X utf8: the licence texts come back as UTF-8 on every system (Windows would print them in its code page)
    done = subprocess.run([str(python_exe(py)), "-I", "-X", "utf8", "-c", script], capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if done.returncode != 0:
        sys.exit(done.stderr.strip() or "could not collect the licences")
    python_licence = next((p for p in (py / "lib" / f"python{PYTHON_VERSION}" / "LICENSE.txt", py / "LICENSE.txt",
                                       py / "Lib" / "LICENSE.txt") if p.is_file()), None)
    if python_licence is None:
        sys.exit("the standalone Python carries no LICENSE.txt")
    head = (f"{NAME} {version()} - MIT License, see LICENSE.\n"
            "It ships with the programs below, each under its own licence.\n\n")
    out.write_text(head + f"=== Python {PYTHON_VERSION} ===\n" + python_licence.read_text(encoding="utf-8").strip()
                   + "\n\n" + done.stdout, encoding="utf-8")


# ---- one installer per system ------------------------------------------------------------------------------------------

def build_mac(py: Path, work: Path, out: Path) -> Path:
    app = work / "dmg" / f"{NAME}.app"
    contents = app / "Contents"
    (contents / "MacOS").mkdir(parents=True)
    (contents / "Resources").mkdir()
    shutil.move(str(py), str(contents / "Resources" / "python"))
    shutil.copyfile(ICONS / "tribunal.icns", contents / "Resources" / "tribunal.icns")
    for name in ("LICENSE",):
        shutil.copyfile(ROOT / name, contents / "Resources" / name)
    shutil.move(str(work / "THIRD-PARTY-NOTICES.txt"), str(contents / "Resources" / "THIRD-PARTY-NOTICES.txt"))
    launcher = contents / "MacOS" / "tribunal-launch"
    launcher.write_text(
        "#!/bin/sh\n"
        "# Opens Tribunal AI with the Python inside this app. Nothing is written into the app while it runs.\n"
        'here="$(cd "$(dirname "$0")/.." && pwd)"\n'
        "export PYTHONDONTWRITEBYTECODE=1\n"
        f'exec "$here/Resources/python/bin/python{PYTHON_VERSION}" ' + " ".join(LAUNCH_ARGS) + "\n", encoding="utf-8")
    launcher.chmod(0o755)
    (contents / "Info.plist").write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>{NAME}</string>
  <key>CFBundleDisplayName</key><string>{NAME}</string>
  <key>CFBundleIdentifier</key><string>{BUNDLE_ID}</string>
  <key>CFBundleExecutable</key><string>tribunal-launch</string>
  <key>CFBundleIconFile</key><string>tribunal</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>{version()}</string>
  <key>CFBundleVersion</key><string>{version()}</string>
  <key>CFBundleInfoDictionaryVersion</key><string>6.0</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
""", encoding="utf-8")
    run(["codesign", "--force", "--deep", "--sign", "-", app])           # ad hoc: no identity, no notarisation
    os.symlink("/Applications", work / "dmg" / "Applications")
    dmg = out / f"Tribunal-AI-{version()}-macos-{arch()}.dmg"
    dmg.unlink(missing_ok=True)
    run(["hdiutil", "create", "-volname", NAME, "-srcfolder", work / "dmg", "-ov", "-format", "UDZO", dmg])
    return dmg


ISS = r"""; Inno Setup script written by scripts/build_bundle.py
[Setup]
AppId={{9A4C5E2B-7F1D-4C8E-9B3A-6D7A1B2C3E4F}
AppName=Tribunal AI
AppVersion=@VERSION@
AppPublisher=Tribunal AI
DefaultDirName={localappdata}\Programs\Tribunal AI
DefaultGroupName=Tribunal AI
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=@OUT@
OutputBaseFilename=Tribunal-AI-@VERSION@-windows-x64-setup
SetupIconFile=@ICON@
UninstallDisplayIcon={app}\tribunal.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
LicenseFile=@LICENSE@
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[InstallDelete]
; an update replaces the whole Python folder: files the new version no longer has must not linger
Type: filesandordirs; Name: "{app}\python"

[Files]
Source: "@SRC@\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\Tribunal AI"; Filename: "{app}\python\pythonw.exe"; Parameters: "@ARGS@"; WorkingDir: "{userdocs}"; IconFilename: "{app}\tribunal.ico"
Name: "{autodesktop}\Tribunal AI"; Filename: "{app}\python\pythonw.exe"; Parameters: "@ARGS@"; WorkingDir: "{userdocs}"; IconFilename: "{app}\tribunal.ico"

[Run]
Filename: "{app}\python\pythonw.exe"; Parameters: "@ARGS@"; Description: "Open Tribunal AI"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{app}\python\python.exe"; Parameters: "-I -m tribunal_cli stop"; Flags: runhidden; RunOnceId: "StopConsole"

[Code]
// An update: a running console keeps its files open, so it is stopped first (records stay).
function PrepareToInstall(var NeedsRestart: Boolean): String;
var Code: Integer;
begin
  if FileExists(ExpandConstant('{app}\python\python.exe')) then
    Exec(ExpandConstant('{app}\python\python.exe'), '-I -m tribunal_cli stop', '', SW_HIDE, ewWaitUntilTerminated, Code);
  Result := '';
end;
"""


def build_windows(py: Path, work: Path, out: Path, iscc: str) -> Path:
    src = work / "app"
    src.mkdir()
    shutil.move(str(py), str(src / "python"))
    shutil.copyfile(ICONS / "tribunal.ico", src / "tribunal.ico")
    shutil.copyfile(ROOT / "LICENSE", src / "LICENSE.txt")
    shutil.move(str(work / "THIRD-PARTY-NOTICES.txt"), str(src / "THIRD-PARTY-NOTICES.txt"))
    script = work / "tribunal.iss"
    script.write_text(ISS.replace("@VERSION@", version()).replace("@OUT@", str(out)).replace("@SRC@", str(src))
                      .replace("@ICON@", str(ICONS / "tribunal.ico")).replace("@LICENSE@", str(ROOT / "LICENSE"))
                      .replace("@ARGS@", " ".join(LAUNCH_ARGS)),
                      encoding="utf-8")
    run([iscc, "/Q", script])
    return out / f"Tribunal-AI-{version()}-windows-x64-setup.exe"


APPRUN = """#!/bin/sh
# Tribunal AI as an AppImage. There is no window library on Linux, so the console opens in the browser - and this
# process stays as long as the console runs: the AppImage's files are only there while it does.
here="$(dirname "$(readlink -f "$0")")"
export PYTHONDONTWRITEBYTECODE=1
exec "$here/usr/python/bin/python@PY@" -I -B -m tribunal_cli app --from-shortcut --foreground "$@"
"""


def build_linux(py: Path, work: Path, out: Path, appimagetool: str) -> Path:
    appdir = work / "Tribunal_AI.AppDir"
    (appdir / "usr").mkdir(parents=True)
    shutil.move(str(py), str(appdir / "usr" / "python"))
    shutil.copyfile(ICONS / "tribunal-512.png", appdir / "tribunal-ai.png")
    shutil.copyfile(ROOT / "LICENSE", appdir / "LICENSE")
    shutil.move(str(work / "THIRD-PARTY-NOTICES.txt"), str(appdir / "THIRD-PARTY-NOTICES.txt"))
    (appdir / "AppRun").write_text(APPRUN.replace("@PY@", PYTHON_VERSION), encoding="utf-8")
    (appdir / "AppRun").chmod(0o755)
    (appdir / "tribunal-ai.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=Tribunal AI\nIcon=tribunal-ai\nExec=AppRun\nTerminal=false\n"
        "Categories=Development;\nComment=Claude Code, Codex and Antigravity as one coding team\n", encoding="utf-8")
    image = out / f"Tribunal-AI-{version()}-linux-{'x86_64' if arch() == 'x64' else 'aarch64'}.AppImage"
    env = dict(os.environ, ARCH="x86_64" if arch() == "x64" else "aarch64")
    run([appimagetool, "--no-appstream", appdir, image], env=env)
    return image


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default=str(ROOT / "dist"))
    ap.add_argument("--offline", action="store_true", help="use only what uv has cached")
    ap.add_argument("--appimagetool", default=shutil.which("appimagetool") or "appimagetool")
    ap.add_argument("--iscc", default=shutil.which("iscc") or r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe")
    args = ap.parse_args()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="tribunal-bundle-") as tmp:
        work = Path(tmp)
        py = standalone_python(work, args.offline)
        install_tribunal(py, work, args.offline)
        notices(py, work / "THIRD-PARTY-NOTICES.txt")
        made = {"mac": lambda: build_mac(py, work, out),
                "windows": lambda: build_windows(py, work, out, args.iscc),
                "linux": lambda: build_linux(py, work, out, args.appimagetool)}[system()]()
    print(f"made: {made} ({made.stat().st_size // (1024 * 1024)} MB)")


if __name__ == "__main__":
    main()
