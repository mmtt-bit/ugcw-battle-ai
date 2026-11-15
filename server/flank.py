"""Flank guard (0.1.4 WIP7, from the battle of 2026-11-12 10:12).

A brigade held in front by one enemy and fired on from the flank by another (enfilade) lost 17.6 men and 0.133
morale per state in that battle, against 6.2 men and 0.029 morale when fired on from the front only: four times
the morale. The four brigades the South lost (37th NC and 7th NC, 4,000 men) were exactly the ones caught that way;
the player then charged them while they were shaken and captured them.

The plugin's face reflex does not help here: it turns a unit only when no enemy stands in front of it, and turning
would hand the front enemy the other flank anyway. The answer is the one of the period:
  1. refuse the flank: a fit brigade nearby, not fighting in front, engages the flanker;
  2. with nobody to do it, the brigade caught in the crossfire steps back out of it (fallback) before it breaks.
The prompt lists the brigades under flank fire so that the model can plan the line instead of leaving a flank open.
"""
import math

from supply import DEAD_STATUSES, split_units, unit_status

DEFAULT_FLANK = {
    "enabled": True,
    "flank_radius": 380.0,      # an enemy this close beside or behind a brigade threatens its flank
    "front_cos": 0.5,           # cosine with the brigade's facing: at or above = in front, below = flank or rear
    "threat_morale": 0.3,       # flankers under this morale are not a threat
    "helper_radius": 650.0,     # a brigade this close to the flanker can refuse the flank
    "helper_min_morale": 0.5,
    "fallback_morale": 0.75,    # without a helper, a flanked brigade under this morale steps back
    "fallback_s": 30.0,
    "max_per_turn": 3,
    "repeat_s": 90.0,           # the same answer for the same brigade is not repeated before this long
}

ENGAGED = ("melee", "routing", "retreat", "shattered", "captured", "gone")


def _d(a, b):
    return math.hypot(a["x"] - b["x"], a["z"] - b["z"])


def _facing(u):
    dx, dz = float(u.get("dx") or 0.0), float(u.get("dz") or 0.0)
    n = math.hypot(dx, dz)
    return (dx / n, dz / n) if n > 0.1 else None


def threats(state, cfg=None):
    """[(brigade, front enemy or None, flanker)] for our infantry fired on from the flank."""
    cfg = {**DEFAULT_FLANK, **(cfg or {})}
    mine, foes = split_units(state)
    live = [e for e in foes if unit_status(e) not in DEAD_STATUSES
            and e["kind"] in ("Infantry", "Cavalry", "Skirmish") and float(e.get("morale", 1.0)) >= cfg["threat_morale"]]
    out = []
    for u in mine:
        if u["kind"] not in ("Infantry", "Skirmish") or unit_status(u) != "" or u.get("offmap"):
            continue
        f = _facing(u)
        if f is None:
            continue
        front, flank = None, None
        for e in live:
            d = _d(u, e)
            if d < 1.0 or d > float(cfg["flank_radius"]):
                continue
            c = ((e["x"] - u["x"]) * f[0] + (e["z"] - u["z"]) * f[1]) / d
            if c >= float(cfg["front_cos"]):
                if front is None or d < _d(u, front):
                    front = e
            elif flank is None or d < _d(u, flank):
                flank = e
        if flank is not None:
            out.append((u, front, flank))
    return out


def flank_orders(state, orders, cfg, mem, skip_ids=(), stats=None):
    """Returns (ids whose own order is replaced, new orders). `mem`: brigade id -> time of the last answer."""
    cfg = {**DEFAULT_FLANK, **(cfg or {})}
    if not cfg["enabled"]:
        return set(), []
    now = float(state.get("time", 0.0))
    found = threats(state, cfg)
    if not found:
        return set(), []
    mine, _ = split_units(state)
    by_id = {o["id"]: o for o in orders}
    busy = {o["id"] for o in orders if o["cmd"] in ("attack", "charge", "range_attack", "fallback", "move")}
    used = set()
    drop, out = set(), []

    def bump(key):
        if stats is not None:
            stats[key] = stats.get(key, 0) + 1

    for u, front, flanker in sorted(found, key=lambda t: float(t[0]["morale"])):
        if len(out) >= int(cfg["max_per_turn"]):
            break
        if u["id"] in skip_ids or now - mem.get(u["id"], -1e9) < float(cfg["repeat_s"]):
            continue
        # 1. a fit brigade nearby that is not fighting in front of itself turns on the flanker
        helpers = []
        for v in mine:
            if (v["id"] == u["id"] or v["kind"] != "Infantry" or unit_status(v) != "" or v.get("offmap")
                    or v["id"] in skip_ids or v["id"] in busy or v["id"] in used
                    or float(v["morale"]) < float(cfg["helper_min_morale"])
                    or _d(v, flanker) > float(cfg["helper_radius"])):
                continue
            if any(t[0]["id"] == v["id"] for t in found):
                continue                                  # itself under flank fire
            helpers.append(v)
        if helpers:
            h = min(helpers, key=lambda v: _d(v, flanker))
            used.add(h["id"])
            if h["id"] in by_id:
                drop.add(h["id"])
            out.append({"cmd": "attack", "id": h["id"], "target": flanker["id"], "auto": True})
            mem[u["id"]] = now
            bump("flank refused: a nearby brigade turned on the enemy firing into a flank")
            continue
        # 2. nobody to cover it: out of the crossfire before it breaks
        if front is not None and float(u["morale"]) < float(cfg["fallback_morale"]) and u["id"] not in by_id:
            out.append({"cmd": "fallback", "id": u["id"], "duration": float(cfg["fallback_s"]), "auto": True})
            mem[u["id"]] = now
            bump("brigades pulled out of a crossfire (front and flank) with no brigade to cover the flank")
    return drop, out


def flank_lines(state, cfg=None):
    """One prompt line listing the brigades fired on from the flank (empty when none)."""
    found = threats(state, cfg)
    if not found:
        return []
    bits = []
    for u, front, flanker in found:
        bits.append(f"#{u['id']} by #{flanker['id']}" + (f" (and #{front['id']} in front)" if front else ""))
    return ["FLANK FIRE (enfilade costs about 4x the morale of frontal fire; cover the flank with a brigade, or "
            "pull the brigade back): " + "; ".join(bits)]
