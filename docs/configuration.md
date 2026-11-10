# UGCW Battle AI — Configuration guide (config.json)

Version 0.1.3-beta · 2026-11-10

## Before you edit

All server settings are in `server/config.json`, read each time `planner_server.py` starts: stop the server, edit, restart.

- **Strict JSON**: double quotes, a comma between two settings but not after the last one, `true` / `false` / `null` in lower case. A syntax error stops the server from starting; the console shows the faulty line.
- **Defaults**: a setting or a block missing from the file takes its default value, so you can keep only what you change. Exception: the sub-block `scale.large` is replaced as a whole; copy it in full if you change it.
- **Units**: distances are in game units (a brigade in line is about 70 to 200 wide; fire range is about 400 to 500). Durations ending in `_s` are seconds, `_minutes` battle minutes. Morale, stamina and strength go from 0 to 1. Thresholds counted in men are proportional to the AI's army: the value in men is only a floor, useful in small battles.
- **Doctrine in plain text**: `strategy.md` (tactics) and `game_rules.md` (rules) can be edited freely too; they are re-read every turn, without restarting.
- **Be careful**: change one or two settings at a time, then compare the battle reports (`reports/`) and the scoreboard.

## Model and execution

These settings choose the model in command and whether its orders are really sent to the game.

| Setting | Default | Effect | When to change it |
| --- | --- | --- | --- |
| `backend` | `claude_code` | Model used: `claude_code` (Claude through the Claude Code command line, Pro or Max subscription), `ollama` (local model), `openai_compatible` (LM Studio, vLLM, any compatible API) | Depending on the model you have |
| `dry_run` | `true` in the zip | `true`: orders are shown and logged but not sent, reflexes stay off. `false`: the AI plays | `true` for a first try, `false` to play |
| `max_orders_per_cycle` | 60 | Maximum number of orders accepted per turn | Rarely; lower for a calmer AI |
| `verbose` | `true` | Details of orders and corrections in the console | `false` for a shorter console |
| `claude_code.model` | `sonnet` | Claude model (`sonnet`, `opus`, `haiku`) | `opus`: better analysis, slower and more expensive; `haiku`: fast and cheap, weaker analysis |
| `claude_code.effort` | `null` | Model reasoning level (`null` = Claude Code's default) | Try `medium` or `low` to cut cost and waiting, compare on the scoreboard |
| `claude_code.timeout_s` | 150 | Longest wait for an answer; after it the game resumes without orders | Raise with `opus` or a slow connection |
| `ollama.model` | `gemma4:12b` | Local Ollama model | Depending on your graphics card; a model that is too small follows the rules poorly |
| `ollama.num_ctx` | 16384 | Context size in tokens | Raise (32768) for large battles if memory allows |
| `ollama.temperature` | 0.2 | Randomness of the answers | 0.1 to 0.3; higher = less consistent decisions |
| `openai_compatible.base_url`, `model`, `api_key` | local server | Address, model and key of an OpenAI-compatible API | For LM Studio, your own server or an online service |

Only Claude has been tested in real battles. Local models work technically but follow the long rules less well.

## Turn pace and cost

The number of turns sets both how reactive the AI is and how many tokens it uses: each turn is one model call. The game is paused while the AI thinks.

| Setting | Default | Effect | When to change it |
| --- | --- | --- | --- |
| `timing.approach_interval_s` | 120 | Interval between two turns while no enemy is in sight | Higher for long approaches |
| `timing.closing_interval_s` | 60 | Interval when the enemy is in sight but far | Rarely |
| `timing.engaged_interval_s` | 60 | Interval in contact when the plugin's reflexes are off | 45 for a more reactive AI (more expensive) |
| `reflexes.engaged_interval_s` | 90 | Interval in contact when the reflexes run (they handle emergencies between turns) | 60 for more model control, 120 to save tokens |
| `timing.contact_distance` | 600 | Distance at which the battle counts as "in contact" | Rarely |
| `economy.skip_quiet_turns` | `true` | Skips the model call when nothing important changed; the server's automatic behaviours still run | `false` if the AI seems slow to react |
| `economy.morale_drop` | 0.3 | A morale drop this large on one unit forces a call (smaller drops are handled by the server: pull-backs, replacements) | 0.2 for a closer watch |
| `economy.new_enemy_men`, `new_enemy_share` | 1200, 0.04 | Newly seen enemy forces worth a call: about a brigade, or 4 % of the AI army (artillery counts double) | Lower to react to every new unit |
| `economy.max_consecutive_skips` | 2 | Quiet turns in a row at most | 1 for more model control |
| `economy.loss_men` | 100 | Floor of the losses since the last turn that force a call. The real threshold is the larger of this floor and `economy.loss_share` (0.01) × the AI's army | Rarely: the threshold already grows with the army. `loss_share` at 0.02 to skip more turns |
| `economy.max_gap_s` | 330 | Never longer than this (battle seconds) without calling the model | 150 for more model control |
| `scale.small.detail_radius`, `route_radius` | 1500, 800 | Short battles: units (not batteries) farther than 1500 from every enemy get a short line; ground towards the enemy only within 800 | Larger for more detail |
| `economy.static_roster` | `true` | The brigades' fixed equipment is sent only once per battle (cached) | Keep on |
| `economy.log_usage` | `true` | Shows the tokens of each call and the total in the report | Keep on to follow the cost |
| `scale.large_threshold` | 40 | Number of your combat units from which the battle is "large" and the prompt is compacted | Lower (30) if large battles cost too much |
| `scale.force` | `null` | Forces `"small"` or `"large"` | `"large"` to always save tokens |
| `scale.large.detail_radius` | 1200 | In a large battle, your units farther than this from every enemy get a short line only | Lower = fewer tokens, less detail |

Intervals are counted on the plugin's clock, which runs about 1.9 times slower than the battle clock shown in the reports: a 60-second setting gives about 114 battle seconds between two turns (measured at Shiloh on 2026-11-10). For reference, a 25-brigade battle used about 25,000 input tokens per call (13,600 of them read from the cache) and 640 answer tokens, for 30 calls in 74 minutes.

## Overall strategy

Three blocks set the AI's character: `plan` chooses to attack, defend or pause; `assault` leads the assault on the objective; `relief` pulls back broken brigades and commits the reserve.

### Doctrine (`doctrine`): one knob for the general's temper

| Setting | Default | Effect | When to change it |
| --- | --- | --- | --- |
| `doctrine.aggressiveness` | `null` | From 0 (cautious) to 1 (reckless). When set, it overrides at once: minimum attack ratio, stop-loss, staging time, launch share and latest launch minute, assault abort, retreat morale, charge target morale, charges per turn, and the answer to fire a unit cannot return (see `reflexes.unseen`). `null` keeps the individual settings below (balanced answer to fire) | 0.8 for an aggressive general, 0.3 for a careful one |

### Plan (`plan`)

| Setting | Default | Effect | When to change it |
| --- | --- | --- | --- |
| `attack_by_default` | `true` | If the player holds the objective the AI needs, it attacks by default | `false` for a defensive AI that only attacks with a clear superiority |
| `min_attack_ratio` | 0.7 | Minimum force ratio to attack at once | Lower = bolder, higher = more careful |
| `build_up_minutes` | 25 | Below that ratio, minutes of preparation in contact before attacking anyway | Shorter = more aggressive |
| `attack_ratio` | 1.25 | Ratio from which the AI considers itself clearly superior | Rarely |
| `stop_loss_ratio` | 1.6 | Pause if the AI loses more than 1.6 times the enemy's losses over 10 minutes | Lower = more careful, higher = more stubborn |
| `stop_loss_min` | 100 | Floor of the losses over 10 minutes that trigger the pause. The real threshold is the larger of this floor and `stop_loss_share` (0.01) × the men of the AI's army, reinforcements included | Rarely |
| `stop_loss_hold_s` | 480 | Shortest length of the pause | Shorter if the AI seems to hesitate |
| `stop_loss_min_contact` | 5 | Minutes of contact before the pause is possible | Rarely |
| `draw_ratio` | 0.8 | Below this ratio, the AI aims for a draw when victory is out of reach | Rarely |

### Assault (`assault`)

| Setting | Default | Effect | When to change it |
| --- | --- | --- | --- |
| `group_share`, `group_min`, `group_max` | 0.45, 2, 5 | Share of the infantry in the assault group, in brigades. The cap of 5 rises to 12 % of the infantry brigades in large armies (`group_max_share`) | Higher = heavier assault, thinner line |
| `launch_minutes` | 6 | Battle minute at which staging starts | Earlier = faster attack |
| `ready_share` | 0.7 | Share of the group that must have reached the staging area to launch | Lower = earlier but less concentrated assault |
| `strong_ratio`, `strong_ready_share` | 2.0, 0.5 | With a 2-to-1 superiority, launch as soon as half the group is in place | Lower = exploits a weakness faster |
| `launch_min_ratio` | 0.6 | Minimum strength of the group against the defenders to launch | Higher = safer but rarer assaults |
| `max_wait_s`, `latest_launch_minutes` | 900, 35 | Launch forced after 15 minutes of waiting or at minute 35 | Shorter for short phases (Shiloh) |
| `defender_memory_s` | 600 | Defenders seen in the last 10 minutes still count in the strength ratio when they hide in woods | Lower for a bolder launch |
| `approach_margin`, `cover_weight` | 250, 700 | A launched brigade further than its range + 250 from its target first marches to a firing position near it, preferring cover (wheat, woods' edge, fortifications); `cover_weight` is the march distance one point of cover × damage is worth | Higher `cover_weight` = more detours for cover |
| `charge_morale`, `charge_when_strong`, `max_charges_per_turn` | 0.5, false, 2 | Launched brigades charge a defender in reach whose morale fell under 0.5 (or a skirmisher/battery); with `charge_when_strong` (aggressive doctrine) any defender when the group is 2:1 up. Never through slow ground | Set by the doctrine |
| `charge_max_distance`, `charge_together` | 200, 2 | Launched brigades charge from 200 at most (whatever their own charge range), and at least 2 of them in the same turn unless the target is already shaken | Lower distance = safer charges |
| `charge_open_distance`, `charge_slow_distance`, `charge_slow_share` | 500, 200, 0.25 | Launched brigades charge from 500 at most over open ground, 200 when more than 25 % of the way is slow ground (woods, scrub, mud) | Lower for safer charges |
| `close_charge_strength` | 0.7 | At 200 or less a fresh brigade charges even alone, if it has at least 70 % of the target's men (standing there only trades volleys) | Higher for fewer close charges |
| `reserve_keep` | `null` | Aggressive doctrine (set to 1 at 0.7 and above): every fit infantry brigade but this many joins the assault group, nearest to the objective first | 0 for an all-in attack, 2 for a safer one |
| `launch_time_share` | 0.7 | Launch forced once only 70 % of the battle timer is left (read from the game's timer) | Higher = earlier attack on timed missions |
| `abort_loss_share` | 0.35 | The group is released after this share of losses | Higher = more stubborn assaults |
| `stage_angles` | 0, ±20, ±40 | Approach directions tried to avoid woods | Rarely |

### Pull-back, relief and reserve (`relief`)

| Setting | Default | Effect | When to change it |
| --- | --- | --- | --- |
| `retreat_morale`, `retreat_men` | 0.5, 0.4 | A brigade in contact below this morale or this share of its men falls back | Lower = the AI fights longer, risk of rout |
| `critical_morale` | 0.3 | Below this morale, retreat behind the line instead of a short fallback | Rarely |
| `rested_morale` | 0.65 | Morale to recover before going back into line | Higher = more careful rotation |
| `replace`, `max_replacements` | `true`, 2 | A fresh brigade takes the place of the one falling back: at most 2 per turn, or 5 % of the infantry brigades if more (`replacements_share`) | `false` to leave it to the model alone |
| `commit_minutes`, `commit_minutes_attack` | 20, 8 | Minute at which idle brigades far from the enemy move up to the line | Later to keep a reserve longer |
| `release_minutes` | 40 | One brigade stays in reserve until this minute | Later for a more careful AI |

### Synchronised assaults and final charge (`final_charge`)

Two assaults of the same turn (two objectives, or one objective from two sides) launch together: the first one
ready waits for the other, unless the model says `"launch": "now"` or the deadline has come.

| Setting | Default | Effect | When to change it |
| --- | --- | --- | --- |
| `final_charge.enabled` | `true` | The last throw on the enemy-held objective at the end of the timer | `false` to keep the army as it is |
| `final_charge.minutes_left`, `charge_minutes_left` | 20, 12 | From 20 minutes left, every fresh brigade closes to charge distance of the defenders; all charge when 60 % are in reach (`ready_share`) or at 12 minutes left | Earlier for longer final fights |
| `final_charge.min_morale`, `keep_back` | 0.7, 1 | Only brigades at 0.7 morale or more take part; the farthest one stays back as the last reserve | 0.6 for a bigger charge |
| `final_charge.open_distance`, `slow_distance` | 500, 200 | Charge distance over open ground / through slow ground | |

### Cohesion (`cohesion`)

| Setting | Default | Effect | When to change it |
| --- | --- | --- | --- |
| `cohesion.enabled` | `true` | Keeps the army together: no lone brigade far from the army and from every objective | `false` to leave the model free |
| `cohesion.leash_friends`, `leash_objective` | 650, 800 | A brigade farther than 650 from any friendly infantry or artillery and 800 from every objective is brought back (falls back first if in contact); orders that would send it there are dropped. Skirmishers get twice the distance, scouting cavalry and artillery are exempt | Larger for a looser army |
| `cohesion.no_chase`, `chase_leash`, `chase_margin` | `true`, 450, 100 | Infantry may chase skirmishers or cavalry while it stays within 450 of friendly infantry or artillery. Farther, a chase of a target more than its range + 100 away stops; if the brigade is still under fire it walks back towards its friends, out of the shooter's reach (assault group members on the defenders excepted) | Larger `chase_leash` = longer pursuits |
| `assault.split_min_infantry` | 6 | With two objectives to take and at least 6 fit infantry brigades, the server's own choice is one assault on each | Higher to keep a single assault |

### Time as a share of the phase

With a battle timer, the server counts time as a share of the phase's whole time (time left + time already spent
in the mission, read from the game, so it stays right after loading a saved battle): TEMPO, the assault deadline
(`assault.launch_time_share`, share of the time LEFT) and reserve commits (`relief.commit_share` 0.3,
`commit_share_attack` 0.12). Without a timer the minute settings (`latest_launch_minutes`, `commit_minutes`) apply.

### Routes (`routes`)

| Setting | Default | Effect | When to change it |
| --- | --- | --- | --- |
| `routes.enabled` | `true` | Moves longer than `min_distance` (500) are sent as a route of waypoints along the fastest ground (game tooltips speeds), like a path drawn with the mouse; at each bend the brigade faces the next leg | `false` to send straight moves |
| `routes.min_gain` | 0.10 | The route is used only when at least 10 % faster than the straight line (always for units outside the playing field) | Higher = fewer detours |
| `routes.road_preference` | 0.85 | Cost factor of roads and bridges: below 1 the route prefers them | 0.7 to stick to roads more |
| `routes.max_waypoints`, `max_routes_per_turn` | 8, 12 | Limits per move and per turn | Rarely |

## Arms and units

These blocks set what the server does by itself for each arm. Each block has an `enabled` switch: `false` leaves that arm entirely to the model.

| Block and setting | Default | Effect | When to change it |
| --- | --- | --- | --- |
| `ranges.fire`, `ranges.charge` | 500, 500 | Default fire and charge ranges; each unit's own range, read in the game, comes first (`use_unit_charge`) | If your mod changes the ranges |
| `line.spacing`, `line.max_spacing` | 70, 150 | Base spacing between brigades of the line (widened to the real width of the brigades) | Larger if units get in each other's way |
| `line.standoff` | 360 | Planned distance of the line from the enemy before contact | Lower = more aggressive line |
| `engage.max_per_turn`, `max_charges` | 4, 2 | Orders and charges added per turn to units left idle; these floors rise to 6 % and 3 % of your combat units (`per_turn_share`, `charges_share`) | 0 charges for an AI that only charges when the model decides |
| `engage.charge_target_morale` | 0.5 | Automatic charge only on a target below this morale | Lower = safer and rarer charges |
| `engage.reserve_share` | 0.2 | Share of brigades the automatic behaviours keep in reserve | Higher = more careful AI |
| `ammo.canister_range` | 500 | Distance at which batteries switch to canister (Rebalance mod range) | 300 without the Rebalance mod |
| `guard.enabled`, `use_fallback` | `true`, `true` | A battery left without infantry cover steps back | `false` for more exposed batteries |
| `battery.advance_share` | 0.85 | Smoothbore guns move up to this share of their range | Lower = guns further back |
| `supply.need_infantry`, `need_artillery` | 0.35, 0.5 | Ammunition level below which a wagon is sent | Higher = more preventive supply |
| `supply.safe_distance`, `path_clear`, `max_trip` | 450, 450, 1500 | Safety distance of the wagon and of its route from known enemies, longest trip | Higher = safer but less useful wagons |
| `cavalry.recon_minutes`, `recon_units` | 12, 1 | Time and number of cavalry brigades allowed to scout at the start | 0 to keep all the cavalry in reserve |
| `cavalry.scout_words` | scout, recon, vision… | Words in a perk name that mark a scouting brigade, used only for perks whose effects are not in the perk bonus files (base game, other mods); with J&P Rebalance the effects decide (Spotting / Stealth up) | Add the scouting perk names of your mod |
| `cavalry.ride_auto` | `true` | Automatic cavalry charges on isolated skirmishers | `false` if the cavalry wears out too fast |
| `cavalry.ride_auto_max`, `ride_auto_window_s` | 2, 600 | At most 2 automatic charges per brigade every 10 minutes | 1 to spare the cavalry |
| `cavalry.ride_woods_clear` | 250 | No automatic charge on a target closer than this to woods | Higher against players who hide skirmishers |
| `generals.auto_follow` | `true` | The general follows his brigades to keep them inside his command radius | `false` to leave generals to the model |
| `generals.safe_distance`, `danger_distance` | 650, 450 | Minimum distance of the general from enemies; immediate retreat below the second | Higher to protect generals more |

## Reflexes, terrain and perks

Reflexes act in the game between two turns, without calling the model: they cost no tokens. They need the 0.1.3-beta DLL and stay off in `dry_run`.

| Block and setting | Default | Effect | When to change it |
| --- | --- | --- | --- |
| `reflexes.enabled` | `true` | Turns the plugin's reflexes on | `false` for an AI that only reacts at the model's turns |
| `reflexes.face`, `face_radius` | `true`, 350 | A halted unit threatened on its flank or rear within 350 turns to face it | Larger = earlier reaction to outflanking |
| `reflexes.brace`, `brace_radius` | `true`, 250 | A charged unit stops and fires; a fresh neighbour counter-charges an enemy locked in melee | `false` if counter-charges feel too strong |
| `reflexes.safety` | `true` | Battery to canister then steps back, wagon and general move away, emergency fallback below 0.3 morale | Keep on |
| `reflexes.panic_morale` | 0.3 | Morale below which a unit in contact falls back at once | Lower = more stubborn units |
| `reflexes.*_cooldown_s` | 15 to 20 | Delay before the same reflex plays again on the same unit | Longer if units fidget too much |
| `terrain_rules.charge_max_slow_share` | 0.4 | A charge whose path is more than 40 % slow ground becomes an attack | Higher = more risky charges |
| `terrain_rules.charge_max_effective` | 1.3 | A charge too long once counted at real speed becomes an attack | Higher = charges from further away |
| `terrain_rules.open_ground_for` | Artillery, Supply | Units whose destination is moved out of woods | Add `Cavalry` to keep cavalry out of woods |
| `reflexes.unseen` | `true` | Any unit (infantry, skirmishers, cavalry, artillery, wagons) losing men while no visible enemy stands within its own fire range — shooters hidden in woods or wheat, camouflaged by a perk, or out-ranging it — reacts by the general's aggressiveness: aggressive (≥ 0.7) fresh infantry or mounted cavalry charges a skirmisher or shaken enemy in reach, fresh infantry and skirmishers advance on the shooters; balanced (0.4–0.7) fresh foot units close in on a visible enemy just out of range; careful (< 0.4), and any tired unit, artillery or wagon, opens the distance | `false` to let units stand under fire |
| `reflexes.unseen_aggressiveness` | `null` | Aggressiveness used for that answer only; `null` = `doctrine.aggressiveness`, else 0.5 (balanced) | Set it to make the answer to fire bolder or more careful than the rest of the doctrine |
| `terrain_rules.unseen_withdraw`, `unseen_advance_stop` | 250, 120 | Distance of the server's pull-back from the hiding place, or of the aggressive advance short of it | Larger withdraw for safer units |
| `terrain_rules.unseen_charge_reach`, `unseen_close_gap` | 400, 200 | Charge reach of the aggressive answer; how far beyond its range a visible enemy may stand for the balanced answer to close in | Lower for fewer charges and advances |
| `terrain_rules.cover_respond`, `cover_max_move`, `cover_min_gain` | true, 220, 0.4 | Idle infantry or skirmishers losing men while trading fire from open ground step to a better spot within 220 that keeps the enemy in range | `false` to keep units where the model put them |
| `reflexes.unseen_window_s`, `unseen_loss` | 60, 6 | The plugin sums a unit's losses over about 60 s, so slow attrition by skirmishers triggers the reflex too | Shorter window = only sharp losses |
| `terrain_rules.unseen_min_range`, `cavalry_withdraw` | 100, 400 | Units with a shorter range count as able to answer within 100; distance mounted cavalry pulls back | Rarely |
| `terrain_rules.unseen_min_loss` | 15 | Losses with no visible enemy that trigger the "UNSEEN FIRE" alert (floor; or 0.5 % of the unit's full strength, `unseen_min_share`) | Higher if the alert shows too often |
| `terrain.in_prompt`, `show_rules` | `true`, `true` | Terrain map and terrain effects (speed, cover, stealth) given to the model | Keep on |
| `terrain.overview_cols` | 60 | Detail of the map in the prompt | 40 to save a few hundred tokens (cached) |
| `perks.folder` | `perks/jp-rebalance-1.29.1` | Folder of the perk bonus files | Point it to a copy of `<game>/Mod/Rebalance/Data/` for another version of the mod |
| `perks.show_in_prompt` | `true` | Table of each perk's effects given to the model | `false` without the Rebalance mod |

## Display, missions and reports

These settings do not change how the AI fights: they set what you see and how battles are scored.

| Block and setting | Default | Effect | When to change it |
| --- | --- | --- | --- |
| `overlay.enabled` | `true` | Panel with the AI's reasoning on the left of the screen (F6 in game) | `false` to play without seeing what the AI thinks |
| `overlay.max_chars` | 260 | Longest text in the panel | Shorter if the panel is in the way |
| `overlay.show_ai_orders` | `false` | Shows the arrows the game draws for the AI's orders (where its brigades march, what they attack). Hidden by default: they give the AI's plan away | `true` for testing only |
| `assessment.enabled` | `true` | After-action review written by the model (`reports/assessment-*.md`), one more call per battle | `false` to save that call |
| `mission.objectives_only` | `[]` | List of objective names to take into account; the others are ignored | For a map whose scene holds objectives outside the playable area; keep empty otherwise |
| `mission.casualty_goal` | 1.05 | Casualty ratio aimed at when the game does not give the victory conditions | Rarely |
| `mission.player_rule` | hold all, 1.05 | Fallback victory rule if the mission conditions are not read | Rarely |
| `mission.trust_game_result` | `false` | Scores the battle from the mission conditions read in the game rather than from the game's result text | `true` if the scoreboard results look wrong |
| `posture.attack_ratio`, `defend_ratio` | 1.25, 0.8 | Fallback posture from the force ratio, used only without mission conditions | Rarely |
| `posture.stalemate_minutes` | 20 | Minutes without an objective changing hands before the stalemate alert | Shorter to push the AI to renew the attack |
| `scoring.victory`, `draw`, `defeat` | 3, 1, 0 | Scoreboard points per result | For your own comparison scale |
| `scoring.min_casualties` | 25 | Below this total of losses, the battle counts as "no fighting" | Rarely |

Each battle writes a text and a JSON report in `reports/` (result, losses, tokens used, battle size) and a line in the per-model scoreboard. Send these files with the log `logs/battle-*.jsonl` to report a problem.

## Player profiles

Copy the blocks of a profile into your `config.json`, replacing the settings of the same name; the settings not listed keep their value. These are starting points, not tested in battle: adjust after a few games.

### Aggressive AI (experienced players)

Attacks earlier, in greater mass, and insists longer under fire.

```
"plan": {"min_attack_ratio": 0.5, "build_up_minutes": 15, "stop_loss_ratio": 2.2},
"assault": {"group_share": 0.55, "ready_share": 0.5, "latest_launch_minutes": 25, "abort_loss_share": 0.45},
"relief": {"retreat_morale": 0.4, "commit_minutes_attack": 5},
"engage": {"max_charges": 3, "charge_target_morale": 0.6}
```

### Careful AI (solid defence, few risks)

Attacks only with the advantage, falls back early and keeps a reserve.

```
"plan": {"min_attack_ratio": 1.0, "build_up_minutes": 35, "stop_loss_ratio": 1.3},
"assault": {"launch_min_ratio": 0.9, "abort_loss_share": 0.25},
"relief": {"retreat_morale": 0.55, "rested_morale": 0.75, "release_minutes": 60},
"engage": {"max_charges": 1, "reserve_share": 0.3}
```

### Very reactive AI (intense fighting, more expensive)

More turns in contact and no skipped turn.

```
"timing": {"engaged_interval_s": 45},
"reflexes": {"engaged_interval_s": 60, "face_radius": 450},
"economy": {"skip_quiet_turns": false}
```

### Token-saving AI

Fewer turns, compact prompt and no after-action review; the analysis is a little less fine.

```
"reflexes": {"engaged_interval_s": 120},
"economy": {"morale_drop": 0.2, "loss_share": 0.02},
"scale": {"force": "large"},
"assessment": {"enabled": false},
"claude_code": {"effort": "low"}
```

### Short phases (Shiloh and chained missions)

The phase objective must fall fast; the AI launches its assault without waiting for its reinforcements.

```
"assault": {"launch_minutes": 3, "strong_ready_share": 0.4, "latest_launch_minutes": 20, "max_wait_s": 480}
```

### Easier opponent (beginners)

Later and lighter assaults, fewer charges and counter-charges.

```
"assault": {"group_share": 0.3, "latest_launch_minutes": 50},
"engage": {"max_charges": 1},
"reflexes": {"brace": false},
"claude_code": {"model": "haiku"}
```

### Model alone (testing the LLM without server help)

Switches the automatic behaviours off: the model decides everything. Clearly weaker in our tests; keep it for model comparisons.

```
"engage": {"enabled": false},
"relief": {"enabled": false},
"assault": {"enabled": false},
"cavalry": {"ride_auto": false},
"generals": {"auto_follow": false},
"reflexes": {"enabled": false}
```
