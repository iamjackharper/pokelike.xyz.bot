# Comparing prompts

**Contents**
[Why paired, again](#why-paired-again) ·
[What it costs](#what-it-costs)

---

```bash
uv run python -m experiments.llm.compare --strategies survivor,explorer --seeds 5
```

The one experiment here that is not learning anything. An LLM bot's behaviour is
decided by its prompt, so "which prompt is better" is an empirical question with
the same shape as any other: play both on **identical seeds** and compare them
paired.

Four strategies ship in [`bots/llm/`](../../bots/llm/), selectable
with `POKELIKE_LLM_STRATEGY`:

| strategy | what it is told to weigh |
|---|---|
| `baseline` | nothing in particular |
| `survivor` | staying alive; heal before it is urgent |
| `explorer` | reaching further, taking the risk |
| `analyst` | read the tools first, commit last |

## Why paired, again

Runs vary enormously by luck, and an LLM is slow enough that you will not run
many. Two separate averages over ten runs each mostly measure who drew the nicer
maps. On identical seeds the question becomes "on this same run, did it do
better", which ten runs can actually answer.

## What it costs

Roughly 30k tokens a run, one HTTP call per decision. Credentials come from the
environment and from nowhere else:

```bash
export FW_ENDPOINT="https://..."     # the base url, no path
export FW_TOKEN="..."
export MODEL_ID="..."
```

A 401 or a model-not-found **stops the run** rather than falling back. A bad
token would otherwise produce a whole run of fallback moves that looks exactly
like a model playing badly, and `bench` would file it on the leaderboard as an
`llm` entry no model ever played.
