# SARSA(λ) with linear function approximation

Sutton & Barto, 2nd edition: **chapter 10** "On-policy Control with
Approximation" for the semi-gradient control update, **section 12.7** for the
SARSA(λ) form.

    q̂(s, a, w) = wᵀ x(s, a)

## Why, after Dyna-Q

Tabular Dyna-Q was given a fair run: 400 episodes, encoding v2, 50 planning
steps, 465k updates. Evaluated greedily on 20 held-out seeds against random on
the same seeds:

```
               mean score   median   worst   best
dyna-q               -3.8      7.5     -75     40
random                7.0      7.5     -50     50

paired: dyna-q wins 6/20, draws 2, loses 12
```

It lost. And the detailed log said why long before the evaluation did:

```
    1 | starter-screen
      | [0] Bulbasaur Lv5  [1] Charmander Lv5  [2] Squirtle Lv5
      |    Q: slot0=6.3, slot1=6.2, slot2=6.3
```

Three values within a rounding error of each other, because the encoding shows
the agent three indistinguishable slots. A player sees a Grass/Poison starter, a
Fire one and a Water one, each with different stats. **No number of episodes
fixes that: the information never reaches the table.**

So the problem was never the algorithm. It was that the agent could not see.

## What changes

**It can see.** Features carry what is on screen — a candidate's types, whether
they are new to the team, its bulk against the other two on offer, where a map
node leads. `features/groups.py` parses the Pokemon card text the tabular agent threw
away.

**It generalises.** Weights are shared, so "catch something that adds a type I
lack" is learned once and applies everywhere, instead of being relearned in each
table cell. That matters here more than usual: every real step costs half a
second of browser, so the sample budget is a few thousand transitions, not
millions.

**Credit reaches back.** Badges arrive many decisions after the choices that
earned them. A one-step backup moves credit one step per visit; λ = 0.9 spreads
it down the whole chain at once.

**Actions stay distinct.** It drives `Game` by action index rather than by key,
so the five EQUIP buttons are five actions with five feature vectors. The tabular
agent collapsed them into one `btn:equip` and could not choose *who* to equip.

**It decides the team order** (feature set v2). Slot 0 leads the next battle, and
reordering costs no turn — so it is modelled as an extra **state** in the MDP with
reward 0, not an extra action in the existing one. Its options are "leave it" plus
"bring slot j to the front", scored by the same q̂ and the same weights, and
SARSA(λ)'s traces carry the credit back through the swap on their own. Available
in about 61% of turns.

Every `order:` feature is a difference against the current leader, or an
interaction with the leave-it option. One that read the same for every option
would cancel in the argmax — the mistake the ablation exists to find, applied
before the fact this time.

## No neural network, on purpose

Not modesty — arithmetic. An episode is ~20 transitions and a step costs ~0.5 s,
so 300 episodes is about 6000 transitions in an hour. A DQN's usual budget is
10⁵–10⁶ transitions: 20 to 200 hours of wall clock for one run, before any
tuning. The binding constraint is samples, not model capacity, and hand-built
features plus a linear model is what that budget buys.

If the features turn out to carry the day, that is the evidence that would
justify learning a representation instead of writing one.

## What happened

300 episodes, reward `progress`, 98 minutes, 5988 updates. Then greedy on seeds
40000-40024, which training never touched, against random on those same seeds:

```
            badges~  badges+   steps~  faints~   score~
sarsa          1.52        5     21.9      3.0     67.6
random         0.64        2     17.6      4.0      3.2

paired: sarsa wins 15, draws 10, loses 0 out of 25
mean difference: +0.88 badges per run       t = 4.18
```

Not one loss in 25, and the draws are nearly all 0-0 on seeds where both runs
die early. Same environment, same reward, same held-out protocol on which
tabular Dyna-Q went **backwards** (−3.8 against random's 7.0). The change was
the representation, and that was the hypothesis.

The learning curve says the same thing about sample cost:

```
ep   0-24   0.84 badges     <- random gets 0.68
ep  25-49   1.20
ep  50-74   1.56            <- most of it, in fifty episodes
ep  75-99   1.20
ep 275-299  1.12
```

Badges per episode, in blocks of 25, from `output/runs/sarsa_v1_history.json`.
It arrives in about 50 episodes, roughly 1000 transitions, and then not only
flattens but drifts back down as epsilon anneals. Dyna-Q had 400 episodes and
never left the floor.

**Read the plateau as a limit of the features, not of the method.** The weights
say where it comes from: the largest are `team_size`, `bias`, `map_index`,
`badges`, all of which are state-only. They shift every action in a state by the
same amount and therefore cancel in the argmax — they fit the level of the
return, not the choice. The features that actually decide anything are further
down: `node:trainer*small_team`, `mon_new_type`, `mon_best_stats`. That is the
next thing worth working on, and it is not a hyperparameter.

## Layout

```
sarsa_lambda/
├── agent.py          the algorithm: q̂ = wᵀx, traces, the update
├── train.py          the three things you run
├── evaluate.py
├── ablation.py
├── features/         THE REPRESENTATION — the part worth arguing about
│   ├── groups.py       the 81 features, in named groups
│   └── variants.py     which groups a run carries, and what it is asking
└── output/           weights, histories, ablation results (gitignored)
```

`features/` is its own package because of what Dyna-Q taught: the update rule was
never the problem, the vector was. Keeping it separate makes it possible to
switch a group off and leave everything else meaning the same thing.

## Which features actually decide anything

```bash
uv run python -m experiments.sarsa_lambda.ablation --list          # the questions
uv run python -m experiments.sarsa_lambda.ablation --episodes 300 --workers 4
```

Every variant is a question with an answer you can be wrong about, written down
in `features/variants.py` **before** the run, so the result cannot be
reinterpreted afterwards into whatever happened.

One training run is about 100 minutes. At that price you test two ideas and
stop, which is how a plateau gets blamed on the step size. So variants train at
the same time, one process and one browser each.

The parallelism is deliberately **between** runs and never inside one. SARSA is
on-policy with eligibility traces: splitting episode collection across several
environments would draw updates from a behaviour distribution the traces do not
describe, which is a different algorithm wearing the same name. Whole
independent runs sidestep that, and comparing variants is exactly the case where
that is all you need.

A variant that drops features and does **not** get worse is the interesting
result, not a disappointing one: it means those features were never doing the
work their weights suggested.

### The first ablation, and why it does not answer the question

```
variant           feats   badges~   score~   vs random     t     max |w|
full                 81      1.52     67.6   15W-10D-0L  4.18        129
no-interactions      45      1.28     54.0   12W-11D-2L  2.87        138
minimal              23      1.04    -16.0   12W-10D-3L  2.62   3.81e+32
action-only          65      0.88    -29.6    8W-15D-2L  2.01   2.35e+09
random                       0.64      3.2
```

Read the last column before the others. **The two worst variants are the two
that diverged numerically.** Their scores measure what a broken linear model
does, not what those features are worth.

The cause is in this repo, not in the game: α is normalised **per active
feature** (`alpha / len(x)`). Dropping groups leaves fewer active features per
(s, a), so the effective step per feature grows — and the divergence order
follows the active-feature count exactly. So each variant changed two things at
once, the features and the learning rate, and an ablation that varies two things
answers nothing.

It is the first suspect named in "where to look if it stalls", below, and it
still got missed. The rerun holds the effective step fixed across variants.

One thing did come out clean: `full` reproduced the original run **bit for bit**
across the features/ repackaging, the `FeatureSet` refactor and the move to
`output/`. The restructure moved nothing.

## Running it

```bash
uv run python -m experiments.sarsa_lambda.train --episodes 300 --reward progress
uv run python -m experiments.sarsa_lambda.evaluate --episodes 25 --seed0 40000
```

| flag | meaning | default |
|---|---|---|
| `--alpha` | step size, divided by the number of active features | 0.05 |
| `--gamma` | discount | 0.98 |
| `--lam` | trace decay λ | 0.9 |
| `--epsilon` | initial exploration, annealed to 0.02 | 0.3 |
| `--reward` | which reward (see `env/rewards.py`) | progress |
| `--out` | *train*: file to write in `output/models/` | `sarsa.json` |
| `--table` | *evaluate*: file to read from `output/models/` | `sarsa.json` |
| `--groups` | *train*: feature groups to keep, comma separated | all |

`--out` deliberately does not default to `sarsa_v1.json`: that is the file
[`bot/sarsa.py`](../../src/pokelike/bot/sarsa.py) loads, so a training run
writing there would silently replace the policy that is on the leaderboard.

## You can read what it learned

The point of a linear model. Training prints the weights it leaned on hardest,
and they are named:

```
what it leaned on:
  team_size                  -129.276
  bias                         93.125
  map_index                   -79.623
  ...
  node:trainer*small_team      29.392
  mon_new_type                 18.384
  mon_best_stats               17.706
```

That is a policy you can argue with, which a value table of 400 opaque cells is
not — and arguing with this one is what produced the ablation above. The first
three depend on the state and not the action, so they add the same number to
every option and cancel in the argmax. Read literally, most of this policy's
weight is not policy.

## Where to look if it stalls

**The features, before the hyperparameters.** If two situations that need
different moves produce the same vector, no step size will separate them.
`feature_names()` is the whole vocabulary the agent has.

**α is normalised per active feature** so that adding features does not silently
multiply the effective learning rate. That mistake looks exactly like the
algorithm being unstable.

**Linear approximation plus bootstrapping can diverge** (chapter 11, the deadly
triad). SARSA is on-policy, which removes one leg of it, but if weights start
growing without bound the step size is the first suspect.
