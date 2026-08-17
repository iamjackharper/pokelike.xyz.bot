"""CLI and HTTP API: both must stay thin faces over the same game."""

from __future__ import annotations

import json
import subprocess
import sys
import urllib.error
import urllib.request

import pytest

from pokelike.interfaces.cli.main import main


def _cli(*argv) -> tuple[int, str]:
    """Runs the CLI in a subprocess and returns (exit code, output)."""
    r = subprocess.run(
        [sys.executable, "-m", "pokelike.interfaces.cli.main", *argv],
        capture_output=True, text=True, timeout=120,
    )
    return r.returncode, r.stdout + r.stderr


def test_help_lists_every_command():
    code, text = _cli("--help")
    assert code == 0
    for command in ("setup", "mirror", "play", "bot", "api", "stats"):
        assert command in text, f"command {command} is missing from the help"


@pytest.mark.parametrize("command", ["setup", "mirror", "play", "bot", "api", "stats"])
def test_every_command_has_its_own_help(command):
    code, _ = _cli(command, "--help")
    assert code == 0


def test_no_command_exits_with_an_error():
    code, _ = _cli()
    assert code != 0


def test_unknown_bot_exits_with_a_readable_error():
    code, text = _cli("bot", "--bot", "nonexistent")
    assert code != 0
    assert "random" in text


def test_main_is_callable_from_python():
    """`main` must not assume it owns the process."""
    with pytest.raises(SystemExit):
        main(["--help"])


# --------------------------------------------------------------------- API
#
# The server runs on the MAIN thread and the requests come from a worker, not
# the other way round: Playwright's sync API is bound to the thread that created
# the game, so the handlers have to run there.


def _api_client(port, steps, results):
    """Makes the HTTP calls and then stops the server, so serve_forever returns."""
    import socket
    import time

    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                break
        time.sleep(0.1)

    base = f"http://127.0.0.1:{port}"

    def get(route):
        with urllib.request.urlopen(f"{base}{route}", timeout=60) as r:
            return json.loads(r.read())

    def post(route, body):
        req = urllib.request.Request(
            f"{base}{route}", data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read())

    try:
        results.update(steps(get, post))
    except Exception as e:  # noqa: BLE001
        results["error"] = f"{type(e).__name__}: {e}"


def _with_api(game, seed, steps, port=8553):
    """Serves the given game over HTTP, lets the client drive, returns results.

    It reuses the session-wide game on purpose: two Playwright sync instances
    cannot live in the same thread, so opening a second browser here would fail
    as soon as any other test has already started one.
    """
    import threading

    from pokelike.interfaces.api.server import create_api

    game.reset(seed=seed)
    httpd = create_api(game, port)
    results: dict = {}
    t = threading.Thread(
        target=lambda: (_api_client(port, steps, results), httpd.shutdown()),
        daemon=True,
    )
    t.start()
    httpd.serve_forever()              # on the main thread, as in production
    httpd.server_close()
    t.join(timeout=10)
    return results


@pytest.mark.slow
def test_api_exposes_the_full_loop(game):
    """Start, read, act, score — all over HTTP."""

    def steps(get, post):
        state = post("/new", {"seed": 21})
        actions = get("/actions")["actions"]
        after = post("/action", {"index": 0})
        return {
            "seed": state["seed"],
            "has_view": "view" in state,
            "n_actions": len(actions),
            "steps_before": state["steps"],
            "steps_after": after["steps"],
            "state_in_sync": get("/state")["steps"] == after["steps"],
            "has_points": "points" in get("/score"),
        }

    r = _with_api(game, 21, steps)
    assert "error" not in r, r.get("error")
    assert r["seed"] == 21
    assert r["has_view"], "the ready-to-print view must be there"
    assert r["n_actions"] >= 2
    assert r["steps_after"] == r["steps_before"] + 1
    assert r["state_in_sync"]
    assert r["has_points"]


@pytest.mark.slow
def test_api_refuses_an_illegal_action(game):
    def steps(get, post):
        try:
            post("/action", {"index": 99})
            return {"code": None}
        except urllib.error.HTTPError as e:
            return {"code": e.code}

    r = _with_api(game, 22, steps, port=8554)
    assert r.get("code") == 409, "an illegal action is a conflict, not a server error"
