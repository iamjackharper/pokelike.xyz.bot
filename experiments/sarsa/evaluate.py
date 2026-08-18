"""Does the learned policy beat random, on runs it has never seen?

    uv run python -m experiments.sarsa.evaluate --episodes 25

Both policies play THE SAME held-out seeds, and the comparison is paired: the
question is not "what did SARSA average" but "on this identical run, did it do
better". Runs vary enormously by luck, so unpaired means are mostly a measure of
who drew the nicer maps.

Judged on BADGES. The engine's score formula was written for the Battle Tower
and two of its terms never fire in Story mode, leaving 5*KO - 10*faints, which
rewards fighting rather than getting further. Badges are the game's own
progression counter. Score is reported anyway, because a policy that scores
badly while earning badges is telling you something about how it earns them.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
from pathlib import Path

from pokelike.assets import AssetServer
from pokelike.core.game import Game

from .agent import SarsaLambda

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).parent
OUT = HERE / "output"
MODELS = OUT / "models"
RUNS = OUT / "runs"


def _available(models: Path) -> str:
    """What is actually on disk, for when the requested table is not.

    Weights are gitignored, so on a fresh clone this directory is empty and the
    honest answer is "train something first" rather than a bare traceback about
    a path.
    """
    found = sorted(p.name for p in models.glob("*.json")) if models.is_dir() else []
    return ("on disk: " + ", ".join(found)) if found else "nothing trained yet"



def _outcome(game: Game, obs: dict, seed: int) -> dict:
    alive = game.last_alive or {}
    score = game.score() or {}
    b = score.get("breakdown") or {}
    return {
        "seed": seed,
        "badges": (alive.get("run") or {}).get("badges", 0),
        "steps": game.steps,
        "score": score.get("points_no_time"),
        "faints": b.get("faints", 0),
        "kos": b.get("enemiesKO", 0),
        "ending": obs.get("screen"),
    }


def play(game: Game, seed: int, pick, max_steps: int = 300) -> dict:
    obs = game.reset(seed=seed)
    while not obs.get("done") and obs.get("actions") and game.steps < max_steps:
        obs = game.step(pick(obs))
    return _outcome(game, obs, seed)


def evaluate(table: str = "sarsa.json", episodes: int = 25,
             seed0: int = 40_000, port: int = 8800) -> dict:
    from tqdm import tqdm

    path = MODELS / table
    if not path.is_file():
        raise SystemExit(
            f"no weights at {path}\n{_available(MODELS)}\n\n"
            f"train some first:  uv run python -m experiments.sarsa.train"
        )
    agent = SarsaLambda.load(path)
    print(f"loaded {table}: {agent.summary()}")
    print("\nwhat it learned to care about:")
    for name, w in agent.top_weights(12):
        print(f"  {name:<26} {w:>8}")
    print()

    seeds = list(range(seed0, seed0 + episodes))
    learned, baseline = [], []
    server = AssetServer(ROOT / "site", port=port)
    server.start()
    game = Game(url=server.url)
    game.open()
    try:
        bar = tqdm(seeds, desc="sarsa vs random", unit="seed")
        for seed in bar:
            a = play(game, seed, lambda o: agent.choose(o, greedy=True))
            rng = random.Random(seed)
            b = play(game, seed, lambda o: rng.randrange(len(o["actions"])))
            learned.append(a)
            baseline.append(b)
            wins = sum(1 for x, y in zip(learned, baseline) if x["badges"] > y["badges"])
            bar.set_postfix(sarsa=a["badges"], random=b["badges"],
                            wins=f"{wins}/{len(learned)}")
    finally:
        game.close()
        server.stop()

    report(learned, baseline)
    RUNS.mkdir(parents=True, exist_ok=True)
    out = RUNS / "evaluation.json"
    out.write_text(json.dumps({"seeds": seeds, "sarsa": learned, "random": baseline},
                              indent=1), encoding="utf-8")
    print(f"\nsaved to {out}")
    return {"sarsa": learned, "random": baseline}


def report(learned: list[dict], baseline: list[dict]) -> None:
    m = statistics.mean

    def row(name, rows):
        return (f"{name:<10}{m(r['badges'] for r in rows):>9.2f}"
                f"{max(r['badges'] for r in rows):>9}"
                f"{m(r['steps'] for r in rows):>9.1f}"
                f"{m(r['faints'] for r in rows):>9.1f}"
                f"{m(r['score'] or 0 for r in rows):>9.1f}")

    print("\n" + "=" * 60)
    head = f"{'':<10}{'badges~':>9}{'badges+':>9}{'steps~':>9}{'faints~':>9}{'score~':>9}"
    print(head)
    print("-" * len(head))
    print(row("sarsa", learned))
    print(row("random", baseline))

    diff = [a["badges"] - b["badges"] for a, b in zip(learned, baseline)]
    wins = sum(1 for d in diff if d > 0)
    draws = sum(1 for d in diff if d == 0)
    mean_d = m(diff)
    print(f"\npaired on the same seeds: sarsa wins {wins}, draws {draws}, "
          f"loses {len(diff) - wins - draws}")
    print(f"mean difference: {mean_d:+.2f} badges per run")
    if len(diff) > 1 and statistics.stdev(diff) > 0:
        t = mean_d / (statistics.stdev(diff) / len(diff) ** 0.5)
        print(f"t = {t:.2f}   " + ("(significant)" if abs(t) > 2 else "(not significant)"))


def main() -> int:
    p = argparse.ArgumentParser(description="Compare a trained SARSA policy with random.")
    # Defaults to what `train` writes, so the two commands chain. The
    # leaderboard's own weights are sarsa_v1.json; train deliberately does not
    # write to that name, or a training run would overwrite a submitted policy.
    p.add_argument("--table", default="sarsa.json",
                   help="file in output/models/ (default: what train writes)")
    p.add_argument("--episodes", type=int, default=25)
    p.add_argument("--seed0", type=int, default=40_000,
                   help="held out: keep away from the training range")
    p.add_argument("--port", type=int, default=8800)
    a = p.parse_args()
    evaluate(table=a.table, episodes=a.episodes, seed0=a.seed0, port=a.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
