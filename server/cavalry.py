"""Cavalry roles: reserve against enemy cavalry, flank guard against skirmishers, early scout.

Cavalry is fragile against steady infantry in front of the line. It is kept behind the front as a
reserve (to meet enemy charges, mainly enemy melee cavalry), sent to the flanks to deal with enemy
skirmishers and scouts, and in the first minutes one brigade may scout to find the enemy dispositions.
"""
import math

import perks as perks_mod

DEFAULT_CAVALRY = {
    "enabled": True,
    "recon_minutes": 12.0,       # the scouting window at the start of the battle
    "recon_units": 1,            # brigades sent to scout
    "recon_keep_away": 500.0,    # a scout stays at least this far from enemy infantry
    "front_gap": 40.0,           # cavalry may not stand closer to the enemy than the front infantry minus this
    "exposure_radius": 700.0,    # enemy infantry within this of a cavalry destination makes it exposed
    "ride_down": True,           # find isolated skirmishers / dismounted troops for the cavalry to ride down
    "ride_max_distance": 1800.0, # farthest target considered
    "ride_isolation": 350.0,     # no steady enemy infantry (or guns) within this of the target
    "ride_path_clear": 250.0,    # the ride must pass at least this far from enemy infantry
    "ride_max_ratio": 1.3,       # target men / cavalry men
    "ride_min_morale": 0.7,      # the cavalry must be fresh
    "ride_min_stamina": 0.5,
    "ride_min_strength": 0.6,    # share of its men left
    "ride_auto": True,           # the server orders the charge when the model leaves the cavalry idle
    "ride_woods_clear": 250.0,  # no ride-down on a target this close to woods (hidden support, slow ground)
    "ride_max_slow_share": 0.3,  # nor through a path more than this share on slow ground
    "ride_auto_max": 2,         # automatic ride-downs per cavalry brigade...
    "ride_auto_window_s": 600,  # ...within this many seconds
    "scout_words": ["scout", "recon", "vision", "sight", "spot", "explor", "observ", "eagle", "hawk"],
}

DEAD = ("routing", "shattered", "captured")


def _live(units):
    return [u for u in units if str(u.get("status") or "") not in DEAD]


def _split(state):
    p = state["playerSide"]
    return _live([u for u in state["units"] if u["side"] != p]), _live([u for u in state["units"] if u["side"] == p])


def _d(a, b):
    return math.hypot(a["x"] - b["x"], a["z"] - b["z"])


def scout_perks(u, cfg):
    """Perks that help scouting. When the Rebalance bonus files give the perk's effects, only the effects count
    (spotting / stealth up): J&P's "Recon_course" is a charge and speed perk despite its name. The name words
    (cfg "scout_words") are the fallback for perks whose effects are unknown (base game, other mods)."""
    words = [w.lower() for w in cfg["scout_words"]]
    out = []
    for p in (u.get("perks") or []):
        effects = perks_mod.effects_of(u.get("kind"), str(p))
        if effects:
            if any(e[0] in ("Spotting", "Stealth") and e[1] > 0 for e in effects):
                out.append(p)
        elif any(w in str(p).lower() for w in words):
            out.append(p)
    return out


def scouts(state, cfg):
    """Ids of the cavalry brigades that may scout now: the ones with scouting perks first, else the
    least valuable (fewest stars, fewest men). Empty after the recon window or when infantry is close."""
    mine, foes = _split(state)
    if float(state.get("time", 0.0)) / 60.0 >= float(cfg["recon_minutes"]):
        return []
    cav = [u for u in mine if u["kind"] == "Cavalry" and u["morale"] >= 0.6]
    if not cav:
        return []
    if any(_d(c, e) < 800 for c in cav for e in foes if e["kind"] == "Infantry"):
        return []        # the enemy is already near: no time for scouting
    cav.sort(key=lambda u: (-len(scout_perks(u, cfg)), int(u.get("stars") or 0), u["hp"]))
    return [u["id"] for u in cav[:int(cfg["recon_units"])]]


def front_distance(mine, enemy):
    """Distance from `enemy` to the nearest friendly infantry (the front line facing it)."""
    inf = [u for u in mine if u["kind"] == "Infantry"]
    return min((_d(u, enemy) for u in inf), default=None)


def exposed_move(me, x, z, state, cfg):
    """True when a cavalry move to (x, z) ends in front of the line, near enemy infantry.
    Dismounted cavalry fights like infantry and may stand in the line."""
    if me.get("mount") in ("dismounted", "dismounting"):
        return False
    mine, foes = _split(state)
    point = {"x": x, "z": z}
    for e in foes:
        if e["kind"] != "Infantry" or _d(point, e) > float(cfg["exposure_radius"]):
            continue
        front = front_distance([u for u in mine if u["id"] != me["id"]], e)
        if front is not None and _d(point, e) < front - float(cfg["front_gap"]):
            return True
    return False


def cavalry_lines(state, cfg=None):
    cfg = {**DEFAULT_CAVALRY, **(cfg or {})}
    if not cfg["enabled"]:
        return []
    mine, foes = _split(state)
    cav = [u for u in mine if u["kind"] == "Cavalry"]
    if not cav:
        return []
    ids = set(scouts(state, cfg))
    enemy_cav = [e for e in foes if e["kind"] == "Cavalry"]
    skirm = [e for e in foes if e["kind"] == "Skirmish"]
    lines = ["CAVALRY:"]
    for c in cav:
        perks = scout_perks(c, cfg)
        bits = []
        if c["id"] in ids:
            bits.append("SCOUT NOW: ride along a flank towards the enemy side to reveal where its forces stand, stay "
                        f"{cfg['recon_keep_away']:.0f}+ from enemy infantry, then come back to the reserve"
                        + (f" (perks: {', '.join(perks)})" if perks else ""))
        else:
            ec = min(enemy_cav, key=lambda e: _d(c, e), default=None)
            sk = min(skirm, key=lambda e: _d(c, e), default=None)
            if ec is not None and _d(c, ec) < 900:
                bits.append(f"enemy cavalry {ec['name']} (#{ec['id']}) at {_d(c, ec):.0f}: stay in reserve behind the "
                            "infantry and meet it when it charges; charge it only when it is shaken or already engaged")
            elif sk is not None:
                bits.append(f"enemy skirmishers {sk['name']} (#{sk['id']}) at {_d(c, sk):.0f}: a flank task, send it round "
                            "the flank to ride them down (charge them when they stand apart from enemy infantry)")
            else:
                bits.append("reserve: wait behind the line, centred on the part of the front most likely to be charged")
        lines.append(f"- {c['name']} (#{c['id']}): " + "; ".join(bits))
    return lines + ride_down_lines(state, cfg)


def _seg_dist(p, a, b):
    """Distance from point p to the segment a-b (all dicts with x, z)."""
    dx, dz = b["x"] - a["x"], b["z"] - a["z"]
    n = dx * dx + dz * dz
    t = 0.0 if n == 0 else max(0.0, min(1.0, ((p["x"] - a["x"]) * dx + (p["z"] - a["z"]) * dz) / n))
    return math.hypot(p["x"] - (a["x"] + t * dx), p["z"] - (a["z"] + t * dz))


TERRAIN = None          # TerrainMap of the battle, set by the planner (set_terrain)
_AUTO_RIDES = {}        # cavalry id -> battle times of its automatic ride-downs


def set_terrain(terrain):
    global TERRAIN
    TERRAIN = terrain
    _AUTO_RIDES.clear()


def ride_down_targets(state, cfg=None):
    """[(cavalry, target, distance)] best target per fresh cavalry brigade: enemy skirmishers or dismounted
    troops that stand apart from steady infantry and guns, with a clear ride to them."""
    cfg = {**DEFAULT_CAVALRY, **(cfg or {})}
    if not cfg["ride_down"]:
        return []
    mine, foes = _split(state)
    steady_inf = [e for e in foes if e["kind"] == "Infantry" and str(e.get("status") or "") == ""]
    guns = [e for e in foes if e["kind"] == "Artillery"]
    targets = [e for e in foes if e["kind"] == "Skirmish"]
    out = []
    for c in mine:
        if (c["kind"] != "Cavalry" or c.get("mount") not in (None, "mounted") or c["morale"] < cfg["ride_min_morale"] or c["fatigue"] < cfg["ride_min_stamina"]
                or c["hp"] < cfg["ride_min_strength"] * c["maxHp"] or str(c.get("status") or "") not in ("",)):
            continue
        best = None
        for t in targets:
            d = _d(c, t)
            if d > float(cfg["ride_max_distance"]) or t["hp"] > float(cfg["ride_max_ratio"]) * c["hp"]:
                continue
            if any(_d(t, e) < float(cfg["ride_isolation"]) for e in steady_inf) or any(_d(t, g) < 400 for g in guns):
                continue
            if any(_seg_dist(e, c, t) < float(cfg["ride_path_clear"]) for e in steady_inf):
                continue
            if TERRAIN is not None and hasattr(TERRAIN, "nearest_hiding_place"):
                if TERRAIN.nearest_hiding_place(t["x"], t["z"], float(cfg["ride_woods_clear"])):
                    continue                           # woods next to it may hide its support; slow ground
                if TERRAIN.path_profile(c["x"], c["z"], t["x"], t["z"], "Cavalry")[2] > float(cfg["ride_max_slow_share"]):
                    continue
            key = (t["morale"] + d / 4000.0)       # shaken and near first
            if best is None or key < best[0]:
                best = (key, t, d)
        if best:
            out.append((c, best[1], best[2]))
    return out


def ride_down_lines(state, cfg=None):
    lines = []
    for c, t, d in ride_down_targets(state, cfg):
        lines.append(f"- {c['name']} (#{c['id']}) can ride down {t['name']} (#{t['id']}, {t['hp']:.0f} men, morale "
                     f"{t['morale']:.2f}) at {d:.0f}: isolated, clear ride. Order a charge from here; the cavalry closes "
                     "the distance by itself and the target's morale drops as it comes. Afterwards, go for the next "
                     "isolated target or return to the reserve.")
    return (["RIDE-DOWN OPPORTUNITIES (see READING THE STATE):"] + lines) if lines else []


def ride_down_orders(state, orders, cfg=None, last_cmds=None, stats=None):
    """Charge orders for fresh cavalry the model left idle, at an isolated skirmish target."""
    cfg = {**DEFAULT_CAVALRY, **(cfg or {})}
    if not cfg["ride_auto"]:
        return []
    ordered = {o["id"] for o in orders if o["cmd"] not in ("ammo", "supply", "limber")}
    out, taken = [], set()
    for c, t, d in ride_down_targets(state, cfg):
        if c["id"] in ordered or t["id"] in taken:
            continue
        last = (last_cmds or {}).get(c["id"])
        if last and last.get("cmd") == "charge" and last.get("target") == t["id"]:
            continue                                   # already on its way
        now = float(state.get("time", 0.0))
        recent = [x for x in _AUTO_RIDES.get(c["id"], []) if now - x < float(cfg["ride_auto_window_s"])]
        if len(recent) >= int(cfg["ride_auto_max"]):
            continue                                   # do not wear the cavalry out with charge after charge
        _AUTO_RIDES[c["id"]] = recent + [now]
        out.append({"cmd": "charge", "id": c["id"], "target": t["id"], "auto": True})
        taken.add(t["id"])
        if stats is not None:
            key = "auto cavalry charges on isolated skirmishers"
            stats[key] = stats.get(key, 0) + 1
    return out
