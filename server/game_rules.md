Game rules for the AI commander (Ultimate General: Civil War). Edit freely: re-read at every planning pause.
They hold the rules of the game and what the server enforces; doctrine is in strategy.md. These rules win.
(Previous versions are kept in old/: game_rules.2026-11-09.md, game_rules.2026-11-13.md.)

HIDDEN TROOPS AND SLOW GROUND
- Woods, dense woods and wheat (not fortifications) can hide enemy troops that see and shoot you while you cannot see
  them (stealth: dense forest x5, forest x1, wheat x0.5 in the TERRAIN EFFECTS), and camouflage perks can make enemy
  units hard or impossible to spot even in the open. Losses while no visible enemy stands within the unit's own fire
  range are listed under UNSEEN FIRE, for every kind of unit. Never leave units, above all cavalry, standing in the
  open within reach of unscouted woods: scout them with skirmishers, shell them with artillery, or move out of range.
- Under fire you cannot answer, never stand still, and never leave the line to answer it. The shooter is often a
  skirmisher or a rifle that out-ranges you (compare its "r" with yours), sent to pull one brigade forward into the
  fire of several. Defending, or whenever closing in would take the unit more than about 100 in front of its
  neighbours: step back out of its range, or answer with your own skirmishers and batteries. Otherwise the answer
  depends on your doctrine (DOCTRINE line under UNSEEN FIRE) and on the unit: an aggressive general charges a
  skirmisher or shaken enemy in reach with fresh infantry or mounted cavalry and advances fresh infantry on the
  shooters; a balanced one closes in only on a visible enemy just out of range; a careful one, and any tired unit,
  artillery or wagon, opens the distance. The plugin's UNSEEN reflex and the server do this for units you leave
  without orders; the reflex never takes an infantry brigade more than about 100 in front of its neighbours and
  never sends it after skirmishers or cavalry (it steps back out of their range instead). When a step forward would
  leave the line, or the plan defends, the brigade holds its place. A screen that "closed in" may need to come
  back to the line in your next answer.
- The ground works twice in a fire fight (game code, TERRAIN EFFECTS):
  - under the TARGET it protects ("Cover", with diminishing returns). On a 0-1 scale: open grass, road, scrub and
    mud 0.25, wheat 0.55, forest 0.67, dense forest 0.70, fortified ground 0.75 (a fortification work uses its own
    value), water, fords and bridges 0. Cavalry gets about 0.05 less. Perks add to it, and so does digging in
    (up to 0.1, only while the unit stands still). Artillery fire passes through part of the cover.
    Damage TAKEN, measured from the game's cover curve (grass = 1): no cover, water, fords and cavalry 1.35,
    grass 1, wheat 0.63, forest 0.49, dense forest 0.46, fortifications 0.42. A brigade in forest loses HALF
    the men it would lose in the open, in fortifications 40 %;
  - under the SHOOTER it cuts its own fire ("Damage"): grass and roads 100 %, wheat, scrub and mud 90-95 %,
    forest and fortified ground 80 %, dense forest 70 %, bridges 60 %, fords and water 50 % (infantry inside a
    fortification work uses that work's own rate of fire instead).
  So woods shelter a line but weaken its fire: a line in forest takes 49 % of the losses for 80 % of the fire,
  in fortifications 42 % for 80 %, in wheat 63 % for 90 %. Trading fire from cover against an enemy in the open
  wins about 2 to 1. Do not leave cover you hold to meet the enemy in the open: let him come.
- COMPARE BOTH GROUNDS: the exchange depends on your ground AND his. You on grass (1) against him in forest (0.49)
  lose about 2 to 1 at equal fire; that is a fight to refuse, not to reinforce. EXCHANGE BY GROUND lists your
  contacts where the ground is against you. LOSING SECTORS lists where you lost twice the men you inflicted in the
  last 10 minutes: never feed a reserve or a replacement into it (the server sends none there and pulls its
  brigades in the open back to the cover behind them). Make the enemy come to you there, or attack it elsewhere
  (South Mountain, 2026-11-14: 5,488 men lost against 498 in two squares of meadow and wheat facing woods).
  Never trade fire from open grass next to cover, from a ford or from water; trade from the edge of woods, wheat or
  fortifications against an enemy in the open. The server moves idle units under fire to such a spot nearby when it
  keeps the enemy in range.
- WOODS: when a kill or loss ratio is among the goals and the exchange is being lost (STOP-LOSS, a casualty deficit,
  or far behind), do not leave the woods to attack: brigades in the open under fire lose twice the men of
  brigades in forest (game cover curve: 1 against 0.49). The server moves them back to cover that keeps the enemy in range.
- Movement speed depends on the ground (TERRAIN EFFECTS): forest about 2/3, dense forest 3/5, scrub under 1/2, mud
  1/3. Do not march artillery or wagons through woods (the server moves their destinations to open ground). Launch
  charges and assaults over open ground and from close: a charge through woods or from far arrives exhausted (the
  server turns such charges into attacks, except a FRESH brigade within about 450: see CHARGE SPARINGLY). Choose
  approach routes along open ground.

HIGH GROUND (from the game's code and its altitude curves, read from the game on 2026-11-13; damage figures are
averages over the random roll of each volley and vary a little with the weapon)
- The relief level (0-9) in the unit tables is the height on THIS map: 0 = its lowest ground, 9 = its highest. A
  level is a tenth of the map's whole relief, so on a flat map a low rise counts as much as a ridge elsewhere.
- FIRE depends on the DIFFERENCE between the shooter and its target, not on the absolute level: read your level in
  YOUR UNITS and his in VISIBLE ENEMY UNITS. "High ground" means higher than him: level 8 facing an enemy on 9 is
  the low ground, and level 4 is not "a hill" when the enemy comes down from 6. It is the same for infantry,
  skirmishers, cavalry and artillery.
  - Firing down, the worst shots of each volley disappear: about +10 % damage for 1 level of difference, +15 to
    +25 % for 2 levels, +20 to +45 % for 3 or 4 levels. There it stops: every volley already gets its best roll.
  - Firing up, the best shots disappear: about -10 % for 1 level, -15 to -20 % for 2, -20 to -30 % for 3 or 4,
    down to -30 to -40 % from the bottom of the map to its top.
  - Up to 2 levels the high ground gains about what the low ground loses. Beyond, the gain stops growing while the
    loss keeps growing. Never leave a line trading fire with an enemy standing 2 or more levels higher: bring it
    level with him, into cover, or out of his range. Take the 2 to 3 levels above the enemy that give most of the
    gain; climbing higher adds little.
- MORALE: height does not change the morale lost under fire (that depends on where the fire comes from: FLANK
  FIRE). It changes how fast a unit RECOVERS, by its own height (not the difference), and only while its morale is
  under its ceiling (0.5 + 0.5 x men left / full strength: a brigade at half its men never climbs above 0.75), at
  half speed while it is being hit: about +6 % per level, from x1.0 at level 0 to x1.6 at level 9 or 10. Rest
  pulled-back brigades on the highest ground in reach (out of the enemy's fire).
- The higher side also gains morale indirectly: inflicting losses raises a unit's morale, and the enemy below
  inflicts fewer losses on it.
- SIGHT: a unit sees farther the higher it stands (its own height): about +5 % per level, from x1.0 at level 0 to
  x1.5 at the top of the map. Put screens, scouts and batteries on the high points.
- MOVEMENT depends on the slope, not the height: downhill x1.07 (1-5 degrees) to x1.35 (36 degrees and more), uphill
  x0.9 (0-5), x0.7 (6-15), x0.5 (16-35), x0.3 (36 and more). A charge uphill arrives late and under fire for
  longer; a charge downhill arrives fast.
- The ground that looks down on an objective from within about 800 is part of its defence. Keep the line and the
  batteries on it and one unit on the point (see CAPTURE); do not come down to stand around the point.
- Once the enemy holds higher ground above your line, do not stay under it: retake it with several brigades
  together, or move the line into cover (woods, fortifications) out of its fire.

UNIT STATES
- Routing units flee and ignore orders until they rally: never order them, never send others to "save" them.
- Shattered and captured units are out of the fight: no orders, do not count them in the line.
- A unit missing from YOUR UNITS is gone. Only Infantry, Cavalry, Artillery and Skirmish take combat orders;
  Supply wagons take only move and supply; Generals take only move (see GENERALS below).
- An attack, range_attack or charge target must be a visible enemy. Fog of war: no enemy seen does not mean none.

SCORING
- Victory 3 points, draw 1, defeat 0, decided by the game from the mission goals (MISSION GOALS block). Holding
  objectives usually decides it, so objectives matter more than killing.
- The kill/death ratio is judged too (PERFORMANCE SO FAR). Under 1.0 you lose more than you inflict: stop costly
  trades, pull back damaged units, fight where you have the advantage. A unit saved can hold an objective later.
- Prisoners count as losses: a routing brigade that enemy cavalry or infantry reaches surrenders with all its men,
  and a unit that walks off the map is counted as lost.

PLAN AND POSTURE
- The STRATEGIC PLAN block is computed from the mission goals (the player's goals, inverted for you). Follow its
  AMBITION; it overrides the FORCE BALANCE posture and the advice for attacking in strategy.md.
  - ATTACK: you need an objective the player holds, or one nobody holds yet, or ("secure") you have the numbers
    (1.5) and the player's victory needs it, even when your own route is a casualty ratio: take it before he is set
    on it. You are the attacker by default: write and carry out an assault plan (ASSAULT PLAN below). Not clearly
    stronger: concentrate on one point, pin the rest with fire.
  - DEFEND: your conditions are met or the objective is out of reach. Hold what you own with a line on good ground
    (HIGH GROUND, THE LINE), let the enemy come into fire range, charge only shaken units.
  - DEFEND (assault abandoned): under a force ratio of 0.5 (0.6 when a casualty ratio is among the goals) at minute
    20 with the assault not gone in, the server gives the assault up for the rest of the battle; only a ratio above
    0.8 opens it again. No "assaults", no staging, no plan to take that objective: the AMBITION names the result still
    possible (usually a draw) and the conditions to deny the player. Break contact, one line covering what you hold.
  - TRADE: a pause, never the plan for the whole battle. It comes from the stop-loss (you lost more than 1.6 times
    the enemy's men over the last 10 minutes, TREND line) and lasts at least 8 minutes: stop advances, rotate out
    brigades under 0.6 morale, hold good ground, win the fire fight. Then the attack resumes.
  - Fallback line: when a win on casualties is out of reach, taking the objective still turns a defeat into a draw.
  - Phases: some battles (Shiloh) start as a series of smaller maps; the goals then name the objectives of the whole
    battle. When those are not on this map, the plan targets this map's objective (PHASE OBJECTIVE): take it before
    the phase ends.
- Time: when no TIME LEFT is shown you do not know when the battle or the phase ends. Attacking, every minute you
  wait lets the defender dig in and reinforce: stage early and launch as soon as the group is ready; with a clear
  local superiority, launch at once. Minutes in TEMPO count from the start of this phase.
- Strength: compare by men and morale, not by the number of brigades. The enemy strength only counts units you see:
  be careful before concluding you are stronger.
- Check OBJECTIVE SCORE every turn. LOSING means you cannot win by defending: take the RETAKE TARGET with several
  units together while the line keeps firing (not when PRESERVE is in force). Owners change during the battle: use
  this turn's table.
- ENTERING THE FIELD: units listed there are still off the map; the game walks them in, they take no orders until
  then. They do not count in the force ratio until they are on the field.
- FRESH ARRIVALS: reinforcements just on the field. Send them together against the nearest end of the enemy line
  (named in the line) to take it in the flank; brigades sent one by one into the front are wasted.
- BREACH: an enemy unit just broke and no steady enemy unit covers the gap. Push fresh brigades through at once
  and turn on the flank or rear of the units beside it, keeping a reserve behind; the gap closes within minutes.
- FLANK ATTACKS: send at least three brigades together, never one or two; they are led by a skirmish screen (the
  server detaches one for a long march towards woods or a ford) and a battery covers the crossing. Do not cross a
  ford into woods no screen has looked into: brigades seen there earlier are probably still there.

OBJECTIVES
- CAPTURE: an objective changes hands only while a unit of yours stands INSIDE its capture range (the "radius" of
  the OBJECTIVES list, often 200) with no enemy in it, and it takes minutes (4 to 12 seen). Order the move to the
  objective's own x,z, not beside it, and leave the unit there until the owner changes: a unit 20 outside the range,
  or one that leaves after three minutes, captures nothing. The server puts such moves onto the point and keeps a
  capturing unit there (advice CAPTURING / TAKE in OBJECTIVES).
- HELD OBJECTIVES: the server faces each enemy brigade coming at a held point with one of your brigades, on cover
  in front of the point, and concentrates their fire on one enemy brigade at a time; spare brigades are the
  reserve behind the point. It also attacks an enemy brigade left alone near twice its strength of yours, and
  charges beaten enemy units again before they rally. Do not pull those brigades away without a reason; a neighbour
  fighting alone (THE LINE, IDLE UNITS) is a reason.
- GARRISONS are for objectives far from the army, against a raid round the front; follow the advice of the
  OBJECTIVES table. Attacking, or under a force ratio of 0.5: a picket only (cavalry, skirmishers), never a brigade
  taken from the main effort. Defending with a ratio above 0.5: one steady brigade (a battery if one is free) on a
  far objective the result depends on. An objective the line covers needs no garrison of its own.

ASSAULT PLAN (when the plan is ATTACK on an objective)
- At the start, read the MISSION BRIEFING and the goals, name the objective and write an attack plan in the "plan"
  field: approach axis, staging area, who fixes the defenders (batteries, skirmishers, the rest of the line by fire),
  who assaults (the freshest infantry), who covers the flank (cavalry on the WEAK SIDE), where the reserve stands,
  when you go in. The server shows it back to you; rewrite it only when it changes.
- The server drives the ASSAULT GROUP. It sizes it to the defenders: brigades are added until the group is 1.5 times
  their strength (men x morale, hidden defenders counted), keeping one fit brigade back; four brigades or more stage
  in two wings, either side of the approach, and go in together from two directions. It launches when most of the
  group has arrived and the ratio is 1.5 (1.0 at the deadline or after 15 minutes, never less). Do not give the group
  other orders. Give the batteries range_attack on the FIXING FIRE targets, keep the rest of the line firing in place,
  scout the point before the launch, and keep the freshest brigade outside the group to fill gaps and follow up.
- A group that loses about a third of its men is released: re-plan (a flank, another point, more artillery) rather
  than repeating the same attack. Never attack everywhere at once.

MOVEMENT, FIRE, FACING AND THE LINE
- A moving unit does not fire; it shoots again only once stopped. Every move costs fire. A unit in fire range stands
  and fires (hold, attack, range_attack): never move it to tidy the line (the server turns such moves into
  range_attack). Form the line before contact; afterwards adjust only units out of fire range, for a real reason
  (open flank, gap, threatened objective, a neighbour fighting alone), and only a few per turn.
- Re-issuing an order restarts the unit's pathing: every new move makes the unit stop, turn and start again. Let an
  order finish unless the situation changed (rout, threatened flank, breakthrough, new enemy force). The server drops
  a new move for a marching unit unless the destination changes by more than 200. Running (gait Run) drains stamina:
  walk unless speed is essential.
- Long moves are sent by the server as routes along the fastest ground (waypoints, facing the next leg at each
  bend): give the destination, not the waypoints.
- A unit hit in the flank or rear takes extra damage and a morale penalty. The table shows "facing enemy",
  "facing obliquely", "SIDE TO ENEMY", "BACK TO ENEMY": fix SIDE and BACK first unless in melee. After a move the
  server turns the unit to the nearest visible enemy (or to "fx","fz"). Turn the end units towards a threatened flank.
- FLANK FIRE: a brigade held in front and fired on from the flank (enfilade) loses about 4 times the morale of one
  fired on from the front only, then breaks and is charged. Keep the line's ends on obstacles or covered by a
  refused brigade; the server sends a nearby fit brigade at the flanker, or pulls the brigade out of the crossfire.
- FIRE: shoot first the enemy CLOSING IN (listed). Fire needs a clear straight lane: a friendly unit in front blocks
  it (FIRE MASKED), and two stacked units mean only one fires. Keep units side by side, never in a column towards
  the enemy; a second line is offset. Brigades differ in width (a very large brigade is much wider): neighbours stand
  at least half the sum of their widths apart, as the FRONT LINE PLAN slots do. The server shifts a destination that
  would stack or block a lane, and drops it if no clean spot exists. A short sidestep listed under FIRE LANES is
  allowed even under fire.
- LOCAL STRENGTH: FORCE BALANCE and the kill/death ratio describe the whole army and hide a brigade fighting alone.
  Each turn, for every brigade in contact, count the enemy brigades within about 600 of it and find its nearest
  friendly brigade. Two or more enemy brigades on it, or no friendly brigade within about 400: it is ISOLATED,
  however good its own exchange looks. The same turn, walk it back beside its neighbours (a move to 500+ from the
  enemy, not a fallback) or bring the neighbours up level with it, and say which in your reasoning.

IDLE UNITS AND INITIATIVE
- A unit that received an order leaves the game's AI and then stands still without new orders. A brigade 450 to 650
  from the enemy, out of fire range, is doing nothing: give it a job. Every brigade in contact needs a task each time
  it finishes one: fire, advance, charge, rest, or hold on purpose (garrison, reserve).
- SUPPORT A NEIGHBOUR: a brigade with no enemy in its own fire range while a neighbour is fired on by two or more
  enemy brigades is not a reserve, it is absent. The same turn, move it beside that neighbour or into range of the
  neighbour's attackers.
- Idle units may get server orders marked "auto" (charge a beaten enemy in charge range, advance into fire range, shoot
  the nearest enemy); resting and holding units are left alone and about one brigade in five is kept back. Your own
  orders are better.
- No objective changing hands for twenty minutes while you do not lead the count: a STALEMATE line names the target
  and fresh brigades. Assault it.

PULLING BACK, REST AND RESERVE (enforced by the server)
- Leaving the fight, for a brigade in contact. Pulling back early saves a unit; a rout can drag neighbours with it.
  - morale under 0.6 during a TRADE pause: rotate it out;
  - morale under 0.5, or men under 40% of its maximum: fallback this turn. Never hold, shoot or attack with it.
    EXCEPTION on a DEFEND or TRADE plan: a brigade in forest, dense forest or fortifications stays and fires down to
    0.3 morale (it takes half the losses of the open there); the server keeps it in place until then;
  - morale under 0.3, or no ammunition: it leaves the front line the same turn and retreats behind it (the server
    orders it; the SAFETY reflex steps it back at once). After its first fallback, or once out of contact, the server
    sends it on to the highest ground 300-600 behind it: morale comes back up to 1.6 times faster on high ground. Leave it there to recover;
  - stamina under 0.3: pull it back yourself.
- A fallback is a step back by hand (about 50): it gets a brigade out of a melee, it does not rest it. A brigade
  whose morale keeps falling turn after turn while the enemy on it stays steady gets a real relief before 0.5: a move
  500+ from the enemy or behind a steady brigade. Do not wait for the server's thresholds.
- FLANK THREAT: an enemy brigade beyond the end of your line, or enemy foot or horse within about 800 of a battery
  with no steady brigade within 300, is listed under FLANK THREAT. Refuse that flank before it turns it: a brigade
  beside the end of the line facing the threat, a skirmish screen further out, the batteries behind the infantry.
  The server sends the nearest free healthy brigade and pulls a lone battery back; a flank attack you leave alone
  costs batteries and brigades (South Mountain: four batteries lost with no guard within 500).
- ISOLATED ON GOOD GROUND: on a defensive plan, a brigade left 650+ from the line in fortifications or in woods by
  your objective is not called back: the line is lengthened to it. The server sends the nearest free healthy
  brigade to stand beside it; extend the line and keep that flank covered yourself (a brigade or a skirmish screen).
- The nearest fresh brigade (morale 0.7+) moves into the gap the same turn. When you pull a brigade back yourself,
  order the replacement in the same answer.
- REST: morale only comes back beyond about 500 from the nearest enemy (measured: -0.03 a minute within 500,
  +0.02 between 500 and 800). The server walks relieved brigades 700 from the enemy.
- Coming back: a brigade that fell back rests until the morale of the ROTATION line (0.75 on a quiet front, 0.7 in a
  fight, 0.65 in a crisis), stamina 0.5 and ammunition above 25 %: do not send it forward before. Brigades joining an
  assault or the final charge need 0.8, to last the whole charge. Out of contact, a nearly empty brigade walks to the
  nearest wagon.
- Idle healthy brigades far from the enemy are sent to the line from minute 20 (minute 8 when attacking); one
  stays back until minute 40. Commit the reserve yourself earlier where the fight is decided.

WITHDRAWAL
- TACTICAL WITHDRAWAL / PRESERVE: outnumbered with the line failing, the server breaks contact (rally line 900 from
  the enemy, a rearguard of skirmishers, cavalry or the freshest brigade in cover); when the battle is lost
  (objectives held by the player, casualty race lost, ratio under 0.6) it keeps the army out of reach for the rest
  of the battle. Do not order those brigades forward; use the rearguard and shaken enemy units close in.
- BY BOUNDS: the main body walks to a line out of reach and STANDS there, firing at whoever follows across the open;
  it falls back again only when that line is pressed, covered by a rearguard and its screens. Do not order the
  standing brigades away from their line.
- Withdraw in order before units are surrounded, towards open ground with room behind it: never into a corner of
  the playable area or against water marked X (a brigade pinned there surrenders), and never off the map.

CHARGES
- Only Infantry and Cavalry charge, and only from within the unit's charge range (unit table flag, CHARGE
  OPPORTUNITIES). Never charge with a routing, shattered, shaken (morale under 0.4) or exhausted (stamina under 0.3)
  unit, and never charge a target that is already routing, shattered or captured.
- CHARGE SPARINGLY, AFTER PREPARING IT: the charge ends a fight already won by fire; it does not win it alone.
  Use it rarely, and well:
  1. COUNT THE ZONE: within 600 of the target, your men (the chargers and the brigades close enough to follow)
     must at least equal the enemy's men there, the target included; three quarters of them are enough once the
     whole zone is broken (its morale under 0.4). One shaken brigade among steady ones is not a weak target.
     The game's own AI won Thoroughfare Gap this way: its 14 charges went in with the zone at morale 0.30 and
     0.86 of the enemy's men there (medians).
  2. PREPARE IT: first wear down the morale of the enemy brigades of that zone with fire and the guns (volleys,
     shells, canister close in), until the target is shaken (under 0.5) and the zone is worn (its morale under
     about 0.6). Then charge, with FRESH brigades (morale and stamina 0.8+), ideally two, from two directions;
     through woods too when the target is within about 450.
  3. RECONSIDER when fresh enemy brigades (0.8+) stand in reserve within about 900, not yet engaged: they will
     counter-charge your chargers in the open. Wait until they are committed, or charge elsewhere.
  CHARGE OPPORTUNITIES gives the count and a verdict for each line: GO (charge), PREPARE (fire first), TOO FEW,
  RECONSIDER. Crampton's Gap (2026-11-14): two brigades, 2,079 men, charged Hayes at morale 0.25 among 6,500
  steady men within 300 and lost 2,500 men in four minutes. A brigade under 0.6 morale or 0.5 stamina never
  charges a steady target. The server's own charges go in only on GO.
- PAIRED CHARGE: veteran brigades (2 stars or more) are wasted trading fire with green ones. Two veterans with morale 0.8+ and
  stamina 0.7+ within charge range (about 500) of the same enemy brigade, with 1.3 times its men (2 times in fortifications) and at most one steady
  enemy brigade beside it, charge it together, front and flank, once the zone verdict is GO (count and preparation
  as above). The server launches such a pair itself when you leave both idle.
- Shaken targets are the surest charges, not the only ones: two or more fresh brigades (morale 0.8+, stamina 0.5+)
  that are good in melee (stars, assault perks, more men than the target) can break a steady unit together, and a
  charge into a flank or the rear works on any target. The server's assault group charges in all three cases.
- WEARING A STEADY ENEMY DOWN (only where the zone count is at least equal): fire alone rarely shakes a fresh
  steady brigade, and feeding brigades into its front only gives it casualties. Pick one target: two expendable units (least experienced or most worn, morale 0.45+,
  stamina 0.4+) charge it; while it is engaged or wavering, the best brigades attack and charge once its morale is
  under 0.5; the line keeps firing on it (WEAR-DOWN PLAN). Pull the chargers out at half morale or half men. Not on
  a target already shaken: just charge it.

ARTILLERY
- A battery is ready (unlimbered, can fire) or packed (limbered, cannot fire); BATTERIES and the unit notes show it. A
  long move needs it packed and it must unpack before firing: move a battery only to relocate it out of fire range or
  behind the line. To step back a little, use fallback: it stays unlimbered and keeps loading, but the guns are
  moved by hand, slowly, and the crews tire: never cover distance with fallbacks. Batteries listed "cannot march"
  in BATTERIES do not carry out move orders for now: plan with them where they stand.
- STAY AND FIRE: packing, marching and unpacking cost minutes of fire each time. A ready battery with a target in
  range and a steady brigade within 200 stays where it is: give it range_attack every turn, never a move, even when
  the line in front of it shifts. Lane masked: sidestep the masking unit or change the target. Threat closing: fallback
  and canister. Move it only when it has had no target for several minutes or has lost its cover, and then once, to a
  spot it can keep: behind the line, on ground higher than the enemy when there is some.
- MARCHING WITH THE ARMY: on an approach march the batteries go behind the first brigades, never at the head of the
  column, and they reach the deployment area after the infantry that covers it: a battery arriving first, packed and
  alone, is taken by the first enemy brigade or cavalry that comes (the game's own AI nearly lost one this way on
  2026-11-13). When the line has advanced and the battery has no target left in range, it follows in one bound to a
  spot behind the new line, with a steady brigade between it and the enemy; it does not stay behind, silent.
- After a march, order {"cmd":"limber","id":N,"value":"unpack"} in the same turn. A battery whose march was cut short
  stays packed: unpack it. Never give hold to a battery that is still marching. The server unpacks packed batteries
  that are not marching and forces the unlimbering after two failed tries.
- COUNTER-BATTERY (COUNTER-BATTERY block): rifled guns (Parrott, Ordnance Rifle: "_RF") out-range smoothbores. When
  an enemy battery stands in their range, it is their first target, before distant infantry: enemy guns at 500-700
  that shell your line unanswered break its morale brigade after brigade (Crampton's Gap, 2026-11-14). Switch to
  infantry only when it comes within about 350 of a rifled battery, 400 of a smoothbore (canister work). Smoothbores
  duel too when the enemy guns are in their range and no foot or horse is that close. Antietam (2026-11-15): 74
  fire orders at infantry, 8 at batteries, while an enemy battery was in range most of the day. With the server's
  help (llm plus), a rifled battery ordered at infantry farther than 800 while an enemy battery is in its range
  fires at the battery instead; idle batteries duel on their own.
- Ammunition: roundshot for counter-battery and long range against formed brigades; shell against massed or covered
  troops; canister only at short range, against infantry or cavalry closing on the guns (its "range" drops while on
  canister). "auto" lets the game pick roundshot or shell, "mixed" fires shell and canister. The server switches to
  canister when infantry or cavalry comes within canister range and back to auto after.
- Smoothbore guns (Napoleons, 6-pdr guns, howitzers) lose effect fast with distance and fire canister only at close
  range: they belong about 400 from the enemy, beside a steady brigade of the line, never in front of it. Rifled guns
  (Parrotts, Rodmans) stand at about 80 % of their range, behind the line. The server brings the batteries you leave
  without orders to such spots (one move every few minutes per battery) and unlimbers them on arrival.
- A battery cannot defend itself in melee. Never leave it alone with enemy infantry within about 350 (550 for
  cavalry): a steady unit must stand within 200 of it and nearer the enemy, or it withdraws about 350 behind the line.
  Under 150 it is too late to limber: canister and infantry cover. The server packs up and pulls back an uncovered
  battery with enemy infantry or cavalry closing within 450 (ARTILLERY AT RISK).

AMMUNITION AND SUPPLY WAGONS
- A unit that runs dry stops fighting and surrenders more easily. Send a wagon before it is empty: brigades under 40%,
  batteries under 50%. AMMUNITION CHECK, every turn: each unit of UNITS LOW ON AMMUNITION under 30 % gets a decision
  (a wagon is coming, it falls back towards the wagon, or it is relieved); in a long battle the wagons come first.
- From the first minute the wagons follow the army (they are as slow as infantry and started 2,800 behind the line
  in one battle: they arrived after 50 minutes, when the line was already dry). They run on long trips.
- A wagon rearms by itself every friendly unit of an enabled kind inside its area (faster out of combat); its stock
  runs down. Switch it on: {"cmd":"supply","id":W,"artillery":true,"infantry":true}.
- The server runs the wagons you leave without orders: they wait about 750 behind the line (from the nearest
  enemy); when two or more units of the line close together run low, the nearest wagon drives up so that its area
  covers them, half its radius behind them, 300+ from every visible enemy and only with a steady brigade between it
  and the enemy; it goes back when they are refilled. A single unit out of the line is served by the wagon, or walks
  to it when nearly empty.
- A wagon is defenceless: a move you give it must keep its whole straight route 450+ from every enemy, visible or
  last seen, and the trip at most about 1500 (ROUTE UNSAFE in SUPPLY WAGONS). Never park a wagon in a fire lane or in
  front of the line.

SKIRMISH SCREENS
- "detach" a brigade's skirmishers to look into woods ahead or to slow pursuers; screens fall back by themselves
  from cavalry and from charges. Never use a screen to hold ground against infantry.
- A screen out of reach of a steady brigade's fire is prey for cavalry. With enemy cavalry about, keep the screens
  within about 300 of a steady brigade, or recall them.

CAVALRY
- Never move cavalry in front of the infantry line or next to steady enemy infantry (the server drops such moves); no
  frontal attacks on steady infantry or guns.
- Reserve (default): behind the line where enemy charges, mainly melee cavalry, are likely; charge enemy cavalry when
  it is shaken or engaged with your infantry.
- Flanks: hunt enemy skirmishers and scouts. Fresh cavalry (morale 0.7+, stamina 0.5+, 60%+ of its men) rides down
  skirmishers or dismounted troops standing apart from steady infantry and guns (RIDE-DOWN OPPORTUNITIES): charge
  from where it stands, chain the next isolated target, then return to the reserve. This has routed such units at
  little cost. The server orders it when the cavalry is idle.
- Mounted or dismounted (unit notes; like a battery's limbered / unlimbered): {"cmd":"mount","id":N,"value":"dismount"}
  puts carbine cavalry on foot, "mount" puts it back in the saddle. Dismounted, it fights like a skirmishing infantry
  line with its carbines (better from cover, perks such as Mounted_infantry and the dismounted range bonus of
  Endurance_course), but it is slow and cannot charge, scout or ride down: mount it before any of those, and allow
  the time the change takes. Dismount to hold a wood, a wall, a ford or an objective, or to add fire to a thin
  sector; never dismount in the open in front of steady infantry or within reach of enemy cavalry. Shock (sabre)
  cavalry cannot dismount ("cannot dismount"), nor can any cavalry inside a fortification.
- Scouting: in the first 12 minutes one cavalry brigade (the CAVALRY block names it, preferring scouting perks) may
  ride along a flank to find the enemy, staying 500+ from enemy infantry, then return.

ENEMY CAVALRY
- It wins by catching what is alone or already broken: screens, batteries, wagons, and brigades that are routing or
  falling back, which surrender when it reaches them. Steady infantry that faces it stops it with fire (BRACE).
- Enemy cavalry seen within about 600 of the line: turn the end brigade of that flank to face it, bring the screens
  of that side in, and check that every battery and wagon has a steady brigade between it and the cavalry.
- A brigade under 0.5 morale within about 500 of enemy cavalry goes behind a steady brigade before it routs. The
  CAVALRY reflex does it between your turns when a steady brigade stands within about 700; when none is in reach,
  order it yourself this turn (towards the army, away from the cavalry).
- Do not charge cavalry with infantry: it rides away and the brigade leaves the line. Fire on it; charge it only
  when it is locked in melee (the BRACE reflex sends the nearest fresh unit).

EQUIPMENT, STARS AND PERKS (the YOUR BRIGADES roster and the notes of the unit tables)
- Smoothbore muskets are short-ranged and strongest close up; rifles hit from farther; carbines suit cavalry;
  breech-loaders and repeaters fire faster. Use each unit's own "range" and compare it with the enemy's: the longer
  range fires first, so do not walk into the other's range for nothing.
- Rifled and fast-firing units go where a long fire fight is needed; smoothbores to assaults, flanks and charges.
  Highest-star brigades take the decisive blow; green ones (0-1 star) the quiet sector, second line or reserve.
- Perks: the PERKS block (end of these rules) gives the exact effect of every perk for each unit kind, and the
  roster shows the "perk roles" they add up to. fire -> firing line and long fire fights; assault -> assault group and
  charges; steady -> the hottest sector; scout -> skirmish screen, flanks and early scouting; cover -> woods, walls and
  objectives to hold; mobile -> flank marches and reserve; flexible (fast pivot) -> line ends and flanks, where a unit
  must turn quickly to face a threat. Name the perk in your reasoning when it decides an assignment.

GENERALS
- Their corps perks reach only the brigades of their corps standing within their command radius (GENERALS block).
  Move each general (move is his only order) behind the middle of his brigades, close enough for most of them to
  stay inside that radius, and never within about 650 of a known enemy: a general lost is a corps without its
  bonuses. When his corps moves, move him with it. The server moves an idle general that has lost most of his
  brigades from his radius, or that an enemy comes close to, and pulls back a general move that ends too near the
  enemy.

REFLEXES (run by the game plugin between your turns, without you)
- FACE: a unit not marching whose flank or rear is threatened by an enemy within about 350 turns to face it, unless a
  closer enemy is already in front of it.
- BRACE: a unit charged while marching stops and fires at the charger; fresh mounted cavalry meets a charge head on;
  when one of your units is locked in melee, the nearest fresh infantry or mounted cavalry charges its opponent.
- UNSEEN: a unit losing men with no visible enemy within its own fire range charges, closes in or opens the distance,
  by the general's aggressiveness and the unit's freshness, without taking an infantry brigade out of the line
  (see HIDDEN TROOPS).
- CAVALRY: a shaken infantry brigade (morale under 0.5) within about 500 of enemy mounted cavalry, or a skirmish
  screen within about 450, walks behind the nearest steady brigade, on the far side from the cavalry; a screen walks
  back into its own brigade when that brigade is farther from the cavalry. A charge already coming at it is met by
  BRACE instead.
- SAFETY: a battery with enemy infantry or cavalry within canister range switches to canister and, uncovered, steps
  back (fallback); a supply wagon or a general with an enemy too close moves away; a unit in contact whose morale falls
  under 0.3 falls back at once.
- They are listed under REFLEXES SINCE YOUR LAST TURN. Do not repeat what a reflex already did (do not turn a unit that
  just turned); check that the result still fits your plan: a unit that stopped to fire may need to resume its march,
  a counter-charging unit may need to be pulled out afterwards, a unit that "closed in" must come back to the line.
  A reflex buys seconds, it is not a plan: a shaken brigade with cavalry on its flank needs your order this turn.
- Your turns can be several minutes apart while the reflexes run: give each unit an order that holds until then.
