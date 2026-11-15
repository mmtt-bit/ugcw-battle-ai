"""Battle report, score and kill/death statistics for the AI commander.

The report is built from the state messages the game sends during the battle and from the
"battle_end" message sent by the plugin when the game announces the mission result.

Scoring (configurable in config.json, "scoring"): victory = 3 points, draw = 1, defeat = 0.
Kill/death uses men lost: our own losses are exact; enemy losses are only counted while the enemy
unit is visible to us (fog of war), so the enemy figure is a lower bound.
"""
import json
import os
import time

from goals import ai_outcome

COMBAT_KINDS = ("Infantry", "Cavalry", "Artillery", "Skirmish")
BROKEN = ("shattered", "captured")        # statuses meaning the unit is out of the battle
DEFAULT_SCORING = {"victory": 3, "draw": 1, "defeat": 0, "min_casualties": 25}
SCOREBOARD = os.path.join("logs", "scoreboard.json")
REPORT_DIR = "reports"


def _status(u):
    return str(u.get("status") or "")


def player_result_to_ai(result):
    """Map the game's result text (from the human player's point of view) to the AI outcome."""
    text = str(result or "").lower()
    if "victory" in text or "win" in text:
        return "defeat"      # the human won, so the AI lost
    if "defeat" in text or "lose" in text or "loss" in text:
        return "victory"
    if "draw" in text or "tie" in text:
        return "draw"
    return None


def player_rule_outcome(obj, own_loss, foe_loss, rule):
    """AI outcome ("victory", "draw", "defeat") and a short explanation, from the human player's
    winning conditions copied from the mission briefing (config "mission" > "player_rule").

    rule keys: hold_all (the player wins by holding every objective, default true), hold_min (with
    this many objectives the player wins if it also inflicts casualty_ratio times the AI's
    casualties; default 1), casualty_ratio (default 1.05), draw_ratio (default 1.10: the player
    inflicts that much more but holds nothing: a draw).
    The enemy losses are only counted while the AI sees them, so the casualty ratio shown here
    is slightly flattering for the player.
    """
    total = obj["ai"] + obj["player"] + obj["unheld"]
    ratio = own_loss / max(foe_loss, 1.0)          # casualties the player inflicted / suffered
    hold_min = int(rule.get("hold_min", 1))
    need = float(rule.get("casualty_ratio", 1.05))
    draw = float(rule.get("draw_ratio", 1.10))
    text = (f"player holds {obj['player']} of {total} objectives, player inflicted/suffered casualties "
            f"= {ratio:.2f} (needs {need:.2f} with {hold_min}+ objective(s))")
    if rule.get("hold_all", True) and total and obj["player"] == total:
        return "defeat", "the player holds every objective; " + text
    if obj["player"] >= hold_min and ratio >= need:
        return "defeat", "the player holds an objective and inflicted enough casualties; " + text
    if ratio >= draw:
        return "draw", "the player inflicted clearly more casualties but holds no objective; " + text
    return "victory", "the player's winning conditions are not met; " + text


class BattleReport:
    def __init__(self, ai_side=None, player_side=None, objectives=None):
        self.ai_side = ai_side
        self.player_side = player_side
        self.start_objectives = objectives or []
        self.started = time.time()
        self.first_time = None
        self.last_time = 0.0
        self.states = 0
        self.origin = {}           # id -> "ai" or "player": the side a unit fought for when first seen
        self.mine_last = {}        # id -> last known men
        self.mine_info = {}        # id -> {name, kind, start, lost, min_morale, status, written_off}
        self.lost_ids = set()      # own units broken, captured or gone
        self.foe_last = {}
        self.foe_info = {}         # id -> {name, kind, seen_max, lost}
        self.foes_broken = set()
        self.own_loss = 0.0
        self.foe_loss = 0.0
        self.own_start = 0.0
        self.timeline = []         # (battle time, own men lost, enemy men lost seen) every 10 min
        self.series = []           # (battle time, own men lost, enemy men lost seen) at every state
        self._next_sample = 600.0

    # ----- live updates ---------------------------------------------------------------------
    def update(self, state):
        player = state.get("playerSide")
        units = state.get("units", [])
        if self.player_side is None:
            self.player_side = player
        # A captured unit changes side in the game: an AI brigade taken prisoner shows up on the player's side with
        # the status "captured" (and comes back to its own side when it is freed). Counted by its current side it
        # was "an enemy unit broken" for the AI, then a new brigade when freed. Every unit is counted for the side
        # it was first seen fighting for.
        for u in units:
            if u["id"] not in self.origin:
                on_player = u["side"] == player
                swapped = _status(u) == "captured"
                self.origin[u["id"]] = "player" if on_player != swapped else "ai"
        combat = [u for u in units if u["kind"] in COMBAT_KINDS]
        mine = [u for u in combat if self.origin[u["id"]] == "ai"]
        foes = [u for u in combat if self.origin[u["id"]] == "player"]
        if self.ai_side is None:
            own = [u for u in units if u["side"] != player and _status(u) != "captured"]
            if own:
                self.ai_side = own[0]["side"]
        t = float(state.get("time", 0.0))
        if self.first_time is None:
            self.first_time = t
        self.last_time = t
        self.states += 1

        present = set()
        for u in mine:
            uid, hp = u["id"], float(u["hp"])
            present.add(uid)
            if uid not in self.mine_info:
                self.own_start += hp         # first sight, or a unit that arrives later
                self.mine_last[uid] = hp
            info = self.mine_info.setdefault(uid, {"name": u["name"], "kind": u["kind"], "start": hp,
                                                   "lost": 0.0, "min_morale": 1.0, "status": "",
                                                   "written_off": 0.0})
            info["status"] = _status(u)
            if _status(u) == "captured":
                self._write_off(uid)         # prisoners: its men are lost while it stays captured
                continue
            if info["written_off"] > 0:
                # freed, or back in the state after being gone: only the men it really lost stay counted
                back = min(info["written_off"], hp)
                self.own_loss -= back
                info["lost"] -= back
                info["written_off"] = 0.0
                self.mine_last[uid] = hp
                if _status(u) not in BROKEN:
                    self.lost_ids.discard(uid)
            prev = self.mine_last.get(uid)
            if prev is not None and hp < prev:
                self.own_loss += prev - hp
                info["lost"] += prev - hp
            self.mine_last[uid] = hp
            info["min_morale"] = min(info["min_morale"], float(u.get("morale", 1.0)))
            if _status(u) in BROKEN:
                self.lost_ids.add(uid)
        for uid, info in self.mine_info.items():
            if uid not in present and info["written_off"] <= 0 and info["status"] != "gone":
                if info["kind"] == "Skirmish" and info["status"] not in ("captured",) + tuple(BROKEN):
                    # 0.1.4 WIP9: a skirmish screen that leaves the state has gone back into its brigade (its men
                    # count again in the brigade); the men it lost were already counted while it fought
                    info["status"] = "gone"
                    continue
                # the unit is gone: whatever men it still had are lost with it
                self._write_off(uid)
                info["status"] = "gone"

        seen = set()
        for u in foes:
            uid, hp = u["id"], float(u["hp"])
            seen.add(uid)
            info = self.foe_info.setdefault(uid, {"name": u["name"], "kind": u["kind"], "lost": 0.0,
                                                  "written_off": 0.0})
            if _status(u) == "captured":
                # prisoners taken by the AI: the men the unit still had are enemy losses, counted once
                if info["written_off"] <= 0:
                    info["written_off"] = max(hp, 1.0)
                    self.foe_loss += hp
                    info["lost"] += hp
                self.foes_broken.add(uid)
                self.foe_last.pop(uid, None)
                continue
            if info["written_off"] > 0:      # freed by the player
                back = min(info["written_off"], hp)
                self.foe_loss -= back
                info["lost"] -= back
                info["written_off"] = 0.0
                self.foes_broken.discard(uid)
            prev = self.foe_last.get(uid)
            if prev is not None and hp < prev:
                self.foe_loss += prev - hp
                info["lost"] += prev - hp
            self.foe_last[uid] = hp
            if _status(u) in BROKEN or _status(u) == "routing":    # a routing enemy unit is out of the fight
                self.foes_broken.add(uid)
        for uid in list(self.foe_last):
            if uid not in seen:
                del self.foe_last[uid]      # out of sight: do not guess
        self.series.append((t, self.own_loss, self.foe_loss))
        self.series = self.series[-400:]
        if t - (self.first_time or 0.0) >= self._next_sample:
            self.timeline.append((t - (self.first_time or 0.0), self.own_loss, self.foe_loss))
            self._next_sample += 600.0

    def _write_off(self, uid):
        """An own unit captured or gone from the state: the men it had are counted lost (once)."""
        info = self.mine_info[uid]
        if info["written_off"] > 0:
            return
        men = float(self.mine_last.get(uid, 0.0))
        info["written_off"] = max(men, 1.0)
        self.own_loss += men
        info["lost"] += men
        self.lost_ids.add(uid)

    # ----- numbers --------------------------------------------------------------------------
    def recent(self, window=600.0):
        """(own men lost, enemy men lost seen) during the last `window` seconds of play."""
        if not self.series:
            return 0.0, 0.0
        t, own, foe = self.series[-1]
        old = next((s for s in self.series if s[0] >= t - window), self.series[0])
        return own - old[1], foe - old[2]

    def kd_men(self):
        return self.foe_loss / max(self.own_loss, 1.0)

    # 0.1.4 WIP9: a brigade's skirmish screen (a few dozen men) is not a unit lost like a brigade: unit counts and
    # the unit kill ratio leave skirmishers out; they are reported apart.
    def units_lost(self):
        return sum(1 for i in self.lost_ids if self.mine_info.get(i, {}).get("kind") != "Skirmish")

    def skirmishers_lost(self):
        return len(self.lost_ids) - self.units_lost()

    def foes_broken_units(self):
        return sum(1 for i in self.foes_broken if self.foe_info.get(i, {}).get("kind") != "Skirmish")

    def kd_units(self):
        return self.foes_broken_units() / max(self.units_lost(), 1)

    def kd_verdict(self):
        kd = self.kd_men()
        if self.own_loss < 1 and self.foe_loss < 1:
            return "no losses on either side"
        if kd >= 1.5:
            return "good: you inflicted clearly more losses than you took"
        if kd >= 0.8:
            return "even: roughly equal losses"
        return "poor: you lost more men than you inflicted"

    def live_lines(self, casualty_goal=None, objectives=None, rule=None):
        """Short performance lines for the prompt, so the model can judge how it is doing."""
        if self.states == 0:
            return []
        extra = []
        if rule and objectives:
            obj = self.objective_summary(objectives)
            outcome, why = player_rule_outcome(obj, self.own_loss, self.foe_loss, rule)
            hold_min = int(rule.get("hold_min", 1))
            need = float(rule.get("casualty_ratio", 1.05))
            extra.append(
                "THE HUMAN PLAYER WINS (you must prevent this) if it holds "
                + ("every objective, or " if rule.get("hold_all", True) else "")
                + f"at least {hold_min} objective(s) AND your losses reach {need:.2f} times its own "
                "(so you must trade at least evenly, ideally better). "
                f"Right now: {'the player is ahead' if outcome == 'defeat' else 'you are not losing'} "
                f"({why}).")
        goal = ""
        if casualty_goal:
            met = self.kd_men() >= float(casualty_goal)
            goal = (f" Mission goal: inflict at least {casualty_goal:.2f}x the enemy's casualties: "
                    + ("MET at the moment." if met else "NOT met yet."))
        return extra + [
            f"PERFORMANCE SO FAR: you lost about {self.own_loss:.0f} men ({self.units_lost()} units broken, "
            f"captured or gone); you inflicted at least {self.foe_loss:.0f} men "
            f"({self.foes_broken_units()} enemy units broken or captured; skirmish screens not counted). "
            f"Kill/death in men: {self.kd_men():.2f} ({self.kd_verdict()}).{goal}"
        ]

    # ----- end of battle --------------------------------------------------------------------
    def objective_summary(self, objectives):
        mine = other = free = 0
        vp_mine = vp_other = 0
        for o in objectives or []:
            vp = o.get("victoryPoints") or 0
            side = str(o.get("side", ""))
            if side == self.ai_side:
                mine += 1
                vp_mine += vp
            elif side == self.player_side:
                other += 1
                vp_other += vp
            else:
                free += 1
        return {"ai": mine, "player": other, "unheld": free, "ai_vp": vp_mine, "player_vp": vp_other}

    def finish(self, game_result, objectives, scoring=None, rule=None, trust_game=False, goals=None):
        """rule: the human player's winning conditions (see player_rule_outcome). The game's own
        result text is only used when trust_game is set and no rule is given: in practice the
        game printed "Defeat" after a battle the human player had won."""
        scoring = {**DEFAULT_SCORING, **(scoring or {})}
        obj = self.objective_summary(objectives)
        outcome, source, why = None, "game result", ""
        by_goals = ai_outcome(goals) if goals else None
        if trust_game and player_result_to_ai(game_result):
            # "Battle finished. Result=" of the game log: the briefing goals, human player's view.
            outcome, source = player_result_to_ai(game_result), "the game's battle result, inverted for the AI"
            if by_goals and by_goals != outcome:
                why = f"note: the goals read from the game say {by_goals}"
        elif by_goals:
            outcome, source = by_goals, "the mission goals read from the game, inverted for the AI"
        elif rule and (objectives or obj["ai"] + obj["player"] + obj["unheld"]):
            outcome, why = player_rule_outcome(obj, self.own_loss, self.foe_loss, rule)
            source = "mission rule from config.json: the player's conditions"
        elif trust_game:
            outcome = player_result_to_ai(game_result)
        if outcome is None and objectives:
            source = "objectives"
            if obj["ai_vp"] != obj["player_vp"]:
                outcome = "victory" if obj["ai_vp"] > obj["player_vp"] else "defeat"
            elif obj["ai"] != obj["player"]:
                outcome = "victory" if obj["ai"] > obj["player"] else "defeat"
            else:
                outcome = "draw"
        if outcome is None:
            source = "unknown"
        min_cas = float(scoring.get("min_casualties", 25))
        if self.own_loss + self.foe_loss < min_cas:
            # Nobody fought (a test, or the battle was stopped at once): no result, no points.
            outcome, source = "no_contest", f"fewer than {min_cas:.0f} casualties in total"
        points = scoring.get(outcome, 0) if outcome else 0
        return {
            "ended": time.strftime("%Y-%m-%d %H:%M:%S"),
            "ai_side": self.ai_side,
            "game_result_for_player": game_result,
            "outcome": outcome or "unknown",
            "outcome_source": source,
            "outcome_reason": why,
            "points": points,
            "duration_s": round(self.last_time - (self.first_time or 0.0)),
            "objectives": obj,
            "own_men_start": round(self.own_start),
            "own_men_lost": round(self.own_loss),
            "enemy_men_lost_seen": round(self.foe_loss),
            "kd_men": round(self.kd_men(), 2),
            "own_units_lost": self.units_lost(),
            "own_skirmishers_lost": self.skirmishers_lost(),
            "enemy_units_broken_seen": self.foes_broken_units(),
            "enemy_skirmishers_broken_seen": len(self.foes_broken) - self.foes_broken_units(),
            "kd_units": round(self.kd_units(), 2),
            "verdict": self.kd_verdict(),
            "brigades": sorted(
                ({"name": i["name"], "kind": i["kind"], "men_lost": round(i["lost"]),
                  "lowest_morale": round(i["min_morale"], 2), "end": i["status"] or "ok"}
                 for i in self.mine_info.values()), key=lambda b: -b["men_lost"]),
            "enemy_units": sorted(
                ({"name": i["name"], "kind": i["kind"], "men_lost_seen": round(i["lost"])}
                 for i in self.foe_info.values()), key=lambda b: -b["men_lost_seen"])[:8],
        }


def format_report(r):
    """Human readable text of a finished report (printed in the console and saved as .md)."""
    o = r["objectives"]
    lines = [
        "=" * 64,
        f"BATTLE REPORT ({r['ended']}, {r['duration_s'] // 60} min {r['duration_s'] % 60} s of play)",
        *(["DRY RUN: the game's own AI commanded the army; the model's orders were only logged. This battle is",
           "kept apart in the scoreboard (dry_runs) as a reference for the game's AI, not counted for the model."]
          if r.get("dry_run") else []),
        f"Result: {r['outcome'].upper()} for the AI ({r['outcome_source']}; game text "
        f"{r['game_result_for_player']!r})  ->  {r['points']} point(s)",
        *([f"Why: {r['outcome_reason']}"] if r.get("outcome_reason") else []),
        f"Objectives: AI {o['ai']} ({o['ai_vp']} VP), player {o['player']} ({o['player_vp']} VP), "
        f"unheld {o['unheld']}",
        f"Men lost: AI {r['own_men_lost']} of {r['own_men_start']}; enemy at least "
        f"{r['enemy_men_lost_seen']} (only counted while visible)",
        f"Kill/death in men: {r['kd_men']:.2f}  |  units broken or lost: AI {r['own_units_lost']}, "
        f"enemy {r['enemy_units_broken_seen']} (ratio {r['kd_units']:.2f}; skirmish screens apart: AI "
        f"{r.get('own_skirmishers_lost', 0)}, enemy {r.get('enemy_skirmishers_broken_seen', 0)})",
        f"Verdict: {r['verdict']}",
        "",
        "AI brigades (most losses first):",
    ]
    for b in r["brigades"][:12]:
        lines.append(f"  {b['name']} ({b['kind']}): -{b['men_lost']} men, lowest morale "
                     f"{b['lowest_morale']:.2f}, end: {b['end']}")
    if r["enemy_units"]:
        lines.append("Enemy units hit hardest (while visible):")
        for b in r["enemy_units"][:5]:
            lines.append(f"  {b['name']} ({b['kind']}): -{b['men_lost_seen']} men")
    lines.append("=" * 64)
    return "\n".join(lines)


def load_scoreboard():
    try:
        with open(SCOREBOARD, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {"battles": 0, "points": 0, "victories": 0, "draws": 0, "defeats": 0,
                "unknown": 0, "men_lost": 0, "enemy_men_lost_seen": 0, "history": []}


def record(report, backend_name=None, dry_run=False):
    """Add a finished report to the scoreboard and save the report files. Returns the scoreboard.
    WIP11: a dry run (the game's own AI fought, the model's orders were only logged) goes to sb["dry_runs"], a
    reference for the game's AI, and changes neither the totals, nor the history, nor the model's line."""
    sb = load_scoreboard()
    if dry_run:
        sb["dry_runs"] = (sb.get("dry_runs", []) + [{
            "ended": report["ended"], "outcome": report["outcome"], "points": report["points"],
            "commander": "game AI (dry run)", "model_logged": backend_name,
            "kd_men": report["kd_men"], "own_men_lost": report["own_men_lost"],
            "enemy_men_lost_seen": report["enemy_men_lost_seen"]}])[-30:]
        _save(sb, report, "-dryrun")
        return sb
    sb["battles"] += 1
    sb["points"] += report["points"]
    key = {"victory": "victories", "draw": "draws", "defeat": "defeats",
           "no_contest": "no_contest", "interrupted": "interrupted"}.get(report["outcome"], "unknown")
    sb[key] = sb.get(key, 0) + 1
    sb["men_lost"] += report["own_men_lost"]
    sb["enemy_men_lost_seen"] += report["enemy_men_lost_seen"]
    if backend_name:
        m = sb.setdefault("by_model", {}).setdefault(backend_name, {
            "battles": 0, "points": 0, "victories": 0, "defeats": 0, "draws": 0,
            "men_lost": 0, "enemy_men_lost_seen": 0})
        m["battles"] += 1
        m["points"] += report["points"]
        m["men_lost"] += report["own_men_lost"]
        m["enemy_men_lost_seen"] += report["enemy_men_lost_seen"]
        for name, k in (("victory", "victories"), ("defeat", "defeats"), ("draw", "draws")):
            if report["outcome"] == name:
                m[k] += 1
    sb["history"] = (sb["history"] + [{
        "ended": report["ended"], "outcome": report["outcome"], "points": report["points"],
        "model": backend_name,
        "kd_men": report["kd_men"], "own_men_lost": report["own_men_lost"],
        "enemy_men_lost_seen": report["enemy_men_lost_seen"]}])[-30:]
    _save(sb, report)
    return sb


def _save(sb, report, suffix=""):
    """Write the scoreboard and the report files (report-<stamp><suffix>.json / .txt)."""
    os.makedirs("logs", exist_ok=True)
    os.makedirs(REPORT_DIR, exist_ok=True)
    with open(SCOREBOARD, "w", encoding="utf-8") as fh:
        json.dump(sb, fh, indent=2)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    with open(os.path.join(REPORT_DIR, f"report-{stamp}{suffix}.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
    with open(os.path.join(REPORT_DIR, f"report-{stamp}{suffix}.txt"), "w", encoding="utf-8") as fh:
        fh.write(format_report(report) + "\n")


def scoreboard_line(sb):
    if not sb["battles"]:
        return ""
    return (f"Total: {sb['points']} point(s) in {sb['battles']} battle(s) "
            f"({sb['victories']} won, {sb['draws']} drawn, {sb['defeats']} lost"
            + (f", {sb['unknown']} unknown" if sb.get("unknown") else "")
            + (f", {sb['no_contest']} with no fighting" if sb.get("no_contest") else "")
            + (f", {sb['interrupted']} interrupted" if sb.get("interrupted") else "") + ").")
