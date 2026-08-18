"""Shared fixtures.

The browser-backed tests need the offline copy of the game in `site/`. If it is
not there they are skipped rather than failing: a fresh clone has no `site/`
until `pokelike setup` has been run.

One browser is started for the whole session and reused: launching Chromium
costs about a second, and every test would otherwise pay it again.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"

# `experiments/` is training code, not part of the shipped package, so it is not
# installed. Tests still need to import it: the one that matters checks that the
# feature set frozen inside a bot has not drifted from the one it was trained
# with, which can only be done by holding the two side by side.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

def free_port() -> int:
    """A port the OS says is free, asked for at the moment it is needed.

    It used to be the constant 8551, which collides with itself: two test runs
    at once, or one left over from a killed run still holding the socket, and
    every browser-backed test errors with `Address already in use` — which reads
    exactly like a real failure and is not one.
    """
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


ASSET_PORT = free_port()


def pytest_collection_modifyitems(config, items):
    """Skip the browser tests when the offline copy is missing."""
    if (SITE / "index.html").is_file():
        return
    skip = pytest.mark.skip(reason="offline copy missing: run `pokelike setup`")
    for item in items:
        if "slow" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def server():
    from pokelike.assets import AssetServer

    if not (SITE / "index.html").is_file():
        pytest.skip("offline copy missing")
    s = AssetServer(SITE, port=ASSET_PORT)
    s.start()
    yield s
    s.stop()


@pytest.fixture(scope="session")
def game(server):
    """A single live game, reused across tests. `reset()` starts a new run."""
    from pokelike.core.game import Game

    g = Game(url=server.url)
    g.open()
    yield g
    g.close()


@pytest.fixture()
def temp_db(tmp_path):
    """An empty stats database, isolated from the real one."""
    return tmp_path / "runs.db"
