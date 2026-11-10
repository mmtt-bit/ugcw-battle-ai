"""Cohesion: keep the army together.

In the Shiloh battle of 2026-11-10 (phase 3) the brigade Anderson was sent to "attack" enemy skirmishers. The
skirmishers fell back, Anderson followed them for 1,700 units, far from the rest of the army and from every
objective, and the player surrounded and captured it. Two rules here:

- chases on a leash: infantry may pursue skirmishers or cavalry (skirmishers fire from 600-700, a line must not
  just stand and take it) while it stays within `chase_leash` of friendly infantry or artillery; past that, a chase
  of a target beyond its fire range stops, and a brigade still under fire walks back towards its friends, out of
  the shooter's reach (light troops fall back faster than a line can follow, and lure it away);
- leash: a brigade far from every friendly combat unit and from every objective is brought back towards the army
  (a fallback first when it is in contact), unless it is a scout. The model's own orders that would send a unit
  out there alone are replaced in the same way.
"""

import math

from prompting import DEAD_STATUSES, nearest, split_units, unit_status

DEFAULT_COHESION = {
    "enabled": True,
    "leash_friends": 650.0,      # farther than this from any friendly infantry / artillery...
    "leash_objective": 800.0,    # ...and from any objective: the unit is out on its own
    "recall_short_of": 250.0,    # it walks back to this distance from the nearest friends
    "max_per_turn": 4,
    "no_chase": True,
    "chase_leash": 450.0,        # a brigade may chase skirmishers / cavalry while it stays this close to friends...
    "chase_margin": 100.0,       # ...beyond that, an attack on light troops past its fire range + this is stopped
    "out_of_reach_margin": 60.0, # a stopped brigade under fire steps back this far out of the shooter's range
}

COMBAT = ("Infantry", "Artillery")


def _d(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def cohesion_orders(state, orders, objectives, scout_ids=(), skip_ids=(), last_cmds=None, cfg=None, stats=None,
                    assault_ids=(), previous_hp=None):
    """Returns (ids whose order is dropped, new orders). `assault_ids`: members of an assault group, whose attacks
    on the defenders are not chases (the leash still applies to them)."""
    cfg = {**DEFAULT_COHESION, **(cfg or {})}
    if not cfg["enabled"]:
        return set(), []
    mine, foes = split_units(state)
    mine = [u for u in mine if unit_status(u) not in DEAD_STATUSES]
    live = {e["id"]: e for e in foes if unit_status(e) not in DEAD_STATUSES}
    pts = [(o["x"], o["z"]) for o in objectives or []]
    by_order = {o["id"]: o for o in orders}
    drop, out = set(), []

    def bump(key):
        if stats is not None:
            stats[key] = stats.get(key, 0) + 1

    for u in mine:
        if len(out) >= int(cfg["max_per_turn"]):
            break
        if (u["kind"] in ("General", "Supply", "Artillery") or u["id"] in scout_ids or u["id"] in skip_ids
                or unit_status(u) in ("melee", "fallback", "routing")):
            continue
        own = by_order.get(u["id"])
        last = (last_cmds or {}).get(u["id"]) or {}
        cmd = own or last
        friends = [(f["x"], f["z"]) for f in mine if f["id"] != u["id"] and f["kind"] in COMBAT]
        # 1. chases on a leash: skirmishers (who shoot from 600-700) and cavalry may be pursued while the brigade
        #    stays close to its friends; past that leash the chase stops, and a brigade still under fire steps back
        #    towards its friends, out of the shooter's reach, instead of standing there
        if (cfg["no_chase"] and u["kind"] in COMBAT and u["id"] not in assault_ids and friends
                and cmd.get("cmd") == "attack" and cmd.get("target") in live):
            e = live[cmd["target"]]
            here = (u["x"], u["z"])
            rng = float(u.get("range") or 300.0)
            d_e = _d(here, (e["x"], e["z"]))
            d_friend = min(_d(here, f) for f in friends)
            if (e["kind"] in ("Skirmish", "Cavalry") and d_e > rng + float(cfg["chase_margin"])
                    and d_friend > float(cfg["chase_leash"])):
                if own:
                    drop.add(u["id"])
                lost = (float((previous_hp or {}).get(u["id"], u["hp"])) - float(u["hp"])) if previous_hp else 0.0
                reach = float(e.get("range") or 650.0)
                if lost > 0 or d_e <= reach:
                    fx, fz = min(friends, key=lambda f: _d(here, f))
                    n = _d(here, (fx, fz)) or 1.0
                    # walk towards the friends until out of reach (or next to them)
                    step = min(max(0.0, n - float(cfg["recall_short_of"])),
                               max(150.0, reach + float(cfg["out_of_reach_margin"]) - d_e))
                    x, z = u["x"] + (fx - u["x"]) / n * step, u["z"] + (fz - u["z"]) / n * step
                    out.append({"cmd": "move", "id": u["id"], "x": round(x, 1), "z": round(z, 1),
                                "fx": round(e["x"], 1), "fz": round(e["z"], 1), "auto": True})
                    bump("chases stopped at the leash: brigade under fire stepped back towards its friends")
                else:
                    out.append({"cmd": "hold", "id": u["id"], "auto": True})
                    bump("chases stopped at the leash (skirmishers / cavalry pursued too far from friends)")
                continue
        # 2. leash
        if not friends:
            continue
        leash_f, leash_o = float(cfg["leash_friends"]), float(cfg["leash_objective"])
        if u["kind"] == "Skirmish":
            leash_f, leash_o = 2 * leash_f, 2 * leash_o   # a screen goes ahead of the line by design

        def alone(p):
            return (min(_d(p, f) for f in friends) > leash_f
                    and min((_d(p, q) for q in pts), default=math.inf) > leash_o)

        here = (u["x"], u["z"])
        where = None                                   # where the unit's order of this turn takes it
        if own and own.get("cmd") == "move":
            where = (float(own["x"]), float(own["z"]))
        elif own and own.get("cmd") in ("attack", "charge") and own.get("target") in live:
            where = (live[own["target"]]["x"], live[own["target"]]["z"])
        near = nearest(u, list(live.values())) if live else None
        in_contact = bool(near and near[1] <= float(u.get("range") or 300.0) * 1.1)
        if not alone(here):
            if where is not None and alone(where):
                # the order would send the brigade out alone, far from the army and the objectives
                drop.add(u["id"])
                bump("orders dropped: they sent a brigade alone far from the army and the objectives")
            continue
        if in_contact:
            if own:
                drop.add(u["id"])
            out.append({"cmd": "fallback", "id": u["id"], "duration": 20.0, "auto": True})
            bump("isolated brigades in contact fell back towards the army")
            continue
        if where is not None and not alone(where):
            continue                                   # its order already brings it back
        if own:
            drop.add(u["id"])
        fx, fz = min(friends, key=lambda f: _d(here, f))
        dist = _d(here, (fx, fz))
        go = max(0.0, dist - float(cfg["recall_short_of"]))
        x = u["x"] + (fx - u["x"]) / (dist or 1.0) * go
        z = u["z"] + (fz - u["z"]) / (dist or 1.0) * go
        o = {"cmd": "move", "id": u["id"], "x": round(x, 1), "z": round(z, 1), "auto": True}
        if near:
            o.update(fx=round(near[0]["x"], 1), fz=round(near[0]["z"], 1))
        out.append(o)
        bump("isolated brigades brought back towards the army")
    return drop, out
