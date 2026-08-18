# llm-example

Every knob the shared LLM harness has, turned, with a reason written next to each.
**A reference, not a contender** — the other `llm-*` bots each change one thing so
the comparison between them means something; this one changes everything at once.

```bash
export FW_ENDPOINT="https://..."   # base URL, no /v1
export FW_TOKEN="..."
export MODEL_ID="..."
uv run pokelike bot --bot llm-example --runs 1 -d
```

| | |
|---|---|
| how it works | the shared harness with two extra tools (`state_json`, `bag`), a state view that adds HP fractions the ASCII screen only draws, and a 60k-token per-run ceiling |
| what it scored | nothing: it is not benchmarked, on purpose |
| what was tried and dropped | pushing the whole state dict into every turn. A late-run map is kilobytes, most of it irrelevant to this turn, and paying for it every turn makes an LLM benchmark about context windows rather than about play. It is a tool instead, so the model pays only when it asks |

## What to copy

| you want | look at |
|---|---|
| a different strategy | `PROMPT` — for most bots this is the whole submission |
| the model to see something new | `EXTRA_TOOLS` + `run_tool()` |
| to change what the model reads each turn | `_situation()` — the deepest hook here |
| a model that is not an HTTP endpoint | `_call()` — the one hook this file does **not** use |

`_call()` is where a local model goes: load it however you like, return the
OpenAI-shaped `message` dict, and the loop, the tools and the fallback policy
above it keep working unchanged.

## Two things it is honest about

**Custom tools are recorded.** Offering the model tools the others did not have
is allowed and is marked in the standings — not as a fault, but because it is a
different question, and comparing it with the rest as though it were the same one
is the actual mistake.

**Overriding `_fallback()` is rarely wise.** Whatever it does is played under the
bot's name on every turn the model did not answer, and `fallback_rate` reports
the share. A clever fallback is cleverness being measured as though the model
produced it.

## It joins prompt comparisons by default

`experiments/llm/compare.py` takes every `llm-*` bot on disk. Name the ones you
mean if you would rather leave this out:

```bash
uv run python -m experiments.llm.compare --bots llm-survivor,llm-explorer --seeds 5
```
