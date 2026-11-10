"""Supply wagons: rearm artillery and infantry that run low on ammunition.

In the game a supply wagon (kind "Supply") refills, by itself, every friendly unit of an enabled kind
that stands inside its area, taking the ammunition from its own stock (faster when the unit is out of
combat). Two switches on the wagon say which kinds it feeds: artillery, infantry. So the job of the
commander is only to bring wagon and unit together, out of enemy reach:
  * move the wagon next to the units that need ammunition, behind them;
  * or pull a battery that is empty (and not in contact) back to the wagon.
The plugin reports for each wagon: supplyStock (0..1), supplyArtillery, supplyInfantry, supplyRange.
"""
import math

DEAD_STATUSES = ("routing", "shattered", "captured")


def unit_status(u):
    return str(u.get("status") or "")


def split_units(state):
    player = state["playerSide"]
    return ([u for u in state["units"] if u["side"] != player], [u for u in state["units"] if u["side"] == player])


def nearest(unit, others):
    best = None
    for o in others:
        d = math.hypot(o["x"] - unit["x"], o["z"] - unit["z"])
        if best is None or d < best[1]:
            best = (o, d)
    return best

DEFAULT_SUPPLY = {
    "enabled": True,
    "need_artillery": 0.5,     # a battery under this share of ammunition needs the wagon
    "need_infantry": 0.35,     # same for infantry, cavalry and skirmishers
    "critical": 0.2,           # under this, an empty unit out of contact walks back to the wagon
    "default_range": 120.0,    # area radius when the plugin does not report one
    "stand_share": 0.5,        # the wagon stops this share of its radius behind the unit
    "safe_distance": 450.0,    # a wagon never goes closer than this to a visible enemy
    "min_stock": 0.05,         # an empty wagon is not worth moving
    "auto_flags": True,        # switch on the artillery / infantry supply modes when units need them
    "path_clear": 450.0,       # the whole route of a wagon stays at least this far from any known enemy
    "max_trip": 1500.0,        # a wagon does not drive farther than this to reach a unit
    "memory_s": 900.0,         # enemies seen this recently (seconds of play) still count as known
}

# Enemy units seen earlier and not visible now, set by the planner at every turn: a wagon must also
# stay away from where the enemy was last seen, not only from what is in sight right now.
KNOWN_FOES = []


def set_known_foes(units):
    KNOWN_FOES[:] = list(units or [])


def known_enemies(foes):
    """Visible live enemies plus the last known position of those out of sight."""
    seen = {e["id"] for e in foes}
    return [e for e in foes if unit_status(e) not in DEAD_STATUSES] + [g for g in KNOWN_FOES if g["id"] not in seen]


def _seg_dist(p, a, b):
    dx, dz = b["x"] - a["x"], b["z"] - a["z"]
    n = dx * dx + dz * dz
    t = 0.0 if n == 0 else max(0.0, min(1.0, ((p["x"] - a["x"]) * dx + (p["z"] - a["z"]) * dz) / n))
    return math.hypot(p["x"] - (a["x"] + t * dx), p["z"] - (a["z"] + t * dz))


def route_threat(a, b, enemies, clear):
    """The known enemy that comes closest to the route a-b when it is nearer than `clear`, else None."""
    worst = None
    for e in enemies:
        d = _seg_dist(e, a, b)
        if d < clear and (worst is None or d < worst[1]):
            worst = (e, d)
    return worst


def wagons(mine):
    return [u for u in mine if u.get("kind") == "Supply" and unit_status(u) not in DEAD_STATUSES
            and u.get("supplyStock") is not None]


def wagon_range(w, cfg):
    try:
        r = float(w.get("supplyRange"))
        return r if 20.0 <= r <= 2000.0 else float(cfg["default_range"])
    except (TypeError, ValueError):
        return float(cfg["default_range"])


def feeds(w, u):
    """True when this wagon is switched on for the kind of the unit."""
    if u["kind"] == "Artillery":
        return bool(w.get("supplyArtillery", True))
    return bool(w.get("supplyInfantry", True))


def needy(mine, cfg):
    """Own units low on ammunition (worst first)."""
    out = []
    for u in mine:
        if u["kind"] not in ("Infantry", "Cavalry", "Artillery", "Skirmish") or unit_status(u) in DEAD_STATUSES:
            continue
        a = u.get("ammo")
        if a is None:
            continue
        limit = cfg["need_artillery"] if u["kind"] == "Artillery" else cfg["need_infantry"]
        if float(a) < limit:
            out.append(u)
    return sorted(out, key=lambda u: float(u["ammo"]) * (0.5 if u["kind"] == "Artillery" else 1.0))


def supply_lines(state, cfg=None):
    cfg = {**DEFAULT_SUPPLY, **(cfg or {})}
    if not cfg["enabled"]:
        return []
    mine, foes = split_units(state)
    ws = wagons(mine)
    if not ws:
        return []
    live = known_enemies(foes)
    lines = ["SUPPLY WAGONS (see READING THE STATE):"]
    for w in ws:
        r = wagon_range(w, cfg)
        near = nearest(w, live)
        lines.append(f"- {w['name']} (#{w['id']}) at {w['x']:.0f},{w['z']:.0f} | stock {float(w['supplyStock']) * 100:.0f}% | "
                     f"feeds artillery: {'yes' if w.get('supplyArtillery', True) else 'NO'}, infantry: "
                     f"{'yes' if w.get('supplyInfantry', True) else 'NO'} | area radius {r:.0f}"
                     + (f" | nearest enemy {near[1]:.0f} away" if near else ""))
    low = needy(mine, cfg)
    if low:
        lines.append("UNITS LOW ON AMMUNITION (worst first; how to rearm: see READING THE STATE):")
        for u in low[:8]:
            w = min(ws, key=lambda x: math.hypot(x["x"] - u["x"], x["z"] - u["z"]))
            d = math.hypot(w["x"] - u["x"], w["z"] - u["z"])
            note = ""
            if d <= wagon_range(w, cfg) and feeds(w, u):
                note = " (inside its area: refilling)"
            else:
                threat = route_threat(w, u, live, float(cfg["path_clear"]))
                if threat:
                    e, dd = threat
                    note = (f" ROUTE UNSAFE: {e['name']} ({e['kind']}, "
                            + ("last seen" if e in KNOWN_FOES else "visible")
                            + f") is {dd:.0f} from the straight route; do NOT drive the wagon there")
                elif d > float(cfg["max_trip"]):
                    note = f" (too far for the wagon: more than {float(cfg['max_trip']):.0f})"
            lines.append(f"- {u['name']} (#{u['id']}) {u['kind']} ammo {float(u['ammo']) * 100:.0f}% at "
                         f"{u['x']:.0f},{u['z']:.0f} | wagon #{w['id']} is {d:.0f} away" + note)
    return lines


def _away_spot(w, target, foes, cfg):
    """Spot near `target`, on the side away from the nearest enemy, at stand_share of the wagon radius."""
    r = wagon_range(w, cfg)
    near = nearest(target, foes)
    if near:
        dx, dz = target["x"] - near[0]["x"], target["z"] - near[0]["z"]
    else:
        dx, dz = target["x"] - w["x"], target["z"] - w["z"]
        dx, dz = -dx, -dz
    n = math.hypot(dx, dz) or 1.0
    d = r * float(cfg["stand_share"])
    return target["x"] + dx / n * d, target["z"] + dz / n * d


def push_from_enemies(x, z, foes, safe):
    """Move (x, z) away from visible enemies until it is `safe` from all of them (a few passes)."""
    for _ in range(4):
        near = nearest({"x": x, "z": z}, foes)
        if not near or near[1] >= safe:
            return x, z
        e = near[0]
        dx, dz = x - e["x"], z - e["z"]
        n = math.hypot(dx, dz) or 1.0
        x, z = e["x"] + dx / n * safe, e["z"] + dz / n * safe
    return x, z


def sanitize_supply(raw_orders, state, terrain, cfg=None, stats=None):
    """Split the model's orders: return (orders without wagon ids, clean wagon orders).
    A wagon can only be moved or switched; its moves never end near the enemy."""
    cfg = {**DEFAULT_SUPPLY, **(cfg or {})}
    mine, foes = split_units(state)
    ids = {w["id"] for w in mine if w.get("kind") == "Supply"}
    live = known_enemies(foes)
    by_id = {u["id"]: u for u in mine}
    rest, clean, seen = [], [], set()
    for o in raw_orders:
        uid = None
        if isinstance(o, dict):
            try:
                uid = int(o.get("id"))
            except (TypeError, ValueError):
                uid = None
        if uid not in ids:
            rest.append(o)
            continue
        cmd = o.get("cmd")
        if cmd == "move" and (uid, "move") not in seen:
            try:
                x, z = float(o["x"]), float(o["z"])
            except (KeyError, TypeError, ValueError):
                continue
            x, z = push_from_enemies(x, z, live, float(cfg["safe_distance"]))
            if terrain is not None:
                spot = terrain.nearest_passable(x, z)
                if spot is None:
                    continue
                x, z = spot
            if route_threat(by_id[uid], {"x": x, "z": z}, live, float(cfg["path_clear"])):
                if stats is not None:
                    key = "supply wagon moves dropped (route passes near a known enemy)"
                    stats[key] = stats.get(key, 0) + 1
                continue
            clean.append({"cmd": "move", "id": uid, "x": round(x, 1), "z": round(z, 1)})
            seen.add((uid, "move"))
        elif cmd == "supply" and (uid, "supply") not in seen:
            order = {"cmd": "supply", "id": uid}
            for key in ("artillery", "infantry"):
                if key in o:
                    order[key] = bool(o[key])
            if len(order) > 2:
                clean.append(order)
                seen.add((uid, "supply"))
    return rest, clean


def supply_orders(state, orders, cfg, terrain=None, pending_moves=None, stats=None):
    """Server-side help: switch the wagon on for the kinds that need it, bring the wagon to the worst
    unit, and walk an empty unit that is out of contact back to the wagon."""
    cfg = {**DEFAULT_SUPPLY, **(cfg or {})}
    if not cfg["enabled"]:
        return []
    bump = (lambda k: stats.__setitem__(k, stats.get(k, 0) + 1)) if stats is not None else (lambda k: None)
    mine, foes = split_units(state)
    ws = [w for w in wagons(mine) if float(w["supplyStock"]) >= cfg["min_stock"]]
    low = needy(mine, cfg)
    if not ws or not low:
        return []
    live = known_enemies(foes)
    ordered = {o["id"] for o in orders if o["cmd"] != "ammo"}
    wagon_cmds = {(o["id"], o["cmd"]) for o in orders if o["id"] in {w["id"] for w in ws}}
    out, claimed = [], set()
    safe = float(cfg["safe_distance"])
    for u in low:
        w = min((x for x in ws), key=lambda x: math.hypot(x["x"] - u["x"], x["z"] - u["z"]))
        r = wagon_range(w, cfg)
        d = math.hypot(w["x"] - u["x"], w["z"] - u["z"])
        if cfg["auto_flags"] and not feeds(w, u) and (w["id"], "supply") not in wagon_cmds:
            key = "artillery" if u["kind"] == "Artillery" else "infantry"
            if not any(o["id"] == w["id"] and o["cmd"] == "supply" and key in o for o in out):
                out.append({"cmd": "supply", "id": w["id"], key: True, "auto": True})
                bump("supply modes switched on")
            continue
        if d <= r * 0.9:
            continue                                   # already inside the area: it refills by itself
        if w["id"] in claimed or (w["id"], "move") in wagon_cmds or w["id"] in ordered:
            continue
        old = (pending_moves or {}).get(w["id"])
        spot = _away_spot(w, u, live, cfg)
        spot = push_from_enemies(spot[0], spot[1], live, safe)
        if terrain is not None:
            ok = terrain.nearest_passable(*spot)
            if ok is None:
                continue
            spot = ok
        trip = math.hypot(spot[0] - w["x"], spot[1] - w["z"])
        if route_threat(w, {"x": spot[0], "z": spot[1]}, live, float(cfg["path_clear"])) or trip > float(cfg["max_trip"]):
            bump("supply trips refused (route near a known enemy, or too far)")
            continue
        if math.hypot(spot[0] - u["x"], spot[1] - u["z"]) > r * 0.9:
            # The safe spot is too far from the unit: the unit must walk to the wagon instead (below).
            near = nearest(u, live)
            if (u["id"] not in ordered and float(u["ammo"]) < cfg["critical"]
                    and (not near or near[1] > 1.5 * 400.0)):
                out.append({"cmd": "move", "id": u["id"], "x": round(w["x"] + 15.0, 1), "z": round(w["z"] + 15.0, 1),
                            "auto": True})
                ordered.add(u["id"])
                bump("empty units sent to a supply wagon")
            continue
        if old and math.hypot(old[0] - spot[0], old[1] - spot[1]) < 150:
            continue                                   # the wagon is already on its way
        out.append({"cmd": "move", "id": w["id"], "x": round(spot[0], 1), "z": round(spot[1], 1), "auto": True})
        claimed.add(w["id"])
        bump("supply wagons moved to a unit low on ammunition")
    return out
