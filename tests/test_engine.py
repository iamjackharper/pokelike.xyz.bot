"""The contract of `Game`: what callers are allowed to rely on."""

from __future__ import annotations

import pytest

from pokelike.core.game import IllegalAction


@pytest.mark.slow
def test_state_has_the_expected_keys(game):
    obs = game.reset(seed=3)
    for key in ("screen", "actions", "steps", "seed", "done"):
        assert key in obs, f"missing {key}"
    assert obs["seed"] == 3
    assert obs["steps"] == 0
    assert obs["done"] is False


@pytest.mark.slow
def test_every_decision_offers_at_least_two_choices(game):
    """`_settle` must never hand back a turn with nothing to decide."""
    obs = game.reset(seed=4)
    for _ in range(8):
        if obs["done"]:
            break
        assert len(obs["actions"]) >= 2, f"turn with no choice on {obs['screen']}"
        obs = game.step(0)


@pytest.mark.slow
def test_state_does_not_advance_the_game(game):
    game.reset(seed=6)
    before = game.state()
    after = game.state()
    assert before["steps"] == after["steps"]
    assert before["actions"] == after["actions"]


@pytest.mark.slow
@pytest.mark.parametrize("index", [-1, 99])
def test_illegal_action_is_refused(game, index):
    game.reset(seed=8)
    with pytest.raises(IllegalAction):
        game.step(index)


@pytest.mark.slow
def test_steps_advance_by_one(game):
    obs = game.reset(seed=9)
    before = obs["steps"]
    obs = game.step(0)
    assert obs["steps"] == before + 1


@pytest.mark.slow
def test_score_hook_is_attached(game):
    """The score hook must attach, otherwise every score would be None."""
    game.reset(seed=10)
    assert game.score_hook is not None
    assert game.score_hook.get("ok") is True


@pytest.mark.slow
def test_stats_arrive_at_every_step(game):
    """Per-step counters are what an RL reward would be built from."""
    obs = game.reset(seed=13)
    for _ in range(6):
        if obs["done"] or not obs["actions"]:
            break
        obs = game.step(0)
    assert "stats" in obs
    assert "enemiesKO" in obs["stats"]


@pytest.mark.slow
def test_last_alive_survives_game_over(game):
    """At game over the engine wipes `state`; the snapshot must keep the team."""
    obs = game.reset(seed=1)
    while not obs["done"] and obs["actions"] and game.steps < 60:
        obs = game.step(0)
    assert obs["done"]
    assert not obs.get("team")
    assert game.last_alive is not None
    assert game.last_alive["team"], "the team was lost"


@pytest.mark.slow
def test_the_map_is_a_consistent_graph(game):
    obs = game.reset(seed=14)
    while not obs["done"] and obs["screen"] != "map-screen":
        obs = game.step(0)
    m = obs["map"]
    ids = {n["id"] for n in m["nodes"]}
    for src, dst in m["edges"]:
        assert src in ids and dst in ids, f"edge to a node that does not exist: {src}->{dst}"
    legal = {a["id"] for a in obs["actions"] if a["kind"] == "node"}
    accessible = {n["id"] for n in m["nodes"] if n["accessible"] and not n["visited"]}
    assert legal == accessible
