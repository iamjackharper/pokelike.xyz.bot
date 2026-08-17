"""The standard benchmark, so different bots can be compared honestly.

Two things make a result comparable, and both are easy to get wrong:

**The same runs.** Luck dominates a single game. The benchmark uses a fixed seed
list, so every bot faces the identical set of maps, starters and encounters.
Comparing bots on different seeds mostly measures who drew the nicer maps.

**The same game.** The upstream game gets updated, and its filename carries a
content hash. A score from before an update is not comparable with one from
after, so the result file records the hash of the exact bundle that was played.
Without it a leaderboard silently mixes different games.

Results are self-reported: nobody can run everyone else's bot, least of all one
that needs an API key. What makes that acceptable is that a self-contained bot
can be re-run by anyone with a single command, and the result file says exactly
which game and which seeds to reproduce.
"""

from __future__ import annotations

import hashlib
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# The official seed list. Fifty runs is enough to see past the luck without
# taking all afternoon, and it is held well away from the seeds used elsewhere
# in the project so nobody trains on the benchmark by accident.
STANDARD_SEEDS = list(range(10_000, 10_050))

CATEGORIES = ("rules", "rl", "llm", "human", "other")


def bundle_fingerprint(site: Path) -> dict[str, str]:
    """Identifies the exact version of the game that was played."""
    bundle = next(Path(site).glob("js/bundle*.js"), None)
    if bundle is None:
        return {"file": "unknown", "sha256": "unknown"}
    return {
        "file": bundle.name,
        "sha256": hashlib.sha256(bundle.read_bytes()).hexdigest()[:16],
    }


def summarise(runs: list[dict[str, Any]]) -> dict[str, Any]:
    scores = [r["score"] for r in runs if r.get("score") is not None]
    if not scores:
        return {"runs": len(runs)}
    return {
        "runs": len(runs),
        "score_mean": round(statistics.mean(scores), 1),
        "score_median": round(statistics.median(scores), 1),
        "score_best": max(scores),
        "score_worst": min(scores),
        "score_stdev": round(statistics.stdev(scores), 1) if len(scores) > 1 else 0.0,
        "badges_mean": round(statistics.mean([r.get("badges") or 0 for r in runs]), 2),
        "badges_best": max((r.get("badges") or 0) for r in runs),
        "maps_mean": round(statistics.mean([r.get("maps") or 0 for r in runs]), 2),
        "completed": sum(1 for r in runs if r.get("ending") == "win-screen"),
        "steps_mean": round(statistics.mean([r["steps"] for r in runs]), 1),
    }


def run_benchmark(
    game,
    bot,
    bot_name: str,
    site: Path,
    seeds: list[int] | None = None,
    author: str = "",
    category: str = "other",
    description: str = "",
    max_steps: int = 400,
    on_run=None,
) -> dict[str, Any]:
    """Plays the seed list and returns the result document."""
    from . import __version__

    seeds = seeds or STANDARD_SEEDS
    runs: list[dict[str, Any]] = []

    from tqdm import tqdm

    bar = tqdm(seeds, desc=f"bench {bot_name}", unit="run", leave=True)
    for seed in bar:
        obs = game.reset(seed=seed)
        bot.on_start(seed)
        while not obs.get("done") and obs.get("actions") and game.steps < max_steps:
            obs = game.step(bot.choose(obs))
        s = game.score() or {}
        bot.on_end(obs, s)

        b = s.get("breakdown") or {}
        row = {
            "seed": seed,
            "steps": game.steps,
            "score": s.get("points_no_time"),
            "badges": ((game.last_alive or {}).get("run") or {}).get("badges", 0),
            "maps": b.get("mapsCleared", 0),
            "kos": b.get("enemiesKO", 0),
            "faints": b.get("faints", 0),
            "ending": obs.get("screen"),
        }
        runs.append(row)
        done = [r["score"] for r in runs if r["score"] is not None]
        bar.set_postfix(score=row["score"],
                        mean=round(sum(done) / len(done), 1) if done else None)
        if on_run:
            on_run(row, len(runs), len(seeds))

    return {
        "bot": bot_name,
        "author": author,
        "category": category,
        "description": description,
        "submitted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "pokelike_version": __version__,
        "game": bundle_fingerprint(site),
        "seeds": seeds,
        "summary": summarise(runs),
        "runs": runs,
        "notes": getattr(bot, "notes", lambda: {})(),
    }


def save(result: dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=1), encoding="utf-8")
    return path


def format_result(result: dict[str, Any]) -> str:
    s = result["summary"]
    g = result["game"]
    return "\n".join([
        "",
        "=" * 60,
        f"  {result['bot']}   [{result['category']}]",
        "=" * 60,
        f"  runs            {s.get('runs')}",
        f"  score mean      {s.get('score_mean')}   (stdev {s.get('score_stdev')})",
        f"  score median    {s.get('score_median')}",
        f"  score range     {s.get('score_worst')} .. {s.get('score_best')}",
        f"  badges mean     {s.get('badges_mean')}   best {s.get('badges_best')}",
        f"  maps mean       {s.get('maps_mean')}",
        f"  runs completed  {s.get('completed')}",
        f"  steps mean      {s.get('steps_mean')}",
        "",
        f"  game bundle     {g['file']}  (sha256 {g['sha256']})",
    ])
