"""Planner server for the UgcwAi bridge. Protocol: one JSON message per line.

Cycle: the game sends a "state" message and pauses itself, this server answers
with zero or more orders followed by {"cmd": "plan_done"}, and the game resumes.

Orders (server -> game). "id" is a unit of the AI side, "target" a visible enemy:
  {"cmd": "move", "id": 9, "x": 3900.0, "z": 300.0}
  {"cmd": "attack", "id": 9, "target": 42}        chase the target and fire
  {"cmd": "charge", "id": 9, "target": 42}        melee charge
  {"cmd": "range_attack", "id": 9, "target": 42}  ranged attack
  {"cmd": "hold", "id": 9}                        hold position
  {"cmd": "fallback", "id": 9, "duration": 20}    fall back for N seconds
  {"cmd": "formation", "id": 9, "value": "Line"}  "Line" or "RoadColumn"
  {"cmd": "gait", "id": 9, "value": "Run"}        "Run" or "Walk"
  {"cmd": "ammo", "id": 9, "value": "canister"}   artillery ammunition: "auto", "mixed" or "canister"
  {"cmd": "plan_done", "next_in": 120}            resume the game; the next planning pause
                                                  comes after 120 s of play (game time)

Events (game -> server):
  {"type": "terrain", ...}                        battlefield description, sent once per
                                                  battle and on every (re)connection
  {"type": "state", ...}                          snapshot, fog of war applied
  {"type": "done", "id": 9, "canceled": false}    a move order has ended

Files next to this script:
  config.json   backend choice and options ("ollama", "openai_compatible",
                "claude_code" or "placeholder")
  strategy.md   free-text strategy notes for the AI commander, re-read every cycle
  backends.py   LLM backends (add your own there)
  prompting.py  prompt construction, answer parsing and order validation
  terrain.py    terrain map built from the plugin's "terrain" message
  show_log.py   prints a session log (logs/*.jsonl) in a readable form
Every session is also written to logs/battle-<date>.jsonl (states, prompts, raw model
answers, orders and events) so prompts can be developed offline, without the game.
"""
import json
import math
import os
import socket
import sys
import time
import traceback
from collections import Counter

from backends import BackendError, make_backend
from equipment import equipment_static, roster_lines
from prompting import (ORDERS_SCHEMA, build_system_prompt, build_user_prompt, parse_answer, extract_plan,
                       sanitize, split_units, label, order_text)
from report import (BattleReport, format_report, record, scoreboard_line, load_scoreboard)
from assessment import write_assessment
from goals import PLAN_DEFAULTS, goals_lines, make_plan
from battery import DEFAULT_BATTERY, unpack_orders
from cavalry import DEFAULT_CAVALRY, ride_down_orders
from situation import situation_lines, stalemate_lines
from supply import DEFAULT_SUPPLY, set_known_foes, supply_orders
from autopilot import (DEFAULT_AMMO, DEFAULT_ENGAGE, DEFAULT_GUARD, ammo_orders, engage_orders,
                       guard_artillery)
from assault import DEFAULT_ASSAULT, assault_lines, assault_orders, briefing_lines
from relief import DEFAULT_RELIEF, relief_orders, reserve_orders
from terrain import TerrainMap

VERSION = "0.1.2-beta"
HOST, PORT = "127.0.0.1", 8765
LOG_DIR = "logs"

DEFAULT_CONFIG = {
    "backend": "ollama",
    "max_orders_per_cycle": 60,
    "dry_run": False,
    "verbose": False,  # True: print the raw model answer; "full": also print the prompt
    "terrain": {
        "in_prompt": True,      # give the terrain description to the model
        "print_map": True,      # print the overview map in this console when it is received
        "overview_cols": 60,    # width of the terrain map in the prompt (characters)
        "height_cols": 40,      # width of the relief map in the prompt
        "show_heights": True,
        "show_rules": True,     # terrain effects as described by the game
    },
    "ranges": {
        # Distances in game units, measured in game: units open fire at 400 and charge at 200.
        "fire": 400,
        "charge": 200,
    },
    "line": {
        # Suggested front line (see FRONT LINE PLAN in the prompt): continuous, evenly spaced and
        # as wide as the visible enemy front.
        "enabled": True,
        "spacing": 70,        # minimum distance between neighbouring infantry units
        "max_spacing": 150,   # never spread wider than this
        "standoff": 360,      # distance from the nearest enemy unit (fire range is 400)
        "tolerance": 50,      # closer than this to the slot counts as "in position"
    },
    "posture": {
        # Attack when stronger, defend when weaker (see FORCE BALANCE in the prompt).
        "enabled": True,
        "attack_ratio": 1.25,   # your strength / visible enemy strength at or above: attack
        "defend_ratio": 0.80,   # at or below: defend
        "local_radius": 800,    # units around an objective counted as "there"
        "stalemate_minutes": 20,  # no objective changed hands for this long: order an assault
    },
    "overlay": {"enabled": True, "max_chars": 260},   # in-game panel with the last reasoning (F6 hides it)
    "plan": dict(PLAN_DEFAULTS),      # attack / defend / trade decision from the mission goals, see goals.py
    "cavalry": dict(DEFAULT_CAVALRY),   # cavalry roles: reserve, flanks, early scout, see cavalry.py
    "battery": dict(DEFAULT_BATTERY),   # artillery readiness and placement, see battery.py
    "supply": dict(DEFAULT_SUPPLY),   # supply wagons rearm batteries and brigades, see supply.py
    "scale": {                         # short battles get every detail; large ones a compact prompt
        "force": None,                 # None = automatic, or "small" / "large"
        "large_threshold": 40,         # own combat units (infantry, cavalry, artillery, skirmishers) for "large"
        "large": {
            "detail_radius": 1200,     # own units farther than this from every visible enemy: short line
            "route_radius": 800,       # terrain along the way to the nearest enemy only this close
            "enemy_detail_radius": 900,  # enemy terrain/equipment only this close to one of your units...
            "max_enemy_detail": 30,    # ...and for at most this many (nearest first)
            "max_charge": 8,           # CHARGE OPPORTUNITIES lines
            "max_lanes": 6,            # FIRE LANES lines
            "compact_orders": True,    # YOUR ORDERS LAST TURN with ids only
        },
    },
    "economy": {                       # token savings, see Commander.quiet_turn and the YOUR BRIGADES roster
        "static_roster": True,         # fixed equipment of your units once in the (cached) system prompt
        "skip_quiet_turns": True,      # no model call when nothing worth a decision happened
        "max_consecutive_skips": 1,    # at most this many quiet turns in a row
        "max_gap_s": 150,              # and never longer than this without a model call (battle seconds)
        "morale_drop": 0.1,            # a unit losing this much morale since the last call is worth a call
        "loss_men": 100,               # men lost since the last call that are worth a call...
        "loss_share": 0.01,            # ...or this share of the starting men, whichever is larger
        "log_usage": True,             # print the tokens of every call and the battle total
    },
    "assault": dict(DEFAULT_ASSAULT),   # assault group and attack plan on an objective, see assault.py
    "relief": dict(DEFAULT_RELIEF),   # pull back broken brigades, replace them, commit the reserve, see relief.py
    "engage": dict(DEFAULT_ENGAGE),   # server-side initiative for idle units, see autopilot.py
    "guard": dict(DEFAULT_GUARD),     # batteries without cover are pulled back
    "ammo": dict(DEFAULT_AMMO),       # automatic canister switching for artillery
    "mission": {
        # Per-mission knowledge copied from the briefing screen ("Victory conditions").
        # objectives_only: names of the objectives that really count (empty = every objective
        # inside the playable area). casualty_goal: the briefing asks to inflict at least this
        # many times the enemy's casualties (1.05 = "5% more casualties than the enemy").
        "objectives_only": [],
        "casualty_goal": None,
        # The human player's winning conditions, copied from the briefing. They decide the result
        # of the battle for the AI (the game's own result text proved unreliable).
        # hold_all: the player wins by holding every objective; hold_min + casualty_ratio: or by
        # holding that many objectives and inflicting that multiple of the AI's casualties;
        # draw_ratio: inflicting that much more but holding nothing is a draw.
        "player_rule": None,
        "trust_game_result": False,
    },
    "assessment": {
        # At the end of a battle the model writes an after-action review (reports/assessment-*.md).
        "enabled": True,
    },
    "scoring": {
        # Points the AI earns at the end of a battle (see the battle report in reports/).
        "victory": 3,
        "draw": 1,
        "defeat": 0,
        "min_casualties": 25,   # fewer total casualties than this: "no contest", no points
    },
    "timing": {
        # Seconds of play (at normal speed, pauses excluded) between two planning pauses.
        "approach_interval_s": 120,   # no enemy in sight yet
        "closing_interval_s": 60,     # an enemy is in sight but not yet in contact
        "engaged_interval_s": 30,     # contact: stays like this for the rest of the battle
        "contact_distance": 600,      # distance (game units) at which we call it contact
    },
    "ollama": {
        "base_url": "http://localhost:11434",
        "model": "gemma4:12b",
        "timeout_s": 75,
        "temperature": 0.2,
        "num_ctx": 16384,      # context window; Ollama's default (4096) is too small
        "num_predict": 3072,   # maximum length of the answer (about 40 tokens per order)
        "think": False,        # switch thinking off ("low" for gpt-oss)
        "use_schema": True,    # constrain the answer to the orders JSON schema
        "keep_alive": "30m",
    },
    "openai_compatible": {
        "base_url": "http://localhost:1234/v1",
        "model": "your-model-name",
        "api_key": "",
        "timeout_s": 75,
        "temperature": 0.3,
        "max_tokens": 4096,
        "json_mode": False,
        "reasoning_effort": None,
    },
    "claude_code": {
        "command": "claude",
        "model": "sonnet",
        "effort": None,
        "timeout_s": 150,      # a Claude Code call takes a few seconds to start, then answers
        "workdir": "claude_workdir",
        "extra_args": [],
    },
}


def load_config(path="config.json"):
    config = json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8-sig") as fh:
            user = json.load(fh)
        for key, value in user.items():
            if isinstance(value, dict) and isinstance(config.get(key), dict):
                config[key].update(value)
            else:
                config[key] = value
    return config


def read_text(path):
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            return fh.read()
    except OSError:
        return ""


def indent_block(text):
    return "\n".join("  | " + line for line in text.splitlines())


def _norm(text):
    return "".join(ch for ch in text.lower() if ch.isalnum())


def describe_order(order, names=None):
    return order_text(order, names or {})


def send(f, obj):
    f.write(json.dumps(obj) + "\n")
    f.flush()


def log_event(log_path, kind, payload):
    """Append one line (state, prompt, orders or event) to the session log."""
    with open(log_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"kind": kind, "payload": payload}) + "\n")


def placeholder_plan(state):
    """Rule-based planner used when backend is "placeholder" (no LLM needed)."""
    mine, foes = split_units(state)
    mine = [u for u in mine if u["kind"] == "Infantry"]
    orders = []
    if not foes:
        return orders  # nothing visible: leave the units to the native AI
    for u in mine:
        foe = min(foes, key=lambda e: math.hypot(e["x"] - u["x"], e["z"] - u["z"]))
        dx, dz = foe["x"] - u["x"], foe["z"] - u["z"]
        dist = math.hypot(dx, dz)
        if dist < 300:
            orders.append({"cmd": "attack", "id": u["id"], "target": foe["id"]})
            continue
        step = min(150.0, dist - 250.0)
        orders.append({"cmd": "move", "id": u["id"],
                       "x": round(u["x"] + dx / dist * step, 1),
                       "z": round(u["z"] + dz / dist * step, 1)})
    return orders


class Commander:
    """Turns game states into validated orders, using the configured backend."""

    def __init__(self, config):
        self.config = config
        self.backend = None if config["backend"] == "placeholder" else make_backend(config)
        self.previous_orders = []
        self.events = []
        self.report = None   # BattleReport of the battle in progress
        self.line_memory = {}     # remembered line slots (see front_line_plan)
        self.journal = []         # one entry per planning turn: time, reasoning, order counts
        self.stats = {}           # how often the server had to correct the model's orders
        self.owner_log = []       # (battle time, objective, before, after)
        self.pending_moves = {}   # unit id -> (x, z, game time) of moves not reported done yet
        self.owners = {}          # objective name -> owner, to report changes
        self.last_objectives = []
        self.pending_objectives = []
        self.names = {}   # unit id -> name, refreshed at every state message
        self.system_logged = False
        self.terrain = None
        self.terrain_warned = False
        self.engaged = False   # becomes True at the first contact and stays True for the battle
        self.last_cmds = {}       # unit id -> last order sent (used to find idle units)
        self.goals = []           # battle goals of the mission as read from the game (human player's view)
        self.last_change = None   # battle time of the last objective change (or of the first contact)
        self.contact_time = None  # battle time of the first contact
        self.plan_info = None     # strategic plan from the mission goals (mode ATTACK / DEFEND / TRADE)
        self.last_mode = None
        self.only_warned = False
        self.foe_memory = {}      # enemy id -> last seen record
        self.briefing = {}        # mission title and description read in the game
        self.assault_mem = {}     # assault group state, see assault.py
        self.relief_clock = {}    # unit id -> battle time of the last pull-back order
        self.unpack_tries = {}    # battery id -> unpack orders given while it stayed packed
        self.saved_plan = None    # (battle time, text): the attack plan the model wrote
        self.stop_loss_until = 0.0
        self.roster = {}          # unit id -> fixed equipment text given once in the system prompt
        self.roster_text = []
        self.tokens = Counter()   # token usage of the battle in progress
        self.llm_calls, self.skipped_turns, self.skips_in_row = 0, 0, 0
        self.last_call_snap = None
        self.manual_arrivals = 0  # moves ordered by the model that finished since the last call
        self.seen_foes = set()    # enemy ids seen at least once in this battle
        self.scale_name = None    # "small" or "large" battle (prompt detail), see battle_scale

    def next_delay(self, state):
        """Seconds of play before the next planning pause, with the reason."""
        timing = self.config["timing"]
        mine, foes = split_units(state)
        closest = None
        for u in mine:
            for e in foes:
                d = math.hypot(u["x"] - e["x"], u["z"] - e["z"])
                if closest is None or d < closest:
                    closest = d
        if closest is not None and closest <= timing["contact_distance"]:
            if not self.engaged:
                self.last_change = float(state.get("time", 0.0))
                self.contact_time = self.last_change
            self.engaged = True
        if self.engaged:
            return timing["engaged_interval_s"], "contact"
        if closest is None:
            return timing["approach_interval_s"], "no enemy in sight"
        return timing["closing_interval_s"], f"enemy in sight at {closest:.0f}"

    def in_play(self, objectives):
        """Keep only objectives inside the playable area (the terrain map). Some maps are a small
        part of a larger battlefield and the scene holds objectives of the whole battlefield."""
        t = self.terrain
        if not objectives:
            return []
        only = [n.lower() for n in self.config.get("mission", {}).get("objectives_only") or []]
        if only:
            kept = [o for o in objectives if str(o.get("name", "")).lower() in only]
            if kept:
                objectives = kept
            elif not self.only_warned:
                self.only_warned = True
                print("  WARNING: none of the objectives in mission.objectives_only exists on this map; "
                      "the list is ignored (empty it or update it for this mission)")
        wanted = self.goal_objective_names()
        if wanted and not (only and kept):
            kept = [o for o in objectives if self.goal_names_match(o, wanted)]
            if kept:
                objectives = kept    # the mission goals say which objectives decide the battle
        if t is None:
            return list(objectives)
        margin = 100.0
        return [o for o in objectives
                if t.min_x - margin <= o["x"] <= t.max_x + margin
                and t.min_z - margin <= o["z"] <= t.max_z + margin]

    def note_terrain(self, msg, log_path):
        try:
            terrain = TerrainMap(msg)
        except (KeyError, TypeError, ValueError) as e:
            print("  Could not read the terrain description:", e)
            return
        self.finish_battle(None, None, log_path)   # a terrain message means the previous battle is over
        self.goals = []          # goals of the previous battle must not filter this map's objectives
        self.foe_memory = {}
        self.briefing, self.assault_mem, self.relief_clock, self.unpack_tries = {}, {}, {}, {}
        self.saved_plan, self.stop_loss_until = None, 0.0
        self.roster, self.roster_text, self.last_call_snap = {}, [], None
        self.skips_in_row, self.manual_arrivals, self.seen_foes = 0, 0, set()
        self.scale_name = None
        set_known_foes([])
        self.terrain = terrain
        all_objectives = terrain.objectives
        terrain.objectives = self.in_play(all_objectives)
        if len(terrain.objectives) != len(all_objectives):
            print(f"  Ignoring {len(all_objectives) - len(terrain.objectives)} objective(s) outside "
                  "the playable area (the map is part of a larger battlefield)")
        self.report = BattleReport(objectives=terrain.objectives)
        self.engaged = False   # a terrain message means a new battle (or a reconnection)
        self.last_cmds, self.last_change = {}, None
        log_event(log_path, "terrain", msg)
        cfg = self.config["terrain"]
        print(f"Terrain received: {terrain.cols}x{terrain.rows} cells of {terrain.step:.0f} units, "
              f"x {terrain.min_x:.0f}..{terrain.max_x:.0f}, z {terrain.min_z:.0f}..{terrain.max_z:.0f}, "
              f"{len(terrain.crossings())} ford/bridge site(s), {len(terrain.objectives)} objective(s)")
        if cfg.get("print_map"):
            text, cell = terrain.overview(cfg["overview_cols"])
            print("Legend: " + ", ".join(f"{s} = {n}" for s, n in terrain.legend.items()))
            print(f"Overview map (one character = about {cell:.0f} units, largest z at the top):")
            print(text)

    def track(self, state):
        """Feed one state message to the battle report (kill/death statistics)."""
        if self.report is None:
            self.report = BattleReport()
        self.report.update(state)
        self.remember_foes(state)

    def remember_foes(self, state):
        """Last known position of every enemy unit seen, for what is out of sight now (fog of war)."""
        now = float(state.get("time", 0.0))
        for u in state["units"]:
            if u["side"] == state["playerSide"]:
                self.foe_memory[u["id"]] = {"id": u["id"], "name": u["name"], "kind": u["kind"],
                                            "x": u["x"], "z": u["z"], "hp": u["hp"], "morale": u.get("morale", 1.0),
                                            "status": "", "t": now}
        horizon = float(DEFAULT_SUPPLY.get("memory_s", 900.0))
        visible = {u["id"] for u in state["units"] if u["side"] == state["playerSide"]}
        set_known_foes([m for i, m in self.foe_memory.items() if i not in visible and now - m["t"] <= horizon])

    def finish_battle(self, game_result, objectives, log_path, goals=None, result_kind=None):
        """Close the battle in progress: print the report, save it and update the scoreboard."""
        report, self.report = self.report, None
        if report is None or report.states == 0:
            return
        mission = self.config.get("mission", {})
        goals = goals or self.goals
        result = report.finish(game_result, self.in_play(objectives) or self.last_objectives,
                               self.config.get("scoring"), mission.get("player_rule"),
                               result_kind == "battle" or bool(mission.get("trust_game_result")), goals)
        result["goals"] = goals
        result["game_result_kind"] = result_kind     # "battle" (player's result) or "mission" (internal)
        self.goals = []
        backend_name = self.config["backend"]
        model = self.config.get(backend_name, {}).get("model") if isinstance(self.config.get(backend_name), dict) else None
        label_ = f"{backend_name}:{model}" if model else backend_name
        result["backend"] = label_
        result["llm_calls"], result["quiet_turns_skipped"] = self.llm_calls, self.skipped_turns
        result["battle_size"] = self.scale_name
        if self.tokens:
            result["tokens"] = dict(self.tokens)
            print("Tokens this battle: " + self.usage_text(self.tokens)
                  + f" | {self.llm_calls} model call(s), {self.skipped_turns} quiet turn(s) skipped")
        self.tokens, self.llm_calls, self.skipped_turns = Counter(), 0, 0
        journal, stats, owner_log = self.journal, self.stats, self.owner_log
        self.pending_moves, self.line_memory, self.owners = {}, {}, {}
        self.last_objectives, self.journal, self.stats, self.owner_log = [], [], {}, []
        scoreboard = record(report=result, backend_name=label_)
        log_event(log_path, "battle_report", result)
        print(format_report(result))
        print(scoreboard_line(scoreboard))
        self.previous_orders = []
        self.last_cmds, self.last_change = {}, None
        self.events = []
        if (self.backend is not None and self.config.get("assessment", {}).get("enabled")
                and result["outcome"] != "no_contest"):
            print("Writing the after-action review (this can take a minute)...")
            try:
                text, path = write_assessment(
                    self.backend, label_, result, journal, stats, owner_log, report.timeline,
                    read_text("strategy.md"), read_text("game_rules.md"))
                log_event(log_path, "assessment", {"text": text, "file": path})
                print("=" * 64)
                print(text)
                print("=" * 64)
                print("Review saved to", path)
            except (BackendError, OSError, ValueError, TypeError) as e:
                print("Could not write the after-action review:", e)

    def situation_for(self, state):
        objectives, stale = self.in_play(state.get("objectives")), False
        if not objectives and self.terrain is not None:
            objectives, stale = self.terrain.objectives, True   # old plugin: owners at battle start
        if objectives and not stale:
            self.last_objectives = objectives
            self.note_owners(state, objectives)
        self.plan_info = self.make_plan(state, objectives or [])
        override = self.plan_info["posture"] if self.plan_info else None
        lines = situation_lines(state, objectives or [], stale, self.config.get("posture"), override)
        mode = self.plan_info["mode"] if self.plan_info else None
        if mode != self.last_mode and mode is not None:
            print(f"  Strategic plan: {mode}" + (f" (kill/death {self.report.kd_men():.2f})" if self.report else ""))
            self.events.append(f"your strategic plan is now {mode}")
            self.last_mode = mode
        if mode in (None, "ATTACK") and objectives and not stale and self.engaged and self.last_change is not None:
            since = (float(state.get("time", 0.0)) - self.last_change) / 60.0
            lines += stalemate_lines(state, objectives, since, self.config.get("posture"))
        return lines

    def thought_command(self, state, cfg):
        """Short text for the in-game panel: plan mode, kill/death and the first words of the reasoning."""
        limit = int(cfg.get("max_chars", 260))
        text = " ".join(str(self.journal[-1]["reasoning"] if self.journal else "").split())
        if len(text) > limit:
            cut = text[:limit]
            end = max(cut.rfind(". "), cut.rfind("; "))
            text = (cut[:end + 1] if end > limit // 2 else cut.rstrip() + "...")
        mode = self.plan_info["mode"] if self.plan_info else ""
        kd = self.report.kd_men() if self.report else None
        return {"cmd": "thought", "mode": mode, "kd": None if kd is None else round(kd, 2),
                "time": int(float(state.get("time", 0.0))), "text": text}

    def goal_objective_names(self):
        """Normalised names of the objectives the mission goals ask the player to hold."""
        names = set()
        for entry in self.goals or []:
            for g in list(entry.get("or") or []) + list(entry.get("and") or []):
                if g.get("type") == "CaptureObjectivePoint":
                    for key in ("message", "objective"):
                        if g.get(key):
                            names.add(_norm(str(g[key])))
        return names

    @staticmethod
    def goal_names_match(objective, wanted):
        name = _norm(str(objective.get("name", "")))
        return bool(name) and any(name == w or name in w for w in wanted)

    def make_plan(self, state, objectives):
        """Attack / defend / trade decision from the mission goals read in the game (None without them)."""
        pcfg = {**PLAN_DEFAULTS, **(self.config.get("plan") or {})}
        if not self.goals or not pcfg.get("enabled", True):
            return None
        since = ((float(state.get("time", 0.0)) - self.contact_time) / 60.0) if self.contact_time is not None else 0.0
        rep = self.report
        kd = rep.kd_men() if rep else 1.0
        if rep and rep.own_start > 0:
            # Absolute thresholds are for ~16,000 men; brigades can be up to 6000 men: scale with the army.
            pcfg["min_casualties"] = max(float(pcfg["min_casualties"]), 0.02 * rep.own_start)
            pcfg["stop_loss_min"] = max(float(pcfg["stop_loss_min"]), 0.01 * rep.own_start)
        now = float(state.get("time", 0.0))
        pcfg["force_stop_loss"] = now < self.stop_loss_until      # a triggered stop-loss lasts a minimum time
        try:
            res = make_plan(self.goals, state, objectives, kd, since,
                            rep.own_loss if rep else 0.0, rep.foe_loss if rep else 0.0, pcfg,
                            rep.recent(600.0) if rep else None)
            if res and res.get("stop_loss") and not pcfg["force_stop_loss"]:
                self.stop_loss_until = now + float(pcfg.get("stop_loss_hold_s", 480))
                print(f"  STOP-LOSS: trading fire for at least {float(pcfg.get('stop_loss_hold_s', 480)) / 60:.0f} min")
            return res
        except Exception as e:      # the plan is advice: never stop the battle for it
            print("  Strategic plan failed:", e)
            return None

    def defending(self, state):
        """True when the plan (or else the force ratio) says not to advance on the enemy."""
        if self.plan_info is not None:
            return self.plan_info["mode"] in ("DEFEND", "TRADE")
        from situation import strength
        cfg = self.config.get("posture") or {}
        if not cfg.get("enabled", True):
            return False
        mine, foes = split_units(state)
        if not foes:
            return False
        a, b = strength(mine), strength(foes)
        return b > 0 and a / b <= float(cfg.get("defend_ratio", 0.8))

    def note_owners(self, state, objectives):
        """Report objective ownership changes (console + EVENTS in the next prompt)."""
        mine = [u for u in state["units"] if u["side"] != state["playerSide"]]
        ai_side = mine[0]["side"] if mine else None
        now = {o.get("name", "?"): ("OURS" if str(o.get("side")) == ai_side else
                                    "ENEMY" if str(o.get("side")) == state["playerSide"] else "UNHELD")
               for o in objectives}
        for name, who in now.items():
            before = self.owners.get(name)
            if before is not None and before != who:
                self.owner_log.append((float(state.get("time", 0.0)), name, before, who))
                self.last_change = float(state.get("time", 0.0))
                text = f"objective {name} changed owner: {before} -> {who}"
                print("  " + text)
                self.events.append(text)
        if not self.owners:
            held = {w: sum(1 for x in now.values() if x == w) for w in ("OURS", "ENEMY", "UNHELD")}
            print(f"  Objectives at start: {held['OURS']} ours, {held['ENEMY']} enemy, {held['UNHELD']} unheld")
            for o in objectives:
                print(f"    - {o.get('name')} at {o.get('x')},{o.get('z')} | owner {now[o.get('name', '?')]}"
                      f" (game side {o.get('side')}) | {o.get('victoryPoints')} VP | radius {o.get('radius')}")
            t = self.terrain
            if t is not None:
                print(f"    playable area: x {t.min_x:.0f}..{t.max_x:.0f}, z {t.min_z:.0f}..{t.max_z:.0f}")
        self.owners = now

    def performance_lines(self):
        mission = self.config.get("mission", {})
        lines = (self.report.live_lines(None if self.goals else mission.get("casualty_goal"), self.last_objectives,
                                        None if self.goals else mission.get("player_rule"))
                 if self.report else [])
        lines = goals_lines(self.goals) + (self.plan_info["lines"] if self.plan_info else []) + lines
        sb = load_scoreboard()
        if sb["battles"]:
            lines.append("YOUR RECORD IN PREVIOUS BATTLES: " + scoreboard_line(sb))
        return lines

    def assault_block(self, state, ranges, terrain):
        """Briefing text and the ASSAULT PLAN block for the prompt."""
        acfg = self.config.get("assault")
        objectives = self.last_objectives or []
        lines = briefing_lines(self.briefing, objectives, acfg)
        plan = assault_lines(state, self.plan_info, acfg, self.assault_mem, ranges, terrain, self.saved_plan)
        return lines + ([""] if lines and plan else []) + plan

    def terrain_for_prompt(self):
        if self.terrain is None or not self.config["terrain"].get("in_prompt"):
            return None
        return self.terrain

    def note_event(self, msg):
        if msg.get("type") == "done" and not msg.get("canceled"):
            self.pending_moves.pop(msg.get("id"), None)
            self.events.append(f"{label(self.names, msg.get('id'))} reached its destination")
            if not (self.last_cmds.get(msg.get("id")) or {}).get("auto"):
                self.manual_arrivals += 1   # a move the model ordered is done: it may want to decide again
            self.events = self.events[-20:]

    @staticmethod
    def usage_text(u):
        return (f"in {u.get('input', 0)} + cache read {u.get('cache_read', 0)} + cache written "
                f"{u.get('cache_write', 0)}, out {u.get('output', 0)}")

    def note_usage(self):
        """Adds the token usage of the last model call to the battle total; returns it (normalised)."""
        info = getattr(self.backend, "last_info", {}) or {}
        raw = info.get("usage") or {}
        u = {"input": raw.get("input_tokens", info.get("prompt_tokens")) or 0,
             "cache_read": raw.get("cache_read_input_tokens") or 0,
             "cache_write": raw.get("cache_creation_input_tokens") or 0,
             "output": raw.get("output_tokens", info.get("completion_tokens")) or 0}
        u = {k: int(v) for k, v in u.items() if isinstance(v, (int, float))}
        self.tokens.update(u)
        return u

    def call_snapshot(self, state):
        mine, foes = split_units(state)
        return {"time": float(state.get("time", 0.0)),
                "own": {u["id"]: (float(u["morale"]), float(u["hp"]), u.get("status", "")) for u in mine},
                "foes": {u["id"] for u in foes},
                "mode": self.plan_info["mode"] if self.plan_info else None,
                "launched": bool(self.assault_mem.get("launched"))}

    def quiet_turn(self, state):
        """True when nothing happened since the last model call that needs a decision. The server's own
        automatons (relief, assault, guard, engage, ammo, supply, unpack, reserve) still run that turn.
        Returns (quiet, reason for calling)."""
        ecfg = self.config.get("economy") or {}
        last = self.last_call_snap
        if not ecfg.get("skip_quiet_turns", True) or last is None:
            self.seen_foes |= {u["id"] for u in split_units(state)[1]}
            return False, "first call"
        snap = self.call_snapshot(state)
        if self.skips_in_row >= int(ecfg.get("max_consecutive_skips", 1)):
            return False, "skip limit"
        if snap["time"] - last["time"] >= float(ecfg.get("max_gap_s", 150)):
            return False, "time"
        if any(not e.endswith("reached its destination") for e in self.events) or self.manual_arrivals:
            return False, "events"
        if snap["mode"] != last["mode"] or snap["launched"] != last["launched"]:
            return False, "plan"
        if snap["mode"] == "ATTACK" and not self.saved_plan:
            return False, "no attack plan yet"
        new_foes = snap["foes"] - self.seen_foes      # never seen before in this battle (not just back in view)
        self.seen_foes |= snap["foes"]
        if new_foes:
            return False, "new enemy"
        start = self.report.own_start if self.report else 0
        lost = 0.0
        for uid, (morale, hp, status) in snap["own"].items():
            before = last["own"].get(uid)
            if before is None:
                return False, "new unit"
            if status != before[2]:
                return False, "unit status"
            if before[0] - morale >= float(ecfg.get("morale_drop", 0.1)):
                return False, "morale drop"
            lost += max(0.0, before[1] - hp)
        if lost >= max(float(ecfg.get("loss_men", 100)), float(ecfg.get("loss_share", 0.01)) * start):
            return False, "losses"
        return True, ""

    def update_roster(self, mine):
        """Fixed equipment of our units, given once in the system prompt (kept as long as the battle lasts,
        so the system prompt stays identical and cached; a later reinforcement is added once)."""
        added = False
        for u in mine:
            if u["id"] not in self.roster:
                static = equipment_static(u)
                if static:
                    self.roster[u["id"]] = static
                    self.roster_text += roster_lines([u])
                    added = True
        return added

    def battle_scale(self, mine):
        """'small' or 'large' (config "scale"), announced once per battle; returns (name, profile or None)."""
        scfg = self.config.get("scale") or {}
        combat = sum(1 for u in mine if u["kind"] in ("Infantry", "Cavalry", "Artillery", "Skirmish"))
        name = scfg.get("force") or ("large" if combat >= int(scfg.get("large_threshold", 40)) else "small")
        if name != self.scale_name:
            print(f"  Battle size: {name} ({combat} combat units of yours)"
                  + (": compact prompt for the units far from the fight" if name == "large" else ""))
            self.scale_name = name
        return name, (scfg.get("large") if name == "large" else None)

    def plan(self, state, log_path):
        DEFAULT_SUPPLY.update(self.config.get("supply") or {})
        DEFAULT_CAVALRY.update(self.config.get("cavalry") or {})
        DEFAULT_BATTERY.update(self.config.get("battery") or {})   # shared by the prompt and the order checks
        if self.backend is None:
            return placeholder_plan(state)
        mine, _ = split_units(state)
        if not mine:
            return []
        max_orders = self.config["max_orders_per_cycle"]
        terrain = self.terrain_for_prompt()
        if terrain is None and self.terrain is None and not self.terrain_warned:
            self.terrain_warned = True
            print("  No terrain description received yet: the model plans without a map.")
        ranges = self.config["ranges"]
        situation = self.situation_for(state) + self.performance_lines() + self.assault_block(state, ranges, terrain)
        quiet, why = self.quiet_turn(state)
        if quiet:
            self.skips_in_row += 1
            self.skipped_turns += 1
            print("  Quiet turn: no model call (nothing changed that needs a decision); server automatons only")
            reasoning, raw, raw_orders, orders = None, "", [], []
        else:
            tcfg = self.config["terrain"]
            terrain_text = terrain.prompt_text(tcfg["overview_cols"], tcfg["height_cols"],
                                               tcfg["show_heights"], tcfg["show_rules"]) if terrain else ""
            use_roster = bool((self.config.get("economy") or {}).get("static_roster", True))
            if use_roster:
                self.update_roster(mine)
            system = build_system_prompt(mine[0]["side"], max_orders, read_text("strategy.md"),
                                         terrain_text, ranges,
                                         read_text("game_rules.md"),
                                         "\n".join(self.roster_text) if use_roster else "")
            user = build_user_prompt(state, self.previous_orders, self.events, terrain, ranges,
                                     self.config.get("line"), situation,
                                     self.line_memory, self.plan_info["mode"] if self.plan_info else None,
                                     self.roster if use_roster else None, self.battle_scale(mine)[1])
            started = time.time()
            raw = None
            try:
                extra = {"schema": ORDERS_SCHEMA} if getattr(self.backend, "supports_schema", False) else {}
                raw = self.backend.complete(system, user, **extra)
                reasoning, raw_orders = parse_answer(raw)
            except (BackendError, ValueError) as e:
                print("  LLM planning failed, units stay with the native AI:", e)
                if raw is not None and self.config.get("verbose"):
                    print("  --- raw model answer ---")
                    print(indent_block(raw.strip()))
                    print("  --- end of answer ---")
                log_event(log_path, "llm_error", {"error": str(e), "user": user, "raw": raw})
                return []
            seconds = time.time() - started
            orders = sanitize(raw_orders, state, max_orders, terrain, ranges.get("fire"), self.pending_moves,
                              self.stats)
            payload = {"user": user, "raw": raw, "seconds": round(seconds, 1),
                       "info": getattr(self.backend, "last_info", {})}
            if self.system_logged != system:      # logged again whenever it changes (new battle, roster)
                payload["system"] = system
                self.system_logged = system
            log_event(log_path, "llm", payload)
            cost = payload["info"].get("cost_usd") if payload["info"] else None
            cost_txt = f", ~${cost:.3f}" if isinstance(cost, (int, float)) else ""
            used = self.note_usage()
            self.llm_calls += 1
            self.skips_in_row = 0
            self.manual_arrivals = 0
            self.last_call_snap = self.call_snapshot(state)
            if used and (self.config.get("economy") or {}).get("log_usage", True):
                cost_txt += " | tokens " + self.usage_text(used)
            print(f"  LLM answered in {seconds:.0f}s{cost_txt}: {reasoning}")
            if self.config.get("verbose"):
                if self.config["verbose"] == "full":
                    print("  --- prompt sent to the model ---")
                    print(indent_block(user))
                print("  --- raw model answer ---")
                print(indent_block(raw.strip()))
                print("  --- end of answer ---")
        dropped = len(raw_orders) - len(orders)
        if dropped > 0:
            print(f"  {dropped} invalid or surplus order(s) dropped")
        written = extract_plan(raw)
        if written:
            self.saved_plan = (float(state.get("time", 0.0)), written)
            print("  Attack plan:", written)
        a_drop, a_new = assault_orders(state, orders, self.plan_info, self.config.get("assault"), self.last_cmds,
                                       self.pending_moves, ranges, terrain, self.assault_mem, self.stats)
        if a_drop or a_new:
            orders = [o for o in orders if o["id"] not in a_drop] + a_new
            print("  Server ran the assault plan: " + "; ".join(order_text(o, self.names) for o in a_new))
        r_drop, r_new = relief_orders(state, orders, self.config.get("relief"), self.last_cmds, self.pending_moves,
                                      terrain, self.relief_clock, self.stats, set(self.assault_mem.get("group") or []))
        if r_drop or r_new:
            orders = [o for o in orders if o["id"] not in r_drop] + r_new
            print("  Server pulled back broken brigades / sent replacements: "
                  + "; ".join(order_text(o, self.names) for o in r_new))
        drop, guard = guard_artillery(state, orders, self.config.get("guard"), terrain, self.pending_moves,
                                      self.stats)
        if drop:
            orders = [o for o in orders if o["id"] not in drop or o["cmd"] == "ammo"] + guard
            print("  Server pulled back unprotected batteries: "
                  + "; ".join(order_text(o, self.names) for o in guard))
        defending = self.defending(state)
        extra = engage_orders(state, orders, ranges, self.config.get("engage"), self.last_cmds,
                              self.pending_moves, defending, self.stats)
        extra += ammo_orders(state, orders + extra, self.config.get("ammo"), self.stats)
        extra += supply_orders(state, orders + extra, self.config.get("supply"), terrain, self.pending_moves,
                               self.stats)
        extra += ride_down_orders(state, orders + extra, self.config.get("cavalry"), self.last_cmds,
                                  self.stats)
        extra += unpack_orders(state, orders + extra, self.pending_moves, self.stats, self.unpack_tries)
        extra += reserve_orders(state, orders + extra, self.config.get("relief"), self.last_cmds, self.pending_moves,
                                self.plan_info["mode"] if self.plan_info else None, terrain, self.stats)
        if extra:
            print(f"  Server added {len(extra)} order(s) for idle units or batteries: "
                  + "; ".join(order_text(o, self.names) for o in extra))
            orders = orders + extra
        for o in orders:
            if o["cmd"] not in ("ammo", "supply", "limber"):
                self.last_cmds[o["id"]] = o
        if quiet:
            # the model's orders of its last turn are still running: keep them listed, newest first
            ids = {o["id"] for o in orders}
            self.previous_orders = orders + [o for o in self.previous_orders if o["id"] not in ids]
        else:
            self.previous_orders = orders
            self.events = []
            self.journal.append({"time": float(state.get("time", 0.0)), "reasoning": str(reasoning),
                                 "orders": dict(Counter(o["cmd"] for o in orders))})
        return orders


def handle(f, msg, log_path, commander, config):
    kind = msg.get("type")
    if kind == "state":
        commander.names = {u["id"]: u["name"] for u in msg["units"]}
        if msg.get("battleGoals"):
            commander.goals = msg["battleGoals"]
        if msg.get("briefing"):
            commander.briefing = msg["briefing"]
        commander.track(msg)
        try:
            orders = commander.plan(msg, log_path)
        except Exception:
            traceback.print_exc()
            orders = []
        if config.get("dry_run"):
            print("  dry run: orders are logged but not sent")
            to_send = []
        else:
            to_send = orders
        for order in to_send:
            send(f, order)
            if order["cmd"] == "move":
                commander.pending_moves[order["id"]] = (order["x"], order["z"], msg["time"])
            elif order["cmd"] not in ("ammo", "supply", "limber"):   # a switch does not interrupt a march
                commander.pending_moves.pop(order["id"], None)
        commander.pending_moves = {k: v for k, v in commander.pending_moves.items()
                                   if msg["time"] - v[2] < 240}
        delay, why = commander.next_delay(msg)
        if config.get("overlay", {}).get("enabled", True):
            send(f, commander.thought_command(msg, config.get("overlay", {})))   # in-game text panel
        send(f, {"cmd": "plan_done", "next_in": delay})  # tells the game to resume
        log_event(log_path, "state", msg)
        # The log copy carries unit names so the log is readable; the orders sent to the game do not.
        log_event(log_path, "orders", [dict(o, text=describe_order(o, commander.names)) for o in orders])
        summary = dict(Counter(o["cmd"] for o in orders))
        print(f"t={msg['time']:.0f}s units={len(msg['units'])} orders={len(orders)} {summary}")
        for order in orders:
            print("   ", describe_order(order, commander.names))
        print(f"    next planning pause in {delay}s of play ({why})")
    elif kind == "terrain":
        commander.note_terrain(msg, log_path)
    elif kind == "battle_end":
        print("Battle ended. Game text:", msg.get("result"), f"({msg.get('resultKind') or 'unknown kind'});",
              "internal mission text:", msg.get("missionResult"))
        commander.finish_battle(msg.get("result"), msg.get("objectives"), log_path,
                                msg.get("battleGoals"), msg.get("resultKind"))
    else:
        commander.note_event(msg)
        log_event(log_path, "event", msg)
        print("Event:", msg)


def serve(config, commander):
    os.makedirs(LOG_DIR, exist_ok=True)
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((HOST, PORT))
    srv.listen(1)
    print(f"UGCW AI Commander v{VERSION}")
    print(f"Backend: {config['backend']}. Waiting for the game on {HOST}:{PORT} "
          "(close the window to stop)")
    while True:
        conn, addr = srv.accept()
        log_path = os.path.join(LOG_DIR, time.strftime("battle-%Y%m%d-%H%M%S.jsonl"))
        print("Game connected:", addr, "| log file:", log_path)
        f = conn.makefile("rw", encoding="utf-8", newline="\n")
        try:
            for line in f:
                try:
                    msg = json.loads(line)
                except ValueError:
                    print("Ignoring invalid line:", line[:80])
                    continue
                handle(f, msg, log_path, commander, config)
        except OSError as e:
            print("Connection lost:", e)
        finally:
            try:
                f.close()
            except OSError:
                pass
            conn.close()
        commander.finish_battle(None, None, log_path)   # battle cut short: report with what we know
        print("Game disconnected, waiting for a new connection...")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        # Never crash on a character the Windows console cannot display.
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    # Make config.json, strategy.md, logs/ and claude_workdir/ relative to this script.
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    config = load_config()
    try:
        commander = Commander(config)
    except BackendError as e:
        raise SystemExit(f"Cannot start the planner: {e}")
    serve(config, commander)


if __name__ == "__main__":
    main()
