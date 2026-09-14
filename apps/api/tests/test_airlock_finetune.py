"""The fine-tuning pipeline for the deep-scan classifier: the dataset
builder and the evaluation harness.

Pinned: the committed held-out split and manifest are exactly what the
builder produces (deterministic seed); train and eval never share a text;
every training example is the classifier's own prompt with an answer the
classifier's parser accepts; and the harness aggregates model-only and
rules+model numbers correctly, counts unavailable calls, and refuses to
write a result when no call succeeded.
"""

import json
import sys
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_ROOT / "scripts"))

FINETUNE = API_ROOT / "benchmarks" / "finetune"


def test_the_committed_split_is_what_the_builder_produces(tmp_path: Path) -> None:
    import airlock_finetune_dataset as builder

    manifest = builder.build(tmp_path)
    committed = json.loads((FINETUNE / "MANIFEST.json").read_text(encoding="utf-8"))
    committed.pop("files", None)
    fresh = dict(manifest)
    files = fresh.pop("files")
    assert fresh == committed, "re-run scripts/airlock_finetune_dataset.py and commit eval.jsonl + MANIFEST.json"
    assert (tmp_path / "eval.jsonl").read_bytes() == (FINETUNE / "eval.jsonl").read_bytes()
    assert set(files) == {"eval.jsonl", "train.jsonl", "train.aistudio.jsonl"}

    train = [json.loads(line) for line in (tmp_path / "train.jsonl").read_text(encoding="utf-8").splitlines()]
    evaluation = [json.loads(line) for line in (tmp_path / "eval.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(train) == manifest["train"]["rows"] and len(evaluation) == manifest["eval"]["rows"]
    assert len(train) + len(evaluation) == manifest["rows_total"] == 718
    assert 0.18 <= len(evaluation) / manifest["rows_total"] <= 0.22

    train_texts = {example["contents"][0]["parts"][0]["text"] for example in train}
    eval_texts = {f"<content>\n{row['text']}\n</content>" for row in evaluation}
    assert not (train_texts & eval_texts), "the held-out split leaked into training"
    for row in evaluation:
        assert row["label"] in (0, 1) and row["language"] in ("en", "de") and 0 <= row["rule_score"] <= 1
        assert row["source"].startswith("deepset/") or row["source"] == "airlock-corpus"
    assert any(row["source"] == "airlock-corpus" for row in evaluation)
    # Stratified: German injections are present on both sides.
    assert sum(1 for r in evaluation if r["language"] == "de" and r["label"] == 1) >= 10


def test_training_examples_are_the_classifiers_own_prompt_and_parseable_answers(tmp_path: Path) -> None:
    import airlock_finetune_dataset as builder

    from app.airlock.rules import FAMILIES
    from app.airlock.semantic import SYSTEM_PROMPT, _parse

    builder.build(tmp_path)
    train = [json.loads(line) for line in (tmp_path / "train.jsonl").read_text(encoding="utf-8").splitlines()]
    studio = [json.loads(line) for line in (tmp_path / "train.aistudio.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(train) == len(studio)
    for example, flat in zip(train[:200], studio[:200], strict=True):
        assert example["systemInstruction"]["parts"][0]["text"] == SYSTEM_PROMPT
        user, model = example["contents"]
        assert user["role"] == "user" and model["role"] == "model"
        assert user["parts"][0]["text"].startswith("<content>\n")
        parsed = _parse(model["parts"][0]["text"])
        assert parsed is not None, "an answer the production parser rejects would teach the wrong thing"
        injection, confidence, family, reason = parsed
        assert confidence in (0.95, 0.05) and (family is None or family in FAMILIES) and reason
        assert flat["text_input"].startswith(SYSTEM_PROMPT) and flat["output"] == model["parts"][0]["text"]


class FakeProvider:
    """Answers by a table of text -> (injection, confidence); anything not
    in the table is unavailable, which is what a dead model looks like."""

    model_name = "fake-gemini"

    def __init__(self, table: dict[str, tuple[bool, float]]):
        self.table = table

    async def complete(self, request):
        from app.ai.provider import ModelResponse

        text = request.messages[0].content
        for key, (injection, confidence) in self.table.items():
            if key in text:
                return ModelResponse(text=json.dumps({"injection": injection, "confidence": confidence, "family": None, "reason": "x"}))
        raise RuntimeError("model down")


@pytest.mark.asyncio
async def test_the_harness_aggregates_model_and_combined_verdicts_and_counts_failures() -> None:
    import airlock_semantic_eval as harness

    rows = [
        {"text": "paraphrased attack", "label": 1, "language": "en", "source": "t", "family": None, "rule_score": 0.0},
        {"text": "rule-blocked attack", "label": 1, "language": "en", "source": "t", "family": "instruction_override", "rule_score": 0.8},
        {"text": "missed by both", "label": 1, "language": "de", "source": "t", "family": None, "rule_score": 0.0},
        {"text": "clean invoice", "label": 0, "language": "en", "source": "t", "family": None, "rule_score": 0.0},
        {"text": "false alarm", "label": 0, "language": "en", "source": "t", "family": None, "rule_score": 0.0},
        {"text": "model down here", "label": 0, "language": "en", "source": "t", "family": None, "rule_score": 0.0},
    ]
    provider = FakeProvider(
        {
            "paraphrased attack": (True, 0.9),
            "rule-blocked attack": (False, 0.9),  # the model can only raise; rules already block
            "missed by both": (False, 0.8),
            "clean invoice": (False, 0.1),
            "false alarm": (True, 0.7),
        }
    )
    results = await harness.evaluate(rows, lambda: provider, concurrency=2)
    out = harness.report(results, provider.model_name)

    assert out["calls"] == {"total": 6, "ok": 5, "unavailable": 1}
    assert out["rules_only"]["caught"] == 1 and out["rules_only"]["false_positives"] == 0
    assert out["model_only"]["overall"]["caught"] == 1  # the paraphrase
    assert out["model_only"]["overall"]["false_positives"] == 1
    combined = out["rules_plus_model"]["overall"]
    assert combined["caught"] == 2 and combined["false_positives"] == 1
    assert combined["recall"] == round(2 / 3, 4) and combined["false_positive_rate"] == round(1 / 3, 4)
    assert [m["text"] for m in out["misses"]] == ["missed by both"]
    assert [f["text"] for f in out["false_positives"]] == ["false alarm"]
    assert out["model_only"]["german"]["caught"] == 0 and out["model_only"]["german"]["injections"] == 1
    assert out["prompt_version"] == "airlock-semantic-v1" and out["model"] == "fake-gemini"


@pytest.mark.asyncio
async def test_the_harness_measures_in_context_tuning_with_training_rows_only() -> None:
    """--examples N shows the classifier N training rows exactly as an
    account's kept examples are shown (render_examples), balanced by label,
    the same rows on every run, none of them held out -- and the result
    file says how many so tuned and untuned never get confused."""
    import airlock_semantic_eval as harness
    from app.airlock.semantic import MAX_TUNING_EXAMPLES, SYSTEM_PROMPT

    examples = harness.training_examples(6)
    assert len(examples) == 6 and sum(e["label"] for e in examples) == 3
    assert examples == harness.training_examples(6), "seeded: the same rows every run"
    held_out = {json.loads(line)["text"] for line in harness.EVAL_FILE.read_text(encoding="utf-8").splitlines() if line.strip()}
    assert not ({e["text"] for e in examples} & held_out), "never a held-out row"
    assert harness.training_examples(0) == []
    with pytest.raises(SystemExit):
        harness.training_examples(MAX_TUNING_EXAMPLES + 1)

    seen: list[str] = []

    class Recording(FakeProvider):
        async def complete(self, request):
            seen.append(request.system)
            return await super().complete(request)

    provider = Recording({"paraphrased attack": (True, 0.9)})
    rows = [{"text": "paraphrased attack", "label": 1, "language": "en", "source": "t", "family": None, "rule_score": 0.0}]
    results = await harness.evaluate(rows, lambda: provider, concurrency=1, examples=examples)
    assert seen[0].startswith(SYSTEM_PROMPT) and seen[0].count("<example>") == 6
    assert examples[0]["text"][:80] in seen[0]
    out = harness.report(results, provider.model_name, len(examples))
    assert out["examples"] == 6
    assert harness.results_file(6).name == "deep-scan-eval.examples-6.json"
    assert harness.results_file(0) == harness.RESULTS_FILE
    # Untuned: the published prompt, byte for byte.
    await harness.evaluate(rows, lambda: provider, concurrency=1)
    assert seen[-1] == SYSTEM_PROMPT


def test_the_harness_refuses_to_write_when_every_call_failed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import airlock_semantic_eval as harness

    monkeypatch.setattr(harness, "RESULTS_FILE", tmp_path / "deep-scan-eval.json")
    monkeypatch.setattr(harness, "EVAL_FILE", FINETUNE / "eval.jsonl")
    monkeypatch.setattr(harness, "create_model_provider", lambda settings: FakeProvider({}))
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused")
    monkeypatch.setenv("GEMINI_API_KEY", "not-a-real-key")
    monkeypatch.setenv("SESSION_SECRET", "eval-only-secret-0123456789abcdef0123")
    monkeypatch.setenv("COOKIE_SECURE", "false")
    from app.settings import get_settings

    get_settings.cache_clear()
    monkeypatch.setattr(sys, "argv", ["airlock_semantic_eval.py", "--limit", "3"])
    assert harness.main() == 2
    assert not (tmp_path / "deep-scan-eval.json").exists()
    get_settings.cache_clear()
