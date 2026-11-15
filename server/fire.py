"""Fire discipline (0.1.4 WIP8, from the battle of 2026-11-12 13:24).

1. FOCUS ON THREATS. Enemy infantry or cavalry closing in on our line (nearer than at the previous state, within
   500) is the unit to shoot: up to `focus_per_threat` of our units that have it in range and no order of the model
   this turn fire on it. The player charged brigade after brigade while our fire was spread over whatever unit each
   brigade had picked.
2. MASKED FIRE. 21 % of the time a unit of ours had an enemy in range, a friendly unit stood across its line of
   fire; the batteries were the worst (Jones 29 states, Hardaway 12). A masked battery is moved sideways to a spot
   with a clear line, a masked brigade is reported to the model.
"""
import math

from supply import DEAD_STATUSES, split_units, unit_status

DEFAULT_FIRE = {
    "enabled": True,
    "focus": True,
    "threat_radius": 500.0,
    "closing_min": 30.0,          # an enemy counts as closing in when it got this much nearer since the last state
    "focus_per_threat": 3,
    "focus_repeat_s": 60.0,       # the same target is not sent again to a unit before this long
    "unmask": True,
    "unmask_step": 160.0,         # a masked battery is moved this far sideways
    "unmask_repeat_s": 90.0,
    "unmask_after": 2,            # WIP12: a battery is moved only when masked this many states in a row...
    "unmask_battery_gap": 250.0,  # ...and to a spot at least this far from the other batteries
    # WIP13 (Crampton's Gap, 2026-11-14 07:45): three rifled Parrotts saw an enemy battery in range in 211 states and
    # never fired at it, while the enemy's smoothbores shelled the AI brigades from 470-700. A rifled battery with
    # no enemy infantry or cavalry within counter_battery_safe fires at the nearest enemy battery in its range.
    "counter_battery": True,
    # WIP17 (Antietam 2026-11-15: a rifled battery had an enemy battery in range in 757 states, a smoothbore in
    # 1277; the server fired counter-battery 8 times). Rifled guns duel unless enemy foot or horse is within 350;
    # smoothbores too now, unless it is within 400 (their canister work comes first).
    "counter_battery_safe": 350.0,
    "counter_battery_smooth": True,
    "counter_battery_safe_smooth": 400.0,
    "counter_battery_repeat_s": 90.0,
    # llm_plus: a rifled battery ordered to fire at foot or horse farther than this, while an enemy battery is in
    # its range, fires at the battery instead (long-range shells on infantry do little; guns are the threat)
    "counter_battery_override_beyond": 800.0,
}

FREE = ("hold", "ammo", "formation", "gait")


def _d(a, b):
    return math.hypot(a["x"] - b["x"], a["z"] - b["z"])


def _rng(u):
    return float(u.get("range") or (1000.0 if u["kind"] == "Artillery" else 400.0))


def masker(shooter, target, friends):
    """The friendly unit standing across the line of fire from shooter to target, or None."""
    L = _d(shooter, target)
    if L < 1.0:
        return None
    ux, uz = (target["x"] - shooter["x"]) / L, (target["z"] - shooter["z"]) / L
    for a in friends:
        if a["id"] == shooter["id"]:
            continue
        t = (a["x"] - shooter["x"]) * ux + (a["z"] - shooter["z"]) * uz
        if 40.0 < t < L - 30.0:
            off = abs(-(a["x"] - shooter["x"]) * uz + (a["z"] - shooter["z"]) * ux)
            if off < float(a.get("width") or 150.0) / 2.0 + float(shooter.get("width") or 150.0) / 4.0:
                return a
    return None


def threats(state, prev_pos, cfg=None):
    """Enemy infantry or cavalry closing in on our units within `threat_radius`: [(distance, enemy)] nearest first."""
    cfg = {**DEFAULT_FIRE, **(cfg or {})}
    mine, foes = split_units(state)
    mine = [u for u in mine if unit_status(u) not in DEAD_STATUSES and u["kind"] not in ("Supply", "General")]
    out = []
    for e in foes:
        if unit_status(e) in DEAD_STATUSES or e["kind"] not in ("Infantry", "Cavalry") or not mine:
            continue
        p = prev_pos.get(e["id"])
        if p is None:
            continue
        near = min(mine, key=lambda u: _d(u, e))
        d = _d(near, e)
        before = math.hypot(near["x"] - p[0], near["z"] - p[1])
        if d <= float(cfg["threat_radius"]) and before - d >= float(cfg["closing_min"]):
            out.append((d, e))
    return sorted(out, key=lambda t: t[0])


def fire_orders(state, terrain, orders, cfg, mem, prev_pos, skip_ids=(), stats=None):
    """Returns new orders. `mem`: {"focus": {unit id: (target, time)}, "unmask": {unit id: time}}."""
    cfg = {**DEFAULT_FIRE, **(cfg or {})}
    if not cfg["enabled"]:
        return []
    now = float(state.get("time", 0.0))
    mine, foes = split_units(state)
    live_mine = [u for u in mine if unit_status(u) not in DEAD_STATUSES]
    busy = {o["id"] for o in orders if o["cmd"] not in FREE} | set(skip_ids)
    out = []
    focus = mem.setdefault("focus", {})
    if cfg["focus"]:
        for d, e in threats(state, prev_pos, cfg):
            shooters = []
            for u in live_mine:
                if (u["id"] in busy or unit_status(u) != "" or u["kind"] not in ("Infantry", "Artillery", "Skirmish")
                        or _d(u, e) > _rng(u) or masker(u, e, live_mine) is not None):
                    continue
                shooters.append(u)
            shooters.sort(key=lambda u: _d(u, e))
            for u in shooters[:int(cfg["focus_per_threat"])]:
                last = focus.get(u["id"])
                busy.add(u["id"])
                if last and last[0] == e["id"] and now - last[1] < float(cfg["focus_repeat_s"]):
                    continue
                focus[u["id"]] = (e["id"], now)
                out.append({"cmd": "range_attack", "id": u["id"], "target": e["id"], "auto": True})
                if stats is not None:
                    stats["fire focused on an enemy closing in"] = stats.get("fire focused on an enemy closing in", 0) + 1
    if cfg.get("counter_battery", True):
        out += _counter_battery(live_mine, foes, busy, mem, now, cfg, stats)
    if cfg["unmask"] and terrain is not None:
        last = mem.setdefault("unmask", {})
        masked = mem.setdefault("masked", {})   # battery id -> masked states in a row
        live_foes = [e for e in foes if unit_status(e) not in DEAD_STATUSES]
        for b in live_mine:
            if (b["kind"] != "Artillery" or b["id"] in busy or unit_status(b) != ""
                    or now - last.get(b["id"], -1e9) < float(cfg["unmask_repeat_s"])):
                continue
            inr = [e for e in live_foes if _d(b, e) <= _rng(b)]
            if not inr:
                continue
            e = min(inr, key=lambda e: _d(b, e))
            if masker(b, e, live_mine) is None:
                masked.pop(b["id"], None)
                continue
            masked[b["id"]] = masked.get(b["id"], 0) + 1
            if masked[b["id"]] < int(cfg.get("unmask_after", 2)):
                continue
            others = [o for o in live_mine if o["kind"] == "Artillery" and o["id"] != b["id"]]
            L = _d(b, e)
            px, pz = -(e["z"] - b["z"]) / L, (e["x"] - b["x"]) / L
            for sign in (1.0, -1.0, 2.0, -2.0):
                x = b["x"] + px * sign * float(cfg["unmask_step"])
                z = b["z"] + pz * sign * float(cfg["unmask_step"])
                if not terrain.passable(x, z):
                    continue
                probe = dict(b, x=x, z=z)
                if any(_d(probe, o) < float(cfg.get("unmask_battery_gap", 250.0)) for o in others):
                    continue
                if masker(probe, e, live_mine) is None and _d(probe, e) <= _rng(b):
                    out.append({"cmd": "move", "id": b["id"], "x": round(x, 1), "z": round(z, 1),
                                "fx": round(e["x"], 1), "fz": round(e["z"], 1), "auto": True})
                    last[b["id"]] = now
                    masked.pop(b["id"], None)
                    busy.add(b["id"])
                    if stats is not None:
                        stats["masked batteries moved sideways to a clear line of fire"] = \
                            stats.get("masked batteries moved sideways to a clear line of fire", 0) + 1
                    break
    return out


def counter_battery_orders(state, orders, cfg, mem, stats=None):
    """WIP15 llm_plus: the counter-battery part of fire_orders alone (units with an order this turn are left out)."""
    cfg = {**DEFAULT_FIRE, **(cfg or {})}
    if not (cfg["enabled"] and cfg.get("counter_battery", True)):
        return []
    mine, foes = split_units(state)
    live_mine = [u for u in mine if unit_status(u) not in DEAD_STATUSES]
    busy = {o["id"] for o in orders if o["cmd"] not in FREE}
    return _counter_battery(live_mine, foes, busy, mem, float(state.get("time", 0.0)), cfg, stats)


def _safe_of(b, cfg):
    """None when this battery does not duel; else the distance within which enemy foot or horse comes first."""
    from battery import is_smoothbore
    if is_smoothbore(b):
        return float(cfg["counter_battery_safe_smooth"]) if cfg.get("counter_battery_smooth", True) else None
    return float(cfg["counter_battery_safe"])


def duel_targets(b, live_foes, live_mine, cfg):
    """Enemy batteries in range of battery b with a clear line, nearest first; [] when foot or horse is too near."""
    safe = _safe_of(b, cfg)
    if safe is None:
        return []
    if any(_d(b, e) <= safe for e in live_foes if e["kind"] in ("Infantry", "Cavalry")):
        return []
    inr = [e for e in live_foes if e["kind"] == "Artillery" and _d(b, e) <= _rng(b) and masker(b, e, live_mine) is None]
    return sorted(inr, key=lambda e: _d(b, e))


def _counter_battery(live_mine, foes, busy, mem, now, cfg, stats):
    """WIP13: batteries fire at enemy batteries in range when no enemy foot or horse threatens them (WIP17: rifled
    within 350, smoothbores too within 400)."""
    from battery import is_ready, is_smoothbore
    out = []
    cb = mem.setdefault("counter", {})
    live_foes = [e for e in foes if unit_status(e) not in DEAD_STATUSES]
    if not any(e["kind"] == "Artillery" for e in live_foes):
        return out
    for b in live_mine:
        if (b["kind"] != "Artillery" or not is_ready(b) or b["id"] in busy or unit_status(b) != ""):
            continue
        inr = duel_targets(b, live_foes, live_mine, cfg)
        if not inr:
            continue
        e = inr[0]
        last = cb.get(b["id"])
        busy.add(b["id"])
        if last and last[0] == e["id"] and now - last[1] < float(cfg["counter_battery_repeat_s"]):
            continue
        cb[b["id"]] = (e["id"], now)
        out.append({"cmd": "range_attack", "id": b["id"], "target": e["id"], "auto": True})
        if stats is not None:
            k = ("counter-battery fire (smoothbore battery on an enemy battery in range)" if is_smoothbore(b)
                 else "counter-battery fire (rifled battery on an enemy battery in range)")
            stats[k] = stats.get(k, 0) + 1
    return out


def counter_battery_override(state, orders, cfg, stats=None):
    """WIP17 llm_plus: a rifled battery that the model sends against foot or horse farther than
    counter_battery_override_beyond, while an enemy battery is in its range, fires at that battery instead.
    Returns the orders (changed copies, same order)."""
    from battery import is_smoothbore
    cfg = {**DEFAULT_FIRE, **(cfg or {})}
    if not (cfg["enabled"] and cfg.get("counter_battery", True)):
        return orders
    mine, foes = split_units(state)
    live_mine = [u for u in mine if unit_status(u) not in DEAD_STATUSES]
    live_foes = [e for e in foes if unit_status(e) not in DEAD_STATUSES]
    by_mine = {u["id"]: u for u in live_mine}
    by_foe = {e["id"]: e for e in live_foes}
    beyond = float(cfg["counter_battery_override_beyond"])
    out = []
    for o in orders:
        b, t = by_mine.get(o.get("id")), by_foe.get(o.get("target"))
        if (o.get("cmd") in ("range_attack", "attack") and b is not None and t is not None
                and b["kind"] == "Artillery" and not is_smoothbore(b)
                and t["kind"] in ("Infantry", "Cavalry") and _d(b, t) > beyond):
            duel = duel_targets(b, live_foes, live_mine, cfg)
            if duel:
                o = {"cmd": "range_attack", "id": b["id"], "target": duel[0]["id"], "auto": True}
                if stats is not None:
                    k = "rifled battery turned from distant infantry to an enemy battery in range"
                    stats[k] = stats.get(k, 0) + 1
        out.append(o)
    return out


def counter_battery_lines(state, cfg=None, limit=8):
    """WIP17 prompt block: our batteries with an enemy battery in range (both modes)."""
    from battery import is_smoothbore
    cfg = {**DEFAULT_FIRE, **(cfg or {})}
    mine, foes = split_units(state)
    live_mine = [u for u in mine if unit_status(u) not in DEAD_STATUSES]
    live_foes = [e for e in foes if unit_status(e) not in DEAD_STATUSES]
    rows = []
    for b in live_mine:
        if b["kind"] != "Artillery" or unit_status(b) != "":
            continue
        duel = duel_targets(b, live_foes, live_mine, cfg)
        if duel:
            gun = "smoothbore" if is_smoothbore(b) else "rifled"
            rows.append(f"  #{b['id']} ({gun}): " + ", ".join(f"#{e['id']} at {_d(b, e):.0f}" for e in duel[:3]))
    if not rows:
        return []
    return (["COUNTER-BATTERY (enemy batteries in range of your guns, no enemy foot or horse close to them; "
             "a rifled gun silences batteries better than it hurts distant infantry):"] + rows[:limit])


def fire_lines(state, prev_pos, cfg=None):
    """Prompt lines: enemies closing in, and our units whose fire is masked by a friendly unit."""
    mine, foes = split_units(state)
    live_mine = [u for u in mine if unit_status(u) not in DEAD_STATUSES]
    live_foes = [e for e in foes if unit_status(e) not in DEAD_STATUSES]
    lines = []
    th = threats(state, prev_pos, cfg)
    if th:
        lines.append("CLOSING IN (concentrate the fire of every unit in range on these first): "
                     + ", ".join(f"#{e['id']} at {d:.0f}" for d, e in th[:5]))
    masked = []
    for u in live_mine:
        if u["kind"] not in ("Infantry", "Artillery") or unit_status(u) != "":
            continue
        inr = [e for e in live_foes if _d(u, e) <= _rng(u)]
        if not inr:
            continue
        a = masker(u, min(inr, key=lambda e: _d(u, e)), live_mine)
        if a is not None:
            masked.append(f"#{u['id']} by #{a['id']}")
    if masked:
        lines.append("FIRE MASKED (a friendly unit stands in the line of fire; move one of the two sideways): "
                     + "; ".join(masked[:6]))
    return lines
