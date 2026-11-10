Game rules for the AI commander (Ultimate General: Civil War). Edit freely: re-read at every planning pause.
They hold the rules of the game and what the server enforces; doctrine is in strategy.md. These rules win.
(The previous, longer version is kept in old/game_rules.2026-11-09.md.)

UNIT STATES
- Routing units flee and ignore orders until they rally: never order them, never send others to "save" them.
- Shattered and captured units are out of the fight: no orders, do not count them in the line.
- A unit missing from YOUR UNITS is gone. Only Infantry, Cavalry, Artillery and Skirmish take combat orders;
  Supply wagons take only move and supply; never order a General.
- An attack, range_attack or charge target must be a visible enemy. Fog of war: no enemy seen does not mean none.

SCORING
- Victory 3 points, draw 1, defeat 0, decided by the game from the mission goals (MISSION GOALS block). Holding
  objectives usually decides it, so objectives matter more than killing.
- The kill/death ratio is judged too (PERFORMANCE SO FAR). Under 1.0 you lose more than you inflict: stop costly
  trades, pull back damaged units, fight where you have the advantage. A unit saved can hold an objective later.

PLAN AND POSTURE
- The STRATEGIC PLAN block is computed from the mission goals (the player's goals, inverted for you). Follow its
  AMBITION; it overrides the FORCE BALANCE posture and the aggressive advice in strategy.md.
  - ATTACK: you need an objective the player holds. You are the attacker by default: write and carry out an assault
    plan (ASSAULT PLAN below). Not clearly stronger: concentrate on one point, pin the rest with fire.
  - DEFEND: your conditions are met or the objective is out of reach. Hold what you own with a continuous line on
    good ground, let the enemy come into fire range, charge only shaken units.
  - TRADE: a pause, never the plan for the whole battle. It comes from the stop-loss (you lost more than 1.6 times
    the enemy's men over the last 10 minutes, TREND line) and lasts at least 8 minutes: stop advances, rotate out
    brigades under 0.6 morale, hold good ground, win the fire fight. Then the attack resumes.
  - Fallback line: when a win on casualties is out of reach, taking the objective still turns a defeat into a draw.
- The enemy strength only counts units you see: be careful before concluding you are stronger.
- Check OBJECTIVE SCORE every turn. LOSING means you cannot win by defending: take the RETAKE TARGET with several
  units together while the line keeps firing. Keep a garrison on an objective you own while the enemy is near.
  Owners change during the battle: use this turn's table.

ASSAULT PLAN (when the plan is ATTACK on an objective)
- At the start, read the MISSION BRIEFING and the goals, name the objective and write an attack plan in the "plan"
  field: approach axis, staging area, who fixes the defenders (batteries, skirmishers, the rest of the line by fire),
  who assaults (the freshest infantry), who covers the flank (cavalry on the WEAK SIDE), where the reserve stands,
  when you go in. The server shows it back to you; rewrite it only when it changes.
- The server drives the ASSAULT GROUP: it walks it to the staging area and launches it on the defenders when most of
  it has arrived and its strength is at least 0.6 of theirs (or after 15 minutes anyway). Do not give the group
  other orders. Give the batteries range_attack on the FIXING FIRE targets, keep the rest of the line firing in place,
  scout the point before the launch, and keep the freshest brigade outside the group to fill gaps and follow up.
- A group that loses about a third of its men is released: re-plan (a flank, another point, more artillery) rather
  than repeating the same attack. Never attack everywhere at once.

PULLING BACK, RELIEF AND RESERVE (enforced by the server)
- A brigade in contact whose morale is under 0.5, or whose men are under 40% of its maximum, gets fallback this turn;
  under 0.3 morale it retreats behind the line. Never hold, shoot or attack with it, even in forest. Pull back
  yourself also when stamina is under 0.3. Pulling back early saves a unit; a rout can drag neighbours with it.
- The nearest fresh brigade (morale 0.7+) moves into the gap the same turn. When you pull a brigade back yourself,
  order the replacement in the same answer.
- A brigade that fell back rests until morale 0.65 and stamina 0.5: do not send it forward or charge with it before.
- Idle healthy brigades far from the enemy are sent to the line from minute 20 (minute 8 when attacking); one
  stays back until minute 40. Commit the reserve yourself earlier where the fight is decided.

MOVEMENT, FIRE, FACING AND THE LINE
- A moving unit does not fire; it shoots again only once stopped. Every move costs fire. A unit in fire range stands
  and fires (hold, attack, range_attack): never move it to tidy the line (the server turns such moves into
  range_attack). Form the line before contact; afterwards adjust only units out of fire range, for a real reason
  (open flank, gap, threatened objective), and only a few per turn.
- Re-issuing an order restarts the unit's pathing: re-order only when the situation changed or the order is done.
  A move to nearly the same spot is ignored. Running (gait Run) drains stamina: walk unless speed is essential.
- A unit hit in the flank or rear takes extra damage and a morale penalty. The table shows "facing enemy",
  "facing obliquely", "SIDE TO ENEMY", "BACK TO ENEMY": fix SIDE and BACK first unless in melee. After a move the
  server turns the unit to the nearest visible enemy (or to "fx","fz"). Turn the end units towards a threatened flank.
- Fire needs a clear straight lane: a friendly unit in front blocks it, and two stacked units mean only one fires.
  Keep units side by side, never in a column towards the enemy; a second line is offset. Brigades differ in width
  (EQUIP "width"; a very large brigade is much wider): neighbours stand at least half the sum of their widths apart,
  as the FRONT LINE PLAN slots do. The server shifts a destination that would stack or block a lane, and drops it if
  no clean spot exists. A short sidestep listed under FIRE LANES is allowed even under fire.
- Compare strengths by men and morale, not by the number of brigades.

IDLE UNITS AND INITIATIVE
- A unit that received an order leaves the game's AI and then stands still without new orders. A brigade 450 to 650
  from the enemy, out of fire range, is doing nothing: give it a job. Every brigade in contact needs a task each time
  it finishes one: fire, advance, charge, rest, or hold on purpose (garrison, reserve).
- Idle units may get server orders marked "auto" (charge a beaten enemy in charge range, advance into fire range, shoot
  the nearest enemy); resting and holding units are left alone and about one brigade in five is kept back. Your own
  orders are better.
- No objective changing hands for twenty minutes while you do not lead the count: a STALEMATE line names the target
  and fresh brigades. Assault it.

CHARGES
- Only Infantry and Cavalry charge, and only from within the unit's charge range (unit table flag, CHARGE
  OPPORTUNITIES). Never charge with a routing, shattered, shaken (morale under 0.4) or exhausted (stamina under 0.3)
  unit, and never charge a target that is already routing, shattered or captured.

ARTILLERY
- A battery is ready (unlimbered, can fire) or packed (limbered, cannot fire); BATTERIES and EQUIP show it. A move
  packs it up and it must unpack before firing: move a battery only to relocate it out of fire range or behind the
  line. To step back a little, use fallback: it stays unlimbered and keeps loading.
- After a march, order {"cmd":"limber","id":N,"value":"unpack"} in the same turn. A battery whose march was cut short
  stays packed: unpack it. Never give hold to a battery that is still marching. The server unpacks packed batteries
  that are not marching and forces the unlimbering after two failed tries.
- Ammunition: roundshot for counter-battery and long range against formed brigades; shell against massed or covered
  troops; canister only at short range, against infantry or cavalry closing on the guns (its "range" drops while on
  canister). "auto" lets the game pick roundshot or shell, "mixed" fires shell and canister. The server switches to
  canister when infantry or cavalry comes within canister range and back to auto after.
- Smoothbore guns (Napoleons, howitzers) lose effect fast with distance: bring them level with the infantry line,
  never in front. Rifled guns (Parrotts, Rodmans) stay on good ground behind the line.
- A battery cannot defend itself in melee. Never leave it alone with enemy infantry within about 350 (550 for
  cavalry): a steady unit must stand within 200 of it and nearer the enemy, or it withdraws about 350 behind the line.
  Under 150 it is too late to limber: canister and infantry cover. The server pulls back unprotected batteries
  (ARTILLERY AT RISK).

AMMUNITION AND SUPPLY WAGONS
- A unit that runs dry stops fighting and surrenders more easily. Send a wagon before it is empty: brigades under 40%,
  batteries under 50%.
- A wagon rearms by itself every friendly unit of an enabled kind inside its area (faster out of combat); its stock
  runs down. Switch it on: {"cmd":"supply","id":W,"artillery":true,"infantry":true}.
- Rearm by moving the wagon to about half its radius behind the unit, at least 450 from any enemy, or by moving a unit
  that is out of fire next to the wagon.
- A wagon is defenceless. Its whole straight route must stay 450+ from every enemy, visible or last seen, and the trip
  at most about 1500; the server drops wagon moves that break this and marks such units ROUTE UNSAFE. Then rotate the
  unit out or bring it back to the wagon instead. Never park a wagon in a fire lane or in front of the line.

CAVALRY
- Never move cavalry in front of the infantry line or next to steady enemy infantry (the server drops such moves); no
  frontal attacks on steady infantry or guns.
- Reserve (default): behind the line where enemy charges, mainly melee cavalry, are likely; charge enemy cavalry when
  it is shaken or engaged with your infantry.
- Flanks: hunt enemy skirmishers and scouts. Fresh cavalry (morale 0.7+, stamina 0.5+, 60%+ of its men) rides down
  skirmishers or dismounted troops standing apart from steady infantry and guns (RIDE-DOWN OPPORTUNITIES): charge
  from where it stands, chain the next isolated target, then return to the reserve. This has routed such units at
  little cost. The server orders it when the cavalry is idle.
- Scouting: in the first 12 minutes one cavalry brigade (the CAVALRY block names it, preferring scouting perks) may
  ride along a flank to find the enemy, staying 500+ from enemy infantry, then return.

EQUIPMENT, STARS AND PERKS (the YOUR BRIGADES roster and the EQUIP column)
- Smoothbore muskets are short-ranged and strongest close up; rifles hit from farther; carbines suit cavalry;
  breech-loaders and repeaters fire faster. Use each unit's own "range" and compare it with the enemy's: the longer
  range fires first, so do not walk into the other's range for nothing.
- Rifled and fast-firing units go where a long fire fight is needed; smoothbores to assaults, flanks and charges.
  Highest-star brigades take the decisive blow; green ones (0-1 star) the quiet sector, second line or reserve.
- Perks: shooting, reloading, range or accuracy -> firing line; charge or melee -> assault; morale or stamina -> a hot
  sector or a long march; scouting or stealth -> skirmishers and cavalry on the flanks. Name the perk in your
  reasoning when it decides an assignment.

WEARING A STEADY ENEMY DOWN
- Fire alone rarely shakes a fresh steady brigade, and feeding brigades into its front only gives it casualties. Pick
  one target: two expendable units (least experienced or most worn, morale 0.45+, stamina 0.4+) charge it; while it is
  engaged or wavering, the best brigades attack and charge once its morale is under 0.5; the line keeps firing on it
  (WEAR-DOWN PLAN). Pull the chargers out at half morale or half men. Not on a target already shaken: just charge it.
