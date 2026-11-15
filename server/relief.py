"""Server-side morale discipline and reserve use: pull back broken brigades, replace them, commit the reserve.

In the battle of 2026-11-09 19:36 the model left brigades fighting until their morale reached 0.01 to 0.03
(one was shattered), pulled others back without sending a fresh brigade into the gap, and kept two brigades
in reserve for 38 minutes (one never fired). This module enforces three rules whatever the model ordered:

1. A brigade in contact with the enemy whose morale is under `retreat_morale` is pulled back (fallback, or a
   real retreat move when it is nearly broken). Holding, shooting or attacking is replaced.
2. The gap it leaves is filled the same turn by the nearest fresh infantry brigade.
3. From `commit_minutes` of battle time (earlier when the plan is to attack) the brigades that stand idle far
   from the enemy are sent to the line. One brigade stays back until `release_minutes`.

Every order it adds carries "auto": true. Switch it off in config.json ("relief").
"""
import math

from prompting import (DEAD_STATUSES, find_clear_spot, nearest, split_units, unit_status)

DEFAULT_RELIEF = {
    "enabled": True,
    "retreat_morale": 0.5,        # a brigade in contact under this morale is pulled back
    "retreat_men": 0.4,           # ...or under this share of its starting men
    "critical_morale": 0.3,       # under this a plain fallback is not enough: it retreats behind the line
    "contact_distance": 650.0,    # "in contact" = an enemy this close (about fire range + margin)
    "fallback_seconds": 15.0,
    "retreat_distance": 300.0,
    "retreat_seconds": 45.0,      # length of the fallback of a brigade under critical morale
    "cooldown_s": 90.0,           # do not re-issue the pull-back to the same brigade sooner than this
    "rested_morale": 0.65,        # (fallback when "return_morale" is null) morale a pulled-back brigade needs again
    # Morale a pulled-back brigade needs before it goes forward again, by situation (see situation_level): a
    # quiet front lets it rest longer, a crisis takes it back sooner. Brigades joining an assault or the final
    # charge need more (assault.eve_morale, final_charge.min_morale: 0.8), to last the whole charge.
    "return_morale": {"calm": 0.75, "tense": 0.7, "critical": 0.65},
    "critical_shaken_share": 0.3,  # this share of the infantry in contact under retreat morale = critical
    "replace": True,
    "max_replacements": 2,        # per turn (floor)...
    "replacements_share": 0.05,   # ...or this share of the infantry brigades, whichever is larger
    "replacement_min_morale": 0.7,
    "replacement_min_strength": 0.6,
    "replacement_max_distance": 1300.0,
    "reserve_commit": True,
    "commit_minutes": 20.0,       # idle healthy brigades go to the line from this battle time...
    "commit_minutes_attack": 8.0,   # ...or from this one when the plan is ATTACK
    "commit_share": 0.3,          # with a battle timer: from this share of the phase's time...
    "commit_share_attack": 0.12,  # ...or this one when attacking
    "release_minutes": 40.0,      # one brigade stays in reserve until this battle time
    "reserve_min_distance": 700.0,  # an idle brigade this far from every enemy counts as reserve
    "reserve_min_morale": 0.7,
    "reserve_min_strength": 0.6,
    "reserve_max_per_turn": 2,    # per turn (floor)...
    "reserve_per_turn_share": 0.05,  # ...or this share of the infantry brigades
    # Ammunition (0.1.4 WIP4: Chalmers and Cleburne stood in the line with 0 % for half an hour):
    "dry_ammo": 0.03,             # a brigade in contact with this little ammunition leaves the line like a broken one
    "rearmed_ammo": 0.25,         # ...and does not go forward again under this share
    # WIP13 (Second Manassas and Crampton's Gap, 2026-11-13/14): 177 brigades were pulled out of forest or
    # fortifications at a median morale of 0.49, where they took half the losses of the open (cover curve). On a
    # DEFEND plan a brigade standing in cover leaves the line only under cover_retreat_morale.
    "cover_retreat_morale": 0.3,
    "cover_terrains": ["Forest", "DenseForest", "Fortifications"],
    # WIP13: a brigade under rally_morale that is out of contact goes on to the highest ground rally_min..rally_max
    # behind it (away from the nearest enemy): morale comes back up to 1.6 times faster on high ground (game curve).
    "rally_high_ground": True,
    "rally_morale": 0.3,
    "rally_min": 300.0,
    "rally_max": 600.0,
    "rally_cooldown_s": 120.0,
    # Crampton's Gap: 102 of 142 brigade-states under 0.3 stood within 450 of the enemy, a fallback (a step of
    # about 50 by hand) never took them out. After one critical fallback, a brigade still under rally_morale and
    # not in melee gets the move to the high ground directly; out of contact it is sent there at once.
    "rally_after_fallback": True,
    # WIP13: on a DEFEND/TRADE plan the reserve commit leaves alone a brigade standing in fortifications, or in
    # woods within cover_hold_objective of an objective you hold (Second Manassas: the line left both by 75 min).
    "cover_hold_objective": 800.0,
}

_STOP_CMDS = ("hold", "attack", "range_attack", "charge", "move")


def _share(u):
    return float(u["hp"]) / max(float(u["maxHp"]), 1.0)


def _live(units):
    return [u for u in units if unit_status(u) not in DEAD_STATUSES]


# Return morale of the current state, set by the planner at every state (see situation_level); None = rested_morale.
RETURN = {"morale": None, "level": None}


def set_return_morale(value, level=None):
    RETURN["morale"], RETURN["level"] = value, level


def return_morale(cfg=None):
    cfg = {**DEFAULT_RELIEF, **(cfg or {})}
    return float(RETURN["morale"]) if RETURN["morale"] is not None else float(cfg["rested_morale"])


def situation_level(state, cfg=None, stop_loss=False):
    """"calm" (no brigade in contact), "critical" (stop-loss running, or a large share of the brigades in contact
    shaken) or "tense" (any other fight). Returns (level, return morale for that level)."""
    cfg = {**DEFAULT_RELIEF, **(cfg or {})}
    mine, foes = split_units(state)
    mine, foes = _live(mine), _live(foes)
    front = [u for u in mine if u["kind"] == "Infantry"
             and (nearest(u, foes) or (None, 1e9))[1] <= float(cfg["contact_distance"])]
    if not front:
        level = "calm"
    else:
        shaken = sum(1 for u in front if u["morale"] < float(cfg["retreat_morale"]))
        level = "critical" if stop_loss or shaken >= max(2, float(cfg["critical_shaken_share"]) * len(front)) else "tense"
    table = cfg.get("return_morale")
    if not isinstance(table, dict):
        return level, float(cfg["rested_morale"])
    return level, float(table.get(level, cfg["rested_morale"]))


def is_resting(u, last_cmds, cfg=None):
    """True for a brigade that was pulled back and has not recovered enough to fight again."""
    last = (last_cmds or {}).get(u["id"])
    if not (last and ((last.get("cmd") == "fallback" and last.get("relief")) or last.get("rally"))):
        return False
    full = {**DEFAULT_RELIEF, **(cfg or {})}
    return u["morale"] < return_morale(cfg) or _ammo(u) < float(full["rearmed_ammo"])


def _ammo(u):
    try:
        return float(u.get("ammo", 1.0))
    except (TypeError, ValueError):
        return 1.0


def _dry(u, cfg):
    return u["kind"] in ("Infantry", "Skirmish") and _ammo(u) <= float(cfg["dry_ammo"])


def _in_cover(u, terrain, cfg):
    return terrain is not None and terrain.name_at(u["x"], u["z"]) in set(cfg.get("cover_terrains") or ())


def _wants_out(u, foes, cfg, terrain=None, defend=False):
    if u["kind"] not in ("Infantry", "Cavalry", "Skirmish") or unit_status(u) in DEAD_STATUSES + ("fallback", "melee"):
        return None
    near = nearest(u, foes)
    if not near or near[1] > float(cfg["contact_distance"]):
        return None
    limit = float(cfg["retreat_morale"])
    if defend and u["kind"] == "Infantry" and _in_cover(u, terrain, cfg):
        limit = min(limit, float(cfg.get("cover_retreat_morale", limit)))   # WIP13: hold the woods / the works
    if u["morale"] < limit or _share(u) < float(cfg["retreat_men"]) or _dry(u, cfg):
        return near
    return None


def holds_cover(u, state, terrain, cfg):
    """WIP13: True for a brigade that should stay where it is on a defensive plan: in fortifications, or in woods
    near an objective of your side."""
    if terrain is None or u.get("kind") != "Infantry":
        return False
    ground = terrain.name_at(u["x"], u["z"])
    if ground == "Fortifications":
        return True
    if ground not in set(cfg.get("cover_terrains") or ()):
        return False
    me = "North" if state.get("playerSide") == "South" else "South"
    reach = float(cfg.get("cover_hold_objective", 800.0))
    return any(str(o.get("side")) == me and math.hypot(o["x"] - u["x"], o["z"] - u["z"]) <= reach
               for o in (state.get("objectives") or []) if "x" in o and "z" in o)


def rally_spot(u, e, terrain, cfg, force=False):
    """WIP13: the highest passable point rally_min..rally_max behind u (away from e), within 60 degrees of straight
    back; on a tie the nearer one. None when nothing is higher than where u stands and e is already far."""
    if terrain is None:
        return None
    dx, dz = u["x"] - e["x"], u["z"] - e["z"]
    n = math.hypot(dx, dz) or 1.0
    base = math.atan2(dz / n, dx / n)
    here = terrain.height_at(u["x"], u["z"])
    best = None
    for dist in (float(cfg["rally_min"]), (float(cfg["rally_min"]) + float(cfg["rally_max"])) / 2, float(cfg["rally_max"])):
        for deg in (0, -30, 30, -60, 60):
            a = base + math.radians(deg)
            x, z = u["x"] + math.cos(a) * dist, u["z"] + math.sin(a) * dist
            if not terrain.passable(x, z):
                continue
            key = (terrain.height_at(x, z), -dist, -abs(deg))
            if best is None or key > best[0]:
                best = (key, x, z)
    if best is None:
        return None
    if not force and best[0][0] <= here and math.hypot(u["x"] - e["x"], u["z"] - e["z"]) >= float(cfg["contact_distance"]) + float(cfg["rally_min"]):
        return None
    return best[1], best[2]


def rally_orders(state, orders, cfg, terrain, clock, pending_moves=None, stats=None):
    """WIP15 llm_plus: only the rally on high ground. A brigade under rally_morale that the model left without an
    order this turn, not in melee, goes to the highest ground rally_min..rally_max behind it (morale comes back up
    to 1.6 times faster there); in contact it goes only when its nearest enemy is 150+ away."""
    cfg = {**DEFAULT_RELIEF, **(cfg or {})}
    if not cfg.get("rally_high_ground", True) or terrain is None:
        return []
    clock = clock if clock is not None else {}
    now = float(state.get("time", 0.0))
    mine, foes = split_units(state)
    foes = [e for e in foes if unit_status(e) not in DEAD_STATUSES]
    ordered = {o["id"] for o in orders}
    out = []
    for u in mine:
        if (u["kind"] != "Infantry" or u["morale"] >= float(cfg["rally_morale"]) or u["id"] in ordered
                or u["id"] in (pending_moves or {}) or unit_status(u) in DEAD_STATUSES + ("melee",)):
            continue
        near = nearest(u, foes)
        if not near or near[1] < 150.0:
            continue
        if now - clock.get(("rally", u["id"]), -1e9) < float(cfg["rally_cooldown_s"]):
            continue
        spot = rally_spot(u, near[0], terrain, cfg, force=near[1] <= float(cfg["contact_distance"]))
        if spot is None:
            continue
        clock[("rally", u["id"])] = now
        out.append({"cmd": "move", "id": u["id"], "x": round(spot[0], 1), "z": round(spot[1], 1),
                    "auto": True, "rally": True})
        if stats is not None:
            k = "broken brigades sent on to high ground to rally (morale recovers faster there)"
            stats[k] = stats.get(k, 0) + 1
    return out


def relief_orders(state, orders, cfg, last_cmds, pending_moves, terrain=None, clock=None, stats=None, avoid=None,
                  plan_mode=None, trap=None):
    """Returns (ids whose own order is dropped, new orders). `clock` is a dict kept between turns;
    `avoid` = ids that should not be used as replacements if others are available (the assault group)."""
    cfg = {**DEFAULT_RELIEF, **(cfg or {})}
    if not cfg["enabled"]:
        return set(), []
    clock = clock if clock is not None else {}
    now = float(state.get("time", 0.0))
    mine, foes = split_units(state)
    mine, foes = _live(mine), _live(foes)
    if not foes:
        return set(), []
    drop, added, taken = set(), [], set()
    by_id = {o["id"]: o for o in orders}
    bump = (lambda k: stats.__setitem__(k, stats.get(k, 0) + 1)) if stats is not None else (lambda k: None)
    vacated = []
    defend = str(plan_mode or "").upper() in ("DEFEND", "TRADE", "HOLD", "PRESERVE")
    for u in mine:
        near = _wants_out(u, foes, cfg, terrain, defend)
        if not near:
            if defend and _wants_out(u, foes, cfg) is not None:
                bump("brigades kept in cover under 0.5 morale (defensive plan, cover holds to 0.3)")
            continue
        mine_order = by_id.get(u["id"])
        if mine_order and mine_order["cmd"] == "fallback":
            continue                                   # the model already pulls it back
        if mine_order and mine_order["cmd"] == "move":
            # a move away from the enemy is fine
            e = near[0]
            if math.hypot(mine_order["x"] - e["x"], mine_order["z"] - e["z"]) > near[1] + 100:
                continue
        dry = _dry(u, cfg)
        critical = u["morale"] < float(cfg["critical_morale"]) or dry
        if not critical and now - clock.get(u["id"], -1e9) < float(cfg["cooldown_s"]):
            continue
        e = near[0]
        dx, dz = u["x"] - e["x"], u["z"] - e["z"]
        n = math.hypot(dx, dz) or 1.0
        if (critical and not dry and cfg.get("rally_high_ground", True) and cfg.get("rally_after_fallback", True)
                and terrain is not None and u["kind"] == "Infantry" and u["morale"] < float(cfg["rally_morale"])
                and ("crit", u["id"]) in clock
                and now - clock[("crit", u["id"])] >= float(cfg["retreat_seconds"])
                and now - clock.get(("rally", u["id"]), -1e9) >= float(cfg["rally_cooldown_s"])):
            spot = rally_spot(u, e, terrain, cfg, force=True)
            if spot is not None:
                clock[("rally", u["id"])] = now
                drop.add(u["id"])
                added.append({"cmd": "move", "id": u["id"], "x": round(spot[0], 1), "z": round(spot[1], 1),
                              "auto": True, "rally": True})
                bump("broken brigades sent on to high ground to rally (morale recovers faster there)")
                clock[u["id"]] = now
                vacated.append((u, e))
                continue
        if critical:
            clock.setdefault(("crit", u["id"]), now)
            # A long fallback, not a move: in the recorded battles a move ordered with the enemy in range did not
            # leave the spot 44 % of the time (the game makes the unit stop to fire), a fallback did.
            cmd = {"cmd": "fallback", "id": u["id"], "duration": float(cfg["retreat_seconds"]), "auto": True,
                   "relief": True}
            bump("auto retreats (brigade out of ammunition in contact)" if dry and u["morale"] >= float(cfg["critical_morale"])
                 else "auto retreats (brigade under critical morale in contact)")
        else:
            cmd = {"cmd": "fallback", "id": u["id"], "duration": float(cfg["fallback_seconds"]), "auto": True,
                   "relief": True}
            bump("auto pull-backs (brigade under retreat morale in contact)")
        drop.add(u["id"])
        added.append(cmd)
        clock[u["id"]] = now
        vacated.append((u, e))
    if cfg.get("rally_high_ground", True) and terrain is not None:
        for u in mine:
            if (u["kind"] != "Infantry" or u["morale"] >= float(cfg["rally_morale"]) or u["id"] in drop
                    or u["id"] in by_id or u["id"] in (pending_moves or {})
                    or unit_status(u) in DEAD_STATUSES + ("melee",)):
                continue
            near = nearest(u, foes)
            if not near or near[1] <= float(cfg["contact_distance"]):
                continue                               # still in contact: the fallback above handles it
            if now - clock.get(("rally", u["id"]), -1e9) < float(cfg["rally_cooldown_s"]):
                continue
            spot = rally_spot(u, near[0], terrain, cfg)
            if spot is None:
                continue
            clock[("rally", u["id"])] = now
            drop.add(u["id"])
            added.append({"cmd": "move", "id": u["id"], "x": round(spot[0], 1), "z": round(spot[1], 1),
                          "auto": True, "rally": True})
            bump("broken brigades sent on to high ground to rally (morale recovers faster there)")
    if cfg["replace"] and vacated:
        ordered = {o["id"] for o in orders if o["id"] not in drop}
        floor = max(float(cfg["replacement_min_morale"]), return_morale(cfg))
        pool = [r for r in mine
                if r["kind"] == "Infantry" and r["morale"] >= floor
                and _share(r) >= float(cfg["replacement_min_strength"]) and r["id"] not in drop
                and r["id"] not in (pending_moves or {})
                and unit_status(r) == ""
                and (r["id"] not in ordered or by_id[r["id"]]["cmd"] in ("hold", "move"))]
        # prefer brigades that are not firing at something right now
        def free(r):
            last = (last_cmds or {}).get(r["id"])
            return not (last and last.get("cmd") in ("attack", "range_attack", "charge"))
        avoid = set(avoid or ())
        pool.sort(key=lambda r: (r["id"] in avoid, not free(r)))
        n_inf = sum(1 for r in mine if r["kind"] == "Infantry")
        cap = max(int(cfg["max_replacements"]), int(round(float(cfg.get("replacements_share", 0.0)) * n_inf)))
        for u, e in vacated[:cap]:
            if trap is not None and trap(u["x"], u["z"], e):
                # WIP14: the slot is in a losing open sector with cover behind: nobody refills it
                bump("replacement not sent: the slot is in a losing open sector (cover behind it)")
                continue
            cands = [r for r in pool if r["id"] not in taken
                     and math.hypot(r["x"] - u["x"], r["z"] - u["z"]) <= float(cfg["replacement_max_distance"])]
            if not cands:
                continue
            best = min(cands, key=lambda r: (r["id"] in avoid, not free(r), math.hypot(r["x"] - u["x"], r["z"] - u["z"])))
            taken.add(best["id"])
            drop.add(best["id"])
            dx, dz = u["x"] - e["x"], u["z"] - e["z"]
            n = math.hypot(dx, dz) or 1.0
            spot = (u["x"] + dx / n * 30.0, u["z"] + dz / n * 30.0)
            added.append({"cmd": "move", "id": best["id"], "x": round(spot[0], 1), "z": round(spot[1], 1),
                          "fx": round(e["x"], 1), "fz": round(e["z"], 1), "auto": True})
            bump("auto replacements (fresh brigade into the slot of a retreating one)")
    return drop, added


def reserve_orders(state, orders, cfg, last_cmds, pending_moves, plan_mode=None, terrain=None, stats=None,
                   trap=None):
    """Send idle, healthy brigades that stand far from the enemy to the line once the commit time has come."""
    cfg = {**DEFAULT_RELIEF, **(cfg or {})}
    if not cfg["enabled"] or not cfg["reserve_commit"]:
        return []
    now_min = float(state.get("phaseTime", state.get("time", 0.0))) / 60.0   # minutes of this map (phase)
    commit = float(cfg["commit_minutes_attack"] if plan_mode == "ATTACK" else cfg["commit_minutes"])
    used = state.get("phaseUsed")
    if used is not None:
        # with a battle timer: a share of the phase's time (20 min of a 1 h battle = a third of it)
        share = float(cfg["commit_share_attack"] if plan_mode == "ATTACK" else cfg["commit_share"])
        if float(used) < share:
            return []
    elif now_min < commit:
        return []
    mine, foes = split_units(state)
    mine, foes = _live(mine), _live(foes)
    if not foes:
        return []
    ordered = {o["id"] for o in orders}
    inf = [u for u in mine if u["kind"] == "Infantry"]
    # the line = brigades that have an enemy in contact distance
    front = [u for u in inf if (nearest(u, foes) or (None, 1e9))[1] <= float(cfg["contact_distance"])
             and unit_status(u) == ""]
    if trap is not None:
        # WIP14: no reserve goes to a brigade standing in a losing open sector
        n_front = len(front)
        front = [f for f in front if not trap(f["x"], f["z"], nearest(f, foes)[0])]
        if len(front) < n_front and stats is not None:
            k = "reserve commit kept away from a losing open sector"
            stats[k] = stats.get(k, 0) + n_front - len(front)
    if not front:
        return []
    reserve = [u for u in inf
               if u["id"] not in ordered and u["id"] not in (pending_moves or {}) and unit_status(u) == ""
               and u["morale"] >= float(cfg["reserve_min_morale"]) and _share(u) >= float(cfg["reserve_min_strength"])
               and (nearest(u, foes) or (None, 1e9))[1] >= float(cfg["reserve_min_distance"])
               and not is_resting(u, last_cmds, cfg)
               and not ((last_cmds or {}).get(u["id"]) or {}).get("cmd") in ("attack", "range_attack", "charge")]
    if str(plan_mode or "").upper() in ("DEFEND", "TRADE"):
        kept = [u for u in reserve if holds_cover(u, state, terrain, cfg)]
        if kept and stats is not None:
            k = "reserve commit skipped: brigade holds fortifications or woods by an objective (defensive plan)"
            stats[k] = stats.get(k, 0) + len(kept)
        reserve = [u for u in reserve if u not in kept]
    if not reserve:
        return []
    keep = 1 if (now_min < float(cfg["release_minutes"]) and len(inf) >= 5) else 0
    reserve.sort(key=lambda u: (nearest(u, foes) or (None, 1e9))[1])
    cap = max(int(cfg["reserve_max_per_turn"]), int(round(float(cfg.get("reserve_per_turn_share", 0.0)) * len(inf))))
    send = reserve[:max(0, len(reserve) - keep)][:cap]
    out = []
    planned = []
    for k, u in enumerate(send):
        # go to the line brigade that is hardest pressed (nearest to the enemy), standing beside it
        anchor = min(front, key=lambda f: (nearest(f, foes) or (None, 1e9))[1] + 0.2 * math.hypot(f["x"] - u["x"], f["z"] - u["z"]))
        e = nearest(anchor, foes)[0]
        ex, ez = e["x"] - anchor["x"], e["z"] - anchor["z"]
        n = math.hypot(ex, ez) or 1.0
        px, pz = -ez / n, ex / n                     # along the line
        side = 1.0 if k % 2 == 0 else -1.0
        gap = 150.0 * (1 + k // 2)
        spot = find_clear_spot(anchor["x"] + px * gap * side, anchor["z"] + pz * gap * side, u, mine, planned, foes, terrain)
        if spot is None:
            continue
        planned.append(spot)
        out.append({"cmd": "move", "id": u["id"], "x": round(spot[0], 1), "z": round(spot[1], 1),
                    "fx": round(e["x"], 1), "fz": round(e["z"], 1), "auto": True})
        if stats is not None:
            key = "auto reserve commits (idle healthy brigade sent to the line)"
            stats[key] = stats.get(key, 0) + 1
    return out
