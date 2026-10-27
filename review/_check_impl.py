"""Static consistency checks for the review-management skeleton.

No third-party imports: parses the Python files with ``ast``/``re`` so it can
run without SQLAlchemy / Pydantic installed (the sandbox runtime has neither).
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODELS = ROOT / "services" / "common" / "models.py"
SCHEMAS = ROOT / "services" / "common" / "schemas.py"
MIGRATION = ROOT / "alembic" / "versions" / "20261027_0002_review_management.py"

failures: list[str] = []


def check(cond: bool, message: str) -> None:
    if cond:
        print("  ok   ", message)
    else:
        print("  FAIL ", message)
        failures.append(message)


def parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


# ---------------------------------------------------------------------------
# models: table -> columns
# ---------------------------------------------------------------------------
model_tables: dict[str, list[str]] = {}
model_classes: list[str] = []
tree = parse(MODELS)
for node in tree.body:
    if not isinstance(node, ast.ClassDef):
        continue
    table = None
    columns: list[str] = []
    for item in node.body:
        if (
            isinstance(item, ast.Assign)
            and len(item.targets) == 1
            and isinstance(item.targets[0], ast.Name)
            and item.targets[0].id == "__tablename__"
            and isinstance(item.value, ast.Constant)
        ):
            table = item.value.value
        if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
            source = ast.get_source_segment(MODELS.read_text(encoding="utf-8"), item.value) or ""
            if "mapped_column" in source:
                columns.append(item.target.id)
    if table:
        model_tables[table] = columns
        model_classes.append(node.name)

# ---------------------------------------------------------------------------
# migration: create_table(...) blocks and add_column calls
# ---------------------------------------------------------------------------
text = MIGRATION.read_text(encoding="utf-8")
migration_tables: dict[str, list[str]] = {}
for match in re.finditer(r'op\.create_table\(\s*"(\w+)"', text):
    name = match.group(1)
    start = match.end()
    depth = 1
    pos = start
    while depth > 0 and pos < len(text):
        ch = text[pos]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        pos += 1
    block = text[start:pos]
    migration_tables[name] = re.findall(r'sa\.Column\(\s*"(\w+)"', block)

migration_added: dict[str, list[str]] = {}
for match in re.finditer(r'op\.add_column\(\s*"(\w+)",\s*sa\.Column\(\s*"(\w+)"', text):
    migration_added.setdefault(match.group(1), []).append(match.group(2))

print("== model tables ==")
for table, cols in model_tables.items():
    print(f"  {table}: {len(cols)} columns")
print("== migration create_table ==")
for table, cols in migration_tables.items():
    print(f"  {table}: {len(cols)} columns")
print("== migration add_column ==")
for table, cols in migration_added.items():
    print(f"  {table}: {cols}")

print("== checks: tables ==")
check(
    set(model_tables) == set(migration_tables) | {"jobs"},
    "model tables == 0002 tables + jobs (legacy cases removed by 0003)",
)
check("cases" not in model_tables, "legacy cases table removed from models")
for table in sorted(set(model_tables) & set(migration_tables)):
    model_cols = set(model_tables[table])
    migration_cols = set(migration_tables[table])
    check(
        model_cols == migration_cols,
        f"{table}: model columns == migration columns ({sorted(model_cols ^ migration_cols) or 'identical'})",
    )

print("== checks: jobs extension ==")
expected_jobs_added = {
    "comment_id",
    "batch_id",
    "max_attempts",
    "next_attempt_at",
    "lease_expires_at",
    "error_code",
}
check(
    set(migration_added.get("jobs", [])) == expected_jobs_added,
    f"jobs adds exactly {sorted(expected_jobs_added)}",
)
for col in expected_jobs_added:
    check(col in model_tables["jobs"], f"jobs model has {col}")

print("== checks: migration downgrade covers every new table ==")
downgrade = text.split("def downgrade", 1)[1]
for table in migration_tables:
    check(f'op.drop_table("{table}")' in downgrade, f"downgrade drops {table}")
check(
    'op.drop_constraint("fk_jobs_comment_id"' in downgrade
    and 'op.drop_column("jobs", "comment_id")' in downgrade,
    "downgrade removes jobs.comment_id after its FK",
)

print("== checks: schemas expose the agreed contracts ==")
schema_tree = parse(SCHEMAS)
schemas = {
    node.name
    for node in schema_tree.body
    if isinstance(node, ast.ClassDef)
}
required = {
    "NormalizedComment",
    "BatchCreateResponse",
    "BatchRead",
    "BatchErrorRead",
    "CommentRead",
    "CommentDetailRead",
    "CommentIssueRead",
    "IssueRead",
    "IssueDetailRead",
    "IssueActionRequest",
    "IssueActionRead",
    "LinkDecisionRequest",
    "AnalysisJobRead",
    "ExtractionRequest",
    "ExtractedIssue",
    "ExtractionResult",
    "GroupSuggestionRequest",
    "GroupSuggestionResult",
}
for name in sorted(required):
    check(name in schemas, f"schemas has {name}")
removed_legacy = {"CaseCreate", "CaseRead", "JobRead", "TriageRequest", "TriageResponse"}
for name in sorted(removed_legacy):
    check(name not in schemas, f"legacy schema removed: {name}")

print("== checks: no duplicate column names inside a table ==")
for table, cols in model_tables.items():
    check(len(cols) == len(set(cols)), f"{table}: no duplicate columns")
for table, cols in migration_tables.items():
    check(len(cols) == len(set(cols)), f"{table}: no duplicate columns in migration")

print()
if failures:
    print(f"RESULT: {len(failures)} failure(s)")
    sys.exit(1)
print("RESULT: all static checks passed")
