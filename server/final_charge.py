"""The last throw: a mass charge on the objective at the end of the phase.

When the battle timer says that only `minutes_left` minutes remain and an objective to take is still in enemy
hands, every fresh brigade (morale at least `min_morale`, infantry and mounted cavalry) within `max_distance` of
it closes in to charge distance of the defenders (500 over open ground, 200 through slow ground), then all of
them charge at once: when `ready_share` of them are in place, or in any case when `charge_minutes_left` remain.
Defenders gone, they walk onto the point. Tired or shaken brigades are left out: they would only break.
"""

import math

from prompting import DEAD_STATUSES, nearest, split_units, unit_status

DEFAULT_FINAL = {
    "enabled": True,
    "minutes_left": 20.0,        # the final charge starts when the battle timer shows this little time left
    "charge_minutes_left": 12.0,  # ...and the brigades charge at the latest at this one
    "min_morale": 0.7,
    "max_distance": 2500.0,      # brigades this far from the objective at most take part
    "defender_radius": 700.0,
    "open_distance": 500.0,      # charge distance over open ground...
    "slow_distance": 200.0,      # ...and through woods, scrub or mud
    "slow_share": 0.25,
    "ready_share": 0.6,          # share of the brigades in charge distance that sends them all in
    "keep_back": 1,              # fresh brigades kept out of it (the last reserve), nearest the other objectives
}


def _d(a, b):
    return math.hypot(a["x"] - b["x"], a["z"] - b["z"])


def final_charge_orders(state, orders, target, cfg, mem, terrain=None, last_cmds=None, stats=None, quiet=False):
    """Returns (ids whose order is dropped, new orders, prompt lines)."""
    cfg = {**DEFAULT_FINAL, **(cfg or {})}
    left = (state.get("briefing") or {}).get("timeLeftS")
    if not cfg["enabled"] or left is None or target is None or float(left) > float(cfg["minutes_left"]) * 60.0:
        return set(), [], []
    mine, foes = split_units(state)
    if mine and target.get("side") == mine[0].get("side"):
        return set(), [], []                         # already ours
    live_foes = [e for e in foes if unit_status(e) not in DEAD_STATUSES]
    defenders = [e for e in live_foes if _d(e, target) <= float(cfg["defender_radius"])]
    fresh = [u for u in mine if unit_status(u) == "" and u["morale"] >= float(cfg["min_morale"])
             and (u["kind"] == "Infantry" or (u["kind"] == "Cavalry" and u.get("mount") in (None, "mounted")))
             and _d(u, target) <= float(cfg["max_distance"])]
    fresh.sort(key=lambda u: _d(u, target))
    keep = int(cfg["keep_back"])
    if keep > 0 and len(fresh) > keep + 1:
        fresh = fresh[:-keep]                        # the farthest stays back as the last reserve
    if not fresh:
        return set(), [], []
    if not mem.get("started"):
        mem["started"] = True
        if not quiet:
            print(f"  FINAL CHARGE on {target.get('name')}: {len(fresh)} fresh brigade(s), {float(left) / 60:.0f} min left")

    def limit(u, e):
        slow = 0.0
        if terrain is not None and hasattr(terrain, "path_profile"):
            _, _, slow = terrain.path_profile(u["x"], u["z"], e["x"], e["z"], "Infantry")
        return float(cfg["slow_distance"] if slow > float(cfg["slow_share"]) else cfg["open_distance"])

    plan = []
    for u in fresh:
        if defenders:
            e = min(defenders, key=lambda x: _d(u, x))
            plan.append((u, e, _d(u, e), limit(u, e)))
        else:
            plan.append((u, None, _d(u, target), 0.0))
    in_reach = [p for p in plan if p[1] is not None and p[2] <= p[3]]
    with_targets = [p for p in plan if p[1] is not None]
    go = (mem.get("charging") or float(left) <= float(cfg["charge_minutes_left"]) * 60.0
          or (with_targets and len(in_reach) >= math.ceil(float(cfg["ready_share"]) * len(with_targets))))
    if go and not mem.get("charging") and with_targets:
        mem["charging"] = True
        if not quiet:
            print(f"  FINAL CHARGE: {len(in_reach)} of {len(with_targets)} brigade(s) in reach, all charge now")
    by_id = {o["id"]: o for o in orders}
    drop, out = set(), []
    for u, e, d, lim in plan:
        last = (last_cmds or {}).get(u["id"]) or {}
        own = by_id.get(u["id"])
        if own and own["cmd"] == "fallback":
            continue
        if e is None:
            if d > float(target.get("captureRange") or 150.0) * 0.6:
                cmd = {"cmd": "move", "id": u["id"], "x": round(target["x"], 1), "z": round(target["z"], 1),
                       "auto": True}
                key = "final charge: walks onto the objective (no defender left)"
            else:
                continue
        elif go and d <= lim * 1.2:
            if last.get("cmd") == "charge" and last.get("target") == e["id"]:
                continue
            cmd = {"cmd": "charge", "id": u["id"], "target": e["id"], "auto": True}
            key = "final charge: brigades charging the defenders together"
        elif d > lim:
            # close in to charge distance, on the line to the defender
            stop = lim * 0.85
            x = e["x"] + (u["x"] - e["x"]) / (d or 1.0) * stop
            z = e["z"] + (u["z"] - e["z"]) / (d or 1.0) * stop
            if last.get("cmd") == "move" and math.hypot(float(last.get("x", 0)) - x, float(last.get("z", 0)) - z) < 80:
                continue
            cmd = {"cmd": "move", "id": u["id"], "x": round(x, 1), "z": round(z, 1),
                   "fx": round(e["x"], 1), "fz": round(e["z"], 1), "auto": True}
            key = "final charge: brigades closing to charge distance"
        else:
            continue
        if own:
            drop.add(u["id"])
        out.append(cmd)
        if stats is not None:
            stats[key] = stats.get(key, 0) + 1
    lines = [f"FINAL CHARGE ({float(left) / 60:.0f} min left): the server sends every fresh brigade (morale "
             f"{float(cfg['min_morale']):.1f}+) at {target.get('name')}: "
             + ("CHARGING now." if mem.get("charging") else
                f"closing to charge distance ({len(in_reach)} of {len(with_targets)} in reach; all charge at "
                f"{float(cfg['charge_minutes_left']):.0f} min left at the latest).")
             + " Feed it: batteries on the defenders, cavalry on their flank; do not order its brigades."]
    return drop, out, lines
