"""Terrain-aware checks on the orders, using the game's own terrain tooltips (speed, stealth).

* Charges through slow ground: a charge whose straight path is mostly forest, scrub or mud, or whose length counted
  at open-ground speed (effective distance) is well beyond the unit's charge range, reaches the enemy exhausted.
  It becomes an attack (advance and fire) instead. In the battle of 2026-11-10 (Shiloh) a mass charge launched from
  too far through a wood wore the men out before contact.
* Artillery and supply wagons are very slow in woods: a destination on slow ground is moved to the nearest open
  ground nearby.
* Unseen fire: a unit that loses men with no visible enemy within reach is being shot by hidden troops; woods and
  wheat hide them (stealth in the tooltips: dense forest 500 %). The UNSEEN FIRE lines name the nearest hiding place.

Switch it off in config.json ("terrain_rules").
"""
import math

from equipment import unit_charge_range
from prompting import DEAD_STATUSES, nearest, split_units, unit_status

DEFAULT_TERRAIN_RULES = {
    "enabled": True,
    "charge_max_slow_share": 0.4,     # a charge path more than this share on slow terrain becomes an attack
    "charge_max_effective": 1.3,
    "charge_close": 200.0,            # a charge from this close always goes in, whatever the ground
    # WIP12 (Thoroughfare Gap, 2026-11-13 15:48): the 7 charges of the model, 6 by fresh brigades on shaken
    # targets 200-450 away through forest, were all turned into attacks, while the game's own AI won on the same
    # map by charging. A FRESH charger (morale and stamina at least these) keeps its charge up to this distance.
    "charge_fresh_morale": 0.8,
    "charge_fresh_stamina": 0.8,
    "charge_fresh_distance": 450.0,
    "slow_below": 0.7,                # terrain slower than this (speed factor) is "slow"
    "open_ground_for": ["Artillery", "Supply"],
    "open_ground_search": 250.0,
    "unseen_min_loss": 15.0,          # men lost since the last turn with no visible enemy within reach (floor)...
    "unseen_min_share": 0.005,        # ...or this share of the unit's full strength (6000-man brigades: 30)
    "unseen_reach": 650.0,            # (kept for older configs; the unit's own fire range is used now)
    "unseen_hide_search": 700.0,
    "unseen_hide_min": 150.0,         # ignore the woods the unit stands in: the shooters are farther out
    "max_unseen_lines": 5,
    "unseen_respond": True,           # the server moves units shot by unseen enemies (when the model did not)
    "unseen_withdraw": 250.0,         # ...away from the hiding place by this much
    "unseen_advance_stop": 120.0,     # ...or, aggressive doctrine, to this distance short of it
    "unseen_advance_max": 350.0,      # ...by this much at most per order (the next state decides again)
    "cavalry_withdraw": 400.0,        # mounted cavalry pulls back this far instead
    "unseen_charge_reach": 400.0,     # aggressive doctrine: fresh infantry / mounted cavalry charges a weak enemy this close
    "unseen_close_gap": 200.0,        # balanced doctrine: close in on a visible enemy at most this far beyond range
    "unseen_min_range": 100.0,
    # 0.1.4 WIP11 (battle of 2026-11-13, Kettle Run): skirmishers out-ranging Trimble drew it 150 (plugin reflex) then
    # 250 (this rule) in front of the line; it ended alone against three brigades and was captured. Same limits as
    # the plugin's UNSEEN reflex, for infantry brigades only (screens are meant to go ahead):
    "unseen_chase_screens": False,    # an infantry brigade may close in on skirmishers or cavalry
    "unseen_line_ahead": 100.0,       # a step may not end farther than this in front of the nearest friendly brigade
    "unseen_neighbour_max": 400.0,
    "unseen_refused_holds": True,     # WIP12: a refused step forward means "hold", not "fall back"    # ...nor farther than this from it
    "cover_respond": True,            # units trading fire in the open step to cover nearby...
    "cover_max_move": 220.0,          # ...at most this far...
    "cover_min_gain": 0.4,            # ...when the spot is this much better (cover x damage; grass 0.5, forest 1.2)
    # 0.1.4 WIP6 (battle of 2026-11-11 20:29: in contact, brigades on grass lost 11.2 men per state, 5.4 in forest,
    # 3.3 in dense forest; the woods were often within 120). When the exchange is being lost and a casualty ratio
    # is among the goals (plan "woods mode"), the units fight from the woods:
    "woods_mode": True,
    "woods_max_move": 350.0,          # a unit in the open goes this far at most to reach a wood's edge
    "woods_max_per_turn": 6,
    "woods_keep_objective": 300.0,    # the last infantry brigade this close to an objective we hold stays there
    "woods_redirect_moves": True,     # a move of the model ending in the open within enemy fire range goes to cover
    "cover_max_per_turn": 3,        # units with a shorter fire range (cavalry) count as answering within this
}


def _bump(stats, key):
    if stats is not None:
        stats[key] = stats.get(key, 0) + 1


def filter_orders(orders, state, terrain, ranges, cfg=None, stats=None):
    """Returns the orders with slow-ground charges turned into attacks and slow-ground destinations of
    artillery and wagons moved to open ground."""
    cfg = {**DEFAULT_TERRAIN_RULES, **(cfg or {})}
    if not cfg["enabled"] or terrain is None or not hasattr(terrain, "path_profile"):
        return orders
    mine, foes = split_units(state)
    by_id = {u["id"]: u for u in mine}
    foe_by_id = {u["id"]: u for u in foes}
    out = []
    for o in orders:
        u = by_id.get(o.get("id"))
        if u is None:
            out.append(o)
            continue
        if o["cmd"] == "charge" and o.get("target") in foe_by_id:
            e = foe_by_id[o["target"]]
            dist, eff, slow = terrain.path_profile(u["x"], u["z"], e["x"], e["z"], u["kind"], cfg["slow_below"])
            reach = unit_charge_range(u, ranges)
            fresh = (u["kind"] == "Infantry" and float(u.get("morale", 0)) >= float(cfg["charge_fresh_morale"])
                     and float(u.get("fatigue", 0)) >= float(cfg["charge_fresh_stamina"]))
            if fresh and dist <= float(cfg["charge_fresh_distance"]):
                if dist > float(cfg["charge_close"]):
                    _bump(stats, "charges kept through slow ground (fresh brigade, close enough)")
                out.append(o)
                continue
            if dist > float(cfg["charge_close"]) and (
                    slow > float(cfg["charge_max_slow_share"]) or eff > float(cfg["charge_max_effective"]) * reach):
                if u["kind"] == "Cavalry":
                    # cavalry must not "attack" (stand and trade carbine fire): drop the charge, and for a server
                    # charge (unit under fire) pull back instead
                    _bump(stats, "cavalry charges dropped (slow ground or too far at real speed)")
                    if not o.get("auto"):
                        continue
                    dx, dz = u["x"] - e["x"], u["z"] - e["z"]
                    n = math.hypot(dx, dz) or 1.0
                    x, z = u["x"] + dx / n * float(cfg["cavalry_withdraw"]), u["z"] + dz / n * float(cfg["cavalry_withdraw"])
                    spot = terrain.nearest_passable(x, z)
                    if spot is None:
                        continue
                    o = {"cmd": "move", "id": u["id"], "x": round(spot[0], 1), "z": round(spot[1], 1),
                         "fx": round(e["x"], 1), "fz": round(e["z"], 1), "auto": True}
                else:
                    o = {k: v for k, v in o.items() if k != "cmd"}
                    o = {"cmd": "attack", **o}
                    _bump(stats, "charges turned into attacks (slow ground or too far at real speed)")
        elif (o["cmd"] in ("attack", "range_attack") and u["kind"] == "Cavalry"
              and u.get("mount") in (None, "mounted") and o.get("target") in foe_by_id):
            e = foe_by_id[o["target"]]
            if math.hypot(u["x"] - e["x"], u["z"] - e["z"]) > fire_range(u, cfg) * 1.1:
                _bump(stats, "mounted cavalry attack / range_attack orders dropped (target beyond its carbines)")
                continue
        elif o["cmd"] == "move" and u["kind"] in cfg["open_ground_for"]:
            if terrain.is_slow(o["x"], o["z"], u["kind"], cfg["slow_below"]):
                spot = terrain.nearest_open(o["x"], o["z"], u["kind"], float(cfg["open_ground_search"]), cfg["slow_below"])
                if spot is not None:
                    o = dict(o, x=round(spot[0], 1), z=round(spot[1], 1))
                    _bump(stats, "artillery / wagon destinations moved out of woods or slow ground")
        out.append(o)
    return out


def fire_range(u, cfg):
    """Distance at which the unit can answer fire (its effective range, at least unseen_min_range)."""
    return max(float(u.get("range") or 0), float(cfg["unseen_min_range"]))


def unseen_hits(state, previous_hp, terrain=None, cfg=None):
    """[(men lost, unit, hiding place or None, (nearest visible enemy, distance) or None)] for your units losing men
    while no visible enemy stands within their own fire range: the shooters are hidden (woods, wheat, a camouflage
    perk) or out-range them, so the unit cannot answer."""
    cfg = {**DEFAULT_TERRAIN_RULES, **(cfg or {})}
    if not cfg["enabled"] or not previous_hp:
        return []
    mine, foes = split_units(state)
    live = [e for e in foes if unit_status(e) not in DEAD_STATUSES]
    hits = []
    for u in mine:
        if u["kind"] == "General" or unit_status(u) in DEAD_STATUSES + ("melee", "fallback"):
            continue
        before = previous_hp.get(u["id"])
        if before is None:
            continue
        lost = float(before) - float(u["hp"])
        if lost < max(float(cfg["unseen_min_loss"]), float(cfg.get("unseen_min_share", 0.0)) * float(u.get("maxHp") or 0)):
            continue
        near = nearest(u, live) if live else None
        if near and near[1] <= fire_range(u, cfg) * 1.1:
            continue                                   # it can shoot back at what it sees
        hide = terrain.nearest_hiding_place(u["x"], u["z"], float(cfg["unseen_hide_search"]), 0.5,
                                            float(cfg["unseen_hide_min"])) \
            if (terrain is not None and hasattr(terrain, "nearest_hiding_place")
                and u["kind"] not in ("Artillery", "Supply")) else None   # 0.1.4 WIP10: no woods for batteries
        hits.append((lost, u, hide, near))
    hits.sort(key=lambda h: -h[0])
    return hits


def unseen_fire_lines(state, previous_hp, terrain=None, cfg=None):
    """UNSEEN FIRE lines: your units that lost men since the last turn with no visible enemy within reach."""
    cfg = {**DEFAULT_TERRAIN_RULES, **(cfg or {})}
    hits = unseen_hits(state, previous_hp, terrain, cfg)
    if not hits:
        return []
    lines = ["UNSEEN FIRE (losses with no visible enemy within the unit's own fire range: shooters hidden in woods or "
             "wheat, camouflaged, or out-ranging it):"]
    for lost, u, hide, near in hits[:int(cfg["max_unseen_lines"])]:
        txt = f"  {u['name']} (#{u['id']}) lost {lost:.0f} men"
        if near:
            txt += f"; nearest visible enemy #{near[0]['id']} at {near[1]:.0f} (its range {fire_range(u, cfg):.0f})"
        if hide:
            txt += f"; nearest hiding place: {hide[2]} at {hide[0]},{hide[1]} ({hide[3]} away)"
        lines.append(txt)
    lines.append("  Do not stand in the open within reach of unscouted woods: scout them with skirmishers, shell them, "
                 "or move out of range; keep cavalry away from them.")
    return lines


def keeps_line(u, x, z, to_x, to_z, mine, cfg):
    """True when infantry brigade u, at (x, z) after a step in direction (to_x, to_z) (unit vector), is still in the
    line: at most unseen_line_ahead in front of the nearest other infantry brigade (along the step) and at most
    unseen_neighbour_max from it. With no other brigade there is no line to keep."""
    others = [m for m in mine if m["id"] != u["id"] and m["kind"] == "Infantry"
              and unit_status(m) not in DEAD_STATUSES + ("routing",)]
    if not others:
        return True
    nb = min(others, key=lambda m: math.hypot(m["x"] - u["x"], m["z"] - u["z"]))
    rx, rz = x - nb["x"], z - nb["z"]
    return (math.hypot(rx, rz) <= float(cfg["unseen_neighbour_max"])
            and rx * to_x + rz * to_z <= float(cfg["unseen_line_ahead"]))


def unseen_orders(state, previous_hp, terrain, orders, aggressiveness=0.5, skip_ids=(), cfg=None, stats=None,
                  hold_line=False):
    """Server answer, for the units the model did not order this turn, to losses the unit cannot answer (shooters
    hidden, camouflaged or out of range), by the general's aggressiveness (0 careful .. 1 reckless):
      >= 0.7  fresh infantry or mounted cavalry charges a skirmisher or shaken enemy in reach; fresh infantry or
              skirmishers advance on the nearest visible enemy, else on the likely hiding place;
      >= 0.4  fresh infantry or skirmishers close in only on a visible enemy just out of their range;
      else    (and for artillery, supply, dismounted cavalry and tired units) the unit opens the distance.
    WIP11: an infantry brigade never steps out of the line (keeps_line), never closes in on skirmishers or cavalry,
    and with hold_line (the plan defends) never advances and charges only a shaken target; a refused step becomes
    "open the distance"."""
    cfg = {**DEFAULT_TERRAIN_RULES, **(cfg or {})}
    if not cfg.get("unseen_respond", True):
        return []
    if isinstance(aggressiveness, bool):              # older callers passed "aggressive"
        aggressiveness = 0.8 if aggressiveness else 0.5
    a = float(0.5 if aggressiveness is None else aggressiveness)
    ordered = {o["id"] for o in orders if o["cmd"] not in ("hold", "range_attack")}
    out = []
    mine, _ = split_units(state)
    for lost, u, hide, near in unseen_hits(state, previous_hp, terrain, cfg):
        if u["id"] in ordered or u["id"] in skip_ids:
            continue
        kind = u["kind"]
        mounted = kind == "Cavalry" and u.get("mount") in (None, "mounted")
        fresh = u["morale"] >= 0.7 and float(u["hp"]) >= 0.6 * float(u.get("maxHp") or u["hp"] or 1)
        rng = fire_range(u, cfg)
        clear_path = True
        if near and terrain is not None and hasattr(terrain, "path_profile"):
            _, eff, slow = terrain.path_profile(u["x"], u["z"], near[0]["x"], near[0]["z"], kind, cfg["slow_below"])
            clear_path = (slow <= float(cfg["charge_max_slow_share"])
                          and eff <= float(cfg["charge_max_effective"]) * float(cfg["unseen_charge_reach"]))
        line = kind == "Infantry"
        if (a >= 0.7 and fresh and near and (kind == "Infantry" or mounted) and clear_path
                and near[1] <= float(cfg["unseen_charge_reach"])
                and (near[0]["kind"] == "Skirmish" or near[0]["morale"] < 0.5)):
            e = near[0]
            dn = near[1] or 1.0
            if line and hold_line and e["morale"] >= 0.5:
                _bump(stats, "unseen fire: no charge on a steady target (the plan defends)")
            elif line and not keeps_line(u, e["x"], e["z"], (e["x"] - u["x"]) / dn, (e["z"] - u["z"]) / dn, mine, cfg):
                _bump(stats, "unseen fire: no charge out of the line")
            else:
                out.append({"cmd": "charge", "id": u["id"], "target": e["id"], "auto": True})
                _bump(stats, "unseen fire: charged a weak enemy in reach (aggressive doctrine)")
                continue
        if near:
            hx, hz = near[0]["x"], near[0]["z"]
        elif hide:
            hx, hz = hide[0], hide[1]
        else:
            # nothing seen: assume the fire comes from where the unit faces
            hx, hz = u["x"] + float(u.get("dx") or 0) * 300.0, u["z"] + float(u.get("dz") or 0) * 300.0
        dx, dz = u["x"] - hx, u["z"] - hz
        n = math.hypot(dx, dz) or 1.0
        foot = kind in ("Infantry", "Skirmish")
        advance = foot and fresh and (
            (a >= 0.7 and (near or hide)) or (a >= 0.4 and near and near[1] <= rng + float(cfg["unseen_close_gap"])))
        refused = False   # WIP12: a fresh brigade kept in the line holds its place instead of falling back
        if advance and line and hold_line:
            advance, refused = False, True
            _bump(stats, "unseen fire: no step forward (the plan defends)")
        if (advance and line and not cfg.get("unseen_chase_screens", False) and near
                and near[0]["kind"] in ("Skirmish", "Cavalry")):
            advance = False   # (a screen out-ranging the brigade: it still opens the distance)
            _bump(stats, "unseen fire: no chase of skirmishers or cavalry")
        if advance:
            stop = rng * 0.8 if near else float(cfg["unseen_advance_stop"])
            # a bounded step: the next state decides again (an uncapped advance walked brigades alone into the
            # enemy line when the "nearest visible enemy" was far behind the hidden shooters)
            go = min(max(0.0, n - stop), float(cfg.get("unseen_advance_max", 350.0)))
            x, z = u["x"] - dx / n * go, u["z"] - dz / n * go
            key = "unseen fire: closed in to answer the fire" if near else "unseen fire: advanced on the hiding place"
            if line and not keeps_line(u, x, z, -dx / n, -dz / n, mine, cfg):
                advance, refused = False, True
                _bump(stats, "unseen fire: no step out of the line")
        if refused and cfg.get("unseen_refused_holds", True):
            # WIP12 (battle of 2026-11-13 15:48): the WIP11 line rule turned 32 refused steps into fallbacks that
            # broke the very line it meant to keep; a fresh brigade kept in the line by the line or by the plan
            # holds its place (out-ranged by a screen it still opens the distance)
            _bump(stats, "unseen fire: held its place in the line")
            continue
        if not advance:
            step = float(cfg["cavalry_withdraw"] if mounted else cfg["unseen_withdraw"])
            x, z = u["x"] + dx / n * step, u["z"] + dz / n * step
            key = f"unseen fire: {kind.lower()} moved out of range"
        if terrain is not None:
            spot = terrain.nearest_passable(x, z)
            if spot is None:
                continue
            x, z = spot
        out.append({"cmd": "move", "id": u["id"], "x": round(x, 1), "z": round(z, 1),
                    "fx": round(hx, 1), "fz": round(hz, 1), "auto": True})
        _bump(stats, key)
    return out


def woods_orders(state, terrain, orders, skip_ids=(), pending=None, cfg=None, stats=None):
    """Woods mode (the plan says the exchange is being lost and the casualties count): infantry in contact on open
    ground steps back to a protected spot (forest, fortifications) that keeps the enemy in range, whether it is
    losing men or not; a move of the model ending in the open under enemy fire is put in cover nearby.
    Returns (orders of the model, possibly redirected, new orders)."""
    cfg = {**DEFAULT_TERRAIN_RULES, **(cfg or {})}
    if not cfg.get("woods_mode", True) or terrain is None or not hasattr(terrain, "best_fire_spot"):
        return orders, []
    mine, foes = split_units(state)
    live = [e for e in foes if unit_status(e) not in DEAD_STATUSES]
    if not live:
        return orders, []
    side = mine[0]["side"] if mine else None
    held = [o for o in state.get("objectives") or [] if o.get("side") == side]
    keep = float(cfg["woods_keep_objective"])
    max_move = float(cfg["woods_max_move"])
    gain = float(cfg["cover_min_gain"])

    def keeper(u):
        """The only steady infantry near an objective we hold: it stays on it."""
        for o in held:
            if math.hypot(u["x"] - o["x"], u["z"] - o["z"]) > keep:
                continue
            others = [v for v in mine if v["id"] != u["id"] and v["kind"] == "Infantry" and unit_status(v) == ""
                      and math.hypot(v["x"] - o["x"], v["z"] - o["z"]) <= keep]
            if not others:
                return True
        return False

    taken = []
    by_id = {u["id"]: u for u in mine}
    redirected = []
    for od in orders:
        u = by_id.get(od.get("id"))
        if (not cfg.get("woods_redirect_moves", True) or u is None or od.get("cmd") != "move"
                or u["kind"] not in ("Infantry", "Skirmish") or u["id"] in skip_ids or keeper(u)):
            redirected.append(od)
            continue
        near = nearest({"x": od["x"], "z": od["z"]}, live)
        rng = fire_range(u, cfg)
        here = terrain.fire_value(od["x"], od["z"], u["kind"])
        if near is None or near[1] > rng * 1.1 or here >= 1.0:
            redirected.append(od)
            continue
        spot = terrain.best_fire_spot(od["x"], od["z"], near[0]["x"], near[0]["z"], rng, u["kind"], taken,
                                      max_move=max_move)
        if spot is None or spot[3] < here + gain:
            redirected.append(od)
            continue
        taken.append((spot[0], spot[1]))
        redirected.append(dict(od, x=spot[0], z=spot[1], fx=round(near[0]["x"], 1), fz=round(near[0]["z"], 1)))
        _bump(stats, f"moves ending in the open under fire put in cover nearby (woods mode, {spot[2]})")
    ordered = {o["id"] for o in redirected if o["cmd"] not in ("hold", "range_attack", "ammo", "formation")}
    out = []
    for u in mine:
        if len(out) >= int(cfg["woods_max_per_turn"]):
            break
        if (u["kind"] not in ("Infantry", "Skirmish") or u["id"] in ordered or u["id"] in skip_ids
                or u["id"] in (pending or {}) or unit_status(u) != "" or keeper(u)):
            continue
        near = nearest(u, live)
        rng = fire_range(u, cfg)
        if near is None or near[1] > rng * 1.1:
            continue
        here = terrain.fire_value(u["x"], u["z"], u["kind"])
        if here >= 1.0:
            continue                                   # already in woods, wheat or works
        spot = terrain.best_fire_spot(u["x"], u["z"], near[0]["x"], near[0]["z"], rng, u["kind"], taken,
                                      max_move=max_move)
        if spot is None or spot[3] < here + gain:
            continue
        taken.append((spot[0], spot[1]))
        out.append({"cmd": "move", "id": u["id"], "x": spot[0], "z": spot[1],
                    "fx": round(near[0]["x"], 1), "fz": round(near[0]["z"], 1), "auto": True})
        _bump(stats, f"units in the open in contact pulled back into cover (woods mode, {spot[2]})")
    return redirected, out


def cover_orders(state, previous_hp, terrain, orders, skip_ids=(), pending=None, cfg=None, stats=None):
    """Infantry and skirmishers trading fire from open ground step to a protected spot nearby (wheat, forest,
    fortifications: cover x damage from the tooltips) that keeps the enemy in range. Only units the model did not
    order this turn, not marching, outside the assault group (which picks its own firing spots)."""
    cfg = {**DEFAULT_TERRAIN_RULES, **(cfg or {})}
    if not cfg.get("cover_respond", True) or terrain is None or not hasattr(terrain, "best_fire_spot"):
        return []
    mine, foes = split_units(state)
    live = [e for e in foes if unit_status(e) not in DEAD_STATUSES]
    if not live:
        return []
    ordered = {o["id"] for o in orders if o["cmd"] not in ("hold", "range_attack")}
    pending = pending or {}
    out, taken = [], []
    for u in mine:
        if len(out) >= int(cfg["cover_max_per_turn"]):
            break
        if (u["kind"] not in ("Infantry", "Skirmish") or u["id"] in ordered or u["id"] in skip_ids
                or u["id"] in pending or unit_status(u) != ""):
            continue
        near = nearest(u, live)
        rng = fire_range(u, cfg)
        if near is None or near[1] > rng * 1.05:
            continue                                   # not trading fire
        lost = float(previous_hp.get(u["id"], u["hp"])) - float(u["hp"]) if previous_hp else 0.0
        if lost <= 0:
            continue
        here = terrain.fire_value(u["x"], u["z"], u["kind"])
        spot = terrain.best_fire_spot(u["x"], u["z"], near[0]["x"], near[0]["z"], rng, u["kind"], taken,
                                      max_move=float(cfg["cover_max_move"]))
        if spot is None or spot[3] < here + float(cfg["cover_min_gain"]):
            continue
        taken.append((spot[0], spot[1]))
        out.append({"cmd": "move", "id": u["id"], "x": spot[0], "z": spot[1],
                    "fx": round(near[0]["x"], 1), "fz": round(near[0]["z"], 1), "auto": True})
        _bump(stats, f"units under fire in the open moved to cover nearby ({spot[2]})")
    return out
