# CLAUDE.md — pokelike.xyz.bot

Notes for agents working on this repo.

**Read [README.md](README.md) as well.** It explains what the project does, how
it is installed and how it is used — everything you need to guide a user. This
file only adds what someone *changing* the code needs: internals, pitfalls, and
the reasoning behind decisions that look odd.

## What this is

An environment for letting bots play [pokelike.xyz](https://pokelike.xyz/), a
Pokémon roguelike that runs entirely in the browser. The game has no backend: all
its logic is in one obfuscated JavaScript bundle. We run it in headless Chromium
and talk to its global functions.

## Commands

```bash
uv sync                          # environment
uv run pokelike setup            # browser + offline copy (once)
uv run pokelike play --seed 42   # interactive run
uv run pokelike bot --runs 5     # the random bot
uv run pokelike stats -d         # summary, with the columns explained
uv run pokelike schema           # what a bot receives (regenerates docs/STATE.md with --markdown)
uv run pokelike bot -d --runs 1  # log every decision, for any bot
uv run pytest                    # full suite, ~3 minutes
uv run pytest -m "not slow"      # fast tests only, no browser

uv run pokelike bench --bot random --runs 10   # the standard benchmark, 50 seeds

uv run python -m experiments.sarsa_lambda.train --episodes 300      # train a policy
uv run python -m experiments.sarsa_lambda.evaluate --seed0 40000    # vs random, paired
uv run python -m experiments.sarsa_lambda.ablation --workers 4      # feature variants,
uv run python -m experiments.sarsa_lambda.ablation --list           # trained in parallel
```

## Architecture

```
site/                    the downloaded game (gitignored, ~130 MB)
src/pokelike/
├── core/                SHARED LOGIC — the only part that knows how to play
│   ├── bridge.js          injected into the page: observes and acts
│   ├── browser.py         Playwright headless, pinned seed, flattened animations
│   ├── game.py            class Game: reset/state/step/score
│   └── render.py          ASCII map, team, actions
├── bot/                 WHOEVER DECIDES THE MOVES
│   ├── base.py            abstract Bot: only choose() is required
│   ├── random_bot.py      the baseline
│   ├── llm.py             self-contained: prompts + tools + HTTP
│   ├── dyna_q.py          a trained policy; the worked example of a submission
│   └── sarsa.py           linear SARSA(λ); currently top of the leaderboard
├── assets/
│   ├── mirror.py          builds site/ in five phases
│   └── server.py          serves site/ from disk
├── stats/registry.py    SQLite in stats/runs.db
├── bench.py             the standard 50-seed benchmark
├── runner.py            play_run(): the one loop that plays a run with a bot
├── schema.py            what a bot receives, described from a live state
├── leaderboard.py       submission folders, artifacts, index
└── interfaces/          how something outside drives the game
    ├── cli/main.py        a human, in a terminal
    └── api/server.py      a program, over HTTP
experiments/             attempts at a better bot, outside the package
├── env/                   the game as an RL problem: environment, rewards, encoding
├── dyna_q/                tabular RL on that MDP: agent, train, evaluate
└── llm/                   prompt strategies compared on identical seeds
leaderboard/             submissions, their weights, and how to submit
tests/                   golden fingerprints + unit tests
tools/deobfuscate.py     makes the bundle readable (needs node)
```

`interfaces/` and `bot/` contain no game logic: they all go through `Game`'s four
methods. If you feel like putting a game rule in the CLI, it belongs in `core`.

Decision logging lives in `runner.play_run` for the same reason: recorded once,
in the shared loop, so a log means the same thing whatever is playing. Bots add
at most one line through the optional `explain()` hook.

`bot/` is deliberately not under `interfaces/`. The interfaces are entry points —
something outside drives the game through them. A bot is an extension point: you
write one, and the interfaces run it. Filing the concrete bots (random, llm,
dyna_q) under `interfaces/` would blur that.

## Talking to the game

The engine exposes everything as page globals. The useful ones:

| global | use |
|---|---|
| `state` | full state: team, bag, map (a DAG), badges, `runSeed` |
| `getAccessibleNodes(state.map)` | legal map moves |
| `onNodeClick(node)` | take a move |
| `runBattle(...)` | pure battle simulator, no DOM |
| `getBestMove`, `calcDamage` | the game's own AI and damage formula |
| `finalizeRunScore`, `foldBattleIntoRunStats`, `newRunStats` | scoring |
| `seedRng`, `getRngSeed` | internal PRNG |

No pixels are looked at. Screenshots exist (`Game.screenshot`) but are for humans
only.

Actions come in two kinds: map moves go through `onNodeClick(node)` (a direct
call), other choices activate a DOM element because that is where the game binds
its handler.

**Team order is a third thing, and it is not an action.** Slot 0 leads the next
battle, so the order is a real decision, but reordering does not consume the
turn. It is exposed as its own verb — `Game.reorder(a, b)`, `Bot.rearrange()`,
`POST /reorder`, `w a b` in the REPL — and advertised in the state as
`can_reorder`. Folding it into `actions` would put fifteen swap pairs next to
the moves at every map node and make the turn count mean something else.

The engine binds it to a hand-rolled pointer drag on the team bar, which lives
outside every `.screen`, which is why `__pk_choices` never saw it. We do not
simulate the drag: under all of it the drop does exactly
`[team[a], team[b]] = [team[b], team[a]]` and re-renders, and the Elite Four
prep screen has its own drag that mutates the same `state.team`. So one
primitive covers both, with no dependence on coordinates or layout.

To explore the bundle: `python3 tools/deobfuscate.py site/js/bundle.*.js`. It
works out the obfuscator's internal names by itself, since they change with every
release.

## Real pitfalls

All of these were hit for real. Worth rereading before changing anything:

- **The site does not answer 404 for missing files**: it returns `index.html` with
  status 200. Without checking magic bytes the mirror fills with HTML dressed as
  `.png` (it happened: 6612 junk files). See `SIGNATURES` in `assets/mirror.py`.
- **Keep download concurrency low.** With 24 requests in flight the site cuts us
  off and *everything* fails silently, which is worse than being slow. The mirror
  runs at 6 and repairs missing files sequentially, from the exact list the
  verification produces by playing.
- **At game over the engine wipes `state`**: empty team, no badges. The
  end-of-run summary needs `Game.last_alive`, the last snapshot taken while the
  run was alive.
- **Never declare a local with the same name as a global you mean to replace** in
  `bridge.js`: you shadow it and rewrite the wrong copy. Symptom:
  `Assignment to constant variable` that has nothing to do with `const`.
- **Two Playwright sync instances cannot live in the same thread.** One `Game` per
  thread, full stop — this is why the API tests reuse the session-wide fixture.
- **The sync API is bound to its creating thread**, so `api/server.py` is
  single-threaded by necessity: `serve_forever()` must run on the thread that owns
  the game, or you get `greenlet.error: Cannot switch to a different thread`.
- **`maxTeamSize` is a high-water mark, not a limit.** The real limit is 6.
- **Non-usable items open an equip modal** which is not a `.screen`. Anything that
  only watches `.screen` elements gets stuck there forever.
- **The map is SVG**: nodes have no `.click()`.
- **Clearing localStorage makes the game re-run its tutorial every time.** We
  clear it in `INIT_SCRIPT` so no saved state leaks between runs, and the price
  is that the game greets a first-time player on every run. A human clicks the
  callouts away; a bot never does, so they stack up, one per team slot, over the
  map and the battle screen alike. `HIDE_TUTORIAL_CSS` in `browser.py` hides
  them. Purely cosmetic — they sit outside every `.screen` so they were never
  offered as actions, and actions are applied by dispatching an event on the
  element rather than clicking a coordinate, so they never intercepted anything
  either.
- **Seeds are 32-bit.** `(cfg.seed >>> 0) || 1`, so seed 0 is seed 1 and seed
  N is seed N + 2**32. `normalise_seed` rejects anything outside the range
  rather than truncating, because above 2**53 Python's `& 0xFFFFFFFF` and JS's
  `>>> 0` disagree: there is no truncation that records the seed that ran. It
  used to surface as an `OverflowError` from SQLite *after* a full run.
- **The bundle filename carries a content hash** and changes with every game
  release. If something breaks all at once, first thing: `pokelike mirror`.
- **Not every failure should be recovered from.** The LLM bot falls back to a
  safe choice when a call fails, which is right for a timeout and wrong for a
  401: a bad token used to produce a whole run of fallbacks that looked like a
  model playing badly, and `bench` would have filed it on the leaderboard as an
  `llm` entry no model ever played. Auth and model-not-found now raise
  `LLMConfigError` and stop the run.
- **`playwright install` exits 0 even when the host is missing libraries.** It
  only warns. Trusting the exit code made `setup` report success on a Raspberry
  Pi while every later command died with a stack trace, so setup now launches
  the browser to check. Never infer "it works" from an installer's exit code.
- **The engine's score formula is a Battle Tower formula.** Two of its six terms
  are dead in Story mode: `mapsCleared` is incremented in exactly one place in
  the bundle, inside `bumpEndlessCounters()`, which only runs on the endless
  path; and `winBonus` needs the whole League beaten. What is left is
  `5·KO − 10·faints`, and badges do not appear at all — which is how a run with
  three badges scores −5. Rank Story runs by **badges**, and see
  `experiments/env/rewards.py` before designing any objective on top of it.

## Scoring

The engine already knows how to compute it (`finalizeRunScore`) and how to count
(`foldBattleIntoRunStats`), but it only wires the two together in Challenge mode:
the call site reads `state.challengeId && state.runStats && fold(...)`.

Forcing `challengeId` is the obvious shortcut and it is **wrong**: that flag
changes the rules, among other things raising the Elite Four's levels
(`challengeId ? Math.max(0, 10 + challengeEliteLevelMod) : 0`). So `bridge.js`
wraps `runBattle` and hands the result to the game's own counting function:
rules untouched, native counters.

Always compare with `points_no_time`. The time bonus depends on `Date.now()`,
which we freeze for determinism, so it sits pinned near 1000 and would drown out
everything else.

## Reproducibility

The run seed is `Date.now() ^ (Math.random() * 2**32)` and everything flows from
the engine's PRNG seeded with it. `browser.py` pins **both** in a script that runs
before the bundle, and caps `setTimeout` at 1 ms to flatten animations. Same seed
+ same actions = same run, score included.

A fresh browser context per run: reusing the page would stack another init script,
and another reseed, on every reset.

## Tests

The regression net lives in `tests/golden/runs.json`: recorded runs, replayed and
compared. The fingerprint holds **only engine data** — screen ids, node types,
Pokémon names, scores — never text we write ourselves. That is what let the whole
codebase be translated from Italian to English with proof that behaviour did not
move.

Regenerate it with `uv run python tests/record_golden.py` **only** when the game
itself has changed upstream and you have checked the new behaviour by hand.
Regenerating it to make a red test go green defeats the point.

## Performance

~1.5 decisions per second, ~14 s per run with a fast policy. Runs are independent:
to go faster, launch more processes, not more threads.

The LLM bot is far slower (one or more HTTP calls per decision) and burns roughly
30k tokens per run.

## Submissions

`leaderboard/` takes bots from anyone, via fork and pull request. Two rules that
are not obvious and matter:

- **A submission must be self-contained.** A trained policy freezes its state
  encoding inside the bot file rather than importing `experiments/env/encoding.py`,
  so improving the training code cannot silently change what past submissions
  mean. `bot/dyna_q.py` is the worked example.
- **The benchmark records the game bundle's sha256.** Scores from before and
  after an upstream game update are not comparable, and without the hash a
  leaderboard mixes them silently.

LLM entries are accepted but flagged as not independently reproducible:
providers change models behind a fixed name and sampling is stochastic.

## Secrets

LLM credentials are read **only** from `FW_ENDPOINT`, `FW_TOKEN`, `MODEL_ID`.
Never write them into code, comments, the README or the run registry. `stats/` is
gitignored.
