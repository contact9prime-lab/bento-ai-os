# AgentOS Windows bootstrap — run by the installer after files are copied.
#
# The installer's job stops at "files are in $InstallDir"; this script makes
# them runnable, prompting the system for what ISN'T there: it finds a suitable
# Python (or installs one via winget / python.org), builds a private venv,
# installs the bundled wheel, and writes the launchers. Optionally installs
# Ollama for local models. Nothing outside $InstallDir + HKCU is touched.
param(
    [Parameter(Mandatory = $true)][string]$InstallDir,
    [switch]$InstallOllama
)
$ErrorActionPreference = "Stop"
$MinPy = [version]"3.10"

function Find-Python {
    # the py launcher knows every installed CPython; prefer the newest
    foreach ($v in "3.13", "3.12", "3.11", "3.10") {
        try {
            $exe = & py "-$v" -c "import sys;print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $exe) { return $exe.Trim() }
        } catch {}
    }
    foreach ($name in "python3", "python") {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) {
            try {
                $ver = & $cmd.Source -c "import sys;print('%d.%d'%sys.version_info[:2])" 2>$null
                if ($LASTEXITCODE -eq 0 -and [version]$ver -ge $MinPy) { return $cmd.Source }
            } catch {}
        }
    }
    return $null
}

Write-Host "AgentOS bootstrap: looking for Python $MinPy+..."
$py = Find-Python

if (-not $py) {
    Write-Host "Python not found - installing it (winget)..."
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        & winget install --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
        # winget updates PATH for new shells; rescan via the py launcher + fresh PATH
        $env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" +
                    [Environment]::GetEnvironmentVariable("Path", "Machine")
        $py = Find-Python
    }
}
if (-not $py) {
    Write-Host "winget unavailable - downloading Python from python.org..."
    $pyUrl = "https://www.python.org/ftp/python/3.12.8/python-3.12.8-amd64.exe"
    $tmp = Join-Path $env:TEMP "python-installer.exe"
    Invoke-WebRequest -Uri $pyUrl -OutFile $tmp
    & $tmp /quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 | Out-Null
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" +
                [Environment]::GetEnvironmentVariable("Path", "Machine")
    $py = Find-Python
}
if (-not $py) { throw "Could not find or install Python $MinPy+. Install it from python.org and re-run the installer." }
Write-Host "Using $py"

$venv = Join-Path $InstallDir "venv"
Write-Host "Creating environment at $venv ..."
& $py -m venv --clear $venv
$pip = Join-Path $venv "Scripts\pip.exe"
$wheel = Get-ChildItem -Path $InstallDir -Filter "agentos-*.whl" | Select-Object -First 1
if (-not $wheel) { throw "No AgentOS wheel found in $InstallDir" }
Write-Host "Installing AgentOS (a minute or two)..."
& $pip install --quiet $wheel.FullName

# Launchers. The .cmd is the CLI; the .vbs files start without a console flash.
$pyw = Join-Path $venv "Scripts\pythonw.exe"
Set-Content -Path (Join-Path $InstallDir "agentos.cmd") -Value @"
@echo off
"$venv\Scripts\python.exe" -m agentos %*
"@
Set-Content -Path (Join-Path $InstallDir "agentos-app.vbs") -Value @"
' Open the AgentOS desktop window (no console).
CreateObject("WScript.Shell").Run """$pyw"" -m agentos app", 0, False
"@
Set-Content -Path (Join-Path $InstallDir "agentos-server.vbs") -Value @"
' Start the AgentOS server in the background (used by the run-at-login option).
CreateObject("WScript.Shell").Run """$pyw"" -m agentos serve --no-browser", 0, False
"@

if ($InstallOllama) {
    if (Get-Command ollama -ErrorAction SilentlyContinue) {
        Write-Host "Ollama already installed - skipping."
    } else {
        Write-Host "Installing Ollama (local AI models)..."
        $winget = Get-Command winget -ErrorAction SilentlyContinue
        if ($winget) {
            & winget install --id Ollama.Ollama --silent --accept-package-agreements --accept-source-agreements
        } else {
            Write-Host "winget unavailable - get Ollama at https://ollama.com/download (AgentOS also works with cloud API keys)."
        }
    }
}
Write-Host "Bootstrap complete."
