"""The published benchmark cannot drift from the engine.

benchmarks/results/deepset-prompt-injections.json is what /airlock shows
the world. This recomputes it from the committed dataset rows and the
current rules, and fails if the committed numbers differ -- so a rule
change without a re-run (or a re-run without a commit) is caught here,
never by a visitor. The web copy of the results is pinned to the same
file by apps/web/tests/airlock-page.test.ts.
"""

import json
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_ROOT / "scripts"))

RESULTS = API_ROOT / "benchmarks" / "results" / "deepset-prompt-injections.json"
DATA = API_ROOT / "benchmarks" / "data" / "deepset-prompt-injections.jsonl"


def test_the_committed_results_match_the_engine_on_the_committed_rows() -> None:
    import airlock_benchmark as bench

    rows = [json.loads(line) for line in DATA.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(rows) == 662, "the cached dataset is the full train+test set"
    fresh = bench.evaluate(rows)
    published = json.loads(RESULTS.read_text(encoding="utf-8"))
    for key in ("overall", "english", "german"):
        assert fresh[key] == published[key], f"{key}: re-run scripts/airlock_benchmark.py and commit the results"
    assert fresh["engine"]["rules"] == published["engine"]["rules"]
    assert [m["text"] for m in fresh["misses"]] == [m["text"] for m in published["misses"]]
    assert [f["text"] for f in fresh["false_positives"]] == [f["text"] for f in published["false_positives"]]


def test_the_published_numbers_are_the_honest_shape() -> None:
    published = json.loads(RESULTS.read_text(encoding="utf-8"))
    overall = published["overall"]
    # The dataset's positives are broader than Airlock's definition of an
    # injection (off-topic questions, role-play), so recall is low and the
    # page must say so. The false-positive rate on 399 legitimate texts is
    # the number that decides adoption, and it must stay at zero.
    assert overall["rows"] == 662 and overall["injections"] == 263 and overall["legitimate"] == 399
    assert overall["false_positives"] == 0 and overall["false_positive_rate"] == 0.0
    assert 0.0 < overall["recall"] < 0.9, "a recall near 1.0 on this dataset would mean overfitting to it"
    assert len(published["misses"]) == overall["injections"] - overall["caught"]
    assert published["license"] == "CC BY 4.0" and "deepset" in published["dataset"]
    assert published["engine"]["deep_scan"] is False


def test_the_website_rule_pages_match_the_engine() -> None:
    """apps/web/app/airlock/rules.json feeds /airlock/rules/[id]; it must be
    exactly what rules.py says, and must never carry a pattern."""
    import export_rules

    web = json.loads((API_ROOT.parent / "web" / "app" / "airlock" / "rules.json").read_text(encoding="utf-8"))
    assert web == export_rules.export(), "re-run scripts/export_rules.py and commit rules.json"
    assert all("pattern" not in rule for rule in web["rules"])
    assert all(rule["description"] for rule in web["rules"])
