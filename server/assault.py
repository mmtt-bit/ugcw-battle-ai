"""Assault on an objective: the attack plan the AI must have when it has to take a point the player holds.

In the battle of 2026-11-09 19:36 the mission asked the AI to take Logan Cross (the player held it and the
AI could not win without it), but the AI traded fire for 125 minutes and never came near the point: 8 attack
orders in the whole battle. This module makes the attack happen and shows the model the plan:

* the BRIEFING lines show the mission text read in the game and the objectives;
* the ASSAULT PLAN lines name the objective, its defenders, a staging area on the side we come from, the
  assault group (the freshest infantry brigades), the weak side for the cavalry and the batteries' targets;
* `assault_orders` enforces it: the group walks to the staging area (STAGING), then, when most of it has
  arrived or after a time-out (LAUNCHED), it attacks the defenders one by one, or walks onto the point when
  no defender is visible. Orders it adds carry "auto": true. A group that loses too much is released.

The model keeps the initiative for everything else (artillery, skirmishers, cavalry, the rest of the line) and
may write its own attack plan in the "plan" field of its answer; the server shows it back every turn.
Switch it off in config.json ("assault").
"""
import math

from equipment import unit_range, unit_width
from prompting import CLEARANCE, DEAD_STATUSES, nearest, split_units, unit_status

DEFAULT_ASSAULT = {
    "enabled": True,
    "launch_minutes": 6.0,        # battle time before which the army is still deploying
    "group_share": 0.45,          # share of the infantry brigades in the assault group
    "group_min": 2,
    "group_max": 5,
    "min_morale": 0.65,           # to join the group
    "min_strength": 0.5,          # share of starting men, to join the group
    "stage_distance": 0.0,        # 0 = from the objective: max(capture range + 200, fire range + 120)
    "stage_radius": 130.0,        # a brigade this close to its staging spot has arrived
    "stage_timeout_s": 420.0,     # launch after this long even if the group is not complete
    "ready_share": 0.7,           # share of the group that must have arrived to launch
    "launch_min_ratio": 0.6,      # group strength / defenders' strength needed to launch...
    "max_wait_s": 900.0,          # ...but the assault goes in anyway after waiting this long in the staging area
    "defender_radius": 650.0,     # enemy units this close to the point are its defenders
    "max_orders_per_turn": 5,
    "abort_loss_share": 0.35,     # the group is released when it has lost this share of its men
    "abort_pause_s": 600.0,
    "briefing_chars": 700,
}


def _share(u):
    return float(u["hp"]) / max(float(u["maxHp"]), 1.0)


def _live(units):
    return [u for u in units if unit_status(u) not in DEAD_STATUSES]


def _dist(a, b):
    return math.hypot(a["x"] - b["x"], a["z"] - b["z"])


def pick_target(plan_info, mine):
    """The objective to assault: of the ones the plan needs, the nearest to our army (most VP on ties)."""
    targets = (plan_info or {}).get("targets") or []
    if not targets or not mine:
        return None
    cx = sum(u["x"] for u in mine) / len(mine)
    cz = sum(u["z"] for u in mine) / len(mine)
    return min(targets, key=lambda o: (math.hypot(o["x"] - cx, o["z"] - cz) - 0.2 * float(o.get("victoryPoints") or 0)))


def stage_distance(obj, cfg, ranges):
    if float(cfg["stage_distance"]) > 0:
        return float(cfg["stage_distance"])
    capture = float(obj.get("captureRange") or obj.get("radius") or 150.0)
    return max(capture + 200.0, float((ranges or {}).get("fire", 400)) + 120.0)


def select_group(mine, foes, obj, cfg, mem):
    """The assault group: brigades kept from earlier turns while they are fit, topped up with the nearest fit ones."""
    inf = [u for u in _live(mine) if u["kind"] == "Infantry"]
    size = max(int(cfg["group_min"]), min(int(cfg["group_max"]), int(round(float(cfg["group_share"]) * len(inf)))))
    size = min(size, len(inf))
    fit = {u["id"]: u for u in inf
           if u["morale"] >= float(cfg["min_morale"]) * (0.75 if u["id"] in mem.get("group", []) else 1.0)
           and _share(u) >= float(cfg["min_strength"]) and unit_status(u) in ("",)}
    keep = [i for i in mem.get("group", []) if i in fit]
    rest = sorted((u for i, u in fit.items() if i not in keep), key=lambda u: _dist(u, obj))
    chosen = keep[:size] + [u["id"] for u in rest[:max(0, size - len(keep))]]
    return [fit[i] for i in chosen]


def stage_spots(group, obj, cfg, ranges, mine, foes, terrain=None):
    """One staging spot per brigade, side by side on the side of the objective we come from."""
    if not group:
        return {}
    cx = sum(u["x"] for u in group) / len(group)
    cz = sum(u["z"] for u in group) / len(group)
    dx, dz = cx - obj["x"], cz - obj["z"]
    n = math.hypot(dx, dz) or 1.0
    ux, uz = dx / n, dz / n
    d = min(stage_distance(obj, cfg, ranges), max(n, 1.0))      # never "stage" behind where we already are
    bx, bz = obj["x"] + ux * d, obj["z"] + uz * d
    px, pz = -uz, ux
    spacing = max(CLEARANCE, max(unit_width(u) for u in group) + 25.0)
    # order the brigades along the line so that nobody has to cross another one
    ordered = sorted(group, key=lambda u: (u["x"] - cx) * px + (u["z"] - cz) * pz)
    spots = {}
    for k, u in enumerate(ordered):
        off = (k - (len(ordered) - 1) / 2.0) * spacing
        x, z = bx + px * off, bz + pz * off
        if terrain is not None:
            snapped = terrain.nearest_passable(x, z)
            if snapped is not None:
                x, z = snapped
        spots[u["id"]] = (round(x, 1), round(z, 1))
    return spots


def defenders_of(obj, foes, cfg):
    r = max(float(cfg["defender_radius"]), float(obj.get("captureRange") or 0.0))
    near = [e for e in _live(foes) if math.hypot(e["x"] - obj["x"], e["z"] - obj["z"]) <= r]
    return sorted(near, key=lambda e: math.hypot(e["x"] - obj["x"], e["z"] - obj["z"]))


def assault_orders(state, orders, plan_info, cfg, last_cmds, pending_moves, ranges, terrain, mem, stats=None):
    """Returns (ids whose own order is dropped, new orders). `mem` is a dict kept between turns."""
    cfg = {**DEFAULT_ASSAULT, **(cfg or {})}
    now = float(state.get("time", 0.0))
    mine, foes = split_units(state)
    mine = _live(mine)
    if (not cfg["enabled"] or not plan_info or plan_info.get("mode") != "ATTACK" or not mine
            or now / 60.0 < float(cfg["launch_minutes"])):
        if not plan_info or plan_info.get("mode") != "ATTACK":
            mem.pop("launched", None)
            mem.pop("group", None)
        return set(), []
    if now < float(mem.get("paused_until", 0.0)):
        return set(), []
    obj = pick_target(plan_info, mine)
    if obj is None:
        return set(), []
    group = select_group(mine, foes, obj, cfg, mem)
    if not group:
        return set(), []
    mem["objective"] = obj.get("name")
    mem["group"] = [u["id"] for u in group]
    men = sum(u["hp"] for u in group)
    if mem.get("launched"):
        start = float(mem.get("start_men") or men)
        if start > 0 and (start - men) / start >= float(cfg["abort_loss_share"]):
            mem.update(paused_until=now + float(cfg["abort_pause_s"]), launched=False, group=[])
            mem.pop("stage_started", None)
            print(f"  Assault on {obj.get('name')} released: the group lost {(start - men) / start:.0%} of its men")
            return set(), []
    spots = stage_spots(group, obj, cfg, ranges, mine, foes, terrain)
    defenders = defenders_of(obj, foes, cfg)
    pm = pending_moves or {}
    mem.setdefault("stage_started", now)

    def arrived(u):
        sx, sz = spots[u["id"]]
        if math.hypot(u["x"] - sx, u["z"] - sz) <= float(cfg["stage_radius"]):
            return True
        near = nearest(u, _live(foes))
        return bool(near and near[1] <= unit_range(u, float((ranges or {}).get("fire", 400))) and unit_status(u) == "melee")

    def worth(u):
        return u["hp"] * (0.5 + 0.5 * u["morale"])

    if not mem.get("launched"):
        ready = sum(1 for u in group if arrived(u))
        ds = sum(worth(e) for e in defenders)
        local = (sum(worth(u) for u in group) / ds) if ds > 0 else math.inf
        mem["local_ratio"] = local
        in_place = (ready >= math.ceil(float(cfg["ready_share"]) * len(group))
                    or now - mem["stage_started"] >= float(cfg["stage_timeout_s"]))
        strong_enough = local >= float(cfg["launch_min_ratio"]) or now - mem["stage_started"] >= float(cfg["max_wait_s"])
        if in_place and not strong_enough and not mem.get("wait_noted"):
            mem["wait_noted"] = True
            print(f"  Assault on {obj.get('name')} waits in the staging area: group/defenders strength {local:.2f} "
                  f"(needs {float(cfg['launch_min_ratio']):.2f}; goes in anyway after {float(cfg['max_wait_s']) / 60:.0f} min)")
        if in_place and strong_enough:
            mem["launched"] = True
            mem["start_men"] = men
            mem["launch_time"] = now
            print(f"  ASSAULT on {obj.get('name')} launched with {len(group)} brigade(s) "
                  f"({ready} in position); defenders seen: {len(defenders)}")
    by_id = {o["id"]: o for o in orders}
    drop, added = set(), []
    budget = int(cfg["max_orders_per_turn"])
    live_foes = {e["id"]: e for e in _live(foes)}
    taken = {}
    for u in sorted(group, key=lambda g: _dist(g, obj)):
        if len(added) >= budget:
            break
        own = by_id.get(u["id"])
        if own and own["cmd"] == "fallback":
            continue
        last = (last_cmds or {}).get(u["id"]) or {}
        if mem.get("launched"):
            cands = [e for e in defenders if math.hypot(e["x"] - u["x"], e["z"] - u["z"]) <= 900.0] or defenders
            if cands:
                e = min(cands, key=lambda c: _dist(u, c) + 250.0 * c["morale"] + 120.0 * taken.get(c["id"], 0))
                if (own and own["cmd"] == "attack" and own.get("target") in live_foes) or \
                        (last.get("cmd") == "attack" and last.get("target") == e["id"] and u["id"] not in pm):
                    taken[e["id"]] = taken.get(e["id"], 0) + 1
                    continue
                taken[e["id"]] = taken.get(e["id"], 0) + 1
                cmd = {"cmd": "attack", "id": u["id"], "target": e["id"], "auto": True}
                key = "auto assault attacks (assault group on a defender of the objective)"
            else:
                if u["id"] in pm and math.hypot(pm[u["id"]][0] - obj["x"], pm[u["id"]][1] - obj["z"]) < 80:
                    continue
                if _dist(u, {"x": obj["x"], "z": obj["z"]}) <= float(obj.get("captureRange") or 100.0) * 0.6:
                    continue                                  # already standing on the point
                cmd = {"cmd": "move", "id": u["id"], "x": round(obj["x"], 1), "z": round(obj["z"], 1),
                       "fx": round(obj["x"], 1), "fz": round(obj["z"], 1), "auto": True}
                key = "auto assault moves (assault group walks onto the objective)"
        else:
            sx, sz = spots[u["id"]]
            if u["id"] in pm and math.hypot(pm[u["id"]][0] - sx, pm[u["id"]][1] - sz) < 60:
                continue
            if math.hypot(u["x"] - sx, u["z"] - sz) <= float(cfg["stage_radius"]):
                if last.get("cmd") == "hold" and not own:
                    continue
                cmd = {"cmd": "hold", "id": u["id"], "auto": True}
                key = "auto assault holds (group member waits in the staging area)"
            else:
                if own and own["cmd"] == "move" and math.hypot(own["x"] - sx, own["z"] - sz) < 80:
                    continue
                cmd = {"cmd": "move", "id": u["id"], "x": sx, "z": sz,
                       "fx": round(obj["x"], 1), "fz": round(obj["z"], 1), "auto": True}
                key = "auto assault staging moves (group walks to the staging area)"
        if own:
            drop.add(u["id"])
        added.append(cmd)
        if stats is not None:
            stats[key] = stats.get(key, 0) + 1
    return drop, added


def briefing_lines(briefing, objectives, cfg=None):
    """The mission text read in the game, then the objectives with their own description."""
    cfg = {**DEFAULT_ASSAULT, **(cfg or {})}
    lines = []
    if briefing and (briefing.get("name") or briefing.get("description")):
        text = " ".join(str(briefing.get("description") or "").split())
        limit = int(cfg["briefing_chars"])
        if len(text) > limit:
            text = text[:limit].rstrip() + "..."
        lines.append("MISSION BRIEFING (the game's own text; the goals below are what counts):")
        if briefing.get("name"):
            lines.append(f"  {briefing['name']}")
        if text:
            lines.append(f"  {text}")
    descs = [o for o in (objectives or []) if o.get("description")]
    if descs:
        if not lines:
            lines.append("OBJECTIVES (from the game):")
        for o in descs:
            lines.append(f"  - {o.get('name')}: {' '.join(str(o['description']).split())[:220]}")
    return lines


def assault_lines(state, plan_info, cfg, mem, ranges, terrain=None, saved_plan=None):
    """The ASSAULT PLAN block of the prompt (empty unless the plan is to attack an objective)."""
    cfg = {**DEFAULT_ASSAULT, **(cfg or {})}
    if not cfg["enabled"] or not plan_info or plan_info.get("mode") != "ATTACK":
        return []
    mine, foes = split_units(state)
    mine = _live(mine)
    obj = pick_target(plan_info, mine)
    if obj is None:
        return []
    now = float(state.get("time", 0.0))
    cx = sum(u["x"] for u in mine) / max(len(mine), 1)
    cz = sum(u["z"] for u in mine) / max(len(mine), 1)
    d_obj = math.hypot(obj["x"] - cx, obj["z"] - cz)
    defenders = defenders_of(obj, foes, cfg)
    lines = [f"ASSAULT PLAN (see READING THE STATE):",
             f"  TARGET {obj.get('name')} at {obj['x']:.0f},{obj['z']:.0f} (held by the player; radius {obj.get('radius')}, "
             f"capture range {obj.get('captureRange')}, {obj.get('victoryPoints')} VP). "
             f"Your army centre is {d_obj:.0f} away."]
    if defenders:
        lines.append(f"  DEFENDERS seen within {max(float(cfg['defender_radius']), 1):.0f} of it: "
                     + "; ".join(f"{e['name']} (#{e['id']}) {e['hp']:.0f} men, morale {e['morale']:.2f}, "
                                 f"{math.hypot(e['x'] - obj['x'], e['z'] - obj['z']):.0f} from the point" for e in defenders[:6]))
        ex = sum(e["x"] for e in defenders) / len(defenders)
        ez = sum(e["z"] for e in defenders) / len(defenders)
        dx, dz = obj["x"] - cx, obj["z"] - cz
        n = math.hypot(dx, dz) or 1.0
        px, pz = -dz / n, dx / n
        left = sum(1 for e in defenders if (e["x"] - ex) * px + (e["z"] - ez) * pz < 0)
        right = len(defenders) - left
        if left != right:
            weak = "left" if left < right else "right"
            lines.append(f"  WEAK SIDE of the defence: the {weak} flank (seen {min(left, right)} defender(s) against "
                         f"{max(left, right)} on the other side).")
    else:
        lines.append("  No defender seen near the point yet: scout it.")
    group_ids = mem.get("group") or [u["id"] for u in select_group(mine, foes, obj, cfg, {})]
    group = [u for u in mine if u["id"] in group_ids]
    if group:
        spots = stage_spots(group, obj, cfg, ranges, mine, foes, terrain)
        state_txt = ("LAUNCHED: attacking the defenders" if mem.get("launched") else
                     ("PAUSED after heavy losses" if now < float(mem.get("paused_until", 0.0)) else
                      ("STAGING: walking to the staging area, launch when most have arrived" if now / 60.0 >= float(cfg["launch_minutes"])
                       else f"FORMING: the assault starts at minute {cfg['launch_minutes']:.0f}")))
        ratio = mem.get("local_ratio")
        if ratio is not None and not mem.get("launched") and ratio != math.inf:
            state_txt += f"; group/defenders strength {ratio:.2f}, launch at {float(cfg['launch_min_ratio']):.2f}"
        lines.append(f"  ASSAULT GROUP ({state_txt}): "
                     + "; ".join(f"{u['name']} (#{u['id']}, {u['hp']:.0f} men, morale {u['morale']:.2f})" for u in group))
        c = next(iter(spots.values()), None)
        if c:
            lines.append("  STAGING AREA (about " + f"{stage_distance(obj, cfg, ranges):.0f}" + " from the point): "
                         + "; ".join(f"#{i} at {x:.0f},{z:.0f}" for i, (x, z) in spots.items()))
    batteries = [u for u in mine if u["kind"] == "Artillery"]
    if batteries and defenders:
        lines.append("  FIXING FIRE targets: " + ", ".join(f"#{e['id']}" for e in defenders[:3]))
    if saved_plan:
        lines.append(f"  YOUR ATTACK PLAN (minute {saved_plan[0] / 60.0:.0f}): "
                     + saved_plan[1])
    else:
        lines.append("  YOUR ATTACK PLAN: none yet; write it in \"plan\" in this answer.")
    return lines
