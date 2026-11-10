"""Smoke tests for the planner server: synthetic battles, no game and no model needed.

Run from the repository root:  python -m unittest discover -s tests
"""
import io
import json
import os
import sys
import unittest
from contextlib import redirect_stdout

SERVER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "server")
sys.path.insert(0, SERVER)

import assault  # noqa: E402
import equipment  # noqa: E402
import goals  # noqa: E402
import planner_server  # noqa: E402
import prompting  # noqa: E402
import relief  # noqa: E402

GOALS = [
    {"result": "Victory", "or": [], "and": [{"type": "CaptureObjectivePoint", "state": True,
                                            "message": "Hold Logan Cross", "hidden": False,
                                            "objective": "LoganCross"}]},
    {"result": "Draw", "or": [], "and": [{"type": "KillRatio", "state": False, "hidden": False,
                                         "message": "Inflict at least 40% more casualties than enemy",
                                         "ratio": 1.4, "condition": "MoreOrEquals"}]},
    {"result": "Defeat", "or": [], "and": []},
]
OBJECTIVE = {"name": "Logan Cross", "x": 4000, "z": 4000, "side": "North", "radius": 150,
             "captureRange": 120, "victoryPoints": 500}


def unit(uid, kind, side, x, z, morale=1.0, hp=1500, **extra):
    u = {"id": uid, "name": f"{kind} {uid}", "kind": kind, "side": side, "x": x, "z": z, "hp": hp,
         "maxHp": 1500, "morale": morale, "fatigue": 1.0, "status": "", "range": 440, "ammo": 0.8,
         "weapon": {"name": "Farmer69", "kind": "musket"}, "stars": 1}
    u.update(extra)
    return u


def battle(n_own, n_foe, time_s=1800.0, rear_share=0.0):
    """n_own South units facing n_foe North units across a line; rear_share of ours stand far back."""
    units = []
    for k in range(n_own):
        far = k >= n_own * (1 - rear_share)
        units.append(unit(1 + k, "Infantry", "South", 1000 + 60 * k, 2000 if far else 3500))
    for k in range(n_foe):
        units.append(unit(5001 + k, "Infantry", "North", 1000 + 60 * k, 3900))
    return {"type": "state", "time": time_s, "playerSide": "North", "units": units, "objectives": [OBJECTIVE]}


class PromptTests(unittest.TestCase):
    def test_large_profile_is_shorter_for_far_units(self):
        state = battle(60, 60, rear_share=0.4)
        large = planner_server.DEFAULT_CONFIG["scale"]["large"]
        full = prompting.build_user_prompt(state, [], [])
        compact = prompting.build_user_prompt(state, [], [], scale=large)
        self.assertLess(len(compact), len(full))
        self.assertIn("short line", compact)

    def test_roster_moves_fixed_equipment_out_of_the_turn(self):
        state = battle(5, 5)
        mine, _ = prompting.split_units(state)
        roster = {u["id"]: equipment.equipment_static(u) for u in mine}
        with_roster = prompting.build_user_prompt(state, [], [], roster=roster)
        without = prompting.build_user_prompt(state, [], [])
        self.assertLess(len(with_roster), len(without))

    def test_system_prompt_has_rules_and_roster(self):
        text = prompting.build_system_prompt("South", 20, "notes", "", None, "rules", "1 A (Infantry): musket")
        self.assertIn("READING THE STATE", text)
        self.assertIn("YOUR BRIGADES", text)


class OrderTests(unittest.TestCase):
    def test_sanitize_drops_unknown_units(self):
        state = battle(3, 3)
        raw = [{"cmd": "hold", "id": 1}, {"cmd": "hold", "id": 999}]
        orders = prompting.sanitize(raw, state, 10)
        self.assertEqual([o["id"] for o in orders], [1])

    def test_attack_is_the_default_when_the_player_holds_the_objective(self):
        state = battle(5, 5)
        plan = goals.make_plan(GOALS, state, [OBJECTIVE], 1.0, 10, 100, 100, None, (50, 60))
        self.assertEqual(plan["mode"], "ATTACK")
        self.assertEqual(plan["targets"][0]["name"], "Logan Cross")

    def test_relief_pulls_back_a_broken_brigade_in_contact(self):
        state = battle(4, 4)
        state["units"][0]["morale"] = 0.4
        drop, added = relief.relief_orders(state, [{"cmd": "hold", "id": 1}], None, {}, {}, None, {}, {})
        self.assertIn(1, drop)
        self.assertTrue(any(o["id"] == 1 and o["cmd"] in ("fallback", "move") for o in added))

    def test_assault_group_walks_to_the_staging_area(self):
        state = battle(6, 2)
        plan = {"mode": "ATTACK", "targets": [OBJECTIVE]}
        mem = {}
        _, added = assault.assault_orders(state, [], plan, None, {}, {}, {"fire": 500}, None, mem)
        self.assertTrue(added)
        self.assertTrue(all(o.get("auto") for o in added))


class CommanderTests(unittest.TestCase):
    def setUp(self):
        self.cwd = os.getcwd()
        os.chdir(SERVER)

    def tearDown(self):
        os.chdir(self.cwd)

    def test_a_planning_turn_runs_end_to_end(self):
        config = planner_server.load_config("config.json")
        config["backend"] = "placeholder"
        commander = planner_server.Commander(config)

        class Stub:
            supports_schema = False
            last_info = {"usage": {"input_tokens": 100, "cache_read_input_tokens": 50, "output_tokens": 20}}

            def complete(self, system, user, **kw):
                return json.dumps({"reasoning": "Hold the line.", "orders": [{"cmd": "hold", "id": 1}]})

        commander.backend = Stub()
        state = battle(5, 5)
        commander.goals = GOALS
        with redirect_stdout(io.StringIO()):
            commander.track(state)
            orders = commander.plan(state, os.devnull)
        self.assertTrue(any(o["id"] == 1 for o in orders))
        self.assertEqual(commander.tokens["input"], 100)


if __name__ == "__main__":
    unittest.main()
