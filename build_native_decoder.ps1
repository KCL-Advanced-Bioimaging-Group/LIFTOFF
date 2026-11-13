$ErrorActionPreference = 'Stop'
$sourceRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location -LiteralPath $sourceRoot
try {
    & (Join-Path $sourceRoot '.venv\Scripts\python.exe') 'tools/build.py' --native-only @args
    if ($LASTEXITCODE -ne 0) { throw 'Native build failed' }
} finally {
    Pop-Location
}
