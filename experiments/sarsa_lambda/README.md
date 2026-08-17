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
node leads. `features.py` parses the Pokemon card text the tabular agent threw
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
ep   0-24   0.75 badges     <- indistinguishable from random
ep  25-49   1.04
ep  50-74   1.42            <- most of it, in fifty episodes
ep 275-299  1.31
```

It arrives in about 50 episodes, roughly 1000 transitions, and then flattens.
Dyna-Q had 400 episodes and never left the floor.

**Read the plateau as a limit of the features, not of the method.** The weights
say where it comes from: the largest are `team_size`, `bias`, `map_index`,
`badges`, all of which are state-only. They shift every action in a state by the
same amount and therefore cancel in the argmax — they fit the level of the
return, not the choice. The features that actually decide anything are further
down: `node:trainer*small_team`, `mon_new_type`, `mon_best_stats`. That is the
next thing worth working on, and it is not a hyperparameter.

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
| `--reward` | which reward (see `mdp/rewards.py`) | progress |

## You can read what it learned

The point of a linear model. Training prints the weights it leaned on hardest,
and they are named:

```
what it leaned on:
  mon_new_type                  5.538
  mon_best_stats                5.074
  leads_to_catch                3.657
```

That is a policy you can argue with, which a value table of 400 opaque cells is
not.

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
