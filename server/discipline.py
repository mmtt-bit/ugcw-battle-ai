"""Last-word rules on the orders of a turn (0.1.4 WIP4, from the battle of 2026-11-11 15:27).

They run after every other server module, on the final list of orders:

1. CAPTURE. An objective changes hands only while a unit stands inside its capture range, and it takes minutes.
   In that battle Forrest's cavalry was sent "to Spain Field" three times: it stopped 217 from the point (capture
   range 200) for four minutes, then stood on the point for three minutes and was sent away before the flag
   changed. Nobody defended it. So: a move that ends near an undefended objective that is not ours is put ONTO
   the point; a unit standing inside the capture range is kept there until the owner changes; an idle unit just
   outside the range steps in.
2. STEADY MOVES. A unit whose march is still running does not get a new move to (almost) the same place: every
   new move makes it stop, turn and start again (279 moves were stopped before arrival in that battle).
3. BATTERY MARCHES. In that battle not one of 237 move orders to a battery was carried out (the plugin's move call
   is cancelled at once for artillery; the batteries only moved under the game's own AI, or by hand on a fallback).
   Until the plugin is fixed the server notices it (two marches without a step) and stops sending marches to that
   battery for a while, instead of an order every four minutes for the whole battle.
4. WAGONS. Supply wagons do not tire: their long trips are made at the run.

Every order added here carries "auto": true. Switch the rules off in config.json ("discipline").
"""
import math

from supply import DEAD_STATUSES, split_units, unit_status

DEFAULT_DISCIPLINE = {
    "enabled": True,
    # units off the field (0.1.4 WIP7)
    "offmap": True,
    # capture
    "capture": True,
    "capture_inner_share": 0.4,    # a capturing unit is sent this share of the capture range from the point
    "capture_snap_share": 2.0,     # a move ending within this many capture ranges of the point is put onto it
    "capture_clear": 250.0,        # "undefended" = no visible enemy within capture range + this
    "capture_threat": 400.0,       # a capturing unit with an enemy this close is free to leave
    "capture_keepers": 2,          # at most this many units are held on one point
    # steady moves
    "steady_moves": True,
    "reissue_min_shift": 200.0,    # a running march is not replaced by a move ending closer than this to its end
    # battery marches
    "battery_watch": True,
    "battery_min_trip": 250.0,     # a "march" is a move at least this long (shorter steps are made by hand)
    "battery_check_s": 50.0,       # seconds after the order before the battery must have moved...
    "battery_min_step": 20.0,      # ...by at least this much
    "battery_fails": 2,            # marches without a step before the server stops sending them
    "battery_block_s": 900.0,      # ...for this long
    # wagons
    "wagon_run": True,
    "wagon_run_trip": 300.0,       # trips longer than this are made at the run
    "wagon_run_repeat_s": 300.0,   # the gait order is sent again after this long (a new move may reset it)
}

CAPTURERS = ("Infantry", "Cavalry", "Skirmish")


def _d(ax, az, bx, bz):
    return math.hypot(ax - bx, az - bz)


def _bump(stats, key, n=1):
    if stats is not None:
        stats[key] = stats.get(key, 0) + n


def _cap(o):
    return float(o.get("captureRange") or o.get("radius") or 150.0)


def open_objectives(state, cfg=None):
    """Objectives that are not ours and that no visible enemy defends: [(objective, capture range)]."""
    cfg = {**DEFAULT_DISCIPLINE, **(cfg or {})}
    mine, foes = split_units(state)
    if not mine:
        return []
    side = mine[0]["side"]
    live = [e for e in foes if unit_status(e) not in DEAD_STATUSES]
    out = []
    for o in state.get("objectives") or []:
        if o.get("side") == side:
            continue
        cap = _cap(o)
        if any(_d(e["x"], e["z"], o["x"], o["z"]) <= cap + float(cfg["capture_clear"]) for e in live):
            continue
        out.append((o, cap))
    return out


def capture_status(state, cfg=None):
    """For the prompt: objective name -> ("in", unit, distance) when a unit of ours stands inside the capture
    range of an undefended objective, ("out", unit, distance) for the nearest one just outside it."""
    cfg = {**DEFAULT_DISCIPLINE, **(cfg or {})}
    if not cfg["enabled"] or not cfg["capture"]:
        return {}
    mine, _ = split_units(state)
    takers = [u for u in mine if u["kind"] in CAPTURERS and unit_status(u) == ""]
    out = {}
    for o, cap in open_objectives(state, cfg):
        near = sorted(((_d(u["x"], u["z"], o["x"], o["z"]), u) for u in takers), key=lambda t: t[0])
        if not near:
            continue
        d, u = near[0]
        if d <= cap:
            out[str(o.get("name"))] = ("in", u, d, cap)
        elif d <= cap * float(cfg["capture_snap_share"]) + 200.0:
            out[str(o.get("name"))] = ("out", u, d, cap)
    return out


def capture_orders(state, orders, cfg, pending_moves, stats=None):
    """Rule 1. Returns the new list of orders."""
    mine, foes = split_units(state)
    live = [e for e in foes if unit_status(e) not in DEAD_STATUSES]
    by_id = {u["id"]: u for u in mine}
    targets = open_objectives(state, cfg)
    if not targets:
        return orders
    inner = float(cfg["capture_inner_share"])
    snap = float(cfg["capture_snap_share"])
    threat = float(cfg["capture_threat"])

    def threatened(u):
        return any(_d(e["x"], e["z"], u["x"], u["z"]) <= threat for e in live)

    def spot(o, cap, fx, fz):
        """A point inside the capture range, on the side the unit comes from."""
        d = _d(fx, fz, o["x"], o["z"])
        if d < 1.0:
            return float(o["x"]), float(o["z"])
        k = min(d, inner * cap) / d
        return o["x"] + (fx - o["x"]) * k, o["z"] + (fz - o["z"]) * k

    # units already inside a capture range: the nearest ones are the keepers
    keepers = {}
    for o, cap in targets:
        inside = sorted((u for u in mine if u["kind"] in CAPTURERS and unit_status(u) == ""
                         and _d(u["x"], u["z"], o["x"], o["z"]) <= cap),
                        key=lambda u: _d(u["x"], u["z"], o["x"], o["z"]))
        for u in inside[:int(cfg["capture_keepers"])]:
            keepers[u["id"]] = (o, cap)
    out, ordered = [], set()
    for od in orders:
        u = by_id.get(od.get("id"))
        if u is None or od.get("cmd") != "move":
            out.append(od)
            if od.get("cmd") not in ("ammo", "supply", "limber", "mount", "formation", "gait", "detach", "recall"):
                ordered.add(od.get("id"))
            continue
        ordered.add(u["id"])
        if u["id"] in keepers and not threatened(u):
            o, cap = keepers[u["id"]]
            if _d(od["x"], od["z"], o["x"], o["z"]) > cap:
                _bump(stats, "moves dropped: the unit is capturing an undefended objective (stays until it changes hands)")
                continue
        if u["kind"] in CAPTURERS:
            for o, cap in targets:
                d = _d(od["x"], od["z"], o["x"], o["z"])
                if inner * cap < d <= snap * cap:
                    x, z = spot(o, cap, od["x"], od["z"])
                    od = dict(od, x=round(x, 1), z=round(z, 1), _capture=True)
                    od.pop("fx", None)
                    od.pop("fz", None)
                    _bump(stats, "moves ending near an undefended objective put ONTO the point (inside its capture range)")
                    break
        out.append(od)
    # an idle unit just outside the capture range of a point nobody of ours is on: it steps in
    for o, cap in targets:
        if any(k[0] is o for k in keepers.values()):
            continue
        if any(od.get("cmd") == "move" and _d(od["x"], od["z"], o["x"], o["z"]) <= cap for od in out):
            continue
        if any(_d(p[0], p[1], o["x"], o["z"]) <= cap for p in (pending_moves or {}).values()):
            continue
        near = sorted((u for u in mine if u["kind"] in CAPTURERS and unit_status(u) == "" and u["id"] not in ordered
                       and u["id"] not in (pending_moves or {}) and not threatened(u)
                       and cap < _d(u["x"], u["z"], o["x"], o["z"]) <= snap * cap),
                      key=lambda u: _d(u["x"], u["z"], o["x"], o["z"]))
        if near:
            u = near[0]
            x, z = spot(o, cap, u["x"], u["z"])
            out.append({"cmd": "move", "id": u["id"], "x": round(x, 1), "z": round(z, 1), "auto": True,
                        "_capture": True})
            ordered.add(u["id"])
            _bump(stats, "idle units just outside the capture range of an undefended objective stepped onto it")
    return out


def steady_orders(state, orders, cfg, pending_moves, stats=None):
    """Rule 2. A move for a unit whose march still runs, ending within `reissue_min_shift` of that march's end,
    is not sent: the march goes on."""
    if not pending_moves:
        return orders
    limit = float(cfg["reissue_min_shift"])
    out = []
    for od in orders:
        old = pending_moves.get(od.get("id")) if od.get("cmd") == "move" else None
        if old and not od.get("_capture") and _d(od["x"], od["z"], old[0], old[1]) < limit:
            _bump(stats, f"moves not reissued (march still running, new destination within {limit:.0f} of it)")
            continue
        out.append(od)
    return out


def battery_orders_watch(state, orders, cfg, mem, stats=None):
    """Rule 3. `mem` is kept between turns: battery id -> {"t", "pos", "fails", "until"}."""
    mine, _ = split_units(state)
    now = float(state.get("time", 0.0))
    guns = {u["id"]: u for u in mine if u["kind"] == "Artillery" and unit_status(u) not in DEAD_STATUSES}
    blocked = set()
    for uid, rec in list(mem.items()):
        u = guns.get(uid)
        if u is None:
            del mem[uid]
            continue
        if rec.get("t") is not None and now - rec["t"] >= float(cfg["battery_check_s"]):
            moved = _d(u["x"], u["z"], rec["pos"][0], rec["pos"][1]) >= float(cfg["battery_min_step"])
            packing = str(u.get("limber") or "") == "packing" or "inMove=True" in str(u.get("limberInfo") or "")
            if moved or packing:
                rec["fails"] = 0
            else:
                rec["fails"] = rec.get("fails", 0) + 1
                if rec["fails"] >= int(cfg["battery_fails"]):
                    rec["until"] = now + float(cfg["battery_block_s"])
                    rec["fails"] = 0
                    print(f"  Battery #{uid} {u.get('name', '')} did not move on {cfg['battery_fails']} march orders: "
                          f"no march for {float(cfg['battery_block_s']) / 60:.0f} min (plugin: artillery move call)")
            rec["t"] = None
        if now < float(rec.get("until", 0.0)):
            blocked.add(uid)
    out = []
    for od in orders:
        u = guns.get(od.get("id"))
        if u is None or od.get("cmd") != "move":
            out.append(od)
            continue
        trip = _d(od["x"], od["z"], u["x"], u["z"])
        if trip < float(cfg["battery_min_trip"]):
            out.append(od)
            continue
        if u["id"] in blocked:
            _bump(stats, "battery marches not sent (the battery does not move on move orders: plugin)")
            continue
        rec = mem.setdefault(u["id"], {})
        if rec.get("t") is None:
            rec["t"], rec["pos"] = now, (u["x"], u["z"])
        out.append(od)
    return out, blocked


def wagon_run_orders(state, orders, cfg, mem, stats=None):
    """Rule 4. `mem`: wagon id -> time of the last gait order."""
    mine, _ = split_units(state)
    now = float(state.get("time", 0.0))
    wagons = {u["id"]: u for u in mine if u["kind"] == "Supply"}
    extra = []
    for od in orders:
        w = wagons.get(od.get("id"))
        if w is None or od.get("cmd") != "move":
            continue
        pts = [(w["x"], w["z"])] + [tuple(p) for p in od.get("path") or []] + [(od["x"], od["z"])]
        trip = sum(_d(a[0], a[1], b[0], b[1]) for a, b in zip(pts, pts[1:]))
        if trip < float(cfg["wagon_run_trip"]) or now - mem.get(w["id"], -1e9) < float(cfg["wagon_run_repeat_s"]):
            continue
        mem[w["id"]] = now
        extra.append({"cmd": "gait", "id": w["id"], "value": "Run", "auto": True})
        _bump(stats, "supply wagons put at the run for a long trip (wagons do not tire)")
    return orders + extra


def mark_offmap(state, terrain, margin=25.0):
    """Sets u["offmap"] on our units that stand outside the playing field (or within `margin` of its edge):
    reinforcements entering at the map edge. Returns their ids.

    0.1.4 WIP9: the plugin's own flag "offField" (the game's TerrainController.InWorldBounds) and the field of the
    current stage (state["field"], which grows when a stage opens a new part of the map) come first. On 2026-11-12
    14:48 the field grew east to x = 3,900 while the terrain scan stopped at x = 1,610: the eastern brigades
    were taken for units off the field and got no orders until they had crossed x = 1,610."""
    field = state.get("field")
    if isinstance(field, (list, tuple)) and len(field) == 4:
        x0, z0, x1, z1 = (float(v) for v in field)
        if x1 <= x0 or z1 <= z0:
            field = None
    else:
        field = None
    if field is None and (terrain is None or not hasattr(terrain, "inside")):
        return set()
    mine, _ = split_units(state)
    out = set()
    for u in mine:
        if unit_status(u) in DEAD_STATUSES:
            # 0.1.4 WIP8: shattered and routing units walk off the map by themselves (the game's rout); they are not
            # reinforcements to give back (81 useless "release" orders in the battle of 2026-11-12 13:24)
            u["offmap"] = False
            continue
        x, z = float(u["x"]), float(u["z"])
        if u.get("offField"):
            off = True
        elif field is not None:
            off = min(x - x0, x1 - x, z - z0, z1 - z) < margin
        else:
            off = (not terrain.inside(x, z) or min(x - terrain.min_x, terrain.max_x - x,
                                                   z - terrain.min_z, terrain.max_z - z) < margin)
        u["offmap"] = off
        if off:
            out.add(u["id"])
    return out


def offmap_orders(state, orders, cfg, mem, stats=None):
    """Rule 0 (0.1.4 WIP7, changed in WIP9). A unit off the field cannot be moved by the planner (its move ends at
    once and it slides along the world bound). Its orders are not sent: the game walks it in by itself, and the
    server orders it once it is on the field.

    WIP9: no "release" any more. Giving the unit back to the game's AI cancelled its entry march (CancelActions)
    and the game refused to take it out of bounds: on 2026-11-12 14:48 eight brigades and batteries stayed at the
    map edge for the whole battle."""
    off = {u["id"] for u in split_units(state)[0] if u.get("offmap")}
    if not off:
        return orders
    out = []
    for od in orders:
        if od.get("id") in off:
            if od.get("cmd") != "release":
                _bump(stats, "orders to units still off the field not sent (the game walks them in)")
            continue
        out.append(od)
    return out


def discipline_orders(state, orders, cfg, pending_moves, mem, stats=None):
    """All the rules, in order. `mem` is a dict kept between turns. Returns (orders, blocked battery ids)."""
    cfg = {**DEFAULT_DISCIPLINE, **(cfg or {})}
    if not cfg["enabled"]:
        return orders, set()
    blocked = set()
    if cfg["offmap"]:
        orders = offmap_orders(state, orders, cfg, mem.setdefault("offmap", {}), stats)
    if cfg["capture"]:
        orders = capture_orders(state, orders, cfg, pending_moves, stats)
    if cfg["steady_moves"]:
        orders = steady_orders(state, orders, cfg, pending_moves, stats)
    if cfg["battery_watch"]:
        orders, blocked = battery_orders_watch(state, orders, cfg, mem.setdefault("batteries", {}), stats)
    if cfg["wagon_run"]:
        orders = wagon_run_orders(state, orders, cfg, mem.setdefault("wagons", {}), stats)
    for od in orders:
        od.pop("_capture", None)
    return orders, blocked
