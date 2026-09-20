[CmdletBinding()]
param(
    [switch]$SkipOpenAIProbe,
    [switch]$NoReload
)

$ErrorActionPreference = "Stop"
$backendRoot = Split-Path -Parent $PSScriptRoot

Push-Location $backendRoot
try {
    if (-not $SkipOpenAIProbe) {
        & uv run python scripts/check_openai_runtime.py
        if ($LASTEXITCODE -ne 0) {
            exit $LASTEXITCODE
        }
    }

    $uvicornArguments = @("run", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000")
    if (-not $NoReload) {
        $uvicornArguments += "--reload"
    }
    & uv @uvicornArguments
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
