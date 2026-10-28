"""Start isolated real services, run smoke tests and verify graceful worker shutdown.

Run in an isolated container with DATABASE_URL and WORKER_TEST_DATABASE_URL pointing
to the same disposable *_test database. No existing application database is reset.
"""
import os
from pathlib import Path
import subprocess
import sys
import time

import httpx
from sqlalchemy.engine import make_url


def main():
    url = os.environ["WORKER_TEST_DATABASE_URL"]
    if not make_url(url).database.endswith("_test"):
        raise RuntimeError("An explicitly named *_test database is required")
    env = dict(os.environ, DATABASE_URL=url, AI_SERVICE_URL="http://127.0.0.1:18200",
               WORKER_RETRY_BASE_SECONDS="0.1", WORKER_RETRY_MAX_SECONDS="1",
               WORKER_POLL_SECONDS="0.1", WORKER_REQUEST_TIMEOUT_SECONDS="5",
               SMOKE_BASE_URL="http://127.0.0.1:18000", WORKER_LIVE_FAULT_PROXY="1")
    commands = [
        ("ai", [sys.executable, "-m", "uvicorn", "services.ai.app.main:app",
                "--host", "127.0.0.1", "--port", "18100"]),
        ("proxy", [sys.executable, "-m", "uvicorn", "fault_ai:app",
                   "--app-dir", "tests/support", "--host", "127.0.0.1", "--port", "18200"]),
        ("api", [sys.executable, "-m", "uvicorn", "services.api.app.main:app",
                 "--host", "127.0.0.1", "--port", "18000"]),
        ("worker", [sys.executable, "-m", "services.worker.app.main"]),
    ]
    processes, logs = [], []
    result = 1
    try:
        for name, command in commands:
            log = open(f"/tmp/r2-live-{name}.log", "w")
            logs.append(log)
            processes.append((name, subprocess.Popen(command, env=env, stdout=log,
                                                     stderr=subprocess.STDOUT)))
        for port, path in ((18100, "health/live"), (18200, "health/live"),
                           (18000, "health/ready"), (8200, "metrics")):
            deadline = time.monotonic() + 15
            while True:
                try:
                    if httpx.get(f"http://127.0.0.1:{port}/{path}", timeout=1).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                if time.monotonic() >= deadline:
                    raise RuntimeError(f"Service on port {port} did not become ready")
                time.sleep(0.1)
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q", "tests/smoke"],
            env=env, check=False,
        ).returncode
    finally:
        graceful = False
        for name, process in reversed(processes):
            process.terminate()
            try:
                code = process.wait(timeout=10)
                if name == "worker":
                    graceful = code == 0
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        for log in logs:
            log.close()
        worker_log = Path("/tmp/r2-live-worker.log").read_text()
        print("Worker graceful shutdown:", graceful and "worker_stopped" in worker_log)
        if not graceful or "worker_stopped" not in worker_log:
            result = 1
        if result:
            for name, _ in processes:
                print(f"--- {name} ---")
                print(Path(f"/tmp/r2-live-{name}.log").read_text()[-8000:])
    return result


if __name__ == "__main__":
    raise SystemExit(main())
