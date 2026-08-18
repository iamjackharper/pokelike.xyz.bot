# experiments

**Yours is not tracked. Ours are, to be read.**

Anything you create under `experiments/` is gitignored, so what you try stays on
your machine and a pull request that adds a bot cannot drag six training runs
along with it. The folders below are ours and are checked in on purpose: they are
worked examples, and the point of them is that you can read what was actually
done rather than a description of it.

```
experiments/
├── env/            the game stated as an RL problem. Shared by all of them.
├── example/        the smallest complete experiment. Start here.
├── dyna_q/         tabular RL. It lost, and is kept because of that.
├── sarsa_lambda/   linear function approximation. The one that worked.
├── llm/            comparing prompts, which is not learning at all.
└── <yours>/        ignored.
```

Every one of them has the same shape, so moving between them costs nothing:

```
<experiment>/
├── README.md    what it asks, and what happened
├── agent.py     the thing being learned, if anything is
├── train.py     the loop
├── evaluate.py  against random, on held-out seeds, paired
├── output/      weights and histories        (ignored)
└── logs/        what each run printed        (ignored)
```

Copy the one closest to your idea into `experiments/mine/` and work there.

**Contents**
[What you have to show, and what you do not](#what-you-have-to-show-and-what-you-do-not) ·
[What the area is for](#what-the-area-is-for)

[`env/`](#env--the-game-as-an-rl-problem) ·
[`example/`](#example--the-shape-with-nothing-clever-in-it) ·
[What was learned here](#what-was-learned-here) ·
[Measuring anything](#measuring-anything)

---

## What you have to show, and what you do not

Submitting a bot **does** reveal the bot: an entry archives the file that ran and
hashes it, and that is the only reason the number beside it means anything. A
leaderboard where the code is hidden is a list of claims.

Submitting does **not** reveal how you got there. The sweeps, the rewards you
tried, the prompts you threw away, the twenty runs that went nowhere — that is
research, it lives here, and it stays yours.

You have to show what your bot does. Not how you arrived at it.

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

The code for each is in its own folder with its own README. This is the short
version, in the order it happened.

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

**Then an ablation answered less than it looked like.** Five feature sets, 300
episodes each, 25 held-out seeds, step size held fixed across variants:

```
full             100 feature   1.60 badges   vs random  t 3.43
action-only       84           1.36                     t 2.42
minimal           23           1.24                     t 3.00
no-v2             81           1.20                     t 4.30
no-interactions   64           1.12                     t 3.12
random                         0.64
```

Every variant beats random and **none beats another**: paired against the full
set, the four differences come out at t = −1.4 to −1.7. The ranking reads like a
result and is noise.

The demonstration is on one model: `full` scored 1.60 over those 25 seeds and
**1.10** over the 50 benchmark seeds. Same weights, opposite conclusion, and a
gap wider than anything in the table.

**25 seeds cannot tell feature sets apart on this game.** Worth knowing before
spending eight hours ranking variants that way. Comparisons against random are
fine — those are large effects — but variant against variant needs far more runs,
or a measurement with less variance in it than badges over a whole run.

**A warning worth repeating.** The FIRST attempt at that ablation put the two
smallest sets last, and was measuring something else: their weights had diverged,
to 10⁹ and 10³². The step size was normalised per active feature, and the number
of active features is a property of the feature set — the full set activates 9.0
per (s, a), the smallest 1.2. So dropping a group silently multiplied the
learning rate by up to 7.5, each run differed in two ways, and the comparison
answered neither. **If you ablate a feature set, hold the effective step fixed.**

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
