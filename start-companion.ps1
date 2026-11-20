$ErrorActionPreference = 'Stop'
$directorRoot = $PSScriptRoot
$directorPython = (Get-Command python).Source
# Port: 8081 by default, or the next free port when that one is busy; a port set in companion.local.json or
# TRIBUNAL_PORT is used as given. The address printed below is the one the server reports.
# (Rewritten together with start-companion.sh; not yet verified on Windows.)
Push-Location $directorRoot
try {
    $directorPort = [int](& $directorPython -m core.companion_config)
    $directorState = (& $directorPython -c "from core import companion_config as c; print(c.probe($directorPort))").Trim()
} finally { Pop-Location }
if ($directorState -eq 'ours') { Write-Output "Tribunal AI companion already running: http://127.0.0.1:$directorPort"; exit 0 }
$directorLog = Join-Path $directorRoot 'data/companion.log'
$directorErr = Join-Path $directorRoot 'data/companion.err'
Set-Content -Path $directorLog -Value '' -NoNewline
$directorProcess = Start-Process -FilePath $directorPython -ArgumentList 'companion_server.py' -WorkingDirectory $directorRoot -WindowStyle Hidden -RedirectStandardOutput $directorLog -RedirectStandardError $directorErr -PassThru
for ($i = 0; $i -lt 40; $i++) {
    $directorText = Get-Content -Path $directorLog -Raw -ErrorAction SilentlyContinue
    if ($directorText -match 'Tribunal AI console (http://127\.0\.0\.1:\d+)') {
        if ($directorText -match '(?m)^.*in use by another program.*$') { Write-Output $Matches[0].Trim() }
        $null = $directorText -match 'Tribunal AI console (http://127\.0\.0\.1:\d+)'
        Write-Output "Tribunal AI companion: $($Matches[1])"
        exit 0
    }
    if ($directorText -match '(?m)^.*already running.*$') { Write-Output $Matches[0].Trim(); exit 0 }
    if ($directorProcess.HasExited) {
        Write-Error ("Tribunal AI companion failed to start: " + ((Get-Content -Path $directorErr -Tail 3 -ErrorAction SilentlyContinue) -join ' '))
        exit 1
    }
    Start-Sleep -Milliseconds 500
}
Write-Error 'Tribunal AI companion started but has not reported ready yet; see data/companion.log'
exit 1
