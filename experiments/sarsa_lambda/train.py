"""Training loop for semi-gradient SARSA(λ).

    uv run python -m experiments.sarsa_lambda.train --episodes 300

Unlike the tabular experiment this drives `Game` directly and works on action
INDICES, not on action keys. That is not a detail: keying by type collapses the
five EQUIP buttons of the equip modal into one action, so a tabular agent cannot
choose *who* to give an item to. Indices keep them apart, and the features
describe each one.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

from experiments.env.rewards import get as get_reward
from pokelike.assets import AssetServer
from pokelike.core.game import Game

from .agent import SarsaLambda
from .features import FeatureSet

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).parent
OUT = HERE / "output"
MODELS = OUT / "models"
RUNS = OUT / "runs"


def train(
    episodes: int = 300,
    seed0: int = 1,
    reward: str = "progress",
    alpha: float = 0.05,
    gamma: float = 0.98,
    lam: float = 0.9,
    epsilon: float = 0.3,
    max_steps: int = 300,
    port: int = 8710,
    out: str = "sarsa.json",
    groups: list[str] | None = None,
    quiet: bool = False,
) -> dict:
    from tqdm import tqdm

    reward_fn = get_reward(reward)
    fs = FeatureSet(groups)
    agent = SarsaLambda(alpha=alpha, gamma=gamma, lam=lam, epsilon=epsilon, seed=seed0,
                        featureset=fs)
    history: list[dict] = []
    started = time.monotonic()

    server = AssetServer(ROOT / "site", port=port)
    server.start()
    game = Game(url=server.url)
    game.open()
    try:
        bar = tqdm(range(episodes), desc=(out.replace(".json", "") or "sarsa(λ)"),
                   unit="ep", disable=quiet)
        for ep in bar:
            seed = seed0 + ep
            obs = game.reset(seed=seed)
            agent.start_episode()

            action = agent.choose(obs)
            x = fs.of(obs, obs["actions"][action])
            total = 0.0

            while True:
                before = obs
                obs = game.step(action)
                done = bool(obs.get("done")) or game.steps >= max_steps or not obs.get("actions")

                # At game over the engine wipes `state`, so reward against the
                # last live snapshot or every run ends with a phantom collapse.
                after = obs if obs.get("run") else (game.last_alive or before)
                r = reward_fn(before, after, done, obs.get("screen") == "win-screen")
                total += r

                if done:
                    agent.update(x, r, None)
                    break

                action = agent.choose(obs)
                x_next = fs.of(obs, obs["actions"][action])
                agent.update(x, r, x_next)
                x = x_next

            agent.end_episode()
            alive = game.last_alive or {}
            score = game.score() or {}
            history.append({
                "episode": ep,
                "seed": seed,
                "steps": game.steps,
                "reward": round(total, 1),
                "badges": (alive.get("run") or {}).get("badges", 0),
                "score": score.get("points_no_time"),
                "ending": obs.get("screen"),
                "epsilon": round(agent.epsilon, 4),
            })
            w = history[-25:]
            bar.set_postfix(
                badges=round(statistics.mean(h["badges"] for h in w), 2),
                reward=round(statistics.mean(h["reward"] for h in w), 1),
                eps=round(agent.epsilon, 3),
            )
    finally:
        game.close()
        server.stop()

    elapsed = (time.monotonic() - started) / 60
    table = agent.save(MODELS / out)
    RUNS.mkdir(parents=True, exist_ok=True)
    log = RUNS / (Path(out).stem + "_history.json")
    log.write_text(json.dumps(history, indent=1), encoding="utf-8")

    print(f"\ntrained {episodes} episodes with reward '{reward}' in {elapsed:.1f} min")
    print(f"agent: {agent.summary()}")
    print("\nwhat it leaned on:")
    for name, weight in agent.top_weights(14):
        print(f"  {name:<26} {weight:>8}")
    print(f"\nweights: {table}\nhistory: {log}")
    return {"agent": agent.summary(), "history": history}


def main() -> int:
    p = argparse.ArgumentParser(description="Train linear SARSA(lambda) on pokelike.")
    p.add_argument("--episodes", type=int, default=300)
    p.add_argument("--seed0", type=int, default=1)
    p.add_argument("--reward", default="progress")
    p.add_argument("--alpha", type=float, default=0.05)
    p.add_argument("--gamma", type=float, default=0.98)
    p.add_argument("--lam", type=float, default=0.9, help="trace decay")
    p.add_argument("--epsilon", type=float, default=0.3)
    p.add_argument("--port", type=int, default=8710)
    p.add_argument("--out", default="sarsa.json")
    p.add_argument("--groups", default=None,
                   help="feature groups to keep, comma separated (default: all). "
                        "See features.GROUPS — this is what an ablation varies.")
    p.add_argument("--quiet", action="store_true", help="no progress bar (parallel runs)")
    a = p.parse_args()
    train(episodes=a.episodes, seed0=a.seed0, reward=a.reward, alpha=a.alpha,
          gamma=a.gamma, lam=a.lam, epsilon=a.epsilon, port=a.port, out=a.out,
          groups=a.groups.split(",") if a.groups else None, quiet=a.quiet)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
