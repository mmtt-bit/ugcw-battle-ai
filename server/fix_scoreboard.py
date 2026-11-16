"""Correct logs/scoreboard.json without deleting anything.

Run it from the server folder (for example c:\\ugcw-ai):
    python fix_scoreboard.py                                 # shows what would change (nothing is written)
    python fix_scoreboard.py --apply                         # applies it
    python fix_scoreboard.py --game-ai "2026-11-13 15:20:06" # also this battle (the "ended" time of its report)

What it does:
  - finds the battles fought by the game's own AI: a dry run ("dry_run": true in config.json), where the model's
    orders were only logged and not sent. They are recognised in the battle logs (logs/battle-*.jsonl: most of the
    AI's units stayed under the game's control), by "dry_run" in their report, or by their "ended" time
    (GAME_AI_BATTLES below, or --game-ai). They leave the history, the totals and the model's line and go to
    "dry_runs", a reference for the game's AI. Their report files get "dry_run": true and the commander (the
    original files are copied first into reports/backup-<date>/), so that rescore.py keeps them apart too;
  - turns the battles recorded as "unknown" into "defeat" (0 points) (--keep-unknown leaves them);
  - with --remove-victories only (the default of older versions): takes the victories out and moves their report
    files into reports/removed/;
  - corrects the totals and the per-model lines (by_model) by the same amounts, so battles older than the
    30 kept in the history still count;
  - WIP17, merges the PHASES of a chained battle (Antietam, Second Manassas...): a battle recorded as several
    entries, each phase closed by the game's internal "Mission finished" ("game_result_kind": "mission" in its
    report), becomes one entry with the result of its last phase and the losses of all phases; the phase entries
    move to "merged_phases" and their report files get "merged_into" (originals copied into
    reports/backup-<date>/). A map open for less than a minute with no losses (a "no_contest" loading artefact)
    moves to "excluded". --no-merge-phases leaves both alone;
  - copies scoreboard.json to logs/scoreboard.backup-<date>.json first. Nothing is deleted.
"""
import datetime
import argparse
import glob
import json
import os
import shutil
import time

SCOREBOARD = os.path.join("logs", "scoreboard.json")
LOG_DIR = "logs"
REPORT_DIR = "reports"
# Battles known to have been fought by the game's own AI (the "ended" time of their report).
GAME_AI_BATTLES = [
    "2026-11-13 15:20:06",   # Thoroughfare Gap: dry run, the game's AI won (k/d 1.61); credited to the model
]
GAME_AI_SHARE = 0.5          # a battle log whose AI units were under the game's control this often is a dry run
COMBAT = ("Infantry", "Cavalry", "Artillery", "Skirmish")
OUTCOME_KEY = {"victory": "victories", "draw": "draws", "defeat": "defeats", "no_contest": "no_contest",
               "interrupted": "interrupted"}
MODEL_KEY = {"victory": "victories", "draw": "draws", "defeat": "defeats"}


def totals(history):
    """Totals of a history list (also used by rescore.py)."""
    sb = {"battles": len(history), "points": sum(h.get("points", 0) for h in history),
          "victories": 0, "draws": 0, "defeats": 0, "unknown": 0, "no_contest": 0, "interrupted": 0,
          "men_lost": sum(h.get("own_men_lost", 0) for h in history),
          "enemy_men_lost_seen": sum(h.get("enemy_men_lost_seen", 0) for h in history)}
    for h in history:
        sb[OUTCOME_KEY.get(h.get("outcome"), "unknown")] += 1
    return sb


def game_ai_battles_from_logs(log_dir=LOG_DIR, share=GAME_AI_SHARE):
    """{ended: (log file, share of AI unit snapshots under the game's control)} for the dry runs in the logs.
    A log file can hold several battles: the count restarts after each battle report."""
    found = {}
    for path in sorted(glob.glob(os.path.join(log_dir, "battle-*.jsonl"))):
        ai = total = 0
        try:
            with open(path, "r", encoding="utf-8") as fh:
                for line in fh:
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    kind, p = rec.get("kind"), rec.get("payload")
                    if not isinstance(p, dict):
                        continue
                    if kind == "state":
                        player = p.get("playerSide")
                        for u in p.get("units") or []:
                            if u.get("side") != player and u.get("kind") in COMBAT and "ai" in u:
                                total += 1
                                ai += bool(u["ai"])
                    elif kind == "battle_report":
                        rate = ai / total if total else 0.0
                        if p.get("ended") and (p.get("dry_run") or (total and rate >= share)):
                            found[p["ended"]] = (path, round(rate, 2))
                        ai = total = 0
        except OSError:
            continue
    return found


def report_files(ended_set):
    """{ended: [report .json and .txt paths]} for the reports whose "ended" time is in ended_set."""
    out = {}
    for path in glob.glob(os.path.join(REPORT_DIR, "report-*.json")):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                ended = json.load(fh).get("ended")
        except (OSError, ValueError):
            continue
        if ended in ended_set:
            files = [path]
            txt = path[:-5] + ".txt"
            if os.path.exists(txt):
                files.append(txt)
            out.setdefault(ended, []).extend(files)
    return out


def _model_line(sb, model):
    m = sb.setdefault("by_model", {}).setdefault(model or "unknown", {})
    for k in ("battles", "points", "victories", "defeats", "draws", "men_lost", "enemy_men_lost_seen"):
        m.setdefault(k, 0)
    return m


def take_out(sb, h):
    """Subtract one history entry from the totals and from its model's line."""
    sb["battles"] = sb.get("battles", 0) - 1
    sb["points"] = sb.get("points", 0) - h.get("points", 0)
    key = OUTCOME_KEY.get(h.get("outcome"), "unknown")
    sb[key] = sb.get(key, 0) - 1
    sb["men_lost"] = sb.get("men_lost", 0) - h.get("own_men_lost", 0)
    sb["enemy_men_lost_seen"] = sb.get("enemy_men_lost_seen", 0) - h.get("enemy_men_lost_seen", 0)
    if h.get("model") and h["model"] in (sb.get("by_model") or {}):
        m = _model_line(sb, h["model"])
        m["battles"] -= 1
        m["points"] -= h.get("points", 0)
        m["men_lost"] -= h.get("own_men_lost", 0)
        m["enemy_men_lost_seen"] -= h.get("enemy_men_lost_seen", 0)
        if h.get("outcome") in MODEL_KEY:
            m[MODEL_KEY[h["outcome"]]] -= 1


def fix(sb, game_ai, remove_victories=False, keep_unknown=False):
    """Corrected copy of the scoreboard; returns (new scoreboard, moved to dry_runs, removed, turned to defeat)."""
    new = json.loads(json.dumps(sb))
    kept, to_dry, removed, to_defeat = [], [], [], []
    for h in sb.get("history", []):
        if h.get("ended") in game_ai:
            to_dry.append(h)
            take_out(new, h)
            continue
        if h.get("outcome") == "victory" and remove_victories:
            removed.append(h)
            take_out(new, h)
            continue
        if h.get("outcome") == "unknown" and not keep_unknown:
            to_defeat.append(h)
            new["unknown"] = new.get("unknown", 0) - 1
            new["defeats"] = new.get("defeats", 0) + 1
            new["points"] = new.get("points", 0) - h.get("points", 0)
            if h.get("model") and h["model"] in (new.get("by_model") or {}):
                m = _model_line(new, h["model"])
                m["defeats"] += 1
                m["points"] -= h.get("points", 0)
            h = dict(h, outcome="defeat", points=0)
        kept.append(h)
    new["history"] = kept
    known = {d.get("ended") for d in new.get("dry_runs", [])}
    for h in to_dry:
        if h.get("ended") not in known:
            new.setdefault("dry_runs", []).append({
                "ended": h.get("ended"), "outcome": h.get("outcome"), "points": h.get("points", 0),
                "commander": "game AI (dry run)", "model_logged": h.get("model"),
                "kd_men": h.get("kd_men"), "own_men_lost": h.get("own_men_lost", 0),
                "enemy_men_lost_seen": h.get("enemy_men_lost_seen", 0)})
    return new, to_dry, removed, to_defeat


def load_reports():
    """{ended: report dict} for every report file."""
    out = {}
    for path in glob.glob(os.path.join(REPORT_DIR, "report-*.json")):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                r = json.load(fh)
        except (OSError, ValueError):
            continue
        if r.get("ended"):
            out[r["ended"]] = r
    return out


def _when(ended):
    try:
        return datetime.datetime.strptime(ended, "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return None


def merge_phases(sb, reports, max_gap_h=4.0):
    """Copy of sb with the phases of chained battles merged; returns (new, [(final, [phases])], [excluded])."""
    new = json.loads(json.dumps(sb))
    kept, merged, excluded, run = [], [], [], []
    for h in sb.get("history", []):
        r = reports.get(h.get("ended")) or {}
        if (h.get("outcome") == "no_contest" and not h.get("own_men_lost") and not h.get("enemy_men_lost_seen")
                and (r.get("duration_s") or 0) < 60):
            excluded.append(h)
            take_out(new, h)
            continue
        if r.get("game_result_kind") == "mission" and "phases" not in r:   # WIP17 reports are already whole
            if run and (run[-1].get("model") != h.get("model")):
                kept.extend(run)
                run = []
            run.append(h)
            continue
        if run:
            t0, t1 = _when(run[0].get("ended")), _when(h.get("ended"))
            if (all(p.get("model") == h.get("model") for p in run) and t0 and t1
                    and (t1 - t0).total_seconds() <= max_gap_h * 3600 and h.get("outcome") != "no_contest"):
                final = dict(h)
                for p in run:
                    take_out(new, p)
                    for k in ("own_men_lost", "enemy_men_lost_seen"):
                        final[k] = final.get(k, 0) + p.get(k, 0)
                        key = "men_lost" if k == "own_men_lost" else k
                        new[key] = new.get(key, 0) + p.get(k, 0)
                        if h.get("model") in (new.get("by_model") or {}):
                            new["by_model"][h["model"]][key] += p.get(k, 0)
                final["kd_men"] = round(final["enemy_men_lost_seen"] / max(final["own_men_lost"], 1), 2)
                final["phases"] = len(run) + 1
                final["merged_from"] = [p.get("ended") for p in run]
                merged.append((final, list(run)))
                kept.append(final)
                run = []
                continue
            kept.extend(run)
            run = []
        kept.append(h)
    kept.extend(run)
    new["history"] = kept
    if merged:
        new.setdefault("merged_phases", []).extend(
            dict(p, merged_into=f.get("ended")) for f, run_ in merged for p in run_)
    if excluded:
        new.setdefault("excluded", []).extend(dict(h, reason="map open under a minute, no losses")
                                               for h in excluded)
    return new, merged, excluded


def summary(sb):
    return (f"{sb.get('points', 0)} point(s) in {sb.get('battles', 0)} battle(s) ({sb.get('victories', 0)} won, "
            f"{sb.get('draws', 0)} drawn, {sb.get('defeats', 0)} lost, {sb.get('unknown', 0)} unknown)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write the changes (default: only show them)")
    ap.add_argument("--game-ai", action="append", default=[], metavar="ENDED",
                    help='"ended" time of a battle fought by the game\'s own AI (repeatable)')
    ap.add_argument("--no-log-scan", action="store_true", help="do not look for dry runs in logs/battle-*.jsonl")
    ap.add_argument("--remove-victories", action="store_true",
                    help="take the victories out of the scoreboard (the default of older versions)")
    ap.add_argument("--keep-victories", action="store_true", help="kept for older command lines: no effect")
    ap.add_argument("--keep-unknown", action="store_true", help="do not turn unknown into defeat")
    ap.add_argument("--no-merge-phases", action="store_true",
                    help="do not merge the phases of chained battles, keep the loading artefacts")
    args = ap.parse_args()

    with open(SCOREBOARD, "r", encoding="utf-8") as fh:
        sb = json.load(fh)
    print(f"Before: {summary(sb)}; {len(sb.get('history', []))} battle(s) in the history list.")

    game_ai = {e: "listed in fix_scoreboard.py" for e in GAME_AI_BATTLES}
    game_ai.update({e: "given with --game-ai" for e in args.game_ai})
    if not args.no_log_scan:
        for ended, (path, rate) in game_ai_battles_from_logs().items():
            game_ai[ended] = f"{os.path.basename(path)}: AI units under the game's control {rate:.0%} of the time"
    for path in glob.glob(os.path.join(REPORT_DIR, "report-*.json")):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                r = json.load(fh)
            if r.get("dry_run") and r.get("ended"):
                game_ai.setdefault(r["ended"], f"{os.path.basename(path)} says dry run")
        except (OSError, ValueError):
            pass

    new, to_dry, removed, to_defeat = fix(sb, game_ai, args.remove_victories, args.keep_unknown)
    merged, excluded = [], []
    if not args.no_merge_phases:
        new, merged, excluded = merge_phases(new, load_reports())
        for final, run in merged:
            print(f"Chained battle merged: {final.get('ended')} {final.get('outcome')} now has "
                  f"{final['phases']} phases (" + ", ".join(f"{p.get('ended')} {p.get('outcome')}" for p in run)
                  + f" + the last); own losses {final['own_men_lost']}, enemy seen {final['enemy_men_lost_seen']}")
        for h in excluded:
            print(f"Loading artefact moved to 'excluded': {h.get('ended')} {h.get('outcome')} (no losses, "
                  "map open under a minute)")
    print(f"After:  {summary(new)}")
    print(f"Battles fought by the game's own AI, moved to dry_runs: {len(to_dry)}")
    for h in to_dry:
        print(f"    {h.get('ended')} {h.get('outcome')} {h.get('points')} point(s), was credited to "
              f"{h.get('model')}  [{game_ai[h.get('ended')]}]")
    if removed:
        print(f"Victories taken out (--remove-victories): {len(removed)}")
        for h in removed:
            print("   ", h.get("ended"), h.get("outcome"), h.get("points"), "point(s)")
    if to_defeat:
        print(f"Unknown results turned into defeats: {len(to_defeat)}")
    for name, m in sorted((new.get("by_model") or {}).items()):
        print(f"    {name}: {m.get('points', 0)} point(s) in {m.get('battles', 0)} battle(s), "
              f"{m.get('victories', 0)} won, {m.get('draws', 0)} drawn, {m.get('defeats', 0)} lost")

    dry_files = report_files({h.get("ended") for h in to_dry})
    moves = [p for files in report_files({h.get("ended") for h in removed}).values() for p in files]
    for files in dry_files.values():
        for p in files:
            print("    report file to mark as a dry run:", p)
    for path in moves:
        print("    report file to move into reports/removed/:", path)
    if not args.apply:
        print("Nothing written. Run again with --apply to apply.")
        return

    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = os.path.join(LOG_DIR, f"scoreboard.backup-{stamp}.json")
    shutil.copy2(SCOREBOARD, backup)
    if merged:
        keep = os.path.join(REPORT_DIR, f"backup-{stamp}")
        os.makedirs(keep, exist_ok=True)
        targets = {p.get("ended"): f.get("ended") for f, run in merged for p in run}
        for ended, files in report_files(set(targets)).items():
            for p in files:
                shutil.copy2(p, os.path.join(keep, os.path.basename(p)))
                if p.endswith(".json"):
                    with open(p, "r", encoding="utf-8") as fh:
                        r = json.load(fh)
                    r["merged_into"] = targets[ended]
                    with open(p, "w", encoding="utf-8") as fh:
                        json.dump(r, fh, indent=2)
        print(f"Phase reports marked 'merged_into'; the originals are copied in {keep}.")
    if dry_files:
        keep = os.path.join(REPORT_DIR, f"backup-{stamp}")
        os.makedirs(keep, exist_ok=True)
        for ended, files in dry_files.items():
            for p in files:
                shutil.copy2(p, os.path.join(keep, os.path.basename(p)))
                if p.endswith(".json"):
                    with open(p, "r", encoding="utf-8") as fh:
                        r = json.load(fh)
                    r["dry_run"] = True
                    r["commander"] = "game AI (dry run: the model's orders were logged, not sent)"
                    with open(p, "w", encoding="utf-8") as fh:
                        json.dump(r, fh, indent=2)
                else:
                    with open(p, "r", encoding="utf-8") as fh:
                        text = fh.read()
                    if not text.startswith("DRY RUN"):
                        with open(p, "w", encoding="utf-8") as fh:
                            fh.write("DRY RUN: the game's own AI commanded the army; the model's orders were only "
                                     "logged. Kept apart in the scoreboard (dry_runs).\n" + text)
        print(f"Report files marked as dry runs; the originals are copied in {keep}.")
    if moves:
        os.makedirs(os.path.join(REPORT_DIR, "removed"), exist_ok=True)
        for path in moves:
            shutil.move(path, os.path.join(REPORT_DIR, "removed", os.path.basename(path)))
    with open(SCOREBOARD, "w", encoding="utf-8") as fh:
        json.dump(new, fh, indent=2)
    print(f"Done. The previous scoreboard is saved as {backup}.")


if __name__ == "__main__":
    main()
