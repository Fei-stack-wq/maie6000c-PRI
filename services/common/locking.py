"""Shared category locks: Worker and human regrouping acquire the same ordered keys."""
import hashlib

from sqlalchemy import text
from sqlalchemy.orm import Session


def lock_issue_groups(
    db: Session, platform: str, shop_id: str, product_id: str, categories,
) -> None:
    if db.get_bind().dialect.name != "postgresql":
        return
    for category in sorted(set(categories)):
        raw = repr((platform, shop_id, product_id, category))
        key = int.from_bytes(hashlib.sha256(raw.encode()).digest()[:8], "big", signed=True)
        db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})
