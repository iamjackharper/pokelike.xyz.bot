"""Which prompt actually plays better?

    uv run python -m experiments.llm.compare --seeds 5 --strategies survivor,explorer

Prompt engineering invites confident storytelling, so this measures instead.
Every strategy plays THE SAME SEEDS, and the comparison is paired: the question
is not "what did survivor score" but "on this identical run, did survivor do
better than explorer".

The metric is badges, because that is the game's own progression counter in Story
mode. The engine's score formula was written for the Battle Tower and two of its
terms never fire here, so ranking prompts by it would reward fighting rather than
getting further. See experiments/common/rewards.py.

A warning about what this can and cannot tell you: the model is stochastic and a
run is high variance, so a handful of seeds will not separate two decent prompts.
Treat small differences as noise and look at the per-seed table, not just the
mean.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from pathlib import Path

from pokelike.assets import AssetServer
from pokelike.bot.llm import STRATEGIES, LLMBot
from pokelike.core.game import Game

ROOT = Path(__file__).resolve().parents[2]
RUNS = Path(__file__).parent / "runs"


def play_one(game: Game, bot: LLMBot, seed: int, max_steps: int = 400) -> dict:
    obs = game.reset(seed=seed)
    bot.on_start(seed)
    while not obs.get("done") and obs.get("actions") and game.steps < max_steps:
        obs = game.step(bot.choose(obs))
    s = game.score() or {}
    alive = game.last_alive or {}
    return {
        "seed": seed,
        "badges": (alive.get("run") or {}).get("badges", 0),
        "score": s.get("points_no_time"),
        "steps": game.steps,
        "faints": (s.get("breakdown") or {}).get("faints", 0),
        "ending": obs.get("screen"),
        "calls": bot.calls,
        "tokens": bot.tokens_used,
        "fallbacks": bot.fallbacks,
    }


def compare(strategies: list[str], seeds: list[int], port: int = 8610) -> dict:
    for s in strategies:
        if s not in STRATEGIES:
            raise SystemExit(f"unknown strategy '{s}' — available: {', '.join(STRATEGIES)}")

    from tqdm import tqdm

    results: dict[str, list[dict]] = {s: [] for s in strategies}
    server = AssetServer(ROOT / "site", port=port)
    server.start()
    game = Game(url=server.url)
    game.open()
    started = time.monotonic()
    try:
        total = len(strategies) * len(seeds)
        bar = tqdm(total=total, desc="prompt comparison", unit="run")
        for strategy in strategies:
            bot = LLMBot(strategy=strategy)
            for seed in seeds:
                row = play_one(game, bot, seed)
                results[strategy].append(row)
                bar.set_postfix(strategy=strategy, seed=seed,
                                badges=row["badges"], steps=row["steps"])
                bar.update(1)
        bar.close()
    finally:
        game.close()
        server.stop()

    elapsed = time.monotonic() - started
    report(results, seeds, elapsed)

    RUNS.mkdir(parents=True, exist_ok=True)
    out = RUNS / "prompt_comparison.json"
    out.write_text(json.dumps({
        "model": os.environ.get("MODEL_ID", ""),
        "seeds": seeds,
        "elapsed_minutes": round(elapsed / 60, 1),
        "results": results,
    }, indent=1), encoding="utf-8")
    print(f"\nsaved to {out}")
    return results


def report(results: dict[str, list[dict]], seeds: list[int], elapsed: float) -> None:
    print("\n" + "=" * 74)
    print("PER SEED (badges)")
    head = f"{'seed':>8}" + "".join(f"{s[:11]:>13}" for s in results)
    print(head)
    print("-" * len(head))
    for i, seed in enumerate(seeds):
        row = f"{seed:>8}"
        for s in results:
            row += f"{results[s][i]['badges']:>13}"
        print(row)

    print("\n" + "=" * 74)
    head = (f"{'strategy':<12}{'badges~':>9}{'badges+':>9}{'score~':>9}"
            f"{'steps~':>9}{'faints~':>9}{'tokens/run':>12}{'fallbacks':>11}")
    print(head)
    print("-" * len(head))
    for s, rows in results.items():
        m = statistics.mean
        print(
            f"{s:<12}{m([r['badges'] for r in rows]):>9.2f}"
            f"{max(r['badges'] for r in rows):>9}"
            f"{m([r['score'] or 0 for r in rows]):>9.1f}"
            f"{m([r['steps'] for r in rows]):>9.1f}"
            f"{m([r['faints'] for r in rows]):>9.1f}"
            f"{m([r['tokens'] for r in rows]):>12.0f}"
            f"{sum(r['fallbacks'] for r in rows):>11}"
        )
    print(f"\n{elapsed / 60:.1f} minutes for {sum(len(r) for r in results.values())} runs")

    if len(results) == 2:
        a, b = list(results)
        diff = [x["badges"] - y["badges"] for x, y in zip(results[a], results[b])]
        wins = sum(1 for d in diff if d > 0)
        print(f"\npaired: {a} beats {b} on {wins}/{len(diff)} seeds, "
              f"mean difference {statistics.mean(diff):+.2f} badges")


def main() -> int:
    p = argparse.ArgumentParser(description="Compare LLM prompt strategies on the same seeds.")
    p.add_argument("--strategies", default=",".join(STRATEGIES),
                   help="comma separated (default: all of them)")
    p.add_argument("--seeds", type=int, default=5, help="how many seeds each strategy plays")
    p.add_argument("--seed0", type=int, default=20_000)
    p.add_argument("--port", type=int, default=8610)
    a = p.parse_args()

    compare(
        strategies=[s.strip() for s in a.strategies.split(",") if s.strip()],
        seeds=list(range(a.seed0, a.seed0 + a.seeds)),
        port=a.port,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
