"""Skirmish screens (0.1.4 WIP10, after the battle of 2026-11-13, Malvern Hill).

The plugin can now detach a brigade's skirmishers (the game's "pop skirmishers" button, command "detach") and send a
screen back into its brigade ("recall"). The state flags a brigade that can detach ("canScout") and gives every
screen its brigade ("owner"). The server uses screens for three jobs:

1. RECON: a brigade marching far (a flank march, a ford, woods ahead) sends its screen ahead of it, so that hidden
   brigades are found by a few dozen men and not by the brigade itself. On the right, the brigades crossed the ford
   and walked into Northern brigades waiting in the woods.
2. FLANK: brigades sent together far from the army (a flank attack) are led by a screen.
3. REARGUARD: during a withdrawal, the rearguard brigades detach their screens, which stay behind, fire on the
   pursuers and fall back last. The player could follow the retreating army and stay in contact all along.

Safety first: a screen with enemy cavalry near, or an enemy unit closing on it fast (a charge), falls back towards
its brigade at the run, whatever its job. A spent screen (low morale) near its brigade goes back into it.
"""
import math

from supply import DEAD_STATUSES, split_units, unit_status

DEFAULT_SKIRMISH = {
    "enabled": True,
    "recon": True,
    "recon_min_march": 500.0,     # a march at least this long...
    "recon_woods": 350.0,         # ...towards woods (cover within this of the destination) or a ford...
    "recon_group": 400.0,         # ...or with another brigade sent within this of the same place (flank attack)
    "recon_lead": 300.0,          # the screen walks this far ahead of its brigade, on the brigade's way
    "recon_no_contact": 500.0,    # not for a brigade already in contact
    "rearguard": True,
    "rearguard_release": 250.0,   # a rearguard screen falls back to its brigade with an enemy this close
    "max_detach_per_turn": 2,
    "cavalry_radius": 450.0,      # SAFETY: enemy cavalry this close...
    "charge_radius": 300.0,       # ...or an enemy unit this close closing in at least...
    "charge_speed": 2.0,          # ...this fast (map units per game second): the screen falls back
    "safety_step": 250.0,         # how far it falls back (towards its brigade)
    "spent_morale": 0.35,         # a screen this shaken...
    "recall_distance": 500.0,     # ...this close to its brigade goes back into it
    "repeat_s": 45.0,             # the same move is not sent again before this long
}


def _d(ax, az, bx, bz):
    return math.hypot(ax - bx, az - bz)


def _live(units):
    return [u for u in units if unit_status(u) not in DEAD_STATUSES]


def screens(state):
    mine, _ = split_units(state)
    return [u for u in _live(mine) if u["kind"] == "Skirmish"]


def screen_of(state, brigade_id):
    return next((s for s in screens(state) if s.get("owner") == brigade_id), None)


def _near_woods(terrain, x, z, r):
    if terrain is None:
        return False
    try:
        if hasattr(terrain, "name_at") and terrain.name_at(x, z) in ("Ford",):
            return True
        if hasattr(terrain, "nearest_hiding_place"):
            return terrain.nearest_hiding_place(x, z, r) is not None
    except Exception:
        return False
    return False


def recon_wanted(state, terrain, orders, pending, cfg):
    """Brigades whose march deserves a screen ahead: {brigade id: ("recon" | "flank", destination)}."""
    mine, foes = split_units(state)
    live_foes = _live(foes)
    dests = {}
    for k, q in (pending or {}).items():
        dests[k] = (float(q[0]), float(q[1]))
    for o in orders:
        if o.get("cmd") == "move" and "x" in o:
            dests[o["id"]] = (float(o["x"]), float(o["z"]))
    by_id = {u["id"]: u for u in mine}
    out = {}
    for bid, (x, z) in dests.items():
        u = by_id.get(bid)
        if u is None or u["kind"] != "Infantry" or unit_status(u) != "":
            continue
        if _d(u["x"], u["z"], x, z) < float(cfg["recon_min_march"]):
            continue
        if any(_d(u["x"], u["z"], e["x"], e["z"]) <= float(cfg["recon_no_contact"]) for e in live_foes):
            continue
        group = [k for k, q in dests.items() if k != bid and by_id.get(k, {}).get("kind") == "Infantry"
                 and _d(q[0], q[1], x, z) <= float(cfg["recon_group"])]
        if group:
            out[bid] = ("flank", (x, z))
        elif _near_woods(terrain, x, z, float(cfg["recon_woods"])):
            out[bid] = ("recon", (x, z))
    # one screen per group: the brigade nearest its destination leads
    chosen = {}
    for bid in sorted(out, key=lambda k: _d(by_id[k]["x"], by_id[k]["z"], *out[k][1])):
        x, z = out[bid][1]
        if any(_d(x, z, *v[1]) <= float(cfg["recon_group"]) for v in chosen.values()):
            continue
        chosen[bid] = out[bid]
    return chosen


def skirmish_orders(state, terrain, orders, pending, mem, prev_pos, rearguard=(), skip=(), cfg=None, stats=None):
    """Returns (ids whose orders are replaced, new orders). `prev_pos`: enemy id -> (x, z) at the previous state;
    `rearguard`: brigade ids of the withdrawal's rearguard; `skip`: ids not to touch (except for safety)."""
    cfg = {**DEFAULT_SKIRMISH, **(cfg or {})}
    if not cfg["enabled"]:
        return set(), []
    now = float(state.get("time", 0.0))
    dt = max(1.0, now - float(mem.get("t", now - 30.0)))
    mem["t"] = now
    mine, foes = split_units(state)
    live_foes = [e for e in _live(foes) if e["kind"] in ("Infantry", "Cavalry", "Skirmish")]
    by_id = {u["id"]: u for u in mine}
    jobs = mem.setdefault("jobs", {})            # brigade id -> (job, destination or None, time)
    sent = mem.setdefault("sent", {})            # screen id -> (x, z, time)
    ids, out = set(), []

    def bump(k):
        if stats is not None:
            stats[k] = stats.get(k, 0) + 1

    def move(s, x, z, run=False, face=None):
        last = sent.get(s["id"])
        if last and _d(last[0], last[1], x, z) < 60.0 and now - last[2] < float(cfg["repeat_s"]):
            return
        if terrain is not None and hasattr(terrain, "nearest_passable"):
            p = terrain.nearest_passable(x, z)
            if p is not None:
                x, z = p
        sent[s["id"]] = (x, z, now)
        o = {"cmd": "move", "id": s["id"], "x": round(x, 1), "z": round(z, 1), "auto": True}
        if face is not None:
            o["fx"], o["fz"] = round(face["x"], 1), round(face["z"], 1)
        out.append(o)
        if run:
            out.append({"cmd": "gait", "id": s["id"], "value": "Run", "auto": True})

    # 1. SAFETY: cavalry near, or an enemy closing in fast: back towards the brigade, at the run
    safe_out = set()
    for s in screens(state):
        threat = None
        for e in live_foes:
            d = _d(s["x"], s["z"], e["x"], e["z"])
            if e["kind"] == "Cavalry" and d <= float(cfg["cavalry_radius"]):
                threat = e
                break
            p = (prev_pos or {}).get(e["id"])
            if p is not None and d <= float(cfg["charge_radius"]):
                closing = (_d(s["x"], s["z"], p[0], p[1]) - d) / dt
                if closing >= float(cfg["charge_speed"]):
                    threat = e
                    break
        if threat is None:
            continue
        owner = by_id.get(s.get("owner"))
        if owner is not None and _d(s["x"], s["z"], owner["x"], owner["z"]) > 80.0:
            ox, oz = owner["x"] - s["x"], owner["z"] - s["z"]
        else:
            ox, oz = s["x"] - threat["x"], s["z"] - threat["z"]
        n = math.hypot(ox, oz) or 1.0
        step = float(cfg["safety_step"])
        if owner is not None:
            step = min(step, max(60.0, _d(s["x"], s["z"], owner["x"], owner["z"]) - 40.0))
        sent.pop(s["id"], None)                        # always sent: the danger is now
        move(s, s["x"] + ox / n * step, s["z"] + oz / n * step, run=True)
        ids.add(s["id"])
        safe_out.add(s["id"])
        bump("skirmish screens fell back from cavalry or a charge")

    # 2. spent screens near their brigade go back into it
    for s in screens(state):
        if s["id"] in safe_out or s["id"] in skip:
            continue
        owner = by_id.get(s.get("owner"))
        if (owner is not None and float(s.get("morale", 1.0)) < float(cfg["spent_morale"])
                and _d(s["x"], s["z"], owner["x"], owner["z"]) <= float(cfg["recall_distance"])
                and not mem.get("recalled", {}).get(s["id"])):
            mem.setdefault("recalled", {})[s["id"]] = now
            out.append({"cmd": "recall", "id": s["id"], "auto": True})
            ids.add(s["id"])
            bump("spent skirmish screens sent back into their brigade")

    # 3. new screens: recon / flank marches, rearguard of a withdrawal
    want = {}                                    # the rearguard first: it is in contact
    if cfg["rearguard"]:
        for bid in rearguard:
            if by_id.get(bid, {}).get("kind") == "Infantry":
                want[bid] = ("rearguard", None)
    if cfg["recon"]:
        for bid, job in recon_wanted(state, terrain, orders, pending, cfg).items():
            want.setdefault(bid, job)
    detached = 0
    for bid, (job, dest) in want.items():
        b = by_id.get(bid)
        if b is None:
            continue
        jobs[bid] = (job, dest, now)
        if screen_of(state, bid) is not None:
            continue
        if detached >= int(cfg["max_detach_per_turn"]) or not b.get("canScout"):
            continue
        last = mem.setdefault("detach_t", {}).get(bid)
        if last is not None and now - last < 120.0:
            continue
        mem["detach_t"][bid] = now
        out.append({"cmd": "detach", "id": bid, "auto": True})
        detached += 1
        bump(f"skirmishers detached ({job})")

    # 4. screens with a job: lead the march, or stay behind and fire
    for s in screens(state):
        if s["id"] in ids or s["id"] in skip:
            continue
        owner = by_id.get(s.get("owner"))
        job = jobs.get(s.get("owner"))
        if owner is None or job is None or now - job[2] > 600.0:
            continue
        kind, dest = job[0], job[1]
        if kind in ("recon", "flank") and dest is not None:
            dx, dz = dest[0] - owner["x"], dest[1] - owner["z"]
            n = math.hypot(dx, dz)
            if n < 80.0:
                continue
            lead = min(n, _d(owner["x"], owner["z"], s["x"], s["z"]) + float(cfg["recon_lead"]),
                       float(cfg["recon_lead"]) + 150.0)
            move(s, owner["x"] + dx / n * lead, owner["z"] + dz / n * lead)
            ids.add(s["id"])
            bump(f"skirmish screens leading a march ({kind})")
        elif kind == "rearguard":
            near = min(live_foes, key=lambda e: _d(s["x"], s["z"], e["x"], e["z"]), default=None)
            if near is None:
                continue
            d = _d(s["x"], s["z"], near["x"], near["z"])
            ids.add(s["id"])
            if d <= float(cfg["rearguard_release"]):
                # its job is done: it falls back to its brigade (the line behind) before the enemy is on it
                tx, tz = (owner["x"], owner["z"])
                n = _d(s["x"], s["z"], tx, tz) or 1.0
                step = min(n, 400.0)
                move(s, s["x"] + (tx - s["x"]) / n * step, s["z"] + (tz - s["z"]) / n * step, run=True)
                bump("skirmish screens of the rearguard fell back last")
            elif d <= 1.05 * float(s.get("range") or 500.0):
                last = sent.get(("fire", s["id"]))
                if not last or last[0] != near["id"] or now - last[1] > 60.0:
                    sent[("fire", s["id"])] = (near["id"], now)
                    out.append({"cmd": "range_attack", "id": s["id"], "target": near["id"], "auto": True})
                    bump("skirmish screens covering the withdrawal fired on the pursuers")
    return ids, out


def skirmish_lines(state):
    """Prompt line: which screens exist and which brigades can detach one."""
    mine, _ = split_units(state)
    sc = screens(state)
    can = [u for u in mine if u.get("canScout")]
    if not sc and not can:
        return []
    bits = []
    if sc:
        bits.append("screens out: " + ", ".join(f"#{s['id']} (of #{s.get('owner')})" for s in sc[:8]))
    if can:
        bits.append(f"{len(can)} brigade(s) can detach one")
    return ["SKIRMISH SCREENS: " + "; ".join(bits) + ". The server detaches screens to scout ahead of long marches "
            "and flank attacks and to cover withdrawals, and pulls them back from cavalry and charges; you may "
            "\"detach\" or \"recall\" yourself."]
