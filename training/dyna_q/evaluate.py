"""Does the trained agent actually beat random?

    uv run python -m training.dyna_q.evaluate --episodes 30

Both policies are run on THE SAME SEEDS, which matters more than it sounds: runs
vary enormously by luck, and comparing two policies on different seeds mostly
measures which one got the nicer maps. Same seeds turns it into a paired
comparison, where the difference per seed is the thing to look at.

Evaluation is greedy (epsilon = 0). Exploration is for learning; at test time you
want the policy the agent believes in.
"""

from __future__ import annotations

import argparse
import random
import statistics
from pathlib import Path

from training.common.environment import TrainingEnv

from .agent import DynaQ

HERE = Path(__file__).parent
MODELS = HERE / "models"


def play_greedy(env: TrainingEnv, agent: DynaQ, seed: int) -> dict:
    s, actions = env.reset(seed=seed)
    total = 0.0
    while actions:
        a = agent.choose(s, actions, greedy=True)
        s, actions, r, done = env.step(a)
        total += r
        if done:
            break
    score = env.score() or {}
    return {"reward": total, "score": score.get("points_no_time"),
            "steps": env.steps, "ending": (env.observation or {}).get("screen")}


def play_random(env: TrainingEnv, seed: int) -> dict:
    rng = random.Random(seed)
    _, actions = env.reset(seed=seed)
    total = 0.0
    while actions:
        _, actions, r, done = env.step(rng.choice(actions))
        total += r
        if done:
            break
    score = env.score() or {}
    return {"reward": total, "score": score.get("points_no_time"),
            "steps": env.steps, "ending": (env.observation or {}).get("screen")}


def evaluate(table: str = "dyna_q_v1.json", episodes: int = 30,
             seed0: int = 5000, port: int = 8601, reward: str = "progress") -> dict:
    agent = DynaQ.load(MODELS / table)
    print(f"loaded {table}: {agent.summary()}\n")

    from tqdm import tqdm

    trained, baseline = [], []
    with TrainingEnv(port=port, reward=reward) as env:
        bar = tqdm(range(episodes), desc="dyna-q vs random", unit="seed")
        for i in bar:
            seed = seed0 + i
            t = play_greedy(env, agent, seed)
            b = play_random(env, seed)
            trained.append(t)
            baseline.append(b)
            wins = sum(1 for x, y in zip(trained, baseline)
                       if (x["score"] or 0) > (y["score"] or 0))
            bar.set_postfix(dyna=t["score"], random=b["score"],
                            wins=f"{wins}/{len(trained)}")

    def stats(rows, field="score"):
        vals = [r[field] for r in rows if r[field] is not None]
        return {
            "mean": round(statistics.mean(vals), 1) if vals else None,
            "median": round(statistics.median(vals), 1) if vals else None,
            "best": max(vals) if vals else None,
            "worst": min(vals) if vals else None,
        }

    wins = sum(1 for t, b in zip(trained, baseline)
               if (t["score"] or 0) > (b["score"] or 0))
    draws = sum(1 for t, b in zip(trained, baseline)
                if (t["score"] or 0) == (b["score"] or 0))

    print("\n" + "=" * 60)
    print(f"{'':<10}{'mean':>9}{'median':>9}{'worst':>8}{'best':>8}")
    ts, bs = stats(trained), stats(baseline)
    print(f"{'dyna-q':<10}{ts['mean']:>9}{ts['median']:>9}{ts['worst']:>8}{ts['best']:>8}")
    print(f"{'random':<10}{bs['mean']:>9}{bs['median']:>9}{bs['worst']:>8}{bs['best']:>8}")
    print(f"\nhead to head on the same seeds: dyna-q wins {wins}/{episodes}, "
          f"draws {draws}, losses {episodes - wins - draws}")
    return {"trained": ts, "baseline": bs, "wins": wins, "episodes": episodes}


def main() -> int:
    p = argparse.ArgumentParser(description="Compare a trained Dyna-Q agent with random.")
    p.add_argument("--table", default="dyna_q_v1.json")
    p.add_argument("--episodes", type=int, default=30)
    p.add_argument("--seed0", type=int, default=5000,
                   help="held-out seeds: keep these away from the training range")
    p.add_argument("--port", type=int, default=8601)
    p.add_argument("--reward", default="progress")
    a = p.parse_args()
    evaluate(table=a.table, episodes=a.episodes, seed0=a.seed0, port=a.port, reward=a.reward)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
