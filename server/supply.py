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
    "need_infantry": 0.4,      # same for infantry, cavalry and skirmishers
    "critical": 0.2,           # under this, an empty unit out of contact walks back to the wagon
    "default_range": 120.0,    # area radius when the plugin does not report one
    "stand_share": 0.5,        # the wagon stops this share of its radius behind the unit
    "safe_distance": 450.0,    # a wagon never goes closer than this to a visible enemy
    "min_stock": 0.05,         # an empty wagon is not worth moving
    "auto_flags": True,        # switch on the artillery / infantry supply modes when units need them
    "path_clear": 450.0,       # the whole route of a wagon stays at least this far from any known enemy
    "max_trip": 1500.0,        # a wagon does not drive farther than this to reach a unit
    "memory_s": 900.0,         # enemies seen this recently (seconds of play) still count as known
    # 0.1.4 (battle of 2026-11-11: the wagons stayed 1,000 to 3,000 from the enemy and used 4 % of their stock,
    # 128 trips refused, the line ran down to 50 % ammunition). The wagon now follows the line and goes forward
    # when the line needs it:
    "park_distance": 750.0,    # a wagon waits this far from the nearest visible enemy, behind the line...
    "park_tolerance": 250.0,   # ...and is moved when it is farther than this from that spot
    "park_spacing": 140.0,     # (before 0.1.4 WIP9: wagons waited side by side this far apart; no longer used)
    "park_spread": 400.0,      # 0.1.4 WIP9: idle wagons wait at least this far apart, each behind its own part of the line
    "advance_units": 2,        # this many units of the line low on ammunition, close together, call a wagon forward
    "contact": 650.0,          # "of the line" = a visible enemy this close
    "advance_safe": 300.0,     # the forward spot stays this far from every visible enemy...
    "advance_screen": True,    # ...with a friendly brigade nearer the enemy than the wagon (against capture)
    "advance_path_clear": 250.0,  # the route of a forward or parking move only avoids the visible enemies this far
    "advance_max_trip": 2500.0,
    # 0.1.4 WIP4 (15:27 battle: 30 trips refused "too far / route unsafe", the dry brigades stayed where they were
    # and the three wagons ended at 91 to 95 % of their stock):
    "walk_back_clear": 350.0,  # a nearly empty unit walks to the wagon when no visible enemy is closer than this
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
    lines = [f"SUPPLY WAGONS (area radius {wagon_range(ws[0], cfg):.0f}; each feeds artillery and infantry unless noted):"]
    for w in ws:
        near = nearest(w, live)
        off = [k for k, f in (("artillery", "supplyArtillery"), ("infantry", "supplyInfantry")) if not w.get(f, True)]
        lines.append(f"- #{w['id']} at {round(w['x'], -1):.0f},{round(w['z'], -1):.0f} | stock {float(w['supplyStock']) * 100:.0f}%"
                     + (f" | NOT feeding {' and '.join(off)}" if off else "")
                     + (f" | nearest enemy {near[1]:.0f}" if near else ""))
    low = needy(mine, cfg)
    if low:
        lines.append("UNITS LOW ON AMMUNITION (worst first):")
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
            lines.append(f"- #{u['id']} {u['name']} ammo {float(u['ammo']) * 100:.0f}% | wagon #{w['id']} is {d:.0f} away"
                         + note)
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


def _screened(spot, enemy, mine, d):
    """True when a steady friendly brigade stands nearer `enemy` than the spot, within 500 of the spot."""
    return any(g["kind"] in ("Infantry", "Cavalry") and unit_status(g) == "" and g["morale"] >= 0.5
               and math.hypot(g["x"] - spot["x"], g["z"] - spot["z"]) <= 500.0
               and math.hypot(g["x"] - enemy["x"], g["z"] - enemy["z"]) < d
               for g in mine)


def _passable(terrain, x, z):
    if terrain is None:
        return x, z
    return terrain.nearest_passable(x, z)


def forward_orders(state, orders, cfg, terrain, pending_moves, ws, claimed, stats):
    """Several units of the line low on ammunition, close together: the nearest wagon drives up so that its area
    covers them, behind them, never closer than `advance_safe` to a visible enemy and only with a friendly
    brigade between it and that enemy."""
    mine, foes = split_units(state)
    visible = [e for e in foes if unit_status(e) not in DEAD_STATUSES]
    if not visible:
        return []
    line = [u for u in needy(mine, cfg) if (nearest(u, visible) or (None, 1e9))[1] <= float(cfg["contact"])]
    out, served = [], set()
    for worst in line:
        if worst["id"] in served:
            continue
        free = [w for w in ws if w["id"] not in claimed]
        if not free:
            break
        r = wagon_range(free[0], cfg)
        group = [u for u in line if u["id"] not in served and math.hypot(u["x"] - worst["x"], u["z"] - worst["z"]) <= 1.6 * r]
        if len(group) < int(cfg["advance_units"]):
            continue
        cx = sum(u["x"] for u in group) / len(group)
        cz = sum(u["z"] for u in group) / len(group)
        w = min(free, key=lambda x: math.hypot(x["x"] - cx, x["z"] - cz))
        r = wagon_range(w, cfg)
        e, _ = nearest({"x": cx, "z": cz}, visible)
        dx, dz = cx - e["x"], cz - e["z"]
        n = math.hypot(dx, dz) or 1.0
        x, z = cx + dx / n * r * float(cfg["stand_share"]), cz + dz / n * r * float(cfg["stand_share"])
        x, z = push_from_enemies(x, z, visible, float(cfg["advance_safe"]))
        spot = _passable(terrain, x, z)
        served.update(u["id"] for u in group)
        if spot is None:
            continue
        p = {"x": spot[0], "z": spot[1]}
        covered = sum(1 for u in group if math.hypot(u["x"] - p["x"], u["z"] - p["z"]) <= r * 0.9)
        ne, nd = nearest(p, visible)
        bump = (lambda k: stats.__setitem__(k, stats.get(k, 0) + 1)) if stats is not None else (lambda k: None)
        if (covered < int(cfg["advance_units"]) or (cfg["advance_screen"] and not _screened(p, ne, mine, nd))
                or route_threat(w, p, visible, float(cfg["advance_path_clear"]))
                or math.hypot(p["x"] - w["x"], p["z"] - w["z"]) > float(cfg["advance_max_trip"])):
            bump("supply wagon not sent forward (no screened spot covering the units, or route under fire)")
            continue
        claimed.add(w["id"])
        if math.hypot(w["x"] - p["x"], w["z"] - p["z"]) <= 100.0:
            continue                                   # already there
        old = (pending_moves or {}).get(w["id"])
        if old and math.hypot(old[0] - p["x"], old[1] - p["z"]) < 120.0:
            continue
        out.append({"cmd": "move", "id": w["id"], "x": round(p["x"], 1), "z": round(p["z"], 1), "auto": True})
        bump("supply wagons sent forward to the line (several units low on ammunition)")
    return out


def park_spots(line, visible, n, cfg):
    """Parking spots for `n` idle wagons: one behind each part of the line, never side by side.

    0.1.4 WIP9: the wagons used to wait side by side (park_spacing apart) behind the centre of the line; on
    2026-11-12 14:48 one Northern push took them all at once. The line is cut into `n` parts along its front and
    each wagon waits behind its own part, at park_distance from the enemy nearest that part, at least
    park_spread from the other wagons."""
    cx = sum(u["x"] for u in line) / len(line)
    cz = sum(u["z"] for u in line) / len(line)
    e, _ = nearest({"x": cx, "z": cz}, visible)
    dx, dz = cx - e["x"], cz - e["z"]
    d = math.hypot(dx, dz) or 1.0
    ux, uz = dx / d, dz / d                     # away from the enemy
    px, pz = -uz, ux                            # along the front
    park, spread = float(cfg["park_distance"]), float(cfg.get("park_spread", 400.0))
    ordered = sorted(line, key=lambda u: (u["x"] - cx) * px + (u["z"] - cz) * pz)
    spots = []
    for k in range(n):
        part = ordered[k * len(ordered) // n:(k + 1) * len(ordered) // n] or ordered
        ax = sum(u["x"] for u in part) / len(part)
        az = sum(u["z"] for u in part) / len(part)
        ek, _ = nearest({"x": ax, "z": az}, visible)
        bx, bz = ax - ek["x"], az - ek["z"]
        b = math.hypot(bx, bz) or 1.0
        x, z = ek["x"] + bx / b * park, ek["z"] + bz / b * park
        for _ in range(6):                      # keep away from the spots already taken
            close = [q for q in spots if math.hypot(q[0] - x, q[1] - z) < spread]
            if not close:
                break
            q = close[0]
            side = 1.0 if (x - q[0]) * px + (z - q[1]) * pz >= 0 else -1.0
            x, z = x + px * side * spread * 0.6, z + pz * side * spread * 0.6
        spots.append(push_from_enemies(x, z, visible, 0.9 * park))
    return spots


def park_orders(state, cfg, terrain, pending_moves, ws, claimed, stats):
    """Wagons with nothing to do wait behind the line, `park_distance` from the nearest visible enemy, each behind
    its own part of the line (see park_spots)."""
    mine, foes = split_units(state)
    visible = [e for e in foes if unit_status(e) not in DEAD_STATUSES]
    if not visible:
        return []
    fighters = [u for u in mine if u["kind"] in ("Infantry", "Cavalry", "Artillery", "Skirmish")
                and unit_status(u) not in DEAD_STATUSES and not u.get("offmap")]
    line = [u for u in fighters if (nearest(u, visible) or (None, 1e9))[1] <= float(cfg["contact"])] or fighters
    if not line:
        return []
    free = [w for w in ws if w["id"] not in claimed and not w.get("offmap")]
    if not free:
        return []
    spots = park_spots(line, visible, len(free), cfg)
    # each wagon takes the nearest spot still free (the wagons do not cross each other's path)
    pairs, left = [], list(range(len(spots)))
    for w in sorted(free, key=lambda w: min(math.hypot(w["x"] - s[0], w["z"] - s[1]) for s in spots)):
        k = min(left, key=lambda i: math.hypot(w["x"] - spots[i][0], w["z"] - spots[i][1]))
        left.remove(k)
        pairs.append((w, spots[k]))
    out = []
    for w, (x, z) in pairs:
        spot = _passable(terrain, x, z)
        if spot is None:
            continue
        p = {"x": spot[0], "z": spot[1]}
        if math.hypot(w["x"] - p["x"], w["z"] - p["z"]) <= float(cfg["park_tolerance"]):
            continue
        old = (pending_moves or {}).get(w["id"])
        if old and math.hypot(old[0] - p["x"], old[1] - p["z"]) <= float(cfg["park_tolerance"]):
            continue
        if route_threat(w, p, visible, float(cfg["advance_path_clear"])):
            continue
        out.append({"cmd": "move", "id": w["id"], "x": round(p["x"], 1), "z": round(p["z"], 1), "auto": True})
        if stats is not None:
            key = "supply wagons kept behind the line, each behind its own part of it"
            stats[key] = stats.get(key, 0) + 1
    return out


def supply_orders(state, orders, cfg, terrain=None, pending_moves=None, stats=None):
    """Server-side help: switch the wagon on for the kinds that need it, drive a wagon up to the line when several
    of its units run low, bring it to a unit out of the line, walk an empty unit back to it, and keep idle wagons
    waiting behind the line."""
    cfg = {**DEFAULT_SUPPLY, **(cfg or {})}
    if not cfg["enabled"]:
        return []
    bump = (lambda k: stats.__setitem__(k, stats.get(k, 0) + 1)) if stats is not None else (lambda k: None)
    mine, foes = split_units(state)
    ws = [w for w in wagons(mine) if float(w["supplyStock"]) >= cfg["min_stock"]]
    if not ws:
        return []
    ordered = {o["id"] for o in orders if o["cmd"] != "ammo"}
    wagon_cmds = {(o["id"], o["cmd"]) for o in orders if o["id"] in {w["id"] for w in ws}}
    claimed = {w["id"] for w in ws if w["id"] in ordered}       # the model moved it this turn
    out = []
    low = needy(mine, cfg)
    for u in low:                                  # the wagon must feed the kind first
        w = min(ws, key=lambda x: math.hypot(x["x"] - u["x"], x["z"] - u["z"]))
        if cfg["auto_flags"] and not feeds(w, u) and (w["id"], "supply") not in wagon_cmds:
            key = "artillery" if u["kind"] == "Artillery" else "infantry"
            if not any(o["id"] == w["id"] and o["cmd"] == "supply" and key in o for o in out):
                out.append({"cmd": "supply", "id": w["id"], key: True, "auto": True})
                bump("supply modes switched on")
    out += forward_orders(state, orders, cfg, terrain, pending_moves, ws, claimed, stats)
    out += _single_orders(state, orders, cfg, terrain, pending_moves, ws, claimed, ordered, stats)
    out += park_orders(state, cfg, terrain, pending_moves, ws, claimed, stats)
    return out


def _single_orders(state, orders, cfg, terrain, pending_moves, ws, claimed, ordered, stats):
    """One unit out of the line low on ammunition: the wagon goes to it (strict route rules), or the unit walks
    back to the wagon when it is nearly empty."""
    bump = (lambda k: stats.__setitem__(k, stats.get(k, 0) + 1)) if stats is not None else (lambda k: None)
    mine, foes = split_units(state)
    low = needy(mine, cfg)
    if not low:
        return []
    live = known_enemies(foes)
    visible = [e for e in foes if unit_status(e) not in DEAD_STATUSES]
    out = []
    safe = float(cfg["safe_distance"])

    def walk_back(u, w):
        """The wagon cannot come: the unit goes to it and stops inside its area, on its own side of the wagon."""
        near = nearest(u, visible)
        if (u["id"] in ordered or u["kind"] == "Artillery" or float(u["ammo"]) >= cfg["critical"]
                or unit_status(u) != "" or (near and near[1] <= float(cfg["walk_back_clear"]))):
            return
        d = math.hypot(w["x"] - u["x"], w["z"] - u["z"])
        k = max(0.0, (d - 0.6 * wagon_range(w, cfg)) / d) if d > 1.0 else 0.0
        out.append({"cmd": "move", "id": u["id"], "x": round(u["x"] + (w["x"] - u["x"]) * k, 1),
                    "z": round(u["z"] + (w["z"] - u["z"]) * k, 1), "auto": True})
        ordered.add(u["id"])
        bump("empty units sent to a supply wagon")

    for u in low:
        if (nearest(u, visible) or (None, 1e9))[1] <= float(cfg["contact"]):
            continue                                   # a unit of the line: forward_orders
        w = min(ws, key=lambda x: math.hypot(x["x"] - u["x"], x["z"] - u["z"]))
        r = wagon_range(w, cfg)
        d = math.hypot(w["x"] - u["x"], w["z"] - u["z"])
        if not feeds(w, u):
            continue                                   # switched on by supply_orders first
        if d <= r * 0.9:
            claimed.add(w["id"])                       # it refills by itself: the wagon stays there
            continue
        if w["id"] in claimed or w["id"] in ordered:
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
            walk_back(u, w)
            continue
        if math.hypot(spot[0] - u["x"], spot[1] - u["z"]) > r * 0.9:
            # The safe spot is too far from the unit: the unit must walk to the wagon instead.
            walk_back(u, w)
            continue
        if old and (math.hypot(old[0] - spot[0], old[1] - spot[1]) < 150
                    or math.hypot(old[0] - u["x"], old[1] - u["z"]) <= r * 0.9):
            claimed.add(w["id"])
            continue                                   # already on its way (to a spot that still covers the unit)
        out.append({"cmd": "move", "id": w["id"], "x": round(spot[0], 1), "z": round(spot[1], 1), "auto": True})
        claimed.add(w["id"])
        bump("supply wagons moved to a unit low on ammunition")
    return out
