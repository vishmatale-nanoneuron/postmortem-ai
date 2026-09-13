#!/usr/bin/env python3
"""Export the detection rules (id, family, weight, description -- never
the pattern) for the website's per-rule pages.

    PYTHONPATH=apps/api python apps/api/scripts/export_rules.py

Writes apps/web/app/airlock/rules.json, the file /airlock/rules/[id] is
generated from at build time. tests/test_airlock_public_benchmark.py fails
if that file drifts from rules.py, so a rule change is re-exported and
committed with the rule, never later.
"""

import json
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_ROOT))

from app.airlock.rules import RULES  # noqa: E402

OUT = API_ROOT.parent / "web" / "app" / "airlock" / "rules.json"


def export() -> dict:
    return {
        "count": len(RULES),
        "families": sorted({rule.family for rule in RULES}),
        "rules": [
            {"id": rule.id, "family": rule.family, "weight": rule.weight, "description": rule.description}
            for rule in RULES
        ],
    }


if __name__ == "__main__":
    OUT.write_text(json.dumps(export(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(API_ROOT.parent.parent)} ({len(RULES)} rules)")
