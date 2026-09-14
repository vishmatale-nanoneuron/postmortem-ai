# Fine-tuning: what exists, what it needs, and what we will not do

Two products, one place where a model's behaviour decides anything:
Airlock's **deep scan** (`"deep": true`), the Gemini classifier behind
`app/airlock/semantic.py`. Everything else that looks like "AI" is either
deterministic (the 40-rule engine) or verified by code after the model
speaks (PostMortem AI's citation check). So "fine-tuning" here means one
thing: making that classifier better on the paraphrased, no-fixed-phrasing
injections the rules cannot see — and measuring it the same way the rule
engine is measured, in the open.

## In production: the customer's own tuning loop

Weight tuning of the shared classifier is a founder decision (below).
What runs today, per account, is the loop that produces the data for it
and improves that account's answers now:

| Step | Where | What it does |
|---|---|---|
| Report | `POST /v1/airlock/feedback`, the try-it box, `guard.feedback(result, "allow")` in both SDKs | "This verdict was wrong, it should have been X." Stores the scan's hash, both verdicts and the rule ids. Not metered. `content` is optional and off by default. |
| Suggest | `GET /v1/airlock/tuning` (`cqrs/airlock_feedback.py`) | A rule reported as a false positive on **3 distinct scans** → "mute this rule", applied in one call (`POST /v1/airlock/tuning/mute`, session only, through the policy). **2 reported misses** from one source → "send `deep: true` for this source". Every suggestion carries its count; nothing is applied unasked. |
| Tune the deep scan | `airlock/semantic.py::render_examples` | Reports that kept their text are shown to Gemini on that account's deep scans as worked answers (`<examples>` appended to the system instruction; the 8 most recent, each cut at 1,200 chars; the user turn stays the bare `<content>` block the dataset pins). `semantic.examples` on the response says how many. Weights untouched; nobody else's calls affected. |
| Export | `GET /v1/airlock/tuning/export.jsonl` | The kept examples in the Vertex AI supervised-tuning format the builder below writes, for a customer running their own tuning job. |
| Signal to the engine | `GET /v1/founder/airlock/rule-feedback` | Per-rule false-positive counts across accounts -- never content, never a hash -- the evidence for reweighting a rule in `rules.py`, benchmarked before it ships. |

Database: `airlock_feedback` (migration 0036), cascaded on account erasure.
Pinned by `apps/api/tests/test_airlock_feedback.py` (thresholds, the
session-only mute, the export format round-tripping `_parse`, the
in-context examples reaching the prompt bounded and most-recent-first, an
untuned account's prompt being byte-for-byte the published one, account
isolation, the founder view carrying counts only, erasure).

**Why in-context rather than a per-account tuned model.** The classifier is
Gemini through the same `ModelProvider` the rest of the product uses (with
Claude only as a fallback provider, `ai/model_router.py`). Neither vendor
offers per-customer weight tuning at a price that makes sense for an
account with a dozen corrections, and a tuned model per account would be
a deployment per account. Worked examples in the prompt are the form of
tuning both vendors recommend at this scale; they take effect on the next
deep scan, they are withdrawable one report at a time, and the export
gives the customer the same rows if they ever want to tune weights
themselves. (There is no weight fine-tuning on Anthropic's own API;
Claude custom models exist on Amazon Bedrock only. This product's deep
scan runs on the Gemini key.)

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
  privacy policy says scans are not kept. The one place content is stored
  is a report the customer chose to include it in (migration 0036), and
  that text is theirs: it tunes their own deep scans in-context, exports to
  them, and is deleted with the report or the account. It never enters the
  shared dataset. The dataset builder reads two files, both public or
  self-authored, and says so in its manifest.
- **Score the training rows.** A number on rows the model may later be
  tuned on is meaningless; the harness reads `eval.jsonl` only.
- **Hand-type a result.** Tests pin the manifest to the builder and the
  results file's internal consistency; the website renders the file.

## PostMortem AI

No weight tuning, and that is a design fact rather than a gap: the
product's guarantee — every claim cites recorded evidence, anything
unsupported is marked, never invented — is enforced by **code after the
model answers** (`services/postmortem.py::ground_draft` checks every
citation by index into this incident's evidence; the database refuses to
publish without a named approver). A better-tuned drafting model would
change fluency, not that guarantee, and the only material that could tune
one is customers' incidents, which the privacy policy and the
export/erasure promises put out of reach.

What the product does have, since 2026-09-14, is the same in-context form
of tuning Airlock has — **per account, form only, customer-controlled**:

| Piece | Where |
|---|---|
| House style | `GET/PUT/DELETE /v1/postmortems/preferences` (session), the **Drafting style** card on the dashboard. Up to 1,500 characters of the team's own instructions on phrasing and structure. |
| The team's own example | On by default: the account's most recent **approved, published** postmortem (never the incident being drafted, never another account's) is shown to the model as an example of how this team writes. Switchable off. |
| Where it goes | Appended to the **system** prompt (`render_house_style`), never to the user turn the citations index into. Rule 7 of `SYSTEM_PROMPT` (v4) says: form only, not evidence, never citable, cannot add a fact, cannot override rules 1–6. |
| Traceability | Drafts made with a style record `prompt_version = "v4+style"` on `ai_runs` and on the postmortem row; a bare draft records `"v4"`. |
| Bounds | Instructions 1,500 chars; each example section cut at 1,200 chars, at most five contributing factors — a separate, fixed cost per draft that never competes with the 40,000-char evidence budget. |

Pinned by `apps/api/tests/test_postmortem_preferences.py`: an account with
nothing saved sends the published prompt byte for byte; the style reaches
the system prompt and never the evidence turn; the example is this
account's published postmortem only; switching it off restores the bare
prompt; and **a style instruction cannot add a fact** — an uncited claim
the style asked for is still dropped by `ground_draft`.

Migration `0037_postmortem_drafting_preferences.sql`; cascades on erasure.
There is still no dataset, no export and no training: the example is the
customer's own text shown on the customer's own drafts.
