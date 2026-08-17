# Dyna-Q

Sutton & Barto, 2nd edition, **Chapter 8** "Planning and Learning with Tabular
Methods", **section 8.2** "Dyna: Integrated Planning, Acting, and Learning".

## The algorithm

Straight from the boxed pseudocode in section 8.2:

```
Initialise Q(s,a) and Model(s,a) for all s, a

Loop forever:
  (a) S  <- current (nonterminal) state
  (b) A  <- eps-greedy(S, Q)
  (c) Take action A; observe R, S'
  (d) Q(S,A) <- Q(S,A) + alpha [R + gamma max_a Q(S',a) - Q(S,A)]
  (e) Model(S,A) <- R, S'
  (f) Loop n times:
        S      <- random previously observed state
        A      <- random action previously taken in S
        R, S'  <- Model(S,A)
        Q(S,A) <- Q(S,A) + alpha [R + gamma max_a Q(S',a) - Q(S,A)]
```

Steps (a) to (d) are plain **Q-learning** (section 6.5). Everything Dyna adds is
(e) and (f): a learned model of the environment, and `n` extra updates per real
step drawn from remembered experience.

In `agent.py` those map to `observe()` for (d) and (e), and `plan()` for (f).

## Why this algorithm first

Because the environment is slow. A real step drives a browser and costs about
0.7 seconds; a planning update is a dict lookup and a bit of arithmetic. Dyna
exists precisely for that trade-off, and this problem happens to fit the
motivation almost too well.

Measured on a 20-episode run: **380 real steps produced 7749 Q updates**. Same
wall clock, twenty times the learning.

## Two departures from the book

**1. The action set changes with the state.** In the maze of section 8.2 every
state offers the same four moves, so `max_a Q(S',a)` ranges over a fixed set.
Here a turn offers 2 to 7 options and they differ every time, so the model
stores which actions were legal in `S'` and the max is taken over those.
Maximising over unavailable actions would leak value from moves that cannot be
played.

**2. The model is deterministic, the game is not.** The book's Dyna-Q assumes a
deterministic environment and keeps one `(R, S')` per pair. Battles roll damage,
so the same `(S, A)` can lead elsewhere. We keep the book's assumption
deliberately: it is the simplest thing that works, and the compressed state hides
much of the variation. It is also the first thing to revisit if learning
plateaus — either stochastic Dyna-Q with outcome counts, or **Dyna-Q+**
(section 8.3).

## Running it

```bash
# train (about 15 minutes for 50 episodes)
uv run python -m training.dyna_q.train --episodes 50

# does it beat random? same seeds for both, held out from training
uv run python -m training.dyna_q.evaluate --episodes 30 --seed0 5000
```

| flag | meaning | default |
|---|---|---|
| `--episodes` | how many runs to learn from | 200 |
| `--planning-steps` | the `n` of the algorithm box | 20 |
| `--alpha` | step size | 0.1 |
| `--gamma` | discount | 0.95 |
| `--epsilon` | initial exploration, annealed to 0.02 | 0.3 |
| `--optimistic` | initial Q; > 0 encourages early exploration | 0.0 |
| `--fixed-seed` | replay the same run every episode | off |
| `--seed0` | seed of the first episode | 1 |

`--fixed-seed` is the sanity check worth running first: on a single repeated run
the agent should get visibly better within a few dozen episodes. If it does not,
the bug is in the encoding or the reward, not in the hyperparameters.

## Where to look when tuning

**`--planning-steps` is the cheap knob.** It costs no browser time. Raising it
to 50 is nearly free in wall clock. Diminishing returns come from the model
being wrong (see departure 2), not from cost.

**The encoding matters more than the hyperparameters.** `common/features.py`
decides what the agent can even distinguish. If two situations that need
different moves collapse into the same key, no amount of `alpha` will save it.

**`gamma` at 0.95 over 15-to-35-step episodes** means the +500 for finishing is
discounted to roughly 500 × 0.95³⁰ ≈ 107 at the start of a run. Since almost no
early run finishes, that term does very little in practice; the learning signal
that actually drives things is +50 per map cleared.

## Results so far

Only a 20-episode smoke run, which is far too short to claim anything:

```
               mean   median   worst    best
dyna-q           25     25.0      -5      55
random         11.2     12.5       0      20
head to head: dyna-q wins 2/4
```

Four seeds is noise. Treat this as evidence that the pipeline runs end to end,
not as evidence that the agent learned. A real number needs a few hundred
training episodes and at least 30 evaluation seeds.
