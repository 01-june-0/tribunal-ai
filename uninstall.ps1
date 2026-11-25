# Removes Tribunal AI from Windows (docs/PACKAGING.md, phase 3). Paste into PowerShell:
#
#   powershell -ExecutionPolicy ByPass -c "irm https://raw.githubusercontent.com/01-june-0/tribunal-ai/main/uninstall.ps1 | iex"
#
# Stops the console, takes away the icons and the `tribunal` command. Kept: the records (shown at the end, delete
# that folder yourself if you want them gone), your projects and the practice folder, uv and the AI CLIs.
# ASCII and Windows PowerShell 5.1 compatible, like install.ps1; never calls `exit`.

function Find-TribunalUv {
    $found = Get-Command uv -ErrorAction SilentlyContinue
    if ($found) { return $found.Source }
    foreach ($candidate in @("$env:USERPROFILE\.local\bin\uv.exe", "$env:USERPROFILE\.cargo\bin\uv.exe")) {
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }
    return $null
}

function Uninstall-TribunalAI {
    $ErrorActionPreference = 'Continue'
    Write-Host ''
    Write-Host 'Removing Tribunal AI'
    $uv = Find-TribunalUv
    $tribunal = $null
    if ($uv) {
        $bin = (& $uv tool dir --bin | Select-Object -First 1).Trim()
        $candidate = Join-Path $bin 'tribunal.exe'
        if (Test-Path -LiteralPath $candidate) { $tribunal = $candidate }
    }
    if (-not $tribunal) {
        $found = Get-Command tribunal -ErrorAction SilentlyContinue
        if ($found) { $tribunal = $found.Source }
    }
    $records = $null
    if ($tribunal) {
        $encoding = [Console]::OutputEncoding
        try {
            [Console]::OutputEncoding = [Text.Encoding]::UTF8       # the report is UTF-8; a Korean user name stays readable
            $report = (& $tribunal doctor --json | Out-String) | ConvertFrom-Json
            $records = $report.home
        } catch { } finally { [Console]::OutputEncoding = $encoding }
        & $tribunal stop
        & $tribunal shortcut --remove
    }
    $listed = $false
    if ($uv) { $listed = [bool]((& $uv tool list 2>$null) -match '^tribunal-ai ') }
    if ($listed) {
        & $uv tool uninstall tribunal-ai
        if ($LASTEXITCODE -ne 0) {
            Write-Host 'Error: uv could not remove Tribunal AI. Close its windows and run this again.' -ForegroundColor Red
            $global:LASTEXITCODE = 1
            return
        }
    } else {
        Write-Host 'Tribunal AI is not installed (uv tool list).'
    }
    Write-Host ''
    Write-Host 'Removed.' -ForegroundColor Green
    if ($records) {
        Write-Host "  Records kept: $records"
        Write-Host '  Delete that folder yourself if you want them gone.'
    }
}

Uninstall-TribunalAI
