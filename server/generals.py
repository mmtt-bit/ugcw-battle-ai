"""Generals: keep each one close enough to his brigades for his corps bonuses to reach them.

A general's corps perks (CorpsPerksBonuses.txt: accuracy, charge damage, speed...) only reach the brigades
of his corps that stand within his command radius. The plugin sends, for every unit, its corps id ("corps"),
and for a general his command radius ("commandRadius"). This module:

* shows the model a GENERALS block (corps, radius, how many of his brigades are inside, where they stand);
* validates the model's move orders for generals (the only order a general takes): a destination too close to
  a known enemy is pulled back behind the brigades;
* moves an idle general by itself when too few of his brigades are inside his radius, or when an enemy
  comes too close to him ("auto": true).

Switch it off in config.json ("generals").
"""
import math

from prompting import DEAD_STATUSES, nearest, split_units, unit_status

DEFAULT_GENERALS = {
    "enabled": True,
    "auto_follow": True,
    "min_inside_share": 0.6,     # move the general when fewer of his brigades than this are inside his radius
    "safe_distance": 650.0,      # never closer than this to a known enemy (fire range + margin)
    "danger_distance": 450.0,    # an enemy this close: pull the general back at once
    "behind_share": 0.35,        # stand this share of his radius behind the centre of his brigades
    "default_radius": 0.0,       # used when the plugin sends no radius (0 = no automatic move)
    "min_move": 120.0,           # do not move for less than this
}

COMMANDED = ("Infantry", "Cavalry", "Artillery", "Skirmish")


def _d(a, b):
    return math.hypot(a["x"] - b["x"], a["z"] - b["z"])


def _live(units):
    return [u for u in units if unit_status(u) not in DEAD_STATUSES]


def corps_of(general, mine):
    """The brigades of the general's corps (same corps id), or [] when the plugin sends no corps ids."""
    cid = general.get("corps")
    if cid is None or int(cid) < 0:
        return []
    return [u for u in mine if u is not general and u["kind"] in COMMANDED and u.get("corps") == cid]


def radius_of(general, cfg):
    r = general.get("commandRadius")
    try:
        r = float(r)
    except (TypeError, ValueError):
        r = 0.0
    return r if r > 0 else float(cfg["default_radius"])


def _station(general, brigades, foes, radius, cfg, terrain=None):
    """Behind the centre of his brigades (away from the nearest enemy), and safe from enemy fire."""
    cx = sum(u["x"] for u in brigades) / len(brigades)
    cz = sum(u["z"] for u in brigades) / len(brigades)
    centre = {"x": cx, "z": cz}
    near = nearest(centre, foes) if foes else None
    if near:
        e = near[0]
        dx, dz = cx - e["x"], cz - e["z"]
        n = math.hypot(dx, dz) or 1.0
        back = radius * float(cfg["behind_share"])
        x, z = cx + dx / n * back, cz + dz / n * back
        # keep a safe distance from every known enemy: walk further back if needed
        for _ in range(8):
            close = nearest({"x": x, "z": z}, foes)
            if not close or close[1] >= float(cfg["safe_distance"]):
                break
            x, z = x + dx / n * 80.0, z + dz / n * 80.0
    else:
        x, z = cx, cz
    if terrain is not None:
        spot = terrain.nearest_passable(x, z)
        if spot is not None:
            x, z = spot
    return round(x, 1), round(z, 1)


def general_lines(state, cfg=None):
    cfg = {**DEFAULT_GENERALS, **(cfg or {})}
    if not cfg["enabled"]:
        return []
    mine, foes = split_units(state)
    mine, foes = _live(mine), _live(foes)
    gens = [u for u in mine if u["kind"] == "General"]
    if not gens:
        return []
    lines = ["GENERALS (corps perks reach only the brigades inside the command radius; a general takes only move):"]
    for g in gens:
        brigades = corps_of(g, mine)
        radius = radius_of(g, cfg)
        near = nearest(g, foes)
        txt = f"  {g['name']} (#{g['id']}) at {g['x']:.0f},{g['z']:.0f}"
        if g.get("corps") is not None:
            txt += f", corps {g['corps']}"
        if radius > 0:
            txt += f", command radius {radius:.0f}"
        if brigades and radius > 0:
            inside = sum(1 for u in brigades if _d(u, g) <= radius)
            cx = sum(u["x"] for u in brigades) / len(brigades)
            cz = sum(u["z"] for u in brigades) / len(brigades)
            txt += f": {inside} of {len(brigades)} brigades inside; their centre at {cx:.0f},{cz:.0f}"
            out = [u for u in brigades if _d(u, g) > radius]
            if out:
                txt += " (outside: " + ", ".join(f"#{u['id']}" for u in out[:6]) + ")"
        elif not brigades:
            txt += " (corps of his brigades unknown)"
        if near:
            txt += f"; nearest enemy {near[1]:.0f}" + (" - TOO CLOSE" if near[1] < float(cfg["safe_distance"]) else "")
        lines.append(txt)
    return lines


def sanitize_generals(raw_orders, state, terrain=None, cfg=None, stats=None):
    """Takes the model's orders for generals out of the list. Returns (general orders, the other raw orders)."""
    cfg = {**DEFAULT_GENERALS, **(cfg or {})}
    mine, foes = split_units(state)
    gens = {u["id"]: u for u in _live(mine) if u["kind"] == "General"}
    live_foes = _live(foes)
    out, rest, seen = [], [], set()
    for o in raw_orders or []:
        try:
            uid = int(o.get("id"))
        except (TypeError, ValueError, AttributeError):
            rest.append(o)
            continue
        if uid not in gens:
            rest.append(o)
            continue
        if o.get("cmd") != "move" or uid in seen or not cfg["enabled"]:
            continue
        try:
            x, z = float(o["x"]), float(o["z"])
        except (KeyError, TypeError, ValueError):
            continue
        if terrain is not None:
            spot = terrain.nearest_passable(x, z)
            if spot is None:
                continue
            x, z = spot
        close = nearest({"x": x, "z": z}, live_foes) if live_foes else None
        if close and close[1] < float(cfg["safe_distance"]):
            g = gens[uid]
            brigades = corps_of(g, mine) or [u for u in mine if u["kind"] in COMMANDED]
            if not brigades:
                continue
            x, z = _station(g, brigades, live_foes, radius_of(g, cfg) or 300.0, cfg, terrain)
            if stats is not None:
                key = "general moves pulled back (too close to the enemy)"
                stats[key] = stats.get(key, 0) + 1
        out.append({"cmd": "move", "id": uid, "x": round(x, 1), "z": round(z, 1)})
        seen.add(uid)
    return out, rest


def general_orders(state, orders, cfg, last_cmds, pending_moves, terrain=None, stats=None):
    """Moves idle generals that are too far from their brigades or too close to the enemy."""
    cfg = {**DEFAULT_GENERALS, **(cfg or {})}
    if not cfg["enabled"] or not cfg["auto_follow"]:
        return []
    mine, foes = split_units(state)
    mine, foes = _live(mine), _live(foes)
    ordered = {o["id"] for o in orders}
    out = []
    for g in (u for u in mine if u["kind"] == "General"):
        if g["id"] in ordered:
            continue
        brigades = corps_of(g, mine)
        radius = radius_of(g, cfg)
        if not brigades or radius <= 0:
            continue
        near = nearest(g, foes) if foes else None
        danger = bool(near and near[1] < float(cfg["danger_distance"]))
        inside = sum(1 for u in brigades if _d(u, g) <= radius)
        if not danger and inside >= float(cfg["min_inside_share"]) * len(brigades):
            continue
        x, z = _station(g, brigades, foes, radius, cfg, terrain)
        pend = (pending_moves or {}).get(g["id"])
        if pend and math.hypot(pend[0] - x, pend[1] - z) < float(cfg["min_move"]):
            continue
        if math.hypot(g["x"] - x, g["z"] - z) < float(cfg["min_move"]) and not danger:
            continue
        out.append({"cmd": "move", "id": g["id"], "x": x, "z": z, "auto": True})
        if stats is not None:
            key = ("auto general moves (enemy too close)" if danger else
                   "auto general moves (to keep his brigades inside his command radius)")
            stats[key] = stats.get(key, 0) + 1
    return out
