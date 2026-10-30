param([switch]$SkipLive)
$ErrorActionPreference = 'Stop'
$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$token = [guid]::NewGuid().ToString('N').Substring(0, 10)
$network = "maie-r2-$token"
$dbName = "$network-db"
$runnerName = "$network-runner"
$databaseUrl = "postgresql+psycopg://postgres:r2-local-test@${dbName}:5432/r2_test"
$networkCreated = $false
$dbCreated = $false
$runnerCreated = $false

function Invoke-TestDocker {
    & docker @args
    if ($LASTEXITCODE -ne 0) {
        throw "Docker test step failed (exit $LASTEXITCODE)."
    }
}

try {
    Invoke-TestDocker info --format '{{.ServerVersion}}'
    Invoke-TestDocker network create $network | Out-Null
    $networkCreated = $true
    Invoke-TestDocker run -d --name $dbName --network $network --label maie.r2-test=true `
        -e POSTGRES_PASSWORD=r2-local-test -e POSTGRES_DB=r2_test postgres:16-alpine | Out-Null
    $dbCreated = $true
    Invoke-TestDocker run -d --name $runnerName --network $network --label maie.r2-test=true `
        --mount "type=bind,source=$repoRoot,target=/repo,readonly" -w /repo `
        -e PYTHONDONTWRITEBYTECODE=1 -e "WORKER_TEST_DATABASE_URL=$databaseUrl" `
        python:3.11-slim sleep infinity | Out-Null
    $runnerCreated = $true
    $ready = $false
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        & docker exec $dbName pg_isready -U postgres -d r2_test *> $null
        if ($LASTEXITCODE -eq 0) {
            $ready = $true
            break
        }
        Start-Sleep -Milliseconds 500
    }
    if (-not $ready) { throw 'Temporary PostgreSQL did not become ready.' }
    Invoke-TestDocker exec $runnerName sh -c `
        'cp -a /repo /tmp/install && cd /tmp/install && python -m pip install -e ".[dev]"'
    Invoke-TestDocker exec $runnerName python -m ruff check --no-cache .
    Invoke-TestDocker exec -e COVERAGE_FILE=/tmp/r2-coverage $runnerName python -m pytest `
        -p no:cacheprovider -q --cov=services.worker.app --cov-report=term-missing `
        tests/unit tests/integration
    Invoke-TestDocker exec -e "DATABASE_URL=$databaseUrl" $runnerName `
        python -m alembic upgrade head
    Invoke-TestDocker exec -e "DATABASE_URL=$databaseUrl" $runnerName `
        python -m alembic downgrade 20260713_0001
    Invoke-TestDocker exec -e "DATABASE_URL=$databaseUrl" $runnerName `
        python -m alembic upgrade head
    if (-not $SkipLive) {
        Invoke-TestDocker exec $runnerName python tests/support/run_worker_live.py
    }
    Invoke-TestDocker exec -e "DATABASE_URL=$databaseUrl" $runnerName `
        python -m scripts.recover_stale_jobs
    Write-Host 'R2 tests passed. Repository files were mounted read-only.'
}
finally {
    # Only these newly created, random-named test resources are removed.
    if ($runnerCreated) { & docker rm -f -v $runnerName | Out-Null }
    if ($dbCreated) { & docker rm -f -v $dbName | Out-Null }
    if ($networkCreated) { & docker network rm $network | Out-Null }
}
