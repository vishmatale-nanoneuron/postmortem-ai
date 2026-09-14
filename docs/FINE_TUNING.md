# Fine-tuning: what exists, what it needs, and what we will not do

Two products, one place where a model's behaviour decides anything:
Airlock's **deep scan** (`"deep": true`), the Gemini classifier behind
`app/airlock/semantic.py`. Everything else that looks like "AI" is either
deterministic (the 40-rule engine) or verified by code after the model
speaks (PostMortem AI's citation check). So "fine-tuning" here means one
thing: making that classifier better on the paraphrased, no-fixed-phrasing
injections the rules cannot see — and measuring it the same way the rule
engine is measured, in the open.

## What exists today (this repository)

| Piece | Where | Status |
|---|---|---|
| Labelled data we own the right to train on | `apps/api/benchmarks/data/` (deepset/prompt-injections, CC BY 4.0, 662 rows) + `apps/api/app/airlock/corpus/` (56 hand-written cases) | committed |
| Dataset builder | `apps/api/scripts/airlock_finetune_dataset.py` | **built, tested** |
| Held-out split (the only rows any published deep-scan number may use) | `apps/api/benchmarks/finetune/eval.jsonl` + `MANIFEST.json` | committed; a test proves it is what the builder produces |
| Training split | `benchmarks/finetune/train.jsonl` (Vertex AI SFT format), `train.aistudio.jsonl` (Gemini API tuning format) | regenerated on demand, gitignored (the system prompt repeats per row) |
| Evaluation harness for the current classifier | `apps/api/scripts/airlock_semantic_eval.py` | **built, tested** — needs a valid `GEMINI_API_KEY` to produce numbers |
| Published deep-scan numbers | `apps/api/benchmarks/results/deep-scan-eval.json` | **not yet produced** — see below |

Sizes: 718 unique rows → 574 train (242 injections) / 144 held-out (61
injections, 42 German). Stratified by label and language, seeded, so the
split is identical on every run.

Every training example is the classifier's *own* prompt (`SYSTEM_PROMPT`,
verbatim) as the system instruction, the `<content>…</content>` wrapper as
the user turn, and an answer the production parser accepts as the model
turn — a test round-trips each one through `semantic._parse`. Tuning on a
prompt shape the product does not use would tune the wrong thing.

## Run it

```bash
# 1. Build the dataset (deterministic; only eval.jsonl + MANIFEST.json are committed).
PYTHONPATH=apps/api python apps/api/scripts/airlock_finetune_dataset.py

# 2. Score the CURRENT classifier on the held-out split -- one Gemini call per row
#    (144 calls; on gemini-2.5-flash a few cents). Never scores training rows.
GEMINI_API_KEY=... DATABASE_URL=postgresql://unused \
SESSION_SECRET=eval-only-secret-0123456789abcdef0123 COOKIE_SECURE=false \
PYTHONPATH=apps/api python apps/api/scripts/airlock_semantic_eval.py            # full split
PYTHONPATH=apps/api python apps/api/scripts/airlock_semantic_eval.py --limit 10 # cheap trial
```

The harness reports, per language: **model alone** (recall, false-positive
rate), **rules + model** (what a real deep scan answers: rule score and
model weight combined by noisy-OR at the default thresholds), unavailable
calls, p50/p95 latency, and every miss and false alarm verbatim. If no
call succeeds (an invalid key), it writes nothing and exits 2 — a file of
zeros would be a published lie.

Commit `deep-scan-eval.json` once produced; the benchmark page will render
it beside the rule-engine numbers. The rule engine's own benchmark
(`scripts/airlock_benchmark.py`) stays the floor: 25.9 % recall, 0 false
positives on 399 legitimate texts.

## What actual weight-tuning needs, and why it has not been run

- **A tuning endpoint that supports the production model.**
  `gemini-2.5-flash` supervised fine-tuning runs on **Vertex AI**, which
  needs a Google Cloud project with an open billing account. This
  company's GCP billing account is closed and cannot be reactivated
  (`docs/BACKEND_DEPLOYMENT.md`). The Gemini API's own `tunedModels`
  endpoint (AI Studio) supports older Flash models only; `train.aistudio.jsonl`
  is provided for that path in case it is the one chosen.
- **A baseline first.** Tuning without the held-out score of the untuned
  model is guessing. Step 2 above is the baseline; it costs cents and
  needs only a valid key.
- **A reason.** The rule engine already answers most calls without a
  model, and a deep scan is charged extra precisely because it costs a
  model call. Tune the classifier when the baseline shows the paraphrase
  class is where the misses are — not because tuning is available.

Expected order of work when the founder decides to: run the baseline →
commit the numbers → tune on `train.jsonl` in Vertex → point
`GEMINI_MODEL` at the tuned endpoint → re-run the harness on the *same*
held-out split → publish both numbers side by side, including the misses.

## What we will not do

- **Train on customer content.** The audit log stores a hash, byte count
  and verdict — no content, by construction (migration 0031) — and the
  privacy policy says scans are not kept. There is nothing to train on
  from production and there never will be. The dataset builder reads two
  files, both public or self-authored, and says so in its manifest.
- **Score the training rows.** A number on rows the model may later be
  tuned on is meaningless; the harness reads `eval.jsonl` only.
- **Hand-type a result.** Tests pin the manifest to the builder and the
  results file's internal consistency; the website renders the file.

## PostMortem AI

There is no fine-tuning to add, and this is a design fact rather than a
gap. The product's guarantee — every claim cites recorded evidence,
anything unsupported is marked, never invented — is enforced by **code
after the model answers** (`services/postmortem.py` verifies every
citation independently before anything is stored; the database refuses
to publish without a named approver). A better-tuned drafting model would
change fluency, not that guarantee. And the only material that could tune
it is customers' incidents and evidence, which the privacy policy and the
data-export/erasure promises put out of reach. The two public worked
examples (`/blog/github-outage-demo`, `/blog/cloudflare-outages-2025`) are
demonstrations, not a dataset. If that ever changes it will be with an
explicit, opt-in, per-account consent — not quietly.
