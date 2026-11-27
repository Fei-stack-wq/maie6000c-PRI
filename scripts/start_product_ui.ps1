param([ValidateSet('start', 'stop', 'status')][string]$Action = 'start')
$ErrorActionPreference = 'Stop'
$repoPath = Split-Path -Parent $PSScriptRoot
Push-Location $repoPath
try {
    $composeCommand = 'docker'
    $composePrefix = @('compose')
    # Windows PowerShell 5.1 turns native stderr into PowerShell errors.
    # An unavailable plugin is an expected probe result, not a startup failure.
    $probePreference = $ErrorActionPreference
    $composeAvailable = $false
    try {
        $ErrorActionPreference = 'SilentlyContinue'
        & docker compose version *> $null
        $composeAvailable = ($LASTEXITCODE -eq 0)
    } finally { $ErrorActionPreference = $probePreference }
    if (-not $composeAvailable) {
        $composeCommand = Join-Path $env:LOCALAPPDATA 'Programs/DockerDesktop/resources/cli-plugins/docker-compose.exe'
        if (-not (Test-Path -LiteralPath $composeCommand)) {
            throw 'Docker Compose was not found. Install Docker Desktop with Compose.'
        }
        $composePrefix = @()
    }
    $composeArgs = @('-p', 'maie6000c-pri', '-f', 'compose.yaml')
    function Invoke-ProductCompose {
        param([string[]]$ComposeArguments)
        $nativePreference = $ErrorActionPreference
        try {
            # Compose writes ordinary build/progress output to stderr too.
            # Judge success by its exit code on both PowerShell 5.1 and 7.
            $ErrorActionPreference = 'Continue'
            & $composeCommand @composePrefix @composeArgs @ComposeArguments 2>&1 |
                ForEach-Object { Write-Host $_ }
            $composeExitCode = $LASTEXITCODE
        } finally { $ErrorActionPreference = $nativePreference }
        if ($composeExitCode -ne 0) {
            throw "Docker Compose failed (exit $composeExitCode). Check the output above."
        }
    }
    if ($Action -eq 'start') {
        if (-not (Test-Path -LiteralPath '.env')) {
            Copy-Item -LiteralPath '.env.example' -Destination '.env'
        }
        Invoke-ProductCompose -ComposeArguments @('up', '-d', '--build', '--wait')
        $port = if ($env:API_HOST_PORT) { $env:API_HOST_PORT } else { '8000' }
        # Compose may read a port override from .env. Read only this non-secret field.
        if (-not $env:API_HOST_PORT) {
            $portLine = Get-Content -LiteralPath '.env' | Where-Object { $_ -match '^API_HOST_PORT=\d+$' } | Select-Object -Last 1
            if ($portLine) { $port = $portLine.Split('=')[1] }
        }
        Write-Host "Open http://localhost:$port/ui/"
    } elseif ($Action -eq 'stop') {
        Invoke-ProductCompose -ComposeArguments @('down')
    } else {
        Invoke-ProductCompose -ComposeArguments @('ps')
    }
} finally { Pop-Location }
