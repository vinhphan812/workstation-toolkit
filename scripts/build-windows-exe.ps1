$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot

python -m pip install -e .
python -m pip install "pyinstaller==6.22.3"
python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --name workstation `
    --paths src `
    --collect-all psutil `
    src/workstation/__main__.py

$Exe = Join-Path $RepoRoot "dist/workstation.exe"
if (-not (Test-Path $Exe)) { throw "Expected executable missing: $Exe" }

& $Exe --help | Out-Null
if ($LASTEXITCODE -ne 0) { throw "--help failed with exit code $LASTEXITCODE" }
& $Exe --version
if ($LASTEXITCODE -ne 0) { throw "--version failed with exit code $LASTEXITCODE" }

$ProbePath = Join-Path $env:TEMP "workstation-loc-probe"
New-Item -ItemType Directory -Force -Path $ProbePath | Out-Null
Set-Content -Path (Join-Path $ProbePath "sample.py") -Value "print('hello')" -Encoding utf8
$Json = & $Exe --json loc --path $ProbePath --top 3 | Out-String
if ($LASTEXITCODE -ne 0) { throw "LOC JSON smoke test failed with exit code $LASTEXITCODE" }
$Report = $Json | ConvertFrom-Json
if (-not $Report.ok -or -not $Report.languages) { throw "LOC JSON contract smoke test failed" }

$OutName = "workstation-toolkit-windows-x64.exe"
Copy-Item $Exe (Join-Path $RepoRoot "dist/$OutName") -Force
Write-Host "Built and smoke-tested dist/$OutName"
