"""Command-line interface.

A thin face over `core.game.Game`, the same class the API uses. No game logic
lives here.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ...assets.mirror import PHASES, build
from ...bench import CATEGORIES, STANDARD_SEEDS, format_result, run_benchmark
from ...leaderboard import build_index, format_table, write_entry
from ...runner import play_run
from ...assets.server import AssetServer
from ...core import render
from ...core.game import Game, IllegalAction
from ...stats import format_summary, record, recent, summary

SITE_ROOT = Path(__file__).resolve().parents[4] / "site"
LEADERBOARD = Path(__file__).resolve().parents[4] / "leaderboard"

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
        text = str(e)
        if "missing dependencies" in text or "error while loading shared libraries" in text:
            print("cannot start the browser." + MISSING_DEPS_HELP, file=sys.stderr)
            raise SystemExit(3) from e
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


MISSING_DEPS_HELP = """
The browser downloaded but cannot start: your Linux is missing the system
libraries Chromium needs. This is common on Raspberry Pi, minimal server images
and containers.

Install them, then run `pokelike setup` again:

    sudo apt-get install -y libatk1.0-0t64 libatk-bridge2.0-0t64 libcups2t64 \
        libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 \
        libasound2t64 libatspi2.0-0t64 libpango-1.0-0 libcairo2 libnss3

On older Ubuntu or Debian, drop the `t64` suffixes. Or let Playwright do it:

    sudo $(which python) -m playwright install-deps chromium

Note the `sudo $(which python)`: plain `sudo playwright` usually fails because
the virtualenv is not on root's PATH."""


def browser_works() -> tuple[bool, str]:
    """Actually launches the browser. Downloading it is not the same as running it.

    The Playwright installer exits 0 even when it warns that the host is missing
    libraries, so trusting the exit code makes `setup` claim success and every
    later command fail with a stack trace. Better to find out here.
    """
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            b = pw.chromium.launch(args=["--no-sandbox"])
            b.close()
        return True, ""
    except Exception as e:  # noqa: BLE001
        return False, str(e)


def cmd_setup(args) -> int:
    """Gets everything ready: browser + offline copy. Run once."""
    import subprocess

    print("[1/3] downloading the headless browser (~120 MB)")
    r = subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium", "--only-shell"]
    )
    if r.returncode != 0:
        print("browser installation failed", file=sys.stderr)
        return r.returncode

    print("[2/3] checking it actually starts")
    ok, why = browser_works()
    if not ok:
        print("\n  the browser does not start.\n", file=sys.stderr)
        if "missing dependencies" in why or "error while loading shared libraries" in why:
            print(MISSING_DEPS_HELP, file=sys.stderr)
        else:
            print(f"  {why[:600]}", file=sys.stderr)
        return 3
    print("      ok")

    if (SITE_ROOT / "index.html").is_file() and not args.force:
        print(f"[3/3] offline copy already in {SITE_ROOT} — skipping")
        print("      (use --force to rebuild it)")
    else:
        print("[3/3] downloading the game for offline use (~130 MB, a few minutes)")
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
    from ...bot import create

    try:
        bot = create(args.bot, seed=args.seed)
    except KeyError as e:
        print(e.args[0], file=sys.stderr)
        raise SystemExit(2) from e

    server, game = _server_and_game(args)
    try:
        for i in range(args.runs):
            seed = args.seed + i

            def each_step(obs, steps, _i=i):
                if args.shots:
                    game.screenshot(
                        Path(args.shots) / f"{_i:02d}-{steps:03d}-{obs['screen']}.png"
                    )
                if args.watch and steps:
                    game.session.page.wait_for_timeout(args.pause)

            # Streamed rather than printed at the end: a run takes tens of
            # seconds, and watching it decide is the point of asking for a log.
            def each_decision(entry):
                print(render.trace_view([entry], detail=args.detailed), flush=True)

            if args.detailed:
                print(f"\n--- run {i + 1}/{args.runs}, seed {seed} ---", flush=True)

            r = play_run(game, bot, seed, max_steps=args.max_steps, on_step=each_step,
                         on_decision=each_decision if args.detailed else None)

            if not args.no_stats:
                record(bot=args.bot, seed=seed, state=r["final_state"],
                       score=r["score_detail"], steps=r["steps"], alive=game.last_alive,
                       extra=bot.notes() if hasattr(bot, "notes") else None)
            # We print `score` (points without the time bonus) because it is the
            # only comparable one: the time bonus is worth ~1000 on a scale where
            # everything else is in the tens.
            print(
                f"run {i + 1}/{args.runs}  seed {seed}  "
                f"steps {r['steps']:>3}  end {r['ending']:<16} "
                f"badges {r['badges']}  score {r['score']}  "
                f"(KO {r['kos']}, faints {r['faints']}, maps {r['maps']})"
            )
        return 0
    finally:
        game.close()
        server.stop()


def cmd_bench(args) -> int:
    """Runs the standard benchmark and writes a submittable result file."""
    from ...bot import create

    try:
        bot = create(args.bot, seed=0)
    except KeyError as e:
        print(e.args[0], file=sys.stderr)
        raise SystemExit(2) from e

    seeds = STANDARD_SEEDS[: args.runs] if args.runs else STANDARD_SEEDS
    server, game = _server_and_game(args)
    try:
        result = run_benchmark(
            game, bot, bot_name=args.name or args.bot, site=SITE_ROOT, seeds=seeds,
            author=args.author, category=args.category, description=args.description,
        )
    finally:
        game.close()
        server.stop()

    print(format_result(result))

    # The entry folder is built here rather than left to the submitter: the bot
    # source, whatever it declared in artifacts(), and the result all get hashed
    # together, so they can never drift apart.
    entry = write_entry(LEADERBOARD, result, bot)
    build_index(LEADERBOARD)

    rel = entry.relative_to(Path.cwd()) if entry.is_relative_to(Path.cwd()) else entry
    print(f"\n  entry written to {rel}/")
    for f in sorted(entry.rglob("*")):
        if f.is_file():
            print(f"    {f.relative_to(entry)}")
    print("\n  to submit (you do not need write access to the repo):")
    print("    1. fork it on GitHub, if you have not already")
    print(f"    2. git checkout -b {result['bot']}")
    print(f"    3. git add {rel} src/pokelike/bot/")
    print(f"    4. git commit -m 'Add {result['bot']}' && git push origin {result['bot']}")
    print("    5. open the pull request GitHub offers you")
    return 0


def cmd_leaderboard(args) -> int:
    """Rebuilds the index from the entries on disk and prints the table."""
    index = build_index(LEADERBOARD)
    print(format_table(index))
    print(f"\n  {len(index['entries'])} entries in {LEADERBOARD}/entries/")
    return 0


def cmd_schema(args) -> int:
    """Prints what a bot receives, captured from a live run."""
    from ...schema import as_markdown, capture, describe

    server, game = _server_and_game(args)
    try:
        obs = capture(game)
    finally:
        game.close()
        server.stop()

    if args.json:
        print(json.dumps(obs, indent=1))
    elif args.markdown:
        out = Path(__file__).resolve().parents[4] / "docs" / "STATE.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(as_markdown(obs), encoding="utf-8")
        print(f"written to {out}")
    else:
        print(describe(obs))
    return 0


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
    s.add_argument("-d", "--detailed", action="count", default=0,
                   help="one line per decision; -dd adds the bot's reasoning, "
                        "-ddd adds the team")
    s.set_defaults(func=cmd_bot)

    s = sub.add_parser("api", help="start the HTTP API")
    s.add_argument("--api-port", type=int, default=8423)
    s.add_argument("--seed", type=int, default=1, help="seed of the initial run")
    s.set_defaults(func=cmd_api)

    s = sub.add_parser("bench", help="run the standard benchmark and produce a result file")
    s.add_argument("--bot", default="random", help="which bot to benchmark")
    s.add_argument("--name", default=None, help="name for the leaderboard (defaults to --bot)")
    s.add_argument("--author", default="", help="your name or github handle")
    s.add_argument("--category", default="other", choices=list(CATEGORIES),
                   help="rules, rl, llm, human or other")
    s.add_argument("--description", default="", help="one line on how it works")
    s.add_argument("--runs", type=int, default=0,
                   help="use only the first N standard seeds (a full run is 50)")
    s.set_defaults(func=cmd_bench)

    s = sub.add_parser("leaderboard", help="rebuild and print the leaderboard table")
    s.set_defaults(func=cmd_leaderboard)

    s = sub.add_parser("schema", help="what a bot receives: state, actions, node kinds")
    s.add_argument("--json", action="store_true", help="print a real observation instead")
    s.add_argument("--markdown", action="store_true", help="regenerate docs/STATE.md")
    s.set_defaults(func=cmd_schema)

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
