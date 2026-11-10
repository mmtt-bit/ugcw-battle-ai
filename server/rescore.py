"""Recompute the result of the recorded battles and rebuild the scoreboard, without deleting anything.

Why: before the plugin read the mission goals from the game, some battles were scored with the
game's internal "Mission finished" text, which was wrong (it said "Defeat" after a battle the human
player had won). This script re-reads the saved reports (reports/report-*.json) and decides the
result of each battle with the best information the report holds, in this order:
  1. the briefing goals read from the game at the end of the battle ("goals" in the report),
     inverted for the AI;
  2. the game's "Battle finished" text, when the report says it is the battle one
     ("game_result_kind": "battle");
  3. the human player's conditions of config.json (mission > player_rule), applied to the objectives
     and casualties of the report;
  4. otherwise the report is left as it was and marked "kept".
Battles with almost no fighting stay "no_contest".

Run it from the planner folder:
    python rescore.py            # shows what would change (nothing is written)
    python rescore.py --apply    # writes logs/scoreboard.json (the old one is saved first as
                                 # logs/scoreboard.backup-<date>.json; report files are not touched)
"""
import argparse
import glob
import json
import os
import shutil
import time

from fix_scoreboard import totals
from goals import ai_outcome
from report import player_result_to_ai, player_rule_outcome

SCOREBOARD = os.path.join("logs", "scoreboard.json")
POINTS = {"victory": 3, "draw": 1, "defeat": 0}


def decide(r, rule, min_cas):
    """(outcome, source) of one saved report."""
    if r["own_men_lost"] + r["enemy_men_lost_seen"] < min_cas:
        return "no_contest", "almost no fighting"
    if r.get("goals") and ai_outcome(r["goals"]):
        return ai_outcome(r["goals"]), "goals read from the game"
    if r.get("game_result_kind") == "battle" and player_result_to_ai(r.get("game_result_for_player")):
        return player_result_to_ai(r["game_result_for_player"]), "game's battle result"
    if rule:
        return player_rule_outcome(r["objectives"], r["own_men_lost"], r["enemy_men_lost_seen"], rule)[0], "player_rule"
    return r.get("outcome", "unknown"), "kept (no goals, no battle text, no rule)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    cfg = {}
    if os.path.exists("config.json"):
        with open("config.json", "r", encoding="utf-8-sig") as fh:
            cfg = json.load(fh)
    rule = cfg.get("mission", {}).get("player_rule")
    points = {**POINTS, **cfg.get("scoring", {})}
    min_cas = float(cfg.get("scoring", {}).get("min_casualties", 25))
    history, changed = [], 0
    for path in sorted(glob.glob(os.path.join("reports", "report-*.json"))):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                r = json.load(fh)
            new, source = decide(r, rule, min_cas)
        except (OSError, ValueError, KeyError, TypeError) as e:
            print(f"{os.path.basename(path)}: skipped ({e})")
            continue
        old = r.get("outcome")
        pts = points.get(new, 0)
        changed += new != old
        print(f"{os.path.basename(path)}  {str(r.get('backend') or '?'):26} {old:10} -> {new:10} "
              f"{pts} pt  [{source}]" + ("   <-- CHANGED" if new != old else ""))
        history.append({"ended": r["ended"], "outcome": new, "points": pts, "model": r.get("backend"),
                        "kd_men": r["kd_men"], "own_men_lost": r["own_men_lost"],
                        "enemy_men_lost_seen": r["enemy_men_lost_seen"]})
    if not history:
        print("No report found in reports/.")
        return
    sb = totals(history)
    by_model = {}
    for h in history:
        m = by_model.setdefault(h["model"] or "unknown", {
            "battles": 0, "points": 0, "victories": 0, "defeats": 0, "draws": 0,
            "men_lost": 0, "enemy_men_lost_seen": 0})
        m["battles"] += 1
        m["points"] += h["points"]
        m["men_lost"] += h["own_men_lost"]
        m["enemy_men_lost_seen"] += h["enemy_men_lost_seen"]
        for name, k in (("victory", "victories"), ("defeat", "defeats"), ("draw", "draws")):
            if h["outcome"] == name:
                m[k] += 1
    sb["by_model"] = by_model
    sb["history"] = history[-30:]
    print(f"{changed} battle(s) changed. New total: {sb['points']} point(s) in {sb['battles']} battle(s) "
          f"({sb['victories']} won, {sb['draws']} drawn, {sb['defeats']} lost, {sb['no_contest']} no contest)")
    if not args.apply:
        print("Nothing written. Run again with --apply to write the scoreboard.")
        return
    if os.path.exists(SCOREBOARD):
        backup = os.path.join("logs", f"scoreboard.backup-{time.strftime('%Y%m%d-%H%M%S')}.json")
        shutil.copy2(SCOREBOARD, backup)
        print("Previous scoreboard saved as", backup)
    os.makedirs("logs", exist_ok=True)
    with open(SCOREBOARD, "w", encoding="utf-8") as fh:
        json.dump(sb, fh, indent=2)
    print("Done.")


if __name__ == "__main__":
    main()
