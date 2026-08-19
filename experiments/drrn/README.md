# A network where SARSA has a dot product

    q̂(s, a) = MLP(x(s, a))          against        q̂(s, a) = wᵀ x(s, a)

One variable moved from `sarsa-v2`: the shape of q̂. Same 100 features, same
reward, same benchmark. Whatever the numbers say is about that.

**Contents**
[What it asks](#what-it-asks) ·
[Why a network, given the linear model plateaued](#why-a-network-given-the-linear-model-plateaued) ·
[Why the data comes first](#why-the-data-comes-first) ·
[Running it](#running-it) ·
[Layout](#layout) ·
[What would refute it](#what-would-refute-it)

---

## What it asks

Three things have been tried on the linear model and none of them moved the
benchmark:

| | badges |
|---|--:|
| more episodes, 300 → 1200 | +0.02 |
| dropping the features that cannot decide | −0.02 |
| more features, 81 → 100 | +0.06 |

The standard error of the mean over 50 seeds is about 0.1 badges, so all three
are noise. The budget is not the limit and the choice of features is not the
limit. What is left is what the model can express given them.

## Why a network, given the linear model plateaued

Read the weights the linear model learns and the largest by far — `team_size`,
`bias`, `map_index`, `badges` — are all state-only. They read the same for
every action available in a state, so they shift each option by the same amount
and cancel in the argmax: they cannot change a single decision. Measured on a
real state, 8 of the 17 active features are in that position and they carry 475
of the 552 total weight.

The obvious conclusion, that they are dead weight, is wrong: dropping them
scores 1.36 against 1.38, which is the same. They are not useless and they are
not policy. What they are is a term that only means anything **crossed with the
action** — how much a trainer node is worth depends on how small the team is.

A linear model can only carry such a cross if a person writes the product down,
and three are written down today (`node:trainer*small_team` and two others; one
of them is among the few large weights that *can* decide). A hidden layer builds
those products out of the same inputs without anyone choosing which.

That is the hypothesis in one line: **the features are fine and the model cannot
combine them.**

## Why the data comes first

Collecting and fitting are bound by different things. Playing is bound by the
browser — one per process, half a second a step — while fitting a small network
to a fixed array is bound by arithmetic and wants everything in memory at once.
Split, 22 cores become 22× the data instead of 22 copies of one run.

So: collect once in parallel, then fit offline as many times as you like. A
round of fitted Q iteration over the whole dataset takes seconds, which means
twenty rounds of policy improvement cost less than one episode of play.

Fitted Q iteration (Ernst, Geurts & Wehenkel, JMLR 2005) treats improvement as a
sequence of ordinary regressions: round *k* builds `y = r + γ·max_a' Q_{k-1}(x')`
for every transition and fits `Q_k` to it. This is why collection records the
features of **every** action available at the next decision point, not just the
one that was taken — the max needs them, and a dataset without them can only
evaluate the policy that produced it.

The behaviour policy is deliberately mixed, half guided and half random. Data
drawn only from a good policy contains no examples of where the bad options
lead, which is precisely what a max over actions has to know.

Between rounds the network is periodically re-initialised while the data is
kept. Reusing one dataset many times overfits a network to whatever it saw first
and more reuse makes it worse — the primacy bias (Nikishin et al.,
arXiv:2205.07802). Throwing the weights away is what makes the reuse safe; the
improvement is carried by the targets, which live in the dataset.

## Running it

Numpy is not a project dependency — a bot has to load in any checkout — so it
comes in for the command and leaves again:

```bash
# 1. collect, in parallel, once
uv run --with numpy python -m experiments.drrn.collect \
    --episodes 4000 --workers 8 --tag mixed \
    --weights bots/sarsa-v2/artifacts/weights.json

# 2. fit, offline, as often as you like
uv run --with numpy python -m experiments.drrn.train --data mixed --iters 30

# 3. measure, the one way there is
cp output/models/drrn.json artifacts/weights.json
uv run pokelike bench --bot experiments/drrn --dry-run
```

| flag | meaning | default |
|---|---|---|
| `--workers` | parallel collectors, one browser each | 1 |
| `--random-share` | share of episodes played at random | 0.5 |
| `--iters` | fitted Q rounds | 30 |
| `--hidden` | layer sizes | `64,64` |
| `--reset-every` | re-initialise the network every N rounds; 0 disables | 10 |
| `--epochs` | passes over the data per round | 6 |

The trained net exports as JSON and the bot does the forward pass in plain
Python, so nothing a submission plays needs numpy installed. The two
implementations of that arithmetic are checked against each other in the test
suite, because a silent drift between them would leave the bot playing a
different policy from the one that was measured.

## Layout

```
drrn/
├── agent.py     the network: forward, backprop, Adam, reset, export
├── collect.py   play episodes, write transitions, fan out over processes
├── train.py     fitted Q iteration over a collected dataset
├── bot.py       the player: frozen features, pure-Python forward pass
├── artifacts/   the weights the bot reads
├── output/      data shards, models, histories   (gitignored)
└── logs/        what each run printed            (gitignored)
```

## What would refute it

A benchmark number at or below 1.36. That would say the features are the
ceiling, and that capacity on top of them buys nothing — which would make the
next thing worth trying a change to what the agent can see, not to how it
combines what it already sees.

Worth being clear in advance: 1.38 would not be a win either. Two bots need
roughly 0.3 badges between them to be distinguishable over 50 seeds.
