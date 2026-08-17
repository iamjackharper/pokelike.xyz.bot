# training

Reinforcement Learning on pokelike. This folder sits outside the `pokelike`
package on purpose: the package is the environment (mirroring, browser, game
logic), this is the research on top of it.

```
training/
├── common/              shared by every algorithm
│   ├── features.py        state -> key, action -> key, reward
│   └── environment.py     TrainingEnv: reset/step with hashable keys
└── dyna_q/              one folder per algorithm
    ├── agent.py           the algorithm
    ├── train.py           training script
    ├── evaluate.py        trained vs random, on the same seeds
    ├── models/            saved tables (gitignored)
    └── runs/              training histories (gitignored)
```

Run everything from the repo root, as modules:

```bash
uv run python -m training.dyna_q.train --episodes 200
uv run python -m training.dyna_q.evaluate --episodes 30
```

## The problem, stated as an MDP

**State.** The full observation is a dict with a team, a bag and a map graph.
Far too large for a table, so `common/features.py` compresses it to a tuple:
screen, team size, worst HP bucket, map index, depth on the map, badges, and the
set of actions on offer. That last field matters more than it looks — without it
one table cell would mix turns offering completely different options.

**Actions.** Between 2 and 7 per turn, and they change every turn. Crucially
they are *not* stable by position: index 2 is a battle now and a catch next
turn. So actions are keyed by what they are (`node:catch`, `btn:skip`), which is
what makes `Q(s, a)` accumulate meaningfully.

**Reward.** Selectable, from a registry in `common/rewards.py`, because here the
choice of reward matters more than the choice of algorithm and that claim is
worth testing rather than asserting.

```bash
uv run python -m training.dyna_q.train --reward progress --episodes 200
```

| reward | signal | density |
|---|---|---|
| `game` | the engine's own weights, verbatim | medium |
| `badges` | +100 a badge, −10 a faint | very sparse |
| `progress` | badges, plus payment per layer descended | dense |
| `survival` | +1 per step, −50 a faint | densest |
| `composite` | progress plus damage efficiency | dense |

`game` is kept as the honest baseline, but be careful with it: the engine's
formula was written for the Battle Tower, and in Story mode `mapsCleared` never
increments (it only happens inside `bumpEndlessCounters()`) while `winBonus`
essentially never fires. What survives is `5·KO − 10·faints`, which says nothing
about getting further and does not mention badges at all. That is why a run with
three badges can score −5, and why `progress` is the default.

**Episode.** One run, from picking a starter to game over. Typically 12–35
decisions.

## What makes this environment awkward

Worth knowing before you pick an algorithm.

**It is slow.** About 0.7 s per step, since every step drives a real browser. A
200-episode run takes roughly an hour. This is the single biggest constraint and
it is why Dyna-Q is the first thing here: planning steps cost nothing.

**Rewards are sparse and delayed.** Most turns return 0. The interesting signals
(clearing a map, losing a Pokemon) arrive several decisions after the choice
that caused them.

**It is stochastic.** Battles roll damage, so the same state and action do not
always lead to the same place. The seed pins a whole run, not a single
transition.

**The action set is state-dependent.** Any `max_a` has to range over the legal
actions only.

## Comparing fairly

Runs vary enormously by luck. Comparing two policies on different seeds mostly
measures which one got the nicer maps, so `evaluate.py` runs both on **the same
seeds** and reports the head-to-head. Use held-out seeds well away from the
training range, or you are grading on the training set.

**Rank by badges, not by score.** Badges are the game's own progression counter
in Story mode; the score formula, for the reasons above, rewards fighting rather
than advancing.

The baseline to beat is the random bot: 0.68 badges on average over the 50
benchmark seeds, dead in 17 moves.

## Adding another algorithm

Copy the shape of `dyna_q/`: a folder with `agent.py`, `train.py`,
`evaluate.py`, `models/`, `runs/`. Reuse `common/` so every algorithm learns on
the same encoding and the same reward, otherwise the comparison between them
means nothing.

Reasonable next steps, in rough order of effort:

- **Dyna-Q+** (Sutton & Barto 8.3) — adds an exploration bonus for state-action
  pairs not tried in a while. Cheap to add on top of what is here.
- **Prioritised sweeping** (8.4) — spend the planning budget where the value is
  changing most, instead of sampling uniformly. Should help a lot given how
  expensive real steps are.
- **n-step SARSA** (Chapter 7) — better suited to delayed rewards than one-step
  backups.
- **Linear function approximation** (Chapter 9) — the honest fix for the state
  space, instead of hand-tuning the buckets in `features.py`.

If you change `features.py`, bump `ENCODING_VERSION` in the agent. Saved tables
are keyed by encoded states, so an old table under a new encoding is not just
stale, it is meaningless — and loading it silently would be worse than an error.
