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
    "cooldown_s": 90.0,           # do not re-issue the pull-back to the same brigade sooner than this
    "rested_morale": 0.65,        # a pulled-back brigade is not sent forward again before this morale
    "replace": True,
    "max_replacements": 2,
    "replacement_min_morale": 0.7,
    "replacement_min_strength": 0.6,
    "replacement_max_distance": 1300.0,
    "reserve_commit": True,
    "commit_minutes": 20.0,       # idle healthy brigades go to the line from this battle time...
    "commit_minutes_attack": 8.0,   # ...or from this one when the plan is ATTACK
    "release_minutes": 40.0,      # one brigade stays in reserve until this battle time
    "reserve_min_distance": 700.0,  # an idle brigade this far from every enemy counts as reserve
    "reserve_min_morale": 0.7,
    "reserve_min_strength": 0.6,
    "reserve_max_per_turn": 2,
}

_STOP_CMDS = ("hold", "attack", "range_attack", "charge", "move")


def _share(u):
    return float(u["hp"]) / max(float(u["maxHp"]), 1.0)


def _live(units):
    return [u for u in units if unit_status(u) not in DEAD_STATUSES]


def is_resting(u, last_cmds, cfg=None):
    """True for a brigade that was pulled back and has not recovered enough to fight again."""
    cfg = {**DEFAULT_RELIEF, **(cfg or {})}
    last = (last_cmds or {}).get(u["id"])
    return bool(last and last.get("cmd") == "fallback" and last.get("relief") and u["morale"] < float(cfg["rested_morale"]))


def _wants_out(u, foes, cfg):
    if u["kind"] not in ("Infantry", "Cavalry", "Skirmish") or unit_status(u) in DEAD_STATUSES + ("fallback", "melee"):
        return None
    near = nearest(u, foes)
    if not near or near[1] > float(cfg["contact_distance"]):
        return None
    if u["morale"] < float(cfg["retreat_morale"]) or _share(u) < float(cfg["retreat_men"]):
        return near
    return None


def relief_orders(state, orders, cfg, last_cmds, pending_moves, terrain=None, clock=None, stats=None, avoid=None):
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
    for u in mine:
        near = _wants_out(u, foes, cfg)
        if not near:
            continue
        mine_order = by_id.get(u["id"])
        if mine_order and mine_order["cmd"] == "fallback":
            continue                                   # the model already pulls it back
        if mine_order and mine_order["cmd"] == "move":
            # a move away from the enemy is fine
            e = near[0]
            if math.hypot(mine_order["x"] - e["x"], mine_order["z"] - e["z"]) > near[1] + 100:
                continue
        critical = u["morale"] < float(cfg["critical_morale"])
        if not critical and now - clock.get(u["id"], -1e9) < float(cfg["cooldown_s"]):
            continue
        e = near[0]
        dx, dz = u["x"] - e["x"], u["z"] - e["z"]
        n = math.hypot(dx, dz) or 1.0
        if critical:
            dist = float(cfg["retreat_distance"])
            spot = find_clear_spot(u["x"] + dx / n * dist, u["z"] + dz / n * dist, u, mine, [], foes, terrain)
            if spot is None:
                spot = (u["x"] + dx / n * dist, u["z"] + dz / n * dist)
            cmd = {"cmd": "move", "id": u["id"], "x": round(spot[0], 1), "z": round(spot[1], 1),
                   "fx": round(e["x"], 1), "fz": round(e["z"], 1), "auto": True, "relief": True}
            bump("auto retreats (brigade under critical morale in contact)")
        else:
            cmd = {"cmd": "fallback", "id": u["id"], "duration": float(cfg["fallback_seconds"]), "auto": True,
                   "relief": True}
            bump("auto pull-backs (brigade under retreat morale in contact)")
        drop.add(u["id"])
        added.append(cmd)
        clock[u["id"]] = now
        vacated.append((u, e))
    if cfg["replace"] and vacated:
        ordered = {o["id"] for o in orders if o["id"] not in drop}
        pool = [r for r in mine
                if r["kind"] == "Infantry" and r["morale"] >= float(cfg["replacement_min_morale"])
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
        for u, e in vacated[:int(cfg["max_replacements"])]:
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


def reserve_orders(state, orders, cfg, last_cmds, pending_moves, plan_mode=None, terrain=None, stats=None):
    """Send idle, healthy brigades that stand far from the enemy to the line once the commit time has come."""
    cfg = {**DEFAULT_RELIEF, **(cfg or {})}
    if not cfg["enabled"] or not cfg["reserve_commit"]:
        return []
    now_min = float(state.get("time", 0.0)) / 60.0
    commit = float(cfg["commit_minutes_attack"] if plan_mode == "ATTACK" else cfg["commit_minutes"])
    if now_min < commit:
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
    if not front:
        return []
    reserve = [u for u in inf
               if u["id"] not in ordered and u["id"] not in (pending_moves or {}) and unit_status(u) == ""
               and u["morale"] >= float(cfg["reserve_min_morale"]) and _share(u) >= float(cfg["reserve_min_strength"])
               and (nearest(u, foes) or (None, 1e9))[1] >= float(cfg["reserve_min_distance"])
               and not is_resting(u, last_cmds, cfg)
               and not ((last_cmds or {}).get(u["id"]) or {}).get("cmd") in ("attack", "range_attack", "charge")]
    if not reserve:
        return []
    keep = 1 if (now_min < float(cfg["release_minutes"]) and len(inf) >= 5) else 0
    reserve.sort(key=lambda u: (nearest(u, foes) or (None, 1e9))[1])
    send = reserve[:max(0, len(reserve) - keep)][:int(cfg["reserve_max_per_turn"])]
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
