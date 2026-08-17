# experiments

Attempts at making a bot play well. Not all of them are training: teaching a
policy with Reinforcement Learning and finding a better prompt for an LLM are
both ways of improving a player, and neither is more legitimate than the other.

This folder sits outside the `pokelike` package on purpose. The package is the
environment (mirroring, browser, game rules); this is the research on top of it.

```
experiments/
├── env/                 the game turned into an RL problem
│   ├── encoding.py        observation -> state key, action -> stable key
│   ├── rewards.py         five reward functions, selectable by name
│   └── environment.py     TrainingEnv: reset/step in those terms
├── dyna_q/              tabular RL (Sutton & Barto 8.2)
│   ├── agent.py           the algorithm
│   ├── train.py           training script
│   ├── evaluate.py        trained vs random, on the same seeds
│   ├── reward_study.py    same algorithm, three rewards, one metric
│   ├── models/            saved tables (gitignored)
│   └── runs/              histories (gitignored)
├── sarsa_lambda/        linear function approximation (S&B 10 and 12.7)
│   ├── agent.py           q̂ = wᵀx, eligibility traces, the update
│   ├── train.py evaluate.py ablation.py
│   ├── features/          x(s,a): what the tabular encoding threw away
│   │   ├── groups.py        the 81 features, in named groups
│   │   └── variants.py      which groups a run carries, and what it asks
│   └── output/            weights, histories, results (gitignored)
└── llm/                 prompt engineering, measured
    └── compare.py         strategies played head to head on identical seeds
```

`env/` was `common/` and then `mdp/`. `common/` was a lie: the LLM experiment reads the
raw observation and imports none of it. What lives there is the Reinforcement
Learning formulation of the game, and nothing else needs it.

Run everything from the repo root, as modules:

```bash
uv run python -m experiments.dyna_q.train --episodes 200 --reward progress
uv run python -m experiments.dyna_q.evaluate --episodes 30
uv run python -m experiments.llm.compare --strategies survivor,explorer --seeds 5
```

Whatever the experiment, the yardstick is the same: **badges**, measured by the
standard benchmark. The training reward is the signal you learn from; badges and
the game's score are the independent measurement of whether it worked.

## The problem, stated as an MDP

**State.** The full observation is a dict with a team, a bag and a map graph.
Far too large for a table, so `env/encoding.py` compresses it to a tuple:
screen, team size, worst HP bucket, map index, depth on the map, badges, and the
set of actions on offer. That last field matters more than it looks — without it
one table cell would mix turns offering completely different options.

**Actions.** Between 2 and 7 per turn, and they change every turn. Crucially
they are *not* stable by position: index 2 is a battle now and a catch next
turn. So actions are keyed by what they are (`node:catch`, `btn:skip`), which is
what makes `Q(s, a)` accumulate meaningfully.

**Reward.** Selectable, from a registry in `env/rewards.py`, because here the
choice of reward matters more than the choice of algorithm and that claim is
worth testing rather than asserting.

```bash
uv run python -m experiments.dyna_q.train --reward progress --episodes 200
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

## Adding another experiment

Copy the shape of `dyna_q/` for an algorithm: a folder with `agent.py`,
`train.py`, `evaluate.py`, `models/`, `runs/`. Reuse `env/` so everything learns on the same
encoding and the same rewards, otherwise comparing them means nothing.

For anything that is not training — a new prompt family, a hand-written
heuristic, a search — copy the shape of `llm/` instead: a script that runs the
variants head to head on identical seeds and reports the paired difference.

Reasonable next steps, in rough order of effort:

**What has been tried, and how it went.** Tabular Dyna-Q, given 400 episodes and
encoding v2, lost to random on 20 held-out seeds: −3.8 mean score against 7.0,
winning 6 of 20. Its own decision log explains it — on the starter screen it
learns Q values of 6.3 / 6.2 / 6.3, three slots it has no way to tell apart. The
limit is the representation, not the algorithm, which is what `sarsa_lambda/`
exists to test.

SARSA(λ) with linear features tested it and the answer was yes. On 25 held-out
seeds, paired against random on the same seeds: **15 wins, 10 draws, no losses**,
+0.88 badges per run, t = 4.18. On the 50 official benchmark seeds it leads the
leaderboard with 1.3 badges and 59.3 mean score, against random's 0.68 and −3.5.
Same environment, same reward, same protocol Dyna-Q lost under. See
[`sarsa_lambda/README.md`](sarsa_lambda/README.md).

- **Dyna-Q+** (Sutton & Barto 8.3) — adds an exploration bonus for state-action
  pairs not tried in a while. Cheap to add on top of what is here.
- **Prioritised sweeping** (8.4) — spend the planning budget where the value is
  changing most, instead of sampling uniformly. Should help a lot given how
  expensive real steps are.
- **n-step SARSA** (Chapter 7) — better suited to delayed rewards than one-step
  backups.
- **Linear function approximation** (Chapter 9) — the honest fix for the state
  space, instead of hand-tuning the buckets in `env/encoding.py`.

If you change `env/encoding.py`, bump `ENCODING_VERSION` there. Saved tables
are keyed by encoded states, so an old table under a new encoding is not just
stale, it is meaningless — and loading it silently would be worse than an error.
