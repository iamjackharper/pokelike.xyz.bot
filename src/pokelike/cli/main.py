"""Command-line interface.

A thin face over `core.game.Game`, the same class the API uses. No game logic
lives here.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..assets.mirror import PHASES, build
from ..assets.server import AssetServer
from ..core import render
from ..core.game import Game, IllegalAction
from ..stats import format_summary, record, recent, summary

SITE_ROOT = Path(__file__).resolve().parents[3] / "site"

REPL_HELP = """
commands:
  <number>   take the action with that number
  s          show the score
  j          show the raw state as JSON
  l          show the legend of map symbols
  n          new run
  q          quit
"""


def _server_and_game(args) -> tuple[AssetServer, Game]:
    if not SITE_ROOT.is_dir() or not (SITE_ROOT / "index.html").is_file():
        print(
            f"offline copy missing in {SITE_ROOT}\n"
            "run it once with:  pokelike setup",
            file=sys.stderr,
        )
        raise SystemExit(2)
    server = AssetServer(SITE_ROOT, port=args.port)
    server.start()

    watch = getattr(args, "watch", False)
    # With a window open the animations should run at their own speed, otherwise
    # everything flashes past unseen. Headless squashes them to 1 ms because
    # nobody is watching.
    game = Game(url=server.url, watch=watch, max_delay=100_000 if watch else 1)
    try:
        game.open()
    except Exception as e:  # noqa: BLE001
        server.stop()
        if watch:
            print(
                f"cannot open the window: {e}\n\n"
                "--watch needs the full browser, not just the headless shell:\n"
                "    uv run playwright install chromium",
                file=sys.stderr,
            )
            raise SystemExit(3) from e
        raise
    return server, game


# -------------------------------------------------------------------- commands


def cmd_setup(args) -> int:
    """Gets everything ready: browser + offline copy. Run once."""
    import subprocess

    print("[1/2] downloading the headless browser (~120 MB)")
    r = subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium", "--only-shell"]
    )
    if r.returncode != 0:
        print("browser installation failed", file=sys.stderr)
        return r.returncode

    if (SITE_ROOT / "index.html").is_file() and not args.force:
        print(f"[2/2] offline copy already in {SITE_ROOT} — skipping")
        print("      (use --force to rebuild it)")
    else:
        print("[2/2] downloading the game for offline use (~130 MB, a few minutes)")
        build(SITE_ROOT)

    print("\nReady. Try:  pokelike play")
    return 0


def cmd_mirror(args) -> int:
    build(SITE_ROOT, phases=args.phase)
    return 0


def cmd_play(args) -> int:
    server, game = _server_and_game(args)
    try:
        obs = game.reset(seed=args.seed)
        print(f"\nnew run — seed {args.seed}")
        if args.shots:
            print(f"images in {args.shots}/")
        print(REPL_HELP)
        while True:
            print()
            print(render.screen(obs))
            if args.shots:
                f = game.screenshot(Path(args.shots) / f"{game.steps:03d}-{obs['screen']}.png")
                print(f"\n[image: {f}]")
            if obs.get("done"):
                print()
                print(render.score_view(game.score()))
                print("\n('n' for another run, 'q' to quit)")

            try:
                line = input("\n> ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print()
                return 0

            if line in {"q", "quit", "exit"}:
                return 0
            if line == "n":
                args.seed += 1
                obs = game.reset(seed=args.seed)
                print(f"\nnew run — seed {args.seed}")
                continue
            if line == "s":
                print()
                print(render.score_view(game.score()))
                continue
            if line == "j":
                print(json.dumps(game.state(), indent=1, ensure_ascii=False))
                continue
            if line == "l":
                print()
                print(render.LEGEND)
                continue
            if line in {"?", "h", "help"}:
                print(REPL_HELP)
                continue
            if not line.isdigit():
                print("did not understand — type a number, or '?' for help")
                continue

            try:
                obs = game.step(int(line))
            except IllegalAction as e:
                print(f"action refused: {e}")
    finally:
        game.close()
        server.stop()


def cmd_bot(args) -> int:
    """Runs a bot. The bot decides the moves; this only drives the loop."""
    from ..bot import create

    try:
        bot = create(args.bot, seed=args.seed)
    except KeyError as e:
        print(e.args[0], file=sys.stderr)
        raise SystemExit(2) from e

    server, game = _server_and_game(args)
    try:
        for i in range(args.runs):
            seed = args.seed + i
            obs = game.reset(seed=seed)
            bot.on_start(seed)
            while not obs.get("done") and obs.get("actions") and game.steps < args.max_steps:
                if args.shots:
                    game.screenshot(
                        Path(args.shots) / f"{i:02d}-{game.steps:03d}-{obs['screen']}.png"
                    )
                obs = game.step(bot.choose(obs))
                if args.watch:
                    game.session.page.wait_for_timeout(args.pause)
            s = game.score() or {}
            bot.on_end(obs, s)
            if not args.no_stats:
                record(bot=args.bot, seed=seed, state=obs, score=s, steps=game.steps,
                       alive=game.last_alive,
                       extra=bot.notes() if hasattr(bot, "notes") else None)
            b = s.get("breakdown") or {}
            badges = ((game.last_alive or {}).get("run") or {}).get("badges", 0)
            # We print `points_no_time` because it is the only comparable one:
            # the time bonus is worth ~1000 on a scale where everything else is
            # in the tens, so `points` makes a disastrous run look fine.
            print(
                f"run {i + 1}/{args.runs}  seed {seed}  "
                f"steps {game.steps:>3}  end {obs.get('screen'):<16} "
                f"badges {badges}  score {s.get('points_no_time')}  "
                f"(KO {b.get('enemiesKO', 0)}, faints {b.get('faints', 0)}, "
                f"maps {b.get('mapsCleared', 0)})"
            )
        return 0
    finally:
        game.close()
        server.stop()


def cmd_stats(args) -> int:
    print(format_summary(summary(), explain=args.explain))
    if args.recent:
        print()
        for r in recent(args.recent, bot=args.bot):
            print(f"  #{r['id']:<5} {r['played_at']}  {r['bot']:<10} seed {r['seed']:<5}"
                  f" steps {r['steps']:>3}  {r['ending']:<16} score {r['points']}")
    return 0


def cmd_api(args) -> int:
    from ..api.server import serve

    server, game = _server_and_game(args)
    try:
        # A run is ready as soon as the server starts, so GET /state answers
        # right away without having to POST /new first.
        game.reset(seed=args.seed)
        print(f"API on http://127.0.0.1:{args.api_port}/   (ctrl-c to stop)")
        print(f"run ready with seed {args.seed} — try: curl 127.0.0.1:{args.api_port}/state")
        serve(game, port=args.api_port)
        return 0
    finally:
        game.close()
        server.stop()


# ------------------------------------------------------------------ arguments


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="pokelike",
        description="Play pokelike.xyz headless, from the command line or over HTTP.",
    )
    p.add_argument("--port", type=int, default=8422, help="port of the game-file server")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("setup", help="get everything ready: browser + offline copy (run once)")
    s.add_argument("--force", action="store_true", help="rebuild the copy even if present")
    s.set_defaults(func=cmd_setup)

    s = sub.add_parser("mirror", help="rebuild only the offline copy of the game")
    s.add_argument("--phase", choices=list(PHASES), default="all",
                   help="resume from one phase without downloading everything again")
    s.set_defaults(func=cmd_mirror)

    s = sub.add_parser("play", help="interactive run in the terminal")
    s.add_argument("--seed", type=int, default=1, help="seed of the run")
    s.add_argument("--watch", action="store_true", help="open a real window and watch")
    s.add_argument("--shots", metavar="FOLDER", help="save an image of every screen")
    s.set_defaults(func=cmd_play)

    s = sub.add_parser("bot", help="run a bot")
    s.add_argument("--bot", default="random", help="which bot to use (see bot/AVAILABLE)")
    s.add_argument("--seed", type=int, default=1)
    s.add_argument("--runs", type=int, default=3)
    s.add_argument("--max-steps", type=int, default=300)
    s.add_argument("--watch", action="store_true", help="open a real window and watch")
    s.add_argument("--shots", metavar="FOLDER", help="save an image at every step")
    s.add_argument("--pause", type=int, default=800, help="ms between moves with --watch")
    s.add_argument("--no-stats", action="store_true", help="do not record the runs")
    s.set_defaults(func=cmd_bot)

    s = sub.add_parser("api", help="start the HTTP API")
    s.add_argument("--api-port", type=int, default=8423)
    s.add_argument("--seed", type=int, default=1, help="seed of the initial run")
    s.set_defaults(func=cmd_api)

    s = sub.add_parser("stats", help="summary of the recorded runs")
    s.add_argument("-d", "--explain", action="store_true",
                   help="explain what each column means")
    s.add_argument("--recent", type=int, default=0, help="also show the last N runs")
    s.add_argument("--bot", default=None, help="filter the recent list by bot")
    s.set_defaults(func=cmd_stats)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
