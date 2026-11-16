"""March columns: road column for long marches, back in line near the enemy.

The game has two formations, "Line" and "RoadColumn". The model almost never used the second one (not once in the
recorded battle of 2026-11-11), so the server does it, as a player would:

- a unit on a long march (at least `min_distance` still to walk, no known enemy within `deploy_distance` +
  `enter_margin`) is put in road column;
- a column goes back to line as soon as a known enemy (visible, or seen in the last `memory_s` seconds) is within
  `deploy_distance`, or would be by the next state at the rate the gap is closing (`anticipate`); also when it
  loses men (unseen fire), when its march ends or is replaced by another order, and near its destination.

The plugin does not report the formation of a unit, so the server remembers which units it put in column
(`columns`: unit id -> battle time). A formation changed by hand in the game is not seen.

Not measured: how much faster a road column marches. The terrain tooltips say nothing about formations.
"""

import math

from prompting import split_units, unit_status

DEFAULT_MARCH = {
    "enabled": True,
    "kinds": ["Infantry"],       # unit kinds put in road column
    "min_distance": 500.0,       # a march with at least this far to go is made in road column
    "deploy_distance": 600.0,    # back in line when a known enemy is within this distance
    "enter_margin": 150.0,       # no column when an enemy is within deploy_distance + this (no flip-flop)
    "arrive_distance": 150.0,    # back in line this close to the destination
    "anticipate": True,          # deploy one state early when the gap would be under deploy_distance by the next one
    "memory_s": 300.0,           # enemies out of sight count for this long at their last known position
    "max_per_turn": 12,          # formation orders per state
}

FORMATION_LINE, FORMATION_COLUMN = "Line", "RoadColumn"
NO_COLUMN_STATUSES = ("melee", "fallback", "routing", "charging")
GONE_STATUSES = ("shattered", "captured")   # a routing unit may rally: it is put back in line, not forgotten


def march_note(cfg=None):
    """One line for the system prompt (ORDERS list): who handles the formations."""
    cfg = {**DEFAULT_MARCH, **(cfg or {})}
    if not cfg["enabled"]:
        return ('- {"cmd": "formation", "id": 9, "value": "Line"}  "Line" or "RoadColumn" (column for long '
                "marches; back to Line before combat)")
    kinds = " and ".join(k.lower() for k in cfg["kinds"]) or "no unit"
    return ("- Formations are the server's job: " + kinds + f" marching {float(cfg['min_distance']):.0f}+ goes in "
            f"road column and deploys in line {float(cfg['deploy_distance']):.0f} from a known enemy. Do not order "
            "formations.")


def _nearest_foe(u, foes):
    best = None
    for e in foes:
        d = math.hypot(u["x"] - e["x"], u["z"] - e["z"])
        if best is None or d < best:
            best = d
    return best


def march_orders(state, orders, pending, columns, gaps, cfg=None, remembered=(), previous_hp=None, stats=None):
    """Formation orders for this state, to be sent BEFORE the other orders of the same units.

    `orders`: the final orders of this state. `pending`: unit id -> (x, z, time) of moves still running.
    `columns` (unit id -> battle time) and `gaps` (unit id -> (battle time, distance to the nearest known enemy))
    are the server's memory, updated in place. `remembered`: enemies out of sight, with "x", "z" and "t".
    """
    cfg = {**DEFAULT_MARCH, **(cfg or {})}
    if not cfg["enabled"]:
        if columns:
            # switched off in config.json during a battle: nobody is left in column
            out = [{"cmd": "formation", "id": i, "value": FORMATION_LINE, "auto": True} for i in sorted(columns)]
            columns.clear()
            return out
        return []
    now = float(state.get("time", 0.0))
    mine, foes = split_units(state)
    foes = [e for e in foes if unit_status(e) not in GONE_STATUSES]
    seen = {e["id"] for e in foes}
    foes = foes + [m for m in remembered if m.get("id") not in seen
                   and now - float(m.get("t", now)) <= float(cfg["memory_s"])]
    deploy_d = float(cfg["deploy_distance"])
    by_order = {}
    for o in orders:
        if o.get("cmd") not in ("ammo", "supply", "limber", "mount", "gait", "detach", "recall"):   # switches do not replace a march
            by_order[o["id"]] = o
    alive = set()
    out = []

    def bump(key):
        if stats is not None:
            stats[key] = stats.get(key, 0) + 1

    for u in mine:
        uid = u["id"]
        if unit_status(u) in GONE_STATUSES:
            continue
        alive.add(uid)
        d_foe = _nearest_foe(u, foes)
        prev = gaps.get(uid)
        if d_foe is None:
            gaps.pop(uid, None)
        else:
            gaps[uid] = (now, d_foe)
        own = by_order.get(uid)
        if own is not None and own.get("cmd") == "formation":
            # the model's own formation order wins; the server only remembers it
            if own.get("value") == FORMATION_COLUMN:
                columns[uid] = now
            else:
                columns.pop(uid, None)
            continue
        # where the unit is marching to, if it is
        dest = None
        if own is not None:
            if own.get("cmd") == "move":
                dest = (float(own["x"]), float(own["z"]))
        elif uid in (pending or {}):
            dest = (float(pending[uid][0]), float(pending[uid][1]))
        left = math.hypot(dest[0] - u["x"], dest[1] - u["z"]) if dest else 0.0
        # the gap at the next state, at the rate it closed since the last one
        ahead = d_foe
        if cfg["anticipate"] and d_foe is not None and prev is not None and now > prev[0]:
            ahead = d_foe - max(0.0, prev[1] - d_foe)
        lost = (float((previous_hp or {}).get(uid, u["hp"])) - float(u["hp"])) if previous_hp else 0.0

        if uid in columns:
            why = None
            if d_foe is not None and d_foe <= deploy_d:
                why = f"columns deployed in line (known enemy within {deploy_d:.0f})"
            elif ahead is not None and ahead <= deploy_d:
                why = f"columns deployed in line (enemy closing, under {deploy_d:.0f} by the next state)"
            elif lost > 0.5:
                why = "columns deployed in line (losing men on the march)"
            elif unit_status(u) in NO_COLUMN_STATUSES:
                why = "columns deployed in line (melee, fallback or rout)"
            elif dest is None:
                why = "columns deployed in line (march over or replaced by another order)"
            elif left <= float(cfg["arrive_distance"]):
                why = "columns deployed in line (near the destination)"
            if why and len(out) < int(cfg["max_per_turn"]):
                out.append({"cmd": "formation", "id": uid, "value": FORMATION_LINE, "auto": True})
                del columns[uid]
                bump(why)
            continue
        if (u["kind"] in cfg["kinds"] and dest is not None and left >= float(cfg["min_distance"])
                and unit_status(u) not in NO_COLUMN_STATUSES and lost <= 0.5
                and (d_foe is None or d_foe > deploy_d + float(cfg["enter_margin"]))
                and (ahead is None or ahead > deploy_d)
                and len(out) < int(cfg["max_per_turn"])):
            out.append({"cmd": "formation", "id": uid, "value": FORMATION_COLUMN, "auto": True})
            columns[uid] = now
            bump("long marches made in road column")
    for uid in [i for i in columns if i not in alive]:
        del columns[uid]                               # destroyed or captured
    for uid in [i for i in gaps if i not in alive]:
        del gaps[uid]
    return out
