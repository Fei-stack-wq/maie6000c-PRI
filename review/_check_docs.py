"""Static doc/code consistency checks for docs/architecture.md vs models.py."""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ARCH = ROOT / "docs" / "architecture.md"
MODELS = ROOT / "services" / "common" / "models.py"

failures: list[str] = []


def check(cond: bool, message: str) -> None:
    print(("  ok    " if cond else "  FAIL  ") + message)
    if not cond:
        failures.append(message)


# ---------------------------------------------------------------- model fields
tree = ast.parse(MODELS.read_text(encoding="utf-8"), filename=str(MODELS))
model_tables: dict[str, list[str]] = {}
for node in tree.body:
    if not isinstance(node, ast.ClassDef):
        continue
    table = None
    columns: list[str] = []
    for item in node.body:
        if (
            isinstance(item, ast.Assign)
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

# -------------------------------------------------------------- doc §6.2 table
doc = ARCH.read_text(encoding="utf-8")
start = doc.index("### 6.2")
end = doc.index("### 6.3")
section = doc[start:end]

doc_tables: dict[str, list[str]] = {}
for line in section.splitlines():
    match = re.match(r"^\|\s*`(\w+)`\s*\|([^|]*)\|", line)
    if not match:
        continue
    table = match.group(1)
    field_cell = match.group(2)
    fields: list[str] = []
    for token in field_cell.split(","):
        token = re.sub(r"（[^）]*）", "", token)
        token = token.replace("`", "").strip()
        token = token.split()[0] if token else ""
        if re.fullmatch(r"[a-z_]+", token or ""):
            fields.append(token)
    doc_tables[table] = fields

print("== doc §6.2 tables parsed ==")
for table, fields in doc_tables.items():
    print(f"  {table}: {len(fields)} fields")

print("== doc §6.2 vs models ==")
for table, fields in doc_tables.items():
    if table not in model_tables:
        check(False, f"{table}: documented but missing in models")
        continue
    model_fields = set(model_tables[table])
    documented = set(fields)
    missing = sorted(model_fields - documented)
    extra = sorted(documented - model_fields)
    check(not missing, f"{table}: doc covers all model fields (missing: {missing or 'none'})")
    check(not extra, f"{table}: doc has no unknown fields (extra: {extra or 'none'})")

print("== doc state machines ==")
for phrase in [
    "failed --> pending",
    "claimed --> pending",
    "confirmed --> resolved",
    "resolved --> confirmed",
    "dismissed --> proposed",
    "suggested --> accepted",
    "accepted --> rejected",
]:
    check(phrase in doc, f"state machine has `{phrase}`")
for forbidden in ["failed --> claimed", "failed → claimed"]:
    hits = [line for line in doc.splitlines() if forbidden in line and "禁止" not in line]
    check(not hits, f"no forbidden transition `{forbidden}` outside an explicit prohibition")

print("== doc error codes vs models.ErrorCode ==")
enum_values = set()
for node in tree.body:
    if isinstance(node, ast.ClassDef) and node.name == "ErrorCode":
        for item in node.body:
            if isinstance(item, ast.Assign) and isinstance(item.value, ast.Constant):
                enum_values.add(item.value.value)
codes = set(re.findall(r"^\|\s*`([a-z_]+)`\s*\|", doc, flags=re.MULTILINE))
error_section = doc[doc.index("### 10.1"): doc.index("### 10.2")]
doc_codes = set(re.findall(r"`([a-z_]+)`", error_section)) & (codes | enum_values)
for value in sorted(enum_values):
    check(value in doc_codes, f"error code {value} documented")
check(not (doc_codes - enum_values - {"error_code"}), f"no undocumented error codes ({sorted(doc_codes - enum_values - {'error_code'})})")

print("== doc headings ==")
headings = [line for line in doc.splitlines() if line.startswith("## ")]
print("  H2 count:", len(headings))
for expected in ["## 4.", "## 6.", "## 7.", "## 9.", "## 12.", "## 13."]:
    check(any(h.startswith(expected) for h in headings), f"section {expected} present")

print("== doc figure ==")
fig = ROOT / "docs" / "assets" / "fig1_end_to_end_flow.png"
check(fig.exists() and fig.stat().st_size > 10_000, "figure 1 exists in docs/assets/")
check("./assets/fig1_end_to_end_flow.png" in doc, "doc references figure 1 with relative path")

print()
if failures:
    print(f"RESULT: {len(failures)} failure(s)")
    sys.exit(1)
print("RESULT: all doc/code consistency checks passed")
