"""Assault on an objective: the attack plan the AI must have when it has to take a point the player holds.

In the battle of 2026-11-09 19:36 the mission asked the AI to take Logan Cross (the player held it and the
AI could not win without it), but the AI traded fire for 125 minutes and never came near the point: 8 attack
orders in the whole battle. This module makes the attack happen and shows the model the plan:

* the BRIEFING lines show the mission text read in the game and the objectives;
* the ASSAULT PLAN lines name the objective, its defenders, a staging area on the side we come from, the
  assault group (the freshest infantry brigades), the weak side for the cavalry and the batteries' targets;
* `assault_orders` enforces it: the group walks to the staging area (STAGING), then, when most of it has
  arrived or after a time-out (LAUNCHED), it attacks the defenders one by one, or walks onto the point when
  no defender is visible. Orders it adds carry "auto": true. A group that loses too much is released.

The model keeps the initiative for everything else (artillery, skirmishers, cavalry, the rest of the line) and
may write its own attack plan in the "plan" field of its answer; the server shows it back every turn.
Switch it off in config.json ("assault").
"""
import math

from equipment import unit_range, unit_width, fire_weight
import perks as perks_mod
from supply import known_enemies
from prompting import CLEARANCE, DEAD_STATUSES, facing_dot, find_clear_spot, in_lane, nearest, split_units, unit_status

DEFAULT_ASSAULT = {
    "enabled": True,
    "launch_minutes": 6.0,        # battle time before which the army is still deploying
    "group_share": 0.45,          # share of the infantry brigades in the assault group
    "group_min": 2,
    "group_max": 5,               # floor of the cap...
    "target_ratio": 1.5,          # 0.1.4 WIP7: the group grows until its strength is this many times the defenders'
    "reserve_min": 1,             # ...keeping at least this many fit brigades out of it
    "launch_floor_ratio": 1.0,    # the deadline or a long wait launch only at this ratio or above
    "converge": True,             # a group of `converge_min` brigades or more stages in two wings...
    "converge_min": 4,
    "converge_angle": 50.0,       # ...this many degrees either side of the approach, and goes in together
    "group_max_share": 0.12,      # ...raised to this share of the infantry brigades in large armies
    "min_morale": 0.65,           # to join the group
    "min_strength": 0.5,          # share of starting men, to join the group
    "stage_distance": 0.0,        # 0 = from the objective: max(capture range + 200, fire range + 120)
    "stage_clear": 600.0,         # 0.1.4 WIP10: ...and at least this far (or the enemy's range + 150) from every enemy
    "stage_radius": 130.0,        # a brigade this close to its staging spot has arrived
    "stage_timeout_s": 420.0,     # launch after this long even if the group is not complete
    "stage_refresh_s": 300.0,     # staging spots are kept this long (a new spot is a new order: the march restarts)
    "ready_share": 0.7,           # share of the group that must have arrived to launch
    "launch_min_ratio": 1.5,      # group strength / defenders' strength needed to launch (0.6 before WIP7)...
    "max_wait_s": 900.0,          # ...but the assault goes in anyway after waiting this long in the staging area
    "strong_ratio": 2.0,          # with this local superiority the group goes in as soon as...
    "strong_ready_share": 0.5,    # ...this share of it has arrived (time given to the defender is time to fortify)
    "latest_launch_minutes": 35.0,  # battle time after which a staged group goes in anyway (unless paused)
    "stage_angles": [0, -20, 20, -40, 40],   # staging directions tried (degrees from the direct approach)
    "defender_radius": 650.0,     # enemy units this close to the point are its defenders
    "max_orders_per_turn": 5,
    "abort_loss_share": 0.35,     # the group is released when it has lost this share of its men
    "abort_pause_s": 600.0,
    "briefing_chars": 700,
    "launch_time_share": 0.7,     # with a battle timer: launch at the latest when only this share of the time is left
    "defender_memory_s": 600.0,   # defenders seen this recently still count (hidden in woods is not gone)
    "approach_margin": 250.0,     # a launched brigade further than its range + this from its target first marches
                                  # to a firing position (cover preferred) instead of an "attack" order
    "cover_weight": 700.0,        # march distance a covered firing spot is worth (per point of cover x damage)
    "charge_morale": 0.5,         # launched brigades charge a defender in reach whose morale fell under this...
    "charge_when_strong": False,  # ...or (aggressive doctrine) any defender in reach when the group is strong_ratio up
    "charge_min_morale": 0.7,     # a brigade charges only with this morale or more
    "max_charges_per_turn": 4,
    "charge_max_distance": 200.0, # (kept for older configs; see charge_open_distance / charge_slow_distance)
    "charge_open_distance": 500.0,  # charges start from this far at most over open ground...
    "charge_slow_distance": 200.0,  # ...and from this far when the way is mostly slow ground (woods, scrub, mud)
    "fresh_charge_slow_distance": 400.0,  # WIP12: ...or this far for a fresh brigade (fresh_charge_morale and
    "fresh_charge_morale": 0.8,           # fresh_charge_stamina): the 15:48 battle charged nothing in the forest
    "fresh_charge_stamina": 0.8,
    "charge_slow_share": 0.25,    # share of slow ground on the way above which the short distance applies
    "close_charge_strength": 0.7, # at the short distance a fresh brigade charges if it has this share of the
                                  # target's men or more
    "charge_together": 2,         # brigades that must be in reach to charge at once (a lone shaken target excepted)
    "reserve_keep": None,         # aggressive doctrine: every fit infantry brigade but this many joins the group
    "split_min_infantry": 6,      # with two objectives to take and this many brigades, one assault on each
    # 0.1.4 (battle of 2026-11-11): rested brigades for the assault, a weak point taken in the flank, mass charges,
    # and covered firing positions instead of chasing in the open
    "eve_morale": 0.8,            # a brigade joining a group that has not gone in yet needs this morale (the group
                                  # is topped up with min_morale brigades only when too few have it)
    "weak_point": True,           # pick the weakest defender (morale, experience, men, support) as the first target
    "weak_flank": True,           # ...and stage on its flank when the game says which way it faces
    "flank_distance": 700.0,      # how far out on the flank the approach comes from
    "weak_bonus": 400.0,          # a launched brigade prefers the weak point as a target (distance it is worth)
    "flank_dot": 0.3,             # a target whose facing makes less than this cosine with the charger: flank or rear
    "mass_charge_morale": 0.8,    # brigades this fresh and good in melee charge a steady defender together...
    "mass_charge_stamina": 0.5,   # ...with this much stamina...
    "mass_charge_min": 2,         # ...when at least this many are in reach (a lone brigade only charges weak targets)
    "trade_cover_move": 250.0,    # a launched brigade trading fire steps this far at most to a better covered spot
    "trade_cover_gain": 0.3,      # ...when the spot's fire value is this much better than where it stands
    "trade_cover_every_s": 120.0, # ...at most once in this many battle seconds per brigade (each move stops its fire)
}


def _share(u):
    return float(u["hp"]) / max(float(u["maxHp"]), 1.0)


def _live(units):
    return [u for u in units if unit_status(u) not in DEAD_STATUSES]


def _dist(a, b):
    return math.hypot(a["x"] - b["x"], a["z"] - b["z"])


def pick_target(plan_info, mine):
    """The objective to assault: of the ones the plan needs, the nearest to our army (most VP on ties)."""
    targets = (plan_info or {}).get("targets") or []
    if not targets or not mine:
        return None
    cx = sum(u["x"] for u in mine) / len(mine)
    cz = sum(u["z"] for u in mine) / len(mine)
    return min(targets, key=lambda o: (math.hypot(o["x"] - cx, o["z"] - cz) - 0.2 * float(o.get("victoryPoints") or 0)))


def stage_distance(obj, cfg, ranges):
    if float(cfg["stage_distance"]) > 0:
        return float(cfg["stage_distance"])
    capture = float(obj.get("captureRange") or obj.get("radius") or 150.0)
    return max(capture + 200.0, float((ranges or {}).get("fire", 400)) + 120.0)


def group_worth(units):
    return sum(u["hp"] * (0.5 + 0.5 * u["morale"]) for u in units)


def select_group(mine, foes, obj, cfg, mem, wanted=None, exclude=(), join_morale=None, need=0.0):
    """The assault group: brigades kept from earlier turns while they are fit, topped up with the nearest fit ones.
    `wanted`: the brigades the model named in its assault directive (macro command), used as given while fit.
    `exclude`: brigades already in another assault group.
    `need` (0.1.4 WIP7): the strength (men x morale, as group_worth) the group must reach, `target_ratio` times
    the defenders': brigades are added beyond the usual size until it is reached, keeping `reserve_min` back.
    Units still off the map (entering) are never chosen."""
    mine = [u for u in mine if not u.get("offmap")]
    if wanted:
        ok = {u["id"]: u for u in _live(mine)
              if u["id"] not in exclude and u["kind"] in ("Infantry", "Skirmish", "Cavalry")
              and u["morale"] >= 0.75 * float(cfg["min_morale"]) and unit_status(u) in ("",)}
        return [ok[i] for i in wanted if i in ok]
    inf = [u for u in _live(mine) if u["kind"] == "Infantry" and u["id"] not in exclude]
    cap = max(int(cfg["group_max"]), int(round(float(cfg.get("group_max_share", 0.0)) * len(inf))))
    size = max(int(cfg["group_min"]), min(cap, int(round(float(cfg["group_share"]) * len(inf)))))
    if cfg.get("reserve_keep") is not None:
        # aggressive attack: the assault gets the brigades nearest the objective, only a small reserve stays back
        size = max(size, len(inf) - int(cfg["reserve_keep"]))
    size = min(size, len(inf))
    fit = {u["id"]: u for u in inf
           if u["morale"] >= float(cfg["min_morale"]) * (0.75 if u["id"] in mem.get("group", []) else 1.0)
           and _share(u) >= float(cfg["min_strength"]) and unit_status(u) in ("",)}
    keep = [i for i in mem.get("group", []) if i in fit]
    # nearest first; brigades whose perks favour assault (charge damage, steadiness in melee) count as nearer
    rest = sorted((u for i, u in fit.items() if i not in keep),
                  key=lambda u: _dist(u, obj) - 400.0 * perks_mod.role_score(u, "assault"))
    if join_morale is not None:
        # newcomers rested enough to last the assault first; the others only to reach the group's minimum size
        rested = [u for u in rest if u["morale"] >= float(join_morale)]
        others = [u for u in rest if u["morale"] < float(join_morale)]
        need = max(0, int(cfg["group_min"]) - len(keep) - len(rested))
        rest = rested + others[:need]
    chosen = keep[:size] + [u["id"] for u in rest[:max(0, size - len(keep))]]
    if need > 0:
        spare = [u["id"] for u in rest if u["id"] not in chosen]
        room = len(fit) - int(cfg.get("reserve_min", 1))
        while spare and len(chosen) < room and group_worth([fit[i] for i in chosen]) < need:
            chosen.append(spare.pop(0))
    return [fit[i] for i in chosen]


def _stage_spots_raw(group, obj, cfg, ranges, mine, foes, terrain=None, approach=None):
    """One staging spot per brigade, side by side on the side of the objective we come from."""
    if not group:
        return {}
    cx = sum(u["x"] for u in group) / len(group)
    cz = sum(u["z"] for u in group) / len(group)
    dx, dz = cx - obj["x"], cz - obj["z"]
    n = math.hypot(dx, dz) or 1.0
    if approach:
        # the model chose the side the assault comes from (macro command): stage between it and the objective
        ax, az = float(approach[0]) - obj["x"], float(approach[1]) - obj["z"]
        an = math.hypot(ax, az)
        if an > 1:
            dx, dz, n = ax, az, max(n, an)
    ux, uz = dx / (math.hypot(dx, dz) or 1.0), dz / (math.hypot(dx, dz) or 1.0)
    d = min(stage_distance(obj, cfg, ranges), max(n, 1.0))      # never "stage" behind where we already are
    bx, bz = obj["x"] + ux * d, obj["z"] + uz * d
    if terrain is not None and hasattr(terrain, "path_profile"):
        # Choose the staging direction whose approach to the objective crosses the least slow ground (woods,
        # scrub, mud slow the assault and tire the men), with a small cost for turning away from the direct line.
        best = None
        for ang in cfg.get("stage_angles") or [0]:
            a = math.radians(float(ang))
            vx, vz = ux * math.cos(a) - uz * math.sin(a), ux * math.sin(a) + uz * math.cos(a)
            sx, sz = obj["x"] + vx * d, obj["z"] + vz * d
            if not terrain.passable(sx, sz):
                continue
            _, eff, _ = terrain.path_profile(sx, sz, obj["x"], obj["z"])
            score = eff + (300.0 if terrain.is_slow(sx, sz) else 0.0) + 3.0 * abs(float(ang))
            if best is None or score < best[0]:
                best = (score, sx, sz, vx, vz)
        if best is not None:
            _, bx, bz, ux, uz = best
    px, pz = -uz, ux
    spacing = max(CLEARANCE, max(unit_width(u) for u in group) + 25.0)
    # order the brigades along the line so that nobody has to cross another one
    ordered = sorted(group, key=lambda u: (u["x"] - cx) * px + (u["z"] - cz) * pz)

    def line(units, x0, z0, lx, lz):
        out = {}
        for k, u in enumerate(units):
            off = (k - (len(units) - 1) / 2.0) * spacing
            x, z = x0 + lx * off, z0 + lz * off
            if terrain is not None:
                snapped = terrain.nearest_passable(x, z)
                if snapped is not None:
                    x, z = snapped
            out[u["id"]] = (round(x, 1), round(z, 1))
        return out

    if cfg.get("converge") and not approach and len(group) >= int(cfg.get("converge_min", 4)):
        # 0.1.4 WIP7: two wings, either side of the approach, so that the defenders are hit from two directions
        # at once (the launch is common to the whole group). One line of brigades is a frontal assault on a
        # position the enemy can face with all of its fire.
        half = len(ordered) // 2
        wings = []
        for units, sign in ((ordered[:half], -1.0), (ordered[half:], 1.0)):
            a = math.radians(sign * float(cfg.get("converge_angle", 50.0)))
            vx, vz = ux * math.cos(a) - uz * math.sin(a), ux * math.sin(a) + uz * math.cos(a)
            wx, wz = obj["x"] + vx * d, obj["z"] + vz * d
            if terrain is not None and not terrain.passable(wx, wz):
                wings = None
                break
            wings.append((units, wx, wz, -vz, vx))
        if wings:
            spots = {}
            for units, wx, wz, lx, lz in wings:
                spots.update(line(units, wx, wz, lx, lz))
            return spots
    return line(ordered, bx, bz, px, pz)


def stage_spots(group, obj, cfg, ranges, mine, foes, terrain=None, approach=None):
    """Staging spots (see _stage_spots_raw), each moved back, away from the objective, until it stands at least
    `stage_clear` (or the enemy's own fire range + 150) from every enemy unit seen or remembered.

    0.1.4 WIP10: the spots were counted from the objective only (capture range + 200, or fire range + 120). At Malvern
    Hill (2026-11-13) the Union stood in front of its objectives: the spots fell 20 to 185 from Union brigades. For
    35 minutes not one brigade of the group reached its spot; they stood 250 to 500 from the enemy, arrived one by
    one, lost 10,766 men for 2,272 seen, and the assault never went in (local ratio up to 1.96)."""
    spots = _stage_spots_raw(group, obj, cfg, ranges, mine, foes, terrain, approach)
    clear = float(cfg.get("stage_clear", 600.0))
    if clear <= 0 or not spots:
        return spots
    enemies = [e for e in known_enemies(_live(foes)) if e.get("kind") in ("Infantry", "Skirmish", "Cavalry", "Artillery")]
    if not enemies:
        return spots

    def need(e):
        if e.get("kind") == "Artillery":
            return clear                      # out of a battery's reach is out of the map: its canister is enough
        return max(clear, float(e.get("range") or 0.0) + 150.0)

    out = {}
    for uid, (x, z) in spots.items():
        dx, dz = x - obj["x"], z - obj["z"]
        n = math.hypot(dx, dz) or 1.0
        ux, uz = dx / n, dz / n
        px, pz = x, z
        for step in range(0, 1601, 50):
            qx, qz = x + ux * step, z + uz * step
            if terrain is not None and hasattr(terrain, "inside") and not terrain.inside(qx, qz):
                break
            if terrain is not None and hasattr(terrain, "passable") and not terrain.passable(qx, qz):
                continue
            px, pz = qx, qz
            if all(math.hypot(qx - e["x"], qz - e["z"]) >= need(e) for e in enemies):
                break
        out[uid] = (round(px, 1), round(pz, 1))
    return out


def defenders_of(obj, foes, cfg):
    r = max(float(cfg["defender_radius"]), float(obj.get("captureRange") or 0.0))
    near = [e for e in _live(foes) if math.hypot(e["x"] - obj["x"], e["z"] - obj["z"]) <= r]
    return sorted(near, key=lambda e: math.hypot(e["x"] - obj["x"], e["z"] - obj["z"]))


def weak_score(e, defenders):
    """Lower = weaker: morale, experience (stars), men left, stamina, and the support of other defenders nearby.
    Skirmishers and batteries count as weak in melee."""
    share = float(e.get("hp", 0)) / max(float(e.get("maxHp") or e.get("hp") or 1.0), 1.0)
    support = sum(1 for d in defenders if d["id"] != e["id"] and _dist(d, e) <= 250.0)
    # a unit with breech-loaders or repeaters is not a weak point for a frontal assault (equipment.FIRE_WEIGHT)
    return (float(e.get("morale", 1.0)) + 0.12 * float(e.get("stars") or 0) + 0.4 * share
            + 0.2 * float(e.get("fatigue", 1.0)) + 0.08 * support + 0.3 * (fire_weight(e) - 1.0)
            - (0.3 if e.get("kind") in ("Skirmish", "Artillery") else 0.0))


def weak_point(defenders, mem=None):
    """The weakest defender (see weak_score); the one chosen before is kept unless another is clearly weaker."""
    cands = [e for e in defenders if e.get("kind") in ("Infantry", "Skirmish", "Artillery", "Cavalry")]
    if not cands:
        return None
    scored = sorted(cands, key=lambda e: weak_score(e, defenders))
    old = next((e for e in cands if e["id"] == (mem or {}).get("weak")), None)
    if old is not None and weak_score(old, defenders) <= weak_score(scored[0], defenders) + 0.15:
        return old
    return scored[0]


def flank_approach(weak, defenders, group, cfg, terrain=None, keep_side=None):
    """A point on the flank of the weak defender to stage from: beside it (its facing from the game), on the side
    with the fewest other defenders and nearest our group. None when the game gives no facing."""
    fx, fz = weak.get("dx"), weak.get("dz")
    if fx is None or fz is None or math.hypot(fx, fz) < 0.1:
        return None
    n = math.hypot(fx, fz)
    px, pz = -fz / n, fx / n
    gx = sum(u["x"] for u in group) / len(group)
    gz = sum(u["z"] for u in group) / len(group)
    far = float(cfg["flank_distance"])
    best = None
    for side in (1.0, -1.0):
        # on the flank, a little to the front of the defender's line (the side our army comes from)
        x = weak["x"] + side * px * far + fx / n * 0.25 * far
        z = weak["z"] + side * pz * far + fz / n * 0.25 * far
        if terrain is not None and not terrain.passable(x, z):
            continue
        crowd = sum(max(0.0, 600.0 - math.hypot(d["x"] - x, d["z"] - z)) for d in defenders if d["id"] != weak["id"])
        cost = crowd + 0.3 * math.hypot(x - gx, z - gz)
        if keep_side is not None and keep_side == ("left" if side > 0 else "right"):
            cost -= 1e6                                # the side chosen before: the march is not restarted
        if best is None or cost < best[0]:
            best = (cost, x, z, "left" if side > 0 else "right")
    return None if best is None else (best[1], best[2], best[3])


def flanked(e, u, cfg):
    """True when `u` stands on the flank or in the rear of the enemy `e` (from its facing)."""
    c = facing_dot(e, u["x"], u["z"])
    return c is not None and c < float(cfg["flank_dot"])


def melee_good(u, e):
    """A brigade worth a charge on a steady unit: assault perks, experience, or more men than the target (more
    still when the target fires faster: the charge crosses its fire, see equipment.FIRE_WEIGHT)."""
    return (perks_mod.role_score(u, "assault") > 0 or float(u.get("stars") or 0) >= 2
            or float(u["hp"]) >= 1.1 * fire_weight(e) * float(e["hp"]))


def lane_blocked(u, target, mine):
    """The friendly unit standing in the straight line of fire from u to target, or None."""
    for f in mine:
        if f["id"] == u["id"] or unit_status(f) in DEAD_STATUSES:
            continue
        if in_lane((u["x"], u["z"]), (target["x"], target["z"]), (f["x"], f["z"])):
            return f
    return None


TIMER_MAX_MINUTES = 240.0   # a "timer" longer than this is the end of the day, not a deadline (see phase_clock)


def phase_clock(state):
    """(share of the phase's time already used, whole time of the phase in s, time left in s), or None without a
    battle timer. The whole time is time left + time already spent in this mission (phase), so it is right after
    loading a saved battle too (the server's own phase clock restarts at the load).
    A timer longer than TIMER_MAX_MINUTES counts as none (0.1.4 WIP7): in the battle of 2026-11-12 10:12 the
    "timer" was the end of the day, 720 minutes, so the assault deadline (36 %) fell at minute 259; the player
    ended the battle at minute 149 and the assault never went in."""
    b = state.get("briefing") or {}
    left = b.get("timeLeftS")
    if left is None:
        return None
    left = float(left)
    spent = b.get("missionElapsedS")
    spent = float(spent) if spent is not None else float(state.get("phaseTime", 0.0))
    total = left + spent
    if total <= 0 or total > TIMER_MAX_MINUTES * 60.0:
        return None
    return spent / total, total, left


def time_share_left(state, mem=None):
    """Share of the phase's time still left (from the battle timer), or None without a timer."""
    c = phase_clock(state)
    return None if c is None else 1.0 - c[0]


def assault_orders(state, orders, plan_info, cfg, last_cmds, pending_moves, ranges, terrain, mem, stats=None,
                   exclude=()):
    """Returns (ids whose own order is dropped, new orders). `mem` is a dict kept between turns.
    plan_info["directive"] (optional) is the model's macro command for this assault: group, approach, launch."""
    cfg = {**DEFAULT_ASSAULT, **(cfg or {}), **((plan_info or {}).get("cfg_override") or {})}
    directive = (plan_info or {}).get("directive") or {}
    if (plan_info or {}).get("sync") is not None:
        # until this assault says otherwise, it does not hold its partner back (no group, paused, released...)
        plan_info["sync"][plan_info.get("sync_key", 0)] = True
    if directive.get("launch") == "release":
        if mem.get("group"):
            print(f"  Assault on {mem.get('objective')} released by the model")
        mem.update(launched=False, group=[])
        mem.pop("first_arrival", None)
        return set(), []
    now = float(state.get("time", 0.0))
    phase_s = float(state.get("phaseTime", now))      # minutes are counted from the start of this map (phase)
    mine_all, foes = split_units(state)
    mine = _live(mine_all)
    if (not cfg["enabled"] or not plan_info or plan_info.get("mode") != "ATTACK" or not mine
            or phase_s / 60.0 < float(cfg["launch_minutes"])):
        if not plan_info or plan_info.get("mode") != "ATTACK":
            mem.pop("launched", None)
            mem.pop("group", None)
        return set(), []
    if now < float(mem.get("paused_until", 0.0)):
        if directive.get("launch") != "now":
            return set(), []
        mem["paused_until"] = 0.0                     # the commander sends it back in: his call
    obj = pick_target(plan_info, mine)
    if obj is None:
        return set(), []
    # the group is sized to the defenders (0.1.4 WIP7): `target_ratio` times their strength, hidden ones included
    d_now = defenders_of(obj, foes, cfg)
    d_ids = {e["id"] for e in d_now}
    d_hidden = [v for k, v in (mem.get("defenders_seen") or {}).items() if k not in d_ids]
    need = float(cfg.get("target_ratio", 1.5)) * (group_worth(d_now) + group_worth(d_hidden))
    mem["need_worth"] = need
    group = select_group(mine, foes, obj, cfg, mem, directive.get("group"), exclude,
                         None if mem.get("launched") else cfg.get("eve_morale"),
                         0.0 if mem.get("launched") else need)
    if not group:
        return set(), []
    mem["objective"] = obj.get("name")
    mem["group"] = [u["id"] for u in group]
    men = sum(u["hp"] for u in group)
    if mem.get("launched"):
        # Losses are counted man by man for every brigade that took part since the launch (a brigade that left
        # the group shaken or routing, or that the model swapped out, is not "lost": only its dead are; one that
        # is shattered, captured or gone counts in full). Counting the men of the brigades still fit released
        # assaults that had lost few men.
        start_hp = mem.setdefault("start_hp", {})
        for u in group:
            start_hp.setdefault(u["id"], float(u["hp"]))
        alive = {u["id"]: float(u["hp"]) for u in mine_all if unit_status(u) not in ("shattered", "captured")}
        start = sum(start_hp.values())
        lost = sum(max(0.0, h - alive.get(i, 0.0)) for i, h in start_hp.items())
        mem["loss_share"] = (lost / start) if start > 0 else 0.0
        if start > 0 and lost / start >= float(cfg["abort_loss_share"]):
            mem.update(paused_until=now + float(cfg["abort_pause_s"]), launched=False, group=[])
            for k in ("stage_started", "first_arrival", "start_hp", "targets"):
                mem.pop(k, None)
            print(f"  Assault on {obj.get('name')} released: its brigades lost {lost / start:.0%} of their men")
            return set(), []
    defenders = defenders_of(obj, foes, cfg)
    # The weak point of the defence (lowest morale, experience, men and support): the first target, taken in the
    # flank when the game says which way it faces. In the battle of 2026-11-11 every assault went in frontally.
    weak = weak_point(defenders, mem) if cfg.get("weak_point", True) else None
    flank = None
    if weak is not None and cfg.get("weak_flank", True) and not directive.get("approach") and not mem.get("launched"):
        old = mem.get("weak_info") or {}
        flank = flank_approach(weak, defenders, group, cfg, terrain,
                               old.get("flank") if old.get("id") == weak["id"] else None)
    mem["weak"] = weak["id"] if weak is not None else None
    mem["weak_info"] = ({"id": weak["id"], "name": weak.get("name"), "morale": float(weak.get("morale", 1.0)),
                         "stars": int(weak.get("stars") or 0), "men": float(weak.get("hp", 0)), "kind": weak.get("kind"),
                         "flank": flank[2] if flank else None} if weak is not None else None)
    # The staging spots are kept while the group and its approach stay the same (refreshed every few minutes):
    # computed again at every state they follow the group's own centre, and every shifted spot is a new move
    # order that restarts the brigade's march.
    stage_key = (tuple(sorted(u["id"] for u in group)), tuple(directive.get("approach") or ()),
                 (weak["id"], flank[2]) if flank else None)
    kept = mem.get("stage") or {}
    if (mem.get("stage_key") == stage_key and all(u["id"] in kept for u in group)
            and now - float(mem.get("stage_time", now)) < float(cfg.get("stage_refresh_s", 300.0))):
        spots = {u["id"]: tuple(kept[u["id"]]) for u in group}
    else:
        if flank:
            pivot = {"x": weak["x"], "z": weak["z"], "captureRange": 0.0}
            spots = stage_spots(group, pivot, cfg, ranges, mine, foes, terrain, (flank[0], flank[1]))
        else:
            spots = stage_spots(group, obj, cfg, ranges, mine, foes, terrain, directive.get("approach"))
        mem["stage_key"], mem["stage"], mem["stage_time"] = stage_key, dict(spots), now
    # defenders seen recently but hidden now (woods, wheat) still count for the strength ratio
    seen_ids = {e["id"] for e in foes}
    dmem = mem.setdefault("defenders_seen", {})
    for e in defenders:
        dmem[e["id"]] = {"hp": e["hp"], "morale": e["morale"], "t": now}
    for k in [k for k, v in dmem.items() if now - v["t"] > float(cfg["defender_memory_s"])]:
        dmem.pop(k)
    hidden = [v for k, v in dmem.items() if k not in seen_ids]
    mem["hidden_defenders"] = len(hidden)
    pm = pending_moves or {}
    mem.setdefault("stage_started", now)

    def arrived(u):
        sx, sz = spots[u["id"]]
        if math.hypot(u["x"] - sx, u["z"] - sz) <= float(cfg["stage_radius"]):
            return True
        near = nearest(u, _live(foes))
        return bool(near and near[1] <= unit_range(u, float((ranges or {}).get("fire", 400))) and unit_status(u) == "melee")

    def worth(u):
        return u["hp"] * (0.5 + 0.5 * u["morale"])

    if not mem.get("launched"):
        ready = sum(1 for u in group if arrived(u))
        if ready:
            mem.setdefault("first_arrival", now)
        waited = now - float(mem.get("first_arrival", now))   # time spent in the staging area, not on the road
        ds = sum(worth(e) for e in defenders) + sum(v["hp"] * (0.5 + 0.5 * v["morale"]) for v in hidden)
        local = (sum(worth(u) for u in group) / ds) if ds > 0 else math.inf
        mem["local_ratio"] = local
        share = float(cfg["strong_ready_share"]) if local >= float(cfg["strong_ratio"]) else float(cfg["ready_share"])
        share_left = time_share_left(state, mem)
        # with a battle timer the deadline is a share of the phase's time; without one, a battle minute
        late = (share_left <= float(cfg["launch_time_share"]) if share_left is not None
                else phase_s / 60.0 >= float(cfg["latest_launch_minutes"]))
        in_place = (ready >= math.ceil(share * len(group)) or late or waited >= float(cfg["stage_timeout_s"]))
        # 0.1.4 WIP7: the deadline and the long wait no longer send in a group much weaker than the defenders;
        # they only lower the bar from launch_min_ratio (1.5) to launch_floor_ratio (1.0)
        floor = float(cfg.get("launch_floor_ratio", 1.0))
        strong_enough = (local >= float(cfg["launch_min_ratio"])
                         or ((late or waited >= float(cfg["max_wait_s"])) and local >= floor))
        launch = directive.get("launch") or "auto"
        if launch == "now":
            in_place, strong_enough = True, True       # the model's call: go in now
        elif launch == "wait":
            # the model holds the assault; only the last part of the timer overrides it
            hard = share_left is not None and share_left <= 0.5 * float(cfg["launch_time_share"])
            if not hard:
                in_place = False
        sync = plan_info.get("sync")
        if sync is not None and not mem.get("launched"):
            # synchronised assaults: this one goes in only when the other one(s) of the same turn are ready too
            sync[plan_info.get("sync_key", 0)] = bool(in_place and strong_enough)
            partners_ready = all(sync.values()) and len(sync) >= 2
            if launch != "now" and not late and not partners_ready and in_place and strong_enough:
                if not mem.get("sync_noted"):
                    mem["sync_noted"] = True
                    print(f"  Assault on {obj.get('name')} ready, waits for the other assault to go in together")
                in_place = False
        if plan_info.get("hold_launch") and launch != "now" and local < float(cfg["launch_min_ratio"]):
            # (a group already at the target ratio goes in through a stop-loss pause: the pause is about trading
            # fire at a loss, not about an assault with the numbers on its side)
            if in_place and strong_enough and not mem.get("pause_noted"):
                mem["pause_noted"] = True
                print(f"  Assault on {obj.get('name')} ready but held: stop-loss pause (staging goes on)")
            in_place = False
        if in_place and not strong_enough and not mem.get("wait_noted"):
            mem["wait_noted"] = True
            print(f"  Assault on {obj.get('name')} waits in the staging area: group/defenders strength {local:.2f} "
                  f"(needs {float(cfg['launch_min_ratio']):.2f}; goes in anyway after {float(cfg['max_wait_s']) / 60:.0f} min)")
        if in_place and strong_enough:
            mem["launched"] = True
            mem["start_men"] = men
            mem["start_hp"] = {u["id"]: float(u["hp"]) for u in group}
            mem["launch_time"] = now
            print(f"  ASSAULT on {obj.get('name')} launched with {len(group)} brigade(s) "
                  f"({ready} in position); defenders seen: {len(defenders)} (+{len(hidden)} hidden now)")
    by_id = {o["id"]: o for o in orders}
    drop, added = set(), []
    budget = int(cfg["max_orders_per_turn"])
    live_foes = {e["id"]: e for e in _live(foes)}
    taken = {}
    spots_taken = []
    charges = 0
    charged = set()
    if mem.get("launched"):
        # charges go in together: several brigades close to the defenders charge in the same turn
        pairs = []
        for u in group:
            own = by_id.get(u["id"])
            if (own and own["cmd"] == "fallback") or u["morale"] < float(cfg["charge_min_morale"]) \
                    or unit_status(u) != "" or ((last_cmds or {}).get(u["id"]) or {}).get("cmd") == "charge":
                continue
            near = nearest(u, [e for e in defenders if e["id"] in live_foes])
            if not near:
                continue
            e, d = near
            if weak is not None and weak["id"] in live_foes and weak["id"] != e["id"] and _dist(u, weak) <= d + 150.0:
                e, d = weak, _dist(u, weak)               # the weak point first, when it is about as near
            # charge distance by the ground: 500 over open ground, 200 through woods, scrub or mud
            slow = 0.0
            if terrain is not None and hasattr(terrain, "path_profile"):
                _, _, slow = terrain.path_profile(u["x"], u["z"], e["x"], e["z"], "Infantry")
            fresh = (u["morale"] >= float(cfg.get("fresh_charge_morale", 0.8))
                     and float(u.get("fatigue", 1.0)) >= float(cfg.get("fresh_charge_stamina", 0.8)))
            slow_limit = max(float(cfg["charge_slow_distance"]),
                             float(cfg.get("fresh_charge_slow_distance", 0.0)) if fresh else 0.0)
            limit = slow_limit if slow > float(cfg["charge_slow_share"]) else float(cfg["charge_open_distance"])
            reach = min(float(u.get("chargeRange") or 0) or limit, limit)
            if d > reach:
                continue
            pairs.append((u, e, own, d))
        # at close range a fresh brigade charges anyway: standing there only trades volleys
        close = [p for p in pairs if p[3] <= float(cfg["charge_slow_distance"])
                 and float(p[0]["hp"]) >= float(cfg["close_charge_strength"]) * float(p[1]["hp"])]
        shaken = [p for p in pairs if p[1]["morale"] < float(cfg["charge_morale"]) or p[1]["kind"] in ("Artillery", "Skirmish")]
        strong = cfg.get("charge_when_strong") and float(mem.get("local_ratio") or 0) >= float(cfg["strong_ratio"])
        together = len(pairs) >= min(int(cfg["charge_together"]), len(group))
        go = pairs if together and (shaken or strong) else shaken
        go = go + [p for p in close if p not in go]
        # a charge on a shaken unit is the rule, not the only case: fresh brigades good in melee charge a steady
        # defender together, and a brigade on the flank or in the rear of its target charges it
        mass = [p for p in pairs if p[0]["morale"] >= float(cfg["mass_charge_morale"])
                and float(p[0].get("fatigue", 1.0)) >= float(cfg["mass_charge_stamina"]) and melee_good(p[0], p[1])]
        if len(mass) >= int(cfg["mass_charge_min"]):
            go = go + [p for p in mass if p not in go]
        go = go + [p for p in pairs if p not in go and flanked(p[1], p[0], cfg)]
        for u, e, own, _ in go[:int(cfg["max_charges_per_turn"])]:
            if own:
                drop.add(u["id"])
            added.append({"cmd": "charge", "id": u["id"], "target": e["id"], "auto": True})
            charged.add(u["id"])
            if stats is not None:
                k = "auto assault charges (together, from close range, on shaken or outnumbered defenders)"
                stats[k] = stats.get(k, 0) + 1
    for u in sorted(group, key=lambda g: _dist(g, obj)):
        if len(added) >= budget + len(charged):
            break
        if u["id"] in charged:
            continue
        own = by_id.get(u["id"])
        if own and own["cmd"] == "fallback":
            continue
        if own and own["cmd"] == "move" and math.hypot(own["x"] - u["x"], own["z"] - u["z"]) <= 250:
            continue                                   # the model's own short sidestep (e.g. to clear its lane)
        last = (last_cmds or {}).get(u["id"]) or {}
        if mem.get("launched"):
            cands = [e for e in defenders if math.hypot(e["x"] - u["x"], e["z"] - u["z"]) <= 900.0] or defenders
            if cands:
                # prefer a defender the brigade can actually shoot at (no friendly unit in its line of fire)
                clear = [c for c in cands if lane_blocked(u, c, mine) is None]
                if not clear:
                    spot = find_clear_spot(u["x"], u["z"], u, mine, [], _live(foes), terrain)
                    if spot is not None and math.hypot(spot[0] - u["x"], spot[1] - u["z"]) > 20:
                        cmd = {"cmd": "move", "id": u["id"], "x": round(spot[0], 1), "z": round(spot[1], 1),
                               "auto": True}
                        if own:
                            drop.add(u["id"])
                        added.append(cmd)
                        mem.setdefault("blocked", {})[u["id"]] = now
                        if stats is not None:
                            k = "auto assault sidesteps (group member's line of fire blocked by a friendly unit)"
                            stats[k] = stats.get(k, 0) + 1
                        continue
                    clear = cands
                # keep the current target while it is alive and in sight (also while marching to a firing
                # position): re-targeting at every state restarts the march and the route
                tmem = mem.setdefault("targets", {})
                cur = live_foes.get(tmem.get(u["id"]))
                if cur is None and last.get("cmd") in ("attack", "charge"):
                    cur = live_foes.get(last.get("target"))
                if cur is not None and any(c["id"] == cur["id"] for c in cands) \
                        and (lane_blocked(u, cur, mine) is None or not any(lane_blocked(u, c, mine) is None for c in cands)):
                    e = cur
                else:
                    wid = weak["id"] if weak is not None else None
                    e = min(clear, key=lambda c: _dist(u, c) + 250.0 * c["morale"] + 120.0 * taken.get(c["id"], 0)
                            - (float(cfg["weak_bonus"]) if c["id"] == wid else 0.0))
                tmem[u["id"]] = e["id"]
                taken[e["id"]] = taken.get(e["id"], 0) + 1
                rng = unit_range(u, float((ranges or {}).get("fire", 400)))
                d = _dist(u, e)
                reach = float(u.get("chargeRange") or 0) or 250.0
                if d > rng + float(cfg["approach_margin"]) and terrain is not None and hasattr(terrain, "best_fire_spot"):
                    # too far for an attack order: march to a firing position, protected if the ground allows
                    # still marching to a firing position against the same target, which has not moved much:
                    # leave the march alone (a new spot every state would restart it)
                    smem = mem.setdefault("spots", {})
                    old = smem.get(u["id"])
                    if (old and old[0] == e["id"] and u["id"] in pm
                            and math.hypot(old[1] - e["x"], old[2] - e["z"]) < 150.0):
                        spots_taken.append((pm[u["id"]][0], pm[u["id"]][1]))
                        continue
                    spot = terrain.best_fire_spot(u["x"], u["z"], e["x"], e["z"], rng, "Infantry", spots_taken,
                                                  cover_weight=float(cfg["cover_weight"]))
                    if spot is None:
                        continue
                    spots_taken.append((spot[0], spot[1]))
                    smem[u["id"]] = (e["id"], e["x"], e["z"])
                    if u["id"] in pm and math.hypot(pm[u["id"]][0] - spot[0], pm[u["id"]][1] - spot[1]) < 120:
                        continue                               # already on its way there
                    cmd = {"cmd": "move", "id": u["id"], "x": spot[0], "z": spot[1],
                           "fx": round(e["x"], 1), "fz": round(e["z"], 1), "auto": True}
                    key = "auto assault approach moves (to a firing position, cover preferred)"
                elif (d <= rng * 0.95 and terrain is not None and hasattr(terrain, "fire_value")
                      and terrain.fire_value(u["x"], u["z"]) >= 0.9):
                    # in range from good cover: stay there and fire instead of walking out into the open
                    if last.get("cmd") == "hold" and not own:
                        continue
                    cmd = {"cmd": "hold", "id": u["id"], "auto": True}
                    key = "auto assault holds in cover (in range of a defender from a protected spot)"
                else:
                    # Trading fire: from the best covered spot within reach, not by chasing the target ("attack"
                    # walks the brigade up to the enemy over open ground). In the battle of 2026-11-11 the group
                    # traded fire in the open and lost 3.3 times the enemy's men in ten minutes.
                    spot = None
                    cover_t = mem.setdefault("cover_time", {})
                    recent = now - float(cover_t.get(u["id"], -1e9)) < float(cfg["trade_cover_every_s"])
                    if terrain is not None and hasattr(terrain, "best_fire_spot") and not recent:
                        here = terrain.fire_value(u["x"], u["z"])
                        cand = terrain.best_fire_spot(u["x"], u["z"], e["x"], e["z"], rng, "Infantry", spots_taken,
                                                      max_move=max(0.0, d - rng) + float(cfg["trade_cover_move"]),
                                                      cover_weight=float(cfg["cover_weight"]))
                        if cand is not None and (cand[3] >= here + float(cfg["trade_cover_gain"]) or d > rng):
                            spot = cand
                    if spot is None and recent and u["id"] in pm:
                        continue                               # still walking to the covered spot it was given
                    if spot is not None:
                        spots_taken.append((spot[0], spot[1]))
                        if u["id"] in pm and math.hypot(pm[u["id"]][0] - spot[0], pm[u["id"]][1] - spot[1]) < 120:
                            continue                           # already on its way there
                        cover_t[u["id"]] = now
                        cmd = {"cmd": "move", "id": u["id"], "x": spot[0], "z": spot[1],
                               "fx": round(e["x"], 1), "fz": round(e["z"], 1), "auto": True}
                        key = "auto assault moves to a covered firing spot in range (instead of chasing in the open)"
                    elif d <= rng:
                        if (own and own["cmd"] in ("range_attack", "attack") and own.get("target") in live_foes) or \
                                (last.get("cmd") == "range_attack" and last.get("target") == e["id"] and u["id"] not in pm):
                            continue
                        cmd = {"cmd": "range_attack", "id": u["id"], "target": e["id"], "auto": True}
                        key = "auto assault fire from where it stands (no better cover in reach)"
                    else:
                        if (own and own["cmd"] == "attack" and own.get("target") in live_foes) or \
                                (last.get("cmd") == "attack" and last.get("target") == e["id"] and u["id"] not in pm):
                            continue
                        cmd = {"cmd": "attack", "id": u["id"], "target": e["id"], "auto": True}
                        key = "auto assault attacks (assault group on a defender of the objective)"
            else:
                if u["id"] in pm and math.hypot(pm[u["id"]][0] - obj["x"], pm[u["id"]][1] - obj["z"]) < 80:
                    continue
                if _dist(u, {"x": obj["x"], "z": obj["z"]}) <= float(obj.get("captureRange") or 100.0) * 0.6:
                    continue                                  # already standing on the point
                cmd = {"cmd": "move", "id": u["id"], "x": round(obj["x"], 1), "z": round(obj["z"], 1),
                       "fx": round(obj["x"], 1), "fz": round(obj["z"], 1), "auto": True}
                key = "auto assault moves (assault group walks onto the objective)"
        else:
            sx, sz = spots[u["id"]]
            if u["id"] in pm and math.hypot(pm[u["id"]][0] - sx, pm[u["id"]][1] - sz) < 60:
                continue
            if math.hypot(u["x"] - sx, u["z"] - sz) <= float(cfg["stage_radius"]):
                if last.get("cmd") == "hold" and not own:
                    continue
                cmd = {"cmd": "hold", "id": u["id"], "auto": True}
                key = "auto assault holds (group member waits in the staging area)"
            else:
                if own and own["cmd"] == "move" and math.hypot(own["x"] - sx, own["z"] - sz) < 80:
                    continue
                cmd = {"cmd": "move", "id": u["id"], "x": sx, "z": sz,
                       "fx": round(obj["x"], 1), "fz": round(obj["z"], 1), "auto": True}
                key = "auto assault staging moves (group walks to the staging area)"
        if own:
            drop.add(u["id"])
        added.append(cmd)
        if stats is not None:
            stats[key] = stats.get(key, 0) + 1
    return drop, added


def briefing_lines(briefing, objectives=None, cfg=None):
    """The clock of the turn: time left on the battle timer (minutes and share of the phase) and the hour."""
    lines = []
    if briefing and briefing.get("timeLeftS") is not None and briefing.get("timerShown", True):
        left = int(float(briefing["timeLeftS"]))
        kind = ("the battle ends then" if "Mandatory" in str(briefing.get("timerKind", ""))
                else "the suggested end of the battle")
        # minutes, never "h:mm": the model read "1:47" (1 hour 47) as one minute 47 and gave the battle up
        spent = briefing.get("missionElapsedS")
        share = ""
        if spent is not None and left + float(spent) > 0:
            share = f", {float(left) / (left + float(spent)):.0%} of this phase's time"
        lines.append(f"TIME LEFT on the battle timer: {left // 60} minutes"
                     + (f" ({left // 3600} h {(left % 3600) // 60:02d} min)" if left >= 3600 else "")
                     + f"{share} ({kind}).")
    return lines


def briefing_static(briefing, objectives, cfg=None):
    """The mission text read in the game and the objectives' own descriptions. They do not change during the
    battle: they go once into the (cached) system prompt, not into every turn."""
    cfg = {**DEFAULT_ASSAULT, **(cfg or {})}
    lines = []
    if briefing and (briefing.get("name") or briefing.get("description")):
        text = " ".join(str(briefing.get("description") or "").split())
        limit = int(cfg["briefing_chars"])
        if len(text) > limit:
            text = text[:limit].rstrip() + "..."
        lines.append("MISSION BRIEFING (the game's own text; the MISSION GOALS of each turn are what counts)")
        if briefing.get("name"):
            lines.append(f"  {briefing['name']}")
        if text:
            lines.append(f"  {text}")
    descs = [o for o in (objectives or []) if o.get("description")]
    if descs:
        lines.append("OBJECTIVES OF THIS MAP (from the game)")
        for o in descs:
            lines.append(f"  - {o.get('name')}: {' '.join(str(o['description']).split())[:220]}")
    return lines


def assault_lines(state, plan_info, cfg, mem, ranges, terrain=None, saved_plan=None):
    """The ASSAULT PLAN block of the prompt (empty unless the plan is to attack an objective)."""
    cfg = {**DEFAULT_ASSAULT, **(cfg or {}), **((plan_info or {}).get("cfg_override") or {})}
    if not cfg["enabled"] or not plan_info or plan_info.get("mode") != "ATTACK":
        return []
    mine, foes = split_units(state)
    mine = _live(mine)
    obj = pick_target(plan_info, mine)
    if obj is None:
        return []
    now = float(state.get("time", 0.0))
    phase_s = float(state.get("phaseTime", now))
    on_field = [u for u in mine if not u.get("offmap")] or mine     # units still entering do not count
    cx = sum(u["x"] for u in on_field) / max(len(on_field), 1)
    cz = sum(u["z"] for u in on_field) / max(len(on_field), 1)
    d_obj = math.hypot(obj["x"] - cx, obj["z"] - cz)
    defenders = defenders_of(obj, foes, cfg)
    lines = [f"ASSAULT PLAN: TARGET {obj.get('name')} at {obj['x']:.0f},{obj['z']:.0f} "
             f"(capture range {float(obj.get('captureRange') or 0):.0f}, {obj.get('victoryPoints')} VP); "
             f"your army centre is {d_obj:.0f} away."]
    # TEMPO: how much of the phase's time is used, so that the march is weighed against the clock
    clock = phase_clock(state)
    march = d_obj / 60.0                          # about 60 per minute for a brigade in line through mixed ground
    if clock is not None:
        used, total, left = clock
        deadline = 1.0 - float(cfg["launch_time_share"])
        tempo = f"  TEMPO: {used:.0%} of this phase's time used ({left / 60:.0f} of {total / 60:.0f} minutes left)"
        if not mem.get("launched"):
            tempo += f"; the assault goes in at {deadline:.0%} at the latest"
        if mem.get("hidden_defenders"):
            tempo += f"; {mem['hidden_defenders']} defender(s) seen recently are hidden now, counted as present"
        if not mem.get("launched"):
            m_share = march * 60.0 / total
            tempo += (f". Marching to the point takes about {march:.0f} min ({m_share:.0%} of the phase) from your "
                      "centre: " + ("you are BEHIND SCHEDULE, commit now." if used + m_share > deadline
                                    else "keep moving."))
    else:
        latest = float(cfg["latest_launch_minutes"])
        tempo = (f"  TEMPO (no battle timer): minute {phase_s / 60:.0f} of this phase; the assault goes in by minute "
                 f"{latest:.0f} at the latest")
        if mem.get("hidden_defenders"):
            tempo += f"; {mem['hidden_defenders']} defender(s) seen recently are hidden now (woods), counted as present"
        if not mem.get("launched"):
            tempo += (f". Marching to the point takes about {march:.0f} min from your centre: "
                      + ("you are BEHIND SCHEDULE, commit now." if phase_s / 60 + march > latest else "keep moving."))
    lines.append(tempo)
    if defenders:
        lines.append(f"  DEFENDERS within {max(float(cfg['defender_radius']), 1):.0f} of it: {len(defenders)} unit(s), "
                     f"{sum(e['hp'] for e in defenders):.0f} men; nearest the point: "
                     + ", ".join(f"#{e['id']} (morale {e['morale']:.2f})" for e in defenders[:6]))
        ex = sum(e["x"] for e in defenders) / len(defenders)
        ez = sum(e["z"] for e in defenders) / len(defenders)
        dx, dz = obj["x"] - cx, obj["z"] - cz
        n = math.hypot(dx, dz) or 1.0
        px, pz = -dz / n, dx / n
        left = sum(1 for e in defenders if (e["x"] - ex) * px + (e["z"] - ez) * pz < 0)
        right = len(defenders) - left
        if left != right:
            weak = "left" if left < right else "right"
            lines.append(f"  WEAK SIDE of the defence: its {weak} flank ({min(left, right)} unit(s) against "
                         f"{max(left, right)}).")
        w = mem.get("weak_info")
        if w and any(e["id"] == w["id"] for e in defenders):
            lines.append(f"  WEAK POINT: #{w['id']} {w['name']} ({w['kind']}, {w['men']:.0f} men, morale {w['morale']:.2f}, "
                         f"{w['stars']}*)" + (f": the group stages on its {w['flank']} flank and takes it first"
                                               if w.get("flank") else ": the group's first target")
                         + "; feed it: batteries and skirmishers on it, cavalry on its rear.")
    else:
        lines.append("  No defender seen near the point yet: scout it.")
    group_ids = mem.get("group") or [u["id"] for u in select_group(mine, foes, obj, cfg, {})]
    group = [u for u in mine if u["id"] in group_ids]
    if group:
        kept = mem.get("stage") or {}
        spots = ({u["id"]: tuple(kept[u["id"]]) for u in group} if all(u["id"] in kept for u in group) else
                 stage_spots(group, obj, cfg, ranges, mine, foes, terrain,
                             ((plan_info or {}).get("directive") or {}).get("approach")))
        state_txt = ((f"LAUNCHED, lost {float(mem.get('loss_share') or 0):.0%} of its men so far (released at "
                      f"{float(cfg['abort_loss_share']):.0%})") if mem.get("launched") else
                     ("PAUSED after heavy losses" if now < float(mem.get("paused_until", 0.0)) else
                      ("STAGING: walking to the staging area, launch when most have arrived" if phase_s / 60.0 >= float(cfg["launch_minutes"])
                       else f"FORMING: the assault starts at minute {cfg['launch_minutes']:.0f}")))
        ratio = mem.get("local_ratio")
        if ratio is not None and not mem.get("launched") and ratio != math.inf:
            state_txt += f"; group/defenders strength {ratio:.2f}, launch at {float(cfg['launch_min_ratio']):.2f}"
            if ratio < float(cfg["launch_min_ratio"]):
                state_txt += (" (every fit brigade but the reserve is already in the group: bring more in, wear the "
                              "defenders down with fire, or give the assault up)" if len(group) > 1 else "")
        def lane_txt(u):
            if not defenders:
                return ""
            tgt = min(defenders, key=lambda e: _dist(u, e))
            b = lane_blocked(u, tgt, mine)
            return f", lane blocked by #{b['id']}" if b else ""
        d = (plan_info or {}).get("directive") or {}
        if d:
            txt = f"  YOUR ASSAULT ORDER (macro, executed by the server): launch {d.get('launch') or 'auto'}"
            if d.get("group"):
                txt += ", group " + ", ".join(f"#{i}" for i in d["group"])
            if d.get("approach"):
                txt += f", approach from {d['approach'][0]:.0f},{d['approach'][1]:.0f}"
            lines.append(txt)
        lines.append(f"  ASSAULT GROUP ({state_txt}): "
                     + "; ".join(f"#{u['id']} {u['name']} ({u['hp']:.0f} men, morale {u['morale']:.2f}{lane_txt(u)})"
                                 for u in group))
        c = next(iter(spots.values()), None)
        if c and not mem.get("launched"):
            lines.append("  STAGING AREA: "
                         + "; ".join(f"#{i} at {x:.0f},{z:.0f}" for i, (x, z) in spots.items()))
    batteries = [u for u in mine if u["kind"] == "Artillery"]
    if batteries and defenders:
        lines.append("  FIXING FIRE targets: " + ", ".join(f"#{e['id']}" for e in defenders[:3]))
    if saved_plan:
        lines.append(f"  YOUR ATTACK PLAN (minute {saved_plan[0] / 60.0:.0f}): "
                     + saved_plan[1])
    else:
        lines.append("  YOUR ATTACK PLAN: none yet; write it in \"plan\" in this answer.")
    return lines
