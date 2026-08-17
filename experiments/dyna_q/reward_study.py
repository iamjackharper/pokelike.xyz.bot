"""Does the reward you train on change the player you get?

    uv run python -m experiments.dyna_q.reward_study --episodes 150

Same algorithm, same hyperparameters, same training seeds, same evaluation
seeds. The only thing that varies is the reward function. If reward design
matters more than algorithm choice — which is the usual claim, and the reason
`env/rewards.py` is a registry rather than one function — it should show up here
as three visibly different players.

The hypotheses, written down before running so they can be wrong:

  game       the engine's own weights. In Story mode two of its terms never
             fire, leaving 5*KO - 10*faints, which says nothing about getting
             further. Expect a bot that fights and does not advance.
  progress   badges plus a payment per layer descended. Expect the one that
             actually goes somewhere.
  survival   +1 per step, -50 a faint. The densest signal available, and the
             one most likely to produce a coward: long runs, no badges.

Judged on BADGES, not on the reward each was trained with — comparing three
policies on three different scales would measure nothing. Badges are the game's
own progression counter and what the leaderboard ranks by.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

from experiments.env import TrainingEnv

from .agent import DynaQ

HERE = Path(__file__).parent
MODELS = HERE / "models"
RUNS = HERE / "runs"

REWARDS = ["game", "progress", "survival"]


def train_one(reward: str, episodes: int, port: int, **hp) -> DynaQ:
    from tqdm import tqdm

    agent = DynaQ(seed=1, **hp)
    with TrainingEnv(port=port, reward=reward) as env:
        bar = tqdm(range(episodes), desc=f"train {reward:<9}", unit="ep")
        badges = []
        for ep in bar:
            s, actions = env.reset(seed=1 + ep)
            while actions:
                a = agent.choose(s, actions)
                s2, actions2, r, done = env.step(a)
                agent.observe(s, a, r, s2, actions2)
                agent.plan()
                s, actions = s2, actions2
                if done:
                    break
            agent.end_episode()
            alive = env.game.last_alive or {}
            badges.append((alive.get("run") or {}).get("badges", 0))
            bar.set_postfix(badges=round(statistics.mean(badges[-25:]), 2),
                            states=len(agent.Q), eps=round(agent.epsilon, 3))
    return agent


def evaluate_one(agent: DynaQ, seeds: list[int], port: int, label: str) -> list[dict]:
    """Greedy play on held-out seeds. Exploration is for learning, not testing."""
    from tqdm import tqdm

    rows = []
    # The reward here is irrelevant to a greedy policy, but the env needs one.
    with TrainingEnv(port=port, reward="progress") as env:
        for seed in tqdm(seeds, desc=f"eval {label:<10}", unit="seed"):
            s, actions = env.reset(seed=seed)
            while actions:
                s, actions, _r, done = env.step(agent.choose(s, actions, greedy=True))
                if done:
                    break
            alive = env.game.last_alive or {}
            score = env.score() or {}
            rows.append({
                "seed": seed,
                "badges": (alive.get("run") or {}).get("badges", 0),
                "steps": env.steps,
                "score": score.get("points_no_time"),
                "faints": (score.get("breakdown") or {}).get("faints", 0),
                "kos": (score.get("breakdown") or {}).get("enemiesKO", 0),
            })
    return rows


def summarise(rows: list[dict]) -> dict:
    m = statistics.mean
    return {
        "badges": round(m([r["badges"] for r in rows]), 2),
        "badges_best": max(r["badges"] for r in rows),
        "steps": round(m([r["steps"] for r in rows]), 1),
        "faints": round(m([r["faints"] for r in rows]), 1),
        "kos": round(m([r["kos"] for r in rows]), 1),
        "score": round(m([r["score"] or 0 for r in rows]), 1),
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--episodes", type=int, default=150)
    p.add_argument("--eval-seeds", type=int, default=25)
    p.add_argument("--eval-seed0", type=int, default=30_000, help="held out from training")
    p.add_argument("--planning-steps", type=int, default=50)
    p.add_argument("--epsilon", type=float, default=0.4)
    p.add_argument("--rewards", default=",".join(REWARDS))
    p.add_argument("--port", type=int, default=8700)
    a = p.parse_args()

    rewards = [r.strip() for r in a.rewards.split(",") if r.strip()]
    seeds = list(range(a.eval_seed0, a.eval_seed0 + a.eval_seeds))
    hp = {"planning_steps": a.planning_steps, "epsilon": a.epsilon}

    started = time.monotonic()
    results = {}
    for i, reward in enumerate(rewards):
        agent = train_one(reward, a.episodes, port=a.port + i, **hp)
        agent.save(MODELS / f"reward_study_{reward}.json")
        rows = evaluate_one(agent, seeds, port=a.port + 50 + i, label=reward)
        results[reward] = {
            "summary": summarise(rows),
            "agent": agent.summary(),
            "runs": rows,
        }
        print(f"  {reward}: {results[reward]['summary']}", flush=True)

    # A random baseline on the same seeds, or the numbers float free.
    import random as _random

    from pokelike.bot import create

    rnd_rows = []
    with TrainingEnv(port=a.port + 99, reward="progress") as env:
        from tqdm import tqdm

        for seed in tqdm(seeds, desc="eval random    ", unit="seed"):
            rng = _random.Random(seed)
            _s, actions = env.reset(seed=seed)
            while actions:
                _s, actions, _r, done = env.step(rng.choice(actions))
                if done:
                    break
            alive = env.game.last_alive or {}
            score = env.score() or {}
            rnd_rows.append({
                "seed": seed,
                "badges": (alive.get("run") or {}).get("badges", 0),
                "steps": env.steps,
                "score": score.get("points_no_time"),
                "faints": (score.get("breakdown") or {}).get("faints", 0),
                "kos": (score.get("breakdown") or {}).get("enemiesKO", 0),
            })
    results["random"] = {"summary": summarise(rnd_rows), "runs": rnd_rows}

    elapsed = (time.monotonic() - started) / 60
    report(results, seeds, a.episodes, elapsed)

    RUNS.mkdir(parents=True, exist_ok=True)
    out = RUNS / "reward_study.json"
    out.write_text(json.dumps({
        "episodes": a.episodes,
        "hyperparameters": hp,
        "eval_seeds": seeds,
        "minutes": round(elapsed, 1),
        "results": results,
    }, indent=1), encoding="utf-8")
    print(f"\nsaved to {out}")
    return 0


def report(results: dict, seeds: list[int], episodes: int, minutes: float) -> None:
    print("\n" + "=" * 78)
    print(f"TRAINED ON {episodes} EPISODES, EVALUATED GREEDILY ON {len(seeds)} HELD-OUT SEEDS")
    print("=" * 78)
    head = f"{'reward':<12}{'badges~':>9}{'badges+':>9}{'steps~':>9}{'faints~':>9}{'KOs~':>8}{'score~':>9}"
    print(head)
    print("-" * len(head))
    for name, r in results.items():
        s = r["summary"]
        print(f"{name:<12}{s['badges']:>9}{s['badges_best']:>9}{s['steps']:>9}"
              f"{s['faints']:>9}{s['kos']:>8}{s['score']:>9}")

    base = results["random"]["summary"]["badges"]
    print(f"\nrandom baseline: {base} badges. Anything not above it did not learn to play,")
    print("whatever its training reward was doing.")
    print(f"\n{minutes:.0f} minutes")


if __name__ == "__main__":
    raise SystemExit(main())
