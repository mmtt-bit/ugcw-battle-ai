"""WIP17 (Antietam, 2026-11-15): crossings and field works in the prompt.

CROSSINGS: at 300-352 min 10-12 fresh AI brigades (15-18k men) stood out of contact while the middle bridge was
empty and the Stone Bridge was held by one brigade (captured). Each ford or bridge near an objective or near the
enemy gets a line: our men within crossing_own, enemy men within crossing_enemy, the nearest fresh brigade.

FORTIFICATIONS: the map had 703 fortification cells and the AI never had more than 3 brigades in them, because
nothing ever asked the game to occupy a work (the player right-clicks its shield). The plugin (WIP17) reports the
works in "fortifications" and runs {"cmd": "fortify", "id": N}; this block lists the free works worth taking.
"""
import math

from prompting import DEAD_STATUSES, split_units, unit_status

DEFAULT_WORKS = {
    "crossings": True,
    "crossing_own": 700.0,        # our men this close to a ford or bridge hold it
    "crossing_enemy": 1000.0,     # enemy men this close threaten it
    "crossing_objective": 2500.0, # a crossing this close to an objective is listed even without an enemy near
    "crossing_lines": 6,
    "fresh_morale": 0.7,          # a reserve brigade: morale at least this...
    "fresh_contact": 500.0,       # ...and no enemy within this
    "fortifications": True,
    "works_reach": 1200.0,        # a free work this close to one of our objectives or brigades is listed
    "works_lines": 6,
}


def _d(a, b):
    return math.hypot(float(a["x"]) - float(b["x"]), float(a["z"]) - float(b["z"]))


def _alive(units):
    return [u for u in units if unit_status(u) not in DEAD_STATUSES]


def _men(units):
    return sum(float(u.get("hp") or 0) for u in units)


def fresh_brigades(mine, foes, cfg, exclude=()):
    """Our infantry brigades in good order and out of contact (reserves)."""
    return [u for u in mine if u["kind"] == "Infantry" and u["id"] not in exclude
            and float(u.get("morale") or 0) >= cfg["fresh_morale"] and unit_status(u) == ""
            and not u.get("fort") and all(_d(u, e) > cfg["fresh_contact"] for e in foes)]


def crossing_lines(state, terrain, cfg=None):
    cfg = {**DEFAULT_WORKS, **(cfg or {})}
    if not cfg["crossings"] or terrain is None or not hasattr(terrain, "crossings"):
        return []
    mine, foes = split_units(state)
    mine, foes = _alive(mine), _alive(foes)
    if not mine:
        return []
    objs = state.get("objectives") or []
    reserves = fresh_brigades(mine, foes, cfg)
    rows = []
    for c in terrain.crossings():
        own = [u for u in mine if u["kind"] != "Artillery" and _d(u, c) <= cfg["crossing_own"]]
        foe = [e for e in foes if e["kind"] != "Artillery" and _d(e, c) <= cfg["crossing_enemy"]]
        near_obj = min((_d(o, c) for o in objs if "x" in o and "z" in o), default=1e9)
        if not foe and near_obj > cfg["crossing_objective"]:
            continue
        own_m, foe_m = _men(own), _men(foe)
        if foe_m > 0 and own_m == 0:
            flag, rank = "THREATENED AND EMPTY", 0
        elif foe_m > own_m * 1.5:
            flag, rank = "OUTNUMBERED", 1
        elif foe_m > 0:
            flag, rank = "contested", 2
        elif own_m == 0:
            flag, rank = "empty, no enemy near", 3
        else:
            flag, rank = "held", 4
        text = (f"  {c['kind'].lower()} at {c['x']},{c['z']}: yours {own_m:.0f} men within {cfg['crossing_own']:.0f}"
                f", enemy {foe_m:.0f} within {cfg['crossing_enemy']:.0f} -> {flag}")
        if rank <= 1:
            pool = [u for u in reserves if u not in own]
            if pool:
                r = min(pool, key=lambda u: _d(u, c))
                text += f"; nearest reserve #{r['id']} ({float(r['hp']):.0f} men) at {_d(r, c):.0f}"
            else:
                text += "; no fresh brigade out of contact"
        rows.append((rank, near_obj, text))
    if not rows:
        return []
    rows.sort(key=lambda r: (r[0], r[1]))
    head = (f"CROSSINGS (fords and bridges; {len(reserves)} fresh brigade(s) out of contact, "
            f"{_men(reserves):.0f} men, are your reserve):")
    return [head] + [t for _, _, t in rows[:int(cfg["crossing_lines"])]]


def fortification_lines(state, cfg=None):
    cfg = {**DEFAULT_WORKS, **(cfg or {})}
    works = state.get("fortifications")
    if not cfg["fortifications"] or not isinstance(works, list) or not works:
        return []
    mine, foes = split_units(state)
    mine, foes = _alive(mine), _alive(foes)
    if not mine:
        return []
    side = mine[0].get("side")
    held = [o for o in state.get("objectives") or [] if o.get("side") == side and "x" in o and "z" in o]
    inside = [u for u in mine if u.get("fort")]
    takers = [u for u in mine if u["kind"] == "Infantry" and not u.get("fort") and unit_status(u) == ""]
    rows = []
    for w in works:
        if not w.get("free") or float(w.get("hp") or 0) <= 0 or "x" not in w or "z" not in w:
            continue
        near_obj = min((_d(o, w) for o in held), default=1e9)
        near_own = min((_d(u, w) for u in mine), default=1e9)
        if min(near_obj, near_own) > cfg["works_reach"]:
            continue
        foe_d = min((_d(e, w) for e in foes), default=1e9)
        text = f"  free work at {round(float(w['x']))},{round(float(w['z']))}"
        if near_obj < 1e9:
            text += f", {near_obj:.0f} from an objective you hold"
        text += f", nearest enemy {foe_d:.0f}" if foe_d < 1e9 else ""
        if takers:
            t = min(takers, key=lambda u: _d(u, w))
            text += f"; nearest brigade #{t['id']} at {_d(t, w):.0f}"
        rows.append((min(near_obj, 1e8), foe_d, text))
    if not rows:
        return []
    rows.sort(key=lambda r: (r[0], r[1]))
    return ([f"FORTIFICATIONS ({len(inside)} of your brigades in works; a brigade in a work takes far less fire. "
             "{\"cmd\": \"fortify\", \"id\": N, \"x\": X, \"z\": Z} marches brigade N into the free work at "
             "X,Z; without x/z, into the nearest free work within 400 m):"]
            + [t for _, _, t in rows[:int(cfg["works_lines"])]])
