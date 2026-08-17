# Leaderboard

Anyone can submit a bot. It can be whatever you like: hand-written rules, a
prompt and an LLM, a trained RL policy, a search, a mix.

You do **not** need write access to this repo, and you should not expect any.
The way in is a fork and a pull request, and the steps are spelled out below.

## What makes results comparable

Two things, and both are recorded automatically.

**The same runs.** Luck dominates a single game of pokelike. The benchmark plays
a fixed list of 50 seeds, so every bot faces the identical maps, starters and
encounters. Comparing bots on different seeds mostly measures who drew the nicer
maps.

**The same game.** The upstream game gets updated and its filename carries a
content hash. A score from before an update is not comparable with one from
after, so every entry records the sha256 of the bundle that was played.

## What a submission is

One folder, built for you by the `bench` command. You never assemble it by hand.

```
leaderboard/
├── index.json                      generated from the entries
└── entries/
    └── dyna-q-v1-a3f21c/           one folder per submission
        ├── submission.json           metadata, per-run results, artifact manifest
        ├── bot.py                    a copy of the bot that actually ran
        └── artifacts/
            ├── manifest.json         what each file is, with its sha256
            ├── weights.json          whatever your bot declared
            └── config.json
```

The folder name is `<name>-<hash>`, where the hash covers the bot source, the
artifacts and the seed list. That makes an entry immutable by construction:
resubmitting a tweaked bot creates a new folder instead of quietly overwriting
the old result, and nobody can swap the weights while keeping the score.

## Declaring your artifacts

Your bot says what it needs archived, by implementing one optional method. If it
is not declared it is not archived, so nothing depends on remembering to copy a
file.

```python
from pokelike.leaderboard import Artifact

class MyBot(Bot):
    def artifacts(self):
        return [
            Artifact(name="weights.json", kind="weights-json",
                     description="Q-table, 563 states, encoding v1",
                     path=self.table_path),
            Artifact(name="config.json", kind="config",
                     description="how it was trained",
                     data={"algorithm": "dyna-q", "episodes": 90}),
        ]
```

Content comes from exactly one of `path` (copy this file), `data` (serialise as
JSON) or `text` (write as-is).

| kind | for what |
|---|---|
| `weights-json` | a tabular policy small enough to live in the repo |
| `weights-file` | a local binary: npz, pt, safetensors |
| `weights-remote` | url + sha256 + how to load it, for anything large |
| `prompt` | the prompts of an LLM bot |
| `model-ref` | provider, model name, temperature, version |
| `config` | the hyperparameters it was trained with |
| `code-ref` | the git commit of the training code |
| `notes` | anything else worth keeping |

Files over 5 MB are refused: a git repository is not an artifact store. Upload
them to a GitHub release or Hugging Face and declare a `weights-remote` artifact
with the url and its sha256 instead.

**A submission must be self-contained.** For a trained policy that means the
state encoding lives inside the bot file, frozen next to the weights, rather than
imported from `experiments/`. Otherwise improving the training code would silently
change what every past submission means.
[`bot/dyna_q.py`](../src/pokelike/bot/dyna_q.py) does exactly this and is meant
to be read as the worked example.

## How to submit

**1. Fork.** Press *Fork* at the top right of the GitHub page. You now have your
own copy you can push to freely.

**2. Clone it and set it up.**

```bash
git clone https://github.com/YOUR-NAME/pokelike.xyz.bot
cd pokelike.xyz.bot
uv sync
uv run pokelike setup
```

**3. Write your bot** in `src/pokelike/bot/`, register it in `AVAILABLE`, and run
the benchmark. If you are not sure what your bot gets to look at, run
`uv run pokelike schema` or read [docs/STATE.md](../docs/STATE.md).

```bash
uv run pokelike bench --bot yourbot \
    --name "your-bot-name" \
    --author "your-github-handle" \
    --category rules \
    --description "one line on how it works"
```

It plays the 50 standard seeds, builds your entry folder, and prints the exact
git commands to finish. A full benchmark takes about 15 minutes for a fast bot;
use `--runs 10` while developing, but submit the full 50.

**4. Commit, push, open the PR.** The command tells you what to `git add`. GitHub
will offer to open the pull request from your new branch.

If any of this goes wrong, open an issue and paste your `submission.json` into
it. A submission that arrives awkwardly is better than one that does not arrive.

## Categories

Scored separately on purpose. A bot calling a frontier model has a budget a
hand-written heuristic does not, and one table would tell you nothing.

**`rules`** — deterministic logic, no learning, no external calls. Fully
reproducible: anyone can re-run your exact result.

**`rl`** — a trained policy. Ship the weights and the encoding version.

**`llm`** — a prompt and a model. Ship the prompts and say which model in
`description`. Never your API key.

**`human`** — you played it yourself with `pokelike play`. Genuinely interesting:
nobody knows yet what a good human score looks like.

## The honest part about verification

Results are self-reported. Nobody can run everyone else's bot, least of all one
that needs somebody's paid API key.

What makes that acceptable is that **rules** and **rl** entries are
self-contained: anyone can re-run them with one command and get the same numbers,
because the environment is deterministic. A result that cannot be reproduced will
show up as such.

**`llm` entries are not independently reproducible** and are marked that way.
Providers change models behind a fixed name, sampling is stochastic, and you can
pin neither. Treat those numbers as indicative. For a reproducible LLM result,
run a local model at temperature 0 and say which one.

## Reading the table

```bash
uv run pokelike leaderboard
```

Look at `stdev` as well as the mean. Variance here is large, and a bot that wins
on average while occasionally collapsing is a different animal from one that is
steadily mediocre. `done` is the one that matters most in the long run: as of now
nothing has finished a full run.
