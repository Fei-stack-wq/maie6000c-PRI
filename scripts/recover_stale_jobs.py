"""Recover expired jobs using the same locking and retry limits as the worker."""
import json

from services.common.config import configure_logging
from services.worker.app.main import recover_stale_jobs


if __name__ == "__main__":
    configure_logging()
    print(json.dumps({"recovered": recover_stale_jobs()}))
