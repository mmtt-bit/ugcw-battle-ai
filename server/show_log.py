"""Print a session log (logs/battle-*.jsonl) in a readable form.

Usage (run it from the folder that contains planner_server.py):
  python show_log.py                    latest log, short view
  python show_log.py --prompts          also print the prompts sent to the model
  python show_log.py --terrain          also print the terrain overview map
  python show_log.py logs\\battle-20261107-153012.jsonl
"""
import argparse
import glob
import json
import os
import sys

from terrain import TerrainMap


def latest_log():
    files = sorted(glob.glob(os.path.join("logs", "battle-*.jsonl")))
    return files[-1] if files else None


def clock(seconds):
    s = int(seconds)
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def block(text):
    return "\n".join("    | " + line for line in str(text).strip().splitlines())


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Print a UgcwAi session log.")
    parser.add_argument("path", nargs="?", help="log file (default: the latest one in logs/)")
    parser.add_argument("--prompts", action="store_true", help="also print the prompts")
    parser.add_argument("--terrain", action="store_true", help="also print the terrain map")
    args = parser.parse_args()
    path = args.path or latest_log()
    if not path or not os.path.exists(path):
        raise SystemExit("No log found. Run this script from the folder that contains logs/.")
    print("Log file:", path)
    pending = []  # LLM lines are written before their state line: regroup them per cycle
    with open(path, "r", encoding="utf-8") as fh:
        for raw_line in fh:
            try:
                entry = json.loads(raw_line)
            except ValueError:
                continue
            kind, data = entry.get("kind"), entry.get("payload")
            if kind in ("llm", "llm_error"):
                pending.append((kind, data))
            elif kind == "state":
                mine = [u for u in data["units"] if u["side"] != data["playerSide"]]
                foes = [u for u in data["units"] if u["side"] == data["playerSide"]]
                print(f"\n=== battle time {clock(data['time'])} | your units: {len(mine)} | "
                      f"visible enemies: {len(foes)}")
                for pkind, pdata in pending:
                    if pkind == "llm_error":
                        print("  LLM ERROR:", pdata.get("error"))
                        if pdata.get("raw"):
                            print("  raw answer:\n" + block(pdata["raw"]))
                    else:
                        info = pdata.get("info") or {}
                        extra = ", ".join(f"{k}={v}" for k, v in info.items() if v is not None)
                        print(f"  LLM answered in {pdata.get('seconds')}s" + (f" ({extra})" if extra else ""))
                        if args.prompts:
                            if pdata.get("system"):
                                print("  system prompt:\n" + block(pdata["system"]))
                            print("  prompt:\n" + block(pdata.get("user", "")))
                        print("  raw answer:\n" + block(pdata.get("raw", "")))
                pending = []
            elif kind == "orders":
                print(f"  orders sent ({len(data)}):")
                for o in data:
                    if o.get("text"):   # logs written since unit names were added
                        print("    " + o["text"])
                        continue
                    extra = {k: v for k, v in o.items() if k not in ("cmd", "id")}
                    print(f"    {o['cmd']} unit {o['id']} {extra}")
            elif kind == "event":
                print("  event:", data)
            elif kind == "terrain":
                try:
                    terrain = TerrainMap(data)
                except (KeyError, TypeError, ValueError) as e:
                    print("\n=== terrain message could not be read:", e)
                    continue
                print(f"\n=== terrain: {terrain.cols}x{terrain.rows} cells of {terrain.step:.0f} units, "
                      f"{len(terrain.crossings())} ford/bridge site(s), {len(terrain.objectives)} objective(s)")
                if args.terrain:
                    text, cell = terrain.overview(60)
                    print("  legend: " + ", ".join(f"{s} = {n}" for s, n in terrain.legend.items()))
                    print(f"  overview (one character = about {cell:.0f} units, largest z at the top):")
                    print(block(text))


if __name__ == "__main__":
    main()
