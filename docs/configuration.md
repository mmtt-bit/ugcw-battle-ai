# UGCW Battle AI — Configuration guide (config.json)

Version 0.1.4-beta (unreleased) · 2026-11-11

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
| `fire.counter_battery`, `counter_battery_safe`, `counter_battery_repeat_s` | true, 350, 90 | WIP13: rifled batteries fire at enemy batteries in range when no enemy foot or horse is within 350 of them (WIP17: was 500) | false to leave targets to the model |
| `fire.counter_battery_smooth`, `counter_battery_safe_smooth` | true, 400 | WIP17: smoothbores duel too, unless enemy foot or horse is within 400 | false to keep smoothbores on infantry |
| `fire.counter_battery_override_beyond` | 800 | WIP17 (llm_plus): a rifled battery ordered at infantry or cavalry farther than this, with an enemy battery in range, fires at the battery | a large value to never change the model's target |
| `works.crossings`, `crossing_own`, `crossing_enemy`, `crossing_objective`, `crossing_lines` | true, 700, 1000, 2500, 6 | WIP17: CROSSINGS block (fords and bridges near an objective or the enemy, men on each side, nearest reserve) | false to drop the block |
| `works.fresh_morale`, `fresh_contact` | 0.7, 500 | WIP17: a reserve brigade in the CROSSINGS block: morale at least this, no enemy within this | |
| `works.fortifications`, `works_reach`, `works_lines` | true, 1200, 6 | WIP17: FORTIFICATIONS block (free field works near a held objective or a brigade; needs the WIP17 DLL) | false to drop the block |
| `relief.cover_retreat_morale`, `cover_terrains`, `cover_hold_objective` | 0.3, Forest/DenseForest/Fortifications, 800 | WIP13: on DEFEND/TRADE a brigade in cover is pulled back only under 0.3; the reserve commit leaves brigades in works, or woods within 800 of your objective | 0.5 for the old behaviour |
| `relief.rally_high_ground`, `rally_morale`, `rally_min`, `rally_max`, `rally_after_fallback` | true, 0.3, 300, 600, true | WIP13: a brigade under 0.3 moves to the highest ground 300-600 behind it (after its first critical fallback, or when out of contact) | false to switch off |
| `cohesion.support_isolated`, `support_min_morale`, `support_max_distance`, `support_gap`, `support_hold_morale` | true, 0.7, 1500, 170, 0.5 | WIP13: on a defensive plan an isolated brigade in cover, or in contact with morale 0.5+, stays and the nearest free healthy brigade within 1500 is sent 170 beside it | false for the old recall |
| `engage.pair_charge`, `pair_min_stars`, `pair_distance`, `pair_min_morale`, `pair_min_stamina`, `pair_men_ratio`, `pair_fort_ratio`, `pair_max_support` | true, 2, 500, 0.8, 0.7, 1.3, 2.0, 1 | WIP13: two veteran brigades charge one enemy brigade together | false to switch off |
| `exchange.sector`, `window_s`, `min_losses`, `losing_ratio` | 600, 600, 200, 2.0 | WIP14: a 600 m sector where you lost 200+ men and twice the enemy losses seen in the last 10 min is LOSING (shown to the model) | Higher ratio = fewer sectors flagged |
| `exchange.cover_search`, `better_cover`, `pull_back`, `pull_max_per_turn` | 800, 0.8, true, 3 | WIP14: in a losing sector on open ground with cover (damage factor 0.8x or less) within 800 behind, no replacement / reserve / objective post goes in and its brigades go back to that cover | `pull_back` false to keep only the blocking |
| `exchange.flank_watch`, `end_margin`, `end_depth`, `battery_threat`, `battery_guard` | true, 200, 700, 800, 300 | WIP14: FLANK THREAT = enemy foot/horse 200+ beyond an end of your line (up to 700 deep), or within 800 of a battery with no steady brigade within 300 | |
| `exchange.refuse_flank`, `refuse_min_morale`, `refuse_max_distance`, `battery_fallback`, `battery_fallback_min` | true, 0.7, 1500, true, 350 | WIP14: the nearest free healthy brigade refuses the flank; a lone battery whose threat is 350+ away falls back behind the infantry | false to switch off |
| `llm_plus` | `true` in the zip | WIP15. The model commands; the server adds only counter-battery fire, the rally of brigades under 0.3 on high ground, lone batteries pulled back behind the infantry, battery unpacking, and the plugin's facing / bracing / safety / cavalry reflexes (no unseen-fire reflex). Scored apart as "<model> (llm plus)". `llm_only` wins when both are true | `false` (and `llm_only` false) for the full system with all the staff work |
| `engage.charge_zone_check` | true | WIP15: the server's automatic charges go in only on the zone verdict GO (600 m zone: men at least equal, 0.75 once the zone morale is under 0.4; zone morale under 0.6; no fresh enemy reserve 600-900 away). The thresholds are constants at the top of `charge_zone` in prompting.py | false for the WIP14 behaviour |
| `exchange.force_by_sector` | true | WIP15: FORCE BY SECTOR block (your men vs the enemy seen in the three thirds of your line) | false to hide it |
| `column.share`, `fit_morale`, `fit_stamina` | 0.8, 0.6, 0.5 | WIP16 (llm_plus): share of the fit infantry taken into an assault column | |
| `column.gather_distance`, `rank_gap`, `file_gap`, `skirmish_out`, `cavalry_back`, `battery_line` | 1250, 160, 190, 260, 450, 1100 | WIP16: the column's gather line and ranks | |
| `column.step`, `step_ready`, `step_timeout_s`, `charge_distance`, `prepare_max_s` | 150, 0.8, 150, 550, 300 | WIP16: synchronized advance by steps, charge line, fire preparation at most 5 min | |
| `column.charge_min_morale`, `charge_min_stamina`, `cancel_morale`, `cancel_wait_s` | 0.5, 0.5, 0.45, 180 | WIP16: who charges, and when the column is called off | `enabled` false to switch the column off |
| `llm_only` | `false` | WIP13. `true`: the model commands alone. The server only checks its orders and forwards them (plus the unpacking of a battery whose march ended); no plan, assault, relief, withdrawal, fire, cover, cohesion, formation, route or skirmish work, and the plugin's reflexes are off. The prompt tells the model so. The battle is scored apart in `by_model` as "<model> (llm only)" | `true` to measure what the model does by itself |
| `dry_run` | `false` in the zip | `false`: the model commands the army. `true`: orders are shown and logged but not sent, reflexes stay off and the game's own AI fights; the battle is kept apart in the scoreboard (`dry_runs`) | `false` to play, `true` only to read what the model would do |
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

The number of model calls sets how many tokens the AI uses. Since 0.1.4 a turn is not a model call any more: the game sends a state often, the server's own staff work (assaults, relief, cover, cohesion, generals, wagons) runs at each of them, and the model is called only when a decision is worth it. With the 0.1.4 DLL the game is paused only while the model thinks; with the 0.1.3 DLL it is paused briefly at every state.

| Setting | Default | Effect | When to change it |
| --- | --- | --- | --- |
| `timing.approach_interval_s` | 120 | Interval between two turns while no enemy is in sight | Higher for long approaches |
| `timing.closing_interval_s` | 60 | Interval when the enemy is in sight but far | Rarely |
| `timing.staff_interval_s` | 30 | 0.1.4 DLL: interval between two states in contact (game seconds). Each state runs the server's staff work; no pause, no tokens | 20 for finer staff work; `null` to use the two intervals below with every DLL |
| `timing.engaged_interval_s` | 60 | 0.1.3 DLL: interval in contact when the plugin's reflexes are off | Rarely |
| `reflexes.engaged_interval_s` | 90 | 0.1.3 DLL (or `skip_quiet_turns` off): interval in contact when the reflexes run | Rarely |
| `economy.min_call_gap_s` | 150 | Battle seconds between two model calls, except for a critical event (an objective changes hands, the plan mode changes, a brigade breaks) | 90 for more model control, 240 to save tokens |
| `timing.contact_distance` | 600 | Distance at which the battle counts as "in contact" | Rarely |
| `economy.skip_quiet_turns` | `true` | Calls the model only when a decision is worth it; the server's staff work runs at every state | `false` calls the model at every state (expensive; the states then keep the 0.1.3 interval) |
| `economy.morale_drop`, `morale_drop_units` | 0.3, 2 | Brigades that lost this much morale since the last call are worth a call when at least 2 of them (or 15 % of the infantry) did; one shaken brigade is the staff's business | 0.2 or 1 for a closer watch |
| `economy.new_enemy_men`, `new_enemy_share` | 1200, 0.04 | Newly seen enemy forces worth a call: about a brigade, or 4 % of the AI army (artillery counts double) | Lower to react to every new unit |
| `economy.loss_men` | 100 | Floor of the losses since the last turn that force a call. The real threshold is the larger of this floor and `economy.loss_share` (0.01) × the AI's army | Rarely: the threshold already grows with the army. `loss_share` at 0.02 to skip more turns |
| `economy.max_gap_s` | 420 | Never longer than this (battle seconds) without calling the model | 240 for more model control |
| `economy.loss_window_s` | 150 | Losses are measured over about this long (unseen fire, cover, quiet turns) | Rarely |
| `economy.retry_backoff_s` | 60 | A lost model answer is asked again at the next state; from the second loss in a row the server waits this long, doubled at every further loss (at most `max_gap_s`) | Rarely |
| `economy.roster_fold`, `roster_max_folds` | 12, 0 | Late brigades keep their equipment in the unit table. With `roster_max_folds` above 0 they are added to the cached roster in batches of `roster_fold`; each addition rewrites the system prompt (about 21,000 tokens) and pays back only after some 40 further calls | 1 for very long battles with many late brigades |
| `claude_code.cache_ttl` | `null` | Prompt cache lifetime asked from Claude Code: `null` (its default, one hour in the recorded battles), `"5m"` or `"1h"`. Five minutes is cheaper to write, but an expired cache rewrites the whole system prompt: worth it only if you rarely pause for more than a few minutes. Not tested in battle yet | `"5m"` if you play without long pauses |
| `assessment.min_calls` | 3 | No after-action review for a battle left after fewer model calls than this | 0 to always get one |
| `scale.small.detail_radius`, `route_radius` | 1500, 800 | Short battles: units (not batteries) farther than 1500 from every enemy get a short line; ground towards the enemy only within 800 | Larger for more detail |
| `economy.static_roster` | `true` | The brigades' fixed equipment is sent only once per battle (cached) | Keep on |
| `economy.log_usage` | `true` | Shows the tokens of each call and the total in the report | Keep on to follow the cost |
| `scale.large_threshold` | 40 | Number of your combat units from which the battle is "large" and the prompt is compacted | Lower (30) if large battles cost too much |
| `scale.force` | `null` | Forces `"small"` or `"large"` | `"large"` to always save tokens |
| `scale.large.detail_radius` | 1200 | In a large battle, your units farther than this from every enemy get a short line only | Lower = fewer tokens, less detail |

Intervals under `timing` and `reflexes` are counted on the plugin's clock, which runs about 1.9 times slower than the battle clock shown in the reports and used by the `economy` settings: 30 game seconds are about one battle minute (measured at Shiloh on 2026-11-10). For reference, 0.1.3 wrote 249,000 to 420,000 tokens to the cache per recorded battle (16 to 29 model calls); replayed with 0.1.4 the same battles need 12 to 14 calls and an estimated 77,000 to 142,000 tokens written. See `docs/token-usage.md`.

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
| `charge_morale`, `charge_when_strong`, `max_charges_per_turn` | 0.6, true, 2 | Launched brigades charge a defender in reach whose morale fell under 0.6 (or a skirmisher/battery); with `charge_when_strong` any defender when the group is 2:1 up (WIP12: on by default) | Set by the doctrine |
| `fresh_charge_slow_distance`, `fresh_charge_morale`, `fresh_charge_stamina` | 400, 0.8, 0.8 | WIP12: a launched brigade with morale and stamina 0.8+ charges from 400 even through slow ground | 200 for the old behaviour |
| `charge_max_distance`, `charge_together` | 200, 2 | Launched brigades charge from 200 at most (whatever their own charge range), and at least 2 of them in the same turn unless the target is already shaken | Lower distance = safer charges |
| `charge_open_distance`, `charge_slow_distance`, `charge_slow_share` | 500, 200, 0.25 | Launched brigades charge from 500 at most over open ground, 200 when more than 25 % of the way is slow ground (woods, scrub, mud); fresh brigades see below | Lower for safer charges |
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
| `routes.road_preference` | 0.85 | Cost factor of road and bridge cells: below 1 the route prefers them. No effect on a map without such cells (none in the battle recorded on 2026-11-11; the game's `Road` tooltip is the one of `Grass`) | 0.7 to stick to roads more, where a map has them |
| `routes.max_waypoints`, `max_routes_per_turn` | 8, 12 | Limits per move and per turn | Rarely |

### March columns (`march`)

The server sets the formations: road column for long marches, line near the enemy. Not tested in game yet; the speed
gain of a road column is not measured. The plugin does not report formations, so a formation changed by hand in the
game is not seen by the server.

| Setting | Default | Effect | When to change it |
| --- | --- | --- | --- |
| `march.enabled` | `true` | Units on a long march go in `RoadColumn` and come back to `Line` near the enemy | `false` to leave formations to the model (columns already formed are put back in line) |
| `march.kinds` | `["Infantry"]` | Unit kinds put in road column | Add `Cavalry` or `Artillery` once you have checked in game what a road column does to them |
| `march.min_distance` | 500 | Distance still to march (straight line to the destination) from which a column is formed | Higher = fewer columns |
| `march.deploy_distance` | 600 | A column goes back to line when a known enemy is within this distance | Higher to deploy earlier |
| `march.enter_margin` | 150 | No column is formed when an enemy is within `deploy_distance` + this | Higher if units switch back and forth |
| `march.anticipate` | `true` | Deploys one state early when, at the rate the gap closed since the last state, the enemy would be within `deploy_distance` by the next one (states come every 30 s in contact, 60 to 120 s before) | `false` to deploy at `deploy_distance` exactly, measured at each state |
| `march.arrive_distance` | 150 | A column goes back to line this close to its destination | Rarely |
| `march.memory_s` | 300 | Enemies out of sight count for this long at their last known position | Lower if columns deploy for enemies long gone |
| `march.max_per_turn` | 12 | Formation orders per state | Rarely |

## Arms and units

These blocks set what the server does by itself for each arm. Each block has an `enabled` switch: `false` leaves that arm entirely to the model.

| Block and setting | Default | Effect | When to change it |
| --- | --- | --- | --- |
| `ranges.fire`, `ranges.charge` | 500, 500 | Default fire and charge ranges; each unit's own range, read in the game, comes first (`use_unit_charge`) | If your mod changes the ranges |
| `line.spacing`, `line.max_spacing` | 70, 150 | Base spacing between brigades of the line (widened to the real width of the brigades) | Larger if units get in each other's way |
| `line.standoff` | 360 | Planned distance of the line from the enemy before contact | Lower = more aggressive line |
| `engage.max_per_turn`, `max_charges` | 4, 4 | Orders and charges added per turn to units left idle; these floors rise to 6 % and 3 % of your combat units (`per_turn_share`, `charges_share`) | 0 charges for an AI that only charges when the model decides |
| `engage.charge_target_morale` | 0.5 | Automatic charge only on a target below this morale | Lower = safer and rarer charges |
| `engage.fresh_morale`, `fresh_stamina`, `fresh_target_morale`, `broken_target_morale` | 0.8, 0.8, 0.6, 0.4 | WIP12: a fresh charger (morale and stamina 0.8+) also charges targets under 0.6, and a target under 0.4 even when steady enemy brigades stand near it | Lower `fresh_target_morale` for fewer charges |
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

Reflexes act in the game between two states, without calling the model: they cost no tokens. They need the 0.1.3-beta DLL or later and stay off in `dry_run`.

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
| `terrain_rules.charge_fresh_morale`, `charge_fresh_stamina`, `charge_fresh_distance` | 0.8, 0.8, 450 | WIP12: a charge of the model by a fresh infantry brigade within 450 is never turned into an attack, woods or not | 0 distance for the old behaviour |
| `terrain_rules.unseen_refused_holds` | true | WIP12: a brigade under unseen fire whose step forward is refused (it would leave the line, or the plan defends) holds its place instead of falling back; also sent to the plugin | false for the WIP11 fallback |
| `terrain_rules.open_ground_for` | Artillery, Supply | Units whose destination is moved out of woods | Add `Cavalry` to keep cavalry out of woods |
| `reflexes.unseen` | `true` | Any unit (infantry, skirmishers, cavalry, artillery, wagons) losing men while no visible enemy stands within its own fire range — shooters hidden in woods or wheat, camouflaged by a perk, or out-ranging it — reacts by the general's aggressiveness: aggressive (≥ 0.7) fresh infantry or mounted cavalry charges a skirmisher or shaken enemy in reach, fresh infantry and skirmishers advance on the shooters; balanced (0.4–0.7) fresh foot units close in on a visible enemy just out of range; careful (< 0.4), and any tired unit, artillery or wagon, opens the distance | `false` to let units stand under fire |
| `reflexes.unseen_aggressiveness` | `null` | Aggressiveness used for that answer only; `null` = `doctrine.aggressiveness`, else 0.5 (balanced) | Set it to make the answer to fire bolder or more careful than the rest of the doctrine |
| `terrain_rules.unseen_withdraw`, `unseen_advance_stop` | 250, 120 | Distance of the server's pull-back from the hiding place, or of the aggressive advance short of it | Larger withdraw for safer units |
| `relief.return_morale` | calm 0.75, tense 0.7, critical 0.65 | Morale a pulled-back brigade needs before it goes forward again. Calm = no brigade in contact; critical = stop-loss running or 30 % of the brigades in contact shaken; tense = any other fight | Higher values for a more careful AI |
| `assault.eve_morale`, `final_charge.min_morale` | 0.8, 0.8 | Morale of the brigades joining an assault that has not gone in yet, and of the final charge (topped up with less rested brigades only when too few have it; `final_charge.fallback_morale` 0.7) | 0.75 if assaults form too slowly |
| `assault.weak_point`, `weak_flank`, `flank_distance` | true, true, 700 | The weakest defender is the first target; the group stages on its flank, 700 out | `false` for straight assaults on the objective |
| `assault.mass_charge_morale`, `mass_charge_stamina`, `mass_charge_min` | 0.8, 0.5, 2 | Brigades this fresh and good in melee (stars, assault perks or more men than the target) charge a steady defender when at least 2 are in reach. A brigade on a target's flank or rear charges it too (`flank_dot` 0.3) | `mass_charge_min` 3 for fewer charges |
| `assault.trade_cover_move`, `trade_cover_gain`, `trade_cover_every_s` | 250, 0.3, 120 | A launched brigade trading fire steps up to 250 to a spot whose fire value is 0.3 better, at most every 120 s; otherwise it fires where it stands | Rarely |
| `battery.auto_place` | `true` | The server places the batteries the model leaves alone | `false` to leave the artillery to the model |
| `battery.smoothbore_distance`, `rifled_share`, `behind_line` | 420, 0.8, 150 | Smoothbores (Napoleons, howitzers, 6-pdr guns) stand 420 from the enemy beside a steady brigade (`screen_gap` 60 behind it); rifled guns at 80 % of their range, 150 behind the line | 500 for more careful smoothbores |
| `battery.place_cooldown_s`, `max_place_per_turn`, `place_tolerance` | 360, 3, 300 | One placement every 6 minutes per battery, 3 a turn, none when the battery is within 300 of its distance (WIP12, was 180 / 150) | Longer cooldown if batteries move too often |
| `battery.keep_firing_guard` | 200 | WIP12: an unlimbered battery with an enemy in range and a steady brigade within 200 is never moved by the server | 0 to switch off |
| `supply.park_distance`, `park_tolerance` | 750, 250 | Idle wagons wait this far from the nearest visible enemy, behind the line | 900 for safer wagons |
| `supply.advance_units`, `advance_safe`, `advance_screen` | 2, 300, true | When 2+ units of the line close together are low on ammunition, a wagon drives up so that its area covers them, 300+ from every visible enemy, with a steady brigade between it and the enemy | 1 to serve single brigades too |
| `supply.need_infantry`, `need_artillery` | 0.4, 0.5 | Ammunition share under which a unit counts as low | Rarely |
| `terrain_rules.unseen_advance_max` | 350 | Longest step of a unit closing in on the enemy it sees to answer unseen fire (the visible enemy may stand far behind the hidden shooters) | Lower for more careful advances |
| `assault.stage_refresh_s` | 300 | Staging spots of an assault group are kept this long (a new spot is a new order: the march restarts) | Rarely |
| `final_charge.recharge_s` | 90 | A brigade of the final charge that was thrown back charges again after this long | Longer to spare the brigades |
| `relief.retreat_seconds` | 45 | Length of the fallback of a broken brigade pulled out of contact | Longer for a deeper retreat |
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
| `mission.merge_phases` | `true` | WIP17: a "Mission finished" (end of a phase of a chained battle) keeps the battle open; one report at the end | `false` for one report per phase (before WIP17) |
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

Finer staff work and more model calls.

```
"timing": {"staff_interval_s": 20},
"reflexes": {"face_radius": 450},
"economy": {"min_call_gap_s": 90, "max_gap_s": 240}
```

### Token-saving AI

Fewer model calls, compact prompt and no after-action review; the analysis is a little less fine.

```
"economy": {"min_call_gap_s": 240, "max_gap_s": 600, "loss_share": 0.02},
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

## WIP4 additions (2026-11-11)

### `plan` (abandon rule)
| Key | Default | Meaning |
|---|---|---|
| `abandon_ratio` | 0.5 | Force ratio (your strength / visible enemy) under which an assault that has not gone in is given up for the rest of the battle. |
| `abandon_ratio_kd_bonus` | 0.1 | Added to `abandon_ratio` when a casualty ratio is among the mission goals (0.6 in all). |
| `abandon_minute` | 20 | Minute of the map from which the rule is checked. |
| `resume_ratio` | 0.8 | An abandoned assault may be planned again only above this ratio. |

### `discipline` (last-word rules on the orders, `discipline.py`)
| Key | Default | Meaning |
|---|---|---|
| `enabled` | true | All four rules. |
| `capture` | true | Moves near an undefended objective go onto the point; a capturing unit stays; an idle one just outside steps in. |
| `capture_inner_share` | 0.4 | Share of the capture range, from the point, where a capturing unit is sent. |
| `capture_snap_share` | 2.0 | A move ending within this many capture ranges of the point is put onto it. |
| `capture_clear` | 250 | "Undefended" = no visible enemy within capture range + this. |
| `capture_threat` | 400 | A capturing unit with an enemy this close may leave. |
| `capture_keepers` | 2 | Units held on one point at most. |
| `steady_moves` | true | No new move for a unit on the march when the destination changes by less than `reissue_min_shift`. |
| `reissue_min_shift` | 200 | See above. |
| `battery_watch` | true | Stops sending marches to a battery that does not move on them. |
| `battery_min_trip` | 250 | A "march" is a move at least this long. |
| `battery_check_s` / `battery_min_step` | 50 / 20 | The battery must have moved this much this long after the order. |
| `battery_fails` / `battery_block_s` | 2 / 900 | Failed marches before the pause, and its length. |
| `wagon_run` | true | Wagons run on trips longer than `wagon_run_trip` (300); the gait order is repeated after `wagon_run_repeat_s` (300). |

### `relief` and `supply`
| Key | Default | Meaning |
|---|---|---|
| `relief.dry_ammo` | 0.03 | A brigade in contact with this little ammunition leaves the line. |
| `relief.rearmed_ammo` | 0.25 | It is not sent forward again under this share. |
| `supply.walk_back_clear` | 350 | A nearly empty unit walks to the wagon when no visible enemy is closer than this. |

### Weapons
`server/weapons/WeaponShootTypes.txt`: one line per weapon, `asset name,"type"` (the game's table). A weapon that is
not in it keeps the tags read from its asset name. Add the lines of a mod's new weapons there.

## WIP7 additions (2026-11-12)

| Key | Default | Meaning |
|---|---|---|
| `plan.take_unheld` | true | An objective nobody holds that the player needs is a target. |
| `plan.secure_when_superior` / `secure_ratio` / `secure_keep_ratio` | true / 1.5 / 1.1 | With this force ratio, the objective the player's victory needs is attacked even when the route to a win is a casualty ratio; kept down to the second ratio. |
| `plan.secure_idle_ratio` | 2.0 | WIP12: when every condition of your victory is already met, the plan still attacks the player's objective at this force ratio over the enemy seen (instead of DEFEND) | Higher for a more passive defender |
| `plan.stop_loss_cooldown_s` | 600 | After a stop-loss pause ends, it cannot trip again for this long. |
| `assault.target_ratio` | 1.5 | The assault group grows until its strength is this many times the defenders'. |
| `assault.reserve_min` | 1 | Fit brigades kept out of the group. |
| `assault.launch_min_ratio` | 1.5 | Group/defenders ratio to launch (was 0.6). |
| `assault.launch_floor_ratio` | 1.0 | At the deadline or after the long wait, the group goes in only at this ratio or above. |
| `assault.converge` / `converge_min` / `converge_angle` | true / 4 / 50 | Groups of 4+ brigades stage in two wings this many degrees either side of the approach. |
| `discipline.offmap` | true | Units off the field get no orders (WIP9: they are left alone, the game walks them in; `offmap_release_s` is gone). |
| `flank.*` | see flank.py | Flank guard: `flank_radius` 380, `helper_radius` 650, `helper_min_morale` 0.5, `fallback_morale` 0.75, `max_per_turn` 3, `repeat_s` 90. |

A battle timer longer than 240 minutes (the end of the day) is not used as an assault deadline.

## WIP8 additions (2026-11-12)

### `withdraw` (withdraw.py)
| Key | Default | Meaning |
|---|---|---|
| `rest` / `rest_distance` / `rest_morale` | true / 700 / 0.65 | Relieved brigades rest this far from every visible enemy until this morale. |
| `withdraw` / `withdraw_ratio` | true / 0.7 | Tactical withdrawal under this force ratio... |
| `withdraw_min_contact` / `withdraw_shaken_share` / `shaken_morale` | 3 / 0.5 / 0.5 | ...with at least 3 brigades in contact, half of them under 0.5 morale. |
| `withdraw_end_morale` / `withdraw_min_s` / `withdraw_max_s` / `withdraw_cooldown_s` | 0.6 / 150 / 600 / 300 | End and repeat of a withdrawal. |
| `preserve` / `preserve_ratio` / `preserve_kd` / `preserve_minute` / `preserve_resume_ratio` | true / 0.6 / 1.0 / 25 / 1.0 | Preservation of a lost battle. |
| `rally_distance` / `edge_margin` / `spacing` | 900 / 150 / 170 | Rally line geometry. |
| `rally_keep_s` / `rally_threat_share` | 240 / 0.6 | The rally point is kept this long unless an enemy comes within this share of `rally_distance`. |
| `rearguard` / `rearguard_min_morale` / `rearguard_release` | 2 / 0.55 / 250 | Rearguard size, quality, and the enemy distance at which it falls back. |
| `disengage` | 250 | A unit with an enemy this close gets a fallback first. |
| `battery_escape` / `battery_threat` / `battery_cover` / `battery_back` | true / 450 / 250 / 400 | Battery escape. |

### `fire` (fire.py)
| Key | Default | Meaning |
|---|---|---|
| `focus` / `threat_radius` / `closing_min` / `focus_per_threat` / `focus_repeat_s` | true / 500 / 30 / 3 / 60 | Fire focused on enemies closing in. |
| `unmask` / `unmask_step` / `unmask_repeat_s` | true / 160 / 90 | Masked batteries moved sideways. |
| `unmask_after` / `unmask_battery_gap` | 2 / 250 | WIP12: only after 2 masked states in a row, and never to a spot within 250 of another battery. |

## WIP9 additions (2026-11-12)

### `tactics` (tactics.py)
| Key | Default | Meaning |
|---|---|---|
| `hold_line` / `hold_threat_radius` / `hold_pool_radius` | true / 1000 / 900 | An objective of ours with enemy brigades within 1000 is faced 1 brigade for 1, with our brigades within 900 of it. |
| `hold_post` / `hold_tolerance` / `hold_min_morale` / `hold_repeat_s` | 180 / 90 / 0.45 / 45 | Post distance in front of the point (less when the enemy is close), "in position" distance, minimum morale, resend delay. |
| `focus_repeat_s` | 60 | Brigades in position all fire on one enemy brigade; the same target is not sent again before this long. |
| `hunt` / `hunt_isolation` / `hunt_radius` / `hunt_radius_defend` / `hunt_ratio` / `hunt_max` / `hunt_min_morale` | true / 500 / 800 / 600 / 2.0 / 3 / 0.6 | An enemy unit with no other enemy within 500 is attacked by up to 3 of ours within 800 (600 when defending) worth at least twice its strength. |
| `pursuit` / `pursuit_radius` / `pursuit_radius_defend` / `pursuit_steady_clear` / `pursuit_min_morale` / `pursuit_max` | true / 350 / 250 / 300 / 0.55 / 4 | A routing or falling-back enemy with no steady enemy within 300 is charged by a fresh unit within 350 (cavalry first). |
| `arrival_window_s` | 600 | Units on the field for less than this are listed as FRESH ARRIVALS, with the nearest end of the enemy line. |
| `breach_window_s` / `breach_clear` | 240 / 450 | An enemy unit broken this recently, with no steady enemy within 450 of its place, is listed as a BREACH. |

Nothing in `tactics` runs during a tactical withdrawal or a preservation; brigades sent to rest stay out of it.

### Other keys
| Key | Default | Meaning |
|---|---|---|
| `supply.park_spread` | 400 | Idle wagons wait at least this far apart, each behind its own part of the line (`park_spacing` is no longer used). |

### Plugin settings (Commands.cs, change and recompile)
| Field | Default | Meaning |
|---|---|---|
| `ArtilleryPackDistance` | 150 | A battery sent farther than this (whole route) limbers up first and starts when packed. |
| `ArtilleryPackTimeout` | 25 | Game seconds to wait for the limbering before moving by hand anyway. |



## WIP10 additions (2026-11-13)

### `skirmish` (skirmish.py)
| Key | Default | Meaning |
|---|---|---|
| `recon` / `recon_min_march` / `recon_woods` / `recon_group` / `recon_lead` / `recon_no_contact` | true / 500 / 350 / 400 / 300 / 500 | A brigade (not in contact) marching 500 or more towards woods or a ford, or with another brigade sent within 400 of the same place (flank attack), detaches its screen, which walks 300 ahead of it. One screen per group. |
| `rearguard` / `rearguard_release` | true / 250 | The rearguard brigades of a withdrawal detach their screens; a screen fires on the pursuers and falls back to its brigade with an enemy within 250. |
| `cavalry_radius` / `charge_radius` / `charge_speed` / `safety_step` | 450 / 300 / 2.0 / 250 | SAFETY: enemy cavalry within 450, or an enemy within 300 closing at 2 units/s or more (a charge): the screen runs back 250 towards its brigade. Overrides every other order. |
| `spent_morale` / `recall_distance` | 0.35 / 500 | A screen this shaken this close to its brigade goes back into it. |
| `max_detach_per_turn` / `repeat_s` | 2 / 45 | |

### Other keys
| Key | Default | Meaning |
|---|---|---|
| `assault.stage_clear` | 600 | Staging spots at least this far (or the enemy's own range + 150) from every enemy seen or remembered. |
| `withdraw.bounds` | true | Withdrawal by bounds: the main body stands on its line and fires; a new bound only when the line is pressed. |
| `withdraw.bound_arrive_share` / `bound_arrive_s` / `bound_min_stand_s` | 0.7 / 300 / 60 | The line "stands" when 70 % of it is at its spots (or after 300 s); it stands at least 60 s. |
| `withdraw.pressed_close` / `pressed_morale` / `pressed_ratio` | 200 / 0.4 / 1.6 | Pressed: a third of the line with an enemy within 200, or its brigades in contact under 0.4 morale on average, or 1.6 times its strength within 700. |
| `withdraw.counter_charge` | true | A standing line charges a beaten enemy unit within 250 (tactics.pursuit). |

Batteries and wagons no longer look for cover on the rally line or under unseen fire.

### Plugin settings (Commands.cs)
`ArtilleryPackTimeout` is gone: a battery limbers up and starts its march at once (the game's Move action stands
still until it is packed).
