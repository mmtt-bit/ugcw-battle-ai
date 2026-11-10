"""Artillery readiness and placement: ready to fire or packed, smoothbore versus rifled.

The plugin reports for each battery "limber": ready (unlimbered, can fire), packing (limbering up),
unpacking (unlimbering) or packed (limbered, on the move, cannot fire). A move order packs a battery up
and it needs time to unpack before it fires again; a fallback order backs it off a little while it
stays unlimbered and keeps loading. Smoothbore guns lose effect with distance, so they should be
brought close to the front (behind the infantry line); rifled guns can stay back.
"""
import math

from equipment import unit_range, weapon_label

DEFAULT_BATTERY = {
    "enabled": True,
    "backstep_max": 200.0,        # a move this short, away from the enemy, becomes a fallback
    "fallback_seconds": 12.0,     # duration of that fallback
    "advance_share": 0.85,        # smoothbore guns are brought to this share of their range from the enemy
    "cover_gap": 60.0,            # ...but never closer to the enemy than the infantry in front, minus this gap
    "default_range": 700.0,       # used when the plugin reports no range for the battery
}

READY = ("ready", "")


def is_smoothbore(u):
    return "smoothbore" in weapon_label(u.get("weapon"))


def limber_state(u):
    return str(u.get("limber") or "ready")


def is_ready(u):
    return limber_state(u) in READY


def _live(units):
    return [u for u in units if str(u.get("status") or "") not in ("routing", "shattered", "captured")]


def _nearest(u, others):
    best = None
    for o in others:
        d = math.hypot(o["x"] - u["x"], o["z"] - u["z"])
        if best is None or d < best[1]:
            best = (o, d)
    return best


def advance_spot(b, e, mine, cfg, r):
    """Where a smoothbore battery should stand: within range of enemy `e`, level with the infantry
    that screens it (not in front of it). Returns (x, z) or None when it is already well placed."""
    d = math.hypot(e["x"] - b["x"], e["z"] - b["z"])
    guards = [g for g in mine if g["kind"] in ("Infantry", "Cavalry") and g["morale"] >= 0.5
              and math.hypot(g["x"] - b["x"], g["z"] - b["z"]) <= 500
              and math.hypot(g["x"] - e["x"], g["z"] - e["z"]) < d + 150]
    if not guards:
        return None
    front = min(math.hypot(g["x"] - e["x"], g["z"] - e["z"]) for g in guards)
    stand = max(float(cfg["advance_share"]) * r, front + float(cfg["cover_gap"]))
    if stand >= d - 30.0:
        return None
    ux, uz = (b["x"] - e["x"]) / (d or 1.0), (b["z"] - e["z"]) / (d or 1.0)
    return e["x"] + ux * stand, e["z"] + uz * stand


def battery_lines(state, cfg=None):
    cfg = {**DEFAULT_BATTERY, **(cfg or {})}
    if not cfg["enabled"]:
        return []
    player = state["playerSide"]
    mine = _live([u for u in state["units"] if u["side"] != player])
    foes = _live([u for u in state["units"] if u["side"] == player])
    bats = [u for u in mine if u["kind"] == "Artillery"]
    if not bats:
        return []
    lines = ["BATTERIES (see READING THE STATE):"]
    for b in bats:
        r = unit_range(b, cfg["default_range"])
        near = _nearest(b, foes)
        state_txt = limber_state(b)
        kind = "smoothbore" if is_smoothbore(b) else ("rifled" if "rifled" in weapon_label(b.get("weapon")) else "gun")
        txt = f"- {b['name']} (#{b['id']}) {kind}, {state_txt}, range {r:.0f}"
        if near:
            e, d = near
            txt += f", nearest enemy {e['name']} (#{e['id']}) at {d:.0f}"
            if state_txt in ("packed", "packing"):
                txt += ": PACKED, it cannot fire; unpack it with the limber order (value unpack); the server also does it for a battery that is not marching"
                if d <= r:
                    txt += " NOW (enemy already in range)"
            elif state_txt == "unpacking":
                txt += ": unlimbering, it fires soon"
            elif d <= r:
                txt += ": in range, keep firing; to step back a little use fallback, not move"
            elif kind == "smoothbore":
                spot = advance_spot(b, e, mine, cfg, r)
                if spot is not None:
                    txt += (f": out of range by {d - r:.0f}. Smoothbore fire is far better at short range: move it up "
                            f"to {spot[0]:.0f},{spot[1]:.0f}, level with the infantry, never in front of it")
                else:
                    txt += ": out of range; bring it forward only together with a steady infantry brigade"
            else:
                txt += f": out of range by {d - r:.0f}; rifled guns shoot far, keep it on good ground and move only to stay in reach"
        lines.append(txt)
    return lines


FORCE_AFTER = 2     # normal unpack orders that failed before the server forces the unlimbering


def unpack_orders(state, orders, pending_moves=None, stats=None, tries=None):
    """A battery whose march was cancelled (a hold or a new order while it was moving) stays packed
    for good and never fires. Unpack every packed battery that is not on a march this turn.

    `tries` (kept between turns) counts the unpack orders given to a battery that is still packed. In the
    battle of 2026-11-09 one battery got 25 plain unpack orders in a row and never fired: after FORCE_AFTER
    failed tries the order becomes "unpack_force", which clears the limbering state in the plugin, and the
    plugin's state dump (limberInfo) is printed so the cause can be found."""
    player = state["playerSide"]
    mine = _live([u for u in state["units"] if u["side"] != player])
    moving = {o["id"] for o in orders if o["cmd"] == "move"}
    tries = tries if tries is not None else {}
    out = []
    for u in mine:
        if u["kind"] != "Artillery":
            continue
        if limber_state(u) not in ("packed", "packing"):
            tries.pop(u["id"], None)
            continue
        if u["id"] in moving or u["id"] in (pending_moves or {}):
            tries.pop(u["id"], None)
            continue
        if any(o["id"] == u["id"] and o["cmd"] == "limber" for o in orders):
            continue
        n = tries.get(u["id"], 0)
        tries[u["id"]] = n + 1
        value = "unpack_force" if n >= FORCE_AFTER else "unpack"
        out.append({"cmd": "limber", "id": u["id"], "value": value, "auto": True})
        if n >= 1:
            print(f"  Battery #{u['id']} is still packed after {n} unpack order(s) -> {value}"
                  + (f" | plugin state: {u['limberInfo']}" if u.get("limberInfo") else ""))
        if stats is not None:
            key = ("auto FORCED unpack of a battery that stayed packed" if value == "unpack_force"
                   else "auto unpack of packed batteries that were not marching")
            stats[key] = stats.get(key, 0) + 1
    return out
