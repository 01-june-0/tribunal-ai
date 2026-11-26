# Tribunal AI installer for Windows (docs/PACKAGING.md, phase 3). Paste into PowerShell:
#
#   powershell -ExecutionPolicy ByPass -c "irm https://raw.githubusercontent.com/01-june-0/tribunal-ai/main/install.ps1 | iex"
#
# What it does, and nothing else:
#   1. uv (Astral's installer for Python programs) - only when it is not there yet, with Astral's own installer.
#      uv also fetches the Python that Tribunal runs on, so no Python needs to be installed first.
#   2. Tribunal AI itself: `uv tool install` puts tribunal.exe in %USERPROFILE%\.local\bin.
#   3. Icons in the Start menu and on the Desktop (`tribunal shortcut`).
#   4. Opens the console (its own window on macOS and Windows, the browser on Linux); its start-up helper guides through git, the AI CLIs and signing in.
# Running it again updates Tribunal to the newest version; records stay. Remove it again with uninstall.ps1.
#
# For checks only: TRIBUNAL_SOURCE (what to install instead of the GitHub archive), TRIBUNAL_NO_OPEN=1 (do not open
# the browser), TRIBUNAL_NO_MODIFY_PATH=1 (leave the user's PATH setting alone).
#
# This file stays ASCII and Windows PowerShell 5.1 compatible: it is read by `irm | iex` and by older Windows.
# Everything is inside a function called on the last line: a download cut off half way runs nothing.
# It never calls `exit`, which would close the window it was pasted into.

function Find-TribunalUv {
    $found = Get-Command uv -ErrorAction SilentlyContinue
    if ($found) { return $found.Source }
    foreach ($candidate in @("$env:USERPROFILE\.local\bin\uv.exe", "$env:USERPROFILE\.cargo\bin\uv.exe")) {
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }
    return $null
}

function Install-TribunalAI {
    $ErrorActionPreference = 'Continue'
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    } catch { }
    $source = $env:TRIBUNAL_SOURCE
    if (-not $source) { $source = 'https://github.com/01-june-0/tribunal-ai/archive/refs/heads/main.zip' }

    Write-Host ''
    Write-Host 'Installing Tribunal AI'
    Write-Host ''
    Write-Host 'Before installing:'
    Write-Host '  - The Maker AI runs commands, installs libraries and edits files in a work folder by itself, without asking each time.'
    Write-Host '  - It works in a folder separate from your project; your project changes only when you press Apply.'
    Write-Host '  - System-wide installs, money and credentials, and irreversible actions are asked about first (AI settings > Permissions).'
    Write-Host '  - This is not a fully isolated environment: commands the AI runs run on this computer.'
    if ($env:TRIBUNAL_ACCEPT_TERMS -eq '1') {
        Write-Host 'Agreed (TRIBUNAL_ACCEPT_TERMS=1)'
    } else {
        $answer = Read-Host 'To agree, type y and press Enter'
        if ($answer -notmatch '^(y|yes)$') {
            Write-Host 'Not agreed: nothing was installed.' -ForegroundColor Yellow
            return
        }
    }

    $uv = Find-TribunalUv
    if (-not $uv) {
        Write-Host ''
        Write-Host '1/3 Installing uv (installer for Python programs, https://docs.astral.sh/uv)'
        # Astral's installer runs in its own PowerShell with ExecutionPolicy Bypass for that process only: run as a plain
        # `irm ... | iex` under the default (Restricted) policy it refuses to start, and its `exit` closed the user's
        # window. The machine's policy is never changed.
        try {
            $shell = (Get-Process -Id $PID).Path
            if (-not $shell) { $shell = 'powershell.exe' }
            & $shell -NoProfile -ExecutionPolicy Bypass -Command 'Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression'
            if ($LASTEXITCODE -ne 0) { throw "the uv installer ended with code $LASTEXITCODE" }
        } catch {
            Write-Host "Error: uv did not install: $_" -ForegroundColor Red
            $global:LASTEXITCODE = 1
            return
        }
        $uv = Find-TribunalUv
        if (-not $uv) {
            Write-Host 'Error: uv did not install.' -ForegroundColor Red
            $global:LASTEXITCODE = 1
            return
        }
    } else {
        Write-Host "1/3 uv found: $uv"
    }

    $old = Join-Path ((& $uv tool dir --bin | Select-Object -First 1).Trim()) 'tribunal.exe'
    if (Test-Path -LiteralPath $old) {
        & $old stop                                     # an update: a running console would hold its files open
    }

    Write-Host ''
    Write-Host '2/3 Installing Tribunal AI (the first time this also fetches Python: a minute or two)'
    $managed = '--managed-python'                      # uv's own Python, never an old system one
    if (-not ((& $uv tool install --help 2>$null | Out-String) -match '--managed-python')) {
        $managed = '--python-preference=only-managed'   # the same in uv releases before that option
    }
    & $uv tool install --force --reinstall $managed --python 3.13 $source
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Error: Tribunal AI did not install. With an old uv ($(& $uv --version)), run 'uv self update' and try again." -ForegroundColor Red
        $global:LASTEXITCODE = 1
        return
    }
    $bin = (& $uv tool dir --bin | Select-Object -First 1).Trim()
    $tribunal = Join-Path $bin 'tribunal.exe'
    if (-not (Test-Path -LiteralPath $tribunal)) {
        Write-Host "Error: $tribunal is missing after the install." -ForegroundColor Red
        $global:LASTEXITCODE = 1
        return
    }
    if (-not $env:TRIBUNAL_NO_MODIFY_PATH) {
        & $uv tool update-shell *> $null              # so a new window knows `tribunal`
    }

    Write-Host ''
    Write-Host '3/3 Shortcuts'
    & $tribunal shortcut
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'No shortcut was made. Tribunal AI still opens with: tribunal' -ForegroundColor Yellow
    }
    & $tribunal consent --accept *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'The agreement was not recorded; the start-up helper asks again.' -ForegroundColor Yellow
    }

    Write-Host ''
    Write-Host 'Installed.' -ForegroundColor Green
    Write-Host '  Open   : the Tribunal AI icon (Start menu or Desktop), or in a new window: tribunal'
    Write-Host '  Remove : powershell -ExecutionPolicy ByPass -c "irm https://raw.githubusercontent.com/01-june-0/tribunal-ai/main/uninstall.ps1 | iex"'
    if (-not $env:TRIBUNAL_NO_OPEN) {
        Write-Host ''
        Write-Host 'Opening the console...'
        & $tribunal app --detach
        if ($LASTEXITCODE -ne 0) {
            Write-Host 'Could not open the console. Try `tribunal` in a new window.' -ForegroundColor Yellow
        }
    }
}

Install-TribunalAI
