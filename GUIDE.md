# Entering the contest

Six steps from a clone to a pull request. None of them is optional, and the two
that are easy to get wrong are marked.

---

**The six steps**
[1 Set up](#1-set-up-once) ·
[2 See the state](#2-look-at-what-a-bot-receives) ·
[3 Create it](#3-create-it) ·
[4 Write it](#4-write-it) ·
[5 Measure it](#5-measure-it) ·
[6 Submit](#6-submit)

**Then**
[The optional hooks](#the-optional-hooks) ·
[The rule that is not obvious](#the-rule-that-is-not-obvious) ·
[Two people, one name](#two-people-one-name) ·
[Where to experiment](#where-to-experiment) ·
[What counts as a bot](#what-counts-as-a-bot)

---

## 1. Set up, once

```bash
git clone https://github.com/pierpierpy/pokelike.xyz.bot && cd pokelike.xyz.bot
uv sync
uv run pokelike setup          # the browser plus an offline copy of the game, ~130 MB
```

The copy is offline on purpose: after this nothing you do reaches the internet,
and the same seed always replays the same run.

## 2. Look at what a bot receives

Do not guess at it. This is generated from a live observation, so it cannot
describe a game that no longer exists:

```bash
uv run pokelike schema         # the full reference
uv run pokelike play           # play it yourself; three minutes is enough
```

Two things decide how you write everything else.

The state is **one dict, not a history**. What history matters is already inside
it: every map node carries `visited`, and `stats` are cumulative from the start
of the run.

**The indices change every turn.** `state["actions"]` is the list you choose
from, and index 2 is a battle now and a catch next turn. Nothing can be decided
by position; you look at what each entry actually is.

It is worth watching the one at the top of the table play before you write
anything:

```bash
uv run pokelike bot --bot sarsa-v2 --seed 40003 --runs 1 -g -dd
```

`-g` draws the map beside each decision, `-dd` prints the value it gave every
option before choosing.

## 3. Create it

```bash
uv run pokelike new-bot mine
```

That writes a folder, and the folder **is** the bot:

```
bots/mine/
├── bot.py        one class inheriting from Bot
├── artifacts/    weights, prompts, tables — whatever yours needs
└── README.md     one line on how it decides
```

Nothing to register anywhere. `--bot mine` finds it because the folder is there.
A prefix works too as long as it is unique — `--bot mi` is fine until someone
adds `mine-v2`, at which point it becomes an error naming both rather than a
guess.

**If your bot is a prompt around a language model**, add `--llm` and you start
from the shared harness instead of an empty `choose`:

```bash
uv run pokelike new-bot my-prompt --llm
```

You then write nothing but the prompt. The tools, the agentic loop, the state
rendering, the HTTP call and what happens when it fails all live in
`pokelike.bot.llm` and are shared by every LLM bot **on purpose**: two bots with
different loops are two harnesses being compared, and the model is the smaller
half of that difference.

What it writes already plays, which matters more than it sounds: measure it
before you change a line, and when the number moves later you know it moved
because of you.

```bash
uv run pokelike bot --bot mine --runs 5 -d
uv run pokelike bench --bot mine --dry-run     # the real 50 seeds, recorded nowhere
```

## 4. Write it

The only method you must write is `choose`. It gets the state and returns an
index into `state["actions"]`.

```python
from typing import Any

from pokelike.bot.base import Bot


class MyBot(Bot):
    name = "mine"

    def choose(self, state: dict[str, Any]) -> int:
        """Heal when someone is hurt, otherwise take a trainer for the levels."""
        team = state.get("team") or []
        hurt = any(p["hp"] / p["max_hp"] < 0.5 for p in team if p["max_hp"])

        for i, a in enumerate(state["actions"]):
            if hurt and a.get("node") == "pokecenter":
                return i
        for i, a in enumerate(state["actions"]):
            if a.get("node") == "trainer":
                return i
        return 0
```

Everything the game knows is in `state`, including things nothing on screen tells
you: `team[i].move` is what that Pokemon actually attacks with, power and type
included, and `offered_moves` is what the move tutor would hand each of them.

**One class per folder.** The name of the folder says which bot ran, so a file
defining two of them is refused rather than guessed at.

## 5. Measure it

Against random, on the **same** seeds, paired. Runs vary enormously by luck here,
so two separate averages mostly measure who drew the nicer maps:

```python
from pokelike import compare
from pokelike.bot import create

print(compare({"mine": create("mine")}, seeds=range(25))["table"])
```

Then the official benchmark, the 50 fixed seeds everyone is scored on:

```bash
uv run pokelike bench --bot mine --dry-run                       # nothing recorded
uv run pokelike bench --bot mine --author YOUR-HANDLE --category rules
```

> **Easy to get wrong, and now it cannot be.** Only a **complete** run records a
> result. `--runs N` is a practice run by definition — a score over 5 seeds is
> not comparable to one over 50 — and `--dry-run` plays all 50 and records
> nothing. Neither leaves anything behind for a stray `git add` to pick up.

A recorded result lands in `bots/mine/result.json`, next to the code that earned
it, with a fingerprint over both. If you then edit the bot, the table marks the
row **⚠︎** until you measure it again: a score can never quietly describe code
that no longer exists.

## 6. Submit

Fork the repo on GitHub, then:

```bash
git checkout -b my-bot
git add bots/mine
git commit -m "Add mine"
git push origin my-bot
```

and open the pull request GitHub offers you. Your whole submission is one
folder.

---

## The optional hooks

Only `choose` is required. These exist for bots that need them, and ignoring one
costs you nothing:

| hook | what it is for |
|---|---|
| `rearrange(state)` | who leads the next battle. Free — it does not use the turn |
| `explain()` | one line under each decision in the log |
| `on_start(seed)` / `on_end(state, score)` | a bot with memory across turns |
| `artifacts()` | weights and config to record beside your result |

`rearrange` is worth a look. Slot 0 is the Pokemon that enters the next battle,
so the order is a real decision, and it is kept out of `actions` because taking
it costs no turn: a full team would otherwise add fifteen swap pairs beside the
real moves at every single map node.

---

## The rule that is not obvious

> **Your folder has to stand on its own.** Everything `bot.py` needs is either in
> the `pokelike` package or in `artifacts/` beside it. It must not import from
> `experiments/`, and it must not import another bot.

Two reasons, and the second is the one people underestimate.

A trained policy is only meaningful under the exact encoding it was trained with.
If `bot.py` imported its feature code from your training scripts, improving those
scripts would silently change what your own past score meant — and the
fingerprint would not catch it, because the file you measured did not change.

And a bot is meant to be handed around, re-run and checked by someone who has
none of your setup. A folder that only works on the machine that made it is not
a submission, it is a screenshot.

[`bots/dyna-q/`](bots/dyna-q/) is the small worked example — an encoding frozen
beside its weights. [`bots/sarsa-v2/`](bots/sarsa-v2/) is the large one, 100
feature definitions carried inline for exactly this reason.

**The one exception is `pokelike.bot.llm`**, the harness the `llm-*` bots share.
It is shared knowingly, so editing it *does* reach every LLM bot ever measured —
which is why it carries a `HARNESS` number that is written into every result, and
why a row measured under an older one is flagged instead of being ranked as
though it had been asked the same question.

### Two people, one name

`bots/` is flat, so two submissions cannot share a folder name. Git will say so
on your pull request and one of you renames — a plain conflict, visible, nothing
auto-resolved. The `--author` you pass to `bench` is what tells people apart in
the standings. The fingerprint is not a name and is deliberately not used as one:
it comes from the content, so it would change every time you retrained.

---

## Where to experiment

`experiments/` is a scratch area and **it is not tracked**: everything under it
is gitignored apart from the shared `env/` and our own worked examples. Whatever
you try there — training runs, sweeps, prompts, dead ends — stays on your
machine, and a pull request that adds a bot cannot drag a training run along with
it by accident.

```bash
cp -r experiments/example experiments/mine
uv run python -m experiments.example.train --episodes 20   # the shape of one
```

That is the split, and it is the whole answer to "what do I have to reveal":

**You show what your bot does. Not how you arrived at it.**

Submitting a folder does reveal the bot — that is the only reason the number
beside it means anything, since a leaderboard where the code is hidden is a list
of claims. It reveals nothing about the sweeps, the rewards you tried, or the
twenty runs that went nowhere.

---

## What counts as a bot

Anything that picks a move given the state. A prompt around an LLM, a model
fine-tuned on the game, reinforcement learning of any flavour, a hand-written
rulebook, search over the game tree since the engine ships a battle simulator you
can call, something deterministic if you can find one that works.

Ranked by **badges**, the game's own progress counter. The bar and the current
standings are in [bots/README.md](bots/README.md).
