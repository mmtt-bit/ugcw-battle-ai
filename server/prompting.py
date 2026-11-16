"""Prompt construction, answer parsing and order validation for the AI commander."""
import json
import re
import math

from equipment import (AMMO_MODES, enemy_bore, equipment_brief, equipment_dynamic, equipment_enemy, equipment_text,
                       unit_charge_range, unit_range, unit_width)
from battery import DEFAULT_BATTERY, battery_lines, is_ready
from cavalry import DEFAULT_CAVALRY, cavalry_lines, exposed_move, scouts
from supply import sanitize_supply, supply_lines

# Only these kinds of AI-side units can receive orders (never Generals or Supply units).
COMBAT_KINDS = ("Infantry", "Cavalry", "Artillery", "Skirmish")
MELEE_KINDS = ("Infantry", "Cavalry")             # can charge
FIRING_KINDS = ("Infantry", "Cavalry", "Skirmish")  # flagged when an enemy is in fire range

# Distances (game units) measured by the player: units open fire at 400 and charge at 200.
# They can be changed in config.json ("ranges").
DEFAULT_RANGES = {"fire": 400, "charge": 200}

# Unit states reported by the game (optional "status" field of each unit in the state message).
# "routing" = fleeing, "shattered" = broken, "captured" = surrendered/taken by the enemy.
DEAD_STATUSES = ("routing", "shattered", "captured")
# Thresholds from game_rules.md, also enforced on the server so a weak model cannot break them.
FALLBACK_BELOW = 0.5     # pull back below this share of morale or of initial men
NO_CHARGE_MORALE = 0.4
NO_CHARGE_STAMINA = 0.3


def label(names, uid):
    """'Name (#id)' when the unit name is known, else '#id'."""
    name = names.get(uid) if names else None
    return f"{name} (#{uid})" if name else f"#{uid}"


def order_text(order, names):
    """One order as readable text with unit names: 'charge 3rd Bde (#614) -> Meredith (#649)'."""
    text = f"{order['cmd']} {label(names, order['id'])}"
    if "target" in order:
        text += f" -> {label(names, order['target'])}"
    extra = {k: v for k, v in order.items() if k not in ("cmd", "id", "target")}
    return text + (f" {extra}" if extra else "")


def facing_dot(u, x, z):
    """Cosine between the unit's facing and the direction to (x, z); None if facing is unknown."""
    if "dx" not in u or "dz" not in u:
        return None
    d = math.hypot(x - u["x"], z - u["z"])
    n = math.hypot(u["dx"], u["dz"])
    if d < 1.0 or n < 0.1:
        return None
    return (u["dx"] * (x - u["x"]) + u["dz"] * (z - u["z"])) / (d * n)


def facing_flag(u, x, z):
    """' facing: ...' text telling whether the unit faces the point (usually the nearest enemy)."""
    c = facing_dot(u, x, z)
    if c is None:
        return ""
    if c >= 0.7:
        return ""                       # facing the enemy is the normal case: said only when it is not
    if c >= 0.2:
        return " facing obliquely"
    if c >= -0.3:
        return " SIDE TO ENEMY"
    return " BACK TO ENEMY"


def unit_status(u):
    return str(u.get("status") or "")


def needs_rest(u):
    """True when morale or the men left are under half: the unit should fall back and rest."""
    if u["kind"] not in ("Infantry", "Cavalry", "Skirmish"):
        return False
    if unit_status(u) in DEAD_STATUSES + ("fallback", "melee"):
        return False
    return u["morale"] < FALLBACK_BELOW or u["hp"] / max(u["maxHp"], 1.0) < FALLBACK_BELOW


# JSON schema of the answer, used by backends that can constrain the model output.
ORDERS_SCHEMA = {
    "type": "object",
    "properties": {
        "reasoning": {"type": "string"},
        "plan": {"type": "string"},
        "assaults": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "objective": {"type": "string"},
                    "group": {"type": "array", "items": {"type": "integer"}},
                    "approach": {"type": "array", "items": {"type": "number"}},
                    "launch": {"type": "string", "enum": ["auto", "now", "wait", "release"]},
                },
                "required": ["objective"],
            },
        },
        "assault_column": {
            "type": "object",
            "properties": {
                "objective": {"type": "string"},
                "from": {"type": "array"},
                "go": {"type": "boolean"},
                "cancel": {"type": "boolean"},
            },
        },
        "orders": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "cmd": {"type": "string", "enum": [
                        "move", "attack", "charge", "range_attack",
                        "hold", "fallback", "formation", "gait", "ammo", "supply", "limber", "mount",
                        "detach", "recall", "fortify"]},
                    "id": {"type": "integer"},
                    "x": {"type": "number"},
                    "z": {"type": "number"},
                    "fx": {"type": "number"},
                    "fz": {"type": "number"},
                    "target": {"type": "integer"},
                    "duration": {"type": "number"},
                    "value": {"type": "string"},
                    "artillery": {"type": "boolean"},
                    "infantry": {"type": "boolean"},
                },
                "required": ["cmd", "id"],
            },
        },
    },
    "required": ["reasoning", "orders"],
}

SYSTEM_PROMPT = """\
You are the field commander of the __SIDE__ army in Ultimate General: Civil War, a real-time
battle game. Every few game seconds the game pauses, shows you the battlefield, and waits
for your orders; then it resumes.

COORDINATES AND UNITS
- Positions are (x, z) map coordinates in game units. A few hundred units is a typical
  firing distance; thousands of units is across the map.
- Unit kinds: Infantry, Cavalry, Artillery, Skirmish (detached skirmishers), General, Supply.
- "men" is the current number of soldiers. Morale and stamina range from 0 (bad) to 1 (good).
- Ranges: infantry and cavalry open fire from about __FIRE__ units and can charge from about
  __CHARGE__ units; each unit's own figures (unit notes, YOUR BRIGADES roster) replace these.
  The unit table flags every unit with an enemy in fire range or in charge range.
- Units you never ordered stay under the game's built-in AI.

ORDERS ("id" is one of your unit ids, "target" is a visible enemy unit id)
- {"cmd": "move", "id": 9, "x": 3900, "z": 300}   march to a point (the game finds the path);
  optional "fx","fz": a point to face on arrival (default: the nearest visible enemy)
- {"cmd": "attack", "id": 9, "target": 42}        advance on the target and fire at it
- {"cmd": "charge", "id": 9, "target": 42}        close-combat charge
- {"cmd": "range_attack", "id": 9, "target": 42}  ranged attack on the target
- {"cmd": "hold", "id": 9}                        stand and hold the current position
- {"cmd": "fallback", "id": 9, "duration": 20}    pull back for N seconds (5 to 60); a battery stays unlimbered
__FORMATION__
- {"cmd": "gait", "id": 9, "value": "Walk"}       "Run" or "Walk"
- {"cmd": "supply", "id": 12, "artillery": true, "infantry": true}   SUPPLY WAGON only: kinds it rearms
- {"cmd": "limber", "id": 9, "value": "unpack"}   ARTILLERY only: "unpack" (ready to fire) or "pack"
- {"cmd": "ammo", "id": 9, "value": "canister"}   ARTILLERY only: "auto", "mixed" or "canister"
- {"cmd": "mount", "id": 9, "value": "dismount"}  CAVALRY only: "dismount" (fight on foot) or "mount"
- {"cmd": "detach", "id": 9}                      INFANTRY flagged "can detach skirmishers": detach its skirmish screen
- {"cmd": "recall", "id": 31}                     SKIRMISH screen only: walk back into its brigade
- {"cmd": "fortify", "id": 9, "x": 3900, "z": 300}  INFANTRY: march into the free field work at x,z (see
  FORTIFICATIONS) and occupy it; without x/z, the nearest free work within 400 m
- {"cmd": "move", "id": 16, "x": 3900, "z": 300}  also for a GENERAL: his only order (see GENERALS)
  "limber", "ammo", "mount", "detach" and "recall" do not cancel the unit's other order: they can go with it in
  the same turn.

ANSWER FORMAT
Reply with ONE JSON object and nothing else (no markdown, no code fences):
{"reasoning": "<one or two short sentences>", "plan": "<optional attack plan>", "assaults": [ <assault>, ... ],
 "orders": [ <order>, ... ]}
- "plan": only when the state shows an ASSAULT PLAN block, two to four short sentences (see the rules); the
  server keeps it and shows it back every turn, so send it again only when it changes.
- "assaults" (optional, at most 2): YOUR MACRO COMMAND of the assaults; the server does the micro-management.
  <assault> = {"objective": "<objective name>", "group": [ids of the brigades], "approach": [x, z],
               "launch": "auto" | "now" | "wait" | "release"}
  objective: which objective to take (any objective on the map, not only the one the server suggests); group: the
  brigades that assault it, in the order you want them (omit = the server picks the nearest fit ones); approach: a
  map point on the side the assault comes from (omit = the best approach found by the server); launch: "now" goes
  in at once, "wait" holds it in the staging area (the server still forces it when the timer runs low), "auto"
  leaves the timing to the server's rules, "release" disbands the group. Two assaults may not share brigades.
  The server keeps your last "assaults" and applies it every turn: send it again only to change it (omit it or
  send [] to keep it); launch "release" hands that assault back to the server.
- Two assaults in "assaults" go in TOGETHER (the server waits until both are ready): on one objective from two
  sides (a pincer), or on two objectives so that the player must split his attention.
- FINAL CHARGE: with 20 minutes or less on the timer and the objective still the enemy's, the server sends every
  fresh brigade (morale 0.7+) at it: they close to charge distance (500 over open ground, 200 through woods),
  then all charge together (at 12 minutes left at the latest). Support it, do not order its brigades.
- COMMAND SPLIT: you are the army commander (macro): objectives, assault groups, approach, timing, the reserve, the
  batteries' positions and targets, flank guards, scouting. The server is your staff (micro): routes, staging spots,
  firing positions in cover, sidesteps for fire lanes, target choice inside the group, charges together from close
  range, pull-backs and reflexes. Do not give move/attack orders to the members of an assault group (they are
  ignored, except fallback and short sidesteps): change the "assaults" instead.
- In "reasoning", name units as "Name (#id)", for example "Stonewall Brigade (#614)"; orders use ids only.
- At most __MAX_ORDERS__ orders, and at most one per unit (plus limber/ammo/mount). An empty list is valid when nothing
  needs to change.

READING THE STATE (what the blocks of each turn mean)
- MISSION GOALS: the human player's goals read from the game. What makes the player win is what you must PREVENT.
- STRATEGIC PLAN: computed from those goals; its AMBITION (ATTACK, DEFEND, TRADE) decides attack or defend.
- OBJECTIVE SCORE: objectives held now; the battle is won by holding more objectives, not by killing.
- ASSAULT PLAN: your orders must serve it; the server drives the ASSAULT GROUP, but a member whose line of fire is
  blocked ("lane blocked") is not fighting: sidestep it or move the unit in its way; correct the line around it. FIXING FIRE targets are for the
  batteries and the line. WEAK SIDE is where cavalry and skirmishers go.
- FRONT LINE "in contact": do not re-form the line; stand and fire (hold, attack, range_attack), charge shaken
  enemies in charge range, move only units out of fire range or whose fire is blocked (FIRE LANES).
- FIRE LANES: units whose straight line of fire is blocked by a friendly unit, with a sidestep spot.
- CHARGE OPPORTUNITIES: your infantry or cavalry with a WEAK enemy in charge range (morale under 0.7, falling
  back, or guns / skirmishers / wagons). Steady infantry in reach is not listed. FRESH = your unit has morale and
  stamina 0.8+. Each line counts the zone of 600 around the target (your men vs the enemy's, the enemy morale
  there, fresh enemy reserves) and gives a verdict: GO, PREPARE (fire and guns first), TOO FEW, RECONSIDER
  (fresh enemy reserve near). See CHARGE SPARINGLY.
- RIDE-DOWN OPPORTUNITIES: fresh cavalry and enemy skirmishers or dismounted troops apart from steady infantry.
- CAVALRY: one line per regiment with its role now: "reserve" (behind the line), "reserve, meet its charge" (enemy
  cavalry near), "flank task" (skirmishers to ride down round a flank), "SCOUT NOW". Not for frontal attacks.
- BATTERIES: how many are in range and firing, then only the ones that need a decision. PACKED = limbered, cannot
  fire until unlimbered (limber order, value unpack; the server unpacks a battery that is not marching); a MOVE
  packs a battery, a FALLBACK steps it back and keeps it unlimbered.
- YOUR UNITS table: positions are rounded to 10; "men" is one number at full strength, "now/max" otherwise;
  ground/height = the terrain under the unit and its relief level 0-9 ("-" for units far from every enemy and for
  generals); nearest enemy = "#id at distance" with [in fire range] or [IN CHARGE RANGE]. Wagons are listed only
  under SUPPLY WAGONS. The notes give only what is not the normal case:
  "r442" = the unit's fire range now; "ammo 56%" only under 75 %; PACKED / unlimbering / packing up = a battery
  that cannot fire (nothing = ready); canister / mixed = ammunition mode (nothing = auto); DISMOUNTED = cavalry on
  foot (nothing = mounted); STATUS MELEE / FALLBACK / ROUTING; MARCHING to x,z; the facing (nothing = it faces its
  nearest enemy; "facing obliquely", "SIDE TO ENEMY", "BACK TO ENEMY"); "way 57% slow (DenseForest)" or "way:
  WATER, no ford" = the straight way to its nearest enemy (nothing = open ground). A unit that is not in YOUR
  BRIGADES (a late arrival) shows its full equipment there.
- VISIBLE ENEMY UNITS: nearest first. Notes: "rifled", "breech" (breech-loader, fires faster), "repeater 7" (7
  shots before reloading, about twice the fire: no frontal charge), "revolver 6" (cavalry sidearm, short range),
  "flintlock" (slower), "double", "carbine" (nothing = smoothbore), "r442" = fire range, "ammo" only under 40 %, PACKED, DISMOUNTED, "2*" = veterancy stars. Distant
  units have position, men and morale only. ENEMY PERKS lists each perk once with the ids of the units that have
  it. Captured and shattered units are not listed.
- ORDERS RUNNING: the orders in force, by unit id; "*" = given by the server (your staff), the others are yours.
- MARCHING (unit table): the unit has not finished its last move; do not re-order it unless the situation changed
  (a new order restarts its path). At most 8 moves are accepted per turn; short sidesteps that clear a blocked line
  of fire (FIRE LANES) do not count and are always allowed.
- TIME LEFT: the game's battle timer in MINUTES and as a share of this phase's time (mandatory = the battle ends
  then; recommended = suggested end). "107 minutes" is almost two hours, not one minute.
- TEMPO (ASSAULT PLAN): the share of this phase's time already used, the launch deadline as a share, and the march
  to the objective as a share of the phase. Used share + march share above the deadline = BEHIND SCHEDULE: hurry.
  As a guide: objective named and plan written by 10 % of the phase, the assault group committed by 25 %, the
  reserve by 40 %, objectives taken with a third of the time left to hold them.
- Mounted cavalry shoots only short-range carbines: never give it attack or range_attack on a target beyond its range
  (the server drops those); charge, scout, screen a flank, or keep it out of enemy fire.
- UNSEEN FIRE: your units losing men while no visible enemy stands within their own fire range (hidden, camouflaged
  or out-ranging shooters), the nearest visible enemy, the nearest woods or wheat that can hide them, and your
  doctrine.
- GENERALS needing attention: only generals in danger or with under half of their brigades inside their
  command radius (how far their corps bonuses reach); the server moves the generals with their brigades.
- SUPPLY WAGONS and UNITS LOW ON AMMUNITION: a wagon rearms, by itself, the friendly units of the kinds it is
  switched on for that stand inside its area. To rearm, follow AMMUNITION AND SUPPLY WAGONS in the rules.
- MISSION BRIEFING and OBJECTIVES OF THIS MAP (below, fixed for the battle): the game's own texts.
- YOUR BRIGADES (below): the fixed equipment of your units for this battle (weapon, perks, width...).
- You are called when a decision is worth it (several battle minutes apart, at once for an objective changing
  hands or a broken brigade); between your turns the server keeps executing your last orders and "assaults".

__TERRAIN_SECTION__GAME RULES (these win over the strategy notes)
__RULES__

STRATEGY NOTES FROM THE PLAYER
__STRATEGY__
__ROSTER__"""

TERRAIN_GUIDE = """\
TERRAIN (fixed for this battle)
How to use it:
__ROADS__- Forests (f, F) and fortifications (#) usually give cover. The exact effects reported by the
  game are listed under TERRAIN EFFECTS: rely on them rather than on guesses.
- Crossing water (~) is usually costly: prefer fords (:) and bridges (B). Water marked X cannot
  be entered: a move that ends there is shifted to the nearest passable spot.
- Higher ground usually helps visibility and defence.
- In the unit tables, units near the fight show the terrain they stand on and its relief level
  (0-9), and your units flag slow ground or water on the straight line to their nearest visible
  enemy. The game finds the real path by itself, so use that only as a hint.

"""


# Written only for a map that has road cells (none in the battles recorded so far: the game's roads are drawn on
# grass, and the tooltip of "Road" is the one of "Grass").
ROADS_GUIDE = "- Roads (=): their speed is under TERRAIN EFFECTS; the server's routes follow them when they help.\n"
FORMATION_ORDER = ('- {"cmd": "formation", "id": 9, "value": "Line"}  "Line" or "RoadColumn" (column for long '
                   "marches; back to Line before combat)")


def build_system_prompt(side_name, max_orders, strategy_text, terrain_text="", ranges=None,
                        rules_text="", roster_text="", briefing_text="", has_roads=False, formation_note=None):
    """`has_roads`: the map has road cells. `formation_note`: the line of the ORDERS list about formations
    (march.march_note: who sets them, the model or the server)."""
    ranges = {**DEFAULT_RANGES, **(ranges or {})}
    strategy = strategy_text.strip() or "(none)"
    guide = TERRAIN_GUIDE.replace("__ROADS__", ROADS_GUIDE if has_roads else "")
    section = (guide + terrain_text.strip() + "\n\n") if terrain_text.strip() else ""
    return (SYSTEM_PROMPT.replace("__TERRAIN_SECTION__", section)
            .replace("__FORMATION__", formation_note or FORMATION_ORDER)
            .replace("__SIDE__", side_name)
            .replace("__FIRE__", f"{float(ranges['fire']):.0f}")
            .replace("__CHARGE__", f"{float(ranges['charge']):.0f}")
            .replace("__RULES__", rules_text.strip() or "(none)")
            .replace("__MAX_ORDERS__", str(max_orders))
            .replace("__STRATEGY__", strategy)
            .replace("__ROSTER__", (("\n" + briefing_text.strip() + "\n") if briefing_text.strip() else "")
                     + (("\nYOUR BRIGADES (fixed equipment for this battle)\n" + roster_text.strip() + "\n")
                        if roster_text.strip() else "")))


def format_clock(seconds):
    s = int(seconds)
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def split_units(state):
    """Return (units of the AI side, visible units of the human player side)."""
    player = state["playerSide"]
    mine = [u for u in state["units"] if u["side"] != player]
    foes = [u for u in state["units"] if u["side"] == player]
    return mine, foes


def nearest(unit, others):
    best = None
    for o in others:
        d = math.hypot(o["x"] - unit["x"], o["z"] - unit["z"])
        if best is None or d < best[1]:
            best = (o, d)
    return best


def _xz(u):
    """Position rounded to 10 (the prompt does not need metre precision; fewer tokens every turn)."""
    return f"{round(float(u['x']), -1):.0f},{round(float(u['z']), -1):.0f}"


def _men(u):
    """Men: '2000' for a unit at full strength, '1450/2000' otherwise."""
    hp, mx = float(u["hp"]), float(u.get("maxHp") or u["hp"])
    return f"{hp:.0f}" if hp >= mx - 0.5 else f"{hp:.0f}/{mx:.0f}"


def range_flag(unit, distance, ranges):
    """Short flag telling whether the unit has an enemy in charge range or fire range."""
    if unit["kind"] in MELEE_KINDS and distance <= unit_charge_range(unit, ranges):
        return " [IN CHARGE RANGE]"
    # A unit reports its own current range (weapon, ammunition mode); the config value is the fallback.
    if unit["kind"] in FIRING_KINDS and distance <= unit_range(unit, ranges["fire"]):
        return " [in fire range]"
    if unit["kind"] == "Artillery" and "range" in unit and distance <= unit_range(unit, 0):
        return " [in fire range]"
    return ""


CHARGE_WORTH_MORALE = 0.7   # a charge on a steadier brigade is not an "opportunity" (the server runs assaults)
FRESH_MORALE = 0.8          # WIP12: a charger this fresh (morale and stamina) is marked FRESH in the list
FRESH_STAMINA = 0.8


# WIP15 (Crampton's Gap, 2026-11-14 18:15, model alone): 6th Va and 61st Va (2,079 men) charged Hayes (morale 0.25)
# among 6,500 steady men within 300 and lost 2,500 men in 4 minutes. A charge is judged on the zone around the
# target: men on each side within CHARGE_ZONE, the enemy morale there, and fresh enemy brigades in reserve nearby.
CHARGE_ZONE = 600.0          # the zone counted around the target
CHARGE_ZONE_MORALE = 0.6     # enemy zone morale (men-weighted) under this: worn down, the charge can go in
CHARGE_ZONE_RATIO = 1.0      # your men in the zone at least this share of the enemy's...
BROKEN_ZONE_MORALE = 0.4     # ...or BROKEN_ZONE_RATIO of them once the zone morale is under this: the game's own
BROKEN_ZONE_RATIO = 0.75     # AI won Thoroughfare Gap with zone morale 0.30 and 0.86 of the zone men (median)
RESERVE_FRESH_MORALE = 0.8   # an enemy brigade this steady...
RESERVE_DISTANCE = 900.0     # ...beyond the zone but within this of the target...
RESERVE_ENGAGED = 400.0      # ...and no unit of yours within this of it is a fresh reserve


def charge_zone(target, mine, foes):
    """{"own", "enemy", "morale", "reserves", "verdict"} for a charge on target. Verdict: GO, PREPARE (wear the
    zone down by fire first), TOO FEW (fewer men than the enemy in the zone), RECONSIDER (fresh enemy reserve)."""
    live_foes = [e for e in foes if unit_status(e) not in DEAD_STATUSES and e["kind"] in ("Infantry", "Cavalry")]
    live_mine = [u for u in mine if unit_status(u) not in DEAD_STATUSES and u["kind"] in ("Infantry", "Cavalry")]
    def d(a, b):
        return math.hypot(a["x"] - b["x"], a["z"] - b["z"])
    zone_e = [e for e in live_foes if d(e, target) <= CHARGE_ZONE]
    if target["kind"] in ("Infantry", "Cavalry") and target not in zone_e:
        zone_e.append(target)
    own = sum(float(u["hp"]) for u in live_mine if d(u, target) <= CHARGE_ZONE and u["morale"] >= NO_CHARGE_MORALE)
    enemy = sum(float(e["hp"]) for e in zone_e)
    morale = (sum(float(e["hp"]) * e["morale"] for e in zone_e) / enemy) if enemy > 0 else 0.0
    reserves = [e for e in live_foes if e is not target and e["morale"] >= RESERVE_FRESH_MORALE
                and CHARGE_ZONE < d(e, target) <= RESERVE_DISTANCE   # those in the zone are already counted
                and all(d(e, u) > RESERVE_ENGAGED for u in mine if unit_status(u) not in DEAD_STATUSES)]
    need = BROKEN_ZONE_RATIO if (enemy > 0 and morale < BROKEN_ZONE_MORALE) else CHARGE_ZONE_RATIO
    if own < need * enemy:
        verdict = "TOO FEW"
    elif reserves:
        verdict = "RECONSIDER"
    elif enemy > 0 and morale >= CHARGE_ZONE_MORALE:
        verdict = "PREPARE"
    else:
        verdict = "GO"
    return {"own": own, "enemy": enemy, "morale": morale, "reserves": reserves, "verdict": verdict}


def charge_opportunities(mine, foes, ranges, limit=12):
    """Own infantry/cavalry with a weak enemy in charge range (shaken, falling back, or guns / skirmishers /
    wagons): the weakest one in reach. Steady infantry in reach is not listed: every brigade in contact has one."""
    lines = []
    for u in mine:
        if (u["kind"] not in MELEE_KINDS or unit_status(u) in DEAD_STATUSES
                or u["morale"] < NO_CHARGE_MORALE or u["fatigue"] < NO_CHARGE_STAMINA):
            continue
        reach = [e for e in foes
                 if unit_status(e) not in DEAD_STATUSES and math.hypot(e["x"] - u["x"], e["z"] - u["z"]) <= unit_charge_range(u, ranges)]
        if not reach:
            continue
        weakest = min(reach, key=lambda e: (e["morale"], e["hp"] / max(e["maxHp"], 1.0)))
        if (weakest["morale"] >= CHARGE_WORTH_MORALE and unit_status(weakest) != "fallback"
                and weakest["kind"] in ("Infantry", "Cavalry")):
            continue
        dist = math.hypot(weakest["x"] - u["x"], weakest["z"] - u["z"])
        fresh = u["morale"] >= FRESH_MORALE and float(u.get("fatigue", 0)) >= FRESH_STAMINA
        z = charge_zone(weakest, mine, foes)
        res = (f", {len(z['reserves'])} fresh enemy brigade(s) in reserve within {RESERVE_DISTANCE:.0f}"
               if z["reserves"] else "")
        lines.append(f"- #{u['id']} {u['name']}{' FRESH' if fresh else ''} -> #{weakest['id']} {weakest['name']} "
                     f"({weakest['kind']}, {weakest['hp']:.0f} men, morale {weakest['morale']:.2f}) at {dist:.0f}"
                     f" | zone {CHARGE_ZONE:.0f}: yours {z['own']:.0f} vs {z['enemy']:.0f} men, enemy morale "
                     f"{z['morale']:.2f}{res}: {z['verdict']}")
    return lines[:limit]


DEFAULT_LINE = {"enabled": True, "spacing": 70, "max_spacing": 150, "standoff": 360,
                "min_enemy_units": 1, "tolerance": 120}


# A unit needs a clear straight line to its target: a friendly unit inside this corridor in front
# of it blocks its fire. Units closer than CLEARANCE to each other are stacked.
LANE_WIDTH = 45        # half-width of the firing lane (game units)
LANE_LENGTH = 300      # how far in front of a unit a friendly unit still blocks it
CLEARANCE = 70         # minimum distance between two friendly units
SHOOTERS = ("Infantry", "Cavalry", "Skirmish")
BLOCKERS = ("Infantry", "Cavalry", "Skirmish", "Artillery")
MAX_MOVES_ENGAGED = 3  # at most this many move orders per turn once the lines are in fire range
MAX_MOVES_TURN = 8     # and at most this many in any turn (re-ordering units restarts their pathing);
                       # short sidesteps that clear a blocked line of fire are not counted


def lane_half(w_shooter, w_blocker):
    """Half-width of the firing lane: wider brigades block and need a wider corridor."""
    return max(LANE_WIDTH, 0.25 * (w_shooter + w_blocker))


def in_lane(shooter, target, blocker, half=None):
    """True if `blocker` stands in the firing lane from `shooter` towards `target` (x, z tuples)."""
    dx, dz = target[0] - shooter[0], target[1] - shooter[1]
    dist = math.hypot(dx, dz)
    if dist < 1.0:
        return False
    ux, uz = dx / dist, dz / dist
    bx, bz = blocker[0] - shooter[0], blocker[1] - shooter[1]
    along = bx * ux + bz * uz
    side = abs(-bx * uz + bz * ux)
    return 10.0 < along < min(dist - 10.0, LANE_LENGTH) and side < (LANE_WIDTH if half is None else half)


def lane_blocker(u, foes, friends):
    """The friendly unit blocking u's fire at its nearest enemy (within fire range), or None."""
    live = [e for e in foes if unit_status(e) not in DEAD_STATUSES]
    near = nearest(u, live)
    if not near:
        return None
    target = (near[0]["x"], near[0]["z"])
    for v in friends:
        if v is u or v["kind"] not in BLOCKERS or unit_status(v) in DEAD_STATUSES:
            continue
        if in_lane((u["x"], u["z"]), target, (v["x"], v["z"]), lane_half(unit_width(u), unit_width(v))):
            return v
    return None


def spot_is_clear(spot, me, friends, planned, foes):
    """Is `spot` free of stacking, and neither blocked by nor blocking a friendly unit's fire?"""
    wme = unit_width(me)
    others = [(v["x"], v["z"], unit_width(v)) for v in friends if v is not me and v["kind"] in BLOCKERS
              and unit_status(v) not in DEAD_STATUSES] + [(q[0], q[1], wme) for q in planned]
    # Two units are stacked when closer than half their widths together (at least CLEARANCE).
    if any(math.hypot(spot[0] - o[0], spot[1] - o[1]) < max(CLEARANCE, 0.5 * (wme + o[2]) + 10.0) for o in others):
        return False
    live = [e for e in foes if unit_status(e) not in DEAD_STATUSES]
    if not live:
        return True
    near = min(live, key=lambda e: math.hypot(e["x"] - spot[0], e["z"] - spot[1]))
    target = (near["x"], near["z"])
    if any(in_lane(spot, target, (o[0], o[1]), lane_half(wme, o[2])) for o in others):   # someone stands in front of us
        return False
    for v in friends:                                             # we would stand in front of someone
        if v is me or v["kind"] not in SHOOTERS or unit_status(v) in DEAD_STATUSES:
            continue
        vn = min(live, key=lambda e: math.hypot(e["x"] - v["x"], e["z"] - v["z"]))
        if math.hypot(vn["x"] - v["x"], vn["z"] - v["z"]) <= LANE_LENGTH + 150 and \
                in_lane((v["x"], v["z"]), (vn["x"], vn["z"]), spot, lane_half(unit_width(v), wme)):
            return False
    return True


def find_clear_spot(x, z, me, friends, planned, foes, terrain=None):
    """Return (x, z) at or beside the wanted spot that keeps every firing lane open, else None."""
    live = [e for e in foes if unit_status(e) not in DEAD_STATUSES]
    if live:
        near = min(live, key=lambda e: math.hypot(e["x"] - x, e["z"] - z))
        dx, dz = near["x"] - x, near["z"] - z
        d = math.hypot(dx, dz) or 1.0
        ax, az = -dz / d, dx / d                  # sideways, along the line
    else:
        ax, az = 1.0, 0.0
    step = max(CLEARANCE, unit_width(me) + 10.0)     # a wide brigade has to shift by at least its width
    for k in (0, 1, -1, 2, -2, 3, -3):
        cx, cz = x + ax * step * k, z + az * step * k
        if terrain is not None:
            spot = terrain.nearest_passable(cx, cz)
            if spot is None:
                continue
            cx, cz = spot
        if spot_is_clear((cx, cz), me, friends, planned, foes):
            return round(cx, 1), round(cz, 1)
    return None


def front_line_plan(mine, foes, ranges, line_cfg=None, terrain=None, memory=None):
    """Suggest a continuous firing line facing the visible enemy.

    The line is perpendicular to the direction from the enemy centre to our centre. It is as wide
    as the visible enemy front (so it "matches" it), evenly spaced, and set a stand-off distance
    from the nearest enemy unit (a bit inside fire range). Our line infantry are assigned to the
    slots in order of their position along the line, so that nobody has to cross another unit.
    Returns the prompt lines (empty when there is nothing sensible to suggest).
    """
    cfg = {**DEFAULT_LINE, **(line_cfg or {})}
    if not cfg["enabled"]:
        return []
    enemy = [e for e in foes if e["kind"] in ("Infantry", "Cavalry", "Artillery")
             and unit_status(e) not in DEAD_STATUSES]
    line = [u for u in mine if u["kind"] == "Infantry" and unit_status(u) not in DEAD_STATUSES
            and not needs_rest(u) and u["morale"] >= NO_CHARGE_MORALE]
    if len(enemy) < cfg["min_enemy_units"] or not line:
        return []
    ex = sum(e["x"] for e in enemy) / len(enemy)
    ez = sum(e["z"] for e in enemy) / len(enemy)
    mx = sum(u["x"] for u in line) / len(line)
    mz = sum(u["z"] for u in line) / len(line)
    d = math.hypot(mx - ex, mz - ez)
    if d < 1.0:
        return []
    nx, nz = (mx - ex) / d, (mz - ez) / d      # from the enemy towards us
    ax, az = -nz, nx                           # along the line
    along = lambda x, z: (x - ex) * ax + (z - ez) * az
    depth = lambda x, z: (x - ex) * nx + (z - ez) * nz
    e_min = min(along(e["x"], e["z"]) for e in enemy)
    e_max = max(along(e["x"], e["z"]) for e in enemy)
    e_mid, e_width = (e_min + e_max) / 2.0, e_max - e_min
    k = len(line)
    spacing = min(max(e_width / max(k - 1, 1), cfg["spacing"]), cfg["max_spacing"]) if k > 1 else 0.0
    front = max(depth(e["x"], e["z"]) for e in enemy)       # enemy unit nearest to us
    slot_depth = front + cfg["standoff"]
    closest = min(math.hypot(u["x"] - e["x"], u["z"] - e["z"]) for u in line for e in enemy)
    if closest <= float(ranges["fire"]) + 150:
        # Contact: the line is what it is. Re-forming under fire is what loses battles.
        return ["FRONT LINE: in contact (stand and fire; see READING THE STATE)."]
    ordered = sorted(line, key=lambda u: along(u["x"], u["z"]))
    # Slot positions along the line: the base spacing, but never closer than the two neighbouring brigades
    # need (half of each width plus a gap): a 6000-man brigade is much wider than a 1500-man one.
    pos = [0.0]
    for i in range(1, k):
        need = 0.5 * (unit_width(ordered[i - 1]) + unit_width(ordered[i])) + 10.0
        pos.append(pos[-1] + max(spacing, need))
    centre = sum(pos) / k
    widest = max(unit_width(u) for u in ordered)
    out = [f"FRONT LINE PLAN (enemy front: {len(enemy)} visible units spread over {e_width:.0f} units; "
           f"your line infantry: {k}, spacing {spacing:.0f} or more (neighbours are kept apart by their widths, "
           f"widest brigade {widest:.0f}), stand-off {cfg['standoff']:.0f} "
           f"from the nearest enemy unit):"]
    moves = 0
    fire = float(ranges["fire"])
    engaged = 0
    for i, u in enumerate(ordered):
        a = e_mid + pos[i] - centre
        sx, sz = ex + a * ax + slot_depth * nx, ez + a * az + slot_depth * nz
        if memory is not None:
            # Keep each unit's slot while the enemy has not moved much: a slot that follows the
            # enemy every turn makes the line shuffle forever.
            anchor = memory.get("anchor")
            if anchor and math.hypot(ex - anchor[0], ez - anchor[1]) < 250 and u["id"] in memory["slots"]:
                sx, sz = memory["slots"][u["id"]]
            else:
                if not anchor or math.hypot(ex - anchor[0], ez - anchor[1]) >= 250:
                    memory["anchor"], memory["slots"] = (ex, ez), {}
                memory["slots"][u["id"]] = (sx, sz)
        near = nearest(u, enemy)
        if near and near[1] <= fire:
            engaged += 1      # already in fire range: it must stand and fire, not be moved
            continue
        if terrain is not None:
            spot = terrain.nearest_passable(sx, sz)
            if spot is None:
                continue
            sx, sz = spot
        off = math.hypot(sx - u["x"], sz - u["z"])
        c = facing_dot(u, ex, ez)
        if off <= cfg["tolerance"] and c is not None and c < 0.7:
            moves += 1
            out.append(f"- {u['id']} {u['name']}: in position but not facing the enemy "
                       f"(move to {sx:.0f},{sz:.0f} to turn it)")
        elif off <= cfg["tolerance"]:
            out.append(f"- {u['id']} {u['name']}: in position")
        else:
            moves += 1
            out.append(f"- {u['id']} {u['name']}: now {u['x']:.0f},{u['z']:.0f} -> slot {sx:.0f},{sz:.0f} "
                       f"({off:.0f} away)")
    if len(out) > 45:
        out = out[:45] + ["- ..."]
    if engaged:
        out.append(f"{engaged} of your line units are already in fire range of the enemy: they must STAND "
                   "and fire (hold, attack or range_attack). Do NOT move them to re-form the line: a "
                   "moving unit cannot fire.")
    out.append("Every unit of the line must FACE THE ENEMY: a unit that shows its back or side takes "
               "a morale penalty. Moves automatically end facing the nearest enemy.")
    out.append("Move units to their slots (move order) unless they are charging, in melee or "
               "in a better position; keep the line continuous and evenly spaced. A charge may "
               "temporarily leave the line: send the charging units back to a slot once it is over.")
    return out if (moves or engaged) else []


def fire_lane_lines(mine, foes, ranges, terrain=None, limit=12):
    """Units in fire range whose straight line to the enemy is blocked by a friendly unit."""
    out = []
    fire = float(ranges["fire"])
    for u in mine:
        if u["kind"] not in SHOOTERS or unit_status(u) in DEAD_STATUSES:
            continue
        live = [e for e in foes if unit_status(e) not in DEAD_STATUSES]
        near = nearest(u, live)
        if not near or near[1] > fire:
            continue
        blocker = lane_blocker(u, foes, mine)
        if blocker is None:
            continue
        spot = find_clear_spot(u["x"], u["z"], u, mine, [], foes, terrain)
        hint = (f"sidestep to {spot[0]:.0f},{spot[1]:.0f} (move order, short)" if spot and
                math.hypot(spot[0] - u["x"], spot[1] - u["z"]) <= 250 else "ask for a short sidestep")
        out.append(f"- {u['name']} (#{u['id']}) cannot fire at #{near[0]['id']}: {blocker['name']} "
                   f"(#{blocker['id']}) stands in its line of fire. {hint}")
    if not out:
        return []
    return ["FIRE LANES (blocked lines of fire):"] + out[:limit]


# ----- wearing a steady enemy down, and keeping the guns safe -----------------------------------
WEAR_RADIUS = 600          # units this close to the target take part in the plan
THREAT_INFANTRY = 350      # a battery with infantry this close is in danger (charge range + margin)
THREAT_CAVALRY = 550       # cavalry covers the ground much faster
COVER_RADIUS = 200         # a covering unit must stand this close to the battery
RETREAT_DISTANCE = 350


def _live(units):
    return [e for e in units if unit_status(e) not in DEAD_STATUSES]


def wear_down_plan(mine, foes, ranges):
    """Pick a steady enemy unit and split nearby units into expendable chargers and a follow-up.

    Returns None or {"target", "sacrifice": [...], "follow": [...]}. Fire alone does not shake a
    steady, fresh unit; a charge costs the defender men and morale even when it fails, so a few
    expendable units charge first and the best brigades hit the disordered target right after.
    """
    eligible = [u for u in mine
                if u["kind"] in MELEE_KINDS and unit_status(u) == "" and not needs_rest(u)
                and u["morale"] >= NO_CHARGE_MORALE + 0.05 and u["fatigue"] >= NO_CHARGE_STAMINA + 0.1]
    best = None
    for e in _live(foes):
        if e["kind"] not in MELEE_KINDS or e["morale"] < 0.5:
            continue
        near = [u for u in eligible if math.hypot(u["x"] - e["x"], u["z"] - e["z"]) <= WEAR_RADIUS]
        if len(near) < 3:
            continue
        key = (len(near), -e["morale"])
        if best is None or key > best[0]:
            best = (key, e, near)
    if best is None:
        return None
    _, target, near = best
    value = lambda u: (u.get("stars") or 0, u["hp"])          # lower = more expendable
    ordered = sorted(near, key=value)
    sacrifice = ordered[:2]
    follow = sorted(ordered[2:], key=lambda u: (-(u.get("stars") or 0), -u["morale"]))[:2]
    return {"target": target, "sacrifice": sacrifice, "follow": follow}


def wear_down_lines(mine, foes, ranges):
    plan = wear_down_plan(mine, foes, ranges)
    if not plan:
        return []
    t = plan["target"]
    fmt = lambda u: f"{u['name']} (#{u['id']}, {u['hp']:.0f} men, morale {u['morale']:.2f})"
    return [
        "WEAR-DOWN PLAN (your fire is not shaking a steady enemy; do not keep attacking it frontally "
        "one brigade after another):",
        f"- Target: {t['name']} (#{t['id']}, {t['hp']:.0f} men, morale {t['morale']:.2f}).",
        "- Step 1, this turn: charge it with the expendable units " + " and ".join(fmt(u) for u in plan["sacrifice"])
        + ". Even a charge that does not break it costs it men and morale and leaves it disordered.",
        "- Step 2, as soon as they are in melee or it wavers: attack with " +
        (" and ".join(fmt(u) for u in plan["follow"]) if plan["follow"] else "your best fresh brigade")
        + " (charge once it is below morale 0.5), while the other units keep firing at it.",
        "- Do not use units under morale 0.45 or stamina 0.4 as chargers; do not repeat the plan on a target "
        "that is already shaken: use CHARGE OPPORTUNITIES then."]


def threatened_batteries(mine, foes):
    """Batteries with enemy infantry or cavalry close and no friendly infantry or cavalry covering.

    Returns a list of (battery, nearest threatening enemy, distance). A battery is covered when a
    steady friendly infantry or cavalry unit stands within COVER_RADIUS and nearer to that enemy.
    """
    out = []
    live_foes = [e for e in _live(foes) if e["kind"] in MELEE_KINDS]
    guards = [u for u in _live(mine) if u["kind"] in MELEE_KINDS and unit_status(u) == "" and u["morale"] >= 0.5]
    for b in _live(mine):
        if b["kind"] != "Artillery":
            continue
        near = None
        for e in live_foes:
            d = math.hypot(e["x"] - b["x"], e["z"] - b["z"])
            limit = THREAT_CAVALRY if e["kind"] == "Cavalry" else THREAT_INFANTRY
            if d <= limit and (near is None or d < near[1]):
                near = (e, d)
        if near is None:
            continue
        e, d = near
        # (a guard standing right beside a wide battery covers it too: brigades and batteries are 150-250 wide)
        covered = any(
            math.hypot(g["x"] - b["x"], g["z"] - b["z"]) <= max(COVER_RADIUS, 0.5 * (unit_width(g) + unit_width(b)) + 60.0)
            and math.hypot(g["x"] - e["x"], g["z"] - e["z"]) < d
            for g in guards)
        if not covered:
            out.append((b, e, d))
    return out


def retreat_spot(b, e, mine, foes, terrain=None, distance=RETREAT_DISTANCE):
    """A clear spot behind the battery, away from the threatening enemy."""
    dx, dz = b["x"] - e["x"], b["z"] - e["z"]
    n = math.hypot(dx, dz) or 1.0
    x, z = b["x"] + dx / n * distance, b["z"] + dz / n * distance
    return find_clear_spot(x, z, b, mine, [], foes, terrain)


def artillery_risk_lines(mine, foes, terrain=None):
    risks = threatened_batteries(mine, foes)
    if not risks:
        return []
    lines = ["ARTILLERY AT RISK (a battery must never stand alone in front of a brigade at charge range; "
             "it cannot defend itself in melee):"]
    for b, e, d in risks:
        spot = retreat_spot(b, e, mine, foes, terrain)
        advice = (f"pull it back to {spot[0]:.0f},{spot[1]:.0f} now (move), or place a steady brigade "
                  f"within {COVER_RADIUS} units in front of it" if d > 150 else
                  "too late to limber up: switch it to canister (ammo) and cover it with infantry")
        lines.append(f"- {b['name']} (#{b['id']}) has {e['name']} (#{e['id']}, {e['kind']}) at {d:.0f} and no "
                     f"cover: {advice}.")
    return lines


def compact_order(o):
    """Short form of an order for ORDERS RUNNING (ids only)."""
    txt = f"#{o['id']} {o['cmd']}"
    if o.get("target") is not None:
        txt += f" #{o['target']}"
    elif o.get("x") is not None:
        txt += f" {round(float(o['x']), -1):.0f},{round(float(o['z']), -1):.0f}"
    elif o.get("value") is not None:
        txt += f" {o['value']}"
    return txt + ("*" if o.get("auto") else "")


def build_user_prompt(state, previous_orders, events, terrain=None, ranges=None, line_cfg=None, extra_lines=None, line_memory=None, plan_mode=None, roster=None, scale=None, marching=None):
    """The state of one turn. Written for few tokens: the prompt of a turn is never read from the cache, so every
    character is paid at every call. Normal cases are not written (see READING THE STATE in the system prompt).
    `scale` (config.json "scale") gives the radii inside which a unit gets its full line."""
    ranges = {**DEFAULT_RANGES, **(ranges or {})}
    mine_all, foes_all = split_units(state)
    # units out of the battle (captured, shattered) are not listed; a captured unit changes side in the game and
    # would otherwise show up as an enemy brigade
    gone = ("captured", "shattered")
    mine = [u for u in mine_all if unit_status(u) not in gone]
    foes = [u for u in foes_all if unit_status(u) not in gone]
    foes_live = [e for e in foes if unit_status(e) not in DEAD_STATUSES]
    sc = scale or {}
    detail_r = sc.get("detail_radius")
    route_r = sc.get("route_radius")
    # 0.1.4 WIP10: the clock of this phase (the game's own mission clock), the whole battle's in brackets. The model
    # read the cumulated clock of two chained phases (95 to 226 min in a phase of 142 min) on 2026-11-13.
    if state.get("phaseTime") is not None and abs(float(state["phaseTime"]) - float(state["time"])) > 60.0:
        lines = [f"Battle time elapsed: {format_clock(float(state['phaseTime']))} in this phase "
                 f"({format_clock(state['time'])} since the first phase)", ""]
    else:
        lines = [f"Battle time elapsed: {format_clock(state['time'])}", ""]
    lines.append("YOUR UNITS (id | name | kind | x,z | men | morale | stamina | ground/height | nearest enemy | notes):")
    wagons_listed = bool(supply_lines(state))
    for u in mine:
        if u["kind"] == "Supply" and wagons_listed and u.get("supplyStock") is not None:
            continue                                   # listed once, under SUPPLY WAGONS
        near = nearest(u, foes_live)
        near_txt = (f"#{near[0]['id']} at {near[1]:.0f}{range_flag(u, near[1], ranges)}"
                    if near else "none visible")
        line = (f"{u['id']} | {u['name']} | {u['kind']} | {_xz(u)} | "
                f"{_men(u)} | {u['morale']:.2f} | {u['fatigue']:.2f}")
        notes = []
        if unit_status(u):
            notes.append(f"STATUS {unit_status(u).upper()}")
        if marching and u["id"] in marching:
            dest = marching[u["id"]]
            notes.append(f"MARCHING to {round(dest[0], -1):.0f},{round(dest[1], -1):.0f}")
        if u.get("canScout"):
            notes.append("can detach skirmishers")
        if u["kind"] == "Skirmish" and u.get("owner") is not None:
            notes.append(f"screen of #{u['owner']}")
        in_roster = roster is not None and u.get("id") in roster
        equip = equipment_brief(u) if in_roster else equipment_text(u, roster)
        staff = u["kind"] in ("General", "Supply")
        far = bool(detail_r) and u["kind"] != "Artillery" and (not near or near[1] > float(detail_r))
        if far or staff:
            # far from the fight, or not a fighting unit: position, strength and state are enough
            if staff:
                equip = " ".join(b for b in equip.split(" ") if not b.startswith("r")) if in_roster else equip
            line += " | - | " + near_txt
        else:
            ground = f"{terrain.name_at(u['x'], u['z'])}/{terrain.height_at(u['x'], u['z'])}" if terrain else "-"
            line += f" | {ground} | {near_txt}"
            if near:
                flag = facing_flag(u, near[0]["x"], near[0]["z"]).strip()
                if flag:
                    notes.append(flag)
                if terrain and (not route_r or near[1] <= float(route_r)):
                    way = terrain.route_brief(u["x"], u["z"], near[0]["x"], near[0]["z"], u["kind"])
                    if way:
                        notes.append(way)
        if equip:
            notes.insert(0, equip)
        if notes:
            line += " | " + "; ".join(notes)
        lines.append(line)
    # a captured unit stands on its captor's side in the state: our prisoners are among the enemy's units and the
    # prisoners we took among ours
    out_mine = (sum(1 for u in mine_all if unit_status(u) == "shattered")
                + sum(1 for u in foes_all if unit_status(u) == "captured"))
    out_foes = (sum(1 for u in foes_all if unit_status(u) == "shattered")
                + sum(1 for u in mine_all if unit_status(u) == "captured"))
    if out_mine:
        lines.append(f"(+{out_mine} of your units shattered or captured, not listed)")
    lines.append("")
    if foes:
        enemy_r = sc.get("enemy_detail_radius", 900)
        max_detail = sc.get("max_enemy_detail", 30)
        dist = {e["id"]: (nearest(e, mine) or (None, 1e9))[1] for e in foes}
        listed = sorted(foes, key=lambda e: dist[e["id"]])      # nearest first
        near_ids = [e["id"] for e in listed if unit_status(e) not in DEAD_STATUSES
                    and (not enemy_r or dist[e["id"]] <= float(enemy_r))]
        detailed = set(near_ids[:int(max_detail)] if max_detail else near_ids)
        lines.append("VISIBLE ENEMY UNITS, nearest first (id | name | kind | x,z | men | morale | ground/height | notes):")
        perk_ids = {}
        for u in listed:
            line = (f"{u['id']} | {u['name']} | {u['kind']} | {_xz(u)} | "
                    f"{u['hp']:.0f} | {u['morale']:.2f}")
            notes = []
            if unit_status(u):
                notes.append(f"STATUS {unit_status(u).upper()}")
            if u["id"] in detailed:
                if terrain:
                    line += f" | {terrain.name_at(u['x'], u['z'])}/{terrain.height_at(u['x'], u['z'])}"
                bits = [b for b in (enemy_bore(u), equipment_brief(u, own=False)) if b]
                if u.get("stars"):
                    bits.append(f"{int(u['stars'])}*")
                if bits:
                    notes.append(" ".join(bits))
                for p in (u.get("perks") or []):
                    if p:
                        perk_ids.setdefault(str(p), []).append(u["id"])
            if notes:
                line += " | " + "; ".join(notes)
            lines.append(line)
        if perk_ids:
            lines.append("ENEMY PERKS (unit ids): " + "; ".join(
                f"{p}: " + ",".join(str(i) for i in ids) for p, ids in sorted(perk_ids.items())))
    else:
        lines.append("VISIBLE ENEMY UNITS: none")
    if out_foes:
        lines.append(f"(+{out_foes} enemy units shattered or captured, not listed)")
    plan_lines = front_line_plan(mine, foes, ranges, line_cfg, terrain, line_memory)
    if plan_lines:
        lines.append("")
        lines.extend(plan_lines)
    lane_lines = fire_lane_lines(mine, foes, ranges, terrain, int(sc.get("max_lanes", 12)))
    if lane_lines:
        lines.append("")
        lines.extend(lane_lines)
    opportunities = charge_opportunities(mine, foes, ranges, int(sc.get("max_charge", 12)))
    if opportunities:
        lines.append("")
        lines.append("CHARGE OPPORTUNITIES (your unit -> weak enemy in its charge range):")
        lines.extend(opportunities)
    battery = battery_lines(state)
    cav = cavalry_lines(state)
    if cav:
        battery = battery + [""] + cav
    risk_lines = (artillery_risk_lines(mine, foes, terrain) + ([""] if battery else []) + battery
                  + ([""] if supply_lines(state) else []) + supply_lines(state))
    if risk_lines:
        lines.append("")
        lines.extend(risk_lines)
    if not opportunities:
        wear = wear_down_lines(mine, foes, ranges) if plan_mode in (None, "ATTACK") else []
        if wear:
            lines.append("")
            lines.extend(wear)
    if previous_orders:
        lines.append("")
        names = {u["id"]: u["name"] for u in state["units"]}
        lines.append("ORDERS RUNNING (* = given by the server): "
                     + "; ".join(compact_order(o) for o in previous_orders[:40]))
    if events:
        lines.append("EVENTS SINCE LAST TURN: " + "; ".join(events[-10:]))
    if extra_lines:
        lines.append("")
        lines.extend(extra_lines)
    lines.append("")
    lines.append("Give your orders as the JSON object described in the instructions.")
    return "\n".join(lines)


def _balance_fix(text):
    """Common slips of a model writing JSON by hand: an extra closing brace before ']' ("}}]"), trailing commas."""
    out = re.sub(r",\s*([\]}])", r"\1", text)
    fixed, depth, in_str, esc = [], [], False, False
    for ch in out:
        if in_str:
            fixed.append(ch)
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            depth.append(ch)
        elif ch in "}]":
            want = "{" if ch == "}" else "["
            if not depth or depth[-1] != want:
                continue                               # a closer that closes nothing: drop it
            depth.pop()
        fixed.append(ch)
    return "".join(fixed) + "".join("}" if d == "{" else "]" for d in reversed(depth))


def _unescape(text):
    """A JSON string body cut out by a regex, with its escapes decoded (left as it is when it cannot be)."""
    try:
        return json.loads('"' + text + '"')
    except ValueError:
        return text


def load_answer(text):
    """The JSON object of the model answer as a dict. Tolerant: code fences, an extra brace, a trailing comma or
    a cut-off end are repaired; as a last resort the flat order objects are salvaged one by one. Raises ValueError
    only when nothing usable is found (a lost answer costs a whole model call)."""
    if isinstance(text, dict):
        return text
    text = str(text or "").strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object in the answer")
    body = text[start:end + 1]
    for candidate in (body, _balance_fix(body), _balance_fix(text[start:])):
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                return data
        except ValueError:
            continue
    orders, assaults = [], []
    for m in re.finditer(r"\{[^{}]*\}", body):
        try:
            obj = json.loads(m.group(0))
        except ValueError:
            continue
        if isinstance(obj, dict) and "cmd" in obj:
            orders.append(obj)
        elif isinstance(obj, dict) and "objective" in obj:
            assaults.append(obj)
    if not orders and not assaults:
        raise ValueError("the answer is not valid JSON and no order could be salvaged")
    data = {"orders": orders, "_salvaged": True}
    if assaults:
        data["assaults"] = assaults
    m = re.search(r'"reasoning"\s*:\s*"((?:[^"\\]|\\.)*)"', body)
    data["reasoning"] = _unescape(m.group(1)) if m else ""
    m = re.search(r'"plan"\s*:\s*"((?:[^"\\]|\\.)*)"', body)
    if m:
        data["plan"] = _unescape(m.group(1))
    return data


def parse_answer(text):
    """Extract the JSON object from the model text. Returns (reasoning, raw_orders)."""
    data = load_answer(text)
    orders = data.get("orders", [])
    if not isinstance(orders, list):
        raise ValueError("'orders' is not a list")
    return str(data.get("reasoning", "")), orders


def extract_plan(text):
    """The optional "plan" text of the model answer ('' when there is none or the JSON cannot be read)."""
    try:
        data = load_answer(text)
        return " ".join(str(data.get("plan") or "").split())[:600]
    except (ValueError, AttributeError, TypeError):
        return ""


def extract_assaults(text):
    """The optional "assaults" macro command of the model answer: None when absent or empty (keep the previous
    one), else a list of at most 2 cleaned directives."""
    try:
        data = load_answer(text)
    except (ValueError, AttributeError, TypeError):
        return None
    if not isinstance(data, dict) or "assaults" not in data:
        return None
    raw = data.get("assaults")
    if not isinstance(raw, list):
        return None
    if not raw:
        # an empty list is what models write for "nothing to change": it must not reset a running assault
        # (the documented way to hand an assault back is launch "release")
        return None
    out, used = [], set()
    for a in raw[:2]:
        if not isinstance(a, dict) or not str(a.get("objective") or "").strip():
            continue
        d = {"objective": str(a["objective"]).strip()}
        ids = [i for i in (_to_int(x) for x in (a.get("group") or [])) if i is not None and i not in used]
        if ids:
            d["group"] = ids
            used.update(ids)
        ap = a.get("approach")
        if isinstance(ap, (list, tuple)) and len(ap) >= 2:
            try:
                d["approach"] = [float(ap[0]), float(ap[1])]
            except (TypeError, ValueError):
                pass
        launch = str(a.get("launch") or "auto").lower()
        d["launch"] = launch if launch in ("auto", "now", "wait", "release") else "auto"
        out.append(d)
    return out


def _to_int(value):
    try:
        if isinstance(value, bool):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


FACE_MAX_DISTANCE = 1500   # only auto-face an enemy that is this close to the destination


def _face_point(raw, order, foes):
    """Point the unit should face at the end of a move: the model's choice, else the nearest enemy."""
    try:
        return round(float(raw["fx"]), 1), round(float(raw["fz"]), 1)
    except (KeyError, TypeError, ValueError):
        pass
    best = None
    for e in foes:
        if unit_status(e) in DEAD_STATUSES:
            continue
        d = math.hypot(e["x"] - order["x"], e["z"] - order["z"])
        if best is None or d < best[0]:
            best = (d, e)
    if best is None or best[0] > FACE_MAX_DISTANCE:
        return None
    return round(best[1]["x"], 1), round(best[1]["z"], 1)


def sanitize(raw_orders, state, max_orders, terrain=None, fire_range=None, pending_moves=None, stats=None):
    return _sanitize(raw_orders, state, max_orders, terrain, fire_range, pending_moves, stats)


def _sanitize(raw_orders, state, max_orders, terrain, fire_range, pending_moves, stats=None):
    raw_orders, wagon_orders = sanitize_supply(raw_orders, state, terrain, None, stats)
    return _sanitize_combat(raw_orders, state, max_orders, terrain, fire_range, pending_moves, stats) + wagon_orders


def _sanitize_combat(raw_orders, state, max_orders, terrain, fire_range, pending_moves, stats=None):
    bump = (lambda key: stats.__setitem__(key, stats.get(key, 0) + 1)) if stats is not None else (lambda key: None)
    """Keep only well-formed orders for units we may command. Never trust the model blindly."""
    mine, foes = split_units(state)
    mine_ids = {u["id"] for u in mine
                if u["kind"] in COMBAT_KINDS and unit_status(u) not in DEAD_STATUSES}
    by_id = {u["id"]: u for u in mine}
    foe_ids = {u["id"] for u in foes}
    foe_by_id = {u["id"]: u for u in foes}
    clean, seen = [], set()
    planned, moves_done = [], 0
    ammo_orders = []
    limber_orders = []
    engaged_turn = bool(fire_range) and any(
        u["kind"] in SHOOTERS and (nearest(u, [e for e in foes if unit_status(e) not in DEAD_STATUSES])
                                   or (None, 1e9))[1] <= float(fire_range)
        for u in mine if unit_status(u) not in DEAD_STATUSES)
    for o in raw_orders:
        if not isinstance(o, dict):
            continue
        cmd, uid = o.get("cmd"), _to_int(o.get("id"))
        if uid not in mine_ids or (uid in seen and cmd not in ("ammo", "limber", "mount")):
            continue
        order = {"cmd": cmd, "id": uid}
        if cmd == "move":
            try:
                x, z = float(o["x"]), float(o["z"])
            except (KeyError, TypeError, ValueError):
                continue
            if terrain is not None:
                # Clamp to the playable area and move off impassable terrain (deep water).
                spot = terrain.nearest_passable(x, z)
                if spot is None:
                    continue
                x, z = spot
            order["x"], order["z"] = round(x, 1), round(z, 1)
            me = by_id[uid]
            if (me["kind"] == "Cavalry" and uid not in scouts(state, DEFAULT_CAVALRY)
                    and exposed_move(me, order["x"], order["z"], state, DEFAULT_CAVALRY)):
                bump("cavalry moves dropped (in front of the line, near enemy infantry)")
                continue
            if me["kind"] == "Artillery" and is_ready(me):
                near_e = nearest(me, [e for e in foes if unit_status(e) not in DEAD_STATUSES])
                step = math.hypot(order["x"] - me["x"], order["z"] - me["z"])
                if (near_e and step <= DEFAULT_BATTERY["backstep_max"]
                        and math.hypot(order["x"] - near_e[0]["x"], order["z"] - near_e[0]["z"]) > near_e[1]):
                    bump("short battery backsteps turned into fallback (stays unlimbered)")
                    clean.append({"cmd": "fallback", "id": uid, "duration": DEFAULT_BATTERY["fallback_seconds"]})
                    seen.add(uid)
                    if len(clean) >= max_orders:
                        break
                    continue
            sidestep = (me["kind"] in FIRING_KINDS and lane_blocker(me, foes, mine) is not None
                        and math.hypot(order["x"] - me["x"], order["z"] - me["z"]) <= 250)
            if fire_range and me["kind"] in FIRING_KINDS:
                near = nearest(me, [e for e in foes if unit_status(e) not in DEAD_STATUSES])
                # the unit's own weapon range (a musket brigade 450 away is not "in fire range" because the
                # config says 500: its move to close in must stay a move)
                if near and near[1] <= float(unit_range(me, fire_range) or fire_range) and not sidestep:
                    # A moving unit cannot fire: a unit in fire range stands and shoots instead.
                    bump("moves turned into range_attack (unit in fire range)")
                    order = {"cmd": "range_attack", "id": uid, "target": near[0]["id"]}
                    if needs_rest(me):
                        order = {"cmd": "fallback", "id": uid, "duration": 25.0}
                    clean.append(order)
                    seen.add(uid)
                    if len(clean) >= max_orders:
                        break
                    continue
            # Units in fire range were turned into range_attack above (unless sidestepping): the moves left are
            # sidesteps and units out of range (reserves, flanks, line corrections), which are allowed.
            if engaged_turn and not sidestep and moves_done >= max(MAX_MOVES_ENGAGED, MAX_MOVES_TURN):
                bump("moves dropped (too many moves while in contact)")
                continue
            if not sidestep and moves_done >= MAX_MOVES_TURN:
                bump("moves dropped (more than the moves allowed in one turn)")
                continue
            old = (pending_moves or {}).get(uid)
            if old and math.hypot(old[0] - order["x"], old[1] - order["z"]) < 150:
                bump("moves dropped (same destination as an unfinished move)")
                continue   # same destination as an unfinished move: let it finish
            spot = find_clear_spot(order["x"], order["z"], me, mine, planned, foes, terrain)
            if spot is None:
                bump("moves dropped (no spot that avoids stacking and blocked fire lanes)")
                continue   # no spot that avoids stacking and keeps the firing lanes open
            if abs(spot[0] - order["x"]) + abs(spot[1] - order["z"]) > 1.0:
                bump("move destinations shifted (stacking or fire lane)")
            order["x"], order["z"] = spot
            planned.append(spot)
            if not sidestep:
                moves_done += 1
            face = _face_point(o, order, foes)
            if face is not None:
                order["fx"], order["fz"] = face
        elif cmd in ("attack", "charge", "range_attack"):
            target = _to_int(o.get("target"))
            if target not in foe_ids:
                continue
            if cmd == "charge" and by_id[uid].get("mount") in ("dismounted", "dismounting", "mounting"):
                bump("charges by dismounted cavalry dropped (mount first)")
                continue
            if cmd == "charge":
                me, foe = by_id[uid], foe_by_id[target]
                if (me["kind"] not in MELEE_KINDS or me["morale"] < NO_CHARGE_MORALE
                        or me["fatigue"] < NO_CHARGE_STAMINA or unit_status(me) in DEAD_STATUSES
                        or unit_status(foe) in DEAD_STATUSES):
                    bump("charges refused (shaken, tired or beaten target)")
                    continue   # game_rules.md: never charge when shaken/exhausted or at a beaten unit
            order["target"] = target
        elif cmd == "ammo":
            # Ammunition mode of a battery. It does not replace the unit's other order.
            if by_id[uid]["kind"] != "Artillery" or o.get("value") not in AMMO_MODES:
                continue
            ammo_orders.append({"cmd": "ammo", "id": uid, "value": o["value"]})
            continue
        elif cmd == "limber":
            if by_id[uid]["kind"] != "Artillery" or o.get("value") not in ("pack", "unpack"):
                continue
            limber_orders.append({"cmd": "limber", "id": uid, "value": o["value"]})
            continue
        elif cmd == "mount":
            me = by_id[uid]
            if me["kind"] != "Cavalry" or o.get("value") not in ("mount", "dismount"):
                continue
            if o["value"] == "dismount" and me.get("canDismount") is False:
                bump("dismount orders dropped (shock cavalry or in a fortification)")
                continue
            if me.get("mount") in (("dismounted", "dismounting") if o["value"] == "dismount" else ("mounted", "mounting")):
                continue                                     # already in (or going to) that mode
            limber_orders.append({"cmd": "mount", "id": uid, "value": o["value"]})
            continue
        elif cmd in ("detach", "recall"):
            # 0.1.4 WIP10: skirmish screens (plugin UnitExtras.Detach / Recall)
            me = by_id[uid]
            if cmd == "detach" and not me.get("canScout"):
                bump("detach orders dropped (this brigade cannot detach skirmishers now)")
                continue
            if cmd == "recall" and (me["kind"] != "Skirmish" or me.get("owner") is None):
                continue
            limber_orders.append({"cmd": cmd, "id": uid})
            continue
        elif cmd == "fortify":
            # WIP17 (Antietam: 703 work cells, never more than 3 AI brigades in them): plugin UnitExtras.Fortify
            if by_id[uid]["kind"] != "Infantry" or by_id[uid].get("fort"):
                bump("fortify orders dropped (not infantry, or already in a work)")
                continue
            try:
                if o.get("x") is not None and o.get("z") is not None:
                    order["x"], order["z"] = float(o["x"]), float(o["z"])
            except (TypeError, ValueError):
                pass
        elif cmd == "hold":
            if by_id[uid]["kind"] == "Artillery" and uid in (pending_moves or {}):
                bump("holds dropped (a battery still on its march: a hold would leave it packed)")
                continue
        elif cmd == "fallback":
            try:
                order["duration"] = min(max(float(o.get("duration", 20)), 5.0), 60.0)
            except (TypeError, ValueError):
                order["duration"] = 20.0
        elif cmd == "formation":
            if o.get("value") not in ("Line", "RoadColumn"):
                continue
            order["value"] = o["value"]
        elif cmd == "gait":
            if o.get("value") not in ("Run", "Walk"):
                continue
            order["value"] = o["value"]
        else:
            continue
        if needs_rest(by_id[uid]) and cmd not in ("fallback", "hold", "formation", "gait"):
            bump("orders replaced by fallback (morale or men under half)")
            order = {"cmd": "fallback", "id": uid, "duration": 25.0}   # game_rules.md: rest
        clean.append(order)
        seen.add(uid)
        if len(clean) >= max_orders:
            break
    return clean + ammo_orders[:max_orders] + limber_orders[:max_orders]
