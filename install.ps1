# Install Studio from this folder on Windows: a virtual environment in .venv, then a Start menu entry.
#   powershell -ExecutionPolicy Bypass -File install.ps1            install or update
#   powershell -ExecutionPolicy Bypass -File install.ps1 --desktop  also put a shortcut on the desktop
# (Prefer not to install Python? Download Studio-windows.zip from the Releases page instead.)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$py = $null
foreach ($c in @(@("py", "-3"), @("python"))) {
    try {
        & $c[0] $c[1..9] -c "import sys; sys.exit(sys.version_info < (3, 11))" 2>$null
        if ($LASTEXITCODE -eq 0) { $py = $c; break }
    } catch { }
}
if (-not $py) { Write-Error "Studio needs Python 3.11 or newer: https://www.python.org/downloads/" }

if (-not (Test-Path .venv)) { & $py[0] $py[1..9] -m venv .venv }
& .venv\Scripts\python.exe -m pip install --quiet --upgrade pip
& .venv\Scripts\python.exe -m pip install --quiet -e ".[app]"
& .venv\Scripts\studio.exe install @args

Write-Host ""
Write-Host "Studio is installed. Open it from the Start menu, then right-click its taskbar icon > Pin to taskbar."
Write-Host "Connect Claude Code:  claude mcp add studio --scope user -- `"$PWD\.venv\Scripts\studio.exe`" mcp"
