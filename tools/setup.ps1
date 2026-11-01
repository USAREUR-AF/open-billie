# Windows launcher for the shared Bash guided setup in Ubuntu WSL.
[CmdletBinding()]
param([string]$Distro = 'Ubuntu-24.04')
$ErrorActionPreference = 'Stop'
$wsl = Get-Command wsl.exe -ErrorAction SilentlyContinue
if (-not $wsl) { throw 'WSL is required. Install Ubuntu 24.04 with: wsl.exe --install -d Ubuntu-24.04' }
$bash = & wsl.exe -d $Distro --exec bash -lc 'command -v bash'
if ($LASTEXITCODE -ne 0 -or -not $bash) { throw "The WSL distribution '$Distro' is unavailable or does not have Bash. Install/launch Ubuntu 24.04, then retry." }
$repoWindows = Split-Path -Parent $PSScriptRoot
$repoWsl = (& wsl.exe -d $Distro --exec wslpath -a $repoWindows).Trim()
if ($LASTEXITCODE -ne 0 -or -not $repoWsl) { throw 'Could not map this checkout into WSL. Store the repository on a WSL-accessible drive and retry.' }
& wsl.exe -d $Distro --exec bash -lc "cd '$repoWsl' && bash tools/setup.sh"
exit $LASTEXITCODE
