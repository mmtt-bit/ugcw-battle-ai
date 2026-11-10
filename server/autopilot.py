"""Server-side initiative for the AI commander: engage, charge and choose the artillery ammunition.

In the last recorded battle the model gave 2 orders per turn on average while 4 to 7 infantry
brigades stood 450 to 600 units from the enemy, out of fire range and without orders. A unit that
has received an order is no longer driven by the game's built-in AI, so it stays where it is until
it is told otherwise. This module fills that gap: units that were given no order this turn and are
not already busy get a simple, safe order. Every order it adds is tagged "auto": true so the logs
show what the model decided and what the server added. Switch it off in config.json ("engage").
"""
import math

from battery import is_ready
from relief import is_resting
from equipment import AMMO_MODES, unit_charge_range, unit_range
from prompting import (DEAD_STATUSES, FIRING_KINDS, MELEE_KINDS, needs_rest, nearest, retreat_spot,
                       split_units, threatened_batteries, unit_status)

DEFAULT_ENGAGE = {
    "enabled": True,
    "max_per_turn": 4,          # orders added per turn (advances and shooting orders together), floor...
    "per_turn_share": 0.06,     # ...or this share of your combat units, whichever is larger
    "max_charges": 2,           # charges added per turn, floor...
    "charges_share": 0.03,      # ...or this share of your combat units
    "trigger_distance": 650,    # advance on an enemy this close that is out of fire range
    "reserve_share": 0.2,       # share of the idle brigades that is never sent forward
    "charge_target_morale": 0.5,  # auto-charge only enemies below this morale (or half strength)
    "charge_min_morale": 0.6,
    "charge_min_stamina": 0.5,
    "charge_min_strength": 0.6,   # share of initial men
}
DEFAULT_AMMO = {
    "auto": True,               # the server switches artillery to canister when infantry gets close
    "canister_range": 500,      # the game's own canister range (Rebalance.Methods.GetCanisterRange); used if not reported
    "release_factor": 1.6,      # back to automatic ammunition beyond canister_range * this
}

BUSY_CMDS = ("attack", "range_attack", "charge")


def _share(u):
    return float(u["hp"]) / max(float(u["maxHp"]), 1.0)


def _busy(u, last_cmds, live_ids, pending_moves, foes_by_id):
    """True when the unit already follows an order that should not be disturbed."""
    if u["id"] in (pending_moves or {}):
        return True
    last = (last_cmds or {}).get(u["id"])
    if not last:
        return False
    if is_resting(u, last_cmds):      # pulled back for low morale: leave it alone until it has recovered
        return True
    if last.get("cmd") in BUSY_CMDS and last.get("target") in live_ids:
        return True
    return last.get("cmd") == "hold"   # a deliberate hold (garrison, reserve) is respected


def engage_orders(state, orders, ranges, cfg, last_cmds=None, pending_moves=None, defending=False, stats=None):
    """Orders for units the model left idle: charge a beaten enemy, advance into fire range, shoot."""
    cfg = {**DEFAULT_ENGAGE, **(cfg or {})}
    if not cfg["enabled"]:
        return []
    bump = (lambda key: stats.__setitem__(key, stats.get(key, 0) + 1)) if stats is not None else (lambda key: None)
    mine, foes = split_units(state)
    live = [e for e in foes if unit_status(e) not in DEAD_STATUSES]
    if not live:
        return []
    live_ids = {e["id"] for e in live}
    foes_by_id = {e["id"]: e for e in live}
    ordered = {o["id"] for o in orders}
    fire_default = float(ranges["fire"])
    idle = [u for u in mine
            if u["kind"] in FIRING_KINDS and u["kind"] != "Skirmish" and u["id"] not in ordered
            and unit_status(u) == "" and not needs_rest(u)
            and not _busy(u, last_cmds, live_ids, pending_moves, foes_by_id)]
    if not idle:
        return []
    n_combat = sum(1 for x in mine if x["kind"] in ("Infantry", "Cavalry", "Artillery", "Skirmish"))
    max_turn = max(int(cfg["max_per_turn"]), int(round(float(cfg.get("per_turn_share", 0.0)) * n_combat)))
    max_charges = max(int(cfg["max_charges"]), int(round(float(cfg.get("charges_share", 0.0)) * n_combat)))
    budget = min(max_turn, int(len(idle) * (1.0 - float(cfg["reserve_share"])) + 0.999))
    added, charges = [], 0
    for u in sorted(idle, key=lambda x: (nearest(x, live) or (None, 1e9))[1]):
        if len(added) >= budget:
            break
        near = nearest(u, live)
        if not near:
            continue
        foe, dist = near
        fire = unit_range(u, fire_default)
        in_charge = [e for e in live if math.hypot(e["x"] - u["x"], e["z"] - u["z"]) <= unit_charge_range(u, ranges)]
        beaten = [e for e in in_charge
                  if e["morale"] < float(cfg["charge_target_morale"]) or _share(e) < 0.5]
        if (beaten and charges < max_charges and u["kind"] in MELEE_KINDS
                and u["morale"] >= float(cfg["charge_min_morale"])
                and u["fatigue"] >= float(cfg["charge_min_stamina"])
                and _share(u) >= float(cfg["charge_min_strength"])):
            target = min(beaten, key=lambda e: (e["morale"], _share(e)))
            added.append({"cmd": "charge", "id": u["id"], "target": target["id"], "auto": True})
            charges += 1
            bump("auto charges (idle unit next to a beaten enemy)")
        elif u["kind"] == "Cavalry" and u.get("mount") in (None, "mounted"):
            continue                                   # mounted cavalry only charges: no carbine duels, no advances
        elif dist <= fire:
            added.append({"cmd": "range_attack", "id": u["id"], "target": foe["id"], "auto": True})
            bump("auto range_attack (idle unit in fire range)")
        elif not defending and dist <= float(cfg["trigger_distance"]):
            shaken = [e for e in live if e["morale"] < float(cfg["charge_target_morale"])
                      and math.hypot(e["x"] - u["x"], e["z"] - u["z"]) <= float(cfg["trigger_distance"])]
            target = min(shaken, key=lambda e: math.hypot(e["x"] - u["x"], e["z"] - u["z"])) if shaken else foe
            added.append({"cmd": "attack", "id": u["id"], "target": target["id"], "auto": True})
            bump("auto advances (idle unit just out of fire range)")
    return added


def ammo_orders(state, orders, cfg, stats=None):
    """Switch artillery to canister when enemy infantry or cavalry is close, back to auto when not."""
    cfg = {**DEFAULT_AMMO, **(cfg or {})}
    if not cfg["auto"]:
        return []
    mine, foes = split_units(state)
    live = [e for e in foes if unit_status(e) not in DEAD_STATUSES and e["kind"] in ("Infantry", "Cavalry")]
    try:
        canister = float(state.get("canisterRange") or cfg["canister_range"])
    except (TypeError, ValueError):
        canister = float(cfg["canister_range"])
    chosen = {o["id"] for o in orders if o.get("cmd") == "ammo"}
    out = []
    for u in mine:
        if u["kind"] != "Artillery" or unit_status(u) in DEAD_STATUSES or u["id"] in chosen:
            continue
        mode = u.get("ammoMode")
        if mode not in AMMO_MODES:
            continue          # the plugin does not report the mode: do not guess
        near = nearest(u, live)
        wanted = mode
        if near and near[1] <= canister:
            wanted = "canister"
        elif mode == "canister" and (not near or near[1] > canister * float(cfg["release_factor"])):
            wanted = "auto"
        if wanted != mode:
            out.append({"cmd": "ammo", "id": u["id"], "value": wanted, "auto": True})
            if stats is not None:
                key = f"auto ammunition: {wanted}"
                stats[key] = stats.get(key, 0) + 1
    return out


DEFAULT_GUARD = {
    "enabled": True,       # pull back a battery that stands alone in front of enemy infantry or cavalry
    "min_escape": 150,     # closer than this it is too late to limber up (it fires canister instead)
    "use_fallback": True,  # a ready (unlimbered) battery steps back with fallback and keeps firing
    "fallback_seconds": 15.0,
}


def guard_artillery(state, orders, cfg, terrain=None, pending_moves=None, stats=None):
    """Retreat orders for batteries without cover that an enemy brigade or cavalry could reach.

    Returns (ids whose own order must be dropped, new orders). The orders are tagged "auto".
    """
    cfg = {**DEFAULT_GUARD, **(cfg or {})}
    if not cfg["enabled"]:
        return set(), []
    mine, foes = split_units(state)
    replace, added, planned = set(), [], []
    for b, e, d in threatened_batteries(mine, foes):
        if d <= float(cfg["min_escape"]) or b["id"] in (pending_moves or {}):
            continue
        spot = retreat_spot(b, e, mine, foes, terrain)
        if spot is None:
            continue
        replace.add(b["id"])
        if cfg["use_fallback"] and is_ready(b):
            added.append({"cmd": "fallback", "id": b["id"], "duration": float(cfg["fallback_seconds"]), "auto": True})
            if stats is not None:
                key = "auto artillery fallbacks (battery stays unlimbered)"
                stats[key] = stats.get(key, 0) + 1
            continue
        added.append({"cmd": "move", "id": b["id"], "x": round(spot[0], 1), "z": round(spot[1], 1),
                      "fx": round(e["x"], 1), "fz": round(e["z"], 1), "auto": True})
        if stats is not None:
            key = "auto artillery retreats (battery without cover in front of infantry or cavalry)"
            stats[key] = stats.get(key, 0) + 1
    return replace, added
