# experiments

**This is your scratch area, and it is not tracked.**

Everything under `experiments/` is gitignored except the two things below, so
whatever you try here stays on your machine. A pull request that adds a bot
should carry the bot, not the six training runs it took to get there.

```
experiments/
├── env/         the game stated as an RL problem. Shared, tracked.
├── example/     the smallest complete experiment. Tracked, as a starting point.
└── <yours>/     anything else. Ignored.
```

Copy `example/` to `experiments/mine/` and work there.

---

## What the area is for

A bot is one method: given the state, say which move to take. Everything that
goes into *deciding what that method should do* belongs here — training a policy,
comparing prompts, sweeping hyperparameters, measuring whether an idea helps.

Nothing in `src/pokelike/` imports anything from here, and that is a rule rather
than an accident. The package is the environment; this is the research on top of
it. A submitted bot has to stand on its own, so if yours carries trained weights
the state encoding is frozen **inside the bot file** rather than imported from
here — otherwise improving your training code would silently change what your
own past results meant. See [GUIDE.md](../GUIDE.md).

## `env/` — the game as an RL problem

The part every experiment shares, whatever it is doing.

| file | what it holds |
|---|---|
| `environment.py` | `TrainingEnv`: reset and step in RL terms |
| `rewards.py` | five reward functions, selectable by name |
| `encoding.py` | observation to a discrete state key, for tabular methods |
| `logs.py` | `tee()`: a run writes its own log into `<experiment>/logs/` |

**An MDP** — a Markov Decision Process — is the standard way of stating a problem
so Reinforcement Learning applies to it: states, the actions available in each,
and a reward. That is all `env/` is.

**Reward matters more than the algorithm here**, which is why it is a registry
rather than one function:

```bash
uv run python -m experiments.example.train --reward badges
```

| reward | signal |
|---|---|
| `game` | the engine's own score |
| `badges` | the game's progress counter, and what the leaderboard ranks by |
| `progress` | badges, plus credit for getting deeper into a map |
| `survival` | staying alive; dense, and easy to learn the wrong lesson from |
| `composite` | a weighted mix |

Careful with `game`. The engine's score formula was written for the Battle Tower
and two of its six terms never fire in Story mode, leaving `5·KO − 10·faints` —
a number that rewards fighting rather than getting further. It is why a run with
three badges can score −5.

## `example/` — the shape, with nothing clever in it

```bash
uv run python -m experiments.example.train --episodes 20
```

It learns one number per node kind: how much that kind of node seems to be
worth. No state at all, so it will not beat much. It is here for the loop —
play, score, update, save — which is what every experiment in this project has
been, with something better in the middle.

---

## What was learned here

The code that produced these is not in the repo, because it was ours and the
same rule applies to us. The findings are, because they are the part worth
keeping.

**Tabular Dyna-Q lost to random.** 400 episodes, a state key of six numbers:
−3.8 mean score against random's 7.0 on held-out seeds, winning 6 of 20. Its own
decision log said why before the evaluation did:

```
    1 | starter-screen
      | [0] Bulbasaur Lv5  [1] Charmander Lv5  [2] Squirtle Lv5
      |    Q: slot0=6.3, slot1=6.2, slot2=6.3
```

Three values within a rounding error, because the encoding showed it three
indistinguishable slots where a player sees a Grass starter, a Fire one and a
Water one with different stats. **No number of episodes fixes that: the
information never reaches the table.**

**Linear SARSA(λ) with hand-built features won**, on the same reward, the same
environment and the same protocol: 15 wins, 10 draws, no losses over 25 held-out
seeds, +0.88 badges per run, t = 4.18. The change was the representation, not
the algorithm.

**And then more features bought nothing.** Nineteen more — team order, items, the
move tutor — measured head to head on the 50 standard seeds against the same
policy without them: +0.06 badges, t = 0.62. Adding what the agent can see is not
the same as adding what it can *use*.

**A warning worth repeating.** In an early ablation the two variants with the
fewest features diverged, to 10⁹ and 10³². The step size was normalised per
active feature, so dropping a group silently multiplied the effective learning
rate by up to 7.5. Each run differed in two ways and the comparison answered
neither. If you ablate a feature set, hold the effective step fixed across the
variants.

## Measuring anything

Against the same seeds, paired. Runs vary enormously by luck here, so two
separate averages mostly measure who drew the nicer maps:

```python
from pokelike import compare
from pokelike.bot.mine import MyBot

print(compare({"mine": MyBot()}, seeds=range(25))["table"])
```

It reports wins, draws, losses and a t. With this much variance, a difference in
means on its own says very little.
