# Changelog

## 0.1.3-beta (2026-11-10)
- Perk effects of J&P Rebalance 1.29.1 for all unit kinds (infantry, skirmishers, cavalry, artillery, corps) read
  from the mod's bonus files (`server/perks/`): a PERKS block in the cached system prompt, "perk roles" (fire,
  assault, steady, scout, cover, mobile, flexible) in the roster; assault group and scouting cavalry chosen with them.
  Effects limited to one unit kind are shown as such (cavalry "Skirmish" = dismounted only).
- Mounted / dismounted cavalry: state sent by the plugin, new `mount` order (dismount / mount) with the game's own
  restrictions (no shock cavalry, not in fortifications); no charges or riding down while dismounted.
- Generals: corps and command radius sent by the plugin, GENERALS block, `move` orders for generals kept away from
  the enemy, and generals moved by the server to keep their brigades inside their command radius.
- Plugin: UnitExtras.cs (mount state, CanDismount, SetMount, corps, commandRadius), Commands.cs (`mount`,
  `reflexes`), new Reflexes.cs, Snapshot.cs and Runner.cs (reflex events and tick): 12 classes.
- Reflexes in the plugin (`plugin/Reflexes.cs`), run every half second between two turns without calling the model:
  FACE (turn to a flank or rear threat), BRACE (stop and fire at a charger, cavalry meets a charge, counter-charge an
  enemy locked in melee), SAFETY (battery canister / step back, wagon and general move away, panic fallback).
- Reflex events shown to the model at the next turn (REFLEXES SINCE YOUR LAST TURN) and counted in the battle report.
- Turns in contact every 90 s instead of 60 while the reflexes run: about a third fewer model calls.
- Multi-phase battles (Shiloh): when the goals' objectives are not on this map, the plan targets this map's objective.
- Stop-loss: not before 5 min of contact nor on unseen fire; in an attack it pauses only the launch, not the staging.
- Faster assaults: launch at half the group with 2:1 superiority, and from minute 35 in any case.
- Terrain speed and stealth from the game's tooltips: staging away from woods, charges through slow ground turned into
  attacks, artillery and wagons kept out of woods, UNSEEN FIRE alerts with the nearest hiding place.
- Large armies: stop-loss, quiet-turn and minimum-casualty thresholds are shares of the AI army (floors kept);
  assault group, replacements, reserve commits and automatic orders per turn scale with the number of brigades.
- Configuration guide (`docs/configuration.md`): every setting, defaults, tuning and player profiles.
- Batteries still marching (plugin state inMove) are no longer unpacked by the server, which stopped their march.
- Cavalry ride-downs: not next to woods or through slow ground, at most 2 per 10 minutes; MARCHING units marked.
- Battle timer read from the game (TIME LEFT): the assault launches at the latest once 70 % of the timer is left.
- Assault members whose line of fire is blocked by a friendly unit sidestep to a clear lane ("lane blocked by #id");
  short sidesteps are exempt from the per-turn move caps (now 8 moves per turn).
- Unseen fire, for every kind of unit: losses while no visible enemy stands within the unit's own fire range (hidden
  in woods or wheat, camouflage perks, out-ranging shooters) are answered by the plugin's UNSEEN reflex and by the
  server according to the general's aggressiveness: charge a weak enemy in reach, close in, or open the distance.
- Mission timer read from the timer goals (the top panel's own timer is only the clock), with the battle clock and
  end of day; TEMPO line (launch deadline, march time, "behind schedule").
- Assault: staging timeout from the first arrival; hidden defenders seen recently still counted; launched brigades
  march to covered firing positions, keep their target, hold in cover in range, charge shaken defenders.
- Idle units trading fire from open ground step to cover nearby; mounted cavalry kept out of carbine duels.
- Routes: long moves sent as waypoints along the fastest ground and roads (new `routes.py`, plugin Commands.cs
  "path"); long marches no longer re-sent every 4 minutes; units outside the field at a new phase walk in first.
- Phase-relative minutes (launch, TEMPO, reserve commits); assault charges from 200 at most and together;
  aggressive doctrine keeps a single brigade in reserve.
- Mixed command: the model gives the macro command of up to 2 assaults ("assaults": objective, group, approach,
  launch now / wait / auto / release); the server keeps it and does the micro-management.
- The AI panel empties at the end of the battle and when the server disconnects; the AI's order arrows are hidden
  (`overlay.show_ai_orders` shows them for testing).
- Multi-phase battles: the map's own objectives (named by no goal) are targets too; two auto assaults when two
  objectives are to be taken; TIME LEFT in minutes.
- Cohesion (new `cohesion.py`): lone brigades brought back, no chasing of skirmishers or cavalry by the line.
- Battles left without an end screen are reported as "interrupted" (no points).
- Time as a share of the phase (timer left + time spent in the mission, plugin MissionGoals.cs
  "missionElapsedS"): TEMPO, assault deadline and reserve commits; right after loading a save too.
- Short battles: units far from every enemy get a short line (not batteries); no "facing enemy" flag.
- Cohesion: chases on a leash of 450 from friends; a stopped brigade under fire steps back out of reach.
- Fewer calls: the model is called for macro events only (sizeable new enemy force, brigade broken, morale
  drop 0.3, heavy losses), 2 quiet turns in a row at most, 330 s at most between calls.
- Lighter prompt: positions rounded to 10, defaults not written (full strength, full ammo, ammo auto, mounted),
  enemy equipment shortened, your units' fixed equipment only in the cached roster, short battery lines.
- Feedback and support: J&P Discord link in the README, the user guide and START_HERE.
- Synchronised assaults (pincer or two objectives); separate state per assault (no false release after losses).
- Charge distance by the ground (500 open, 200 slow); close charges at 200.
- Final charge (new `final_charge.py`): with 20 minutes left every fresh brigade closes in and all charge.
- Scouting perks: with the perk bonus files only the effects count (J&P "Recon_course" is a charge perk);
  `cavalry.scout_words` is the fallback for perks with unknown effects.
- `doctrine.aggressiveness` (0 to 1): one knob for the general's temper, driving attack, stop-loss, assault and
  fire-response settings.

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
