"""Shared fixtures.

The browser-backed tests need the offline copy of the game in `site/`. If it is
not there they are skipped rather than failing: a fresh clone has no `site/`
until `pokelike setup` has been run.

One browser is started for the whole session and reused: launching Chromium
costs about a second, and every test would pay it again.
"""

from __future__ import annotations

from pathlib import Path

import pytest

RADICE = Path(__file__).resolve().parents[1]
SITO = RADICE / "site"

# Ports well away from the defaults, so a test run never collides with a game
# the developer is playing in another terminal.
PORTA_ASSET = 8551


def pytest_collection_modifyitems(config, items):
    """Skip the browser tests when the offline copy is missing."""
    if (SITO / "index.html").is_file():
        return
    salta = pytest.mark.skip(reason="copia offline assente: esegui `pokelike setup`")
    for item in items:
        if "slow" in item.keywords:
            item.add_marker(salta)


@pytest.fixture(scope="session")
def server():
    from pokelike.assets import ServerAsset

    if not (SITO / "index.html").is_file():
        pytest.skip("copia offline assente")
    s = ServerAsset(SITO, porta=PORTA_ASSET)
    s.avvia()
    yield s
    s.ferma()


@pytest.fixture(scope="session")
def partita(server):
    """A single live game, reused across tests. `nuova()` resets it."""
    from pokelike.core.game import Partita

    g = Partita(url=server.url)
    g.apri()
    yield g
    g.chiudi()


@pytest.fixture()
def db_temporaneo(tmp_path):
    """An empty stats database, isolated from the real one."""
    return tmp_path / "partite.db"
