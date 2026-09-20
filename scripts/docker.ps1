[CmdletBinding()]
param(
    [ValidateSet("up", "start", "stop", "status", "logs", "down")]
    [string]$Action = "up"
)

$ErrorActionPreference = "Stop"

# Always run Compose from the repository root so relative environment files work.
$repositoryRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repositoryRoot

& docker version --format "{{.Server.Version}}" | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Docker Desktop is not ready. Start Docker Desktop and run this command again."
}

$composeArguments = @("compose", "--env-file", ".env", "--env-file", "infra/.env")
$actionArguments = switch ($Action) {
    "up" { @("up", "-d", "--build", "--wait") }
    "start" { @("start") }
    "stop" { @("stop") }
    "status" { @("ps", "--all") }
    "logs" { @("logs", "--tail", "100") }
    # Deliberately omit --volumes so local documents and database data remain intact.
    "down" { @("down") }
}

& docker @composeArguments @actionArguments
if ($LASTEXITCODE -ne 0) {
    throw "LicenceIQ Docker action '$Action' failed."
}

if ($Action -in @("up", "start")) {
    Write-Host "LicenceIQ is ready at http://127.0.0.1:3000"
}
