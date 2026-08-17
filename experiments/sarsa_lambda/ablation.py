"""Train every variant at once, then judge them on the same held-out seeds.

    uv run python -m experiments.sarsa_lambda.ablation --episodes 300 --workers 4
    uv run python -m experiments.sarsa_lambda.ablation --list

Each variant is a separate PROCESS with its own port and its own browser. Not
threads: Playwright's sync API is bound to the thread that created it, so two
games in one thread is not slow, it is broken.

The parallelism is between runs and never inside one. SARSA is on-policy with
eligibility traces: splitting episode collection across several environments
would make the updates come from a behaviour distribution the traces do not
describe, which is a different algorithm wearing the same name. Whole
independent runs sidestep that, and comparing variants is exactly the case where
that is all you need.
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

from .agent import SarsaLambda
from .features import BY_NAME, VARIANTS, describe

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).parent
RESULTS = HERE / "output" / "ablation"
MODELS = HERE / "output" / "models"

# Ports are handed out per worker. Well clear of the defaults so an ablation
# never collides with a game someone is playing in another terminal.
PORT0 = 8900


def _train_cmd(v, episodes: int, reward: str, port: int, seed0: int) -> list[str]:
    cmd = [
        sys.executable, "-m", "experiments.sarsa_lambda.train",
        "--episodes", str(episodes), "--reward", reward, "--seed0", str(seed0),
        "--port", str(port), "--out", f"ablation_{v.name}.json", "--quiet",
    ]
    if v.groups is not None:
        cmd += ["--groups", ",".join(v.groups)]
    return cmd


def train_all(variants, episodes: int, reward: str, workers: int, seed0: int) -> dict:
    """Runs the training processes, at most `workers` at a time."""
    queue = list(variants)
    running: list[tuple] = []
    done: dict[str, int] = {}
    logs = RESULTS / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()

    print(f"training {len(queue)} variants, {workers} at a time, "
          f"{episodes} episodes each\n")
    slot_of: dict[str, int] = {}
    free = list(range(workers))

    while queue or running:
        while queue and free:
            v = queue.pop(0)
            slot = free.pop(0)
            slot_of[v.name] = slot
            log = (logs / f"{v.name}.log").open("w", encoding="utf-8")
            p = subprocess.Popen(
                _train_cmd(v, episodes, reward, PORT0 + slot, seed0),
                cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
            )
            running.append((v, p, log))
            print(f"  started {v.name:<16} ({v.n} features) on port {PORT0 + slot}")

        time.sleep(5)
        for entry in list(running):
            v, p, log = entry
            if p.poll() is None:
                continue
            running.remove(entry)
            log.close()
            free.append(slot_of[v.name])
            done[v.name] = p.returncode
            mins = (time.monotonic() - started) / 60
            status = "ok" if p.returncode == 0 else f"FAILED ({p.returncode})"
            print(f"  {v.name:<16} {status}   [{mins:.0f} min elapsed]")

    return done


def evaluate_all(variants, episodes: int, seed0: int, workers: int) -> dict:
    """Greedy evaluation of every trained variant, plus random, on the same seeds."""
    from pokelike.assets import AssetServer
    from pokelike.core.game import Game

    seeds = list(range(seed0, seed0 + episodes))
    server = AssetServer(ROOT / "site", port=PORT0 + workers + 1)
    server.start()
    game = Game(url=server.url)
    game.open()
    out: dict[str, list[dict]] = {}
    try:
        import random as _random

        from tqdm import tqdm

        policies: list[tuple[str, object]] = []
        for v in variants:
            path = MODELS / f"ablation_{v.name}.json"
            if not path.is_file():
                print(f"  {v.name}: no weights, skipped")
                continue
            policies.append((v.name, SarsaLambda.load(path)))

        for name, agent in policies:
            rows = []
            for seed in tqdm(seeds, desc=f"eval {name}", unit="seed", leave=False):
                rows.append(_play(game, seed, lambda o: agent.choose(o, greedy=True)))
            out[name] = rows

        rows = []
        for seed in tqdm(seeds, desc="eval random", unit="seed", leave=False):
            rng = _random.Random(seed)
            rows.append(_play(game, seed, lambda o: rng.randrange(len(o["actions"]))))
        out["random"] = rows
    finally:
        game.close()
        server.stop()
    return out


def _play(game, seed: int, pick, max_steps: int = 300) -> dict:
    obs = game.reset(seed=seed)
    while not obs.get("done") and obs.get("actions") and game.steps < max_steps:
        obs = game.step(pick(obs))
    alive = game.last_alive or {}
    score = game.score() or {}
    return {
        "seed": seed,
        "badges": (alive.get("run") or {}).get("badges", 0),
        "steps": game.steps,
        "score": score.get("points_no_time") or 0,
    }


def report(results: dict, variants) -> str:
    m = statistics.mean
    base = results.get("random") or []
    lines = ["", "=" * 74,
             f"{'variant':<16}{'feats':>7}{'badges~':>10}{'badges+':>9}"
             f"{'score~':>9}{'vs random':>12}{'t':>8}",
             "-" * 74]

    order = sorted(results, key=lambda k: -m(r["badges"] for r in results[k]))
    n_of = {v.name: v.n for v in variants}
    for name in order:
        rows = results[name]
        cell, t_cell = "", ""
        if base and name != "random":
            diff = [a["badges"] - b["badges"] for a, b in zip(rows, base)]
            wins = sum(1 for d in diff if d > 0)
            losses = sum(1 for d in diff if d < 0)
            cell = f"{wins}W-{len(diff) - wins - losses}D-{losses}L"
            if len(diff) > 1 and statistics.stdev(diff) > 0:
                t_cell = f"{m(diff) / (statistics.stdev(diff) / len(diff) ** 0.5):.2f}"
        lines.append(
            f"{name:<16}{n_of.get(name, ''):>7}{m(r['badges'] for r in rows):>10.2f}"
            f"{max(r['badges'] for r in rows):>9}{m(r['score'] for r in rows):>9.1f}"
            f"{cell:>12}{t_cell:>8}"
        )
    lines += ["-" * 74, "paired on identical seeds; t over 2 is worth believing", ""]
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(description="Compare feature sets, trained in parallel.")
    p.add_argument("--episodes", type=int, default=300, help="training episodes each")
    p.add_argument("--eval-episodes", type=int, default=25)
    p.add_argument("--workers", type=int, default=4,
                   help="training processes at once; each is a python + a chromium")
    p.add_argument("--reward", default="progress")
    p.add_argument("--seed0", type=int, default=1, help="first TRAINING seed")
    p.add_argument("--eval-seed0", type=int, default=40_000,
                   help="first evaluation seed: keep it clear of the training range")
    p.add_argument("--only", default=None, help="comma separated variant names")
    p.add_argument("--list", action="store_true", help="show the variants and stop")
    p.add_argument("--skip-training", action="store_true",
                   help="evaluate weights that are already on disk")
    a = p.parse_args()

    if a.list:
        print(describe())
        return 0

    variants = VARIANTS
    if a.only:
        try:
            variants = [BY_NAME[n.strip()] for n in a.only.split(",")]
        except KeyError as e:
            print(f"unknown variant {e}; have: {', '.join(BY_NAME)}", file=sys.stderr)
            return 2

    if a.eval_seed0 < a.seed0 + a.episodes:
        print("evaluation seeds overlap the training range: the comparison would "
              "reward memorising, not learning.", file=sys.stderr)
        return 2

    RESULTS.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()

    if not a.skip_training:
        codes = train_all(variants, a.episodes, a.reward, a.workers, a.seed0)
        failed = [n for n, c in codes.items() if c != 0]
        if failed:
            print(f"\ntraining failed for: {', '.join(failed)} "
                  f"(see {RESULTS / 'logs'})", file=sys.stderr)
            variants = [v for v in variants if v.name not in failed]
        if not variants:
            return 1

    print("\nevaluating on held-out seeds")
    results = evaluate_all(variants, a.eval_episodes, a.eval_seed0, a.workers)
    text = report(results, variants)
    print(text)
    print(f"total {(time.monotonic() - started) / 60:.0f} min")

    out = RESULTS / "ablation.json"
    out.write_text(json.dumps({
        "episodes": a.episodes, "eval_episodes": a.eval_episodes,
        "eval_seed0": a.eval_seed0, "reward": a.reward,
        "variants": {v.name: {"groups": v.groups, "n": v.n,
                              "question": v.question, "expect": v.expect}
                     for v in variants},
        "results": results,
    }, indent=1), encoding="utf-8")
    print(f"saved to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
