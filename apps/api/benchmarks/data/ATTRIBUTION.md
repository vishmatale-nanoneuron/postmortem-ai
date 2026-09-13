# Benchmark data attribution

`deepset-prompt-injections.jsonl` is a verbatim cache of the
[deepset/prompt-injections](https://huggingface.co/datasets/deepset/prompt-injections)
dataset (train + test splits, 662 rows), by deepset GmbH, licensed under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). It is copied here
so that `scripts/airlock_benchmark.py` is reproducible offline and the
numbers published on /airlock can be re-derived from exactly these rows.
No changes were made to the texts or labels; the `split` field records
which split each row came from.
