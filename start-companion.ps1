$ErrorActionPreference = 'Stop'
$directorRoot = $PSScriptRoot
$directorPython = (Get-Command python).Source
# Port: companion.json, overridden by companion.local.json
Push-Location $directorRoot
try { $directorPort = [int](& $directorPython -m core.companion_config) } finally { Pop-Location }
try {
    $directorHealth = Invoke-RestMethod "http://127.0.0.1:$directorPort/ops/state" -TimeoutSec 3
    if ($directorHealth.solomon_url) { Write-Output 'Tribunal AI companion already running'; exit 0 }
} catch { }
Start-Process -FilePath $directorPython -ArgumentList 'companion_server.py' -WorkingDirectory $directorRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $directorRoot 'data/companion.log') -RedirectStandardError (Join-Path $directorRoot 'data/companion.err') | Out-Null
Write-Output "Tribunal AI companion: http://127.0.0.1:$directorPort"
