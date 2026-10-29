param(
    [ValidateSet('start', 'stop', 'status', 'check')]
    [string]$Action = 'start',
    [ValidateRange(1024, 65535)]
    [int]$Port = 18717
)
$ErrorActionPreference = 'Stop'
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$composeFile = Join-Path $repoRoot 'compose.midterm.yaml'
$dockerCommand = Get-Command docker -ErrorAction Stop
$composeExecutable = $dockerCommand.Source
$composePrefix = @('compose')
$pluginAvailable = $false
try {
    & $composeExecutable compose version *> $null
    $pluginAvailable = $LASTEXITCODE -eq 0
} catch { $pluginAvailable = $false }
if (-not $pluginAvailable) {
    $candidates = @(
        (Join-Path (Split-Path $dockerCommand.Source) '..\cli-plugins\docker-compose.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\resources\cli-plugins\docker-compose.exe'),
        (Join-Path $env:ProgramFiles 'Docker\Docker\resources\cli-plugins\docker-compose.exe')
    )
    $standalone = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not $standalone) { throw 'Docker Compose is unavailable. Install/enable Docker Desktop Compose.' }
    $composeExecutable = [IO.Path]::GetFullPath($standalone)
    $composePrefix = @()
}
& $dockerCommand.Source info --format '{{.ServerVersion}}'
if ($LASTEXITCODE -ne 0) { throw 'Start Docker Desktop (Linux containers), then retry.' }
$previousPort = $env:MIDTERM_DEMO_PORT
try {
    $env:MIDTERM_DEMO_PORT = "$Port"
    switch ($Action) {
        'start' { $composeArgs = @('up', '--build', '-d', '--wait', '--wait-timeout', '180') }
        'stop' { $composeArgs = @('down') }
        'status' { $composeArgs = @('ps') }
        'check' {
            $composeArgs = @('exec', '-T', 'midterm-demo', 'python', 'demo/midterm/check_demo.py')
        }
    }
    & $composeExecutable @composePrefix --project-directory $repoRoot -f $composeFile @composeArgs
    if ($LASTEXITCODE -ne 0) { throw "Midterm command failed: $Action" }
    if ($Action -eq 'start') { Write-Host "Midterm Demo: http://localhost:$Port/" }
} finally { $env:MIDTERM_DEMO_PORT = $previousPort }
