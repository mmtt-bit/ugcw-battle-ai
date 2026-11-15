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
    "stop_loss_min": 100,        # ...and at least this many men lost in those 10 minutes (floor)...
    "stop_loss_share": 0.01,     # ...or this share of the AI army (all men that took part), whichever is larger
    "stop_loss_hold_s": 480,     # once triggered, the stop-loss (TRADE) lasts at least this long, then the attack resumes
    "stop_loss_cooldown_s": 600,  # after a pause ends it cannot trip again for this long (0.1.4 WIP7)
    "take_unheld": True,          # an unheld objective the player needs is a target (0.1.4 WIP7)
    "secure_when_superior": True,  # with the numbers, an objective the player's victory needs is taken even when
    "secure_ratio": 1.5,           # the route to a win is a casualty ratio (0.1.4 WIP7)
    "secure_keep_ratio": 1.1,      # ...and stays the target down to this ratio once chosen
    # WIP12 (Thoroughfare Gap, 2026-11-13 15:48): every condition was met at the start, so the plan said DEFEND
    # while 9,324 men faced 1,598 visible at 21 min (5.8 to 1). With this ratio over the enemy seen, an objective
    # the player holds or nobody holds is taken even then.
    "secure_idle_ratio": 2.0,
    "force_stop_loss": False,    # set by the server while a triggered stop-loss is still running
    "stop_loss_min_contact": 5,  # minutes in contact before the stop-loss can trip (losses to unseen fire before
                                 # contact are hidden troops to find, not a fire fight to stop)
    "attack_by_default": True,   # an objective the player holds and the AI must take = attack, not trade fire
    "min_attack_ratio": 0.7,     # ...unless the force ratio is below this (then build up first)
    "build_up_minutes": 25,      # ...for at most this long in contact: after that the attack goes ahead anyway
    "min_casualties": 300,       # floor; the real threshold is the larger of this and min_casualties_share x army
    "min_casualties_share": 0.02,       # below this many men lost (both sides) a kill ratio means nothing yet
    "recoverable_kd": 0.65,      # estimated kill/death under this after that time = far behind
    # 0.1.4 WIP4 (battle of 2026-11-11 15:27: an assault at a force ratio of 0.39 was called off 8 times by the
    # model and put back each time by this plan, which named the attack "by default"):
    "abandon_ratio": 0.5,        # force ratio under which an assault that has not gone in is abandoned for good
    "abandon_ratio_kd_bonus": 0.1,   # ...raised by this much when a casualty ratio is among the mission goals
    "abandon_minute": 20,        # ...checked from this minute of the map on (the server keeps the decision)
    "resume_ratio": 0.8,         # an abandoned assault may be planned again only above this force ratio
    "force_abandon": False,      # set by the server while the assault is abandoned
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
    own_side = mine[0]["side"] if mine else None
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
                    # 0.1.4 WIP7 (battle of 2026-11-12 10:12): "Meeting point" was neutral for 15 minutes while the
                    # South had the numbers; the plan called the condition met and traded fire, the player walked in.
                    # An objective nobody holds that the player needs is taken first, while it is cheap.
                    obj = _objective_for(a["text"], objectives)
                    if obj is not None and cfg.get("take_unheld", True) and obj.get("side") not in (own_side, player):
                        ok, _ = cap_feasible(a, thr)
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
                o = _objective_for(a["text"], objectives)
                unheld = (not a["state"] and o is not None and cfg.get("take_unheld", True)
                          and o.get("side") not in (own_side, player))
                parts.append("hold: " + a["text"].replace("Hold ", "").strip()
                              + (" [the player holds it now]" if a["state"] else
                                 " [nobody holds it: take it before the player does]" if unheld else " [done]"))
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
    has_ratio_goal = any(a["kind"] == "ratio" for a in atoms.values())
    abandon_thr = float(cfg["abandon_ratio"]) + (float(cfg["abandon_ratio_kd_bonus"]) if has_ratio_goal else 0.0)
    abandoned = bool(cfg.get("force_abandon"))
    # (the build-up limit no longer sends a clearly outnumbered army in: under the abandon ratio it keeps building up)
    attack_default = bool(need_cap) and cfg["attack_by_default"] and not fallback and (
        overall >= cfg["min_attack_ratio"] or sf <= 0
        or (minutes_in_contact >= cfg["build_up_minutes"] and overall >= abandon_thr))
    hold_objs, retake_objs = [], []
    # With the numbers, an objective the player's victory needs is taken even when the chosen route is a casualty
    # ratio (see the "secure" branch below)
    secure = []
    idle_superior = (not needs and sf > 0
                     and overall >= float(cfg["secure_keep_ratio"] if cfg.get("secure_latched")
                                          else cfg.get("secure_idle_ratio", 2.0)))
    if (not need_cap and not abandoned and cfg.get("secure_when_superior", True)
            and ((need_ratio and overall >= float(cfg["secure_keep_ratio"] if cfg.get("secure_latched")
                                                   else cfg["secure_ratio"])) or idle_superior)):
        # (once chosen, the objective stays the target down to secure_keep_ratio: the visible ratio moves at every
        # state, and an assault cancelled by the plan going back to TRADE is the worst of both)
        for a in atoms.values():
            if a["kind"] != "cap":
                continue
            obj = _objective_for(a["text"], objectives)
            if obj is None or obj.get("side") == own_side or any(n[2] is obj for n in secure):
                continue
            secure.append(("cap", a, obj, True))
    wanted_cap = bool(need_cap or secure)          # the win needs an objective the player holds (kept for the server's latch)
    if abandoned:
        # The assault is off for good (see the server's latch): the best result left is the one the goals still
        # allow without taking the objective, usually a draw by denying the player his other conditions.
        names = ", ".join((n[2].get("name") if n[2] else n[1]["text"]) for n in need_cap) or "the enemy's objective"
        best_d = None
        for route in draw:
            nd, dn, hd = describe(route, cfg["attack_ratio"])
            key = (sum(1 for n in nd if n[0] == "cap" and not n[3]), len(nd))
            if best_d is None or key < best_d[0]:
                best_d = (key, route, nd)
        mode = "DEFEND"
        posture = (f"DEFEND (assault abandoned): {names} is out of reach (force ratio {overall:.2f}, under "
                   f"{abandon_thr:.2f}). Do not plan, stage or launch any assault on it"
                   f" until the ratio is above {float(cfg['resume_ratio']):.2f}. ")
        if best_d is not None:
            _, d_route, d_needs = best_d
            for k in sorted(reduce(d_route), key=str):
                a = atoms[k]
                if a["kind"] == "cap":
                    obj = _objective_for(a["text"], objectives)
                    if obj is not None:
                        (retake_objs if a["state"] else hold_objs).append(obj)
            posture += ("Best result left: a DRAW, by denying the player every other condition: "
                        + route_text(d_route) + ". ")
            if any(atoms[k]["kind"] == "ratio" for k in d_route):
                posture += ("The casualty condition is one of them: every man counts, no charge on a steady unit, "
                            "no brigade left in a losing fire fight. ")
        else:
            posture += ("The goals leave no draw: limit the losses (in a campaign they are missing in the next "
                        "battle) and keep what you hold. ")
        posture += ("Break contact with the enemy's main body, form one line on good ground (wood's edge, ridge, "
                    "fortifications) that covers the objectives you hold, batteries behind it and wagons close; "
                    "fire from cover, counter-attack only shaken or isolated units, rotate early.")
        if retake_objs:
            posture += (" Retake " + ", ".join(str(o.get("name")) for o in retake_objs)
                        + " only when undefended or weakly held (cavalry or one fresh brigade, ONTO the point).")
        need_cap = []                                  # no assault target: the assault code stands down
        lines = [l.replace("  <- CHOSEN", "  <- ABANDONED (out of reach)") for l in lines]
    elif fallback:
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
    elif secure:
        # 0.1.4 WIP7 (battle of 2026-11-12 10:12): the only route to a win was a casualty ratio, so the plan
        # traded fire with "do not take objectives", at 2 to 4 times the enemy's visible strength, while the
        # player walked onto the objective his victory needed. With the numbers, take it: it denies the player's
        # victory (a draw at worst), and an attack with the numbers is also the cheapest way to inflict losses.
        need_cap = secure
        names = ", ".join(n[2].get("name") for n in secure)
        mode = "ATTACK"
        posture = (f"ATTACK to secure {names}: you have the numbers (force ratio {overall:.2f}) and the player's "
                   "victory needs it. Take it now, before the player is set on it: an assault group of at least "
                   "1.5 times the defenders' strength, coming from two sides at once, the rest of the line firing "
                   "from cover. Holding it denies the player's victory (a draw at worst); the casualty condition "
                   "is then won by fire from the objective and by captures.")
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
    hold_launch = False
    if trend is not None:
        t_own, t_foe = trend
        lines.append(f"  TREND (last 10 min): you lost {t_own:.0f} men, the enemy lost {t_foe:.0f} (seen).")
        in_fight = minutes_in_contact >= cfg.get("stop_loss_min_contact", 5) and t_foe > 0
        # a pause that just ended cannot trip again at once (cooldown, set by the server): in the battle of
        # 2026-11-12 10:12 it re-tripped at every state for 107 minutes and the assault never went in
        tripped = bool(cfg.get("force_stop_loss")) or (not cfg.get("stop_loss_cooldown") and in_fight
                                                       and t_own >= cfg["stop_loss_min"]
                                                       and t_own > cfg["stop_loss_ratio"] * max(t_foe, 1.0))
        stop_loss = tripped
        if tripped and mode == "ATTACK":
            # An attack keeps its plan: the assault group goes on staging, only its launch waits for the pause.
            hold_launch = True
            posture += (" STOP-LOSS PAUSE: the last 10 minutes cost more than " + f"{cfg['stop_loss_ratio']:.1f}x the enemy's "
                        "losses. Keep staging the assault group out of fire and at full strength, rotate out brigades under "
                        "0.6 morale, win the fire fight with the artillery; the launch waits for the pause to end (a few "
                        "minutes). Never use the pause as a reason to stop preparing the attack.")
        elif tripped and mode != "TRADE" and not abandoned:
            mode = "TRADE"
            posture = ("TRADE (stop-loss): you are losing more than " + f"{cfg['stop_loss_ratio']:.1f}x the enemy's men over the last 10 minutes. "
                       "Stop all advances, rotate out every brigade under 0.6 morale, hold good ground, concentrate fire and "
                       "use artillery until the exchange recovers."
                       + (" The pause is temporary: as soon as the exchange recovers, the attack on the objective resumes." if (fallback or need_cap) else ""))
        elif tripped:
            posture += (" STOP-LOSS: the last 10 minutes cost more than " + f"{cfg['stop_loss_ratio']:.1f}x the enemy's losses: "
                        "no advances, rotate out brigades under 0.6 morale.")
    if has_ratio_goal and (mode != "ATTACK" or abandoned) and (stop_loss or deficit or behind_far):
        posture += (" WOODS: the casualties count and you are losing the exchange: fight only from woods, wheat or "
                    "works; brigades in the open step back to the nearest wood's edge that keeps the enemy in range "
                    "(the server does it), let the enemy cross the open ground, no attack out of the woods except "
                    "on a shaken unit. Keep one brigade on an objective you must hold.")
    lines.append(f"  AMBITION: {mode}. " + posture)
    return {"mode": mode, "posture": posture, "lines": lines, "route": [atoms[k]["text"] for k in best],
            "deficit": deficit, "behind_far": behind_far, "stop_loss": stop_loss, "hold_launch": hold_launch,
            "targets": [n[2] for n in need_cap if n[2] is not None],
            "overall": overall, "abandon_ratio": abandon_thr, "abandoned": abandoned, "need_cap": wanted_cap,
            "kd_goal": has_ratio_goal, "kd": kd_est, "secure": bool(secure),
            "hold": hold_objs, "retake": retake_objs}
