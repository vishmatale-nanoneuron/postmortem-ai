#!/usr/bin/env python3
"""Airlock against a public prompt-injection dataset, numbers published as
they come out.

    PYTHONPATH=apps/api python apps/api/scripts/airlock_benchmark.py            # run on the cached data
    PYTHONPATH=apps/api python apps/api/scripts/airlock_benchmark.py --refresh  # re-download first

Dataset: deepset/prompt-injections (Hugging Face), CC BY 4.0, 662 labelled
texts (label 1 = injection, 0 = legitimate), English and German. It is
cached under benchmarks/data/ so the run is reproducible offline and the
numbers on the website can be re-derived from the committed rows.

What is measured, and what is not:
- "caught" means the engine's verdict was flag or block. Recall is caught
  injections over all injections; the false-positive rate is legitimate
  texts that were flagged or blocked over all legitimate texts.
- The rules are English. The dataset is roughly half German, so the
  numbers are reported overall AND for the English rows only, split by a
  stopword heuristic (benchmarks/results/*.json says which rows landed
  where). The deep scan (Gemini) is not run here: it costs money per call,
  and the point of this file is the free, deterministic layer.
- Every miss and every false positive is written to the results file, so
  the website can list them rather than a single flattering number.

The results file is what /airlock renders and what tests/test_airlock_
benchmark.py pins: change the engine, re-run this, commit both.
"""

import argparse
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
API_ROOT = HERE.parent
sys.path.insert(0, str(API_ROOT))

from app.airlock import Detector  # noqa: E402
from app.airlock.rules import RULES  # noqa: E402

DATASET = "deepset/prompt-injections"
DATASET_URL = "https://huggingface.co/datasets/deepset/prompt-injections"
LICENSE = "CC BY 4.0"
ROWS_API = "https://datasets-server.huggingface.co/rows?dataset=deepset%2Fprompt-injections&config=default&split={split}&offset={offset}&length=100"
SPLITS = ("train", "test")

DATA_FILE = API_ROOT / "benchmarks" / "data" / "deepset-prompt-injections.jsonl"
RESULTS_FILE = API_ROOT / "benchmarks" / "results" / "deepset-prompt-injections.json"

# German is the other language in this dataset. A text is called German
# when it carries several of these function words; English otherwise. The
# split is a heuristic and is reported as such.
_GERMAN = re.compile(
    r"\b(und|nicht|ist|ich|das|die|der|ein|eine|sie|wir|du|bitte|alle|deine|dein|vergiss|ignoriere|"
    r"anweisungen|jetzt|auch|mit|für|über|wie|was|kannst|schreibe|sag)\b",
    re.IGNORECASE,
)


def language_of(text: str) -> str:
    hits = len(_GERMAN.findall(text))
    words = max(1, len(text.split()))
    return "de" if hits >= 2 and hits / words >= 0.08 else "en"


def download() -> list[dict]:
    rows: list[dict] = []
    for split in SPLITS:
        offset = 0
        while True:
            response = httpx.get(ROWS_API.format(split=split, offset=offset), timeout=30.0)
            response.raise_for_status()
            page = response.json().get("rows", [])
            for entry in page:
                row = entry["row"]
                rows.append({"split": split, "text": row["text"], "label": int(row["label"])})
            if len(page) < 100:
                break
            offset += 100
    return rows


def load_rows(refresh: bool) -> list[dict]:
    if refresh or not DATA_FILE.exists():
        rows = download()
        DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        with DATA_FILE.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        return rows
    with DATA_FILE.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def evaluate(rows: list[dict]) -> dict:
    detector = Detector()
    results = []
    for row in rows:
        detection = detector.scan(row["text"])
        results.append(
            {
                "split": row["split"],
                "label": row["label"],
                "language": language_of(row["text"]),
                "verdict": detection.verdict,
                "score": detection.score,
                "rules": [match.rule_id for match in detection.matches],
                "text": row["text"],
            }
        )

    def metrics(subset: list[dict]) -> dict:
        injections = [r for r in subset if r["label"] == 1]
        legitimate = [r for r in subset if r["label"] == 0]
        caught = [r for r in injections if r["verdict"] != "allow"]
        blocked = [r for r in injections if r["verdict"] == "block"]
        false_positives = [r for r in legitimate if r["verdict"] != "allow"]
        return {
            "rows": len(subset),
            "injections": len(injections),
            "legitimate": len(legitimate),
            "caught": len(caught),
            "blocked": len(blocked),
            "recall": round(len(caught) / len(injections), 4) if injections else None,
            "block_rate": round(len(blocked) / len(injections), 4) if injections else None,
            "false_positives": len(false_positives),
            "false_positive_rate": round(len(false_positives) / len(legitimate), 4) if legitimate else None,
            "precision": round(len(caught) / (len(caught) + len(false_positives)), 4)
            if (caught or false_positives)
            else None,
        }

    english = [r for r in results if r["language"] == "en"]
    german = [r for r in results if r["language"] == "de"]
    rule_hits = Counter(rule for r in results if r["label"] == 1 for rule in r["rules"])

    def excerpt(r: dict) -> dict:
        return {
            "split": r["split"],
            "language": r["language"],
            "score": r["score"],
            "verdict": r["verdict"],
            "rules": r["rules"],
            "text": r["text"][:200],
        }

    return {
        "dataset": DATASET,
        "dataset_url": DATASET_URL,
        "license": LICENSE,
        "generated_at": int(time.time() * 1000),
        "engine": {"rules": len(RULES), "families": sorted({rule.family for rule in RULES}), "deep_scan": False},
        "language_split": "heuristic: German function-word density; reported per row in misses/false_positives",
        "overall": metrics(results),
        "english": metrics(english),
        "german": metrics(german),
        "top_rules_on_injections": [{"rule": rule, "hits": hits} for rule, hits in rule_hits.most_common(10)],
        "misses": [excerpt(r) for r in results if r["label"] == 1 and r["verdict"] == "allow"],
        "false_positives": [excerpt(r) for r in results if r["label"] == 0 and r["verdict"] != "allow"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="re-download the dataset before running")
    args = parser.parse_args()

    rows = load_rows(refresh=args.refresh)
    report = evaluate(rows)
    RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_FILE.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    for name in ("overall", "english", "german"):
        m = report[name]
        print(
            f"{name:8} rows={m['rows']:4}  injections={m['injections']:3}  caught={m['caught']:3} "
            f"(recall {m['recall']})  blocked={m['blocked']:3}  legit={m['legitimate']:3}  "
            f"false_pos={m['false_positives']:2} (fpr {m['false_positive_rate']})"
        )
    print(f"misses: {len(report['misses'])}   false positives: {len(report['false_positives'])}")
    print(f"wrote {RESULTS_FILE.relative_to(API_ROOT.parent.parent)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
