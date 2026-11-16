"""Artillery readiness and placement: ready to fire or packed, smoothbore versus rifled.

The plugin reports for each battery "limber": ready (unlimbered, can fire), packing (limbering up),
unpacking (unlimbering) or packed (limbered, on the move, cannot fire). A move order packs a battery up
and it needs time to unpack before it fires again; a fallback order backs it off a little while it
stays unlimbered and keeps loading. Smoothbore guns lose effect with distance, so they should be
brought close to the front (behind the infantry line); rifled guns can stay back.
"""
import math

from equipment import unit_range, unit_width, weapon_label

DEFAULT_BATTERY = {
    "enabled": True,
    "backstep_max": 200.0,        # a move this short, away from the enemy, becomes a fallback
    "fallback_seconds": 12.0,     # duration of that fallback
    "advance_share": 0.85,        # smoothbore guns are brought to this share of their range from the enemy
    "cover_gap": 60.0,            # ...but never closer to the enemy than the infantry in front, minus this gap
    "default_range": 700.0,       # used when the plugin reports no range for the battery
    # Placement by the server (0.1.4). In the battle of 2026-11-11 the ten batteries stood 2,000 to 3,600 from
    # the enemy for the whole battle (range 1,050 to 1,450): they never fired, and never fired canister.
    "auto_place": True,
    "smoothbore_distance": 420.0, # smoothbore guns go this close to the enemy, beside a steady brigade, for canister
    "rifled_share": 0.8,          # rifled guns stand at this share of their range, behind the line
    "behind_line": 150.0,         # ...and at least this much farther from the enemy than the brigades in front
    "screen_morale": 0.6,         # a brigade guarding a battery needs this morale...
    "screen_contact": 650.0,      # ...and an enemy this close (it is the line)
    "screen_gap": 60.0,           # the battery stands this much farther from the enemy than its guard
    "screen_offset": 20.0,        # ...and beside it, this much space between the two
    # WIP12 (battle of 2026-11-13 15:48): 32 marches, 12 of them of 160 m, two batteries stepping on each other;
    # a battery that fires stays, wider tolerance, longer pause between two placements.
    "place_tolerance": 300.0,     # a battery this close to its ideal distance stays where it is
    "max_trip": 2500.0,
    "place_cooldown_s": 360.0,    # battle seconds between two placements of the same battery
    "keep_firing_guard": 200.0,   # an unlimbered battery with an enemy in range and a steady brigade this close stays
    "max_place_per_turn": 3,
}

READY = ("ready", "")

# Batteries whose march orders are not carried out (set by the planner from discipline.battery_orders_watch):
# the prompt must not promise that the server brings them forward.
BLOCKED = set()


def is_smoothbore(u):
    """The game marks only the rifled guns ("_RF": Parrott, Ordnance Rifle); Napoleons, howitzers and 6-pdr guns carry
    no mark. (Before 0.1.4 only a "_SB" mark counted, which no gun has: no battery was ever seen as smoothbore.)"""
    label = weapon_label(u.get("weapon"))
    if "smoothbore" in label:
        return True
    return u.get("kind") == "Artillery" and bool(label) and "rifled" not in label


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
    # Only the batteries that need a decision get a line; the ones in range and firing are counted.
    todo, firing, stuck = [], 0, []
    for b in bats:
        r = unit_range(b, cfg["default_range"])
        near = _nearest(b, foes)
        state_txt = limber_state(b)
        rifled = "rifled" in weapon_label(b.get("weapon"))
        head = f"- #{b['id']} {b['name']}" + (" (rifled)" if rifled else "")
        if not near:
            if state_txt in ("packed", "packing"):
                todo.append(f"{head}: PACKED, no enemy in sight")
            continue
        e, d = near
        if state_txt in ("packed", "packing"):
            todo.append(f"{head}: PACKED, cannot fire" + (f"; #{e['id']} already in range ({d:.0f})" if d <= r
                                                           else f"; #{e['id']} at {d:.0f}, range {r:.0f}"))
        elif state_txt == "unpacking":
            todo.append(f"{head}: unlimbering")
        elif d <= r:
            firing += 1
        elif b["id"] in BLOCKED:
            stuck.append(f"#{b['id']}")
        elif not rifled:
            spot = advance_spot(b, e, mine, cfg, r)
            todo.append(f"{head}: out of range by {d - r:.0f} (#{e['id']} at {d:.0f})"
                        + ("; the server brings it forward beside a steady brigade" if cfg.get("auto_place")
                           else (f"; move it up to {spot[0]:.0f},{spot[1]:.0f}, level with the infantry" if spot is not None
                                 else "; bring it forward only with a steady brigade")))
        else:
            todo.append(f"{head}: out of range by {d - r:.0f} (#{e['id']} at {d:.0f})")
    lines = [f"BATTERIES: {firing} of {len(bats)} in range and firing"
             + (". Needing a decision:" if todo else ".")]
    if stuck:
        todo.append("- cannot march for now (move orders to these batteries are not carried out; use them where "
                    "they stand, do not order them forward): " + ", ".join(stuck))
        lines = [f"BATTERIES: {firing} of {len(bats)} in range and firing. Needing a decision:"]
    return lines + todo


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
        if limber_state(u) not in ("packed", "packing") or u.get("offmap"):
            # (0.1.4 WIP9) a battery still walking in from the map edge is not unpacked: 444 useless forced
            # unpacks on the replay of 2026-11-12 14:48
            tries.pop(u["id"], None)
            continue
        if u["id"] in moving or u["id"] in (pending_moves or {}) or "inMove=True" in str(u.get("limberInfo") or ""):
            # still on its march (the plugin's state says inMove): unpacking now would stop it where it is.
            # In the Shiloh battle of 2026-11-10, 13 of 14 automatic unpacks hit marching batteries.
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


def _enemy_of(u, foes):
    return _nearest(u, [e for e in foes if e["kind"] in ("Infantry", "Cavalry", "Artillery", "Skirmish")])


def _keeps_firing(b, mine, foes, cfg):
    """WIP12: an unlimbered battery with an enemy in range and a steady brigade beside it is where it should be."""
    if not is_ready(b):
        return False
    near = _enemy_of(b, foes)
    if not near or near[1] > unit_range(b, cfg["default_range"]):
        return False
    guard = float(cfg.get("keep_firing_guard", 200.0))
    return any(f["kind"] == "Infantry" and float(f.get("morale", 0)) >= float(cfg["screen_morale"])
               and math.hypot(f["x"] - b["x"], f["z"] - b["z"]) <= guard for f in mine)


def placement_spot(b, mine, foes, cfg):
    """Where the battery should stand, or None to stay: a smoothbore beside a steady brigade of the line, at
    `smoothbore_distance` from the enemy (never in front of the brigade); a rifled gun at `rifled_share` of its
    range and behind the line. Returns (x, z, enemy, why)."""
    near = _enemy_of(b, foes)
    if not near:
        return None
    e, d = near
    r = unit_range(b, cfg["default_range"])
    smooth = is_smoothbore(b)
    want = min(float(cfg["smoothbore_distance"]), 0.9 * r) if smooth else float(cfg["rifled_share"]) * r
    if abs(d - want) <= float(cfg["place_tolerance"]) or (not smooth and d <= r and d >= want - float(cfg["place_tolerance"])):
        return None
    screens = []
    for g in mine:
        if g["kind"] != "Infantry" or str(g.get("status") or "") != "" or g["morale"] < float(cfg["screen_morale"]):
            continue
        ge = _enemy_of(g, foes)
        if not ge or ge[1] > float(cfg["screen_contact"]):
            continue
        screens.append((g, ge[0], ge[1]))
    best = None
    for g, ge, gd in screens:
        stand = max(want, gd + float(cfg["screen_gap"])) if smooth else max(want, gd + float(cfg["behind_line"]))
        if stand > r * 0.95:
            continue                                   # behind this part of the line it could not reach the enemy
        ux, uz = (g["x"] - ge["x"]) / (gd or 1.0), (g["z"] - ge["z"]) / (gd or 1.0)
        px, pz = -uz, ux                                # along the line
        side = 1.0 if (b["x"] - g["x"]) * px + (b["z"] - g["z"]) * pz >= 0 else -1.0
        off = (0.5 * (unit_width(g) + unit_width(b)) + float(cfg["screen_offset"])) if smooth else 0.0
        x = ge["x"] + ux * stand + side * px * off
        z = ge["z"] + uz * stand + side * pz * off
        trip = math.hypot(x - b["x"], z - b["z"])
        if trip > float(cfg["max_trip"]):
            continue
        if best is None or trip < best[0]:
            best = (trip, x, z, ge, f"{'smoothbore' if smooth else 'rifled'} at {stand:.0f} from the enemy, "
                                    f"{'beside' if smooth else 'behind'} #{g['id']}")
    if best is None:
        return None
    return best[1], best[2], best[3], best[4]


def battery_orders(state, orders, cfg=None, terrain=None, pending_moves=None, clock=None, stats=None):
    """Brings the batteries the model leaves alone to their firing positions (see placement_spot). The march packs
    a battery up; unpack_orders unlimbers it when it arrives."""
    from prompting import find_clear_spot
    cfg = {**DEFAULT_BATTERY, **(cfg or {})}
    if not cfg["enabled"] or not cfg["auto_place"]:
        return []
    player = state["playerSide"]
    mine = _live([u for u in state["units"] if u["side"] != player])
    foes = _live([u for u in state["units"] if u["side"] == player])
    if not foes:
        return []
    now = float(state.get("time", 0.0))
    clock = clock if clock is not None else {}
    ordered = {o["id"] for o in orders if o.get("cmd") not in ("ammo",)}
    out, planned = [], []
    for b in sorted((u for u in mine if u["kind"] == "Artillery"), key=lambda u: -(_enemy_of(u, foes) or (None, 0))[1]):
        if len(out) >= int(cfg["max_place_per_turn"]):
            break
        if (b["id"] in ordered or b["id"] in (pending_moves or {}) or limber_state(b) in ("packing", "unpacking")
                or b.get("offmap")):
            continue
        if "inMove=True" in str(b.get("limberInfo") or ""):
            continue
        if now - float(clock.get(b["id"], -1e9)) < float(cfg["place_cooldown_s"]):
            continue
        if _keeps_firing(b, mine, foes, cfg):
            if stats is not None:
                stats["batteries left in place (firing, guarded)"] = stats.get("batteries left in place (firing, guarded)", 0) + 1
            continue
        got = placement_spot(b, mine, foes, cfg)
        if got is None:
            continue
        x, z, e, why = got
        spot = find_clear_spot(x, z, b, mine, planned, foes, terrain)
        if spot is None:
            continue
        planned.append(spot)
        clock[b["id"]] = now
        out.append({"cmd": "move", "id": b["id"], "x": round(spot[0], 1), "z": round(spot[1], 1),
                    "fx": round(e["x"], 1), "fz": round(e["z"], 1), "auto": True})
        if stats is not None:
            key = "auto battery placements (" + why.split(" at ")[0] + ")"
            stats[key] = stats.get(key, 0) + 1
    return out
