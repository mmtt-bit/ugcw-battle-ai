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
import perks as perks_mod
from prompting import CLEARANCE, DEAD_STATUSES, find_clear_spot, in_lane, nearest, split_units, unit_status

DEFAULT_ASSAULT = {
    "enabled": True,
    "launch_minutes": 6.0,        # battle time before which the army is still deploying
    "group_share": 0.45,          # share of the infantry brigades in the assault group
    "group_min": 2,
    "group_max": 5,               # floor of the cap...
    "group_max_share": 0.12,      # ...raised to this share of the infantry brigades in large armies
    "min_morale": 0.65,           # to join the group
    "min_strength": 0.5,          # share of starting men, to join the group
    "stage_distance": 0.0,        # 0 = from the objective: max(capture range + 200, fire range + 120)
    "stage_radius": 130.0,        # a brigade this close to its staging spot has arrived
    "stage_timeout_s": 420.0,     # launch after this long even if the group is not complete
    "ready_share": 0.7,           # share of the group that must have arrived to launch
    "launch_min_ratio": 0.6,      # group strength / defenders' strength needed to launch...
    "max_wait_s": 900.0,          # ...but the assault goes in anyway after waiting this long in the staging area
    "strong_ratio": 2.0,          # with this local superiority the group goes in as soon as...
    "strong_ready_share": 0.5,    # ...this share of it has arrived (time given to the defender is time to fortify)
    "latest_launch_minutes": 35.0,  # battle time after which a staged group goes in anyway (unless paused)
    "stage_angles": [0, -20, 20, -40, 40],   # staging directions tried (degrees from the direct approach)
    "defender_radius": 650.0,     # enemy units this close to the point are its defenders
    "max_orders_per_turn": 5,
    "abort_loss_share": 0.35,     # the group is released when it has lost this share of its men
    "abort_pause_s": 600.0,
    "briefing_chars": 700,
    "launch_time_share": 0.7,     # with a battle timer: launch at the latest when only this share of the time is left
    "defender_memory_s": 600.0,   # defenders seen this recently still count (hidden in woods is not gone)
    "approach_margin": 250.0,     # a launched brigade further than its range + this from its target first marches
                                  # to a firing position (cover preferred) instead of an "attack" order
    "cover_weight": 700.0,        # march distance a covered firing spot is worth (per point of cover x damage)
    "charge_morale": 0.5,         # launched brigades charge a defender in reach whose morale fell under this...
    "charge_when_strong": False,  # ...or (aggressive doctrine) any defender in reach when the group is strong_ratio up
    "charge_min_morale": 0.7,     # a brigade charges only with this morale or more
    "max_charges_per_turn": 4,
    "charge_max_distance": 200.0, # (kept for older configs; see charge_open_distance / charge_slow_distance)
    "charge_open_distance": 500.0,  # charges start from this far at most over open ground...
    "charge_slow_distance": 200.0,  # ...and from this far when the way is mostly slow ground (woods, scrub, mud)
    "charge_slow_share": 0.25,    # share of slow ground on the way above which the short distance applies
    "close_charge_strength": 0.7, # at the short distance a fresh brigade charges if it has this share of the
                                  # target's men or more
    "charge_together": 2,         # brigades that must be in reach to charge at once (a lone shaken target excepted)
    "reserve_keep": None,         # aggressive doctrine: every fit infantry brigade but this many joins the group
    "split_min_infantry": 6,      # with two objectives to take and this many brigades, one assault on each
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


def select_group(mine, foes, obj, cfg, mem, wanted=None, exclude=()):
    """The assault group: brigades kept from earlier turns while they are fit, topped up with the nearest fit ones.
    `wanted`: the brigades the model named in its assault directive (macro command), used as given while fit.
    `exclude`: brigades already in another assault group."""
    if wanted:
        ok = {u["id"]: u for u in _live(mine)
              if u["id"] not in exclude and u["kind"] in ("Infantry", "Skirmish", "Cavalry")
              and u["morale"] >= 0.75 * float(cfg["min_morale"]) and unit_status(u) in ("",)}
        return [ok[i] for i in wanted if i in ok]
    inf = [u for u in _live(mine) if u["kind"] == "Infantry" and u["id"] not in exclude]
    cap = max(int(cfg["group_max"]), int(round(float(cfg.get("group_max_share", 0.0)) * len(inf))))
    size = max(int(cfg["group_min"]), min(cap, int(round(float(cfg["group_share"]) * len(inf)))))
    if cfg.get("reserve_keep") is not None:
        # aggressive attack: the assault gets the brigades nearest the objective, only a small reserve stays back
        size = max(size, len(inf) - int(cfg["reserve_keep"]))
    size = min(size, len(inf))
    fit = {u["id"]: u for u in inf
           if u["morale"] >= float(cfg["min_morale"]) * (0.75 if u["id"] in mem.get("group", []) else 1.0)
           and _share(u) >= float(cfg["min_strength"]) and unit_status(u) in ("",)}
    keep = [i for i in mem.get("group", []) if i in fit]
    # nearest first; brigades whose perks favour assault (charge damage, steadiness in melee) count as nearer
    rest = sorted((u for i, u in fit.items() if i not in keep),
                  key=lambda u: _dist(u, obj) - 400.0 * perks_mod.role_score(u, "assault"))
    chosen = keep[:size] + [u["id"] for u in rest[:max(0, size - len(keep))]]
    return [fit[i] for i in chosen]


def stage_spots(group, obj, cfg, ranges, mine, foes, terrain=None, approach=None):
    """One staging spot per brigade, side by side on the side of the objective we come from."""
    if not group:
        return {}
    cx = sum(u["x"] for u in group) / len(group)
    cz = sum(u["z"] for u in group) / len(group)
    dx, dz = cx - obj["x"], cz - obj["z"]
    n = math.hypot(dx, dz) or 1.0
    if approach:
        # the model chose the side the assault comes from (macro command): stage between it and the objective
        ax, az = float(approach[0]) - obj["x"], float(approach[1]) - obj["z"]
        an = math.hypot(ax, az)
        if an > 1:
            dx, dz, n = ax, az, max(n, an)
    ux, uz = dx / (math.hypot(dx, dz) or 1.0), dz / (math.hypot(dx, dz) or 1.0)
    d = min(stage_distance(obj, cfg, ranges), max(n, 1.0))      # never "stage" behind where we already are
    bx, bz = obj["x"] + ux * d, obj["z"] + uz * d
    if terrain is not None and hasattr(terrain, "path_profile"):
        # Choose the staging direction whose approach to the objective crosses the least slow ground (woods,
        # scrub, mud slow the assault and tire the men), with a small cost for turning away from the direct line.
        best = None
        for ang in cfg.get("stage_angles") or [0]:
            a = math.radians(float(ang))
            vx, vz = ux * math.cos(a) - uz * math.sin(a), ux * math.sin(a) + uz * math.cos(a)
            sx, sz = obj["x"] + vx * d, obj["z"] + vz * d
            if not terrain.passable(sx, sz):
                continue
            _, eff, _ = terrain.path_profile(sx, sz, obj["x"], obj["z"])
            score = eff + (300.0 if terrain.is_slow(sx, sz) else 0.0) + 3.0 * abs(float(ang))
            if best is None or score < best[0]:
                best = (score, sx, sz, vx, vz)
        if best is not None:
            _, bx, bz, ux, uz = best
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


def lane_blocked(u, target, mine):
    """The friendly unit standing in the straight line of fire from u to target, or None."""
    for f in mine:
        if f["id"] == u["id"] or unit_status(f) in DEAD_STATUSES:
            continue
        if in_lane((u["x"], u["z"]), (target["x"], target["z"]), (f["x"], f["z"])):
            return f
    return None


def phase_clock(state):
    """(share of the phase's time already used, whole time of the phase in s, time left in s), or None without a
    battle timer. The whole time is time left + time already spent in this mission (phase), so it is right after
    loading a saved battle too (the server's own phase clock restarts at the load)."""
    b = state.get("briefing") or {}
    left = b.get("timeLeftS")
    if left is None:
        return None
    left = float(left)
    spent = b.get("missionElapsedS")
    spent = float(spent) if spent is not None else float(state.get("phaseTime", 0.0))
    total = left + spent
    if total <= 0:
        return None
    return spent / total, total, left


def time_share_left(state, mem=None):
    """Share of the phase's time still left (from the battle timer), or None without a timer."""
    c = phase_clock(state)
    return None if c is None else 1.0 - c[0]


def assault_orders(state, orders, plan_info, cfg, last_cmds, pending_moves, ranges, terrain, mem, stats=None,
                   exclude=()):
    """Returns (ids whose own order is dropped, new orders). `mem` is a dict kept between turns.
    plan_info["directive"] (optional) is the model's macro command for this assault: group, approach, launch."""
    cfg = {**DEFAULT_ASSAULT, **(cfg or {}), **((plan_info or {}).get("cfg_override") or {})}
    directive = (plan_info or {}).get("directive") or {}
    if directive.get("launch") == "release":
        if mem.get("group"):
            print(f"  Assault on {mem.get('objective')} released by the model")
        mem.update(launched=False, group=[])
        mem.pop("first_arrival", None)
        return set(), []
    now = float(state.get("time", 0.0))
    phase_s = float(state.get("phaseTime", now))      # minutes are counted from the start of this map (phase)
    mine, foes = split_units(state)
    mine = _live(mine)
    if (not cfg["enabled"] or not plan_info or plan_info.get("mode") != "ATTACK" or not mine
            or phase_s / 60.0 < float(cfg["launch_minutes"])):
        if not plan_info or plan_info.get("mode") != "ATTACK":
            mem.pop("launched", None)
            mem.pop("group", None)
        return set(), []
    if now < float(mem.get("paused_until", 0.0)):
        if directive.get("launch") != "now":
            return set(), []
        mem["paused_until"] = 0.0                     # the commander sends it back in: his call
    obj = pick_target(plan_info, mine)
    if obj is None:
        return set(), []
    group = select_group(mine, foes, obj, cfg, mem, directive.get("group"), exclude)
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
            mem.pop("first_arrival", None)
            print(f"  Assault on {obj.get('name')} released: the group lost {(start - men) / start:.0%} of its men")
            return set(), []
    spots = stage_spots(group, obj, cfg, ranges, mine, foes, terrain, directive.get("approach"))
    defenders = defenders_of(obj, foes, cfg)
    # defenders seen recently but hidden now (woods, wheat) still count for the strength ratio
    seen_ids = {e["id"] for e in foes}
    dmem = mem.setdefault("defenders_seen", {})
    for e in defenders:
        dmem[e["id"]] = {"hp": e["hp"], "morale": e["morale"], "t": now}
    for k in [k for k, v in dmem.items() if now - v["t"] > float(cfg["defender_memory_s"])]:
        dmem.pop(k)
    hidden = [v for k, v in dmem.items() if k not in seen_ids]
    mem["hidden_defenders"] = len(hidden)
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
        if ready:
            mem.setdefault("first_arrival", now)
        waited = now - float(mem.get("first_arrival", now))   # time spent in the staging area, not on the road
        ds = sum(worth(e) for e in defenders) + sum(v["hp"] * (0.5 + 0.5 * v["morale"]) for v in hidden)
        local = (sum(worth(u) for u in group) / ds) if ds > 0 else math.inf
        mem["local_ratio"] = local
        share = float(cfg["strong_ready_share"]) if local >= float(cfg["strong_ratio"]) else float(cfg["ready_share"])
        share_left = time_share_left(state, mem)
        # with a battle timer the deadline is a share of the phase's time; without one, a battle minute
        late = (share_left <= float(cfg["launch_time_share"]) if share_left is not None
                else phase_s / 60.0 >= float(cfg["latest_launch_minutes"]))
        in_place = (ready >= math.ceil(share * len(group)) or late or waited >= float(cfg["stage_timeout_s"]))
        strong_enough = (local >= float(cfg["launch_min_ratio"]) or late or waited >= float(cfg["max_wait_s"]))
        launch = directive.get("launch") or "auto"
        if launch == "now":
            in_place, strong_enough = True, True       # the model's call: go in now
        elif launch == "wait":
            # the model holds the assault; only the last part of the timer overrides it
            hard = share_left is not None and share_left <= 0.5 * float(cfg["launch_time_share"])
            if not hard:
                in_place = False
        sync = plan_info.get("sync")
        if sync is not None and not mem.get("launched"):
            # synchronised assaults: this one goes in only when the other one(s) of the same turn are ready too
            sync[plan_info.get("sync_key", 0)] = bool(in_place and strong_enough)
            partners_ready = all(sync.values()) and len(sync) >= 2
            if launch != "now" and not late and not partners_ready and in_place and strong_enough:
                if not mem.get("sync_noted"):
                    mem["sync_noted"] = True
                    print(f"  Assault on {obj.get('name')} ready, waits for the other assault to go in together")
                in_place = False
        if plan_info.get("hold_launch") and launch != "now":
            if in_place and strong_enough and not mem.get("pause_noted"):
                mem["pause_noted"] = True
                print(f"  Assault on {obj.get('name')} ready but held: stop-loss pause (staging goes on)")
            in_place = False
        if in_place and not strong_enough and not mem.get("wait_noted"):
            mem["wait_noted"] = True
            print(f"  Assault on {obj.get('name')} waits in the staging area: group/defenders strength {local:.2f} "
                  f"(needs {float(cfg['launch_min_ratio']):.2f}; goes in anyway after {float(cfg['max_wait_s']) / 60:.0f} min)")
        if in_place and strong_enough:
            mem["launched"] = True
            mem["start_men"] = men
            mem["launch_time"] = now
            print(f"  ASSAULT on {obj.get('name')} launched with {len(group)} brigade(s) "
                  f"({ready} in position); defenders seen: {len(defenders)} (+{len(hidden)} hidden now)")
    by_id = {o["id"]: o for o in orders}
    drop, added = set(), []
    budget = int(cfg["max_orders_per_turn"])
    live_foes = {e["id"]: e for e in _live(foes)}
    taken = {}
    spots_taken = []
    charges = 0
    charged = set()
    if mem.get("launched"):
        # charges go in together: several brigades close to the defenders charge in the same turn
        pairs = []
        for u in group:
            own = by_id.get(u["id"])
            if (own and own["cmd"] == "fallback") or u["morale"] < float(cfg["charge_min_morale"]) \
                    or unit_status(u) != "" or ((last_cmds or {}).get(u["id"]) or {}).get("cmd") == "charge":
                continue
            near = nearest(u, [e for e in defenders if e["id"] in live_foes])
            if not near:
                continue
            e, d = near
            # charge distance by the ground: 500 over open ground, 200 through woods, scrub or mud
            slow = 0.0
            if terrain is not None and hasattr(terrain, "path_profile"):
                _, _, slow = terrain.path_profile(u["x"], u["z"], e["x"], e["z"], "Infantry")
            limit = float(cfg["charge_slow_distance"] if slow > float(cfg["charge_slow_share"])
                          else cfg["charge_open_distance"])
            reach = min(float(u.get("chargeRange") or 0) or limit, limit)
            if d > reach:
                continue
            pairs.append((u, e, own, d))
        # at close range a fresh brigade charges anyway: standing there only trades volleys
        close = [p for p in pairs if p[3] <= float(cfg["charge_slow_distance"])
                 and float(p[0]["hp"]) >= float(cfg["close_charge_strength"]) * float(p[1]["hp"])]
        weak = [p for p in pairs if p[1]["morale"] < float(cfg["charge_morale"]) or p[1]["kind"] in ("Artillery", "Skirmish")]
        strong = cfg.get("charge_when_strong") and float(mem.get("local_ratio") or 0) >= float(cfg["strong_ratio"])
        together = len(pairs) >= min(int(cfg["charge_together"]), len(group))
        go = pairs if together and (weak or strong) else weak
        go = go + [p for p in close if p not in go]
        for u, e, own, _ in go[:int(cfg["max_charges_per_turn"])]:
            if own:
                drop.add(u["id"])
            added.append({"cmd": "charge", "id": u["id"], "target": e["id"], "auto": True})
            charged.add(u["id"])
            if stats is not None:
                k = "auto assault charges (together, from close range, on shaken or outnumbered defenders)"
                stats[k] = stats.get(k, 0) + 1
    for u in sorted(group, key=lambda g: _dist(g, obj)):
        if len(added) >= budget + len(charged):
            break
        if u["id"] in charged:
            continue
        own = by_id.get(u["id"])
        if own and own["cmd"] == "fallback":
            continue
        if own and own["cmd"] == "move" and math.hypot(own["x"] - u["x"], own["z"] - u["z"]) <= 250:
            continue                                   # the model's own short sidestep (e.g. to clear its lane)
        last = (last_cmds or {}).get(u["id"]) or {}
        if mem.get("launched"):
            cands = [e for e in defenders if math.hypot(e["x"] - u["x"], e["z"] - u["z"]) <= 900.0] or defenders
            if cands:
                # prefer a defender the brigade can actually shoot at (no friendly unit in its line of fire)
                clear = [c for c in cands if lane_blocked(u, c, mine) is None]
                if not clear:
                    spot = find_clear_spot(u["x"], u["z"], u, mine, [], _live(foes), terrain)
                    if spot is not None and math.hypot(spot[0] - u["x"], spot[1] - u["z"]) > 20:
                        cmd = {"cmd": "move", "id": u["id"], "x": round(spot[0], 1), "z": round(spot[1], 1),
                               "auto": True}
                        if own:
                            drop.add(u["id"])
                        added.append(cmd)
                        mem.setdefault("blocked", {})[u["id"]] = now
                        if stats is not None:
                            k = "auto assault sidesteps (group member's line of fire blocked by a friendly unit)"
                            stats[k] = stats.get(k, 0) + 1
                        continue
                    clear = cands
                # keep the current target while it is alive and in sight: re-targeting each turn restarts the march
                cur = live_foes.get(last.get("target")) if last.get("cmd") in ("attack", "charge") else None
                if cur is not None and cur in cands:
                    e = cur
                else:
                    e = min(clear, key=lambda c: _dist(u, c) + 250.0 * c["morale"] + 120.0 * taken.get(c["id"], 0))
                taken[e["id"]] = taken.get(e["id"], 0) + 1
                rng = unit_range(u, float((ranges or {}).get("fire", 400)))
                d = _dist(u, e)
                reach = float(u.get("chargeRange") or 0) or 250.0
                if d > rng + float(cfg["approach_margin"]) and terrain is not None and hasattr(terrain, "best_fire_spot"):
                    # too far for an attack order: march to a firing position, protected if the ground allows
                    spot = terrain.best_fire_spot(u["x"], u["z"], e["x"], e["z"], rng, "Infantry", spots_taken,
                                                  cover_weight=float(cfg["cover_weight"]))
                    if spot is None:
                        continue
                    spots_taken.append((spot[0], spot[1]))
                    if u["id"] in pm and math.hypot(pm[u["id"]][0] - spot[0], pm[u["id"]][1] - spot[1]) < 120:
                        continue                               # already on its way there
                    cmd = {"cmd": "move", "id": u["id"], "x": spot[0], "z": spot[1],
                           "fx": round(e["x"], 1), "fz": round(e["z"], 1), "auto": True}
                    key = "auto assault approach moves (to a firing position, cover preferred)"
                elif (d <= rng * 0.95 and terrain is not None and hasattr(terrain, "fire_value")
                      and terrain.fire_value(u["x"], u["z"]) >= 0.9):
                    # in range from good cover: stay there and fire instead of walking out into the open
                    if last.get("cmd") == "hold" and not own:
                        continue
                    cmd = {"cmd": "hold", "id": u["id"], "auto": True}
                    key = "auto assault holds in cover (in range of a defender from a protected spot)"
                else:
                    if (own and own["cmd"] == "attack" and own.get("target") in live_foes) or \
                            (last.get("cmd") == "attack" and last.get("target") == e["id"] and u["id"] not in pm):
                        continue
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
    if briefing and briefing.get("timeLeftS") is not None and briefing.get("timerShown", True):
        left = int(float(briefing["timeLeftS"]))
        kind = ("the battle ends then" if "Mandatory" in str(briefing.get("timerKind", ""))
                else "the suggested end of the battle")
        # minutes, never "h:mm": the model read "1:47" (1 hour 47) as one minute 47 and gave the battle up
        spent = briefing.get("missionElapsedS")
        share = ""
        if spent is not None and left + float(spent) > 0:
            share = f", {float(left) / (left + float(spent)):.0%} of this phase's time"
        lines.append(f"TIME LEFT on the battle timer: {left // 60} minutes"
                     + (f" ({left // 3600} h {(left % 3600) // 60:02d} min)" if left >= 3600 else "")
                     + f"{share} ({kind}).")
    if briefing and briefing.get("clock"):
        txt = f"CLOCK: {briefing['clock']} in the battle"
        if briefing.get("endOfDay"):
            txt += f"; the day ends at {briefing['endOfDay']}"
        lines.append(txt + ".")
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
    cfg = {**DEFAULT_ASSAULT, **(cfg or {}), **((plan_info or {}).get("cfg_override") or {})}
    if not cfg["enabled"] or not plan_info or plan_info.get("mode") != "ATTACK":
        return []
    mine, foes = split_units(state)
    mine = _live(mine)
    obj = pick_target(plan_info, mine)
    if obj is None:
        return []
    now = float(state.get("time", 0.0))
    phase_s = float(state.get("phaseTime", now))
    cx = sum(u["x"] for u in mine) / max(len(mine), 1)
    cz = sum(u["z"] for u in mine) / max(len(mine), 1)
    d_obj = math.hypot(obj["x"] - cx, obj["z"] - cz)
    defenders = defenders_of(obj, foes, cfg)
    lines = [f"ASSAULT PLAN (see READING THE STATE):",
             f"  TARGET {obj.get('name')} at {obj['x']:.0f},{obj['z']:.0f} (held by the player; radius {obj.get('radius')}, "
             f"capture range {obj.get('captureRange')}, {obj.get('victoryPoints')} VP). "
             f"Your army centre is {d_obj:.0f} away."]
    # TEMPO: how much of the phase's time is used, so that the march is weighed against the clock
    clock = phase_clock(state)
    march = d_obj / 60.0                          # about 60 per minute for a brigade in line through mixed ground
    if clock is not None:
        used, total, left = clock
        deadline = 1.0 - float(cfg["launch_time_share"])
        tempo = (f"  TEMPO: {used:.0%} of this phase's time used ({left / 60:.0f} of {total / 60:.0f} minutes left); "
                 f"the assault goes in at {deadline:.0%} at the latest")
        if mem.get("hidden_defenders"):
            tempo += f"; {mem['hidden_defenders']} defender(s) seen recently are hidden now (woods), counted as present"
        if not mem.get("launched"):
            m_share = march * 60.0 / total
            tempo += (f". Marching to the point takes about {march:.0f} min ({m_share:.0%} of the phase) from your "
                      "centre: " + ("you are BEHIND SCHEDULE, commit now." if used + m_share > deadline
                                    else "keep moving."))
    else:
        latest = float(cfg["latest_launch_minutes"])
        tempo = (f"  TEMPO (no battle timer): minute {phase_s / 60:.0f} of this phase; the assault goes in by minute "
                 f"{latest:.0f} at the latest")
        if mem.get("hidden_defenders"):
            tempo += f"; {mem['hidden_defenders']} defender(s) seen recently are hidden now (woods), counted as present"
        if not mem.get("launched"):
            tempo += (f". Marching to the point takes about {march:.0f} min from your centre: "
                      + ("you are BEHIND SCHEDULE, commit now." if phase_s / 60 + march > latest else "keep moving."))
    lines.append(tempo)
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
        spots = stage_spots(group, obj, cfg, ranges, mine, foes, terrain, ((plan_info or {}).get("directive") or {}).get("approach"))
        state_txt = ("LAUNCHED: attacking the defenders" if mem.get("launched") else
                     ("PAUSED after heavy losses" if now < float(mem.get("paused_until", 0.0)) else
                      ("STAGING: walking to the staging area, launch when most have arrived" if phase_s / 60.0 >= float(cfg["launch_minutes"])
                       else f"FORMING: the assault starts at minute {cfg['launch_minutes']:.0f}")))
        ratio = mem.get("local_ratio")
        if ratio is not None and not mem.get("launched") and ratio != math.inf:
            state_txt += f"; group/defenders strength {ratio:.2f}, launch at {float(cfg['launch_min_ratio']):.2f}"
        def lane_txt(u):
            if not defenders:
                return ""
            tgt = min(defenders, key=lambda e: _dist(u, e))
            b = lane_blocked(u, tgt, mine)
            return f", lane blocked by #{b['id']}" if b else ""
        d = (plan_info or {}).get("directive") or {}
        if d:
            txt = f"  YOUR ASSAULT ORDER (macro, executed by the server): launch {d.get('launch') or 'auto'}"
            if d.get("group"):
                txt += ", group " + ", ".join(f"#{i}" for i in d["group"])
            if d.get("approach"):
                txt += f", approach from {d['approach'][0]:.0f},{d['approach'][1]:.0f}"
            lines.append(txt)
        lines.append(f"  ASSAULT GROUP ({state_txt}): "
                     + "; ".join(f"{u['name']} (#{u['id']}, {u['hp']:.0f} men, morale {u['morale']:.2f}{lane_txt(u)})"
                                 for u in group))
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
