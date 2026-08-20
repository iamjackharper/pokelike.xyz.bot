"""Parallel model benchmark for a bot folder.

This is deliberately separate from the submission leaderboard.  The bot and its
prompt stay fixed while one or more model ids vary.  Each worker owns a browser
and an asset server because Playwright's synchronous API cannot be shared.
"""

from __future__ import annotations

import hashlib
import json
import multiprocessing as mp
import statistics
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from datetime import datetime, timezone
from queue import Empty, Full
from pathlib import Path
from typing import Any, Callable

from .bench import STANDARD_SEEDS

ROOT = Path(__file__).resolve().parents[2]
BOTS = ROOT / "bots"
OUT = ROOT / "llm-bench" / "cartographer"
_STATUS_QUEUE = None


def _init_status_queue(status_queue) -> None:
    """Give each spawned worker direct access to the native status queue."""
    global _STATUS_QUEUE
    _STATUS_QUEUE = status_queue


def _report_status(status: dict[str, Any]) -> None:
    """Best-effort heartbeat; benchmark results never depend on this queue."""
    if _STATUS_QUEUE is None:
        return
    try:
        _STATUS_QUEUE.put_nowait(status)
    except Full:
        pass


def slug(model: str) -> str:
    return model.replace("/", "--").replace(":", "-").replace(" ", "-")


def bot_path(name: str) -> Path:
    path = Path(name)
    if "/" not in name and "\\" not in name:
        path = BOTS / name
    path = path if path.name == "bot.py" else path / "bot.py"
    if not path.is_file():
        raise FileNotFoundError(f"no bot.py at {path}")
    return path


def fingerprint(name: str) -> dict[str, str]:
    paths = [bot_path(name), ROOT / "src/pokelike/bot/llm.py",
             ROOT / "src/pokelike/core/render.py", ROOT / "src/pokelike/core/bridge.js"]
    h = hashlib.sha256()
    for path in paths:
        h.update(str(path.relative_to(ROOT)).encode())
        h.update(path.read_bytes())
    return {"sha256": h.hexdigest()[:16], "files": ",".join(str(p.relative_to(ROOT)) for p in paths)}


def _worker(bot_name: str, model: str, seed: int, endpoint: str | None,
            token: str | None, port: int, site: str, max_steps: int) -> list[dict[str, Any]]:
    from .assets.server import AssetServer
    from .bot.catalogue import load_class
    from .core.game import Game
    from .runner import play_run

    cls = load_class(bot_path(bot_name))
    bot = cls(seed=0, model=model, endpoint=endpoint, token=token)
    server = AssetServer(Path(site), port=port)
    server.start()
    game = Game(url=server.url)
    game.open()
    rows: list[dict[str, Any]] = []
    try:
        _report_status({"seed": seed, "kind": "started"})

        def heartbeat(obs, steps):
            run = obs.get("run") or {}
            _report_status({
                "seed": seed,
                "kind": "step",
                "map": run.get("map"),
                "step": steps,
            })

        full = play_run(game, bot, seed, max_steps=max_steps, on_step=heartbeat)
        notes = bot.notes()
        rows.append({
            "seed": seed,
            "steps": full["steps"],
            "score": full["score"],
            "badges": full["badges"],
            "maps": full["maps"],
            "kos": full["kos"],
            "faints": full["faints"],
            "ending": full["ending"],
            "stalled": full["stalled"],
            "tokens_in": notes.get("tokens_in", 0),
            "tokens_out": notes.get("tokens_out", 0),
            "cached_tokens": notes.get("cached_tokens", 0),
            "cache_write_tokens": notes.get("cache_write_tokens", 0),
            "reasoning_tokens": notes.get("reasoning_tokens", 0),
            "cost": notes.get("cost"),
            "fallbacks": notes.get("fallbacks", 0),
            "turns": notes.get("turns", 0),
            "calls": notes.get("calls", 0),
        })
    finally:
        game.close()
        server.stop()
    return rows


def summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    badges = [r.get("badges") or 0 for r in rows]
    costs = [r["cost"] for r in rows if isinstance(r.get("cost"), (int, float))]
    turns = sum(r.get("turns") or 0 for r in rows)
    fallbacks = sum(r.get("fallbacks") or 0 for r in rows)
    return {
        "runs": len(rows),
        "badges_mean": round(statistics.mean(badges), 3) if badges else 0,
        "badges_sem": round(statistics.stdev(badges) / len(badges) ** 0.5, 3)
        if len(badges) > 1 else 0,
        "badges_best": max(badges) if badges else 0,
        "completed": sum(r.get("ending") == "win-screen" for r in rows),
        "tokens_in": sum(r.get("tokens_in") or 0 for r in rows),
        "tokens_out": sum(r.get("tokens_out") or 0 for r in rows),
        "cached_tokens": sum(r.get("cached_tokens") or 0 for r in rows),
        "cache_write_tokens": sum(r.get("cache_write_tokens") or 0 for r in rows),
        "reasoning_tokens": sum(r.get("reasoning_tokens") or 0 for r in rows),
        "cost": round(sum(costs), 8) if rows and len(costs) == len(rows) else None,
        "cost_mean": round(statistics.mean(costs), 8)
        if rows and len(costs) == len(rows) else None,
        "cost_observed_runs": len(costs),
        "fallback_rate": round(fallbacks / turns, 3) if turns else 0,
    }


def run_model(bot_name: str, model: str, seeds: list[int], workers: int,
              endpoint: str | None, token: str | None, site: Path,
              port: int, max_steps: int = 400,
              on_progress: Callable[[list[dict[str, Any]]], None] | None = None,
              on_status: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
    workers = max(1, min(workers, len(seeds)))
    rows: list[dict[str, Any]] = []
    context = mp.get_context("spawn")
    # Heartbeats are best-effort diagnostics. This is a native multiprocessing
    # queue inherited when workers spawn, not a Manager proxy in the main loop.
    status_queue = context.Queue(maxsize=max(8, workers * 4))
    try:
        with ProcessPoolExecutor(
            max_workers=workers,
            mp_context=context,
            initializer=_init_status_queue,
            initargs=(status_queue,),
        ) as pool:
            futures = [pool.submit(_worker, bot_name, model, seed, endpoint, token,
                                   port + i, str(site), max_steps)
                       for i, seed in enumerate(seeds)]
            pending = set(futures)
            while pending:
                done, pending = wait(pending, timeout=0.25,
                                     return_when=FIRST_COMPLETED)
                # Drain only a bounded number of diagnostic events per pass.
                # With an unbounded `while`, workers could refill the queue as
                # quickly as it was drained, so completed runs were never
                # processed even though the pool had already started new ones.
                for _ in range(max(8, workers * 4)):
                    try:
                        if on_status:
                            on_status(status_queue.get_nowait())
                        else:
                            status_queue.get_nowait()
                    except Empty:
                        break
                for future in done:
                    result_rows = future.result()
                    rows.extend(result_rows)
                    if on_status:
                        for row in result_rows:
                            on_status({"kind": "finished", "seed": row["seed"]})
                    if on_progress:
                        on_progress(rows)
    finally:
        status_queue.close()
    rows.sort(key=lambda r: r["seed"])
    return {
        "model": model,
        "bot": bot_name,
        "harness": "cartographer-v1",
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fingerprint": fingerprint(bot_name),
        "seeds": seeds,
        "summary": summary(rows),
        "runs": rows,
    }


def save(result: dict[str, Any]) -> Path:
    path = OUT / "results" / f"{slug(result['model'])}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return path
