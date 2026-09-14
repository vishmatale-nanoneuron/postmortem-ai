#!/usr/bin/env python3
"""Evaluate the deep-scan classifier (the model behind `"deep": true`) on
the held-out split, the same way the rule engine is benchmarked.

    GEMINI_API_KEY=... PYTHONPATH=apps/api python apps/api/scripts/airlock_semantic_eval.py
    ... --limit 20        # a cheap trial
    ... --concurrency 4   # parallel calls (default 4)

Reads benchmarks/finetune/eval.jsonl (never the training rows), sends
each text through app/airlock/semantic.semantic_opinion -- the exact
prompt, provider and parser production uses -- and reports:

- model alone: recall on injections, false-positive rate on legitimate
  text, and how many calls came back unavailable/unparseable;
- rules + model: what a real deep scan answers, i.e. the rule score
  combined with the model's weight by noisy-OR (semantic.combine) at the
  default thresholds -- recall and false positives of the whole product;
- per language, plus every miss and every false alarm verbatim.

Writes benchmarks/results/deep-scan-eval.json. This costs money (one
model call per row) and needs a key, so it is run by hand and the result
is committed; tests pin the file's internal consistency, not its
regeneration. The training set is never scored: a number on rows the
model could later be tuned on would be meaningless.
"""

import argparse
import asyncio
import json
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
API_ROOT = HERE.parent
sys.path.insert(0, str(API_ROOT))

from app.ai.model_router import create_model_provider  # noqa: E402
from app.airlock.semantic import SEMANTIC_PROMPT_VERSION, combine, semantic_opinion  # noqa: E402
from app.settings import get_settings  # noqa: E402

EVAL_FILE = API_ROOT / "benchmarks" / "finetune" / "eval.jsonl"
RESULTS_FILE = API_ROOT / "benchmarks" / "results" / "deep-scan-eval.json"


def metrics(rows: list[dict], caught_key: str) -> dict:
    injections = [r for r in rows if r["label"] == 1]
    legitimate = [r for r in rows if r["label"] == 0]
    caught = [r for r in injections if r[caught_key]]
    false_positives = [r for r in legitimate if r[caught_key]]
    return {
        "rows": len(rows),
        "injections": len(injections),
        "legitimate": len(legitimate),
        "caught": len(caught),
        "recall": round(len(caught) / len(injections), 4) if injections else None,
        "false_positives": len(false_positives),
        "false_positive_rate": round(len(false_positives) / len(legitimate), 4) if legitimate else None,
        "precision": round(len(caught) / (len(caught) + len(false_positives)), 4) if (caught or false_positives) else None,
    }


async def evaluate(rows: list[dict], provider_factory, concurrency: int) -> list[dict]:
    semaphore = asyncio.Semaphore(concurrency)

    async def one(row: dict) -> dict:
        async with semaphore:
            started = time.perf_counter()
            opinion = await semantic_opinion(provider_factory, row["text"])
            latency_ms = int((time.perf_counter() - started) * 1000)
        combined_score, combined_verdict = combine(row["rule_score"], opinion)
        return {
            **row,
            "model_status": opinion.status,
            "model_injection": opinion.injection,
            "model_confidence": opinion.confidence,
            "model_family": opinion.family,
            "model_reason": opinion.reason,
            "model_weight": opinion.weight,
            "model_caught": opinion.status == "ok" and opinion.injection and opinion.confidence >= 0.5,
            "combined_score": combined_score,
            "combined_verdict": combined_verdict,
            "combined_caught": combined_verdict != "allow",
            "rules_caught": row["rule_score"] >= 0.40,
            "latency_ms": latency_ms,
        }

    return await asyncio.gather(*(one(row) for row in rows))


def report(results: list[dict], model_name: str) -> dict:
    def excerpt(r: dict) -> dict:
        return {
            "language": r["language"],
            "source": r["source"],
            "rule_score": r["rule_score"],
            "model_injection": r["model_injection"],
            "model_confidence": r["model_confidence"],
            "model_reason": r["model_reason"],
            "combined_verdict": r["combined_verdict"],
            "text": r["text"][:200],
        }

    english = [r for r in results if r["language"] == "en"]
    german = [r for r in results if r["language"] == "de"]
    statuses = Counter(r["model_status"] for r in results)
    latencies = sorted(r["latency_ms"] for r in results)
    return {
        "eval_file": "benchmarks/finetune/eval.jsonl",
        "prompt_version": SEMANTIC_PROMPT_VERSION,
        "model": model_name,
        "generated_at": int(time.time() * 1000),
        "calls": {"total": len(results), "ok": statuses.get("ok", 0), "unavailable": statuses.get("unavailable", 0)},
        "latency_ms": {"p50": latencies[len(latencies) // 2] if latencies else None, "p95": latencies[int(len(latencies) * 0.95) - 1] if latencies else None},
        "rules_only": metrics(results, "rules_caught"),
        "model_only": {"overall": metrics(results, "model_caught"), "english": metrics(english, "model_caught"), "german": metrics(german, "model_caught")},
        "rules_plus_model": {"overall": metrics(results, "combined_caught"), "english": metrics(english, "combined_caught"), "german": metrics(german, "combined_caught")},
        "misses": [excerpt(r) for r in results if r["label"] == 1 and not r["combined_caught"]],
        "false_positives": [excerpt(r) for r in results if r["label"] == 0 and r["combined_caught"]],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="score only the first N rows (a trial)")
    parser.add_argument("--concurrency", type=int, default=4)
    args = parser.parse_args()

    rows = [json.loads(line) for line in EVAL_FILE.read_text(encoding="utf-8").splitlines() if line.strip()]
    if args.limit:
        rows = rows[: args.limit]
    settings = get_settings()
    provider_factory = lambda: create_model_provider(settings)  # noqa: E731
    model_name = getattr(provider_factory(), "model_name", settings.gemini_model)

    results = asyncio.run(evaluate(rows, provider_factory, args.concurrency))
    out = report(results, model_name)
    if out["calls"]["ok"] == 0:
        # Every call failed (an invalid key, a dead network): there is no
        # measurement here, and writing zeros as a result would publish a
        # lie. Say so and stop.
        print("no successful model calls -- check GEMINI_API_KEY; nothing written", file=sys.stderr)
        return 2
    if not args.limit:
        RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        RESULTS_FILE.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    for name in ("rules_only",):
        m = out[name]
        print(f"{name:18} recall {m['recall']}  fpr {m['false_positive_rate']}  ({m['caught']}/{m['injections']} caught, {m['false_positives']}/{m['legitimate']} false)")
    for name in ("model_only", "rules_plus_model"):
        m = out[name]["overall"]
        print(f"{name:18} recall {m['recall']}  fpr {m['false_positive_rate']}  ({m['caught']}/{m['injections']} caught, {m['false_positives']}/{m['legitimate']} false)")
    print(f"calls ok {out['calls']['ok']}/{out['calls']['total']}  p50 {out['latency_ms']['p50']} ms  p95 {out['latency_ms']['p95']} ms  model {model_name}")
    if not args.limit:
        print(f"wrote {RESULTS_FILE.relative_to(API_ROOT.parent.parent)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
