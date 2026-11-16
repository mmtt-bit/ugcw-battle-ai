# Changelog

## 0.1.4-beta (2026-11-15)

Seventeen work-in-progress builds (WIP1 to WIP17), each made after a recorded battle: Shiloh, Gaines' Mill, Cold
Harbor, Malvern Hill, Kettle Run, Thoroughfare Gap, Second Manassas, Crampton's Gap, South Mountain, Antietam. The
detailed notes of each build, with the measurements that motivated it, follow this summary.

Highlights
- Three command modes (config.json): `llm_plus` (default: the model's orders plus a few staff reflexes:
  counter-battery, rally on high ground, lone batteries pulled back, unpacking, assault column), `llm_only` (the
  model alone, for testing) and the full system (the server plans, relieves, reinforces and charges).
- Doctrine for the model: game_rules.md (what the game really does: cover curve, altitude, morale recovery,
  charges) and strategy.md (cohesion, the line and the ground, assault column, envelopment, reinforcements, river
  defence, field works), read again at every planning pause; previous versions kept in server/old/.
- Charges: zone count within 600 of the target (own and enemy men, enemy morale, fresh enemy reserves nearby) with
  a verdict GO / PREPARE / TOO FEW / RECONSIDER, calibrated on the game's own AI; paired charges of veterans.
- Assault column (column.py): 80 % of the fit infantry gathered at 1,250 in two ranks, a synchronized advance by
  steps of 150, fire preparation at 550, then the charge; one group per approach point for an envelopment.
- New prompt blocks: FORCE BY SECTOR, EXCHANGE BY GROUND and FLANK THREAT (exchange.py), REINFORCEMENTS,
  COUNTER-BATTERY, CROSSINGS (fords and bridges with the nearest reserve) and FORTIFICATIONS (works.py).
- Artillery: batteries really move (the game cancelled every AI battery move until WIP6), limber and unlimber,
  unmask their line of fire, counter-battery fire by rifled guns and smoothbores, canister when infantry closes.
- Field works: new `fortify` order, the same call as the player's right click on a work's shield.
- Skirmish screens (`detach` / `recall`), withdrawal and preservation of a lost battle (withdraw.py), fire
  discipline and focus (fire.py), marches (march.py), cohesion of the army, unseen-fire reflexes in the plugin.
- Scoring: chained battles (several phases) give one report and one scoreboard entry; fix_scoreboard.py repairs
  older scoreboards (dry runs, phases, loading artefacts) with a preview and backups, nothing deleted; rescore.py
  rebuilds the history from the reports.
- Plugin: Commands.cs, UnitExtras.cs, Reflexes.cs, TerrainScan.cs, Snapshot.cs and the new SnapshotStatus.cs and
  Runner_Update_body.cs; see plugin/INSTALL.txt for the upgrade steps from 0.1.3.
- Tests: tests/test_smoke.py, 148 synthetic battles and checks, no game and no model needed.

Detailed notes by build

### WIP17 (2026-11-15, after Antietam in llm_plus, 3 phases, defeat)
Server, texts and two plugin classes (UnitExtras, Commands). DLL WIP17 built by Marc (md5
cadeb969fd6b4940fb7948be95179ea8): against WIP13 only Commands.Execute, UnitExtras.Write and WriteRoot changed, plus
UnitExtras.Fortify and ActiveWorks (FortificationsManager.activeFortifications is private: read by reflection).
The WIP17 server also works with the WIP13 DLL (no "fortifications" in the state).

Measured on the battle (log ebc94665): 703 fortification cells, never more than 3 AI brigades in them; at 300-352
min 10-12 fresh AI brigades (15-18k men) out of contact while the middle bridge was empty and the Stone Bridge was
held by Toombs alone (captured); a rifled battery had an enemy battery in range in 757 states, a smoothbore in
1277, and the model gave 30 + 44 fire orders at infantry while the server fired counter-battery 8 times; the
battle was scored as three battles (draw at 14:50, draw at 15:54, defeat at 16:38).

- FIELD WORKS. Plugin: {"cmd": "fortify", "id": N, "x": X, "z": Z} = the player's right click on a work's shield
  (GOAP.Planner.TakeFortification): the brigade marches into the free work nearest X,Z (within 150), or without
  x/z the nearest within 400; the state carries "fortifications" (position, hp, free, occupant, side) and
  "fort": true on a unit in a work. Server: the command in the schema and the order checks (infantry not in a
  work), FORTIFICATIONS block (free works within 1,200 of a held objective or a brigade, nearest brigade), doctrine
  in strategy.md (FIELD WORKS).
- CROSSINGS block (new works.py): each ford or bridge within 2,500 of an objective or with the enemy near: our men
  within 700, enemy men within 1,000, THREATENED AND EMPTY / OUTNUMBERED / contested / held, the nearest fresh
  brigade out of contact, and the total of the reserve. Doctrine in strategy.md (DEFENDING A RIVER). Replayed on
  the battle: at 310 and 340 min the middle bridge shows THREATENED AND EMPTY (5,358 enemy men) with a reserve
  brigade 1,063-1,318 away, 18-19 fresh brigades out of contact.
- COUNTER-BATTERY: rifled guns duel unless enemy foot or horse is within 350 (was 500); smoothbores duel too,
  unless it is within 400. COUNTER-BATTERY block (our batteries with an enemy battery in range: 253 of 457 states
  on the battle). In llm_plus a rifled battery ordered at infantry or cavalry farther than 800, while an enemy
  battery is in its range, fires at the battery instead. game_rules.md and the llm_plus note updated.
- CHAINED BATTLES: a "Mission finished" end (resultKind "mission") no longer closes the battle: the server logs a
  phase_end event and keeps the battle, its memory and its report; one report at "Battle finished", with
  "phases". A battle left after a phase (new map, disconnect) is scored with that phase's result. A map open
  under a minute with no losses and no game result is not recorded. "mission.merge_phases": false restores the
  old behaviour.
- fix_scoreboard.py merges the phases already recorded: entries whose report has game_result_kind "mission" are
  folded into the next entry of the same model within 4 hours (its result and points, losses summed, "phases",
  "merged_from"); the phase entries move to "merged_phases", their report files get "merged_into" (originals
  copied to reports/backup-<date>/), loading artefacts move to "excluded". Preview by default, --apply to write,
  --no-merge-phases to skip. rescore.py follows "merged_into". On the current scoreboard: Second Manassas (2
  phases) and Antietam (3 phases) become one defeat each, the 3 draws were all phase ends; 27 entries -> 22.

### WIP16 (2026-11-15, after Thoroughfare Gap in llm_plus, 11:42, defeat k/d 0.29)
Server and texts only; the DLL is the WIP13 build (md5 342968e8c30216a2c7ebd9ee1418363d).

Measured against the game's own AI on the same map (dry run 2026-11-13 14:31, victory): the game AI closed in from
3-4 sectors from 29 min, had 4-7 brigades within 900 of the Gap at 49-62 min, 4-6 directions, 13 melees in the
hour, took the Gap at 62 min (2,805 enemy losses for 1,556 at 60-90 min). Sonnet: 15,800 men against 10,300 seen
at 36-47 min (1.5 to 1) but no brigade within 900 yet; never more than 4 brigades near the Gap (2 or fewer after
68 min) while the player's 8-9 brigades (11,000-15,000 men) stood there; one melee in the battle. Law 1st and 2nd
arrived at 66 min 1,550 behind the line on the player's flank, faced 3-5 brigades alone and were captured while
Wilcox, Corse, Benning, Drayton and Hunton (morale 0.9-1.0) were out of contact.

- New column.py, ASSAULT COLUMN (Marc's design), run by the server in llm_plus mode when the model sends
  "assault_column": {"objective": ..., "from": [[x, z], ...], "go": true} (or {"cancel": true}):
  80 % of the fit infantry (morale 0.6+, stamina 0.5+), skirmishers, cavalry and up to two batteries per group;
  one group per approach point (two or three = envelopment); gather 1,250 from the objective in two ranks (the
  biggest brigade(s) in front to take the fire, the charging rank 160 behind, skirmishers 260 out on the flanks,
  cavalry 450 behind, guns on the flanks firing); advance by steps of 150, every group on the same line, the next
  step when 80 % have closed up (forced after 150 s); at 550 the front rank and the guns fire until the zone count
  is GO (at most 5 min), then every unit with morale and stamina 0.5+ charges the nearest enemy. Cancelled by the
  model, when the column's morale falls under 0.45, or after 3 min of TOO FEW / RECONSIDER at the charge line
  (back to the gather line). The model's fallback orders still apply to its members.
  ASSAULT COLUMN possible line when the fit infantry outnumbers the enemy seen within 1,200 of an enemy
  objective by 1.5 to 1 (in llm_only it points to the doctrine instead). Replayed on the 11:42 battle: offered at
  27 min and at 39 min (1.9 to 1).
- REINFORCEMENTS block: brigades that arrived in the last 30 min, 800+ from the army, enemy within 1,000, with
  the fresh brigades out of contact that could join them. On the 11:42 battle: Law flagged at 66 min.
- strategy.md: ASSAULT COLUMN step by step (so that the model can do it alone in llm_only), ENVELOPMENT, and the
  REINFORCEMENTS rule under COHESION. The MODEL-PLUS note documents "assault_column"; the answer schema has it.
- Tests: 143 pass (a walking simulation checks that groups with brigades twice as slow reach the charge line
  together, two ranks deep).

### WIP15 (2026-11-15, after Crampton's Gap played by the model alone, 2026-11-14 18:15)
Server and texts only; the DLL is the WIP13 build (md5 342968e8c30216a2c7ebd9ee1418363d).

Measured: same map, similar army (about 14,000 men). Full system (11-14 07:45): 791 orders (673 server, 455 moves),
11,842 lost, 5,166 enemy seen, k/d 0.44, exchange 0.35 at 90-120 min and 0.14 at 120-150. Model alone: 306 orders
(94 moves, 100 holds), 9,953 lost, 5,140 enemy seen, k/d 0.52, exchange 0.87 and 0.52. At 57 min the model charged
Hayes (1,578 men, morale 0.25) with 6th Va and 61st Va (2,079 men, one at 0.55) while Barton, Ferrell, two
batteries and then Wright (about 6,500 steady men) stood within 300: 2,500 men lost in four minutes; it followed
WIP12's "a fresh brigade charges a shaken target alone". From 57 min the enemy massed 6,500-6,600 men on one
flank against 3,200 then 1,300, while 3-4 brigades stayed on the other.

- Charges (Marc's rule, "charge sparingly"): prompting.charge_zone counts the 600 m zone around the target (your
  men vs the enemy's, the enemy morale there, fresh enemy brigades in reserve 600-900 away and not engaged) and
  gives a verdict: GO, PREPARE (wear the zone down by fire and guns first: zone morale 0.6+), TOO FEW (fewer men
  than the enemy in the zone; three quarters suffice once the zone morale is under 0.4), RECONSIDER (fresh
  reserve). CHARGE OPPORTUNITIES shows the count and the verdict. All the server's automatic charges (single and
  paired) go in only on GO (engage.charge_zone_check); WIP12's "a broken target needs no clear support" is gone.
  Checked on five logs: the game AI's winning Thoroughfare Gap gets GO on 27 target-slots (its 14 melees started
  at zone morale 0.30 and 0.86 of the zone's men, medians), Sonnet's battles almost none (outnumbered or losing
  the exchange). game_rules.md: CHARGE SPARINGLY replaces WHO MAY CHARGE; strategy.md: CHARGE WHILE FRESH, BUT
  PREPARED.
- FORCE BY SECTOR block (exchange.force_lines): your infantry and cavalry vs the enemy seen in the three thirds
  of your line, OUTNUMBERED flags, and a hint to shift a brigade from a quiet third to the outnumbered one.
- New mode llm_plus (config "llm_plus": true, the shipped default; "llm_only" still wins when set): the model
  commands, the server adds only counter-battery fire for rifled batteries left without an order, the rally of
  brigades under 0.3 on high ground, lone batteries pulled back behind the infantry, battery unpacking, and the
  plugin's facing / bracing / safety / cavalry reflexes (the unseen-fire reflex is off). No plan, assault,
  relief, replacement, reserve, withdrawal, fire focus, placement, cover, cohesion, routes or formations. The
  prompt gets a MODEL-PLUS MODE block; reports carry "mode" and the label "<model> (llm plus)". Replay of the
  model-alone battle in llm_plus: 22 server orders in 158 min (11 rallies, 6 counter-battery, 5 battery pull-backs).
  For the full system set "llm_plus": false. Tests: 138 pass.

### WIP14 (2026-11-14, after South Mountain, 09:14, full system, defeat k/d 0.29)
Server and texts only; the DLL is the WIP13 build (md5 342968e8c30216a2c7ebd9ee1418363d).

Measured in that battle: in two 600 m squares of meadow and wheat east of the objective, facing the player's
woods, the AI lost 5,488 men against 498 seen (11 to 1); the 18 brigades sent there were all server moves (120
replacements and 66 reserve commits between 45 and 130 min). Four batteries were lost with no enemy seen within
600 two minutes before and no steady infantry within 520-1,700; enemy brigades stood beyond the ends of the line
in 44 states from 90 min on; the prompt only warned of enfilade fire once it had started.

- New exchange.py:
  - ExchangeTracker: own losses and enemy losses seen per 600 m sector over the last 10 min (exchange.sector,
    window_s). A sector is LOSING at 200+ men lost and 2+ to 1 (min_losses, losing_ratio).
  - A losing sector on open ground with better cover within 800 behind is a trap: no replacement (relief), no
    reserve commit, no objective post (tactics.hold_line) goes into it; its brigades in the open are pulled back
    to that cover (pull_back, 3 a turn, not on an ATTACK plan; the model's own orders are never replaced).
  - Prompt: EXCHANGE BY GROUND (your ground and his for each contact where the ground is against you, with the
    game's cover factors), LOSING SECTORS, FLANK THREAT (enemy beyond an end of the line, enemy foot or horse
    within 800 of a battery with no steady brigade within 300). Shown in llm_only too, as information.
  - Flank watch: the nearest free healthy brigade (morale 0.7+, out of contact, within 1500) is sent beside the
    threatened end of the line, facing the threat; a lone battery whose threat is still 350+ away falls back 150
    behind the nearest steady brigade.
- game_rules.md: COMPARE BOTH GROUNDS (cover section), FLANK THREAT.
- Replay of South Mountain through the server: hot zone flagged in 74 of 89 states (45-130 min); 91 brigades
  pulled back to cover, 58 replacements and the reserve commits kept out of losing sectors; on the real states the
  flank watch gives 9 flank refusals and 30 battery pull-backs (after 120 min usually no free brigade left).
  Tests: 134 pass (Wip14ExchangeAndFlanks).

### WIP13 (2026-11-14, after the Second Manassas battle of 2026-11-13 19:15-20:55, two phases)
- New `llm_only` switch (config.json, default false): the model commands alone, for testing. The server only
  validates and forwards its orders, plus the unpacking of a battery whose march ended; the plugin's reflexes are
  off; the system prompt gets a MODEL-ONLY MODE block and the state no longer shows the server's plan, assault,
  rotation or reflex blocks. Reports carry "llm_only": true and the scoreboard keeps them apart
  ("<model> (llm only)" in by_model).
- game-dll/Assembly-CSharp.dll is the WIP13 build (md5 342968e8c30216a2c7ebd9ee1418363d). Checked against
  WIP12: only UgcwAi.TerrainScan differs (CoverCurve added, field TerrainCoverPoints, Build / .cctor /
  SampleCurve changed, 7,756 methods, none removed), plus two 28-byte compiler array helpers, one of them left
  over from a second compile and unused (harmless).
- Plugin TerrainScan: the game's cover curve (UnitPreference.coverCurve) is sampled, sent with the terrain and
  written to the game log ("[UgcwAi] Cover curve"). Measured damage taken (grass = 1): no cover / water / cavalry
  1.35, wheat 0.63, forest 0.49, dense forest 0.46, fortifications 0.42 (J&P correction 0.1 - 0.15 c up to
  c = 0.53 included). game_rules.md cover rules now use these figures.
- Staff work after Crampton's Gap (2026-11-14 07:45, full system, defeat k/d 0.44) and Second Manassas:
  - Counter-battery (fire.counter_battery*): a rifled battery with no enemy foot or horse within 500 fires at the
    nearest enemy battery in range (the three Parrotts never fired at the enemy guns seen in range in 211 states).
  - Cover holds (relief.cover_retreat_morale 0.3): on a DEFEND/TRADE plan a brigade in forest, dense forest or
    fortifications is pulled back only under 0.3 (was 0.5). The reserve commit leaves alone a brigade in
    fortifications or in woods within 800 of an objective you hold (relief.cover_hold_objective).
  - Rally on high ground (relief.rally_*): a brigade under 0.3, after its first critical fallback or once out of
    contact, moves to the highest passable ground 300-600 behind it (morale regenerates up to x1.6 there).
  - Isolated brigades (cohesion.support_*): on a defensive plan an isolated brigade holding cover, or in contact
    with morale 0.5+, is not recalled or pulled back alone: the nearest free healthy brigade is sent beside it.
  - Paired charge (engage.pair_*): two brigades of 2+ stars, morale 0.8+, stamina 0.7+, within 500 of the same
    enemy infantry brigade, with 1.3x its men (2x in fortifications) and at most one steady brigade beside it,
    charge it together (front and flank preferred), also when they were trading fire.
  - Replay of Crampton's Gap through the server: 14 counter-battery volleys in the first hour, 42 brigades kept in
    cover, 11 rallies on high ground, 31 isolated brigades kept in place, 4 paired charges (a replay without the
    game's reaction: the counts show the rules work, not the result).
  - game_rules.md: COUNTER-BATTERY, PAIRED CHARGE, ISOLATED ON GOOD GROUND, cover exception and rally in PULLING
    BACK. The report always carries "llm_only"; the server prints the mode and the config path at start.
- Measured in that battle (2026-11-13, phase 1 + 2, plan DEFEND throughout): 2,827 server orders against 249 of
  the model; the AI line left the fortifications and woods west of Stony Ridge between minutes 60 and 95 (reserve
  commits and cohesion pulls towards the centre, all server moves); 177 pull-backs of infantry standing in
  forest, fortifications or wheat at a median morale of 0.49 (relief.retreat_morale 0.5); when the enemy cavalry
  reached the batteries (minutes 218-235) the nearest infantry was 250-700 away.

### WIP12 (2026-11-13, after the battle of 15:48, Thoroughfare Gap, played by the model)
Server, texts and one plugin class. game-dll/Assembly-CSharp.dll is the WIP12 build (Reflexes recompiled;
md5 6d13a4162b1e7b9e3338ceb982350d67). Checked against the WIP11 DLL: only UgcwAi.Reflexes differs (1 field added,
UnseenRefusedHolds, default true; 3 methods changed: .cctor, Configure, UnseenReflex; 7,754 methods, none added or
removed); the new test reads the infantry/skirmish flag and the refusal reason ("it would leave the line", "the
plan defends"); setting key and log texts match the sources.

What the comparison with the game's own AI on the same map showed (measured)
- Game AI: 33 melee snapshots, 28 enemy routs, 5 surrenders. Model: 8, 1, 0; it sent 7 charges, 6 of them by fresh
  brigades (morale 0.85+, stamina 0.80+) on shaken targets (0.31 to 0.47) 206 to 441 away through forest: the
  terrain filter turned all of them into attacks but one.
- The plan said DEFEND until minute 32 ("every condition met") while 9,324 men faced 1,598 seen at minute 21.
- Batteries marched 32 times, 12 of them 160 m (unmasking), the two batteries stepping on each other.
- The WIP11 "no step out of the line" rule of the UNSEEN answer made 32 brigades fall back, breaking the line.

Changes
- Fresh charges: a charge of the model by fresh infantry (morale and stamina 0.8+) within 450 is kept through slow
  ground (terrain_rules.charge_fresh_*). Assault: fresh brigades charge from 400 through woods
  (fresh_charge_slow_distance), charge_morale 0.5 -> 0.6, charge_when_strong on. Auto-engage: max_charges 2 -> 4,
  charges_share 0.03 -> 0.06; a fresh charger also takes targets under 0.6 and needs no clear support around a
  target under 0.4. The doctrine formula gives these values at 0.5. Prompt: CHARGE OPPORTUNITIES lists targets
  under 0.7 and marks FRESH chargers.
- Plan: with 2 to 1 over the enemy seen (plan.secure_idle_ratio), the player's objective is attacked even when
  every condition of your victory is met. Replayed on the 15:48 battle: ATTACK from minute 21 (was 32).
- UNSEEN fire: a refused step forward (line, plan defends) holds the brigade in place (terrain_rules.
  unseen_refused_holds, sent to the plugin); out-ranged by skirmishers or cavalry it still steps back.
- Batteries: place_tolerance 150 -> 300, place_cooldown_s 180 -> 360; a firing battery with a steady brigade
  within 200 is never moved; a masked battery moves only after 2 masked states and never within 250 of another.
- game_rules.md: WHO MAY CHARGE replaces NEVER ONE BRIGADE ALONE; woods charge and reflex texts updated.
  strategy.md: CHARGE WHILE FRESH.
- Replay check: 6 of the 7 charges of the 15:48 battle now go in (1 before). Tests: 123 pass.

### WIP11 (2026-11-13, after the battle of 11:52, Kettle Run, DEFEND: defeat, k/d 0.20)
Plugin AND server. game-dll/Assembly-CSharp.dll is the WIP11 build (UnitExtras, Reflexes, TerrainScan recompiled;
md5 7ba8bb7e7dede7dc3e2a6bd378fa9208). Checked against the WIP10 DLL: only those three classes differ (8 methods
changed, 4 added: CavalryReflex, KeepsLine, AltitudeCurves, SampleCurve; 12 settings added), the rest of the game
code and the BattleLogic.Run hook are unchanged; defaults, settings keys, calls and log texts match the sources.

What the replay showed (measured)
- Even exchange for 40 minutes (k/d 0.89 to 1.37), then 10,857 of 13,265 men lost; about 4,100 were prisoners and
  1,495 (Early) walked off the map in the withdrawal.
- Skirmishers out-ranging Trimble (r547 against r400) drew it out of the line: the plugin's UNSEEN reflex "closed
  in" (150), then the server's own unseen-fire answer (terrain_rules.unseen_orders) moved it 250 more. The server
  then moved its neighbour 870 west. Trimble stood alone against three brigades; Lawton and Forno had no enemy in
  range in 0 of 39 states before minute 44, Early in 2.
- One enemy cavalry regiment (584 men) took Trimble, the battery, Forno and a screen: every one of them was routing,
  falling back or a skirmish screen when it was caught.
- The battery packed up 11 times in 50 minutes (packed or unpacking in 61 % of the states) and was captured.

Relief, read from the game's code (Assembly-CSharp)
- GOAP.UnitModel.altitude: 0 (lowest ground of the map) to 1 (highest); the relief digit of the prompt is
  int(altitude x 10). Fire: GOAP.Action.RangeAttack.RangeDmg evaluates UnitPreference.altitudeAccuracyDependency at
  (shooter altitude - target altitude), clamped to -1..1: above 0 it raises the low end of the damage roll, below 0
  it lowers the high end. Morale: GOAP.Modifier.Morale.Update multiplies the morale REGENERATION by
  altitudeMoraleDependency(own altitude). Spotting: GOAP.UnitModel.get_SpottingRange multiplies by
  altitudeSpottingDependency(own altitude). Speed: TerrainModifiersManager.SlopeSpeedModifier, downhill x1.07 to
  x1.35, uphill x0.9 to x0.3 by slope angle. The three curves live in the game's assets: WIP11 logs them.
- Surrender (J&P Rebalance, GOAP.UnitModel.CheckGlobalActions): a unit at zero morale surrenders with a chance that
  grows with the enemy men against friendly men close to it; fire and melee on a weak unit can also make it
  surrender (AskToSurrender / AskToSurrenderMelee). UnitManager.IsSurrounded (45 degree gap) is not called.

Changes
- Plugin, Reflexes.UnseenReflex: an infantry brigade never charges or steps more than unseen_line_ahead (100) in
  front of its nearest friendly brigade nor farther than unseen_neighbour_max (400) from it, never closes in on
  skirmishers or cavalry (unseen_chase_screens false), and with unseen_hold_line (sent by the server while the plan
  is DEFEND) never advances and charges only a shaken target. A refused step becomes "fell back to open the
  distance (no step forward: ...)". Replayed on Kettle Run: the 4 close-ins of line brigades are refused, the 2 of
  the screens are kept.
- Plugin, new CAVALRY reflex: a shaken infantry brigade (morale under 0.5) within 500 of enemy mounted cavalry, or a
  screen within 450, walks behind the nearest steady brigade (morale 0.6+, within 700), on the far side from the
  cavalry; a screen walks back into its own brigade when that brigade is farther from the cavalry. A charge
  already coming within brace_radius is left to BRACE. Settings: cavalry, cavalry_danger, screen_cavalry_danger,
  cavalry_shaken_morale, shelter_morale, shelter_search, shelter_behind, cavalry_cooldown_s.
- Plugin, Reflexes.Num / Bool: a setting sent as JSON null keeps its default (the cast threw and stopped Configure).
- Plugin, UnitExtras.Write: every unit carries "alt" (GOAP.UnitModel.altitude, 0..1).
- Plugin, TerrainScan: the terrain message carries "altitudeCurves" (accuracy, morale, spotting; 11 points each)
  and the game log gets one line "[UgcwAi] Altitude curves [x, value]: ...".
- Server, terrain_rules.unseen_orders: the same limits as the reflex (keeps_line, no chase of skirmishers or
  cavalry, hold_line). Server, planner_server: unseen_hold_line follows the plan mode (DEFEND) and the reflex
  settings are sent again when it changes.
- game_rules.md and strategy.md rewritten: duplicates removed (one place per rule), contradictions resolved,
  new sections (HIGH GROUND, LOCAL STRENGTH, SUPPORT A NEIGHBOUR, STAY AND FIRE, ENEMY CAVALRY, WITHDRAWAL,
  DEFENCE IN DEPTH, FORCE CONCENTRATION, ENCIRCLEMENT, EXPLOITATION), charges on fortifications only at 2 to 1.
  The previous files are in server/old/ (*.2026-11-13.md).
- game_rules.md, HIGH GROUND and the cover rule rewritten from the game's code: fire depends on the height
  difference (gain capped, loss without floor), morale regeneration on the unit's own height, sight on its own
  height, speed on the slope. Cover protects the TARGET (TerrainCover / CalcCover, coverCurve in RangeAttack.Shoot:
  grass 0.25, wheat 0.55, forest 0.67, dense forest 0.70 on a 0-1 scale), while "Damage" cuts the SHOOTER's own fire
  (Rebalance.Config.tooltipHints in RangeDmg). The old "Cover x Damage" figures mixed the two.
- Battle of 14:31 (Thoroughfare Gap, "victory", k/d 1.61) was a DRY RUN: config.json had "dry_run": true (the
  shipped default), so the game's own AI fought (units "ai": true in 95 % of the states, no plugin order, no reflex
  event) and the model's orders were only logged; yet the scoreboard credited the victory to the model and the
  after-action review described orders that were never carried out. Now: a dry run is recorded in
  scoreboard.json "dry_runs" (a reference for the game's AI) and changes neither the totals, the history nor the
  model's line; its report says DRY RUN and is saved as report-<stamp>-dryrun.*; no after-action review is
  written; the server prints a banner when the game connects and the in-game panel shows "DRY RUN (game AI
  commands)".
- Altitude curves read from the game (log line of the WIP11 DLL): accuracy -0.5 (shooter 1 below the target, on
  the 0-1 scale) .. 0 .. +0.69 (0.2 above) .. +4.5 (1 above); morale regeneration x1.0 .. x1.6 and spotting
  x1.0 .. x1.5 from the lowest to the highest ground. In damage (average of the roll): about +-10 % per level of
  difference up to 2 levels; above, the gain stops at +20 to +50 % (every volley at its best roll) while the loss
  goes on to -30 to -40 %. game_rules.md HIGH GROUND now gives these figures.
- game_rules.md: NEVER ONE BRIGADE ALONE (charges) and MARCHING WITH THE ARMY (batteries behind the first
  brigades, never first in the deployment area; follow the line in one bound), from the game AI's mistakes in the
  14:31 battle. Server, autopilot.engage_orders: no lone auto charge on a beaten unit with a steady enemy within
  charge_support_clear (300) of it.
- config.json: "dry_run" is now false by default (START_HERE, readme / user guide and CONFIGURATION updated).
- fix_scoreboard.py rewritten: it finds the battles fought by the game's own AI (battle logs where the AI's units
  stayed under the game's control at least half the time, reports with "dry_run", GAME_AI_BATTLES or --game-ai),
  moves them to "dry_runs" and corrects the totals AND the per-model lines by the same amounts; report files of
  those battles get "dry_run": true (originals copied into reports/backup-<date>/). Victories are no longer taken
  out by default (--remove-victories does it). It no longer drops "by_model" and counts "interrupted" properly.
  Run on Marc's scoreboard: the 15:20:06 victory moves to dry_runs; claude_code:sonnet 0 point in 17 battles.
- rescore.py keeps dry-run reports apart (dry_runs), so it cannot credit them to the model again.
- Tests: 119 pass (classes Wip11UnseenLine, Wip11DryRun, Wip11LoneCharge, Wip11FixScoreboard; test_infantry_out_ranged
  updated: no chase of skirmishers).

To check in game
- "[UgcwAi] Reflexes configured: ... cavalry=True hold_line=..." at the start, and the server line "Reflexes:
  unseen_hold_line = True (plan mode changed)" when the plan turns to DEFEND.
- "[UgcwAi] Altitude curves [x, value]: ..." once per terrain description: send it, it gives the size of the
  high-ground effect.
- "Reflex unseen: ... (no step forward: no chase of skirmish)" instead of "closed in on #..." for line brigades.
- "Reflex cavalry: #N (morale 0.4x) took shelter behind #M" and "screen #N walked back into brigade #M".

### WIP10 (2026-11-13, after the battle of 08:31, Malvern Hill, two phases: defeats, k/d 0.17 and 0.13)
Plugin AND server: UnitExtras.cs then Commands.cs must be recompiled.

What the replay showed (measured)
- WIP9 worked in game: no "Trying to add unit", every reinforcement entered, two field updates, 131 battery moves
  limbered (92 by hand).
- 86 "not packed after 25 s": limbering takes 30 game seconds, and a battery waiting idle is unlimbered again by
  the game (GOAP.Precondition Idle.AttackTarget / Hold.AttackTarget call set_IsLimbering(false) with an enemy in
  range). Move.Process (dnSpy, sent by Marc) limbers by itself only when the current leg is longer than
  limberingSwitchDistance and the move is not a move with fire; while IsLimbering it stands still.
- The staging spots of the assault were 20 to 185 from Union brigades (counted from the objective only; the Union
  stood in front of it). For 35 minutes no brigade reached its spot, they stood 250 to 500 from the enemy, arrived
  one by one; local ratio up to 1.96, never launched. Phase 1 in ATTACK: 10,766 men lost for 2,272 seen.
- The cohesion rule dropped 609 orders and recalled 28 brigades: a destination was judged against where the other
  brigades stood, not where they were going. Brigades sent together to the ford were each "alone".
- Batteries (all 10-pdr Parrotts) packed 30 % to 95 % of the time, 167 automatic moves; deployed in woods 19 % of
  the time (the rally line searched cover for every unit, then terrain_rules moved them out: 237 corrections).
- Phase 2 entirely in PRESERVE: a continuous retreat, pursued; 5,937 men lost for 1,601 seen.

Changes
- Plugin, artillery: limber-and-go. A battery sent farther than 150 m (whole route) is packed right after
  CancelActions and its march starts at once: Move.Process stands still while IsLimbering, then moves limbered. The
  idle wait of WIP9 (and ArtilleryPackTimeout) is gone.
- Plugin, skirmish screens: commands "detach" {id: brigade} (UnitModel.CreateScout, the game's "pop skirmishers"
  with its own test Rebalance.Methods.CanDetachSkirmisher) and "recall" {id: screen} (Planner.PushScout). The state
  flags "canScout" on brigades that can detach and "owner" on screens.
- Server, new skirmish.py (block `skirmish`): screens scout ahead of long marches towards woods or fords and of
  flank groups, cover the withdrawal (rearguard brigades detach theirs; they fire and fall back last), and fall
  back at the run from enemy cavalry within 450 or an enemy closing fast within 300 (a charge), whatever their job.
  Spent screens near their brigade go back into it. The model may "detach" and "recall" too.
- Server, assault: staging spots at least 600 (or the enemy's range + 150) from every enemy seen or remembered
  (`assault.stage_clear`). Replay: every spot 600 or more from the enemy instead of 20 to 185.
- Server, cohesion: a destination is judged with the other brigades' destinations (this turn's orders and marches
  under way). Replay: 31 orders dropped instead of 609.
- Server, withdrawal by bounds (`withdraw.bounds`): the main body walks to a line out of reach and STANDS there,
  its brigades firing together on the enemy that follows; a new bound only when the line is pressed (enemies within
  200 of a third of it, its brigades in contact under 0.4 morale, or 1.6 times its strength within 700), with a new
  rearguard. A standing line charges a beaten enemy within 250. Replay: 670 rally orders instead of 1,289,
  9 bounds, 15 volleys of the standing line.
- Server, artillery: no cover search for batteries and wagons (rally line, unseen fire). Replay: 95 woods
  corrections instead of 237.
- Prompt: the clock is the phase's (the whole battle's in brackets); unit notes "can detach skirmishers" and
  "screen of #id"; SKIRMISH SCREENS line; game_rules.md: flank attacks (three brigades at least, a screen ahead, a
  battery covering the crossing), screens, withdrawal by bounds.
- Replay cost: 66 calls, about 701k tokens written (WIP9 code: 693k): +1 %.

Waiting for the WIP10 DLL before more artillery work (placement hysteresis, preparation fire before the launch).

To test in game
- "Battery N limbers up for a march of M m", then the battery stands still about 30 s and moves limbered.
- "Detach N: skirmishers detached" (or "refused"); screens falling back from cavalry; "Recall N: back to brigade".
- During a withdrawal: the main body stops on its line and fires; it goes back only when pressed.

### WIP9 (2026-11-12, after the battle of 14:48, Cold Harbor / Boatswain Woods: defeat, 15,869 men lost for 3,338 seen)
Plugin AND server: Commands.cs, UnitExtras.cs and TerrainScan.cs must be recompiled (in this order).

What the logs showed
- Eight brigades, batteries, a general and a wagon (Longstreet, Walton, Pryor, Wilcox, Pickett, Law, Hood, Reilly) stayed
  at x = -4,200, outside the field, for the whole battle. They arrive with IsUnderAIControl = false and the game
  walks them in by itself; the WIP7 "release" called CancelActions(), which killed that entry march (Pryor moved
  46 m, then stopped), then CommanderManager.AddUnit(), which the game refuses out of bounds ("Trying to add unit
  with position out of the game bounds", 146 times). Law and Hood, arriving later, were stopped the same way the
  moment they appeared; on the east side Hardaway (36 times), Jones (20), Garland and Anderson were stopped too
  while walking in.
- The playing field grew with the second stage (TerrainController.SetLevel): the Union army fought at x = 1,600 to
  3,900, our eastern brigades arrived at x = 3,800, but the terrain scan, sent once, stopped at x = 1,610. The
  server took the eastern brigades for units off the field (no orders until they crossed x = 1,610), clamped the
  model's moves to the east (11 of 235), and the model saw no ground on the Union right flank.
- The force ratio counted the units stuck at the edge: 1.0 to 1.6 for the whole battle, while the army on the field
  lost five men for one. The plan never switched to DEFEND, no withdrawal or preservation started, the stop-loss
  tripped 10 times.
- Every battery move started with limbered = False: our moves never limber a battery, the guns were pushed by hand
  across the field. Seven unpack orders reached batteries already on their march.
- The supply wagons waited side by side behind the centre of the line and were taken together.
- 22 "units lost" in the report included 9 skirmish screens.

Changes
- Plugin, off-field units: `Commands.ReleaseToGame` only writes a log line (once per unit); the unit is not touched.
  The server no longer sends "release" (`discipline.offmap_release_s` / `offmap_release_tries` are gone).
- Plugin, field bounds: every state carries `field` = [minX, minZ, maxX, maxZ] of the current stage, and `offField`
  = true on a unit outside the game's world bounds (TerrainController.InWorldBounds). The server marks off-field
  units from these (the terrain scan only for an older plugin).
- Plugin, terrain update: TerrainScan watches the field bounds (every 2 s) and sends the terrain again with
  "update": true when a stage moves them. The server replaces its map and keeps the battle (report, plan,
  assaults, memories) and tells the model.
- Plugin, artillery: a battery sent farther than 150 m (the whole route) is limbered up first (SetLimber "pack",
  after stopping any older march) and starts when packed, or by hand after 25 s; another order (hold, fallback,
  attack...) ends the wait. An unpack order reaching a battery on its march is ignored.
- Server, force ratio: units off the field do not count in `situation.strength` (plan, abandon, withdrawal,
  preservation). Replay of the battle: assault abandoned at minute 24 (ratio 0.57), PRESERVE at minute 35 (0.45),
  later two withdrawals, instead of ATTACK all along. Batteries off the field are not unpacked or placed (444
  forced unpacks in the replay).
- Server, new `tactics.py` (block `tactics`):
  - HOLD LINE: an objective of ours with enemy brigades within 1000 is faced 1 brigade for 1 (nearest enemy first,
    the same pairing kept), each on the best cover near a post in front of the point, facing its enemy, with a
    clear line of fire; brigades in position all fire on ONE enemy brigade (the one most of them reach, the weakest
    when equal). Spare brigades stay the reserve.
  - HUNT: an enemy unit with no other enemy within 500 is attacked by up to 3 of our units within 800 (600 when
    defending) worth at least twice its strength.
  - PURSUIT: a routing or falling-back enemy with no steady enemy within 300 is charged again by a fresh unit within
    350 (cavalry first).
  - Prompt lines FRESH ARRIVALS (reinforcements just on the field and the nearest end of the enemy line, to be sent
    together against it) and BREACH (an enemy unit just broke and no steady enemy covers the gap: push through).
  - Nothing of it runs during a withdrawal or a preservation; brigades sent to rest stay out of it.
- Server, wagons: idle wagons wait each behind its own part of the line, at least 400 apart (`supply.park_spread`).
- Report: skirmish screens are counted apart (own_skirmishers_lost, enemy_skirmishers_broken_seen); a screen that
  goes back into its brigade is not a loss. The battle recounted: 13 brigades lost and 9 skirmish screens (was 22).
- game_rules.md: FRESH ARRIVALS, BREACH, held objectives; units entering do not count in the force ratio.
- Replay cost: 80 calls, about 650k tokens written (WIP8: 78 calls, 618k): +5 %.

To test in game
- Reinforcements walk in by themselves (log: "left alone until the game walks it in", no "Trying to add unit").
- "The playing field changed: terrain description sent again" when a stage opens; the server prints the new bounds.
- "Battery N limbers up before a march of M m", then the Move line shows limbered=True; no "not packed after".

### WIP8 (2026-11-12, after the battle of 13:24, Cold Harbor: defeat, 7,969 men lost for 2,562; outnumbered)
Server only (the WIP7 DLL is unchanged and validated).

What the logs showed
- Morale only comes back away from the enemy: -0.031 a minute within 500 of the nearest enemy, +0.021 between
  500 and 800; men lost 9.7 a minute within 500, 2.3 beyond. The 181 fallbacks moved the brigades 51 m (median),
  the nearest enemy went from 440 to 475 m, 61 % stayed within 500: the rotation never rested anyone, and the player
  shot the brigades one at a time while the others were too weak to threaten him.
- 21 % of the time a unit had an enemy in range, a friendly unit stood across its line of fire (Jones 29 states,
  Hardaway 12).
- Batteries were overrun: the plugin's battery_back reflex steps back by hand; nothing packed them up and pulled them
  back when the enemy closed in without infantry in front.
- 81 "release" orders went to shattered units walking off the map (the game's rout); the game refused them. Harmless
  but useless: a WIP7 defect.

Changes
- New `withdraw.py` (block `withdraw`):
  - REST: a brigade relieved by the server and no longer in melee walks to a spot 700 from every visible enemy,
    behind the line, in cover when there is some, until its morale is 0.65 again.
  - TACTICAL WITHDRAWAL: force ratio under 0.7, at least 3 brigades in contact and half of them under 0.5 morale:
    the army goes to a rally line 900 from the enemy and 150 inside the map, behind a rearguard (skirmishers,
    cavalry, then the freshest brigade) that fires from where it stands and falls back when the enemy is within 250.
    Ends when the withdrawn brigades average 0.6 morale (2.5 minutes at least) or after 10 minutes; 5 minutes
    before the next one. Replay: started at minute 25.7.
  - PRESERVE (battle lost): from minute 25, the player holds the objectives and we hold none, estimated kill ratio
    under 1.0, force ratio under 0.6, no assault going on: the same withdrawal for the rest of the battle (ends
    above 1.0). The plan is set to DEFEND with no target while it runs. Replay: from minute 29.5 (Center fell at 30).
  - Battery escape: enemy infantry or cavalry closing within 450 of a battery with no steady brigade within 250:
    pack up and go 400 back, behind the nearest steady brigade when there is one.
- New `fire.py` (block `fire`): enemy infantry or cavalry closing in (nearer by 30 since the last state, within 500)
  gets the fire of up to 3 of our units that have it in range, a clear line and no order of the model; a battery
  whose line of fire is masked by a friendly unit moves 160 sideways to a clear spot. Prompt lines CLOSING IN and
  FIRE MASKED.
- Off-field rule: shattered and routing units are no longer marked; at most 3 "release" orders per unit.
- Rules and doctrine: REST, TACTICAL WITHDRAWAL / PRESERVE, FIRE (game_rules.md); OUTNUMBERED AND LOSING (strategy.md).
- Tokens (replay of that battle, recorded answers): 236,900 written against 225,300 for WIP7 (+5.2 %); measured in
  game with WIP7: 291,471.
- 7 new tests (94). Previous files: old/v0.1.4-wip/before-wip8/.

To test in game
- Whether brigades sent 700 back actually walk there (the 0.1.4 notes say moves in contact were sometimes ignored:
  the server sends a fallback first when an enemy is within 250).
- The rearguard holding, and the army not oscillating between WITHDRAW and the plan.

### WIP7 (2026-11-12, after the battle of 10:12, Gaines' Mill campaign map: defeat, 8,065 men lost for 3,050)
Recompile Commands.cs, then Orders.cs, then Runner.cs (in that order: Orders now calls Commands). Replace the server.

Causes found in the logs (the after-action review saw the symptoms, not these)
- 3 brigades (38th NC 1st and 2nd, 22nd NC 2nd: 3,000 fresh men) and General Branch never entered the map: they
  started beyond its edge, got move orders at second 0, and the game cannot move a unit that is off the field (the
  move ends at once, the unit slides along the world bound to z=4883). The game's own AI walks such units in (two
  other brigades that were left to it for 4 minutes did enter). 71 orders to #1383 alone, a march to the map edge
  and back every 2 minutes for 100 minutes; and they were in the assault group, which therefore never assembled.
- The plan traded fire for the first 27 minutes at 2 to 4 times the enemy's visible strength. The only route to an
  AI win was the player's 40 % loss condition, so the plan said "do not take objectives"; Meeting point was neutral
  and the player took it at minute 15.
- The assault group was a share of the brigades (5), not sized to the defenders: group/defenders 0.6 to 0.77.
- The stop-loss re-tripped at every state from minute 40 to 147: the launch was held for 107 minutes.
- The assault deadline used a 720-minute "timer" (the end of the day): 36 % = minute 259; the player ended the
  battle at minute 149.
- Enfilade: brigades fired on from front and flank lost 17.6 men and 0.133 morale per state, against 6.2 and 0.029
  from the front only. The four brigades lost (37th and 7th NC) were exactly those. The plugin's face reflex does not
  turn a unit that has an enemy in front.

Changes
- Plugin: a unit off the field (TerrainController.InWorldBounds) is never taken from the game's AI, and is given
  back (GOAP.AI.CommanderManager.AddUnit) if an order reaches it; new command "release". Runner leaves such units to
  the game at the start.
- Server: units off the field are marked; their orders are not sent, a "release" is sent (once a minute) while the
  plugin holds them; they stay out of the assault group and of the army centre; one prompt line "ENTERING THE FIELD".
- Plan: an objective nobody holds that the player needs is a target (`plan.take_unheld`); with a force ratio of 1.5
  (`plan.secure_ratio`) the objective the player's victory needs is attacked even when the route is a casualty
  ratio ("secure"), kept down to 1.1 (`secure_keep_ratio`). Replay: ATTACK from minute 4 instead of 28.
- Stop-loss: after a pause it cannot trip again for 10 minutes (`plan.stop_loss_cooldown_s`); a group at 1.5 goes
  in through a pause.
- Assault: the group grows until 1.5 times the defenders' strength (`assault.target_ratio`, hidden defenders
  counted, `reserve_min` 1 kept back); launch at 1.5 (`launch_min_ratio`, was 0.6), at the deadline or after the long
  wait at 1.0 at least (`launch_floor_ratio`, was any ratio); four brigades or more stage in two wings 50 degrees
  either side of the approach (`converge*`). Replay: 10 brigades, ratio 1.2 to 1.55, launched at minute 27.6.
- A battle timer over 240 minutes is not a deadline (`assault.TIMER_MAX_MINUTES`): the minute deadline applies.
- New `flank.py` (block `flank`): a brigade under flank fire gets a fit brigade within 650 sent at the flanker; with
  none and morale under 0.75 it falls back out of the crossfire; prompt line "FLANK FIRE".
- Rules and doctrine: ATTACK/secure, assault sizing and wings, FLANK FIRE, ENTERING THE FIELD, WITH THE NUMBERS.
- Tokens (replay of that battle, recorded answers): 269,000 written against 257,000 for WIP6 (+4.9 %, one call more);
  system prompt +480 tokens. Measured in game with WIP6: 319,081.
- 7 new tests (87). Previous files: old/v0.1.4-wip/before-wip7/.

Not done / to test in game
- The release to the game AI (AddUnit) and the walk in. Whether the wings stage where the ground allows.
- Artillery moves (WIP6) still untested: no Southern battery in that battle.

### WIP6 (2026-11-12, after the battle of 2026-11-11 20:29: defeat, Forest Hill lost at 117 min, kill/death 0.44)
Recompile Commands.cs (plugin) and replace the server.

Artillery (plugin)
- WIP5's diagnostic: 27 of 27 artillery moves cancelled within 0.1 s, with the speed argument at 0 too.
- Cause, in the game code (Planner.MovePlayerToTargetWithFire): an artillery unit that is not on
  RuntimeVars.playerSide gets the cancel condition EnemyEnterArea(unit, ERange.InThreatArea). Any enemy inside the
  battery's threat area cancels its move at once, so a battery that sees the enemy could never move, not even away.
- Fix: for that one call the battery's side is set as RuntimeVars.playerSide, then put back (try/finally, same
  frame). Switch: `Commands.ArtilleryIgnoreThreatCancel` (true). The WIP5 diagnostic stays.
- Checked in the game DLL (2026-11-12): RuntimeVars.playerSide is a public static field (writable); Move.Create
  and Move's constructor do not read it. Within the switched call only UnitModel.set_Target reads it (selection and
  highlight of the old target, UI only): the battery's target is now cleared before the switch, with the real
  playerSide, so the player's units cannot be deselected.
- To check in game: batteries move, including with the enemy in range.

Woods mode (server)
- In that battle, in contact, brigades on grass lost 11.2 men per state, 5.4 in forest, 3.3 in dense forest, and
  woods were often within 20 to 120. The army left the woods to attack and stayed in the open after the exchange
  turned (stop-loss tripped 12 times).
- When a kill or loss ratio is among the goals, the plan is not attacking (or the assault is abandoned) and the
  exchange is being lost (stop-loss, casualty deficit or far behind): infantry in contact on open ground steps back
  to cover within 350 that keeps the enemy in range (up to 6 a turn, even without losses), and a move of the model
  ending in the open under fire is put in cover nearby. The last steady brigade within 300 of an objective we hold
  stays. AMBITION adds a WOODS line. Settings: `terrain_rules.woods_*`. Replay: 30 pull-backs, 6 moves redirected.
- 2 new tests (80).
- Previous files: old/v0.1.4-wip/before-wip6/.

### WIP5 (2026-11-11): artillery moves, plugin
Recompile Commands.cs (then Runner, as before). The server is unchanged.
- dnSpy: the game's own mouse path move (GameInputController.OnLeftMouseUpPathMove) calls
  Planner.MovePlayerToTargetWithFire(..., 0f); the plugin passed u.BaseSpeed. Artillery moves now pass 0
  (`Commands.ArtilleryGameSpeed`, true); infantry and the rest keep BaseSpeed until tested.
- Diagnostic: an artillery move cancelled within 2 seconds writes "[UgcwAi] Artillery move N cancelled after ..."
  with the limbering state before and after; every artillery "Move" line shows the speed argument.
- If the batteries still do not move, the next step is to call GameInputController.MoveUnitWithFire (the game's
  move for a click), once its body is known.

### WIP4 (2026-11-11, after the Shiloh battle of 15:27: defeat, 13,927 men lost for 2,585, three objectives lost)
Server only: it works with the WIP3 DLL. Nothing to recompile. Replay of that battle with the recorded answers:
about 327,000 tokens written instead of 347,000 (41 calls; turn prompts 6.7 % smaller, system prompt 1,500 tokens
larger, written once).

What the log showed
- The assault on Pittsburg Landing (force ratio 0.39 to 0.54) was called off by the model 8 times and came back
  each time: the strategic plan named the attack "by default" after 25 minutes of build-up, whatever the ratio, and
  told the model never to stop preparing it. The goals also allowed a draw (hold the three other objectives and keep
  the player's casualty ratio under 1.2): the plan never offered it.
- Forrest's cavalry was sent to the undefended Spain Field three times. It stood 217 from the point for four minutes
  (capture range 200), then on the point for three minutes, and was sent away before the owner changed.
- Not one of the 237 move orders to a battery was carried out (every one cancelled at once by the game). The
  batteries moved only under the game's own AI at the start (limbered, 1.1 per second, no fatigue) or by hand on
  fallbacks and routs (0.55 per second, 0.3 stamina per 1,000). Four batteries never moved. PLUGIN BUG, NOT FIXED
  HERE: the move call used for artillery must be found in the game code (see the questions in the release note).
- The three wagons started 2,800 behind the line, walked at 0.75 per second and reached it after 50 minutes; they
  ended the battle at 91 to 95 % of their stock. 30 trips were refused ("too far", "route unsafe") and the dry
  brigades were then left where they were.
- 279 moves were stopped before arrival; 30 of the replayed ones only changed a running march by less than 200.

Changes
- Abandon rule (`plan.abandon_ratio` 0.5, +`abandon_ratio_kd_bonus` 0.1 when a casualty ratio is among the goals,
  `abandon_minute` 20, `resume_ratio` 0.8). Under the ratio at minute 20 of the map with the assault not launched,
  the server gives the assault up for the rest of the battle and keeps that decision itself: AMBITION becomes
  "DEFEND (assault abandoned)", names the result still possible (the draw route of the goals: what to hold, which
  casualty ratio to keep) and the objectives to retake only when undefended; the ASSAULT PLAN block is no longer
  written, the model's "assaults" are ignored and its running directives dropped. Only a ratio above 0.8 opens the
  question again. Before minute 20 the build-up limit no longer forces an attack under the abandon ratio.
- Capture (new `discipline.py`, block `discipline` in config.json). A move ending within two capture ranges of an
  objective that is not ours and that no visible enemy defends is put onto the point (0.4 of the range from it); a
  unit inside the range is kept there until the owner changes (unless an enemy comes within 400); an idle unit just
  outside the range steps in. OBJECTIVES says CAPTURING or "TAKE: ... #1101 is at 217: move it ONTO the point".
- Steady moves: a move for a unit whose march still runs, ending within `discipline.reissue_min_shift` (200) of
  that march's end, is not sent.
- Wagons: orders for wagons are sent first; trips over 300 are made at the run (`gait Run`, to be checked in game:
  the plugin passes the base speed to the move call); a nearly empty unit (under 20 %) out of contact now walks to
  the wagon when the wagon's trip is refused, and stops inside its area (`supply.walk_back_clear` 350).
- Rotation limit made explicit and enforced for ammunition: a brigade in contact with no ammunition
  (`relief.dry_ammo` 0.03) leaves the line like one under critical morale, and is not sent forward again under
  `relief.rearmed_ammo` (0.25).
- Garrisons: the advice of the OBJECTIVES table now depends on the force ratio and the plan (picket when attacking
  or under 0.5; one steady brigade on a far objective the result depends on when defending; nothing when the line
  covers it). Advice only: the server does not move garrisons.
- Batteries: after two marches without a step the server stops sending marches to that battery for 15 minutes
  (143 useless orders on the replay) and BATTERIES lists it once as "cannot march" instead of promising that the
  server brings it forward.
- Weapons: `weapons/WeaponShootTypes.txt` (the game's table) replaces the guess from the asset name. Enemy notes say
  "breech", "repeater 7", "revolver 6", "flintlock", "double"; nothing more is written for single-shot weapons. The
  server weighs it in two of its own choices: a unit with breech-loaders or repeaters is less of a weak point for
  an assault, and a charge on a steady one needs more men (`equipment.FIRE_WEIGHT`, a rough weight, not game data).
- Rules and doctrine: CAPTURE, GARRISONS, ROTATION LIMIT, AMMUNITION CHECK, "cannot march" batteries
  (game_rules.md); OUTNUMBERED and the 200 rule (strategy.md).
- 11 new tests (78).
- Previous files: old/v0.1.4-wip/server-before-wip4/.

Not done
- Artillery marches (plugin). Capture time and conditions are not read from the game: 4 and 12 minutes were seen.
- Garrisons are not enforced by the server. The abandon rule is not applied before minute 20.
Code review of 0.1.3-beta: fewer tokens, features that did not work, bugs. The plugin changes need a new DLL
(recompile Bridge, Reflexes, Commands and Runner, in this order); the server also works with the 0.1.3 DLL.

Tokens (estimated on replays of three recorded battles: 46 to 63 % fewer tokens written per battle than 0.1.3, see
docs/token-usage.md; not yet measured in game)
- The model is called for decisions only: at once for a critical event (an objective changes hands, the plan mode
  changes, a brigade breaks), otherwise at most every `economy.min_call_gap_s` (150 battle seconds) and at the latest
  every `economy.max_gap_s` (420, was 330). `economy.max_consecutive_skips` is gone.
- The server's own staff work (assaults, relief, cover, cohesion, generals, wagons) runs at every state, model call
  or not.
- Turn prompt rewritten in a compact form (normal cases are not written; see READING THE STATE in the system prompt):
  unit and enemy tables, BATTERIES, GENERALS, CAVALRY, SUPPLY, CHARGE OPPORTUNITIES, ASSAULT PLAN, ORDERS RUNNING.
- Briefing and objective descriptions moved to the cached system prompt.
- Late brigades no longer rewrite the cached system prompt: they keep their equipment in the unit table
  (`economy.roster_max_folds` 0; one rewrite cost 21,800 tokens and saved 6,100 on the replay of a Shiloh phase).
- A model that keeps failing (not logged in, usage limit, time-outs) is asked again at the next state, then less and
  less often (`economy.retry_backoff_s`): every try froze the game and could be paid.
- No after-action review for a battle left after fewer than `assessment.min_calls` (3) model calls.
- New `claude_code.cache_ttl` (null, "5m" or "1h"), to be tested.

Features that did not work
- Waypoint routes stopped at their first waypoint (a unit stood still for 28 minutes in a recorded battle): the next
  leg is now started at the next frame (plugin, Commands.cs).
- A final charge thrown back never went in again: it does after `final_charge.recharge_s` (90 s). The first fix
  was defeated by the prompt preview, which stamped the charge time at every state.
- A retreat by `move` stayed in place 44 % of the time (logs): `fallback` for `relief.retreat_seconds` (45 s).
- A lost or invalid model answer lost the whole turn: the staff work still runs, the answer is repaired when
  possible (extra brace, trailing comma, cut-off end, orders salvaged one by one) and the model is asked again.
- `"assaults": []` in an answer reset a launched assault to STAGING: it now means "nothing to change"
  (`"launch": "release"` hands an assault back).

Bugs
- Phantom end of battle: an end-of-mission line seconds after a map started (previous phase closing) wrote a
  "no contest" report and reset the server's memory of the battle.
- Assault losses were counted on the brigades still fit (false "group lost 42 %"): now man by man for every brigade
  since the launch; a routing brigade counts for its dead only.
- Prisoners: a captured unit changes side in the game. A brigade of the AI taken prisoner was counted as "an enemy
  unit broken", then as a new brigade when freed, and could trigger a model call as a "new enemy force"; enemy
  prisoners counted as AI units lost and as "reinforcements". Units are now counted for the side they fought for
  (recorded battle of 2026-11-10 17:05: 2 of the 9 "enemy units broken" were the AI's own brigades).
- `done` with `canceled: true` left the move "pending" (false MARCHING for minutes).
- `sanitize` used `ranges.fire` instead of the unit's own range to turn moves into range_attack.
- Unseen-fire advance not bounded (`terrain_rules.unseen_advance_max` 350); assault members moved by that rule.
- Staging spots, assault targets, generals, wagons and cohesion recalls were re-issued at every state.
- `contact_time`, `last_mode` and `llm_failures` were kept from one map to the next.
- The after-action review prompt began with a stray backslash; salvaged reasoning lost its escaped quotes.
- server.py (bridge test) printed French messages.

Protocol (plugin 0.1.4, to be tested in game)
- States carry `"soft": true` and no longer pause the game; the server sends `{"cmd":"freeze","max_s":...}` just
  before a model call and `plan_done` resumes. In contact a state comes every `timing.staff_interval_s` (30 game
  seconds). With `economy.skip_quiet_turns` off the old interval is kept (one model call per state).
- Old DLL + new server: works as before (pause at every state, 90 s interval). New DLL + old server: not supported.
- Plugin: Bridge sees a closed server within half a second; the unit dump every 2 seconds is gone (once, on F9);
  the "counter" reflex keeps its cooldown when no helper is in reach; a move for a unit that is gone is reported.
- plugin/Runner_Update_body.cs was still an older body (no reflexes, no route legs, pause at every state): rewritten
  to match Runner.cs. The previous text is in old/v0.1.4-wip/plugin/.

After the first battle with the 0.1.4 DLL (Shiloh, 2026-11-11 13:24; server only, the DLL is unchanged)
- Artillery: no gun was ever seen as smoothbore (the game marks only rifled guns, "_RF"), and the ten batteries stood
  2,000 to 3,600 from the enemy for the whole battle (range 1,050 to 1,450): they never fired. The server now brings
  the batteries the model leaves alone to their firing spot: smoothbores about 420 from the enemy beside a steady
  brigade of the line (canister range), rifled guns at 80 % of their range behind the line (`battery.auto_place`).
  A guard standing right beside a wide battery counts as its cover.
- Supply: the wagons stayed 1,000 to 3,000 from the enemy and used 4 % of their stock while the line fell to 50 %
  ammunition (128 trips refused). Wagons now wait 750 behind the line and drive up when two or more units of the
  line run low, behind them, 300+ from the enemy and behind a steady brigade; they go back once the units are
  refilled (`supply.park_distance`, `advance_*`). Infantry counts as low under 40 % (was 35 %).
- Rotation: a pulled-back brigade goes forward again from morale 0.75 on a quiet front, 0.7 in a fight, 0.65 in a
  crisis (`relief.return_morale`); brigades joining an assault (`assault.eve_morale`) or the final charge
  (`final_charge.min_morale`) need 0.8. A ROTATION line in the prompt gives the current values.
- Assaults: the weakest defender (morale, experience, men, support) is the WEAK POINT and the first target; the group
  stages on its flank when the game gives its facing. Charges are no longer kept for shaken targets: two or more fresh
  brigades (morale 0.8+, stamina 0.5+) good in melee (stars, assault perks or more men) charge a steady defender
  together, and a brigade on a target's flank or rear charges it. A launched brigade trading fire moves to the best
  covered spot in range, or fires where it stands, instead of chasing its target over open ground ("attack" orders
  of the group: 91 -> 20 on the replay of that battle).
- game_rules.md and strategy.md say the same.

March columns and roads (2026-11-11 14:35; server only, the DLL is unchanged; not tested in game)
- New `march.py`: infantry with 500 or more still to march and no known enemy within 750 is put in road column
  (`RoadColumn`), and goes back to `Line` when a known enemy (visible, or seen in the last 5 minutes) is within 600,
  or would be by the next state at the rate the gap is closing. A column also deploys when it loses men, when its
  march ends or is replaced by another order, and 150 from its destination. Settings in `march` (config.json).
  The model did not order `RoadColumn` once in the battle of 13:24; the ORDERS list now tells it that formations
  are the server's job. On the replay of that battle: 16 columns formed, 16 deployed (replayed units do not follow
  new orders). The speed gain of a road column is not measured, and the plugin does not report formations: the
  server remembers the columns it formed and does not see a formation changed by hand.
- A `formation` or `gait` order no longer clears the unit's march in the server's memory (as `limber`, `mount`).
- Roads: the game's tooltip for `Road` is the one for `Grass` (speed 100 %, cover 50 %, stealth 2.5 %) and the map
  of that battle has no road cell (0 of 20,824; another modder reports that no map uses them). On a map without
  road cells the system prompt no longer mentions roads (legend, guide, TERRAIN EFFECTS), and game_rules.md no
  longer asks for approach routes "along roads". `routes.road_preference` is kept: it only acts on road cells.

Tests: 67 smoke tests (12 more for the march columns and the road lines). Earlier: 42 smoke tests (18 new: call economy, lost answers and repair, assault command and losses, prisoners,
pending moves, end of battle, final charge, roster), then 13 more for the changes above: 55 in all.

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
