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
import generals  # noqa: E402
import goals  # noqa: E402
import perks  # noqa: E402
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


class PerkTests(unittest.TestCase):
    def test_bonus_files_are_read_and_give_roles(self):
        kinds = perks.load(os.path.join(SERVER, "perks", "jp-rebalance-1.29.1"), "J&P Rebalance 1.29.1")
        self.assertIn("Infantry", kinds)
        self.assertIn("assault", perks.roles("Infantry", ["Assalt_course"]))
        self.assertIn("scout", perks.roles("Skirmish", ["Firearms_course"]))
        self.assertIn("Assalt_course", perks.prompt_section())
        self.assertIn("Cavalry", kinds)
        self.assertIn("dismounted only", perks.prompt_section())
        self.assertNotIn("fire", perks.roles("Cavalry", ["Shock_cavalry"]))


class CavalryAndGeneralTests(unittest.TestCase):
    def test_mount_orders_follow_the_game_rules(self):
        state = {"time": 600.0, "playerSide": "North", "units": [
            unit(1, "Cavalry", "South", 1000, 1000, mount="mounted", canDismount=True),
            unit(2, "Cavalry", "South", 1100, 1000, mount="mounted", canDismount=False),
            unit(3, "Cavalry", "South", 1200, 1000, mount="dismounted", canDismount=True),
            unit(50, "Infantry", "North", 1200, 1150)]}
        raw = [{"cmd": "mount", "id": 1, "value": "dismount"}, {"cmd": "mount", "id": 2, "value": "dismount"},
               {"cmd": "charge", "id": 3, "target": 50}]
        orders = prompting.sanitize(raw, state, 10)
        self.assertEqual([(o["id"], o["cmd"]) for o in orders], [(1, "mount")])

    def test_general_follows_his_brigades_and_keeps_away_from_the_enemy(self):
        state = {"time": 600.0, "playerSide": "North", "units": [
            unit(1, "Infantry", "South", 1000, 1000, corps=2), unit(2, "Infantry", "South", 1200, 1000, corps=2),
            unit(9, "General", "South", 300, 300, corps=2, commandRadius=300),
            unit(50, "Infantry", "North", 1100, 1500)]}
        moves = generals.general_orders(state, [], None, {}, {}, None, {})
        self.assertEqual(len(moves), 1)
        spot = {"x": moves[0]["x"], "z": moves[0]["z"]}
        self.assertGreaterEqual(prompting.nearest(spot, [state["units"][3]])[1], 650)
        g, rest = generals.sanitize_generals([{"cmd": "move", "id": 9, "x": 1100, "z": 1400}], state)
        self.assertEqual(rest, [])
        self.assertGreaterEqual(prompting.nearest(g[0], [state["units"][3]])[1], 650)


class TerrainRuleTests(unittest.TestCase):
    def terrain(self):
        import terrain
        rows = ["..FFF...", "..FFF...", "..FFF...", "..FFF..."]
        return terrain.TerrainMap({"minX": 0, "minZ": 0, "maxX": 800, "maxZ": 400, "step": 100,
                                   "terrain": rows, "heights": ["11111111"] * 4,
                                   "legend": {".": "Grass", "F": "DenseForest"}, "objectives": [],
                                   "rules": {"Infantry": {"Grass": "Speed 100%\nStealth 2.5%",
                                                          "DenseForest": "Speed 60%\nStealth 500%"}}})

    def test_charge_through_woods_becomes_an_attack_and_guns_avoid_woods(self):
        import terrain_rules
        t = self.terrain()
        state = {"time": 600.0, "playerSide": "North", "units": [
            unit(1, "Infantry", "South", 150, 200), unit(2, "Artillery", "South", 100, 100),
            unit(50, "Infantry", "North", 650, 200)]}
        out = terrain_rules.filter_orders([{"cmd": "charge", "id": 1, "target": 50},
                                           {"cmd": "move", "id": 2, "x": 350, "z": 150}],
                                          state, t, {"charge": 500})
        self.assertEqual(out[0]["cmd"], "attack")
        self.assertFalse(t.is_slow(out[1]["x"], out[1]["z"]))

    def test_phase_objective_replaces_objectives_not_on_this_map(self):
        config = planner_server.load_config(os.path.join(SERVER, "config.json"))
        config["backend"] = "placeholder"
        commander = planner_server.Commander(config)
        res = {"mode": "ATTACK", "targets": [], "route": ["hold: Pittsburg Landing"], "lines": [], "posture": ""}
        church = {"name": "Shiloh Church", "x": 0, "z": 0, "side": "North", "victoryPoints": 500}
        out = commander.phase_override(res, battle(3, 3), [church])
        self.assertEqual(out["targets"][0]["name"], "Shiloh Church")
        self.assertIn("PHASE OBJECTIVE", out["posture"])


class LargeArmyTests(unittest.TestCase):
    def test_caps_grow_with_the_army(self):
        state = battle(100, 10)
        mine, foes = prompting.split_units(state)
        group = assault.select_group(mine, foes, OBJECTIVE, dict(assault.DEFAULT_ASSAULT), {})
        self.assertGreater(len(group), assault.DEFAULT_ASSAULT["group_max"])


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

    def test_reflexes_are_off_in_dry_run_and_slow_down_the_turns(self):
        config = planner_server.load_config("config.json")
        config["backend"] = "placeholder"
        commander = planner_server.Commander(config)
        self.assertFalse(commander.reflex_command(True)["enabled"])
        self.assertTrue(commander.reflex_command(False)["enabled"])
        commander.note_reflexes({"reflexEvents": ["[15:01] face: #724 turned to face #62"]})
        self.assertIn("REFLEXES SINCE YOUR LAST TURN", commander.reflex_lines()[0])
        commander.engaged = True
        delay, _ = commander.next_delay({"units": [], "playerSide": "North", "time": 900})
        self.assertEqual(delay, config["reflexes"]["engaged_interval_s"])



class CavalryUnderFire(unittest.TestCase):
    def _state(self):
        cav = {"id": 1, "side": "South", "kind": "Cavalry", "x": 0.0, "z": 0.0, "dx": 0.0, "dz": 1.0, "hp": 700,
               "maxHp": 800, "morale": 0.8, "status": "idle", "mount": "mounted"}
        skirm = {"id": 9, "side": "North", "kind": "Skirmish", "x": 0.0, "z": 350.0, "hp": 200, "maxHp": 200,
                 "morale": 0.9, "status": "firing"}
        return {"playerSide": "North", "units": [cav, skirm]}

    def test_withdraw_or_charge(self):
        import terrain_rules
        state = self._state()
        out = terrain_rules.unseen_orders(state, {1: 760}, None, [])
        self.assertEqual(out[0]["cmd"], "move")
        self.assertLess(out[0]["z"], 0)
        out = terrain_rules.unseen_orders(state, {1: 760}, None, [], 0.8)
        self.assertEqual((out[0]["cmd"], out[0]["target"]), ("charge", 9))
        self.assertEqual(terrain_rules.unseen_orders(state, {1: 705}, None, []), [])

    def test_infantry_out_ranged(self):
        import terrain_rules
        state = self._state()
        state["units"][0].update(kind="Infantry", mount=None, range=200)
        state["units"][1].update(z=380.0)
        careful = terrain_rules.unseen_orders(state, {1: 760}, None, [], 0.2)
        self.assertLess(careful[0]["z"], 0)                       # opens the distance
        balanced = terrain_rules.unseen_orders(state, {1: 760}, None, [], 0.5)
        self.assertGreater(balanced[0]["z"], 0)                   # closes in to answer the fire
        state["units"][1].update(z=150.0)
        self.assertEqual(terrain_rules.unseen_orders(state, {1: 760}, None, [], 0.5), [])  # it can shoot back


class FireSpots(unittest.TestCase):
    def test_best_fire_spot_prefers_cover(self):
        import terrain as T
        grid = ["G" * 20 for _ in range(20)]
        for r in range(8, 13):
            grid[r] = "G" * 12 + "F" * 8              # forest east of the target, inside the fire range
        tmap = T.TerrainMap({"minX": 0, "minZ": 0, "maxX": 600, "maxZ": 600, "step": 30.0, "terrain": grid,
                             "heights": ["0" * 20 for _ in range(20)], "legend": {"G": "Grass", "F": "Forest"}})
        spot = tmap.best_fire_spot(560.0, 315.0, 300.0, 315.0, 250.0)
        self.assertEqual(spot[2], "Forest")


class ScoutPerks(unittest.TestCase):
    def test_effects_win_over_names(self):
        import cavalry
        import perks
        perks.load(os.path.join(SERVER, "perks", "jp-rebalance-1.29.1"))
        cfg = cavalry.DEFAULT_CAVALRY
        pick = lambda p: cavalry.scout_perks({"kind": "Cavalry", "perks": [p]}, cfg)
        self.assertEqual(pick("Recon_course"), [])                 # charge perk despite its name
        self.assertEqual(pick("Cavalry_training"), ["Cavalry_training"])
        self.assertEqual(pick("Eagle_scouts"), ["Eagle_scouts"])   # unknown perk: name fallback


class Routes(unittest.TestCase):
    def test_route_avoids_woods(self):
        import routes
        import terrain as T
        grid = ["G" * 30 for _ in range(30)]
        for r in range(0, 26):
            grid[r] = "G" * 12 + "M" * 6 + "G" * 12      # a wide strip of mud (speed 1/3), open at the top rows
        tmap = T.TerrainMap({"minX": 0, "minZ": 0, "maxX": 900, "maxZ": 900, "step": 30.0, "terrain": grid,
                             "heights": ["0" * 30 for _ in range(30)],
                             "legend": {"G": "Grass", "M": "Mud"}})
        via = routes.route(tmap, {"id": 1, "kind": "Infantry", "x": 100.0, "z": 700.0}, 800.0, 700.0)
        self.assertTrue(via)
        self.assertTrue(any(z > 760 for _, z in via))       # goes round the mud by the open gap


class MacroCommand(unittest.TestCase):
    def test_extract_assaults(self):
        from prompting import extract_assaults
        raw = json.dumps({"reasoning": "x", "orders": [], "assaults": [
            {"objective": "Spain Field", "group": [1, 2], "launch": "now"},
            {"objective": "Larkin", "group": [2, 3], "approach": [10, 20], "launch": "bogus"},
            {"objective": "third one"}]})
        a = extract_assaults(raw)
        self.assertEqual(len(a), 2)
        self.assertEqual(a[0]["launch"], "now")
        self.assertEqual(a[1]["group"], [3])                   # no brigade in two assaults
        self.assertEqual(a[1]["launch"], "auto")
        self.assertIsNone(extract_assaults(json.dumps({"reasoning": "x", "orders": []})))


class Cohesion(unittest.TestCase):
    def test_lone_brigade_recalled(self):
        import cohesion
        units = [{"id": 1, "side": "South", "kind": "Infantry", "x": 0.0, "z": 0.0, "hp": 2000, "maxHp": 2000,
                  "morale": 1.0, "status": "", "range": 400},
                 {"id": 2, "side": "South", "kind": "Infantry", "x": 100.0, "z": 0.0, "hp": 2000, "maxHp": 2000,
                  "morale": 1.0, "status": "", "range": 400},
                 {"id": 3, "side": "South", "kind": "Infantry", "x": 2000.0, "z": 0.0, "hp": 2000, "maxHp": 2000,
                  "morale": 1.0, "status": "", "range": 400}]
        state = {"playerSide": "North", "units": units}
        drop, new = cohesion.cohesion_orders(state, [], [{"x": 0.0, "z": 300.0}])
        self.assertEqual([(o["cmd"], o["id"]) for o in new], [("move", 3)])
        self.assertLess(new[0]["x"], 2000.0)
        # an order sending brigade 2 far out alone is dropped
        drop, new = cohesion.cohesion_orders(state, [{"cmd": "move", "id": 2, "x": 100.0, "z": 3000.0}],
                                             [{"x": 0.0, "z": 300.0}])
        self.assertIn(2, drop)


class ChaseLeash(unittest.TestCase):
    def test_chase_near_friends_allowed_far_stopped(self):
        import cohesion
        mk = lambda i, side, kind, x, z, **k: {"id": i, "side": side, "kind": kind, "x": x, "z": z, "hp": 1000,
                                               "maxHp": 1000, "morale": 1.0, "status": "", "range": 400, **k}
        friends = [mk(1, "South", "Infantry", 0.0, 0.0), mk(2, "South", "Infantry", 0.0, 200.0)]
        skirm = mk(9, "North", "Skirmish", 0.0, 1300.0, range=650)
        near = mk(3, "South", "Infantry", 0.0, 500.0)          # 300 from friends: may chase
        state = {"playerSide": "North", "units": friends + [near, skirm]}
        last = {3: {"cmd": "attack", "id": 3, "target": 9}}
        self.assertEqual(cohesion.cohesion_orders(state, [], [], last_cmds=last)[1], [])
        far = mk(3, "South", "Infantry", 0.0, 750.0)           # 550 from friends and from the target
        state = {"playerSide": "North", "units": friends + [far, skirm]}
        drop, new = cohesion.cohesion_orders(state, [], [], last_cmds=last, previous_hp={3: 1050.0})
        self.assertEqual(new[0]["cmd"], "move")                   # under fire: steps back towards its friends
        self.assertLess(new[0]["z"], 750.0)


class FinalCharge(unittest.TestCase):
    def test_close_then_charge(self):
        import final_charge
        mk = lambda i, side, kind, x, z, m=1.0: {"id": i, "side": side, "kind": kind, "x": x, "z": z, "hp": 1500,
                                                 "maxHp": 1500, "morale": m, "status": ""}
        units = [mk(1, "South", "Infantry", 0.0, 0.0), mk(2, "South", "Infantry", 200.0, 0.0),
                 mk(3, "South", "Infantry", 400.0, 0.0, 0.5), mk(4, "South", "Infantry", 100.0, -400.0),
                 mk(9, "North", "Infantry", 100.0, 1500.0)]
        target = {"name": "Hill", "x": 100.0, "z": 1600.0, "side": "North", "captureRange": 200}
        state = {"playerSide": "North", "units": units, "briefing": {"timeLeftS": 1100}}
        mem = {}
        drop, new, lines = final_charge.final_charge_orders(state, [], target, None, mem)
        self.assertEqual({o["cmd"] for o in new}, {"move"})       # 18 min left: close in first
        self.assertNotIn(3, {o["id"] for o in new})               # shaken brigade left out
        for u in units[:4]:
            if u["id"] in (1, 2):
                u["z"] = 1100.0                                    # now within 500 of the defender
        state["briefing"]["timeLeftS"] = 700                       # under 12 minutes: everybody charges
        drop, new, lines = final_charge.final_charge_orders(state, [], target, None, mem)
        self.assertIn(("charge", 1), {(o["cmd"], o["id"]) for o in new})

if __name__ == "__main__":
    unittest.main()
