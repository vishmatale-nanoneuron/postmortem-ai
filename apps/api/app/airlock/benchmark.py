"""Benchmark harness for the detection engine.

The plan this product came from is explicit that the corpus is the moat and
the benchmark is the distribution: hand-written rules are a demo, and the
numbers only mean something once they are computed over a corpus someone
else can check. The public /airlock page promises exactly that, and
promises the misses will be published too.

This is the machinery for it. It is deliberately built before there is a
public dataset to run it on, because the shape of the answer is what
decides whether the dataset is worth gathering:

- Overall precision, recall and F1 at the live thresholds -- not a single
  "accuracy" number, which on an unbalanced corpus flatters a detector that
  simply blocks everything.
- Per-rule true and false positives. This is the part a rule author needs
  and a headline number hides: a rule that fires on nothing is dead weight,
  and a rule that fires on benign documents is the one that will get the
  product uninstalled.
- The benign score distribution, so drift toward the flag threshold is
  visible long before it becomes a false positive someone notices.

Pure functions over a corpus. No database, no network, no I/O except the
JSONL reader, so it runs anywhere and in CI.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from .detector import Detector
from .rules import RULES

# A corpus case is labelled with what it IS, not with what we hope the
# engine says about it -- so the same file can be re-scored after a rule
# change without relabelling.
ATTACK = "attack"
BENIGN = "benign"


@dataclass(frozen=True)
class CorpusCase:
    text: str
    label: str  # ATTACK | BENIGN
    # Where it came from, so a published benchmark can be traced back to its
    # sources rather than asserted.
    source: str = "unknown"
    # Optional family label from the source dataset. Never used for scoring;
    # carried so per-family recall can be reported when a dataset has it.
    family: str | None = None


@dataclass
class RuleStats:
    rule_id: str
    family: str
    fired_on_attacks: int = 0
    fired_on_benign: int = 0

    @property
    def is_dead(self) -> bool:
        """Fired on nothing at all. Either the pattern is broken or the
        corpus has no example of what it targets -- both worth knowing, and
        indistinguishable from a headline score."""
        return self.fired_on_attacks == 0 and self.fired_on_benign == 0

    @property
    def precision(self) -> float | None:
        total = self.fired_on_attacks + self.fired_on_benign
        return None if total == 0 else self.fired_on_attacks / total


@dataclass
class BenchmarkResult:
    attacks: int = 0
    benign: int = 0
    # An attack the engine did not allow through (flag or block both count:
    # either one stops the content reaching the model unreviewed).
    true_positives: int = 0
    false_negatives: int = 0
    # A benign document the engine did not allow.
    false_positives: int = 0
    true_negatives: int = 0
    rules: dict[str, RuleStats] = field(default_factory=dict)
    benign_scores: list[float] = field(default_factory=list)
    missed: list[CorpusCase] = field(default_factory=list)
    false_alarms: list[CorpusCase] = field(default_factory=list)

    @property
    def precision(self) -> float | None:
        flagged = self.true_positives + self.false_positives
        return None if flagged == 0 else self.true_positives / flagged

    @property
    def recall(self) -> float | None:
        return None if self.attacks == 0 else self.true_positives / self.attacks

    @property
    def f1(self) -> float | None:
        precision, recall = self.precision, self.recall
        if not precision or not recall:
            return None
        return 2 * precision * recall / (precision + recall)

    @property
    def false_positive_rate(self) -> float | None:
        """The number that decides whether anyone keeps the product past
        week two. Reported separately from precision because precision moves
        with the attack/benign ratio of the corpus and this does not."""
        return None if self.benign == 0 else self.false_positives / self.benign

    @property
    def dead_rules(self) -> list[str]:
        return sorted(stats.rule_id for stats in self.rules.values() if stats.is_dead)


def load_corpus(path: str | Path) -> list[CorpusCase]:
    """JSONL, one case per line: {"text": ..., "label": "attack"|"benign",
    "source": ..., "family": ...}. Chosen so a public dataset can be
    converted with a few lines of jq and appended, rather than requiring a
    loader per source."""
    cases: list[CorpusCase] = []
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"{path}:{number}: not valid JSON ({error})") from error
        label = record.get("label")
        if label not in (ATTACK, BENIGN):
            raise ValueError(f"{path}:{number}: label must be {ATTACK!r} or {BENIGN!r}, got {label!r}")
        text = record.get("text")
        if not isinstance(text, str) or not text:
            raise ValueError(f"{path}:{number}: 'text' must be a non-empty string")
        cases.append(
            CorpusCase(
                text=text,
                label=label,
                source=str(record.get("source") or "unknown"),
                family=record.get("family"),
            )
        )
    return cases


def run_benchmark(cases: Iterable[CorpusCase], detector: Detector | None = None) -> BenchmarkResult:
    engine = detector or Detector()
    result = BenchmarkResult()
    result.rules = {rule.id: RuleStats(rule_id=rule.id, family=rule.family) for rule in RULES}

    for case in cases:
        detection = engine.scan(case.text)
        caught = detection.verdict != "allow"

        for match in detection.matches:
            stats = result.rules.get(match.rule_id)
            if stats is None:
                continue
            if case.label == ATTACK:
                stats.fired_on_attacks += 1
            else:
                stats.fired_on_benign += 1

        if case.label == ATTACK:
            result.attacks += 1
            if caught:
                result.true_positives += 1
            else:
                result.false_negatives += 1
                result.missed.append(case)
        else:
            result.benign += 1
            result.benign_scores.append(detection.score)
            if caught:
                result.false_positives += 1
                result.false_alarms.append(case)
            else:
                result.true_negatives += 1

    return result


def _percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def format_report(result: BenchmarkResult) -> Iterator[str]:
    """Plain text, so it can go in a README, a CI log or a blog post
    unchanged. The misses are printed, not summarised -- publishing the
    failures is the part that makes a benchmark worth reading."""
    yield "Airlock detection benchmark"
    yield "=" * 60
    yield f"corpus            {result.attacks + result.benign} cases ({result.attacks} attack, {result.benign} benign)"
    yield f"recall            {_percent(result.recall)}  ({result.true_positives}/{result.attacks} attacks caught)"
    yield f"precision         {_percent(result.precision)}"
    yield f"false positives   {_percent(result.false_positive_rate)}  ({result.false_positives}/{result.benign} benign flagged)"
    yield f"F1                {_percent(result.f1)}"
    if result.benign_scores:
        worst = max(result.benign_scores)
        yield f"worst benign score {worst:.2f}  (flag threshold 0.40)"
    yield ""

    dead = result.dead_rules
    yield f"rules that fired on nothing: {len(dead)}/{len(result.rules)}"
    if dead:
        yield "  " + ", ".join(dead)
    yield ""

    noisy = sorted(
        (stats for stats in result.rules.values() if stats.fired_on_benign),
        key=lambda stats: stats.fired_on_benign,
        reverse=True,
    )
    yield f"rules that fired on benign documents: {len(noisy)}"
    for stats in noisy:
        yield f"  {stats.rule_id}  {stats.fired_on_benign} benign, {stats.fired_on_attacks} attack, precision {_percent(stats.precision)}"
    yield ""

    if result.missed:
        yield f"MISSED ({len(result.missed)}):"
        for case in result.missed:
            yield f"  [{case.source}] {case.text[:100]!r}"
        yield ""
    if result.false_alarms:
        yield f"FALSE ALARMS ({len(result.false_alarms)}):"
        for case in result.false_alarms:
            yield f"  [{case.source}] {case.text[:100]!r}"
        yield ""
