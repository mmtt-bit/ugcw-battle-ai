"""Perk effects read from the J&P Rebalance bonus files (<Kind>PerksBonuses.txt).

File format, one perk per line:   PerkName, Stat|value|*|Target, Stat|value|*|Target, ...
The plugin reports each brigade's perks by these same internal names (e.g. "Discipline_training_inf").
The same name can have different effects per unit kind (Discipline_training_inf for infantry is not the
skirmishers' one), so the table of the unit's own kind is used first.

Assumed meaning (from the Rebalance data): "*" multiplies the stat, so ".3" is +30 % and "-.05" is -5 %.
The last field is the unit kind the effect applies to ("All", or e.g. "Skirmish" = only while dismounted).
RotationSpeed is how fast a unit pivots to change its firing angle; CommandRadius is the radius in which a
general's (corps) bonuses reach his brigades.
Reload is a reload TIME: a negative value means faster reloading, a positive one slower. *DamageMoraleImpact
is the morale lost when hit: negative is better. Cover, Spotting, Stealth, EffectiveRange, MoveSpeed,
RotationSpeed, Accuracy, ChargeDamage, SolidAndShellDamage, CanisterDamage, Experience, CommandRadius and
DetachedSize: positive is better.

Point config.json "perks.folder" at a copy of the mod's files (the game keeps them in <game>/Mod/Rebalance/Data/)
to follow another Rebalance version.
"""
import os
import re

KIND_FILES = {
    "Infantry": "InfantryPerksBonuses.txt",
    "Skirmish": "SkirmisherPerksBonuses.txt",
    "Artillery": "ArtilleryPerksBonuses.txt",
    "Cavalry": "CavalryPerksBonuses.txt",
    "General": "CorpsPerksBonuses.txt",
}

STAT_WORDS = {
    "Accuracy": "accuracy",
    "Reload": "reload time",
    "EffectiveRange": "range",
    "Cover": "cover bonus",
    "Spotting": "spotting",
    "Stealth": "stealth",
    "MoveSpeed": "speed",
    "RotationSpeed": "pivot speed (to change the firing angle)",
    "ChargeDamage": "charge damage",
    "MeleeDamageMoraleImpact": "morale loss in melee",
    "SmallArmsDamageMoraleImpact": "morale loss under fire",
    "SolidAndShellDamage": "roundshot/shell damage",
    "CanisterDamage": "canister damage",
    "Experience": "experience gain",
    "CommandRadius": "command radius (reach of the general's bonuses)",
    "DetachedSize": "detached skirmisher size",
}

# stats where a negative value is the good direction
LOWER_IS_BETTER = {"Reload", "MeleeDamageMoraleImpact", "SmallArmsDamageMoraleImpact"}

# roles a perk can strengthen: stat -> role
ROLE_OF_STAT = {
    "Accuracy": "fire", "Reload": "fire", "EffectiveRange": "fire",
    "SolidAndShellDamage": "fire", "CanisterDamage": "close-range guns",
    "ChargeDamage": "assault", "MeleeDamageMoraleImpact": "assault",
    "SmallArmsDamageMoraleImpact": "steady",
    "Spotting": "scout", "Stealth": "scout",
    "MoveSpeed": "mobile", "RotationSpeed": "flexible",
    "CommandRadius": "command",
    "Cover": "cover",
}

_TABLES = {}       # kind -> {perk name -> [(stat, value, target)]}
_SOURCE = ""


def parse(text):
    """{perk name: [(stat, value, target), ...]} from the content of a bonus file."""
    table = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("//"):
            continue
        parts = [p.strip() for p in line.split(",") if p.strip()]
        name, effects = parts[0], []
        for p in parts[1:]:
            bits = p.split("|")
            if len(bits) < 2:
                continue
            try:
                target = bits[3].strip() if len(bits) > 3 and bits[3].strip() else "All"
                effects.append((bits[0].strip(), float(bits[1]), target))
            except ValueError:
                continue
        table[name] = effects
    return table


def load(folder, source=""):
    """Load every <Kind>PerksBonuses.txt found in `folder` (relative to the server folder). Returns the kinds."""
    global _TABLES, _SOURCE
    _TABLES, _SOURCE = {}, source or os.path.basename(os.path.normpath(folder or ""))
    if not folder or not os.path.isdir(folder):
        return []
    for kind, fname in KIND_FILES.items():
        path = os.path.join(folder, fname)
        if os.path.isfile(path):
            with open(path, encoding="utf-8-sig", errors="replace") as f:
                _TABLES[kind] = parse(f.read())
    return sorted(_TABLES)


def loaded():
    return bool(_TABLES)


def effects_of(kind, perk):
    """Effects of a perk for a unit kind: its own kind's table first, then any table that knows the name."""
    own = _TABLES.get(kind, {})
    if perk in own:
        return own[perk]
    for table in _TABLES.values():
        if perk in table:
            return table[perk]
    return None


def _applies(kind, target):
    return target in ("All", "", None) or target == kind


def _effect_text(stat, value, target="All", table_kind=None):
    word = STAT_WORDS.get(stat, re.sub(r"(?<=[a-z])(?=[A-Z])", " ", stat).lower())
    pct = value * 100.0
    txt = f"{word} {pct:+.0f}%"
    if stat == "Reload":
        txt += " (faster)" if value < 0 else " (slower)"
    if target not in ("All", "", None):
        if table_kind == "Cavalry" and target == "Skirmish":
            txt += " (dismounted only)"
        elif table_kind == "General":
            txt += " (on " + {"Skirmish": "skirmishers"}.get(target, target.lower()) + ")"
        else:
            txt += f" ({target} only)"
    return txt


def describe(effects, table_kind=None):
    return ", ".join(_effect_text(*e, table_kind=table_kind) for e in effects)


def roles(kind, perks):
    """Roles the unit's perks strengthen, strongest first (e.g. ['assault', 'fire'])."""
    score = {}
    for p in perks or []:
        for stat, value, target in effects_of(kind, str(p)) or []:
            role = ROLE_OF_STAT.get(stat)
            if not role or not _applies(kind, target):
                continue
            good = -value if stat in LOWER_IS_BETTER else value
            if good > 0:
                score[role] = score.get(role, 0.0) + good
    return [r for r, _ in sorted(score.items(), key=lambda kv: -kv[1])]


def role_score(u, role):
    """How much the unit's perks strengthen a role (0 when none or no tables loaded)."""
    total = 0.0
    for p in u.get("perks") or []:
        for stat, value, target in effects_of(u.get("kind"), str(p)) or []:
            if ROLE_OF_STAT.get(stat) == role and _applies(u.get("kind"), target):
                total += -value if stat in LOWER_IS_BETTER else value
    return total


def prompt_section(kinds_present=None):
    """The PERKS block of the system prompt: what every perk does, per unit kind."""
    if not _TABLES:
        return ""
    lines = [f"PERKS ({_SOURCE}): what each perk does, per unit kind. Reload is a reload time (negative = faster); "
             "morale loss: negative = steadier; pivot speed = how fast the unit turns to a new firing angle; "
             "command radius = how far a general's bonuses reach his brigades. Use them to give each brigade the job "
             "its perks make it good at."]
    label = {"General": "Generals (corps perks, apply to the units they command)"}
    for kind in ("Infantry", "Skirmish", "Cavalry", "Artillery", "General"):
        table = _TABLES.get(kind)
        if not table or (kinds_present is not None and kind not in kinds_present and kind != "General"):
            continue
        lines.append(f"- {label.get(kind, kind)}:")
        for name, effects in table.items():
            if effects:
                lines.append(f"  {name}: {describe(effects, kind)}")
    missing = [k for k in ("Infantry", "Skirmish", "Cavalry", "Artillery") if k not in _TABLES]
    if missing:
        lines.append(f"  (No bonus file for: {', '.join(missing)}; judge those perks by their names.)")
    return "\n".join(lines)
