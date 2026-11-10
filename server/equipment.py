"""Equipment, veterancy (stars), perks and ammunition of units, turned into short prompt text.

The plugin reports, for every unit (optional fields, an old plugin simply omits them):
  weapon  asset name of the weapon, for example "rifle_Mississippi_1841_RF"
  range   current effective firing range in game units (changes with the ammunition mode)
  stars   veterancy (0 to 5) and "perks": names of the talents the brigade has unlocked
  ammo    share of ammunition left (0 to 1)
  ammoMode  artillery only: "auto", "mixed" or "canister"
"""
import math
import re

import perks as perks_mod

AMMO_MODES = ("auto", "mixed", "canister")
MIN_RANGE, MAX_RANGE = 100.0, 3000.0     # ignore absurd values reported by the game

# Words in a weapon asset name that tell what kind of weapon it is.
BREECH_WORDS = ("sharps", "spencer", "henry", "burnside", "maynard", "gallagher", "colt", "revolving")


def _words(text):
    """'rifle_Mississippi_1841_RF' / 'PerkSharpshooter' -> 'rifle Mississippi 1841 RF'."""
    text = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", str(text).replace("_", " "))
    return re.sub(r"\s+", " ", text).strip()


def weapon_label(name):
    """Readable weapon name with its bore type: 'rifle Mississippi 1841 (rifled)'."""
    if not name:
        return ""
    parts = str(name).split("_")
    tags = []
    if parts and parts[-1].upper() == "SB":
        parts = parts[:-1]
        tags.append("smoothbore")
    elif parts and parts[-1].upper() == "RF":
        parts = parts[:-1]
        tags.append("rifled")
    if any(w in str(name).lower() for w in BREECH_WORDS):
        tags.append("breech-loader or repeater")
    label = _words(" ".join(parts))
    return f"{label} ({', '.join(tags)})" if tags else label


def unit_range(u, fallback):
    """Firing range of this unit: the value reported by the game, else the configured one."""
    try:
        r = float(u.get("range"))
    except (TypeError, ValueError):
        return float(fallback)
    return r if MIN_RANGE <= r <= MAX_RANGE else float(fallback)


def unit_charge_range(u, ranges):
    """Charge range of this unit as reported by the game (UnitModel.chargeRange), else the configured one."""
    fallback = float(ranges["charge"])
    if not ranges.get("use_unit_charge", True):
        return fallback
    try:
        r = float(u.get("chargeRange"))
    except (TypeError, ValueError):
        return fallback
    return r if 50.0 <= r <= 1500.0 else fallback


def unit_width(u, base=70.0):
    """Width (frontage) of the unit in game units: the value the game reports (the size of its line formation),
    else an estimate from its full strength. Brigade sizes differ a lot (Rebalance: up to 2500 men, or 6000 with
    the very large size), and a wide brigade needs more room in the line."""
    try:
        w = float(u.get("width"))
        if 20.0 <= w <= 1500.0:
            return w
    except (TypeError, ValueError):
        pass
    men = max(float(u.get("maxHp") or 0.0), 1.0)
    return min(max(base, base * math.sqrt(men / 1500.0)), 3.0 * base)


def perks_list(u):
    perks = u.get("perks")
    if not isinstance(perks, list):
        return []
    return [_words(p) for p in perks if p]


def _num(u, key, fmt):
    try:
        return fmt.format(float(u[key]))
    except (KeyError, TypeError, ValueError):
        return None


def equipment_static(u):
    """The part of the equipment that does not change during a battle (weapon, stars, perks, charge range,
    spotting). The range is not in it: it was seen to change during a battle."""
    bits = []
    label = weapon_label(u.get("weapon"))
    if label:
        bits.append(label)
    if u.get("stars") is not None:
        bits.append(f"{int(u['stars'])} star" + ("" if int(u["stars"]) == 1 else "s"))
    if u.get("chargeRange") is not None and u.get("kind") in ("Infantry", "Cavalry", "Skirmish"):
        t = _num(u, "chargeRange", "charge range {:.0f}")
        if t:
            bits.append(t)
    if u.get("spotting") is not None:
        t = _num(u, "spotting", "sees {:.0f}")
        if t:
            bits.append(t)
    raw_perks = [str(p) for p in (u.get("perks") or []) if p]
    if raw_perks:
        if perks_mod.loaded():
            # the internal names, as in the PERKS block of the system prompt, plus the roles they strengthen
            bits.append("perks: " + ", ".join(raw_perks))
            roles = perks_mod.roles(u.get("kind"), raw_perks)
            if roles:
                bits.append("perk roles: " + ", ".join(roles[:3]))
        else:
            bits.append("perks: " + ", ".join(perks_list(u)))
    return "; ".join(bits)


def equipment_dynamic(u):
    """The part that changes from turn to turn: wagon stock, artillery range and state, ammunition, width."""
    bits = []
    if u.get("supplyStock") is not None:
        t = _num(u, "supplyStock", "x")
        if t:
            bits.append(f"supply stock {float(u['supplyStock']) * 100:.0f}%")
    if "range" in u:                      # changes in battle (ammunition mode, conditions)
        bits.append(f"range {unit_range(u, 0):.0f}")
    if u.get("width") is not None and u.get("kind") in ("Infantry", "Cavalry"):
        t = _num(u, "width", "width {:.0f}")
        if t:
            bits.append(t)
    if u.get("mount") and u["mount"] != "mounted":
        bits.append({"mounted": "mounted", "dismounted": "DISMOUNTED", "dismounting": "dismounting",
                     "mounting": "mounting"}.get(str(u["mount"]), str(u["mount"])))
    if u.get("mount") == "mounted" and u.get("canDismount") is False:
        bits.append("cannot dismount")
    if u.get("limber"):
        bits.append({"ready": "ready to fire", "packed": "PACKED (limbered)", "packing": "packing up",
                     "unpacking": "unlimbering"}.get(str(u["limber"]), str(u["limber"])))
    if u.get("ammoMode") in AMMO_MODES and u["ammoMode"] != "auto":
        bits.append(f"ammo mode {u['ammoMode']}")          # "auto" is the normal mode: not written
    if u.get("ammo") is not None:
        t = _num(u, "ammo", "x")
        if t and float(u["ammo"]) < 0.995:
            bits.append(f"ammo {float(u['ammo']) * 100:.0f}%")   # full ammunition: not written
    return "; ".join(bits)


def equipment_text(u, roster=None):
    """Compact 'equipment' cell for the unit tables; empty when the plugin reports nothing.
    With `roster` (unit id -> fixed equipment already given in the system prompt) a unit whose fixed part
    is unchanged only shows its changing part, which saves tokens every turn."""
    static, dynamic = equipment_static(u), equipment_dynamic(u)
    if roster is not None and u.get("id") in roster:
        return dynamic           # fixed part in the roster of the system prompt (a changed charge range included)
    return "; ".join(b for b in (static, dynamic) if b)


def equipment_enemy(u):
    """Short equipment of an enemy unit, written every turn: bore of the weapon, stars, perks, and the changing
    part (range, width, ammunition...). Weapon model names and charge ranges are left out to save tokens."""
    bits = []
    label = weapon_label(u.get("weapon"))
    if label:
        kind = label.split(" ")[0]                     # rifle / musket / carbine / gun...
        tag = label[label.find("(") + 1:label.rfind(")")] if "(" in label else ""
        bits.append(kind + (f" ({tag})" if tag else ""))
    if u.get("stars"):
        bits.append(f"{int(u['stars'])} star" + ("" if int(u["stars"]) == 1 else "s"))
    raw_perks = [str(p) for p in (u.get("perks") or []) if p]
    if raw_perks:
        bits.append("perks: " + ", ".join(raw_perks))
    dynamic = equipment_dynamic(u)
    return "; ".join(b for b in bits + ([dynamic] if dynamic else []) if b)


def roster_lines(units):
    """One line per unit for the YOUR BRIGADES block of the system prompt."""
    out = []
    for u in units:
        static = equipment_static(u)
        if static:
            out.append(f"{u['id']} {u['name']} ({u['kind']}): {static}")
    return out
