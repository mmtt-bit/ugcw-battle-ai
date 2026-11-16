Strategy notes for the AI commander. Edit freely: re-read at every planning pause. The player's notes plus lessons
from recorded battles. (Previous versions are kept in old/: strategy.2026-11-09.md, strategy.2026-11-13.md.)
Thresholds, distances and what the server enforces are in game_rules.md, not here.

IN EVERY BATTLE

COMMAND
- You command the army; the server is your staff. Decide which objectives to take or hold and in what order, which
  brigades go where, from which side, and when. Contact is not the goal; the objective is.
- Watch the clock every turn (TEMPO, TIME LEFT, CLOCK) and follow the TEMPO guide. Without a battle timer: minutes
  10, 20, 30, 60.
- Keep about one fifth of the infantry (at least one brigade) back early to reinforce, close a gap or exploit;
  commit it where the fight is decided. A reserve is behind the brigade it will relieve, not across the field
  (where it stands: FORCE CONCENTRATION when attacking, DEFENCE IN DEPTH when defending).

COHESION
- Brigades fight together. Never send one brigade alone far from the army into ground that holds no objective:
  only scouts (cavalry, skirmishers) go out alone.
- Do not chase skirmishers or cavalry with a line brigade: they fall back faster than it can follow and lead it
  under the fire of several brigades. Being shot at by skirmishers is an invitation, not a reason to advance.
- A brigade that looks as if it is winning its own fire fight in front of the line is the one the player is
  setting up. Judge it by who stands beside it and how many face it, not by its casualties so far.
- REINFORCEMENTS that arrive away from the army (REINFORCEMENTS block) are never left alone: the same turn, send
  one or two fresh brigades to them, or make them and the army strike the same enemy together from two sides (a
  pincer), or pull them back to the army. Thoroughfare Gap (2026-11-15): Law 1st and 2nd arrived 1,550 behind the
  line on the enemy's flank, faced 3-5 brigades alone for 20 minutes and were captured (2,688 men) while five
  fresh brigades stood out of contact.

THE LINE AND THE GROUND
- The line is a front, not a ruler. It does not need to be straight or centred on the objective: it needs every
  brigade able to fire, each within reach of a neighbour, and both ends on something the enemy cannot walk round
  (woods, a river, a ridge, fortifications) or covered by a refused brigade.
- Choose the ground by the enemy: higher than him, in cover when there is some, as wide as his visible front.
  Ground that looks down on the objective is worth more than the objective's own surroundings.
- Once the line is in contact, stop redrawing it. Move a brigade only to bring it into the fight, to cover a flank,
  or to relieve another; a line that keeps turning to face each new threat ends as brigades marching one by one.
- Cross rivers at fords and bridges, never under fire; hold your bank and strike enemy groups that cross alone.
- DEFENDING A RIVER (CROSSINGS block): every ford and bridge the enemy can reach is watched, and a reserve stands
  within a few minutes' march of each, not in a heap behind the centre. A crossing marked THREATENED AND EMPTY or
  OUTNUMBERED gets the nearest reserve brigade the same turn, before the enemy is across. Antietam (2026-11-15):
  10-12 fresh brigades (15-18k men) stood out of contact while the middle bridge was empty and the Stone Bridge
  was held by one brigade, which was captured.
- FIELD WORKS (FORTIFICATIONS block): a brigade holding a line or an objective near free works goes into them
  ({"cmd": "fortify"}): in a work it takes far less fire and holds far longer. Put the works nearest the enemy
  and the objective first; keep the reserve out of them. Antietam (2026-11-15): 703 work cells on the map, never
  more than 3 of the army's brigades in them.
- Skirmishers screen in front, then come in behind the ends of the line once it engages. Artillery behind the
  infantry, on the higher ground.

FORCE CONCENTRATION
- Do not attack along the whole front. Choose one WEAK POINT of the enemy line and put most of your brigades on it:
  an exposed flank (an end not resting on woods, water or a ridge, or a brigade standing out of the line), a
  brigade without cover (open grass, lower ground than yours), a demoralised or worn brigade, a green one, or one
  no battery supports. Aim for 2 to 3 of your men for 1 of his at that point; elsewhere, pin the enemy with fire,
  batteries and skirmishers so that he cannot move his brigades to the point.
- Go in TOGETHER. The brigades reach their firing positions at the same time (stage them first, out of his
  range), fire a few volleys and charge at once, from two directions when you can (ENCIRCLEMENT). Brigades that
  arrive one by one are beaten one by one: with "assaults", the server waits until the group is in place.
- Keep one or two fresh brigades (and the cavalry) out of the attack, behind the point, for EXPLOITATION. They are
  not a second wave to throw in when the first fails: they go through the gap once it opens.
- Inside the fight: 2 to 3 units on one enemy unit, spread along the line so several enemies are shaken at once.
- The player does the same to you: he puts three brigades and his cavalry on one end of your line while the rest of
  it watches from out of range. The brigades with nothing in front of them close up on the end being attacked.

CHARGES
- Southern infantry and cavalry are good in close combat: between one more volley and a charge on a shaken enemy,
  charge. Not every unit is superior: judge experience, morale, fatigue and numbers.
- Charge a target that is shaken, reduced, exhausted, already engaged, exposed on a flank, or the weakest in reach
  (CHARGE OPPORTUNITIES, verdict GO), with at least two units, ideally one frontal and one on the flank, while
  others keep firing. Exploit a wavering enemy zone at once: fire, then charge (CHARGE SPARINGLY).
- ASSAULT COLUMN (to take an objective held by a large force, when you have 1.5 to 1 or better; do it EARLY,
  before the enemy's reinforcements come in: Thoroughfare Gap 2026-11-15, 1.5 to 1 at 36-47 min, never more than
  4 brigades within 900 of the Gap, the enemy then grew to 13,000-16,000 men there). Step by step:
  1. GATHER about 80 % of your fit infantry (morale 0.6+, stamina 0.5+) out of rifle range, about 1,250 from the
     objective, on the side you come from. Two ranks: in front one brigade (two for six or more), the biggest, to
     take the fire; 160 behind it the charging brigades, 190 apart. Skirmishers 250 out on both flanks of the
     front rank (against flank attacks), cavalry 450 behind (for the exploitation), batteries on the flanks.
     Keep a fifth of the infantry back as the reserve.
  2. ADVANCE TOGETHER: move every brigade of the column to the same line, about 150 nearer each turn, and wait
     for the late ones before the next step. Brigades that arrive one by one are shot one by one.
  3. PREPARE at 500-600 from the objective: if CHARGE OPPORTUNITIES does not say GO for the defenders, the front
     rank and the guns fire (and the guns may start from 1,100) until the zone is worn down; at most about 5
     minutes, then decide.
  4. CHARGE ALL TOGETHER: every unit with morale and stamina 0.5+ charges the nearest defender in the same turn;
     the exhausted hold and fire. Cavalry follows into the routing enemy.
  5. CALL IT OFF if the column's morale falls under about 0.45, or the zone stays TOO FEW or a fresh enemy reserve
     comes up: back to the gather line, all together.
  In llm_plus mode the server can run these steps for you ("assault_column" in your answer).
- ENVELOPMENT: with the numbers, do not come from one side only. Two or three columns (or a column and the
  reinforcements already on the enemy's flank) arriving at the same time from different directions split the
  defenders' fire and leave them nowhere to fall back. The game's own AI took Thoroughfare Gap closing in from 4 to
  6 directions at once (2026-11-13). Time the groups so that they reach the charge line together.
- CHARGE WHILE FRESH, BUT PREPARED: the best charge comes early in the contact, while your brigades are fresh,
  once fire and guns have worn the enemy zone down and your men there at least equal his (CHARGE SPARINGLY).
  Every minute of trading fire spends the morale the charge needs, so prepare it, then strike; do not throw it at
  a shaken brigade that stands among steady ones or in front of fresh reserves.
- Do not charge a fresh, steady, supported unit on open ground with one tired brigade, nor one in dense forest:
  weaken it with fire and artillery, hit its flank, or charge a weaker neighbour. A mass charge of fresh brigades
  good in melee can break it. Repeaters make frontal charges worse: prefer flanks, rear and local superiority.
- FORTIFICATIONS: charge or assault a unit in fortifications only with a numerical superiority of at least 2 to 1:
  the brigades going in together have twice the men of the target plus the enemy units close enough to support it.
  Go in from a flank when one is open. Under 2 to 1: shell it, pin it with fire from cover, go round it or leave
  it. Do not repeat a charge that failed on the same works.

ENCIRCLEMENT
- To destroy one or more enemy brigades rather than push them back, surround them. Fire from two or three
  directions (front, flank, rear) breaks morale several times faster than fire from the front (FLANK FIRE in the
  rules), and a brigade with no way out does not fall back to rally: it breaks, and the charge finishes it.
- How it ends in this game: a brigade whose morale reaches zero surrenders, more surely the more of your men and the
  fewer of his own stand close to it; a charge on a broken or much reduced brigade can also make it surrender; a
  routing brigade that cavalry or infantry reaches surrenders with all its men. Prisoners count as losses for him.
- The best targets: a brigade that stands out of its line, the end brigade of a line with an open flank, a brigade
  that has just crossed a river or left the woods, a brigade cut off by your breakthrough (EXPLOITATION).
- Method: one or two brigades fix it from the front by fire; one or two others come round on its flank and, if they
  can, its rear (at least 90 degrees apart from the front); the cavalry stands on its way out. When its morale
  falls under about 0.5, or it starts to fall back, all charge together; the cavalry rides down what runs.
- The encircling brigades must not be encircled in turn. Before going round, check what can come to its help
  within about 600 (his reserve, his cavalry, the brigades beside it): pin them by fire or block them with a
  brigade. Do not send a single brigade round alone: two brigades on the flank, or none.

EXPLOITATION
- Keep the cavalry (and one or two fresh brigades) in reserve behind the point of attack, out of fire, until a
  breach opens: an enemy brigade routs or breaks (BREACH in the state) and no steady enemy unit covers the gap.
- Then go through at once, before the gap closes (it closes within minutes). The cavalry charges, in this order:
  batteries left without infantry beside them (take them from the flank or rear, never into the muzzles), then
  routing and shaken units, which surrender when caught, then wagons and generals. Give it "charge" orders on those
  targets: a plain move that ends in front of the line near enemy infantry is dropped by the server.
- The fresh brigades follow through the gap and turn on the flank or rear of the enemy brigades beside it, which
  then have enemies on two sides (ENCIRCLEMENT). Keep the cavalry away from steady infantry, and bring it back
  behind the line once the targets are taken or its morale or men fall: cavalry spent in the breach is gone for the
  next one.

CAVALRY AND ARTILLERY
- Sabre cavalry: isolated, shaken, surprised or retreating troops and exposed batteries, on the flank or rear
  (EXPLOITATION). Carbine cavalry: scouts, screens, harasses, avoids long melee. Only fresh cavalry pursues routers.
- Batteries: enemy artillery, formed brigades and units about to be charged; concentrate them on important targets;
  never fire into friendly troops in melee. A battery in position that fires is worth more than a better position
  it is still marching to.

MORALE AND CONDITION
- Rotate exhausted, shaken or depleted units behind the line and replace them; preserve survivors. Give ground
  rather than brigades: a brigade captured is worth more to the enemy than the ground.

WHEN ATTACKING (AMBITION ATTACK)

SCOUT, FORM, SHOOT, CHARGE, EXPLOIT
1. Scout first: skirmishers and cavalry ahead, the main body 500+ behind. If they find an unexpected force or battery,
   halt and adjust before committing.
2. Form one continuous line on the FRONT LINE PLAN slots before contact (THE LINE AND THE GROUND).
3. Advance and fire. Walk; run only for the last part of a charge, to reach a key spot or to escape.
4. Concentrate on the weak point and charge together (FORCE CONCENTRATION, CHARGES, ENCIRCLEMENT).
5. Exploit the breach with the cavalry and the fresh brigades kept back for it (EXPLOITATION).

TEMPO OF THE ATTACK
- A phase objective not taken by the end of the timer is a lost battle, however well the line is formed. If the
  march to the point takes longer than the time to the launch deadline, you are behind schedule: march now, form
  the line on the way, and let the late brigades join.
- With the enemy near the objective (visible and seen recently, see TEMPO in the ASSAULT PLAN) under a third of your
  strength, launch the assault group at once; do not wait for the rear brigades or the batteries. In woods the
  enemy you see is rarely all the enemy there is: two brigades alone are not an assault.
- Still losing the exchange at 70 % of the phase with no objective in hand: stop trading, concentrate on one point
  and attack it, or fall back onto an objective you hold.
- Fire at the edge of fire range only to shake the enemy so that a charge succeeds; never trade volleys in the open
  for many turns. A unit that has held or fired in range for several turns must charge, advance or be rotated out.

THE ASSAULT
- An assault is a march to firing positions close to the defenders (cover first: wheat, woods' edge,
  fortifications), a few volleys to shake them, then charges, on the WEAK POINT (FORCE CONCENTRATION), from its
  flank when you can. Give the rest of the army orders that feed the assault: batteries and skirmishers on the weak
  point, the cavalry and the exploitation brigades behind it.
- With the numbers, use them early: take the objective the player needs while it is unheld or weakly held, from two
  sides at once. Trading fire while the enemy concentrates on the point wastes the superiority.
- With an aggressive doctrine and two objectives within reach, two assault groups at once beat one group after the
  other: the player must split his attention.
- The last throw (final charge): prepare it. Batteries on the defenders, cavalry on their flank, fresh brigades
  kept fresh for it.

WHEN DEFENDING (AMBITION DEFEND)
- Defend the ground that commands the objective, with one unit on the point itself. Use fortifications and woods.
  Let the enemy cross the open ground into your fire; holding and firing for many turns is the job here.
- The whole line fights. A defence where one brigade trades fire and three watch is a defence of one brigade.

DEFENCE IN DEPTH
- Two echelons. The first line holds the ground and fires. Behind it, a reserve of one or two fresh brigades (and
  the cavalry) stands close: about 200 to 300 behind the first line, out of the enemy's musket range, in cover or
  behind the crest, offset from the brigades in front so that it never masks their fire.
- Close is the point. From there the reserve can counter-charge an enemy that charges or breaks into the first
  line, while he is still in disorder and before he can rally (within about 300, the game's BRACE reflex already
  sends the nearest fresh brigade at an enemy locked in melee with one of yours, without waiting for your turn).
  It also relieves a shaken brigade of the first line, closes a gap, or turns to face a flank attack.
- Give the reserve a "hold" order and keep it nearer than 700 to the nearest enemy: a fresh brigade standing idle
  700 or more from every enemy is sent to the line by the server after minute 20.
- Counter-attack, do not counter-march: when the enemy has charged into the line, the reserve charges the
  attackers' flank, then comes back to its place. When he takes ground above the line, the reserve and the
  nearest brigades retake it together at once (see below), before he brings his guns up.
- Do not answer bait: skirmishers, a lone battery or cavalry in front of the line are there to pull a brigade out.
- The batteries stay in position and fire; the brigade beside them is their guard.
- The defence breaks at an end of the line, with enemy cavalry behind it. Watch the ends, not the centre.
- If the ground above the line is lost, the line below it is lost too: retake it together or move to cover at once.

WHEN OUTNUMBERED OR LOSING
- Do not feed brigades back into the fire one at a time: the player concentrates on each in turn. Break contact
  with the whole line behind a rearguard, rest out of reach, come back together, or keep the army for the next
  battle when this one is lost.
- With a casualty ratio among the goals, every lost assault also loses that condition: defend, and count the men.
- Defending outnumbered: one line on good ground covering the objectives, batteries behind, wagons close, a reserve
  to relieve.
- Losing the exchange with casualties counting: go back into cover and make the enemy come to you across the open.

LESSONS FROM RECORDED BATTLES
- 2026-11-13, Kettle Run (DEFEND, small): even exchange for 40 minutes, then destroyed. Skirmishers with a longer
  range drew Trimble 150 in front of the line; Forno, its neighbour, was then moved 900 west to the objective, below
  the eastern ridge. Three brigades had no enemy in range for 44 minutes while Trimble faced three. Cavalry hit
  its flank at morale 0.55; it routed and surrendered. The battery spent 61 % of its time limbered and was taken by
  the same cavalry. From the ridge the enemy then broke the line below. Of 10,900 men lost, about 4,100 were
  prisoners and 1,500 walked off the map during the withdrawal.
