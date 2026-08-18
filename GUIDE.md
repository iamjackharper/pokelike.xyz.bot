# Entering the contest

Seven steps from a clone to a pull request. None of them is optional, and the
two that are easy to get wrong are marked.

---

## 1. Set up, once

```bash
git clone https://github.com/pierpierpy/pokelike.xyz.bot && cd pokelike.xyz.bot
uv sync
uv run pokelike setup          # the browser plus an offline copy of the game, ~130 MB
```

The copy is offline on purpose: after this, nothing you do reaches the internet,
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

## 3. Write the file

`src/pokelike/bot/mine.py`. The only method you must write is `choose`.

```python
from typing import Any

from .base import Bot


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

## 4. Register it

In [`src/pokelike/bot/__init__.py`](src/pokelike/bot/__init__.py):

```python
AVAILABLE = {
    ...
    "mine": ("mine", "MyBot"),
}
```

Modules are imported only when used, so a bot that pulls in something heavy does
not slow down anyone else.

## 5. Watch it play

```bash
uv run pokelike bot --bot mine --seed 40003 --runs 1 -g -dd
```

`-g` draws the map beside each decision, with where it is on it and which nodes
are still open. `-dd` prints your `explain()` line under each choice. Then over a
stretch: `--runs 20 -d`.

## 6. Measure it

Against random, on the **same** seeds, paired. Runs vary enormously by luck here,
so two separate averages mostly measure who drew the nicer maps:

```python
from pokelike import compare
from pokelike.bot.mine import MyBot

print(compare({"mine": MyBot()}, seeds=range(25))["table"])
```

Then the official benchmark, the 50 fixed seeds everyone is scored on. Try it
without committing to anything first:

```bash
uv run pokelike bench --bot mine --name my-bot --dry-run     # plays 50, writes nothing
uv run pokelike bench --bot mine --runs 5                    # a quick look, writes nothing
```

When the number is one you want on the board, drop the flag:

```bash
uv run pokelike bench --bot mine --name my-bot --author YOUR-HANDLE --category rules
```

Only a **complete** run writes an entry. `--runs N` is a practice run by
definition — a score over 5 seeds is not comparable to one over 50 — so it
prints the result and files nothing.

## 7. Submit

Fork the repo on GitHub, then:

```bash
git checkout -b my-bot
git add leaderboard/entries/my-bot-<hash> src/pokelike/bot/
git commit -m "Add my-bot"
git push origin my-bot
```

and open the pull request GitHub offers you. The full version, including what to
do if your bot carries trained weights, is in
[leaderboard/README.md](leaderboard/README.md#how-to-submit).

---

## The optional hooks

Only `choose` is required. These exist for bots that need them, and ignoring one
costs you nothing:

| hook | what it is for |
|---|---|
| `rearrange(state)` | who leads the next battle. Free — it does not use the turn |
| `explain()` | one line under each decision in the log |
| `on_start(seed)` / `on_end(state, score)` | a bot with memory across turns |
| `artifacts()` | weights and config to archive with your submission |

`rearrange` is worth a look. Slot 0 is the Pokemon that enters the next battle,
so the order is a real decision, and it is kept out of `actions` because taking
it costs no turn: a full team would otherwise add fifteen swap pairs beside the
real moves at every single map node.

---

## The rule that is not obvious

> **A submission must be self-contained.** If your bot carries trained weights,
> the state encoding has to be frozen **inside the bot file** rather than
> imported from `experiments/`. Otherwise improving the training code silently
> changes what every past submission meant, and old results quietly become wrong.

There is a mechanical reason on top of the principle: an entry archives **one
file**, the one holding your bot's class, and hashes it for the entry id. Split
your bot across two modules and the archive keeps an unrunnable half while the
hash stops identifying what actually ran.

[`bot/dyna_q.py`](src/pokelike/bot/dyna_q.py) is the small worked example;
[`bot/sarsa.py`](src/pokelike/bot/sarsa.py) is the large one.

---

## What counts as a bot

Anything that picks a move given the state. A prompt around an LLM, a model
fine-tuned on the game, reinforcement learning of any flavour, a hand-written
rulebook, search over the game tree since the engine ships a battle simulator you
can call, something deterministic if you can find one that works.

Ranked by **badges**, the game's own progress counter. The bar and the current
standings are in [leaderboard/README.md](leaderboard/README.md).
