# lspi

LSTD-Q(λ) + Least-Squares Policy Iteration (Lagoudakis & Parr, JMLR 2003;
Boyan 2002 for the λ trace form). Same 100 hand-built linear features as
`bots/sarsa-v2`, same environment, same reward. What differs is how the
weights are estimated: instead of an incremental, step-size-driven update,
this solves the exact linear fixed point of the projected Bellman equation
from batch statistics accumulated over real transitions, then re-solves
periodically as more data arrives and the policy improves.

```bash
uv run pokelike bot --bot lspi --runs 5 -d
uv run pokelike bench --bot lspi --dry-run
```

| | |
|---|---|
| how it works | `q̂(s,a) = wᵀx(s,a)`, w solved exactly each policy-iteration round rather than nudged by gradient steps |
| what it scored | **1.44 badges** mean, best single run 8, over the official 50 seeds |
| what was tried and dropped | three ways of reusing real transitions harder via extra gradient steps (true online traces + per-episode λ-return replay, cross-episode experience replay buffer) — all measured worse than plain accumulating-trace SARSA(λ), see `experiments/rl_sample_efficient/README.md` |

Trained by `experiments/lspi/train.py` (not shipped — research folder, see
that experiment's README for the full derivation, the numerical-stability fix
that mattered, and the measurements against the SARSA(λ) baseline).
