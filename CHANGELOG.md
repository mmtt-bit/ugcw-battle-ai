# Changelog

## 0.1.2-beta (2026-11-10)
- Short and large battles (`scale` in config.json): from 40 combat units the prompt is compacted (short
  lines for units far from the fight, enemy detail only near your units, capped lists, orders by id).

## 0.1.1-beta (2026-11-10)
- Token usage printed after every model call and totalled in the battle report.
- Fixed equipment of your brigades given once in the cached system prompt (YOUR BRIGADES roster).
- Repeated explanations moved to READING THE STATE in the system prompt.
- `game_rules.md` and `strategy.md` merged and cleaned up (outdated stop-loss and TRADE rules fixed,
  mission-specific notes removed).
- Quiet turns skipped: no model call when nothing changed that needs a decision.

## 0.1-beta (2026-11-09)
- First public beta: plugin (11 classes) and planner server.
- Mission goals and briefing read from the game; ATTACK / DEFEND / TRADE plan; attack by default when the
  player holds the objective the AI needs; assault plan with staging area, assault group and launch.
- Server-side doctrine: morale relief and replacement, reserve commitment, stop-loss, artillery guard,
  canister, limbering (forced unpack after failed tries), supply wagons with safe routes, cavalry roles and
  riding down skirmishers.
- Battle reports, scoreboard per model, after-action review, in-game reasoning panel (F6).
