param(
    [string]$BaseUrl = "http://localhost:8000",
    [string]$AiUrl = "http://localhost:8100",
    [switch]$SkipUp
)
$ErrorActionPreference = "Stop"
$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
Set-Location $repoRoot

function Invoke-Checked {
    param([scriptblock]$Block, [string]$Label)
    & $Block
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed (exit $LASTEXITCODE)."
    }
}

function Dump-Logs {
    Write-Host "---- docker compose logs ai (tail) ----"
    & docker compose logs --tail 80 ai
    Write-Host "---- docker compose logs worker (tail) ----"
    & docker compose logs --tail 80 worker
}

if (-not (Test-Path (Join-Path $repoRoot ".env"))) {
    Copy-Item (Join-Path $repoRoot ".env.example") (Join-Path $repoRoot ".env")
    Write-Host "Created .env from .env.example"
}

try {
    if (-not $SkipUp) {
        Write-Host "Building and starting Compose stack (AI installs sentence-transformers)..."
        Invoke-Checked { docker compose up --build -d --wait } "docker compose up"
    }

    Write-Host "Checking AI embedder backend..."
    Invoke-Checked {
        docker compose exec -T ai python scripts/probe_grouping_backend.py
    } "AI embedder probe"

    Write-Host "Running grouping smoke tests against $BaseUrl ..."
    $env:SMOKE_BASE_URL = $BaseUrl
    $env:SMOKE_AI_URL = $AiUrl
    $env:GROUPING_SIMILARITY_THRESHOLD = "0.45"
    Invoke-Checked {
        uv run python -m pytest -q tests/smoke/test_grouping_flow.py
    } "grouping smoke pytest"

    Write-Host "Grouping e2e passed (extract + semantic grouping)."
}
catch {
    Dump-Logs
    throw
}
