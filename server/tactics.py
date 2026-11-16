"""Local tactics run by the server every state (0.1.4 WIP9, from the battle of 2026-11-12 14:48).

1. HOLD LINE. An objective of ours with enemy brigades coming at it: one of our brigades faces each enemy brigade
   (1 for 1, the nearest enemy first), on a post between the point and that enemy, on the best cover close to it,
   facing it, with a clear line of fire. Brigades in position concentrate their fire on ONE enemy brigade (the
   one most of them reach, the weakest when equal). Spare brigades wait behind the point as a reserve. After the
   capture of Boatswain Woods the line was badly deployed and the fire spread.
2. HUNT. An enemy brigade alone (no other enemy unit near it) within reach of at least twice its strength of ours
   is attacked by the nearest of them. A Northern brigade stayed isolated and was left alone.
3. PURSUIT. An enemy unit that is routing or falling back, with no steady enemy unit next to it, is charged by a
   fresh unit of ours close to it: the pressure is kept on after a success instead of letting the line close.
4. Prompt lines: FRESH ARRIVALS (reinforcements just on the field and the nearest end of the enemy line: a flank
   attack from there takes the line from the side) and BREACH (an enemy unit just broke and no steady enemy unit
   stands near the gap).
"""
import math

from equipment import unit_range
from fire import masker
from situation import strength
from supply import DEAD_STATUSES, split_units, unit_status

DEFAULT_TACTICS = {
    "enabled": True,
    "hold_line": True,
    "hold_threat_radius": 1000.0,    # enemy brigades this close to one of our objectives are faced 1 for 1
    "hold_pool_radius": 900.0,       # our brigades this close to the objective take part
    "hold_post": 180.0,              # a post stands this far from the point towards its enemy (less when close)
    "hold_tolerance": 90.0,          # a brigade this close to its post is in position
    "hold_min_morale": 0.45,
    "hold_repeat_s": 45.0,           # the same post is not sent again before this long
    "focus_repeat_s": 60.0,
    "hunt": True,
    "hunt_isolation": 500.0,         # an enemy unit with no other enemy combat unit this close is alone
    "hunt_radius": 800.0,            # our units this close to it may hunt it...
    "hunt_radius_defend": 600.0,     # ...this close when the plan defends
    "hunt_ratio": 2.0,               # ...when they are at least this many times its strength
    "hunt_max": 3,
    "hunt_min_morale": 0.6,
    "hunt_repeat_s": 60.0,
    "pursuit": True,
    "pursuit_radius": 350.0,         # a fresh unit this close to a routing or falling-back enemy charges it...
    "pursuit_radius_defend": 250.0,
    "pursuit_steady_clear": 300.0,   # ...when no steady enemy unit stands this close to that enemy
    "pursuit_min_morale": 0.55,
    "pursuit_max": 4,
    "arrival_window_s": 600.0,       # units on the field for less than this are "fresh arrivals"
    "breach_window_s": 240.0,        # an enemy unit that broke this recently opens a breach...
    "breach_clear": 450.0,           # ...when no steady enemy unit stands this close to where it was
}

COMBAT = ("Infantry", "Cavalry", "Artillery", "Skirmish")
KEEP = ("charge", "attack")          # orders of the model the tactics leave alone (its own aggression)


def _d(a, b):
    return math.hypot(a["x"] - b["x"], a["z"] - b["z"])


def _steady(u):
    return unit_status(u) == "" and not u.get("offmap")


def _ai_side(state):
    mine, _ = split_units(state)
    return mine[0]["side"] if mine else None


def held_objectives(state):
    side = _ai_side(state)
    return [o for o in state.get("objectives") or [] if side is not None and str(o.get("side")) == side]


def _post_spot(terrain, px, pz, e, u, taken, friends):
    """Best spot near the post (px, pz): passable, apart from the posts already given, with a clear line of fire
    on `e`, in the best cover."""
    best, best_v = None, None
    ex, ez = e["x"] - px, e["z"] - pz
    n = math.hypot(ex, ez) or 1.0
    ax, az = ex / n, ez / n                      # towards the enemy
    lx, lz = -az, ax                             # along the line
    for along in (0.0, 60.0, -60.0, 120.0, -120.0):
        for depth in (0.0, -50.0, 40.0):
            x, z = px + lx * along + ax * depth, pz + lz * along + az * depth
            if terrain is not None and hasattr(terrain, "passable") and not terrain.passable(x, z):
                continue
            if any(math.hypot(x - tx, z - tz) < 110.0 for tx, tz in taken):
                continue
            probe = dict(u, x=x, z=z)
            if masker(probe, e, [f for f in friends if f["id"] != u["id"]]) is not None:
                continue
            v = terrain.fire_value(x, z) if terrain is not None and hasattr(terrain, "fire_value") else 0.5
            v -= abs(along) / 1000.0             # the nearest of equal spots
            if best_v is None or v > best_v:
                best, best_v = (round(x, 1), round(z, 1)), v
    return best


def hold_line_orders(state, terrain, orders, plan, cfg, mem, skip=(), pending_moves=None, last_cmds=None,
                     stats=None, trap=None):
    """Returns (ids whose orders are replaced, new orders)."""
    cfg = {**DEFAULT_TACTICS, **(cfg or {})}
    if not cfg["enabled"] or not cfg["hold_line"]:
        return set(), []
    targets = {str(t.get("name")) for t in ((plan or {}).get("targets") or []) if isinstance(t, dict)}
    attacking = (plan or {}).get("mode") == "ATTACK"
    now = float(state.get("time", 0.0))
    mine, foes = split_units(state)
    friends = [u for u in mine if unit_status(u) not in DEAD_STATUSES]
    enemies = [e for e in foes if e["kind"] in ("Infantry", "Cavalry") and unit_status(e) not in DEAD_STATUSES]
    own = {o["id"]: o for o in orders}
    posts = mem.setdefault("posts", {})
    focus = mem.setdefault("focus", {})
    pairs = mem.setdefault("pairs", {})
    used, ids, out = set(skip), set(), []
    for obj in held_objectives(state):
        if attacking and str(obj.get("name")) in targets:
            continue
        threat = sorted((e for e in enemies if _d(e, obj) <= float(cfg["hold_threat_radius"])),
                        key=lambda e: _d(e, obj))
        if not threat:
            continue
        pool = [u for u in friends if u["kind"] == "Infantry" and _steady(u) and u["id"] not in used
                and float(u.get("morale", 1.0)) >= float(cfg["hold_min_morale"])
                and _d(u, obj) <= float(cfg["hold_pool_radius"])
                and (own.get(u["id"]) or {}).get("cmd") not in KEEP]
        if not pool:
            continue
        taken, placed = [], []
        for e in threat:
            if not pool:
                break
            de = _d(e, obj)
            post = min(float(cfg["hold_post"]), 0.4 * de)
            px = obj["x"] + (e["x"] - obj["x"]) / de * post if de > 0 else obj["x"]
            pz = obj["z"] + (e["z"] - obj["z"]) / de * post if de > 0 else obj["z"]
            # the brigade that already faces this enemy keeps it (a new pairing at every state restarts marches)
            kept = [v for v in pool if pairs.get(v["id"]) == e["id"]]
            u = kept[0] if kept else min(pool, key=lambda v: math.hypot(v["x"] - px, v["z"] - pz))
            pairs[u["id"]] = e["id"]
            pool.remove(u)
            used.add(u["id"])
            spot = _post_spot(terrain, px, pz, e, u, taken, friends) or (round(px, 1), round(pz, 1))
            if trap is not None and trap(spot[0], spot[1], e):
                # WIP14: no post in a losing open sector; the brigade stays where it is (or in the cover behind)
                pool.append(u)
                used.discard(u["id"])
                pairs.pop(u["id"], None)
                if stats is not None:
                    k = "hold line: no post in a losing open sector"
                    stats[k] = stats.get(k, 0) + 1
                continue
            taken.append(spot)
            placed.append((u, e, spot))
        # move the brigades that are not at their post; the others fire
        in_place = []
        for u, e, spot in placed:
            far = math.hypot(u["x"] - spot[0], u["z"] - spot[1]) > float(cfg["hold_tolerance"])
            if not far:
                in_place.append(u)
                continue
            pm = (pending_moves or {}).get(u["id"])
            last = posts.get(u["id"])
            if pm and math.hypot(pm[0] - spot[0], pm[1] - spot[1]) < 60.0:
                ids.add(u["id"])
                continue
            if last and math.hypot(last[0] - spot[0], last[1] - spot[1]) < 60.0 \
                    and now - last[2] < float(cfg["hold_repeat_s"]):
                ids.add(u["id"])
                continue
            posts[u["id"]] = (spot[0], spot[1], now)
            ids.add(u["id"])
            out.append({"cmd": "move", "id": u["id"], "x": spot[0], "z": spot[1],
                        "fx": round(e["x"], 1), "fz": round(e["z"], 1), "auto": True})
            if stats is not None:
                k = "hold line: a brigade posted in front of a held objective, facing its own enemy brigade (1 for 1)"
                stats[k] = stats.get(k, 0) + 1
        # one target for every brigade in position: the enemy most of them reach, the weakest when equal
        if in_place:
            def reach(e):
                return [u for u in in_place if _d(u, e) <= unit_range(u, 400.0) and masker(u, e, friends) is None]
            best = max(threat, key=lambda e: (len(reach(e)), -float(e["hp"]) * float(e.get("morale", 1.0))))
            for u in reach(best):
                ids.add(u["id"])
                last = focus.get(u["id"])
                if last and last[0] == best["id"] and now - last[1] < float(cfg["focus_repeat_s"]):
                    continue
                focus[u["id"]] = (best["id"], now)
                out.append({"cmd": "range_attack", "id": u["id"], "target": best["id"], "auto": True})
                if stats is not None:
                    k = "hold line: fire of the brigades in position concentrated on one enemy brigade"
                    stats[k] = stats.get(k, 0) + 1
    return ids, out


def hunt_orders(state, orders, plan, cfg, mem, skip=(), stats=None):
    """An isolated enemy unit within reach of at least `hunt_ratio` times its strength is attacked."""
    cfg = {**DEFAULT_TACTICS, **(cfg or {})}
    if not cfg["enabled"] or not cfg["hunt"]:
        return set(), []
    defending = (plan or {}).get("mode") in ("DEFEND", "TRADE")
    radius = float(cfg["hunt_radius_defend" if defending else "hunt_radius"])
    now = float(state.get("time", 0.0))
    mine, foes = split_units(state)
    live_foes = [e for e in foes if e["kind"] in COMBAT and unit_status(e) not in DEAD_STATUSES]
    own = {o["id"]: o for o in orders}
    used, ids, out = set(skip), set(), []
    last = mem.setdefault("hunt", {})
    for e in sorted(live_foes, key=lambda e: float(e["hp"])):
        if e["kind"] == "Skirmish" or unit_status(e) != "":
            continue
        if any(f["id"] != e["id"] and _d(f, e) < float(cfg["hunt_isolation"]) for f in live_foes):
            continue
        cands = sorted((u for u in mine if u["kind"] in ("Infantry", "Cavalry") and _steady(u)
                        and u["id"] not in used and float(u.get("morale", 1.0)) >= float(cfg["hunt_min_morale"])
                        and _d(u, e) <= radius and (own.get(u["id"]) or {}).get("cmd") not in KEEP),
                       key=lambda u: _d(u, e))
        need = float(cfg["hunt_ratio"]) * strength([e])
        if need <= 0 or strength(cands) < need:
            continue
        team, got = [], 0.0
        for u in cands[:int(cfg["hunt_max"])]:
            team.append(u)
            got += strength([u])
            if got >= 1.25 * need and len(team) >= 2:
                break
        if got < need:
            continue
        for u in team:
            used.add(u["id"])
            ids.add(u["id"])
            prev = last.get(u["id"])
            if prev and prev[0] == e["id"] and now - prev[1] < float(cfg["hunt_repeat_s"]):
                continue
            last[u["id"]] = (e["id"], now)
            close = _d(u, e) <= float(u.get("chargeRange") or 250.0)
            shaken = float(e.get("morale", 1.0)) < 0.5 or e["kind"] == "Artillery"
            cmd = "charge" if close and shaken else "attack"
            out.append({"cmd": cmd, "id": u["id"], "target": e["id"], "auto": True})
            if stats is not None:
                k = "hunt: an isolated enemy unit attacked by twice its strength or more"
                stats[k] = stats.get(k, 0) + 1
    return ids, out


def pursuit_orders(state, orders, plan, cfg, mem, skip=(), stats=None):
    """A routing or falling-back enemy unit, with no steady enemy unit next to it, is charged by a fresh unit of
    ours close to it."""
    cfg = {**DEFAULT_TACTICS, **(cfg or {})}
    if not cfg["enabled"] or not cfg["pursuit"]:
        return set(), []
    defending = (plan or {}).get("mode") in ("DEFEND", "TRADE")
    radius = float(cfg["pursuit_radius_defend" if defending else "pursuit_radius"])
    now = float(state.get("time", 0.0))
    mine, foes = split_units(state)
    steady = [e for e in foes if e["kind"] in COMBAT and unit_status(e) == "" and float(e.get("morale", 1.0)) >= 0.5]
    beaten = [e for e in foes if e["kind"] in ("Infantry", "Cavalry", "Artillery")
              and unit_status(e) in ("routing", "fallback")]
    own = {o["id"]: o for o in orders}
    used, ids, out = set(skip), set(), []
    last = mem.setdefault("pursuit", {})
    for e in sorted(beaten, key=lambda e: float(e["hp"])):
        if len(out) >= int(cfg["pursuit_max"]):
            break
        if any(_d(s, e) < float(cfg["pursuit_steady_clear"]) for s in steady):
            continue
        cands = [u for u in mine if u["kind"] in ("Infantry", "Cavalry") and _steady(u) and u["id"] not in used
                 and float(u.get("morale", 1.0)) >= float(cfg["pursuit_min_morale"]) and _d(u, e) <= radius
                 and (own.get(u["id"]) or {}).get("cmd") not in KEEP]
        if not cands:
            continue
        # cavalry first (it catches up), then the nearest
        u = min(cands, key=lambda u: (u["kind"] != "Cavalry", _d(u, e)))
        used.add(u["id"])
        ids.add(u["id"])
        prev = last.get(u["id"])
        if prev and prev[0] == e["id"] and now - prev[1] < 45.0:
            continue
        last[u["id"]] = (e["id"], now)
        out.append({"cmd": "charge", "id": u["id"], "target": e["id"], "auto": True})
        if stats is not None:
            k = "pursuit: a beaten enemy unit charged again before it rallies"
            stats[k] = stats.get(k, 0) + 1
    return ids, out


def note_field(state, mem):
    """Keeps, per unit of ours, the time it was first seen on the field, and the last place of each enemy unit
    with the time it broke (for the BREACH line)."""
    now = float(state.get("time", 0.0))
    mine, foes = split_units(state)
    since = mem.setdefault("on_field_since", {})
    first = "t0" not in mem
    mem.setdefault("t0", now)
    for u in mine:
        if not u.get("offmap") and u["id"] not in since:
            since[u["id"]] = mem["t0"] if first else now
    seen = mem.setdefault("foes", {})
    for e in foes:
        rec = seen.get(e["id"])
        broken = unit_status(e) in DEAD_STATUSES
        if rec is None:
            seen[e["id"]] = {"x": e["x"], "z": e["z"], "broke": None, "kind": e["kind"]}
            continue
        if broken and rec["broke"] is None:
            rec["broke"] = now
        if not broken:
            rec.update(x=e["x"], z=e["z"], broke=None)


def arrivals_lines(state, mem, cfg=None):
    cfg = {**DEFAULT_TACTICS, **(cfg or {})}
    now = float(state.get("time", 0.0))
    mine, foes = split_units(state)
    since = mem.get("on_field_since") or {}
    t0 = mem.get("t0", now)
    fresh = [u for u in mine if u["kind"] in ("Infantry", "Cavalry", "Artillery") and _steady(u)
             and since.get(u["id"], t0) > t0 and now - since[u["id"]] <= float(cfg["arrival_window_s"])]
    rest = [u for u in mine if _steady(u) and u not in fresh and u["kind"] in COMBAT]
    enemy = [e for e in foes if e["kind"] in ("Infantry", "Cavalry", "Artillery") and unit_status(e) == ""]
    if not fresh or not enemy or not rest:
        return []
    fx = sum(u["x"] for u in fresh) / len(fresh)
    fz = sum(u["z"] for u in fresh) / len(fresh)
    mx = sum(u["x"] for u in rest) / len(rest)
    mz = sum(u["z"] for u in rest) / len(rest)
    ex = sum(e["x"] for e in enemy) / len(enemy)
    ez = sum(e["z"] for e in enemy) / len(enemy)
    ax, az = ex - mx, ez - mz
    n = math.hypot(ax, az) or 1.0
    px, pz = -az / n, ax / n                     # along the enemy front
    ends = (min(enemy, key=lambda e: (e["x"] - ex) * px + (e["z"] - ez) * pz),
            max(enemy, key=lambda e: (e["x"] - ex) * px + (e["z"] - ez) * pz))
    end = min(ends, key=lambda e: math.hypot(e["x"] - fx, e["z"] - fz))
    d = math.hypot(end["x"] - fx, end["z"] - fz)
    ids = ", ".join(f"#{u['id']}" for u in fresh[:8])
    return [f"FRESH ARRIVALS: {ids} came onto the field near ({fx:.0f}, {fz:.0f}). The nearest end of the enemy "
            f"line is #{end['id']} at ({end['x']:.0f}, {end['z']:.0f}), {d:.0f} from them: sent together against "
            "that end, they take the enemy line in the flank (fire from the side costs a line several times the "
            "morale of fire from the front). Commit them together and now, not one by one."]


def breach_lines(state, mem, cfg=None):
    cfg = {**DEFAULT_TACTICS, **(cfg or {})}
    now = float(state.get("time", 0.0))
    mine, foes = split_units(state)
    steady = [e for e in foes if e["kind"] in COMBAT and unit_status(e) == ""]
    fresh = [u for u in mine if u["kind"] in ("Infantry", "Cavalry") and _steady(u)
             and float(u.get("morale", 1.0)) >= 0.6]
    out = []
    for eid, rec in (mem.get("foes") or {}).items():
        if rec.get("broke") is None or now - rec["broke"] > float(cfg["breach_window_s"]):
            continue
        if rec.get("kind") not in ("Infantry", "Cavalry"):
            continue
        gap = min((math.hypot(s["x"] - rec["x"], s["z"] - rec["z"]) for s in steady), default=1e9)
        if gap < float(cfg["breach_clear"]):
            continue
        near = sorted(fresh, key=lambda u: math.hypot(u["x"] - rec["x"], u["z"] - rec["z"]))[:3]
        near = [u for u in near if math.hypot(u["x"] - rec["x"], u["z"] - rec["z"]) <= 900.0]
        if not near:
            continue
        out.append(f"BREACH at ({rec['x']:.0f}, {rec['z']:.0f}): enemy #{eid} broke there, the nearest steady enemy "
                   f"unit is {gap:.0f} away; fresh units near: "
                   + ", ".join(f"#{u['id']}" for u in near)
                   + ". Push through now and turn on the flank or rear of the units beside the gap, before the "
                     "player closes it (keep a reserve behind).")
        if len(out) >= 2:
            break
    return out
