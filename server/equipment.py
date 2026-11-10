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
    perks = perks_list(u)
    if perks:
        bits.append("perks: " + ", ".join(perks))
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
    if u.get("limber"):
        bits.append({"ready": "ready to fire", "packed": "PACKED (limbered)", "packing": "packing up",
                     "unpacking": "unlimbering"}.get(str(u["limber"]), str(u["limber"])))
    if u.get("ammoMode") in AMMO_MODES:
        bits.append(f"ammo mode {u['ammoMode']}")
    if u.get("ammo") is not None:
        t = _num(u, "ammo", "x")
        if t:
            bits.append(f"ammo {float(u['ammo']) * 100:.0f}%")
    return "; ".join(bits)


def equipment_text(u, roster=None):
    """Compact 'equipment' cell for the unit tables; empty when the plugin reports nothing.
    With `roster` (unit id -> fixed equipment already given in the system prompt) a unit whose fixed part
    is unchanged only shows its changing part, which saves tokens every turn."""
    static, dynamic = equipment_static(u), equipment_dynamic(u)
    if roster is not None and static and roster.get(u.get("id")) == static:
        return dynamic
    return "; ".join(b for b in (static, dynamic) if b)


def roster_lines(units):
    """One line per unit for the YOUR BRIGADES block of the system prompt."""
    out = []
    for u in units:
        static = equipment_static(u)
        if static:
            out.append(f"{u['id']} {u['name']} ({u['kind']}): {static}")
    return out
