#!/usr/bin/env python3
"""Build the fine-tuning dataset for Airlock's deep-scan classifier.

    PYTHONPATH=apps/api python apps/api/scripts/airlock_finetune_dataset.py

What goes in -- and only this:
- the public benchmark rows (benchmarks/data/deepset-prompt-injections.jsonl,
  CC BY 4.0, 662 rows, label 1 = injection),
- the engine's own corpus (app/airlock/corpus/rule_coverage.jsonl, 56
  hand-written cases).
Never customer content: the audit log stores no content by design and the
privacy policy says scans are not kept, so there is nothing to train on
from production and there never will be.

What comes out (benchmarks/finetune/):
- eval.jsonl   -- the held-out split, committed. Every published deep-scan
                  number is computed on exactly these rows.
- train.jsonl  -- the training split in Vertex AI supervised-tuning format
                  (systemInstruction + contents), regenerated on demand
                  (gitignored: the system prompt repeats per row).
- train.aistudio.jsonl -- the same rows as {text_input, output} for the
                  Gemini API's tuning endpoint.
- MANIFEST.json -- counts, the split seed, and SHA-256s of every file, so a
                  test can prove the committed eval split is what this
                  script produces and that train/eval never overlap.

The model turn is the exact JSON the classifier is asked to produce
(app/airlock/semantic.py): injection, confidence, family, reason. Labels
give `injection`; `family` comes from the rule engine when a rule fired
and is null otherwise; `confidence` is 0.95 / 0.05 (a labelled row is a
certain row); `reason` is a short fixed phrase, not invented prose.

Split: 80/20, stratified by label and by language (German rows are ~30%
of the public set), seeded so it is the same every run.
"""

import hashlib
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
API_ROOT = HERE.parent
sys.path.insert(0, str(API_ROOT))
sys.path.insert(0, str(HERE))

from airlock_benchmark import DATA_FILE, language_of  # noqa: E402

from app.airlock import Detector  # noqa: E402
from app.airlock.benchmark import ATTACK, load_corpus  # noqa: E402
from app.airlock.semantic import SEMANTIC_PROMPT_VERSION, SYSTEM_PROMPT  # noqa: E402

CORPUS_FILE = API_ROOT / "app" / "airlock" / "corpus" / "rule_coverage.jsonl"
OUT_DIR = API_ROOT / "benchmarks" / "finetune"
SEED = 20260914
EVAL_FRACTION = 0.2


def load_rows() -> list[dict]:
    rows: list[dict] = []
    seen: set[str] = set()
    for line in DATA_FILE.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        key = row["text"].strip()
        if key in seen:
            continue
        seen.add(key)
        rows.append({"text": row["text"], "label": int(row["label"]), "source": f"deepset/{row['split']}"})
    for case in load_corpus(CORPUS_FILE):
        key = case.text.strip()
        if key in seen:
            continue
        seen.add(key)
        rows.append({"text": case.text, "label": 1 if case.label == ATTACK else 0, "source": "airlock-corpus"})
    return rows


def annotate(rows: list[dict]) -> None:
    detector = Detector()
    for row in rows:
        row["language"] = language_of(row["text"])
        detection = detector.scan(row["text"])
        families = sorted({match.family for match in detection.matches})
        row["family"] = families[0] if families else None
        row["rule_score"] = detection.score


def split(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """Stratified by (label, language); deterministic."""
    rng = random.Random(SEED)
    buckets: dict[tuple[int, str], list[dict]] = defaultdict(list)
    for row in rows:
        buckets[(row["label"], row["language"])].append(row)
    train: list[dict] = []
    evaluation: list[dict] = []
    for key in sorted(buckets):
        bucket = sorted(buckets[key], key=lambda r: r["text"])
        rng.shuffle(bucket)
        cut = max(1, round(len(bucket) * EVAL_FRACTION))
        evaluation.extend(bucket[:cut])
        train.extend(bucket[cut:])
    return train, evaluation


def answer_for(row: dict) -> str:
    injection = row["label"] == 1
    return json.dumps(
        {
            "injection": injection,
            "confidence": 0.95 if injection else 0.05,
            "family": row["family"] if injection else None,
            "reason": "Instructs or steers the agent reading it." if injection else "Ordinary content; no instruction aimed at the agent.",
        }
    )


def vertex_example(row: dict) -> dict:
    return {
        "systemInstruction": {"role": "system", "parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [
            {"role": "user", "parts": [{"text": f"<content>\n{row['text']}\n</content>"}]},
            {"role": "model", "parts": [{"text": answer_for(row)}]},
        ],
    }


def aistudio_example(row: dict) -> dict:
    return {"text_input": f"{SYSTEM_PROMPT}\n\n<content>\n{row['text']}\n</content>", "output": answer_for(row)}


def write_jsonl(path: Path, items: list[dict]) -> str:
    text = "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in items)
    path.write_text(text, encoding="utf-8")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build(out_dir: Path = OUT_DIR) -> dict:
    rows = load_rows()
    annotate(rows)
    train, evaluation = split(rows)
    out_dir.mkdir(parents=True, exist_ok=True)
    eval_rows = [
        {"text": r["text"], "label": r["label"], "language": r["language"], "source": r["source"], "family": r["family"], "rule_score": r["rule_score"]}
        for r in evaluation
    ]
    manifest = {
        "prompt_version": SEMANTIC_PROMPT_VERSION,
        "seed": SEED,
        "eval_fraction": EVAL_FRACTION,
        "rows_total": len(rows),
        "train": {"rows": len(train), "injections": sum(r["label"] for r in train)},
        "eval": {
            "rows": len(evaluation),
            "injections": sum(r["label"] for r in evaluation),
            "german": sum(r["language"] == "de" for r in evaluation),
        },
        "files": {
            "eval.jsonl": write_jsonl(out_dir / "eval.jsonl", eval_rows),
            "train.jsonl": write_jsonl(out_dir / "train.jsonl", [vertex_example(r) for r in train]),
            "train.aistudio.jsonl": write_jsonl(out_dir / "train.aistudio.jsonl", [aistudio_example(r) for r in train]),
        },
        "sources": {"public": "deepset/prompt-injections (CC BY 4.0)", "corpus": "app/airlock/corpus/rule_coverage.jsonl"},
        "never_included": "customer content -- the audit log stores none and the privacy policy promises none is kept",
    }
    (out_dir / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    m = build()
    print(f"rows {m['rows_total']}  train {m['train']['rows']} ({m['train']['injections']} injections)  eval {m['eval']['rows']} ({m['eval']['injections']} injections, {m['eval']['german']} German)")
    print(f"wrote {OUT_DIR.relative_to(API_ROOT.parent.parent)}/{{eval.jsonl, train.jsonl, train.aistudio.jsonl, MANIFEST.json}}")
