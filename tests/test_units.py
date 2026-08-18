"""Fast tests: no browser, no network, no game copy needed."""

from __future__ import annotations

import pathlib

import pytest

from pokelike.assets.mirror import _valid_content
from pokelike.bot import available, create
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


def test_every_bot_on_disk_defines_exactly_one_bot():
    """Each folder under `bots/` must load and define one Bot subclass.

    A bot is loaded from a directory rather than imported from a registry, so
    nothing checks it until something tries to play it. This is that check: a
    folder that will not load is a bot nobody can run, including its author.

    It stops at the CLASS on purpose. Building one is allowed to need things a
    test does not have — the LLM bot refuses to construct without credentials,
    which is deliberate and right.
    """
    from pokelike.bot.catalogue import BOTS, available as on_disk, load_class

    names = on_disk()
    assert names, "bots/ has no bots in it"
    for name in names:
        cls = load_class(BOTS / name / "bot.py")
        assert issubclass(cls, Bot), f"{name} does not inherit from Bot"


def test_the_baseline_is_always_available():
    """`random` must build with no bots/ folder at all: `compare()` defaults to it."""
    assert "random" in available()
    assert isinstance(create("random", seed=1), Bot)


def test_the_sarsa_bot_freezes_exactly_the_features_it_was_trained_on():
    """The copy in `bots/sarsa-v2/bot.py` must stay identical to the training code.

    Weights are a plain list of numbers: index 43 only means `mon_new_type`
    because `feature_names()` says so. Insert one feature on the training side
    and every index after it silently points somewhere else, so the same file of
    weights becomes a different policy — including policies already on the
    leaderboard.

    If this fails, the fix is to bump `FEATURES_VERSION` and retrain, never to
    quietly paste the new names across.
    """
    from experiments.sarsa_lambda.features import feature_names as trained_on

    from pokelike.bot.catalogue import load_class

    frozen = load_class(pathlib.Path("bots/sarsa-v2/bot.py")).__module__
    import sys

    assert sys.modules[frozen].feature_names() == trained_on()


def test_new_bot_writes_something_that_loads(tmp_path):
    """Both templates, because they break differently.

    The LLM one is full of JSON — tool schemas are literal braces — and the
    scaffold used `str.format`, so adding a commented-out tool example to the
    template made `new-bot` die with a KeyError about a JSON key. A template is
    only text until someone runs it.
    """
    from pokelike.bot.catalogue import load_class
    from pokelike.bot.llm import LLMBot
    from pokelike.scaffold import new_bot

    plain = load_class(new_bot("probe-plain", tmp_path) / "bot.py")
    assert plain(seed=0).choose({"actions": [{}, {}], "team": []}) in (0, 1)

    llm = load_class(new_bot("probe-llm", tmp_path, llm=True) / "bot.py")
    assert issubclass(llm, LLMBot) and llm.PROMPT
    assert "play" in [t["function"]["name"] for t in llm.tools(llm)]


def test_the_two_sarsas_are_two_different_policies():
    """v1 and v2 exist side by side to be compared, so they must differ.

    The failure this catches is copying a folder to make a variant and forgetting
    to change the weights: two rows on the leaderboard, one policy, and a
    difference in their scores that is pure noise being read as progress.
    """
    import json

    v1, v2 = (json.loads(pathlib.Path(f"bots/sarsa-{v}/artifacts/weights.json")
                         .read_text(encoding="utf-8")) for v in ("v1", "v2"))
    assert v1["encoding_version"] != v2["encoding_version"]
    assert len(v1["weights"]) != len(v2["weights"])


def test_every_llm_bot_uses_the_shared_harness_and_its_own_prompt():
    """The whole point of the split: same loop, different prompts.

    A benchmark of models compares models only if the harness is held still. An
    LLM bot that reimplements the loop, or two that ship the same prompt, are
    measuring something other than what the standings claim.
    """
    from pokelike.bot.catalogue import BOTS, available as on_disk, load_class
    from pokelike.bot.llm import HARNESS, LLMBot

    prompts = {}
    for name in [n for n in on_disk() if n.startswith("llm-")]:
        cls = load_class(BOTS / name / "bot.py")
        assert issubclass(cls, LLMBot), f"{name} does not build on the shared harness"
        assert cls.HARNESS == HARNESS, f"{name} pins an old harness version"
        assert cls.PROMPT and cls.PROMPT not in prompts, (
            f"{name} has the same prompt as {prompts.get(cls.PROMPT)}")
        prompts[cls.PROMPT] = name
    assert len(prompts) >= 2, "there is nothing to compare"


def test_an_llm_bot_refuses_to_build_without_credentials(monkeypatch):
    """Never a silent default: a bot that cannot reach a model must say so.

    Falling back here would play a whole run on the backup heuristic and file it
    as an LLM result — a leaderboard row no model ever played.
    """
    from pokelike.bot.llm import LLMBot, LLMConfigError

    class Probe(LLMBot):
        PROMPT = "x"

    for var in ("FW_ENDPOINT", "FW_TOKEN", "MODEL_ID"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(LLMConfigError) as e:
        Probe()
    assert "FW_ENDPOINT" in str(e.value)

    monkeypatch.setenv("FW_ENDPOINT", "https://example.invalid")
    monkeypatch.setenv("FW_TOKEN", "t")
    with pytest.raises(LLMConfigError) as e:
        Probe()
    assert "MODEL_ID" in str(e.value)


def test_a_bot_may_add_its_own_tools_but_not_remove_play(monkeypatch):
    """Tools are overridable, because a prompt is not the only thing worth trying.

    `play` is the exception, checked once at construction rather than discovered
    fifty runs in: it is how a turn ends, so without it every turn exhausts its
    rounds and falls back — a whole benchmark of our backup heuristic, filed
    under the model's name, with nothing that looks wrong until you read
    `fallback_rate`.
    """
    from pokelike.bot.llm import LLMBot, LLMConfigError

    for var, val in (("FW_ENDPOINT", "https://x.invalid"),
                     ("FW_TOKEN", "t"), ("MODEL_ID", "m")):
        monkeypatch.setenv(var, val)

    class Extra(LLMBot):
        PROMPT = "x"
        EXTRA_TOOLS = [{"type": "function",
                        "function": {"name": "bag", "parameters": {}}}]

        def run_tool(self, name, args, state):
            return "a potion" if name == "bag" else super().run_tool(name, args, state)

    bot = Extra()
    assert "bag" in bot.tool_names() and "play" in bot.tool_names()
    assert bot.run_tool("bag", {}, {}) == "a potion"
    assert "empty team" in bot.run_tool("team_details", {}, {"team": []})
    # An invented tool is answered, not raised: the model should be told and
    # allowed to carry on, not have the turn thrown away and played by fallback.
    assert "unknown tool" in bot.run_tool("invented", {}, {})
    # And the difference is recorded, so the row is not read as comparable.
    assert bot.notes()["stock_tools"] is False

    class NoPlay(LLMBot):
        PROMPT = "x"

        def tools(self):
            return []

    with pytest.raises(LLMConfigError) as e:
        NoPlay()
    assert "play" in str(e.value)


def test_a_name_matching_two_bots_is_an_error_not_a_guess():
    """`--bot sarsa` with sarsa-v1 and sarsa-v2 on disk must refuse to choose.

    Variants of one idea share a name, so picking one silently produces a result
    that looks entirely plausible and is about the wrong bot.
    """
    from pokelike.bot import resolve

    assert resolve("sarsa-v1") == "sarsa-v1"
    assert resolve("rand") == "random", "a unique prefix should still work"
    with pytest.raises(KeyError) as e:
        resolve("sarsa")
    assert "sarsa-v1" in e.value.args[0] and "sarsa-v2" in e.value.args[0]


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
