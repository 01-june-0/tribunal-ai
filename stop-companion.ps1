$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try { $directorPort = [int](& (Get-Command python).Source -m core.companion_config) } finally { Pop-Location }
$directorListeners = Get-NetTCPConnection -LocalPort $directorPort -State Listen -ErrorAction SilentlyContinue
foreach ($directorListener in $directorListeners) {
    $directorProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$($directorListener.OwningProcess)"
    if ($directorProcess.CommandLine -match 'companion_server\.py') {
        Stop-Process -Id $directorListener.OwningProcess
        Write-Output 'AI DEV companion stopped; records and worktrees preserved.'
    } else { throw "Port $directorPort belongs to another process; not stopped." }
}
