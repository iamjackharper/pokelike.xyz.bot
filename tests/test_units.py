"""Fast tests: no browser, no network, no game copy needed."""

from __future__ import annotations

import pytest

from pokelike.assets.mirror import _valid_content
from pokelike.bot import AVAILABLE, create
from pokelike.bot.base import Bot
from pokelike.core import render
from pokelike.stats import format_summary, record, recent, summary

# --------------------------------------------------------------- mirror


SPA_SHELL = b"<!DOCTYPE html><html>"


@pytest.mark.parametrize(
    "data,suffix,expected",
    [
        (b"\x89PNG\r\n\x1a\n", ".png", True),
        (SPA_SHELL, ".png", False),           # the case that once filled the mirror with junk
        (b"\xff\xd8\xff\xe0", ".jpg", True),
        (b"ID3\x04", ".mp3", True),
        (SPA_SHELL, ".mp3", False),
        (b"", ".png", False),
        (b"body { }", ".css", True),
    ],
)
def test_recognises_valid_files(data, suffix, expected):
    assert _valid_content(data, suffix) is expected


# ------------------------------------------------------------------ bot


def test_registered_bots_can_be_built():
    assert "random" in AVAILABLE
    assert isinstance(create("random", seed=1), Bot)


def test_unknown_bot_gives_a_useful_error():
    with pytest.raises(KeyError) as e:
        create("nonexistent")
    assert "random" in e.value.args[0]


def test_random_bot_is_reproducible():
    state = {"actions": [{}] * 5, "steps": 0}
    a = create("random", seed=7)
    b = create("random", seed=7)
    a.on_start(7)
    b.on_start(7)
    assert [a.choose(state) for _ in range(20)] == [b.choose(state) for _ in range(20)]


def test_random_bot_stays_in_range():
    state = {"actions": [{}] * 3, "steps": 0}
    b = create("random", seed=1)
    b.on_start(1)
    assert all(0 <= b.choose(state) < 3 for _ in range(50))


def test_abstract_bot_cannot_be_instantiated():
    with pytest.raises(TypeError):
        Bot()


# --------------------------------------------------------------- render


SAMPLE_STATE = {
    "screen": "map-screen",
    "steps": 4,
    "run": {"map": 0, "badges": 1},
    "team": [
        {"name": "Bulbasaur", "level": 5, "hp": 19, "max_hp": 19,
         "types": ["Grass", "Poison"], "item": None, "shiny": True},
        {"name": "Charmander", "level": 7, "hp": 0, "max_hp": 22,
         "types": ["Fire"], "item": "Life Orb", "shiny": False},
    ],
    "bag": ["Potion"],
    "map": {
        "nodes": [
            {"id": "n0_0", "kind": "start", "layer": 0, "col": 0,
             "accessible": False, "visited": True, "revealed": True},
            {"id": "n1_0", "kind": "catch", "layer": 1, "col": 0,
             "accessible": True, "visited": False, "revealed": True},
            {"id": "n1_1", "kind": "battle", "layer": 1, "col": 1,
             "accessible": True, "visited": False, "revealed": True},
            {"id": "n9_9", "kind": "boss", "layer": 9, "col": 0,
             "accessible": False, "visited": False, "revealed": False},
        ],
        "edges": [["n0_0", "n1_0"], ["n0_0", "n1_1"]],
        "current": "n0_0",
    },
    "actions": [
        {"kind": "node", "id": "n1_0", "node": "catch", "layer": 1, "col": 0},
        {"kind": "node", "id": "n1_1", "node": "battle", "layer": 1, "col": 1},
    ],
    "done": False,
}


def test_map_marks_position_and_legal_moves():
    text = render.map_view(SAMPLE_STATE["map"])
    assert "[@]" in text, "the current position is not marked"
    assert "<o>" in text and "<x>" in text, "legal moves are not marked"
    assert "B" not in text, "an unrevealed node must not show up"


def test_team_shows_hp_and_shiny():
    text = render.team_view(SAMPLE_STATE["team"])
    assert "Bulbasaur" in text and "19/19" in text
    assert "Life Orb" in text
    assert "*" in text, "the shiny is not marked"


def test_actions_are_numbered_from_zero():
    text = render.actions_view(SAMPLE_STATE["actions"])
    assert "[0]" in text and "[1]" in text


def test_screen_survives_an_empty_state():
    """A caller should never get an exception just for rendering early state."""
    assert render.screen({"actions": []})


def test_screen_contains_the_pieces():
    text = render.screen(SAMPLE_STATE)
    for piece in ("Bulbasaur", "n1_0", "[@]"):
        assert piece in text


# ----------------------------------------------------------------- stats


FINAL_STATE = {"screen": "gameover-screen", "run": {"badges": 2}, "team": []}
ALIVE_STATE = {"run": {"badges": 2}, "team": [{"name": "Pikachu", "level": 12,
                                               "hp": 3, "max_hp": 30}]}
SCORE = {
    "points": 1005,
    "points_no_time": 25,
    "breakdown": {"enemiesKO": 9, "faints": 4, "mapsCleared": 1,
                  "winBonus": 0, "legendaries": 0, "shinies": 0, "timeBonus": 980},
    "stats": {"catches": 3, "totalDamageDealt": 220, "highestLevel": 12},
}


def test_record_then_read_back(temp_db):
    idx = record(bot="probe", seed=1, state=FINAL_STATE, score=SCORE,
                 steps=17, alive=ALIVE_STATE, path=temp_db)
    assert idx > 0
    rows = recent(5, path=temp_db)
    assert len(rows) == 1
    assert rows[0]["bot"] == "probe"
    assert rows[0]["points"] == 25, "it must store the score without the time bonus"


def test_the_team_comes_from_the_alive_state(temp_db):
    """The regression that started this: at game over the final state is empty."""
    import json
    import sqlite3

    record(bot="probe", seed=1, state=FINAL_STATE, score=SCORE,
           steps=17, alive=ALIVE_STATE, path=temp_db)

    conn = sqlite3.connect(temp_db)
    (team,) = conn.execute("SELECT team FROM runs").fetchone()
    assert json.loads(team)[0]["name"] == "Pikachu"


def test_summary_aggregates_per_bot(temp_db):
    for seed in (1, 2, 3):
        record(bot="alpha", seed=seed, state=FINAL_STATE, score=SCORE,
               steps=10, alive=ALIVE_STATE, path=temp_db)
    record(bot="beta", seed=1, state=FINAL_STATE, score=SCORE,
           steps=10, alive=ALIVE_STATE, path=temp_db)

    rows = {r["bot"]: r for r in summary(path=temp_db)}
    assert rows["alpha"]["runs"] == 3
    assert rows["beta"]["runs"] == 1
    assert rows["alpha"]["badges_best"] == 2
    assert rows["alpha"]["score_avg"] == 25


def test_empty_summary_does_not_blow_up(temp_db):
    assert "no runs" in format_summary(summary(path=temp_db))


def test_explain_describes_the_columns(temp_db):
    record(bot="alpha", seed=1, state=FINAL_STATE, score=SCORE,
           steps=10, alive=ALIVE_STATE, path=temp_db)
    rows = summary(path=temp_db)
    short = format_summary(rows)
    long = format_summary(rows, explain=True)
    assert len(long) > len(short)
