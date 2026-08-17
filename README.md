# pokelike.xyz.bot

Play [pokelike.xyz](https://pokelike.xyz/) — a Pokémon roguelike — from the
command line, from Python, or over an HTTP API. No windows, no internet, and a
score to compare players with.

Built to let bots play it. Three ship with it (random, an LLM one, and a trained
Dyna-Q policy), the interface for writing your own is a single method, and there
is a benchmark and a leaderboard so bots can be compared honestly.

---

## Install

You need [uv](https://docs.astral.sh/uv/) and nothing else:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Then:

```bash
git clone https://github.com/pierpierpy/pokelike.xyz.bot
cd pokelike.xyz.bot
uv sync              # creates the environment and installs dependencies
uv run pokelike setup
```

`setup` does three things, once:

1. downloads the headless browser (~120 MB)
2. checks it actually starts
3. downloads the game into `site/` (~130 MB, a few minutes)

After that **you never need the internet again**.

> **On Linux you may need system libraries.** Chromium needs a handful of them,
> and minimal images — Raspberry Pi, servers, containers — usually lack them.
> `setup` tells you if that is your case and prints the exact command. It checks
> by launching the browser rather than trusting the installer's exit code, which
> is 0 even when it warns.
>
> ```bash
> sudo $(which python) -m playwright install-deps chromium
> ```
>
> Use `sudo $(which python)`, not plain `sudo playwright`: the virtualenv is not
> on root's PATH.

> No environment to activate: `uv run` handles it. If you prefer,
> `source .venv/bin/activate` and then drop the `uv run` prefix.

## Play it yourself

```bash
uv run pokelike play --seed 42
```

You get the situation and answer with a number:

```
========================================================================
step 2   screen: map-screen   map 0   badges 0
========================================================================

TEAM
  0. Bulbasaur    Lv 5  ##########  19/19   Grass/Poison *

MAP   [here]  <legal move>  x'=done
  layer  0 | [@]
  layer  1 | <o> <x>
  layer  2 |  T   x   T
  layer  3 |  o   o   i   o
  layer  8 |  B

ACTIONS
  [0] go to node n1_0   (catch)
  [1] go to node n1_1   (battle)

> 1
```

Reading the map: it runs top to bottom, `[here]` is where you are, `<like this>`
are the legal moves, `x'` is already done, the boss sits at the bottom.
**Picking one node closes the others on that layer forever.**

At the prompt: a **number** to act, `l` for the symbol legend, `s` for the score,
`j` for the raw JSON state, `n` for a new run, `q` to quit.

## Let a bot play

```bash
uv run pokelike bot --runs 5             # the random bot
uv run pokelike bot --runs 1 -d          # + log every decision it made
uv run pokelike stats                    # how it went
```

`-d` streams one line per decision as it happens, so you watch the bot play
rather than read a report afterwards. `>` marks what it took, `b` is badges and
`m` is which map:

```
$ pokelike bot --runs 1 -d

--- run 1/1, seed 1 ---
    0 trainer-screen    b0 m0 | >BOY   GIRL
    1 starter-screen    b0 m0 |  Bulbasaur Lv5   Charmander Lv5  >Squirtle Lv5
    2 map-screen        b0 m0 | >catch   battle
    3 catch-screen      b0 m0 |  Venonat Lv4  >Slowpoke Lv4   Nidoran-f Lv4
    4 map-screen        b0 m0 | >catch   battle
    5 catch-screen      b0 m0 |  Geodude Lv4  >Zubat Lv4   Venonat Lv4
    6 map-screen        b0 m0 |  catch  >battle
    7 map-screen        b0 m0 |  catch  >battle
    8 map-screen        b0 m0 |  tutor  >catch
    9 catch-screen      b0 m0 | >Voltorb Lv4   Poliwag Lv4   Magnemite Lv4
   10 map-screen        b0 m0 | >trainer   unknown
   11 map-screen        b0 m0 |  pokecenter  >unknown
run 1/1  seed 1  steps 12  end gameover-screen  badges 0  score -15  (KO 5, faints 4, maps 0)
```

That is the random bot, and you can watch it lose: it takes `unknown` over
`pokecenter` on the last turn with a hurt team.

`-dd` adds the bot's own reasoning, `-ddd` the team as well:

```
    2 | map-screen         map 0  badges 0
      | [0] catch  [1]*battle
      | -> battle
      |    Q: catch=5.8, battle=7.3
```

Everything but that last line is recorded by the shared run loop, so a log means
the same thing whatever is playing. The reasoning comes from an optional
`explain()` hook and is simply absent for a bot with nothing to say.

The LLM bot needs your own credentials for any OpenAI-compatible endpoint
(OpenAI, vLLM, Ollama, a company endpoint — whatever you have):

```bash
export FW_ENDPOINT="https://your-endpoint"    # no trailing /v1
export FW_TOKEN="your-key"
export MODEL_ID="your-model-name"

uv run pokelike bot --bot llm --runs 3
POKELIKE_VERBOSE=1 uv run pokelike bot --bot llm --runs 1   # with its reasoning
```

Credentials are read **only** from the environment: they never reach the code or
the run registry.

## Watch what happens

```bash
uv run pokelike play --seed 42                     # text only (fastest)
uv run pokelike play --seed 42 --shots /tmp/shots  # + a PNG of every screen
uv run pokelike play --seed 42 --watch             # + a real window of the game
```

`--watch` works on `bot` too, with `--pause` for the milliseconds between moves.
It needs the full browser: `uv run playwright install chromium`.

---

## How it works

### The game lives entirely in the browser

Pokelike has no server: all its logic sits in one JavaScript file that runs in
your browser. So there is no remote API to call — the engine is already on your
machine, and we talk straight to its functions.

### "Headless" does not mean "no graphics"

It means **no window**. The browser still builds everything in memory: the game
state, the buttons, the map. It simply never paints them.

So we look at no pixels and recognise no images. The ASCII map above is not read
from a screenshot: we redraw it from the nodes and edges we read out of the
game's memory.

### Battles play themselves

The game picks the moves for both sides. What a player decides is the roguelike
part: where to go on the map, who to catch, which item to take and who to give it
to, who to swap out when the team is full.

### The pieces

```
site/                the downloaded game (not in git)
   │
   ▼
assets/server.py     serves it from disk, never touching the internet
   │
   ▼
headless browser     runs the game
   │
core/bridge.js       reads the state, performs the choices
   │
core/game.py         class Game  ← THE LOGIC, one copy of it
   │
   ├─── interfaces/cli/   the terminal
   ├─── interfaces/api/   HTTP JSON
   └─── bot/              whoever decides the moves
```

`Game` has four methods, and everything else goes through them:

```python
g.reset(seed=42)   # start
g.state()          # team, map, legal actions
g.step(1)          # take move 1 -> new state
g.score()          # what the run is worth
```

CLI, API and bots are three faces over those four methods. None of them holds any
game logic.

### The two interfaces

**Python**

```python
from pokelike import Game
from pokelike.assets import AssetServer

with AssetServer("site") as s, Game(url=s.url) as g:
    obs = g.reset(seed=42)
    while not obs["done"]:
        print(obs["actions"])   # [{'kind':'node','id':'n1_0','node':'catch'}, ...]
        obs = g.step(0)
    print(g.score())
```

**HTTP** — `uv run pokelike api` (port 8423). The browser stays alive between
calls, which is why this is a process that has to keep running.

| Method | Route | What it does |
|---|---|---|
| `POST` | `/new` `{"seed":42}` | start a run |
| `GET` | `/state` | full state + a ready-to-print `view` field |
| `GET` | `/actions` | just the legal actions |
| `POST` | `/action` `{"index":1}` | take it → new state (409 if illegal) |
| `GET` | `/score` | score using the game's own formula |
| `GET` | `/screenshot` | a PNG of the current screen |
| `GET` | `/schema` | what the state contains, described from itself |

### Who can do what

The two interfaces are meant for different drivers, so they are not identical —
but everything needed to *play* is in both.

| | CLI | HTTP |
|---|---|---|
| start, read, act, score | yes | yes |
| see the screen | `--shots`, `--watch` | `GET /screenshot` |
| what the state contains | `pokelike schema` | `GET /schema` |
| run a bot over many seeds | `pokelike bot` | — |
| benchmark and submit | `pokelike bench` | — |
| history and leaderboard | `pokelike stats`, `leaderboard` | — |
| install and mirror | `pokelike setup`, `mirror` | — |

The missing HTTP rows are batch and installation jobs, not ways of playing a
run. Exposing them over an interface whose whole job is one live game would be
scope, not symmetry.

---

## Writing a bot

A bot is one thing only: given the state, it says **which action to take**.

**What you get to look at:** [docs/STATE.md](docs/STATE.md), or run
`uv run pokelike schema`. It is generated from a live observation, so it cannot
describe a game that no longer exists.

```python
# src/pokelike/bot/mine.py
from .base import Bot

class MyBot(Bot):
    name = "mine"

    def choose(self, state):
        # state["actions"] is the numbered list you see when playing
        for i, a in enumerate(state["actions"]):
            if a.get("node") == "catch":
                return i          # catch whenever you can
        return 0
```

Register it in `AVAILABLE` inside [bot/\_\_init\_\_.py](src/pokelike/bot/__init__.py):

```python
AVAILABLE = {
    "random": ("random_bot", "RandomBot"),
    "llm":    ("llm", "LLMBot"),
    "mine":   ("mine", "MyBot"),      # <-
}
```

then use it: `uv run pokelike bot --bot mine`. Modules are imported only when
needed, so a bot that pulls in torch does not slow down the others.

Two optional hooks for bots that need memory across turns: `on_start(seed)` and
`on_end(state, score)`.

### The bots that ship with it

**`random`** picks uniformly among the legal actions. It is the baseline: dead in
12–17 moves, no badges, no maps cleared, score around zero. Everyone has to beat
it.

**`llm`** ([bot/llm.py](src/pokelike/bot/llm.py)) is self-contained: prompts,
tools, agentic loop and the HTTP call with `urllib`. Each turn the model gets the
situation and the numbered actions, may call read-only tools, and closes with
`play(index)`:

| tool | what it gives |
|---|---|
| `team_details` | HP, levels, types, held items |
| `what_lies_ahead` | where each action leads on the next layer |
| `play(index, why)` | performs it and ends the turn |

`what_lies_ahead` is the one that matters: the choice closes the other nodes on
that layer forever, and without reading the edges the model cannot know that.

If the model returns a bad index, times out, or never calls `play`, the bot falls
back to a safe choice and the fallback is counted. **A run never dies because of
the model.**

**`dyna_q`** ([bot/dyna_q.py](src/pokelike/bot/dyna_q.py)) plays a policy trained
by [experiments/dyna_q](experiments/dyna_q/). It doubles as the worked example of what
a leaderboard submission looks like, which is why it carries its own copy of the
state encoding instead of importing the training code.

---

## The score

It is the game's own, not something we made up:

```
500 if completed + 5·enemies_KOd − 10·faints + 50·maps_cleared
+ 20·legendaries + 20·shinies + time_bonus
```

Use **`points_no_time`** to compare: the time bonus is worth ~1000 on a scale
where everything else is in the tens, so it would drown out the rest.

## Statistics

Every `pokelike bot` run lands in `stats/runs.db`, a SQLite file you can query
with plain SQL. `--no-stats` skips it.

```bash
uv run pokelike stats                # summary per bot
uv run pokelike stats -d             # + what each column means
uv run pokelike stats --recent 10    # + the last runs
```

```
bot         runs  done  badge~ badge+  maps~  maps+  score~ score- score+ catch~   KO~ faint~ Lv max~ moves~
------------------------------------------------------------------------------------------------------------
random         7     0    0.43      1    0.0      0    -2.1    -35     25    2.3   7.0    3.7    12.6   14.7
```

`~` is the average, `+` the best. Careful with `done`: those are runs *completed*
by beating the whole League, not badges — badges are their own column.

The `extra` column is free-form JSON for a bot's own notes: the LLM one puts its
model, call count, tokens spent and how many fallbacks it made.

## If a piece of the game is missing

The local copy can have holes: some addresses the game builds on the fly
(`"img/sprites/items/" + name + ".png"`) and cannot be found by reading the code.
To check:

```bash
uv run pokelike mirror --phase verify
```

It plays with the network closed, lists what is missing, downloads it and checks
again. It does not guess: the list comes from the game itself as it plays.

**What happens if something is missing:** nothing, as far as the game goes.
Images are decoration. The local server answers 404, notes it down, and the game
shows an emoji instead of the sprite. **The run, the rules and the score do not
change at all** — verified by deleting a sprite in use and replaying the same
run: same steps, same ending, same score.

Bots do not even notice: they read the game state, not pixels. A missing sprite
only shows up with `--watch` or `--shots`.

The only file that truly matters is the game bundle (`js/bundle.*.js`): without
it the game does not start, and you find out immediately.

## Submit a bot

There is a [leaderboard](leaderboard/): anyone can submit a bot, of any kind.
Hand-written rules, a prompt and an LLM, a trained RL policy, a search, a mix.

```bash
uv run pokelike bench --bot yourbot --name "your-bot" \
    --author "your-handle" --category rules --description "how it works"
```

That plays a fixed list of 50 seeds and writes a result file recording the
scores, the seeds, and the sha256 of the game bundle you played. Both matter:
luck dominates a single run, and the upstream game gets updated, so without them
a leaderboard silently compares different things.

**You do not need write access.** Fork the repo, push your branch to your fork,
and open a pull request with the result file, your bot's code, and its weights if
it has any. [leaderboard/README.md](leaderboard/README.md) walks through the fork
and PR steps command by command, explains the categories, and covers how LLM
entries are handled (they are not independently reproducible, and are marked as
such). [`bot/dyna_q.py`](src/pokelike/bot/dyna_q.py) is the worked example of a
submitted bot.

If the git side is a hassle, open an issue and paste your result file into it
instead.

## Making a bot play better

[experiments/](experiments/) holds the attempts, kept outside the package: the
package is the environment, that folder is the research on top of it. Not all of
it is training — teaching a policy with RL and finding a better prompt for an LLM
are both ways of improving a player.

```bash
uv run python -m experiments.dyna_q.train --episodes 200 --reward progress
uv run python -m experiments.llm.compare --strategies survivor,explorer --seeds 5
```

`experiments/mdp/` states the game as an MDP: the encoding, the environment
adapter, and five selectable reward functions. That last one matters
more than it sounds, because **the engine's score is a Battle Tower formula**:
`mapsCleared` only increments on the endless path and `winBonus` needs the whole
League, so in Story mode what is left is `5·KO − 10·faints` with badges absent
entirely. That is why a run with three badges can score −5, why the leaderboard
ranks by badges, and why the reward you train on is worth choosing deliberately.

See [experiments/README.md](experiments/README.md) for the game framed as an MDP
and what makes it awkward (slow steps, sparse rewards, a state-dependent action
set).

## Reproducibility

Same seed + same actions = exactly the same run. That is what lets you compare
two bots on the same games rather than on luck.

## Tests

```bash
uv run pytest              # the whole suite (~3 minutes)
uv run pytest -m "not slow"   # only the fast ones, no browser needed
```

The regression tests replay recorded runs and compare fingerprints made only of
engine data — screens, node types, scores — so refactoring and renaming cannot
make them pass or fail spuriously.

## Commands

| command | what it does |
|---|---|
| `setup` | browser + offline copy. Run once |
| `play` | interactive run in the terminal |
| `bot` | runs a bot (`--bot`, `--runs`, `--seed`) |
| `api` | HTTP JSON server |
| `bench` | run the 50-seed benchmark and produce a submittable result |
| `stats` | summary of recorded runs (`-d` explains the columns) |
| `mirror --phase verify` | check the local copy is not missing anything |
| `mirror` | rebuild the offline copy (after a game update) |

---

## Notes

The game is somebody else's fan project and asks not to be mistaken for an
official one. With the local copy, traffic to them is zero: downloaded once, then
never again.

The game's filename carries a content hash, so it **changes with every update**:
if things break one day, run `uv run pokelike mirror`.

Internals, pitfalls and how it is put together: [CLAUDE.md](CLAUDE.md).
