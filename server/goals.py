"""Mission goals read from the game, turned round for the AI.

The plugin (MissionGoals.cs) sends "battleGoals": the battle objectives of the mission as the
briefing screen shows them to the human player. A list of entries, each with
  result  "Victory", "Draw" or "Defeat" (always from the human player's point of view),
  or      goals of which at least one must be met,
  and     goals that must all be met,
and for every goal: type, message (the briefing text), state (met right now) and details
(objective name, ratio, condition). The game takes the first entry whose goals are met as the
result of the battle. For the AI the picture is inverted: what makes the player win is what the AI
must prevent, and a player defeat is an AI victory.
"""
AI_RESULT = {"victory": "defeat", "draw": "draw", "defeat": "victory"}
AI_WORDS = {"victory": "THE PLAYER WINS (you lose)", "draw": "THE PLAYER GETS A DRAW (you draw)",
            "defeat": "THE PLAYER LOSES (you win)"}
PLAYER_VERB = {"victory": "WIN", "draw": "DRAW", "defeat": "LOSE"}
CONDITIONS = {"MoreOrEquals": ">=", "LessOrEquals": "<=", "More": ">", "Less": "<",
              "Equals": "=", "NotEqual": "!="}


def _goals(entry, key):
    return [g for g in (entry.get(key) or []) if isinstance(g, dict)]


def entry_met(entry):
    """Are the goals of this entry met? 'or': any one; 'and': all; an empty entry is never met."""
    ors, ands = _goals(entry, "or"), _goals(entry, "and")
    if not ors and not ands:
        return False
    return (not ors or any(g.get("state") for g in ors)) and all(g.get("state") for g in ands)


def player_result(goals):
    """The human player's result according to the goals ('victory', 'draw', 'defeat') or None.

    Like the game, the first entry whose goals are met decides."""
    for entry in goals or []:
        if isinstance(entry, dict) and entry_met(entry):
            return str(entry.get("result", "")).lower() or None
    return None


def ai_outcome(goals):
    """AI outcome from the goals, or None when no entry is met (the goals alone cannot tell)."""
    return AI_RESULT.get(player_result(goals) or "")


def goal_text(g):
    text = str(g.get("message") or "").strip()
    if not text:
        kind = str(g.get("type", "goal"))
        if g.get("objective"):
            text = f"{kind}: {g['objective']}"
        elif "ratio" in g:
            text = f"{kind} {CONDITIONS.get(str(g.get('condition')), g.get('condition', ''))} {g['ratio']}"
        else:
            text = kind
    return text


def _set_text(entry):
    parts = []
    ands, ors = _goals(entry, "and"), _goals(entry, "or")
    fmt = lambda g: f"[{'MET' if g.get('state') else 'not met'}] {goal_text(g)}" + (
        " (hidden in the briefing)" if g.get("hidden") else "")
    if ands:
        parts.append("ALL of: " + "; ".join(fmt(g) for g in ands))
    if ors:
        parts.append("ANY of: " + "; ".join(fmt(g) for g in ors))
    return " | ".join(parts) or "(empty)"


def goals_lines(goals):
    """Prompt lines: the briefing goals inverted for the AI, with their state right now."""
    entries = [e for e in (goals or []) if isinstance(e, dict)]
    if not entries:
        return []
    lines = ["MISSION GOALS (the player's goals: PREVENT them):"]
    for result in ("victory", "draw", "defeat"):
        group = [e for e in entries if str(e.get("result", "")).lower() == result]
        if not group:
            continue
        lines.append(f"- {AI_WORDS[result]} if any of these sets is met:")
        for e in group:
            lines.append("    * " + _set_text(e) + ("   <- MET NOW" if entry_met(e) else ""))
    now = player_result(entries)
    lines.append("  Right now: " + (
        f"the goals say the player would {PLAYER_VERB.get(now, now)} the battle." if now else
        "no set is met yet. Keep it that way for the player and work towards your own."))
    return lines


# ----- strategic plan: which way to win, and so attack or defend --------------------------------
import itertools
import math

PLAN_DEFAULTS = {
    "enabled": True,
    "attack_ratio": 1.25,        # force ratio (overall or around the objective) needed to attack for an objective
    "min_contact_minutes": 20,   # before this, a bad casualty ratio is still recoverable
    "draw_ratio": 0.8,           # force ratio needed to attack for a DRAW (1 point) when a win is out of reach
    "stop_loss_ratio": 1.6,      # men lost in the last 10 min above this times the enemy's: stop-loss
    "stop_loss_min": 100,        # ...and at least this many men lost in those 10 minutes
    "stop_loss_hold_s": 480,     # once triggered, the stop-loss (TRADE) lasts at least this long, then the attack resumes
    "force_stop_loss": False,    # set by the server while a triggered stop-loss is still running
    "attack_by_default": True,   # an objective the player holds and the AI must take = attack, not trade fire
    "min_attack_ratio": 0.7,     # ...unless the force ratio is below this (then build up first)
    "build_up_minutes": 25,      # ...for at most this long in contact: after that the attack goes ahead anyway
    "min_casualties": 300,       # below this many men lost (both sides) a kill ratio means nothing yet
    "recoverable_kd": 0.65,      # estimated kill/death under this after that time = far behind
}


def _atom_key(g):
    if g.get("type") == "CaptureObjectivePoint":
        return ("cap", str(g.get("objective") or goal_text(g)))
    return (str(g.get("type")), g.get("ratio"), g.get("condition"), goal_text(g))


def atoms_of(goals):
    """Distinct goals of the mission: key -> {kind, text, state, ratio}. state True = the PLAYER meets it."""
    atoms = {}
    for e in goals or []:
        for g in _goals(e, "or") + _goals(e, "and"):
            k = _atom_key(g)
            if k not in atoms:
                atoms[k] = {"key": k, "kind": "cap" if k[0] == "cap" else "ratio", "text": goal_text(g),
                            "state": bool(g.get("state")), "ratio": g.get("ratio"),
                            "type": g.get("type"), "condition": g.get("condition")}
    return atoms


def _entry_met_under(entry, assign):
    ors, ands = _goals(entry, "or"), _goals(entry, "and")
    if not ors and not ands:
        return False
    return ((not ors or any(assign[_atom_key(g)] for g in ors))
            and all(assign[_atom_key(g)] for g in ands))


def solve_routes(goals):
    """Minimal sets of goals the AI must keep unmet so that the player cannot win (win routes),
    or cannot win but may draw (draw routes). Worst case: every other goal is met by the player."""
    atoms = atoms_of(goals)
    keys = sorted(atoms, key=str)
    if not keys or len(keys) > 12:
        return atoms, [], []
    entries = [e for e in goals if isinstance(e, dict)]
    win, draw = [], []
    for size in range(0, len(keys) + 1):
        for subset in itertools.combinations(keys, size):
            assign = {k: (k not in subset) for k in keys}
            victory = any(_entry_met_under(e, assign) for e in entries if str(e.get("result")).lower() == "victory")
            drawn = any(_entry_met_under(e, assign) for e in entries if str(e.get("result")).lower() == "draw")
            sset = frozenset(subset)
            if not victory and not drawn and not any(r <= sset for r in win):
                win.append(sset)
            elif not victory and drawn and not any(r <= sset for r in draw) and not any(r <= sset for r in win):
                draw.append(sset)
    return atoms, win, draw


def _objective_for(text, objectives):
    low = str(text).lower()
    best = None
    for o in objectives or []:
        name = str(o.get("name", "")).lower()
        if name and name in low and (best is None or len(name) > len(str(best.get("name", "")))):
            best = o
    return best


def make_plan(goals, state, objectives, kd_est, minutes_in_contact, own_loss=0.0, foe_loss=0.0, cfg=None, trend=None):
    """Choose the AI's route to victory and the posture that goes with it.

    Returns None without goals, else {"mode": "ATTACK"|"DEFEND"|"TRADE", "posture": str, "lines": [...]}.
    Modes: ATTACK = take an objective the player holds; DEFEND = hold what you hold; TRADE = the casualty
    ratio is the problem: fight by fire from good ground, charge only shaken units, avoid assaults.
    """
    cfg = {**PLAN_DEFAULTS, **(cfg or {})}
    if not cfg["enabled"] or not goals:
        return None
    from situation import strength     # local import: situation.py does not import this module
    atoms, win, draw = solve_routes(goals)
    if not atoms or not win:
        return None
    player = state["playerSide"]
    mine = [u for u in state["units"] if u["side"] != player]
    foes = [u for u in state["units"] if u["side"] == player]
    sm, sf = strength(mine), strength(foes)
    overall = sm / sf if sf > 0 else math.inf

    def cap_feasible(atom, thr=None):
        thr = cfg["attack_ratio"] if thr is None else thr
        obj = _objective_for(atom["text"], objectives)
        if obj is None:
            return overall >= thr, None
        r = 800.0
        lm = strength([u for u in mine if math.hypot(u["x"] - obj["x"], u["z"] - obj["z"]) <= r * 2])
        lf = strength([u for u in foes if math.hypot(u["x"] - obj["x"], u["z"] - obj["z"]) <= r])
        local = lm / lf if lf > 0 else math.inf
        return (local >= thr or overall >= thr), obj

    behind_far = (minutes_in_contact >= cfg["min_contact_minutes"] and kd_est < cfg["recoverable_kd"])

    def reduce(route):
        """A lower kill ratio kept unmet implies every higher one is unmet too: show only the lowest."""
        ratios = [k for k in route if atoms[k]["kind"] == "ratio" and isinstance(atoms[k].get("ratio"), (int, float))]
        if len(ratios) < 2:
            return list(route)
        low = min(ratios, key=lambda k: atoms[k]["ratio"])
        return [k for k in route if k not in ratios or k == low]

    def describe(route, thr=None):
        needs, done, hard = [], [], 0
        for k in sorted(reduce(route), key=str):
            a = atoms[k]
            if a["kind"] == "cap":
                if a["state"]:                      # the player holds it: the AI must take it
                    ok, obj = cap_feasible(a, thr)
                    needs.append(("cap", a, obj, ok))
                    hard += 0 if ok else 1
                else:
                    done.append(a)
            else:
                if a["state"] and (own_loss + foe_loss) >= cfg["min_casualties"]:   # met by the player: the AI is behind
                    needs.append(("ratio", a, None, not behind_far))
                    hard += 1 if behind_far else 0
                else:
                    done.append(a)
        return needs, done, hard

    scored = []
    for route in win:
        needs, done, hard = describe(route)
        scored.append(((hard, len(needs)), route, needs, done))
    scored.sort(key=lambda t: t[0])
    _, best, needs, done = scored[0]

    def ratio_need(a):
        r = a.get("ratio")
        try:
            r = float(r)
        except (TypeError, ValueError):
            return a["text"]
        return f"{a['text']} (you must keep your own kill/death above {1.0 / r:.2f})"

    def route_text(route):
        parts = []
        for k in sorted(reduce(route), key=str):
            a = atoms[k]
            if a["kind"] == "cap":
                parts.append("hold: " + a["text"].replace("Hold ", "").strip()
                              + (" [the player holds it now]" if a["state"] else " [done]"))
            else:
                parts.append("keep the player from: " + ratio_need(a) + (" [the player meets it now]" if a["state"] else " [done]"))
        return "; ".join(parts) or "nothing to do beyond staying out of defeat"

    need_ratio = [n for n in needs if n[0] == "ratio"]
    need_cap = [n for n in needs if n[0] == "cap"]
    lines = ["STRATEGIC PLAN:",
             "  Ways for YOU to win (prevent every player victory and draw condition):"]
    for i, (score, route, nd, dn) in enumerate(scored[:3]):
        mark = "  <- CHOSEN" if i == 0 else ""
        lines.append(f"   {chr(65 + i)}. {route_text(route)}{mark}")
    deficit = None
    if need_ratio:
        a = need_ratio[0][1]
        try:
            r = float(a.get("ratio"))
            deficit = max(0.0, own_loss / r - foe_loss)
        except (TypeError, ValueError):
            pass
    fallback = None
    if need_ratio and behind_far and draw:
        # A win on casualties is out of reach: look for a DRAW (1 point instead of 0), which only needs the
        # player's victory conditions to stay unmet (usually: take the objective the player holds).
        dscored = []
        for route in draw:
            nd, dn, hd = describe(route, cfg["draw_ratio"])
            dscored.append(((hd, len(nd)), route, nd, dn))
        dscored.sort(key=lambda t: t[0])
        nd = dscored[0][2]
        caps = [n for n in nd if n[0] == "cap"]
        if caps and not any(n[0] == "ratio" for n in nd) and all(n[3] for n in caps):
            fallback = (dscored[0], caps)
    attack_default = bool(need_cap) and cfg["attack_by_default"] and not fallback and (
        overall >= cfg["min_attack_ratio"] or minutes_in_contact >= cfg["build_up_minutes"] or sf <= 0)
    if fallback:
        caps = fallback[1]
        names = ", ".join((n[2].get("name") if n[2] else n[1]["text"]) for n in caps)
        lines.append(f"  Fallback (a DRAW, 1 point instead of 0): take {names} so that the player does not win; "
                     "the casualty condition then only gives the player a draw.")
        mode = "ATTACK"
        posture = (f"ATTACK for a draw: a win on casualties is out of reach (kill/death {kd_est:.2f}), but taking {names} "
                   "turns a defeat into a draw. Go for it with several brigades together, keep the fire superior on the way, "
                   "wear down steady defenders with charges on shaken units, and keep a reserve.")
    elif attack_default:
        feas = all(n[3] for n in need_cap)
        names = ", ".join((n[2].get("name") if n[2] else n[1]["text"]) for n in need_cap)
        mode = "ATTACK"
        posture = (f"ATTACK to take {names}: the player holds it and you cannot win without it, so you are the attacker "
                   "by default. Write an assault plan (axis, staging area, fixing fire, assault brigades, flank, reserve) "
                   "and carry it out; do not sit in a fire fight for the whole battle. "
                   + ("You have the superiority: attack with several brigades together." if feas else
                      "You are NOT clearly superior: do not attack everywhere; concentrate the best brigades and the "
                      "artillery on one point, pin the rest of the line with fire, and use the flanks and cavalry on "
                      "weak or shaken defenders. ")
                   + "Keep a reserve to relieve broken brigades.")
        if need_ratio:
            posture += (" The casualty condition also matters: favour the trades (artillery on the defenders, "
                        "fire before steel, charges only on shaken units).")
    elif need_ratio:
        mode = "TRADE"
        why = (f"the casualty condition is the problem (estimated kill/death {kd_est:.2f}"
               + (f", you must still inflict about {deficit:.0f} more casualties than you take to reach the line; "
                  "your enemy count only includes units you have seen" if deficit else "")
               + ("; you are FAR behind, every route needs this, so stop feeding brigades into assaults and "
                  "win the exchange of fire" if behind_far else "") + ").")
        posture = ("TRADE: win the casualty race before anything else. Fight by fire from good ground, concentrate "
                   "fire on one enemy unit at a time, use artillery, charge ONLY shaken enemy units, rotate tired "
                   "units, and refuse frontal assaults on steady or fortified units. Do not take objectives "
                   "until the casualty condition is met. " + why)
    elif need_cap:
        feas = all(n[3] for n in need_cap)
        names = ", ".join((n[2].get("name") if n[2] else n[1]["text"]) for n in need_cap)
        if feas:
            mode = "ATTACK"
            posture = (f"ATTACK to take {names}: the route to victory needs it and you have the superiority. "
                       "Advance with several brigades together, pin the enemy with fire, wear a steady unit down "
                       "with sacrificial charges before the main blow, and keep a reserve. Keep an eye on the "
                       "casualty condition: it stays under control only if the trades remain even.")
        else:
            mode = "DEFEND"
            posture = (f"DEFEND for now: the route to victory needs {names} but you do not have the superiority "
                       "to take it. Hold what you own, build local superiority (fresh brigades, artillery), kill "
                       "weak enemy units that come into range, and attack only when the odds are at least "
                       f"{cfg['attack_ratio']:.2f} to 1.")
    else:
        mode = "DEFEND"
        posture = ("DEFEND: every condition for your victory is met right now. Hold the objectives you own, stay "
                   "in good ground with a continuous line, keep the trades at least even, and do not take risks "
                   "that would cost the ratio. Counter-attack only shaken units.")
    stop_loss = False
    if trend is not None:
        t_own, t_foe = trend
        lines.append(f"  TREND (last 10 min): you lost {t_own:.0f} men, the enemy lost {t_foe:.0f} (seen).")
        tripped = bool(cfg.get("force_stop_loss")) or (t_own >= cfg["stop_loss_min"] and t_own > cfg["stop_loss_ratio"] * max(t_foe, 1.0))
        stop_loss = tripped
        if tripped and mode != "TRADE":
            mode = "TRADE"
            posture = ("TRADE (stop-loss): you are losing more than " + f"{cfg['stop_loss_ratio']:.1f}x the enemy's men over the last 10 minutes. "
                       "Stop all advances, rotate out every brigade under 0.6 morale, hold good ground, concentrate fire and "
                       "use artillery until the exchange recovers."
                       + (" The pause is temporary: as soon as the exchange recovers, the attack on the objective resumes." if (fallback or need_cap) else ""))
        elif tripped:
            posture += (" STOP-LOSS: the last 10 minutes cost more than " + f"{cfg['stop_loss_ratio']:.1f}x the enemy's losses: "
                        "no advances, rotate out brigades under 0.6 morale.")
    lines.append(f"  AMBITION: {mode}. " + posture)
    return {"mode": mode, "posture": posture, "lines": lines, "route": [atoms[k]["text"] for k in best],
            "deficit": deficit, "behind_far": behind_far, "stop_loss": stop_loss,
            "targets": [n[2] for n in need_cap if n[2] is not None]}
