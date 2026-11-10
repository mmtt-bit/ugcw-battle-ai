"""Force balance and objective ownership, turned into prompt lines for the AI commander.

The AI is told, for the whole army and for each objective, whether it outnumbers the enemy or
not, and what that means: attack when stronger, defend when weaker (thresholds in config.json,
"posture"). Only the enemy units the AI currently sees are counted (fog of war), so the enemy
figure is a lower bound.
"""
import math

# Share of the men that counts, per unit kind (artillery gunners are few and do not hold ground).
WEIGHT = {"Infantry": 1.0, "Cavalry": 1.0, "Skirmish": 0.5}
DEAD = ("routing", "shattered", "captured")

DEFAULT_POSTURE = {
    "enabled": True,
    "attack_ratio": 1.25,   # your strength / enemy strength at or above this: attack
    "defend_ratio": 0.80,   # at or below this: defend
    "local_radius": 800,    # units around an objective counted as "there"
}


def strength(units):
    """Fighting strength: men weighted by kind and by morale (a shaken unit counts for less)."""
    total = 0.0
    for u in units:
        w = WEIGHT.get(u["kind"])
        if w is None or str(u.get("status") or "") in DEAD:
            continue
        total += float(u["hp"]) * w * (0.5 + 0.5 * float(u.get("morale", 1.0)))
    return total


def _ratio(a, b):
    if b <= 0:
        return math.inf if a > 0 else 1.0
    return a / b


def _fmt_ratio(r):
    return "no enemy seen" if math.isinf(r) else f"{r:.2f}"


def owner(obj, ai_side, player_side):
    side = str(obj.get("side", ""))
    if side == ai_side:
        return "OURS"
    if side == player_side:
        return "ENEMY"
    return "UNHELD"


def objective_score(objectives, mine, foes, ai_side, player, cfg):
    """Who holds more objectives and victory points, and the best enemy objective to retake."""
    if not objectives:
        return [], None
    radius = float(cfg["local_radius"])
    own = [o for o in objectives if owner(o, ai_side, player) == "OURS"]
    enemy = [o for o in objectives if owner(o, ai_side, player) == "ENEMY"]
    free = [o for o in objectives if owner(o, ai_side, player) == "UNHELD"]
    vp = lambda lst: sum(o.get("victoryPoints") or 0 for o in lst)
    mine_vp, foe_vp = vp(own), vp(enemy)
    if mine_vp > foe_vp or (mine_vp == foe_vp and len(own) > len(enemy)):
        verdict = "WINNING"
    elif mine_vp < foe_vp or len(own) < len(enemy):
        verdict = "LOSING"
    else:
        verdict = "TIED"
    text = (f"OBJECTIVE SCORE: {verdict}. You hold {len(own)} of {len(objectives)} objectives "
            f"({mine_vp} VP), the enemy holds {len(enemy)} ({foe_vp} VP), {len(free)} unheld.")
    retake = None
    if verdict != "WINNING":
        best = None
        for o in enemy + free:
            lm = strength([u for u in mine if math.hypot(u["x"] - o["x"], u["z"] - o["z"]) <= radius * 2])
            lf = strength([u for u in foes if math.hypot(u["x"] - o["x"], u["z"] - o["z"]) <= radius])
            key = (_ratio(lm, lf) if lm > 0 else 0.0, o.get("victoryPoints") or 0)
            if best is None or key > best[0]:
                best = (key, o)
        if best:
            o = best[1]
            retake = o
            text += (f" RETAKE TARGET: {o.get('name', '?')} at {o['x']:.0f},{o['z']:.0f} "
                     f"(best local odds among the objectives you do not hold).")
    return [text], retake


def situation_lines(state, objectives, stale=False, cfg=None, posture_override=None):
    """Prompt lines: force balance with a posture, then one line per objective with advice."""
    cfg = {**DEFAULT_POSTURE, **(cfg or {})}
    if not cfg["enabled"]:
        return []
    player = state["playerSide"]
    mine = [u for u in state["units"] if u["side"] != player]
    foes = [u for u in state["units"] if u["side"] == player]
    if not mine:
        return []
    ai_side = mine[0]["side"]
    mine_s, foes_s = strength(mine), strength(foes)
    ratio = _ratio(mine_s, foes_s)
    if ratio >= cfg["attack_ratio"]:
        posture = ("ATTACK: you outnumber the enemy. Advance, take enemy and unheld objectives, "
                   "and charge shaken units.")
    elif ratio <= cfg["defend_ratio"]:
        posture = ("DEFEND: you are outnumbered. Hold the objectives you own, fight from good "
                   "terrain with a continuous line, let the enemy come to you, and charge only "
                   "when it is in charge range and shaken. Do not attack objectives held by a stronger force.")
    else:
        posture = ("BALANCED: strengths are close. Secure unheld objectives you can reach first, "
                   "keep the line and look for a weak enemy unit or flank to win local superiority.")
    if posture_override:
        posture = posture_override
    score_lines, retake = objective_score(objectives, mine, foes, ai_side, player, cfg)
    if retake and ratio <= cfg["defend_ratio"] and not posture_override:
        posture += (" BUT you are losing the objective count: defending alone cannot win. "
                    "Also retake the target below with the units you can spare.")
    lines = score_lines + [f"FORCE BALANCE: your strength {mine_s:.0f} vs visible enemy {foes_s:.0f} "
             f"(ratio {_fmt_ratio(ratio)}; infantry, cavalry and half-weight skirmishers, weighted by "
             f"morale; unseen enemy units are not counted). Posture: {posture}"]
    if not objectives:
        return lines
    radius = float(cfg["local_radius"])
    lines.append("OBJECTIVES (name | x,z | owner | victory points | your nearest unit | "
                 "forces within " + f"{radius:.0f}" + " units: yours vs enemy | advice)"
                 + (" - owners are as at the start of the battle:" if stale else ":"))
    for o in objectives:
        ox, oz = o["x"], o["z"]
        near_m = [u for u in mine if math.hypot(u["x"] - ox, u["z"] - oz) <= radius]
        near_f = [u for u in foes if math.hypot(u["x"] - ox, u["z"] - oz) <= radius]
        lm, lf = strength(near_m), strength(near_f)
        lr = _ratio(lm, lf)
        who = owner(o, ai_side, player)
        dists = [math.hypot(u["x"] - ox, u["z"] - oz) for u in mine if u["kind"] != "General"]
        nearest = f"{min(dists):.0f}" if dists else "-"
        if who == "OURS":
            if lf > 0 and lr < 1.0:
                advice = "DEFEND: threatened, reinforce it now"
            elif lf > 0:
                advice = "HOLD: enemy nearby, keep a garrison"
            else:
                advice = "HOLD: keep a small garrison"
        else:
            if lf == 0 and lm > 0:
                advice = "TAKE: nobody is defending it, move onto it"
            elif lr >= cfg["attack_ratio"]:
                advice = "ATTACK: local superiority"
            elif lr <= cfg["defend_ratio"] and lf > 0:
                advice = "AVOID: outnumbered there, reinforce or take another one first"
            elif lm == 0 and lf == 0:
                advice = ("TAKE: send units" if ratio > cfg["defend_ratio"]
                          else "SECURE only if safe: you are outnumbered overall")
            else:
                advice = "CONTEST: bring more units before attacking"
        lines.append(f"- {o.get('name', '?')} | {ox:.0f},{oz:.0f} | {who} | {o.get('victoryPoints', 0)} VP | "
                     f"{nearest} | {lm:.0f} vs {lf:.0f} | {advice}")
    return lines


def stalemate_lines(state, objectives, since, cfg=None):
    """After a long time without any objective changing hands, tell the AI to force the issue.

    since: minutes of battle time since the last change of owner (or since the first contact).
    Only when the AI is not already winning the objective count.
    """
    cfg = {**DEFAULT_POSTURE, **(cfg or {})}
    minutes_limit = float(cfg.get("stalemate_minutes", 20))
    if not objectives or since < minutes_limit:
        return []
    player = state["playerSide"]
    mine = [u for u in state["units"] if u["side"] != player]
    foes = [u for u in state["units"] if u["side"] == player]
    if not mine:
        return []
    ai_side = mine[0]["side"]
    score, retake = objective_score(objectives, mine, foes, ai_side, player, cfg)
    if retake is None or not score or "WINNING" in score[0]:
        return []
    ox, oz = retake["x"], retake["z"]
    fresh = [u for u in mine
             if u["kind"] == "Infantry" and str(u.get("status") or "") == ""
             and u["morale"] >= 0.7 and u["hp"] / max(u["maxHp"], 1.0) >= 0.6 and u["fatigue"] >= 0.6]
    fresh.sort(key=lambda u: math.hypot(u["x"] - ox, u["z"] - oz))
    guns = [u for u in mine if u["kind"] == "Artillery" and str(u.get("status") or "") == ""]
    guns.sort(key=lambda u: math.hypot(u["x"] - ox, u["z"] - oz))
    lines = [f"STALEMATE: no objective has changed hands for {since:.0f} minutes and you do not lead the "
             f"objective count. Waiting at long range will lose the battle. Launch an assault on "
             f"{retake.get('name', '?')} at {ox:.0f},{oz:.0f} now: pin the enemy with fire, then attack "
             "with several fresh brigades together, one on a flank if you can."]
    if fresh:
        lines.append("  Fresh brigades for the assault (nearest first): " + ", ".join(
            f"{u['name']} (#{u['id']}, {u['hp']:.0f} men, morale {u['morale']:.2f})" for u in fresh[:4]))
    if guns:
        lines.append("  Batteries to support it: " + ", ".join(f"{u['name']} (#{u['id']})" for u in guns[:3]))
    return lines
