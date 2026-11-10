# UGCW Battle AI

An unofficial fan mod for **Ultimate General: Civil War** that hands the computer-controlled army to a
large language model (Claude by default). You play one side; the model commands the other. Every few
seconds of play the game pauses, the battlefield is sent to a small Python server, the model gives its
orders, the server checks them against the rules of the game, and the game resumes.

It follows the design of [rome-battle-ai](https://github.com/Cegli865/rome-battle-ai) by Cegli865
(Total War: ROME REMASTERED), adapted to Ultimate General: Civil War (Unity 5.4.4, Mono).

> **Status: beta (v0.1.2-beta).** Tested on a few missions, one battle at a time, on Windows.
> Expect rough edges. Bug reports with the server console text and the files in `logs/` and
> `reports/` are welcome.

## How it works

| Part | Folder | What it does |
|---|---|---|
| Game plugin (C#) | [`plugin/`](plugin) | 11 classes in the `UgcwAi` namespace compiled into the game's `Assembly-CSharp.dll` with dnSpy. Reads the battlefield, sends it over TCP (127.0.0.1:8765), executes the orders, shows the AI's reasoning in game (F6). |
| Planner server (Python) | [`server/`](server) | Standard library only. Builds the prompts, calls the model, validates the orders, runs the server-side doctrine (morale relief, assault on objectives, artillery and supply discipline), writes battle reports and an after-action review. |
| Doctrine | [`server/game_rules.md`](server/game_rules.md), [`server/strategy.md`](server/strategy.md) | Plain-text rules and tactics given to the model. Edit them freely: they are re-read at every planning pause. |

Main features: mission goals and briefing read from the game, an attack/defend/trade plan computed from
them, an assault plan on the objective, front line and fire-lane management, artillery (limbering,
canister, protection), supply wagons with safe routes, cavalry roles (reserve, flanks, scouting, riding
down skirmishers), battle reports with a scoreboard per model, and token-saving options for short and
large battles. Details: [`docs/user-guide.txt`](docs/user-guide.txt).

## Requirements

- Ultimate General: Civil War, Mono build (Unity 5.4.4), on Windows.
- Python 3.8 or newer (no packages to install).
- A model: Claude through the Claude Code command line (Claude Pro or Max subscription), a local model
  with Ollama, or any OpenAI-compatible server.
- dnSpy to build the plugin into your own copy of the game DLL.

## Install

1. **Plugin.** Back up `Assembly-CSharp.dll` from `<game>\<game name>_Data\Managed`, then follow
   [`plugin/INSTALL.txt`](plugin/INSTALL.txt): add the 11 classes with dnSpy and one line,
   `UgcwAi.Bootstrap.Init();`, at the start of `BattleLogic.Run()`, then *File > Save Module*.
2. **Server.** Copy `server/` anywhere (for example `C:\ugcw-ai`) and run `python planner_server.py`.
3. **Model.** Set `"backend"` in `server/config.json` (`claude_code`, `ollama` or `openai_compatible`).
   `"dry_run": true` logs the orders without sending them; set it to `false` to let the AI play.
4. Start the game and a battle. The game log shows `[UgcwAi] loads`; F6 toggles the reasoning panel.

No game file is part of this repository. A ready-made modded DLL, if one is published, goes in the
Releases, never in the git tree, and only fits the game version it was built from.

## Configuration

Everything is in [`server/config.json`](server/config.json): backend and model, planning intervals,
ranges, the server-side doctrine blocks (`plan`, `assault`, `relief`, `guard`, `engage`, `ammo`,
`supply`, `battery`, `cavalry`), the in-game overlay, and token savings (`economy`, `scale`).
See [`docs/token-usage.md`](docs/token-usage.md) for the estimated cost of short and large battles.

## Tests

```
python -m unittest discover -s tests
```

The smoke tests build prompts and run the order checks on synthetic battles; they need neither the
game nor a model.

## Contributing

Issues and pull requests are welcome: bug fixes, better doctrine in `strategy.md` and `game_rules.md`,
support for more models, more game data read by the plugin. Attach the battle log (`logs/*.jsonl`) to
bug reports. Code comments and log lines are in English. Never commit game files.

## Credits and license

- Design and approach: [rome-battle-ai](https://github.com/Cegli865/rome-battle-ai) by Cegli865 (MIT).
- Ultimate General: Civil War is a game by Game-Labs. This project is not affiliated with Game-Labs.
- Some players use it together with the Rebalance mod; the plugin works with or without it.
- Released under the [MIT License](LICENSE).
