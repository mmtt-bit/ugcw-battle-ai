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
import re
import math
import os
import socket
import sys
import time
import traceback
from collections import Counter

from backends import BackendError, make_backend
from equipment import equipment_static, roster_lines
import perks as perks_mod
from routes import DEFAULT_ROUTES, add_routes
from cohesion import DEFAULT_COHESION, cohesion_orders
from march import DEFAULT_MARCH, march_note, march_orders
from final_charge import DEFAULT_FINAL, final_charge_orders
from prompting import (ORDERS_SCHEMA, build_system_prompt, build_user_prompt, parse_answer, extract_plan, extract_assaults,
                       sanitize, split_units, label, order_text)
from report import (BattleReport, format_report, record, scoreboard_line, load_scoreboard)
from assessment import write_assessment
from goals import PLAN_DEFAULTS, goals_lines, make_plan
from battery import DEFAULT_BATTERY, battery_orders, unpack_orders
from cavalry import DEFAULT_CAVALRY, ride_down_orders
from situation import situation_lines, stalemate_lines
from supply import DEFAULT_SUPPLY, set_known_foes, supply_orders
from autopilot import (DEFAULT_AMMO, DEFAULT_ENGAGE, DEFAULT_GUARD, ammo_orders, engage_orders,
                       guard_artillery)
import battery as battery_mod
from discipline import capture_status, discipline_orders, mark_offmap
from tactics import arrivals_lines, breach_lines, hold_line_orders, hunt_orders, note_field, pursuit_orders
from fire import counter_battery_lines, counter_battery_orders, counter_battery_override
from works import crossing_lines, fortification_lines
from column import AssaultColumn, column_offer, parse_directive as parse_column, reinforcement_lines
from prompting import load_answer
from relief import rally_orders
from exchange import (ExchangeTracker, exchange_lines, flank_threats, force_lines, is_trap, refuse_flank_orders,
                      threat_lines, pull_orders)
from skirmish import skirmish_lines, skirmish_orders
from flank import flank_lines, flank_orders
from fire import fire_lines, fire_orders
from relief import is_resting
from withdraw import PASS as WITHDRAW_PASS, Withdrawal, battery_escape_orders, rest_orders
from assault import DEFAULT_ASSAULT, assault_lines, assault_orders, briefing_lines, briefing_static, phase_clock
from relief import DEFAULT_RELIEF, relief_orders, reserve_orders, set_return_morale, situation_level
import cavalry as cavalry_mod
from generals import DEFAULT_GENERALS, general_lines, general_orders, sanitize_generals
from terrain_rules import DEFAULT_TERRAIN_RULES, cover_orders, filter_orders, unseen_fire_lines, unseen_orders, woods_orders
from terrain import TerrainMap

VERSION = "0.1.4-beta"
HOST, PORT = "127.0.0.1", 8765
LOG_DIR = "logs"

LLM_PLUS_NOTE = """

MODEL-PLUS MODE (this battle overrides everything above about the server)
You command. The server does no staff work for you: no plan, no assault groups ("assaults" and "plan" are
ignored), no final charge, no automatic charges, no pull-backs, relief, replacement, reserve or withdrawal, no
fire focus or battery placement, no cover or woods moves, no cohesion checks, no routes and no formations: set
"formation" yourself (RoadColumn to march, Line before contact). A unit you give no order keeps its last order.
The only help, never replacing an order of yours this turn (one exception, below):
- a battery you leave without an order fires at an enemy battery in its range when no enemy foot or horse is within
  350 (rifled) or 400 (smoothbore) of it (counter-battery); the exception: a rifled battery you order to fire at
  infantry or cavalry farther than 800 while an enemy battery is in its range fires at that battery instead;
- a brigade under 0.3 morale you leave without an order goes to the highest ground 300-600 behind it to rally;
- a battery with enemy foot or horse within about 800 and no steady brigade within 300 falls back behind the
  nearest steady brigade; a battery whose march ended is unpacked;
- the game's reflexes: facing a flank attack, bracing against a charge, stepping back a broken unit, skirmishers
  and batteries away from cavalry (REFLEXES lines). There is no answer to unseen fire: that is yours.
ASSAULT COLUMN (the one macro command the server executes for you here): to take a defended objective with a
large force, add to your answer
  "assault_column": {"objective": "<objective name>", "from": [[x, z]] or [[x1, z1], [x2, z2]], "go": true}
The server takes about 80 % of your fit infantry (morale 0.6+, stamina 0.5+) with skirmishers, cavalry and up to
two batteries per group, one group per "from" point (two or three points = an envelopment from several sides). Each
group gathers 1,250 from the objective on the line from that point, out of rifle range, in two ranks: the biggest
brigade(s) in front to take the fire, the charging brigades 160 behind, skirmishers on the flanks, cavalry behind,
guns on the flanks firing. Then every group advances by steps of 150 on the same line, so that all arrive
together; at 550 from the objective the front rank and the guns fire until the zone count is GO (at most 5
minutes), then every unit with morale and stamina 0.5+ charges. It stops if the column's morale falls under 0.45
or the zone stays TOO FEW / RECONSIDER for 3 minutes (back to the gather line), or when you send
"assault_column": {"cancel": true}. While it runs, your orders to its units are ignored except fallback. Use it
when ASSAULT COLUMN possible shows (1.5 to 1 or better) and early, before the enemy's reinforcements arrive.
"""

LLM_ONLY_NOTE = """

MODEL-ONLY MODE (this battle overrides everything above about the server)
The server is switched off. Only your orders reach the army, checked for validity and nothing else. There is NO
staff work: no assault groups ("assaults" and "plan" are ignored), no final charge, no automatic charges, no
pull-backs, relief, reserve or withdrawal, no reflexes (facing, bracing, unseen fire, cavalry), no fire focus or
battery placement, no cover or woods moves, no cohesion checks, no routes and no formations: set "formation"
yourself (RoadColumn to march, Line before contact). A unit you give no order keeps its last order. The only help:
a battery whose march ended is unpacked. Everything the rules say the server does, you must now order yourself,
an ASSAULT COLUMN too (strategy: ASSAULT COLUMN, step by step).
"""

DEFAULT_CONFIG = {
    "backend": "ollama",
    "max_orders_per_cycle": 60,
    "dry_run": False,
    # 0.1.4 WIP13: true = the model commands alone. The server only checks and forwards its orders (plus the
    # unpacking of a battery whose march ended, a game mechanic); no plan, assault, relief, withdrawal, fire,
    # cover, cohesion, formation, route or skirmish work, and the plugin's reflexes are off. For testing the model.
    "llm_only": False,
    # 0.1.4 WIP15: true (and llm_only false) = the model commands, the server keeps only the help that does not
    # move the line for it: counter-battery fire, rally of broken brigades on high ground, lone batteries pulled
    # back behind the infantry, battery unpacking, and the plugin's facing / bracing / safety / cavalry reflexes
    # (no unseen-fire reflex). Crampton's Gap 2026-11-14: model alone k/d 0.52 against 0.44 with the full staff.
    "llm_plus": False,
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
    "overlay": {"enabled": True, "max_chars": 260,    # in-game panel with the last reasoning (F6 hides it);
                "show_ai_orders": False},           # True shows the arrows of the AI orders (testing only)
    "plan": dict(PLAN_DEFAULTS),      # attack / defend / trade decision from the mission goals, see goals.py
    "cavalry": dict(DEFAULT_CAVALRY),   # cavalry roles: reserve, flanks, early scout, see cavalry.py
    "battery": dict(DEFAULT_BATTERY),   # artillery readiness and placement, see battery.py
    "supply": dict(DEFAULT_SUPPLY),   # supply wagons rearm batteries and brigades, see supply.py
    "scale": {                         # short battles get every detail; large ones a compact prompt
        "force": None,                 # None = automatic, or "small" / "large"
        "large_threshold": 40,         # own combat units (infantry, cavalry, artillery, skirmishers) for "large"
        "small": {
            "detail_radius": 1500,     # own units (not artillery) farther than this from every visible enemy: short line
            "route_radius": 800,       # terrain along the way to the nearest enemy only this close
        },
        "large": {
            "detail_radius": 1200,     # own units farther than this from every visible enemy: short line
            "route_radius": 800,       # terrain along the way to the nearest enemy only this close
            "enemy_detail_radius": 900,  # enemy terrain/equipment only this close to one of your units...
            "max_enemy_detail": 30,    # ...and for at most this many (nearest first)
            "max_charge": 8,           # CHARGE OPPORTUNITIES lines
            "max_lanes": 6,            # FIRE LANES lines
        },
    },
    "perks": {                         # perk effects of the Rebalance mod, see perks.py
        "folder": "perks/jp-rebalance-1.29.1",   # <Kind>PerksBonuses.txt files (copied from <game>/Mod/Rebalance/Data/)
        "label": "J&P Rebalance 1.29.1",
        "show_in_prompt": True,        # the PERKS block (what every perk does) in the cached system prompt
    },
    "doctrine": {
        # One knob for the AI general's character, from 0 (very careful) to 1 (very aggressive). null keeps the
        # values of each block; a number overwrites the settings listed in apply_doctrine() (0.5 = the defaults).
        "aggressiveness": None,
    },
    "economy": {                       # token savings, see Commander.quiet_turn and the YOUR BRIGADES roster
        "static_roster": True,         # fixed equipment of your units once in the (cached) system prompt
        "skip_quiet_turns": True,      # no model call when nothing worth a decision happened
        # The game sends a state every timing.engaged_interval_s; the server's own staff work (assaults, relief,
        # cover, cohesion...) runs at every state, the model is called only when a decision is worth it:
        "min_call_gap_s": 150,         # battle seconds between two model calls, except for a critical event
                                       # (objective changed hands, plan mode changed, a brigade broken)
        "max_gap_s": 420,              # never longer than this without a model call (battle seconds)
        "retry_backoff_s": 60,         # a lost answer is asked again at the next state; from the second loss in a
                                       # row the server waits this long, doubled at every further loss
        "loss_window_s": 150,          # losses are measured over about this long (unseen fire, cover, quiet turns)
        # Late arrivals keep their equipment in the unit table of every turn (a few dozen tokens a call for each
        # brigade, measured). Adding them to the cached roster rewrites the whole system prompt (about 21,000
        # tokens): on the replays that pays back only after some 40 further model calls, more than a battle has
        # left. So no addition by default; raise roster_max_folds for very long battles with many late brigades.
        "roster_fold": 12,             # brigades waiting before an addition to the cached roster...
        "roster_max_folds": 0,         # ...and how many additions a battle may have (0 = never)
        # The model is the commander (macro); the server handles the details between its calls, so only events
        # that change the big picture call it: a sizeable new enemy force, a brigade breaking, heavy losses.
        "new_enemy_men": 1200,         # newly seen enemy men worth a call (about a brigade)...
        "new_enemy_share": 0.04,       # ...or this share of your starting men, whichever is larger
        "morale_drop": 0.3,            # brigades losing this much morale since the last call...
        "morale_drop_units": 2,        # ...are worth a call when at least this many (or 15 % of the infantry) did
        "loss_men": 100,               # men lost since the last call that are worth a call...
        "loss_share": 0.01,            # ...or this share of the starting men, whichever is larger
        "log_usage": True,             # print the tokens of every call and the battle total
    },
    "assault": dict(DEFAULT_ASSAULT),   # assault group and attack plan on an objective, see assault.py
    "relief": dict(DEFAULT_RELIEF),
    "generals": dict(DEFAULT_GENERALS),
    "final_charge": dict(DEFAULT_FINAL),             # last-minutes mass charge on the objective, see final_charge.py
    "march": dict(DEFAULT_MARCH),                   # road column on long marches, line near the enemy, see march.py
    "cohesion": dict(DEFAULT_COHESION),             # no lone brigades far from the army, no chasing skirmishers
    "routes": dict(DEFAULT_ROUTES),                 # long moves along the fastest ground as waypoints, see routes.py
    "terrain_rules": dict(DEFAULT_TERRAIN_RULES),   # slow ground for charges / guns, unseen fire, see terrain_rules.py
    "reflexes": {                      # fast reactions run by the plugin between two turns (Reflexes.cs), no tokens
        "enabled": True, "face": True, "brace": True, "safety": True, "tick_s": 0.5,
        "face_radius": 350, "face_angle": 60, "face_cooldown_s": 20,
        "brace_radius": 250, "counter_radius": 300, "counter_morale": 0.7, "brace_cooldown_s": 15,
        "canister_range": 300, "battery_cover": 200, "battery_danger": 150,
        "wagon_danger": 450, "general_danger": 400, "run_away": 300,
        "panic_morale": 0.3, "panic_contact": 300, "safety_cooldown_s": 20,
        "unseen": True, "unseen_advance": False, "unseen_loss": 6, "unseen_share": 0.003, "unseen_reach": 650,
        "unseen_window_s": 60, "unseen_cooldown_s": 25, "unseen_advance_morale": 0.7, "unseen_step": 150, "unseen_aggressiveness": None,
        "engaged_interval_s": 90,      # turn interval in contact once the reflexes run, for a plugin older than
                                       # 0.1.4 (it pauses the game at every state); see timing.staff_interval_s
        "max_lines": 8,                # reflex events shown to the model per turn
    },   # generals follow their brigades (command radius), see generals.py   # pull back broken brigades, replace them, commit the reserve, see relief.py
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
        "min_calls": 3,          # no review for a battle left after fewer model calls than this (nothing to review)
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
        # Plugin 0.1.4 or later: a state no longer pauses the game (the server asks for the pause only when it
        # calls the model), so in contact the game sends one every staff_interval_s (game seconds; one game second
        # is about two battle seconds) and the server's own staff work runs at each of them. null: the intervals
        # above for every plugin.
        "staff_interval_s": 30,
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
        "cache_ttl": None,     # prompt cache lifetime asked from Claude Code: None (its default), "5m" or "1h"
    },
}


def command_mode(config):
    """"llm_only", "llm_plus" or "full" (llm_only wins when both are set)."""
    if config.get("llm_only"):
        return "llm_only"
    return "llm_plus" if config.get("llm_plus") else "full"


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


def apply_doctrine(config):
    """doctrine.aggressiveness (0 careful .. 1 aggressive) sets several settings at once; 0.5 gives the defaults."""
    a = (config.get("doctrine") or {}).get("aggressiveness")
    if a is None:
        return config
    a = max(0.0, min(1.0, float(a)))
    def put(block, key, value):
        config.setdefault(block, {})[key] = value
    put("plan", "min_attack_ratio", round(0.9 - 0.4 * a, 2))
    put("plan", "stop_loss_ratio", round(1.2 + 0.8 * a, 2))
    put("plan", "build_up_minutes", round(35 - 20 * a))
    put("assault", "ready_share", round(0.9 - 0.4 * a, 2))
    put("assault", "latest_launch_minutes", round(50 - 30 * a))
    put("assault", "abort_loss_share", round(0.25 + 0.2 * a, 2))
    put("assault", "launch_time_share", round(0.8 - 0.2 * a, 2))
    put("relief", "retreat_morale", round(0.6 - 0.2 * a, 2))
    put("engage", "charge_target_morale", round(0.3 + 0.4 * a, 2))
    put("engage", "max_charges", int(round(1 + 6 * a)))          # WIP12: 4 at 0.5 (was 2)
    put("assault", "group_share", round(0.35 + 0.3 * a, 2))
    put("assault", "charge_when_strong", a >= 0.5)               # WIP12: on by default
    put("assault", "reserve_keep", 1 if a >= 0.7 else None)
    put("assault", "charge_morale", round(0.4 + 0.4 * a, 2))     # WIP12: 0.6 at 0.5 (was 0.5)
    put("reflexes", "unseen_advance", a >= 0.7)
    put("reflexes", "unseen_aggressiveness", round(a, 2))
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
        self.config = apply_doctrine(config)
        self.backend = None if config["backend"] == "placeholder" else make_backend(config)
        self.previous_orders = []
        self.events = []
        self.report = None   # BattleReport of the battle in progress
        self.line_memory = {}     # remembered line slots (see front_line_plan)
        self.journal = []         # one entry per planning turn: time, reasoning, order counts
        self.stats = {}           # how often the server had to correct the model's orders
        self.owner_log = []       # (battle time, objective, before, after)
        self.pending_moves = {}   # unit id -> (x, z, game time) of moves not reported done yet
        self.pending_expiry = {}  # unit id -> game time after which a pending move counts as lost
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
        self.directives = []      # the model's macro command of the assaults ("assaults" in its answer)
        self.assault_mems = {}    # objective name -> assault state, for the assaults the model commands
        self.assault_groups = set()
        self.assault_sync = {}    # objective name -> {assault index: ready to launch}, for synchronised assaults
        self.final_mem = {}       # state of the final charge, see final_charge.py
        self.relief_clock = {}    # unit id -> battle time of the last pull-back order
        self.cohesion_mem = {}    # WIP13: isolated unit id -> battle time a supporting brigade was sent
        self.pending_phase, self.phases_done = None, 0   # WIP17: chained battles, one report for all phases
        self.exchange = ExchangeTracker(config.get("exchange"))   # WIP14: exchange of fire per sector
        self.threat_mem = {}      # WIP14: flank / battery threat -> battle time of the last order
        self.column = AssaultColumn(config.get("column"))   # WIP16: the model's assault column (llm_plus)
        self.arrived = {}         # WIP16: own unit id -> battle time first seen (reinforcements)
        self.roster_t0 = None
        self.unpack_tries = {}    # battery id -> unpack orders given while it stayed packed
        self.battery_clock = {}   # battery id -> battle time of its last placement by the server
        self.assault_abandoned = False   # the assault was given up for good (plan.abandon_ratio), see make_plan
        self.discipline = {}      # memory of the last-word rules (capture, steady moves, battery marches)
        self.flank_mem = {}       # brigade id -> time of the last flank-guard answer (flank.py)
        self.withdrawal = Withdrawal(config.get("withdraw"))   # tactical withdrawal / preservation (withdraw.py)
        self.rest_sent = {}       # resting brigade id -> rest spot sent
        self.fire_mem = {}        # fire.py memory
        self.tactics_mem = {}     # tactics.py memory (0.1.4 WIP9)
        self.skirmish_mem = {}    # skirmish.py memory (0.1.4 WIP10)
        self.prev_enemy_pos = {}  # enemy id -> (x, z) at the previous state (threats closing in)
        self.saved_plan = None    # (battle time, text): the attack plan the model wrote
        self.stop_loss_until = 0.0
        self.roster = {}          # unit id -> fixed equipment text given once in the system prompt
        self.roster_text = []
        self.tokens = Counter()   # token usage of the battle in progress
        self.llm_calls, self.skipped_turns, self.skips_in_row = 0, 0, 0
        self.last_call_snap = None
        self.manual_arrivals = 0  # moves ordered by the model that finished since the last call
        self.seen_foes = set()    # enemy ids seen at least once in this battle
        self.reflexes_live = False  # the plugin runs the reflexes (configured this battle)
        self.reflexes_sent = False
        self.sent_hold_line = None  # unseen_hold_line last sent to the plugin (resent when the plan mode changes)
        self.reflex_log = []      # reflex events since the last model call
        self.scale_name = None    # "small" or "large" battle (prompt detail), see battle_scale
        self.new_foe_men = 0.0    # enemy men seen for the first time since the last model call
        self.hp_history = []      # [(battle time, {unit id: hp})] of the last states, for losses over a window
        self.previous_hp = {}
        self.phase_start = None
        self.roster_folds = 0
        self.llm_failures = 0
        self.static_brief = None  # mission briefing and objective descriptions, once in the system prompt
        self.retry_call = False
        self.fail_streak, self.retry_after = 0, 0.0   # model calls lost in a row; battle time of the next try
        self.before_call = None   # called just before a model call (the plugin is asked to pause the game)
        self.columns = {}         # unit id -> battle time: units the server put in road column, see march.py
        self.foe_gaps = {}        # unit id -> (battle time, distance to the nearest known enemy)

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
            # (with economy.skip_quiet_turns off every state is a model call: keep the long interval then)
            if (state.get("soft") and timing.get("staff_interval_s")
                    and (self.config.get("economy") or {}).get("skip_quiet_turns", True)):
                return float(timing["staff_interval_s"]), "contact (staff work at every state, no pause)"
            rcfg = self.config.get("reflexes") or {}
            if self.reflexes_live and rcfg.get("engaged_interval_s"):
                return float(rcfg["engaged_interval_s"]), "contact (reflexes on)"
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
        if wanted and not (only and kept) and not self.multi_phase(objectives):
            kept = [o for o in objectives if self.goal_names_match(o, wanted)]
            if kept:
                objectives = kept    # the mission goals say which objectives decide the battle
        # multi-phase battles (Shiloh): some goals name objectives of later phases, and this map adds objectives
        # of its own that no goal names (Hornet's Nest in phase 3): every objective of the map stays in play
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
        if msg.get("update") and self.terrain is not None:
            # 0.1.4 WIP9: the same battle, a new stage that opened a new part of the map (plugin TerrainScan): the
            # map is replaced and the battle goes on (the battle state, the report and the plan are kept)
            old = self.terrain
            self.terrain = terrain
            cavalry_mod.set_terrain(terrain)
            all_objectives = terrain.objectives
            terrain.objectives = self.in_play(all_objectives)
            log_event(log_path, "terrain", msg)
            note = (f"The playing field changed: x {old.min_x:.0f}..{old.max_x:.0f}, z {old.min_z:.0f}..{old.max_z:.0f}"
                    f" -> x {terrain.min_x:.0f}..{terrain.max_x:.0f}, z {terrain.min_z:.0f}..{terrain.max_z:.0f}")
            print("  " + note + f" ({len(terrain.objectives)} objective(s))")
            self.events.append(note + ": units there can now be ordered")
            return
        self.finish_battle(None, None, log_path)   # a terrain message means the previous battle is over
        self.goals = []          # goals of the previous battle must not filter this map's objectives
        self.phase_start = None  # set by the first state of this map
        self.foe_memory = {}
        self.briefing, self.assault_mem, self.relief_clock, self.unpack_tries = {}, {}, {}, {}
        self.cohesion_mem = {}
        self.exchange.reset()
        self.threat_mem = {}
        self.column.reset()
        self.arrived, self.roster_t0 = {}, None
        self.battery_clock = {}
        self.assault_abandoned, self.discipline, self.flank_mem = False, {}, {}
        self.withdrawal.reset()
        self.rest_sent, self.fire_mem, self.prev_enemy_pos = {}, {}, {}
        self.tactics_mem = {}
        self.skirmish_mem = {}
        self.directives, self.assault_mems, self.assault_groups, self.assault_sync = [], {}, set(), {}
        self.final_mem = {}
        self.saved_plan, self.stop_loss_until = None, 0.0
        self.roster, self.roster_text, self.last_call_snap = {}, [], None
        self.skips_in_row, self.manual_arrivals, self.seen_foes = 0, 0, set()
        self.new_foe_men, self.hp_history, self.roster_folds = 0.0, [], 0
        self.static_brief, self.retry_call = None, False
        self.fail_streak, self.retry_after = 0, 0.0
        self.scale_name = None
        self.reflexes_live, self.reflex_log, self.reflexes_sent = False, [], False
        self.previous_hp = {}
        self.columns, self.foe_gaps = {}, {}
        set_known_foes([])
        self.terrain = terrain
        cavalry_mod.set_terrain(terrain)
        all_objectives = terrain.objectives
        terrain.objectives = self.in_play(all_objectives)
        if len(terrain.objectives) != len(all_objectives):
            print(f"  Ignoring {len(all_objectives) - len(terrain.objectives)} objective(s) outside "
                  "the playable area (the map is part of a larger battlefield)")
        self.report = BattleReport(objectives=terrain.objectives)
        self.engaged = False   # a terrain message means a new battle (or a reconnection)
        self.last_cmds, self.last_change = {}, None
        self.contact_time, self.last_mode, self.llm_failures = None, None, 0
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
        self.exchange.update(state)
        self.note_arrivals(state)

    def remember_foes(self, state):
        """Last known position of every enemy unit seen, for what is out of sight now (fog of war)."""
        now = float(state.get("time", 0.0))
        for u in state["units"]:
            if u["side"] == state["playerSide"] and u.get("status") != "captured":
                self.foe_memory[u["id"]] = {"id": u["id"], "name": u["name"], "kind": u["kind"],
                                            "x": u["x"], "z": u["z"], "hp": u["hp"], "morale": u.get("morale", 1.0),
                                            "status": "", "t": now}
        horizon = float(DEFAULT_SUPPLY.get("memory_s", 900.0))
        visible = {u["id"] for u in state["units"] if u["side"] == state["playerSide"]}
        set_known_foes([m for i, m in self.foe_memory.items() if i not in visible and now - m["t"] <= horizon])

    def finish_battle(self, game_result, objectives, log_path, goals=None, result_kind=None):
        """Close the battle in progress: print the report, save it and update the scoreboard."""
        pending, self.pending_phase = getattr(self, "pending_phase", None), None
        phases, self.phases_done = getattr(self, "phases_done", 0), 0
        if pending is not None and game_result is None and result_kind is None:
            # WIP17: the battle was left after a phase ended: that phase's result is the battle's
            game_result, objectives = pending.get("result"), pending.get("objectives") or objectives
            goals, result_kind = pending.get("battleGoals") or goals, "mission"
        report, self.report = self.report, None
        if report is None or report.states == 0:
            return
        if (report.last_time - (report.first_time or 0.0) < 60.0 and report.own_loss <= 0 and report.foe_loss <= 0
                and game_result is None):
            # WIP17: a map loaded for a few seconds (Second Manassas 19:50, Thoroughfare Gap 11:43): not a battle
            print("A map was open for less than a minute with no fighting: no report.")
            return
        mission = self.config.get("mission", {})
        goals = goals or self.goals
        result = report.finish(game_result, self.in_play(objectives) or self.last_objectives,
                               self.config.get("scoring"), mission.get("player_rule"),
                               result_kind == "battle" or bool(mission.get("trust_game_result")), goals)
        if game_result is None and result_kind is None and result["outcome"] != "no_contest":
            # no end screen: the battle was left (saved and quit, or a new battle loaded). Not a result: a saved
            # battle resumed later starts a new report, and only that one counts.
            result["outcome_reason"] = (f"interrupted (no end of battle from the game); the goals said "
                                        f"{result['outcome']} at that point")
            result["outcome"], result["points"] = "interrupted", 0
        result["goals"] = goals
        result["game_result_kind"] = result_kind     # "battle" (player's result) or "mission" (internal)
        if phases:
            result["phases"] = phases + (0 if result_kind == "mission" and pending is not None else 1)
        self.goals = []
        backend_name = self.config["backend"]
        model = self.config.get(backend_name, {}).get("model") if isinstance(self.config.get(backend_name), dict) else None
        label_ = f"{backend_name}:{model}" if model else backend_name
        result["llm_only"] = bool(self.config.get("llm_only"))   # always written: shows which mode really ran
        result["mode"] = command_mode(self.config)
        if result["mode"] != "full":
            # WIP13/15: model-only and model-plus battles are scored apart (own line in by_model)
            label_ += " (llm only)" if result["mode"] == "llm_only" else " (llm plus)"
        result["backend"] = label_
        dry = bool(self.config.get("dry_run"))
        if dry:
            # WIP11 (battle of 2026-11-13 14:31): a dry run was credited to the model as a victory
            result["dry_run"] = True
            result["commander"] = "game AI (dry run: the model's orders were logged, not sent)"
        result["llm_calls"], result["quiet_turns_skipped"] = self.llm_calls, self.skipped_turns
        result["battle_size"] = self.scale_name
        if self.tokens:
            result["tokens"] = dict(self.tokens)
            print("Tokens this battle: " + self.usage_text(self.tokens)
                  + f" | {self.llm_calls} model call(s), {self.skipped_turns} quiet turn(s) skipped")
        self.tokens, self.llm_calls, self.skipped_turns = Counter(), 0, 0
        journal, stats, owner_log = self.journal, self.stats, self.owner_log
        self.pending_moves, self.line_memory, self.owners = {}, {}, {}
        self.pending_expiry = {}
        self.columns, self.foe_gaps = {}, {}
        self.last_objectives, self.journal, self.stats, self.owner_log = [], [], {}, []
        scoreboard = record(report=result, backend_name=label_, dry_run=dry)
        log_event(log_path, "battle_report", result)
        print(format_report(result))
        print(scoreboard_line(scoreboard))
        self.previous_orders = []
        self.last_cmds, self.last_change = {}, None
        self.events = []
        if dry:
            print("Dry run: no after-action review (the model's orders were not carried out).")
        elif (self.backend is not None and self.config.get("assessment", {}).get("enabled")
                and result["outcome"] != "no_contest"
                and result["llm_calls"] >= int(self.config.get("assessment", {}).get("min_calls", 0))):
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
        # a withdrawal or the preservation of a lost battle overrides the plan: no assault while it runs
        if self.withdrawal.update_mode(state, self.plan_info, self.stats) and self.plan_info:
            self.plan_info = dict(self.plan_info, mode="DEFEND", targets=[], hold_launch=True)
            self.directives = []
        override = self.plan_info["posture"] if self.plan_info else None
        lines = situation_lines(state, objectives or [], stale, self.config.get("posture"), override,
                                (self.plan_info or {}).get("targets") if self.plan_info else None,
                                capture=capture_status(state, self.config.get("discipline")), plan=self.plan_info)
        if getattr(self, "offmap", None):
            lines.append("ENTERING THE FIELD (off the map; the game walks them in, no orders until they arrive): "
                         + ", ".join(f"#{i}" for i in sorted(self.offmap)))
        lines += flank_lines(state, self.config.get("flank"))
        lines += self.withdrawal.lines()
        tcfg = self.config.get("tactics")
        if (tcfg or {}).get("enabled", True):
            lines += arrivals_lines(state, self.tactics_mem, tcfg)
            if not self.withdrawal.active():
                lines += breach_lines(state, self.tactics_mem, tcfg)
        lines += skirmish_lines(state)
        lines += fire_lines(state, self.prev_enemy_pos, self.config.get("fire"))
        mode = self.plan_info["mode"] if self.plan_info else None
        if mode != self.last_mode and mode is not None:
            print(f"  Strategic plan: {mode}" + (f" (kill/death {self.report.kd_men():.2f})" if self.report else ""))
            self.events.append(f"your strategic plan is now {mode}")
            self.last_mode = mode
        has_assault = bool(self.plan_info and self.plan_info.get("targets")) or bool(self.directives)
        if (mode in (None, "ATTACK") and not has_assault and objectives and not stale and self.engaged
                and self.last_change is not None):       # with an ASSAULT PLAN the stalemate advice repeats it
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
        if self.config.get("dry_run"):
            # WIP11: visible in the game, so that a dry run is never mistaken for the model's battle
            mode = "DRY RUN (game AI commands) " + mode
            text = "Orders logged, not sent: set \"dry_run\": false in config.json. " + text
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

    def multi_phase(self, objectives):
        """True when a goal names an objective that is not on this map (a phase of a larger battle)."""
        for entry in self.goals or []:
            for g in list(entry.get("or") or []) + list(entry.get("and") or []):
                if g.get("type") != "CaptureObjectivePoint":
                    continue
                names = {_norm(str(g[k])) for k in ("message", "objective") if g.get(k)}
                if names and not any(self.goal_names_match(o, names) for o in objectives or []):
                    return True
        return False

    @staticmethod
    def goal_names_match(objective, wanted):
        name = _norm(str(objective.get("name", "")))
        return bool(name) and any(name == w or name in w for w in wanted)

    def woods_mode(self):
        """The exchange is being lost and the casualties count (a kill or loss ratio among the goals): not
        attacking, and either the stop-loss tripped, or a casualty deficit, or far behind."""
        p = self.plan_info or {}
        return bool(p.get("kd_goal") and (p.get("mode") != "ATTACK" or p.get("abandoned"))
                    and (p.get("stop_loss") or p.get("deficit") or p.get("behind_far")))

    def make_plan(self, state, objectives):
        """Attack / defend / trade decision from the mission goals read in the game (None without them)."""
        pcfg = {**PLAN_DEFAULTS, **(self.config.get("plan") or {})}
        if not self.goals or not pcfg.get("enabled", True) or command_mode(self.config) != "full":
            return None
        since = ((float(state.get("time", 0.0)) - self.contact_time) / 60.0) if self.contact_time is not None else 0.0
        rep = self.report
        kd = rep.kd_men() if rep else 1.0
        if rep and rep.own_start > 0:
            # Absolute thresholds are for ~16,000 men; brigades can be up to 6000 men: scale with the army.
            # own_start counts every man of the AI army that took part (units arriving later included).
            pcfg["min_casualties"] = max(float(pcfg["min_casualties"]),
                                         float(pcfg.get("min_casualties_share", 0.02)) * rep.own_start)
            pcfg["stop_loss_min"] = max(float(pcfg["stop_loss_min"]),
                                        float(pcfg.get("stop_loss_share", 0.01)) * rep.own_start)
        now = float(state.get("time", 0.0))
        pcfg["force_stop_loss"] = now < self.stop_loss_until      # a triggered stop-loss lasts a minimum time
        # ...and once over, it cannot trip again for `stop_loss_cooldown_s` (0.1.4 WIP7)
        pcfg["stop_loss_cooldown"] = (self.stop_loss_until > 0.0 and not pcfg["force_stop_loss"]
                                      and now < self.stop_loss_until + float(pcfg.get("stop_loss_cooldown_s", 600)))
        pcfg["force_abandon"] = self.assault_abandoned
        pcfg["secure_latched"] = bool((self.plan_info or {}).get("secure"))

        def run():
            return make_plan(self.goals, state, objectives, kd, since,
                             rep.own_loss if rep else 0.0, rep.foe_loss if rep else 0.0, pcfg,
                             rep.recent(600.0) if rep else None)
        try:
            res = run()
            if res and res.get("stop_loss") and not pcfg["force_stop_loss"]:
                self.stop_loss_until = now + float(pcfg.get("stop_loss_hold_s", 480))
                print(f"  STOP-LOSS: pause of at least {float(pcfg.get('stop_loss_hold_s', 480)) / 60:.0f} min")
            res = self.phase_override(res, state, objectives)
            # Abandon latch. A clearly outnumbered army that has not sent its assault in by minute
            # `abandon_minute` gives it up for the rest of the battle; only a force ratio above `resume_ratio`
            # opens the question again. The decision is kept here, so the plan cannot put the attack back.
            ratio = (res or {}).get("overall")
            minutes = float(state.get("phaseTime", now)) / 60.0
            launched = bool(self.assault_mem.get("launched")) or any(
                m.get("launched") for m in self.assault_mems.values())
            flip = None
            if self.assault_abandoned and ratio is not None and ratio >= float(pcfg["resume_ratio"]):
                flip = False
                print(f"  ASSAULT allowed again: force ratio {ratio:.2f} is above {float(pcfg['resume_ratio']):.2f}")
            elif (not self.assault_abandoned and res and (res.get("mode") == "ATTACK" or res.get("need_cap"))
                  and ratio is not None
                  and ratio < float(res.get("abandon_ratio", pcfg["abandon_ratio"]))
                  and minutes >= float(pcfg["abandon_minute"]) and not launched):
                flip = True
                print(f"  ASSAULT ABANDONED for the rest of the battle: force ratio {ratio:.2f} at minute "
                      f"{minutes:.0f}, the assault has not gone in. The army defends what it holds.")
                self.stats["assault abandoned for good (force ratio under plan.abandon_ratio)"] = 1
            if flip is not None:
                self.assault_abandoned = pcfg["force_abandon"] = flip
                res = self.phase_override(run(), state, objectives)
            if self.assault_abandoned and self.directives:
                self.directives = []                    # the model's own assaults stand down too
            return res
        except Exception as e:      # the plan is advice: never stop the battle for it
            print("  Strategic plan failed:", e)
            return None

    def phase_override(self, res, state, objectives):
        """Multi-phase battles (e.g. Shiloh): the goals name the objectives of the whole battle, but this map only
        holds the objective(s) of the current phase. When the chosen way to win needs objectives that are not on
        this map, the plan targets this map's objectives instead: attack those the player holds or nobody holds,
        defend them when you already hold them all."""
        if not res or not objectives or res.get("abandoned"):
            return res
        if res.get("targets"):
            # this map's own objectives (named by no goal) are phase objectives too: take them as well
            if not self.multi_phase(objectives):
                return res
            mine, _ = split_units(state)
            ai_side = mine[0]["side"] if mine else None
            wanted = self.goal_objective_names()
            extra = [o for o in objectives if o.get("side") != ai_side and not self.goal_names_match(o, wanted)
                     and all(o.get("name") != t.get("name") for t in res["targets"])]
            if extra:
                res["targets"] = list(res["targets"]) + extra
                names = ", ".join(str(o.get("name")) for o in res["targets"])
                res["mode"] = "ATTACK"
                res["posture"] = (f"PHASE OBJECTIVES: this map is one phase of a larger battle; take {names} before "
                                  "the phase ends (with enough brigades, one assault on each at the same time). "
                                  + res.get("posture", ""))
                res["lines"] = [l for l in res.get("lines", []) if "AMBITION:" not in l] + \
                    [f"  AMBITION: {res['mode']}. " + res["posture"]]
            return res
        if not any(str(r).lower().startswith("hold") for r in res.get("route") or []):
            return res                                   # the way to win is not about objectives
        mine, _ = split_units(state)
        ai_side = mine[0]["side"] if mine else None
        missing = ", ".join(str(r).split(":", 1)[-1].strip() for r in res.get("route") or [] if str(r).lower().startswith("hold"))
        theirs = sorted((o for o in objectives if o.get("side") != ai_side),
                        key=lambda o: -float(o.get("victoryPoints") or 0))
        if theirs:
            names = ", ".join(str(o.get("name")) for o in theirs)
            res["targets"] = theirs
            res["mode"] = "ATTACK"
            res["posture"] = (f"PHASE OBJECTIVE: this map is one phase of a larger battle. The goals name {missing}, "
                              f"which is not on this map: take {names}, the objective of this phase, before the phase ends. "
                              "ATTACK: write the assault plan and launch it early; the time you give the player is time "
                              "to fortify. " + ("STOP-LOSS PAUSE: keep staging, the launch waits a few minutes. "
                                                if res.get("stop_loss") else ""))
        else:
            names = ", ".join(str(o.get("name")) for o in objectives)
            res["mode"] = "DEFEND"
            res["posture"] = (f"PHASE OBJECTIVE: this map is one phase of a larger battle ({missing} is not on this map). "
                              f"You hold {names}: keep it with a continuous line on good ground and a reserve.")
        res["lines"] = [l for l in res.get("lines", []) if "AMBITION:" not in l] + [f"  AMBITION: {res['mode']}. " + res["posture"]]
        return res

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
        return lines

    def rotation_lines(self, state):
        """Sets the morale a pulled-back brigade needs before it goes forward again, by situation (calm, tense,
        critical; see relief.situation_level), and gives the prompt line."""
        rcfg = self.config.get("relief") or {}
        level, value = situation_level(state, rcfg, bool(self.plan_info and self.plan_info.get("stop_loss")))
        set_return_morale(value, level)
        if level != getattr(self, "rotation_level", None):
            print(f"  Situation {level.upper()}: rotated brigades go forward again from morale {value:.2f}")
            self.rotation_level = level
        if not self.engaged:
            return []
        eve = float({**DEFAULT_ASSAULT, **(self.config.get("assault") or {})}["eve_morale"])
        return [f"ROTATION ({level.upper()}): pulled-back brigades go forward again from morale {value:.2f}; brigades "
                f"joining an assault or the final charge need {eve:.2f}."]

    def assault_runs(self, state):
        """[(plan info, assault state)] for this turn: one per assault the model commands ("assaults"), else the
        server's own single assault on the objective the plan needs."""
        if not self.directives:
            targets = (self.plan_info or {}).get("targets") or []
            acfg = self.config.get("assault") or {}
            mine, _ = split_units(state)
            n_inf = sum(1 for u in mine if u["kind"] == "Infantry" and u.get("status", "") == "")
            if (self.plan_info and self.plan_info.get("mode") == "ATTACK" and len(targets) >= 2
                    and n_inf >= int(acfg.get("split_min_infantry", 6))):
                # two objectives to take and a big enough army: the server's own choice is one assault on each
                cx = sum(u["x"] for u in mine) / len(mine)
                cz = sum(u["z"] for u in mine) / len(mine)
                two = sorted(targets, key=lambda o: math.hypot(o["x"] - cx, o["z"] - cz))[:2]
                runs = []
                for k, obj in enumerate(two):
                    mem = self.assault_mem if k == 0 else self.assault_mems.setdefault("auto:" + obj["name"], {})
                    info = dict(self.plan_info, targets=[obj],
                                cfg_override={"group_share": 0.5, "reserve_keep": None, "group_max": 99} if k == 0 else {})
                    runs.append((info, mem))
                return self.synchronise(runs)
            return [(self.plan_info, self.assault_mem)]
        objs = state.get("objectives") or []
        runs = []
        for k, d in enumerate(self.directives):
            name = d["objective"].lower()
            obj = next((o for o in objs if str(o.get("name", "")).lower() == name), None) or \
                next((o for o in objs if name in str(o.get("name", "")).lower()
                      or str(o.get("name", "")).lower() in name), None)
            if obj is None:
                continue
            # one state per assault (two assaults on the same objective must not share their losses and timing)
            mem = self.assault_mems.setdefault(f"{obj['name']}#{k}", {})
            info = dict(self.plan_info or {}, mode="ATTACK", targets=[obj], directive=d)
            runs.append((info, mem))
        return self.synchronise(runs) or [(self.plan_info, self.assault_mem)]

    def synchronise(self, runs):
        """Two assaults in the same turn go in together (same objective: a pincer; two objectives: the player
        must split his attention): they share a readiness table, see assault.assault_orders."""
        if len(runs) >= 2:
            table = self.assault_sync.setdefault("+".join(sorted(i["targets"][0]["name"] for i, _ in runs)), {})
            for k, (info, _) in enumerate(runs):
                info["sync"], info["sync_key"] = table, k
        return runs

    def final_target(self, state):
        """The objective of the final charge: the nearest enemy-held objective among the assaults' targets."""
        mine, _ = split_units(state)
        if not mine:
            return None
        side = mine[0]["side"]
        cands = [i["targets"][0] for i, _ in self.assault_runs(state)
                 if i and i.get("mode") == "ATTACK" and i.get("targets")]
        cands = [o for o in cands if o.get("side") != side]
        if not cands:
            return None
        cx = sum(u["x"] for u in mine) / len(mine)
        cz = sum(u["z"] for u in mine) / len(mine)
        return min(cands, key=lambda o: math.hypot(o["x"] - cx, o["z"] - cz))

    def assault_block(self, state, ranges, terrain):
        """Briefing text and the ASSAULT PLAN block(s) for the prompt."""
        acfg = self.config.get("assault")
        objectives = self.last_objectives or []
        lines = briefing_lines(self.briefing, objectives, acfg)
        plan = []
        for info, mem in self.assault_runs(state):
            plan += assault_lines(state, info, acfg, mem, ranges, terrain, self.saved_plan)
        _, _, final = final_charge_orders(state, [], self.final_target(state), self.config.get("final_charge"),
                                          dict(self.final_mem), terrain, quiet=True)
        return lines + ([""] if lines and plan else []) + plan + final

    def terrain_for_prompt(self):
        if self.terrain is None or not self.config["terrain"].get("in_prompt"):
            return None
        return self.terrain

    def note_event(self, msg):
        if msg.get("type") != "done":
            return
        uid = msg.get("id")
        if msg.get("canceled"):
            # The plugin reports a canceled move only when something else stopped it (a reflex, the game itself):
            # a move replaced by a newer order of ours stays silent. The unit is not marching any more, so the
            # move must not stay "pending" (the server would wait for it for minutes and show MARCHING).
            if self.pending_moves.pop(uid, None) is not None:
                self.pending_expiry.pop(uid, None)
                key = "moves stopped before arrival (reflex or game), freed for a new order"
                self.stats[key] = self.stats.get(key, 0) + 1
            return
        self.pending_moves.pop(uid, None)
        self.events.append(f"{label(self.names, uid)} reached its destination")
        if not (self.last_cmds.get(uid) or {}).get("auto"):
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

    @staticmethod
    def fighting(state):
        """(own units, enemy units) without the prisoners: a captured unit changes side in the game, so a brigade
        of ours taken prisoner is no "new enemy force", and prisoners we took are no "reinforcements"."""
        mine, foes = split_units(state)
        return ([u for u in mine if u.get("status") != "captured"],
                [u for u in foes if u.get("status") != "captured"])

    def call_snapshot(self, state):
        mine, foes = self.fighting(state)
        return {"time": float(state.get("time", 0.0)),
                "own": {u["id"]: (float(u["morale"]), float(u["hp"]), u.get("status", "")) for u in mine},
                "foes": {u["id"] for u in foes},
                "mode": self.plan_info["mode"] if self.plan_info else None,
                "launched": bool(self.assault_mem.get("launched"))}

    def quiet_turn(self, state):
        """True when the model need not be called for this state. The game sends a state every few seconds of
        play; the server's own staff work runs at every one of them, the model (the commander) is called
        - at once for a critical event: an objective changed hands, the plan mode changed, a brigade broke;
        - after `min_call_gap_s` for an ordinary reason: its orders are all carried out, a sizeable new enemy
          force, a morale collapse, heavy losses, reinforcements, an assault launched or released;
        - in any case after `max_gap_s`.
        Returns (quiet, reason for calling)."""
        ecfg = self.config.get("economy") or {}
        last = self.last_call_snap
        mine, foes = self.fighting(state)
        new_foes = {e["id"] for e in foes} - self.seen_foes     # never seen before in this battle
        self.seen_foes |= new_foes
        self.new_foe_men += sum(float(e["hp"]) * (2.0 if e["kind"] == "Artillery" else 1.0) for e in foes
                                if e["id"] in new_foes and e["kind"] in ("Infantry", "Cavalry", "Artillery"))
        if self.retry_call:
            # one lost answer is asked again at the next state; a backend that keeps failing (not logged in,
            # usage limit, time-outs) is tried less and less often: every try freezes the game and may be paid
            if float(state.get("time", 0.0)) < self.retry_after:
                return True, ""
            return False, "retry after a lost answer"
        if not ecfg.get("skip_quiet_turns", True) or last is None:
            return False, "first call"
        snap = self.call_snapshot(state)
        gap = snap["time"] - last["time"]
        # 1. critical events: the commander decides now
        if any("changed owner" in e for e in self.events):
            return False, "objective changed hands"
        if snap["mode"] != last["mode"]:
            return False, "plan"
        kinds = {u["id"]: u["kind"] for u in mine}
        for uid, (morale, hp, status) in snap["own"].items():
            before = last["own"].get(uid)
            if (before is not None and status != before[2] and status in ("routing", "shattered", "captured")
                    and kinds.get(uid) in ("Infantry", "Artillery")):
                return False, "brigade broken"
        # 2. too soon after the last call: the staff handles it
        if gap < float(ecfg.get("min_call_gap_s", 150)):
            return True, ""
        # 3. ordinary reasons
        if snap["launched"] != last["launched"]:
            return False, "assault launched or released"
        if snap["mode"] == "ATTACK" and not self.saved_plan:
            return False, "no attack plan yet"
        own_pending = [i for i in self.pending_moves if not (self.last_cmds.get(i) or {}).get("auto")]
        if self.manual_arrivals and not own_pending:
            return False, "its orders are carried out"
        start = self.report.own_start if self.report else 0
        if self.new_foe_men >= max(float(ecfg.get("new_enemy_men", 1200)),
                                   float(ecfg.get("new_enemy_share", 0.04)) * start):
            return False, "new enemy force"
        lost, shaken = 0.0, 0
        for uid, (morale, hp, status) in snap["own"].items():
            before = last["own"].get(uid)
            if before is None:
                return False, "reinforcements"
            if before[0] - morale >= float(ecfg.get("morale_drop", 0.3)) and kinds.get(uid) in ("Infantry", "Cavalry"):
                shaken += 1
            lost += max(0.0, before[1] - hp)
        # one shaken brigade is the staff's business (pull-back, replacement); several at once change the picture
        n_inf = sum(1 for k in kinds.values() if k == "Infantry")
        if shaken >= max(int(ecfg.get("morale_drop_units", 2)), int(round(0.15 * n_inf))):
            return False, "several brigades shaken"
        if lost >= max(float(ecfg.get("loss_men", 100)), float(ecfg.get("loss_share", 0.01)) * start):
            return False, "losses"
        if gap >= float(ecfg.get("max_gap_s", 420)):
            return False, "time"
        return True, ""

    def losses_since(self, state):
        """{unit id: hp} about economy.loss_window_s ago (the oldest state kept when the battle is younger): with
        a state every battle minute, losses per state are too small to judge fire a unit cannot answer."""
        now = float(state.get("time", 0.0))
        window = float((self.config.get("economy") or {}).get("loss_window_s", 150))
        mine, _ = split_units(state)
        self.hp_history.append((now, {u["id"]: float(u["hp"]) for u in mine}))
        self.hp_history = [h for h in self.hp_history if now - h[0] <= 2.5 * window][-12:]
        older = [h for h in self.hp_history[:-1] if now - h[0] >= window]
        if older:
            return older[-1][1]
        return self.hp_history[0][1] if len(self.hp_history) > 1 else {}

    def update_roster(self, mine):
        """Fixed equipment of our units, given once in the system prompt, which must stay identical to stay
        cached: every change rewrites the whole system prompt (about 20,000 tokens). In battles where the army
        arrives little by little (Shiloh) that happened 4 to 7 times a battle and cost up to half of the tokens
        written. So late arrivals keep their full equipment in the unit table (a few tokens each per turn) and
        join the roster only in batches: `roster_fold` units waiting, at most `roster_max_folds` times (0 by
        default: on the replays one addition cost 21,800 tokens and saved 6,100 over the rest of the battle)."""
        ecfg = self.config.get("economy") or {}
        late = [u for u in mine if u["id"] not in self.roster and equipment_static(u)]
        if not late:
            return False
        first = not self.roster
        if not first and (len(late) < int(ecfg.get("roster_fold", 12))
                          or self.roster_folds >= int(ecfg.get("roster_max_folds", 0))):
            return False
        if not first:
            self.roster_folds += 1
            print(f"  Roster: {len(late)} late brigade(s) added to the cached system prompt (rewritten once)")
        for u in late:
            self.roster[u["id"]] = equipment_static(u)
            self.roster_text += roster_lines([u])
        return True

    def perks_text(self):
        """The PERKS block appended to the rules (empty when no bonus file is found or it is switched off)."""
        pcfg = self.config.get("perks") or {}
        if not pcfg.get("show_in_prompt", True) or not perks_mod.loaded():
            return ""
        return "\n\n" + perks_mod.prompt_section()

    def unseen_aggressiveness(self):
        """Doctrine value for the answer to fire a unit cannot return (0.5 = balanced when no doctrine is set)."""
        r = self.config.get("reflexes") or {}
        if r.get("unseen_aggressiveness") is not None:
            return float(r["unseen_aggressiveness"])
        return 0.8 if r.get("unseen_advance") else 0.5

    def hold_line(self):
        """WIP11: the plan defends, so units shot by unseen enemies never step forward (plugin reflex and server)."""
        mode = (self.plan_info or {}).get("mode") if isinstance(self.plan_info, dict) else None
        return str(mode or "").startswith("DEFEND")

    def reflex_command(self, dry_run):
        """Settings for the plugin's reflexes, sent once per battle (switched off in dry run)."""
        rcfg = dict(self.config.get("reflexes") or {})
        rcfg["enabled"] = bool(rcfg.get("enabled", True)) and not dry_run and not self.config.get("llm_only")
        if command_mode(self.config) == "llm_plus":
            rcfg["unseen"] = False           # WIP15: the unseen-fire reflex moves the line: left to the model
        self.reflexes_live = rcfg["enabled"]
        cmd = {"cmd": "reflexes"}
        cmd.update({k: v for k, v in rcfg.items() if k not in ("engaged_interval_s", "max_lines")})
        cmd["unseen_aggressiveness"] = self.unseen_aggressiveness()
        # the game draws arrows for orders given "as a player": hidden unless overlay.show_ai_orders (testing)
        cmd["hide_orders"] = not bool((self.config.get("overlay") or {}).get("show_ai_orders", False))
        tr = {**DEFAULT_TERRAIN_RULES, **(self.config.get("terrain_rules") or {})}
        cmd.setdefault("unseen_charge_reach", tr["unseen_charge_reach"])
        cmd.setdefault("unseen_close_gap", tr["unseen_close_gap"])
        cmd.setdefault("unseen_min_range", tr["unseen_min_range"])
        cmd.setdefault("unseen_advance_max", tr["unseen_advance_max"])
        # WIP11: the limits of the server's own answer to unseen fire apply to the plugin's reflex too
        cmd.setdefault("unseen_chase_screens", tr["unseen_chase_screens"])
        cmd.setdefault("unseen_line_ahead", tr["unseen_line_ahead"])
        cmd.setdefault("unseen_neighbour_max", tr["unseen_neighbour_max"])
        cmd.setdefault("unseen_refused_holds", tr["unseen_refused_holds"])
        cmd["unseen_hold_line"] = self.hold_line()
        self.sent_hold_line = cmd["unseen_hold_line"]
        return cmd

    def note_reflexes(self, state):
        """Collects the reflex events the plugin reports; counted in the battle stats."""
        for line in state.get("reflexEvents") or []:
            line = str(line)
            self.reflex_log.append(line)
            kind = line.split("] ", 1)[-1].split(":", 1)[0].strip()
            key = f"reflex {kind} (plugin, no model call)"
            self.stats[key] = self.stats.get(key, 0) + 1
        self.reflex_log = self.reflex_log[-60:]

    def reflex_lines(self):
        if not self.reflex_log:
            return []
        n = int((self.config.get("reflexes") or {}).get("max_lines", 8))
        shown = self.reflex_log[-n:]
        more = len(self.reflex_log) - len(shown)
        return (["REFLEXES SINCE YOUR LAST TURN (done by the game itself; adjust your orders if needed):"]
                + [f"  {line}" for line in shown] + ([f"  (+{more} earlier)"] if more else []))

    def battle_scale(self, mine):
        """'small' or 'large' (config "scale"), announced once per battle; returns (name, profile or None)."""
        scfg = self.config.get("scale") or {}
        combat = sum(1 for u in mine if u["kind"] in ("Infantry", "Cavalry", "Artillery", "Skirmish"))
        threshold = int(scfg.get("large_threshold", 40))
        if self.scale_name == "large":
            threshold = int(threshold * 0.85)    # hysteresis: a few losses must not flip the prompt layout back
        name = scfg.get("force") or ("large" if combat >= threshold else "small")
        if name != self.scale_name:
            print(f"  Battle size: {name} ({combat} combat units of yours)"
                  + (": compact prompt for the units far from the fight" if name == "large" else ""))
            self.scale_name = name
        # short battles too give a short line to the units far from every visible enemy (scale.small)
        return name, (scfg.get("large") if name == "large" else (scfg.get("small") or {"detail_radius": 1500, "route_radius": 800}))

    def note_arrivals(self, state):
        """WIP16: battle time each of our units was first seen; the units of the first state are not arrivals."""
        now = float(state.get("time", 0.0))
        mine, _ = split_units(state)
        if self.roster_t0 is None:
            self.roster_t0 = now
            self.arrived.update({u["id"]: -1e9 for u in mine})
            return
        for u in mine:
            if u["id"] not in self.arrived:
                self.arrived[u["id"]] = now

    def llm_plus_tail(self, state, orders, quiet, reasoning, terrain):
        """WIP15 llm_plus: the model's checked orders, plus counter-battery, rally on high ground and lone
        batteries pulled back (none of them replaces an order of the model)."""
        # WIP16: the assault column takes over its units (the model's fallback orders still apply)
        c_ids, c_new = self.column.orders(state, orders, terrain, self.stats)
        if c_ids:
            orders = [o for o in orders if o["id"] not in c_ids or o["cmd"] == "fallback"] + c_new
        # WIP17: a rifled battery shelling distant infantry with an enemy battery in range duels instead
        orders = counter_battery_override(state, orders, self.config.get("fire"), self.stats)
        extra = counter_battery_orders(state, orders, self.config.get("fire"), self.fire_mem, self.stats)
        extra += rally_orders(state, orders + extra, self.config.get("relief"), terrain, self.relief_clock,
                              self.pending_moves, self.stats)
        threats = [t for t in flank_threats(state, self.config.get("exchange")) if t["kind"] == "battery"]
        _, bat = refuse_flank_orders(state, terrain, orders + extra, threats, self.threat_mem, (),
                                     self.pending_moves, {**(self.config.get("exchange") or {}),
                                                          "refuse_flank": False}, self.stats)
        taken = {o["id"] for o in orders + extra}
        extra += [o for o in bat if o["id"] not in taken]
        for o in bat:
            self.battery_clock[o["id"]] = float(state.get("time", 0.0))
        return self.llm_only_tail(state, orders + extra, quiet, reasoning)

    def llm_only_tail(self, state, orders, quiet, reasoning):
        """WIP13 llm_only: the model's checked orders go to the game as they are. The only addition is the
        unpacking of a battery whose march ended or was cancelled (otherwise it stays packed for good)."""
        orders = orders + unpack_orders(state, orders, self.pending_moves, self.stats, self.unpack_tries)
        for o in orders:
            if o["cmd"] not in ("ammo", "supply", "limber", "detach", "recall"):
                self.last_cmds[o["id"]] = o
        if quiet:
            ids = {o["id"] for o in orders}
            self.previous_orders = orders + [o for o in self.previous_orders if o["id"] not in ids]
        else:
            self.previous_orders = orders
            self.events = []
            self.journal.append({"time": float(state.get("time", 0.0)), "reasoning": str(reasoning),
                                 "orders": dict(Counter(o["cmd"] for o in orders))})
        return orders

    def plan(self, state, log_path):
        # time since this map (phase) began: chained missions (Shiloh) start their second phase at minute 75
        if getattr(self, "phase_start", None) is None:
            self.phase_start = float(state.get("time", 0.0))
        state["phaseTime"] = float(state.get("time", 0.0)) - self.phase_start
        spent = (state.get("briefing") or {}).get("missionElapsedS")
        if spent is not None:
            state["phaseTime"] = float(spent)         # the game's own phase clock (right after a saved game too)
        clock = phase_clock(state)
        if clock is not None:
            state["phaseUsed"] = clock[0]
        # units still off the field (reinforcements at the map edge): left to the game's AI until they enter
        self.offmap = mark_offmap(state, self.terrain)
        note_field(state, self.tactics_mem)
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
        self.note_reflexes(state)
        self.previous_hp = self.losses_since(state)
        unseen = unseen_fire_lines(state, getattr(self, "previous_hp", {}), terrain, self.config.get("terrain_rules"))
        if unseen:
            a = self.unseen_aggressiveness()
            temper = "aggressive" if a >= 0.7 else ("balanced" if a >= 0.4 else "careful")
            unseen.append(f"  DOCTRINE: {temper} general (aggressiveness {a:.1f}); units you leave without orders "
                          "get the matching answer from the server.")
        mode = command_mode(self.config)
        llm_only = mode != "full"          # WIP15: llm_only and llm_plus share the lean prompt
        # WIP14: ground of each contact, losing sectors, threats on the flanks (information: both modes)
        threats = flank_threats(state, self.config.get("exchange"))
        ground = (force_lines(state, self.config.get("exchange")) + exchange_lines(state, terrain, self.exchange)
                  + threat_lines(state, threats)
                  + reinforcement_lines(state, {k: v for k, v in self.arrived.items() if v > -1e8}))
        # WIP17 (Antietam): duels in reach, crossings and their reserves, free field works (information: all modes)
        ground += (counter_battery_lines(state, self.config.get("fire"))
                   + crossing_lines(state, self.terrain, self.config.get("works"))
                   + fortification_lines(state, self.config.get("works")))
        if mode == "llm_plus":
            ground += self.column.lines(state, column_offer(state, self.config.get("column")))
        elif mode == "llm_only":
            offer = column_offer(state, self.config.get("column"))
            if offer:
                ground.append(offer.split(". Send")[0] + ": you may form it yourself (ASSAULT COLUMN in the "
                              "doctrine).")
        if llm_only:
            # WIP13: nothing in the state may promise server help that will not come
            unseen = [l for l in unseen if "DOCTRINE:" not in l]
            ground = [l.replace("; the server sends no replacement or reserve there", "")
                       .replace("; the server sends the nearest free brigade, you decide the rest", "") for l in ground]
            situation = (unseen + self.situation_for(state) + self.performance_lines() + ground
                         + general_lines(state, self.config.get("generals"))
                         + (self.reflex_lines() if mode == "llm_plus" else []))
        else:
            situation = (unseen + self.situation_for(state) + self.performance_lines() + ground
                         + self.rotation_lines(state)
                         + self.assault_block(state, ranges, terrain)
                         + general_lines(state, self.config.get("generals")) + self.reflex_lines())
        quiet, why = self.quiet_turn(state)
        if quiet:
            self.skipped_turns += 1
            if self.config.get("verbose"):
                print("  No model call for this state (staff work only)")
            reasoning, raw, raw_orders, orders = None, "", [], []
        else:
            tcfg = self.config["terrain"]
            terrain_text = terrain.prompt_text(tcfg["overview_cols"], tcfg["height_cols"],
                                               tcfg["show_heights"], tcfg["show_rules"]) if terrain else ""
            use_roster = bool((self.config.get("economy") or {}).get("static_roster", True))
            if use_roster:
                self.update_roster(mine)
            if self.static_brief is None:
                # frozen at the first call of the battle: the system prompt must stay identical to stay cached
                self.static_brief = "\n".join(briefing_static(self.briefing, self.last_objectives,
                                                              self.config.get("assault")))
            system = build_system_prompt(mine[0]["side"], max_orders, read_text("strategy.md"),
                                         terrain_text, ranges,
                                         read_text("game_rules.md") + self.perks_text(),
                                         "\n".join(self.roster_text) if use_roster else "",
                                         self.static_brief,
                                         has_roads=bool(terrain and terrain.has("Road")),
                                         formation_note=march_note({"enabled": False} if llm_only
                                                                   else self.config.get("march")))
            if llm_only:
                system += LLM_PLUS_NOTE if mode == "llm_plus" else LLM_ONLY_NOTE
            user = build_user_prompt(state, self.previous_orders, self.events, terrain, ranges,
                                     self.config.get("line"), situation,
                                     self.line_memory, self.plan_info["mode"] if self.plan_info else None,
                                     self.roster if use_roster else None, self.battle_scale(mine)[1],
                                     self.pending_moves)
            started = time.time()
            raw = None
            if self.before_call is not None:
                self.before_call()                     # the game pauses while the commander thinks
            try:
                extra = {"schema": ORDERS_SCHEMA} if getattr(self.backend, "supports_schema", False) else {}
                raw = self.backend.complete(system, user, **extra)
                reasoning, raw_orders = parse_answer(raw)
            except (BackendError, ValueError) as e:
                # A lost answer must not lose the turn: the server's own staff work still runs (as in a quiet
                # turn) and the model is asked again at the next state.
                print("  LLM planning failed, the server's own orders only this turn:", e)
                if raw is not None and self.config.get("verbose"):
                    print("  --- raw model answer ---")
                    print(indent_block(raw.strip()))
                    print("  --- end of answer ---")
                log_event(log_path, "llm_error", {"error": str(e), "user": user, "raw": raw})
                self.llm_failures += 1
                self.fail_streak += 1
                self.retry_call = True                 # ask again at the next state, then less and less often
                if self.fail_streak >= 2:
                    ecfg = self.config.get("economy") or {}
                    wait = min(float(ecfg.get("retry_backoff_s", 60)) * 2 ** (self.fail_streak - 2),
                               float(ecfg.get("max_gap_s", 420)))
                    self.retry_after = float(state.get("time", 0.0)) + wait
                    print(f"  {self.fail_streak} model calls lost in a row: next try in {wait:.0f} battle seconds")
                if raw is not None:
                    self.note_usage()                  # the call was paid for even if its answer is unusable
                quiet, reasoning, raw, raw_orders, orders = True, None, "", [], []
        if not quiet:
            seconds = time.time() - started
            gen_orders, raw_orders = sanitize_generals(raw_orders, state, terrain, self.config.get("generals"),
                                                       self.stats)
            orders = sanitize(raw_orders, state, max_orders, terrain, ranges.get("fire"), self.pending_moves,
                              self.stats) + gen_orders
            payload = {"user": user, "raw": raw, "seconds": round(seconds, 1),
                       "info": getattr(self.backend, "last_info", {})}
            if self.system_logged != system:      # logged again whenever it changes (new battle, roster)
                payload["system"] = system
                self.system_logged = system
            log_event(log_path, "llm", payload)
            cost = payload["info"].get("cost_usd") if payload["info"] else None
            cost_txt = f", ~${cost:.3f}" if isinstance(cost, (int, float)) else ""
            used = self.note_usage()
            self.reflex_log = []          # shown to the model: start a new list
            self.llm_calls += 1
            self.skips_in_row = 0
            self.manual_arrivals = 0
            self.new_foe_men = 0.0
            self.retry_call, self.fail_streak, self.retry_after = False, 0, 0.0
            self.last_call_snap = self.call_snapshot(state)
            if used and (self.config.get("economy") or {}).get("log_usage", True):
                cost_txt += " | tokens " + self.usage_text(used)
            print(f"  LLM called ({why}), answered in {seconds:.0f}s{cost_txt}: {reasoning}")
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
        if mode == "llm_plus":
            if not quiet and raw:
                try:
                    msg = self.column.command(parse_column(load_answer(raw)), state)
                except (ValueError, AttributeError, TypeError):
                    msg = ""
                if msg:
                    print("  " + msg)
            return self.llm_plus_tail(state, orders, quiet, reasoning, terrain)
        if llm_only:
            return self.llm_only_tail(state, orders, quiet, reasoning)
        written = extract_plan(raw)
        if written:
            self.saved_plan = (float(state.get("time", 0.0)), written)
            print("  Attack plan:", written)
        assaults = extract_assaults(raw)
        if assaults is not None and self.assault_abandoned:
            if any(d.get("launch") != "release" for d in assaults):
                print("  Assault command ignored: the assault is abandoned (force ratio under plan.abandon_ratio)")
                self.stats["assault commands of the model ignored (assault abandoned)"] = \
                    self.stats.get("assault commands of the model ignored (assault abandoned)", 0) + 1
            assaults = None
        if assaults is not None and assaults != self.directives:
            self.directives = assaults
            print("  Assault command from the model: " + ("; ".join(
                f"{d['objective']} launch {d['launch']}" + (f" group {d['group']}" if d.get('group') else "")
                for d in assaults) or "none (server's own choice)"))
        a_drop, a_new, used = set(), [], set()
        for info, mem in self.assault_runs(state):
            d1, n1 = assault_orders(state, [o for o in orders if o["id"] not in a_drop] + a_new, info,
                                    self.config.get("assault"), self.last_cmds, self.pending_moves, ranges, terrain,
                                    mem, self.stats, exclude=used)
            a_drop |= d1
            a_new += n1
            used |= set(mem.get("group") or [])
        f_drop, f_new, _ = final_charge_orders(state, [o for o in orders if o["id"] not in a_drop] + a_new,
                                               self.final_target(state), self.config.get("final_charge"),
                                               self.final_mem, terrain, self.last_cmds, self.stats)
        if f_new:
            f_ids = {o["id"] for o in f_new}
            a_new = [o for o in a_new if o["id"] not in f_ids]
            a_drop |= f_drop
            used |= f_ids
            print("  FINAL CHARGE orders: " + "; ".join(order_text(o, self.names) for o in f_new))
            a_new += f_new
        self.assault_groups = used
        if self.directives:
            first = self.assault_runs(state)[0][1]
            self.assault_mem = first
        if a_drop or a_new:
            orders = [o for o in orders if o["id"] not in a_drop] + a_new
            print("  Server ran the assault plan: " + "; ".join(order_text(o, self.names) for o in a_new))
        sums = self.exchange.sums()
        trap = (lambda x, z, e: is_trap(self.exchange, terrain, x, z, e, sums)) if terrain is not None else None
        r_drop, r_new = relief_orders(state, orders, self.config.get("relief"), self.last_cmds, self.pending_moves,
                                      terrain, self.relief_clock, self.stats, set(self.assault_groups),
                                      plan_mode=(self.plan_info or {}).get("mode"), trap=trap)
        if r_drop or r_new:
            orders = [o for o in orders if o["id"] not in r_drop] + r_new
            print("  Server pulled back broken brigades / sent replacements: "
                  + "; ".join(order_text(o, self.names) for o in r_new))
        drop, guard = guard_artillery(state, orders, self.config.get("guard"), terrain, self.pending_moves,
                                      self.stats)
        if drop:
            for o in guard:
                self.battery_clock[o["id"]] = float(state.get("time", 0.0))   # no placement right after a pull-back
            orders = [o for o in orders if o["id"] not in drop or o["cmd"] == "ammo"] + guard
            print("  Server pulled back unprotected batteries: "
                  + "; ".join(order_text(o, self.names) for o in guard))
        defending = self.defending(state)
        extra = engage_orders(state, orders, ranges, self.config.get("engage"), self.last_cmds,
                              self.pending_moves, defending, self.stats, terrain=terrain)
        extra += ammo_orders(state, orders + extra, self.config.get("ammo"), self.stats)
        extra += supply_orders(state, orders + extra, self.config.get("supply"), terrain, self.pending_moves,
                               self.stats)
        extra += ride_down_orders(state, orders + extra, self.config.get("cavalry"), self.last_cmds,
                                  self.stats)
        extra += battery_orders(state, orders + extra, self.config.get("battery"), terrain, self.pending_moves,
                                self.battery_clock, self.stats)
        extra += unpack_orders(state, orders + extra, self.pending_moves, self.stats, self.unpack_tries)
        extra += general_orders(state, orders + extra, self.config.get("generals"), self.last_cmds, self.pending_moves,
                                terrain, self.stats)
        extra += reserve_orders(state, orders + extra, self.config.get("relief"), self.last_cmds, self.pending_moves,
                                self.plan_info["mode"] if self.plan_info else None, terrain, self.stats, trap=trap)
        # WIP14: brigades out of losing open sectors to the cover behind; flanks refused, lone batteries back
        p_ids, p_new = pull_orders(state, terrain, orders + extra, self.exchange, set(self.assault_groups),
                                   self.pending_moves, (self.plan_info or {}).get("mode"), self.stats)
        # their moves replace the server's own orders for those units this turn (never the model's)
        orders = [o for o in orders if not (o["id"] in p_ids and o.get("auto"))]
        extra = [o for o in extra if o["id"] not in p_ids] + p_new
        f_ids, f_new = refuse_flank_orders(state, terrain, orders + extra, threats, self.threat_mem,
                                    set(self.assault_groups), self.pending_moves, self.config.get("exchange"),
                                    self.stats)
        for o in f_new:
            if o["id"] in self.battery_clock or any(u["id"] == o["id"] and u["kind"] == "Artillery"
                                                    for u in state["units"]):
                self.battery_clock[o["id"]] = float(state.get("time", 0.0))   # no placement right after
        orders = [o for o in orders if not (o["id"] in f_ids and o.get("auto"))]
        extra = [o for o in extra if o["id"] not in f_ids] + f_new
        if extra:
            print(f"  Server added {len(extra)} order(s) for idle units or batteries: "
                  + "; ".join(order_text(o, self.names) for o in extra))
            orders = orders + extra
        aggressive = self.unseen_aggressiveness()
        # units the plugin's UNSEEN reflex already moved since the last state
        handled = {int(m) for line in (state.get("reflexEvents") or []) if "unseen" in str(line)
                   for m in re.findall(r"#(\d+) under fire", str(line))}
        # (not for the members of an assault group: the assault decides where they go)
        orders = orders + unseen_orders(state, getattr(self, "previous_hp", {}), terrain, orders, aggressive,
                                        handled | set(self.assault_groups), self.config.get("terrain_rules"),
                                        self.stats, hold_line=self.hold_line())
        skip = set(self.assault_groups) | handled
        # 0.1.4 WIP8 (withdraw.py, fire.py): tactical withdrawal / preservation of the army, real rest out of the
        # enemy's reach for relieved brigades, batteries packed up and pulled back, fire focused on the enemy
        # closing in and masked batteries moved to a clear line
        wcfg = self.config.get("withdraw")
        driven = set()
        w_ids, w_new = self.withdrawal.army_orders(state, terrain, orders, self.stats)
        mine_now = [u for u in state["units"] if u["side"] != state["playerSide"]]
        resting = {u["id"] for u in mine_now if is_resting(u, self.last_cmds, self.config.get("relief"))}
        r_ids, r_new = rest_orders(state, terrain, orders, resting, wcfg, self.rest_sent, skip | w_ids, self.stats)
        b_ids, b_new = battery_escape_orders(state, terrain, orders, wcfg, self.prev_enemy_pos,
                                             skip | w_ids | r_ids, self.stats)
        driven = w_ids | r_ids | b_ids
        if driven:
            orders = [o for o in orders if o["id"] not in driven or o["cmd"] in WITHDRAW_PASS] + w_new + r_new + b_new
            skip = skip | driven
        # 0.1.4 WIP10 (skirmish.py): skirmish screens scout long marches and flank attacks, cover the withdrawal,
        # and fall back from cavalry and charges (that safety overrides every other order of a screen)
        s_ids, s_new = skirmish_orders(state, terrain, orders, self.pending_moves, self.skirmish_mem,
                                       self.prev_enemy_pos,
                                       self.withdrawal.rearguard if self.withdrawal.active() else (),
                                       skip, self.config.get("skirmish"), self.stats)
        if s_ids or s_new:
            orders = [o for o in orders if o["id"] not in s_ids or o["cmd"] in WITHDRAW_PASS] + s_new
            skip = skip | s_ids
        if self.withdrawal.standing() and self.withdrawal.cfg.get("counter_charge", True):
            # a standing line of the withdrawal charges a beaten enemy unit that came too close (tactics.pursuit,
            # with the defensive radius), the other units stay out of it
            line = self.withdrawal.line_ids
            others = {u["id"] for u in state["units"] if u["side"] != state["playerSide"] and u["id"] not in line}
            c_ids, c_new = pursuit_orders(state, orders, {"mode": "DEFEND"}, self.config.get("tactics"),
                                          self.tactics_mem, others | (skip - line), self.stats)
            if c_new:
                orders = [o for o in orders if o["id"] not in c_ids or o["cmd"] in WITHDRAW_PASS] + c_new
                skip = skip | c_ids
        # 0.1.4 WIP9 (tactics.py): a held objective faced 1 brigade for 1 with concentrated fire, isolated enemy
        # units hunted, beaten enemy units charged again (not during a withdrawal: its units are in `skip`)
        tcfg = self.config.get("tactics")
        if not self.withdrawal.active():
            skip_t = skip | resting           # brigades sent to rest stay out of it
            for step in ("hold", "hunt", "pursuit"):
                if step == "hold":
                    t_ids, t_new = hold_line_orders(state, terrain, orders, self.plan_info, tcfg, self.tactics_mem,
                                                    skip_t, self.pending_moves, self.last_cmds, self.stats,
                                                    trap=trap)
                elif step == "hunt":
                    t_ids, t_new = hunt_orders(state, orders, self.plan_info, tcfg, self.tactics_mem, skip_t,
                                               self.stats)
                else:
                    t_ids, t_new = pursuit_orders(state, orders, self.plan_info, tcfg, self.tactics_mem, skip_t,
                                                  self.stats)
                if t_ids or t_new:
                    orders = [o for o in orders if o["id"] not in t_ids or o["cmd"] in WITHDRAW_PASS] + t_new
                    skip = skip | t_ids | {o["id"] for o in t_new}
                    skip_t = skip_t | t_ids | {o["id"] for o in t_new}
        orders = orders + fire_orders(state, terrain, orders, self.config.get("fire"), self.fire_mem,
                                      self.prev_enemy_pos, skip, self.stats)
        # flank guard (flank.py): a brigade under enfilade gets its flank covered, or leaves the crossfire
        f_drop, f_new = flank_orders(state, orders, self.config.get("flank"), self.flank_mem, skip, self.stats)
        if f_new:
            orders = [o for o in orders if o["id"] not in f_drop] + f_new
            skip = skip | {o["id"] for o in f_new}
        if self.woods_mode():
            orders, w_new = woods_orders(state, terrain, orders, skip, self.pending_moves,
                                         self.config.get("terrain_rules"), self.stats)
            orders = orders + w_new
            skip = skip | {o["id"] for o in w_new}
        orders = orders + cover_orders(state, getattr(self, "previous_hp", {}), terrain, orders, skip,
                                       self.pending_moves, self.config.get("terrain_rules"), self.stats)
        c_drop, c_new = cohesion_orders(state, orders, self.last_objectives or [],
                                        set(cavalry_mod.scouts(state, DEFAULT_CAVALRY)), set(), self.last_cmds,
                                        self.config.get("cohesion"), self.stats, set(self.assault_groups) | driven,
                                        getattr(self, "previous_hp", {}), self.pending_moves,
                                        plan_mode=(self.plan_info or {}).get("mode"), terrain=terrain,
                                        mem=self.cohesion_mem, relief_cfg=self.config.get("relief"))
        if c_drop or c_new:
            orders = [o for o in orders if o["id"] not in c_drop] + c_new
            print("  Server kept the army together: " + "; ".join(order_text(o, self.names) for o in c_new)
                  + (" (orders dropped for " + ", ".join(label(self.names, i) for i in sorted(c_drop)) + ")"
                     if c_drop else ""))
        orders = filter_orders(orders, state, terrain, ranges, self.config.get("terrain_rules"), self.stats)
        orders = add_routes(orders, state, terrain, self.config.get("routes"), self.stats)
        self.prev_enemy_pos = {u["id"]: (u["x"], u["z"]) for u in state["units"] if u["side"] == state["playerSide"]}
        # last word: capture, steady moves, battery marches that do not happen, wagons at the run (discipline.py)
        orders, stuck = discipline_orders(state, orders, self.config.get("discipline"), self.pending_moves,
                                          self.discipline, self.stats)
        battery_mod.BLOCKED = stuck
        # wagons first: in a long battle the ammunition decides, and their orders must not wait behind the rest
        wagon_ids = {u["id"] for u in state["units"] if u.get("kind") == "Supply"}
        orders = [o for o in orders if o["id"] in wagon_ids] + [o for o in orders if o["id"] not in wagon_ids]
        for o in orders:
            if o["cmd"] not in ("ammo", "supply", "limber", "detach", "recall"):
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
        # Road column for the long marches, line again near the enemy. These go first (a column is in line before
        # its attack order) and are kept out of last_cmds and of ORDERS RUNNING: a formation is not an order to
        # march or fight.
        now = float(state.get("time", 0.0))
        horizon = float({**DEFAULT_MARCH, **(self.config.get("march") or {})}["memory_s"])
        remembered = [m for m in self.foe_memory.values() if now - m["t"] <= horizon]
        columns = march_orders(state, orders, self.pending_moves, self.columns, self.foe_gaps,
                               self.config.get("march"), remembered, getattr(self, "previous_hp", {}), self.stats)
        if columns:
            print("  Server set formations: " + "; ".join(order_text(o, self.names) for o in columns))
        return columns + orders


def handle(f, msg, log_path, commander, config):
    kind = msg.get("type")
    if kind == "state":
        commander.names = {u["id"]: u["name"] for u in msg["units"]}
        if msg.get("battleGoals"):
            commander.goals = msg["battleGoals"]
        if msg.get("briefing"):
            commander.briefing = msg["briefing"]
        commander.track(msg)
        # plugin 0.1.4+ ("soft" states): the game keeps running while the server works and pauses only on request
        freeze = {"cmd": "freeze", "max_s": float((config.get(config.get("backend")) or {}).get("timeout_s", 75)) + 20.0}
        commander.before_call = (lambda: send(f, freeze)) if msg.get("soft") else None
        if "reflexEvents" in msg and not commander.reflexes_sent:
            send(f, commander.reflex_command(bool(config.get("dry_run"))))   # the plugin can run reflexes
            commander.reflexes_sent = True
        try:
            orders = commander.plan(msg, log_path)
        except Exception:
            traceback.print_exc()
            orders = []
        # WIP11: the plan mode decides whether the plugin's UNSEEN reflex may step forward; resend the settings
        # when it changes (Reflexes.Configure takes the whole set again)
        if commander.reflexes_sent and commander.hold_line() != commander.sent_hold_line:
            send(f, commander.reflex_command(bool(config.get("dry_run"))))
            print(f"  Reflexes: unseen_hold_line = {commander.sent_hold_line} (plan mode changed)")
        if config.get("dry_run"):
            print("  dry run: orders are logged but not sent")
            to_send = []
        else:
            to_send = orders
        units_now = {u["id"]: u for u in msg.get("units", [])}
        for order in to_send:
            send(f, order)
            if order["cmd"] == "move":
                commander.pending_moves[order["id"]] = (order["x"], order["z"], msg["time"])
                # a long march is not "lost" after 4 minutes: expect about 1 unit of distance per game second
                u = units_now.get(order["id"])
                pts = ([(u["x"], u["z"])] if u else []) + [tuple(p) for p in order.get("path") or []] + \
                      [(order["x"], order["z"])]
                length = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:]))
                commander.pending_expiry[order["id"]] = msg["time"] + max(240.0, 1.5 * length)
            elif order["cmd"] not in ("ammo", "supply", "limber", "mount", "formation", "gait", "detach", "recall"):
                # (a switch does not interrupt a march)
                commander.pending_moves.pop(order["id"], None)
        commander.pending_moves = {k: v for k, v in commander.pending_moves.items()
                                   if msg["time"] < commander.pending_expiry.get(k, v[2] + 240)}
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
        report = commander.report
        if msg.get("resultKind") != "battle" and (report is None or report.states <= 2):
            # "Mission finished" alone, seconds after a map started: the game closing the previous phase of a
            # chained battle (or a loaded save), not the end of this one. Closing the report here wrote a phantom
            # "no contest" battle and reset the server's memory of the battle that goes on.
            print("Ignoring an end-of-mission line at the start of a map (previous phase closing):",
                  msg.get("result"))
            return
        if msg.get("resultKind") == "mission" and (config.get("mission") or {}).get("merge_phases", True):
            # WIP17 (Antietam 2026-11-15: three phases scored as draw, draw, defeat; Second Manassas 11-13 the
            # same): "Mission finished" closes a PHASE of a chained battle. The battle goes on: one report at the
            # real end ("Battle finished"), or with this phase result if the battle is left after it.
            commander.pending_phase = msg
            commander.phases_done += 1
            log_event(log_path, "event", {"type": "phase_end", "result": msg.get("result"),
                                          "phase": commander.phases_done})
            print(f"Phase {commander.phases_done} over (mission result {msg.get('result')}): the battle goes on; "
                  "one report at its end.")
            return
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
    print(f"UGCW Battle AI v{VERSION}")
    print(f"Backend: {config['backend']}. Waiting for the game on {HOST}:{PORT} "
          "(close the window to stop)")
    while True:
        conn, addr = srv.accept()
        log_path = os.path.join(LOG_DIR, time.strftime("battle-%Y%m%d-%H%M%S.jsonl"))
        print("Game connected:", addr, "| log file:", log_path)
        _m = command_mode(config)
        print(f"  Mode: {'LLM ONLY (model alone)' if _m == 'llm_only' else ('LLM PLUS (model + light help)' if _m == 'llm_plus' else 'full system (model + server staff work)')}"
              f" - config file: {os.path.abspath('config.json')}"
              f"{'' if os.path.exists('config.json') else ' (NOT FOUND: defaults in use)'}")
        if config.get("llm_only"):
            print("!" * 64 + "\n  LLM ONLY: the model commands alone, the server only forwards its orders (no staff\n"
                  "  work, plugin reflexes off). Set \"llm_only\": false in config.json for the full system.\n" + "!" * 64)
        if config.get("dry_run"):
            print("!" * 64 + "\n  DRY RUN: the model's orders are logged, NOT sent. The game's own AI commands the army.\n"
                  "  Set \"dry_run\": false in config.json to let the model command.\n" + "!" * 64)
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
    pcfg = config.get("perks") or {}
    kinds = perks_mod.load(pcfg.get("folder"), pcfg.get("label", ""))
    print("Perk bonuses: " + (f"{pcfg.get('label')} ({', '.join(kinds)})" if kinds
                              else f"none found in {pcfg.get('folder')}"))
    try:
        commander = Commander(config)
    except BackendError as e:
        raise SystemExit(f"Cannot start the planner: {e}")
    serve(config, commander)


if __name__ == "__main__":
    main()
