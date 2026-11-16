"""Smoke tests for the planner server: synthetic battles, no game and no model needed.

Run from the repository root:  python -m unittest discover -s tests
"""
import io
import json
import math
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
import terrain_rules  # noqa: E402
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


def open_terrain(size=6000, step=100):
    """A flat grass map covering the synthetic battles."""
    import terrain
    n = size // step
    return terrain.TerrainMap({"minX": 0, "minZ": 0, "maxX": size, "maxZ": size, "step": step,
                               "terrain": ["." * n] * n, "heights": ["1" * n] * n,
                               "legend": {".": "Grass"}, "objectives": []})


class PromptTests(unittest.TestCase):
    def test_units_far_from_the_fight_get_a_short_line(self):
        # 0.1.4: every profile gives a short line (no ground, no route note) to units beyond detail_radius
        state = battle(60, 60, rear_share=0.4)
        large = planner_server.DEFAULT_CONFIG["scale"]["large"]
        t = open_terrain()
        full = prompting.build_user_prompt(state, [], [], terrain=t)
        compact = prompting.build_user_prompt(state, [], [], terrain=t, scale=large)
        self.assertLess(len(compact), len(full))
        rows = {int(l.split(" | ")[0]): l for l in compact.splitlines()
                if " | Infantry | " in l and l.split(" | ")[0].isdigit()}
        front, rear = rows[1].split(" | "), rows[60].split(" | ")      # unit 1 at z 3500, unit 60 at z 2000
        self.assertEqual(rear[7], "-")
        self.assertNotIn("way ", rows[60])
        self.assertTrue(front[7].startswith("Grass/"))
        # without a profile nobody is "far": the rear unit keeps its ground
        self.assertTrue(rows and full.splitlines()[0].startswith("Battle time"))
        full_rear = next(l for l in full.splitlines() if l.startswith("60 | "))
        self.assertTrue(full_rear.split(" | ")[7].startswith("Grass/"))

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
        self.assertLess(balanced[0]["z"], 0)                      # WIP11: a brigade does not chase skirmishers
        state["units"][1].update(kind="Infantry")
        balanced = terrain_rules.unseen_orders(state, {1: 760}, None, [], 0.5)
        self.assertGreater(balanced[0]["z"], 0)                   # closes in on infantry to answer the fire
        state["units"][1].update(z=150.0)
        self.assertEqual(terrain_rules.unseen_orders(state, {1: 760}, None, [], 0.5), [])  # it can shoot back


class Wip11DryRun(unittest.TestCase):
    """Battle of 2026-11-13 14:31: a dry run (the game's AI fought) was credited to the model as a victory."""
    def test_dry_run_kept_apart(self):
        import report, tempfile
        here = os.getcwd()
        with tempfile.TemporaryDirectory() as tmp:
            os.chdir(tmp)
            try:
                r = {"ended": "x", "outcome": "victory", "points": 3, "kd_men": 1.6, "own_men_lost": 10,
                     "enemy_men_lost_seen": 16, "dry_run": True, "duration_s": 600, "outcome_source": "game",
                     "game_result_for_player": "Defeat", "outcome_reason": "", "own_men_start": 100,
                     "own_units_lost": 0, "enemy_units_broken_seen": 1, "kd_units": 1.0, "verdict": "good",
                     "objectives": {"ai": 1, "ai_vp": 100, "player": 0, "player_vp": 0, "unheld": 0},
                     "brigades": [], "enemy_units": []}
                sb = report.record(r, "claude_code:sonnet", dry_run=True)
                self.assertEqual(sb["battles"], 0)
                self.assertEqual(sb["points"], 0)
                self.assertEqual(sb["history"], [])
                self.assertNotIn("by_model", sb)
                self.assertEqual(sb["dry_runs"][0]["commander"], "game AI (dry run)")
                self.assertTrue(any(n.endswith("-dryrun.json") for n in os.listdir("reports")))
            finally:
                os.chdir(here)

    def test_dry_run_shown_in_game(self):
        config = planner_server.load_config(os.path.join(SERVER, "config.json"))
        config["backend"] = "placeholder"
        config["dry_run"] = True
        c = planner_server.Commander(config)
        cmd = c.thought_command({"time": 10}, {})
        self.assertIn("DRY RUN", cmd["mode"])
        self.assertIn("dry_run", cmd["text"])


class Wip11LoneCharge(unittest.TestCase):
    """Battle of 2026-11-13 14:31: Hood charged alone among steady enemy brigades and was destroyed."""
    def _state(self, neighbour_morale):
        me = {"id": 1, "side": "South", "kind": "Infantry", "x": 0.0, "z": 0.0, "dx": 0.0, "dz": 1.0, "hp": 2000,
              "maxHp": 2000, "morale": 0.9, "fatigue": 0.9, "status": "", "range": 400, "chargeRange": 200}
        weak = {"id": 9, "side": "North", "kind": "Infantry", "x": 0.0, "z": 150.0, "hp": 600, "maxHp": 2000,
                "morale": 0.3, "status": ""}
        nb = {"id": 10, "side": "North", "kind": "Infantry", "x": 250.0, "z": 150.0, "hp": 2000, "maxHp": 2000,
              "morale": neighbour_morale, "status": ""}
        return {"playerSide": "North", "units": [me, weak, nb]}

    def test_no_lone_charge_on_a_supported_target(self):
        import autopilot
        ranges = {"fire": 400, "charge": 200}
        cfg = {"max_per_turn": 4, "max_charges": 2}
        st = self._state(0.9)
        st["units"][0].update(morale=0.75)                              # WIP12: not fresh
        out = autopilot.engage_orders(st, [], ranges, cfg)
        self.assertFalse(any(o["cmd"] == "charge" for o in out))      # a steady neighbour 250 away
        out = autopilot.engage_orders(self._state(0.9), [], ranges, cfg)
        self.assertFalse(any(o["cmd"] == "charge" for o in out))      # WIP15: fresh, target broken, zone steady
        out = autopilot.engage_orders(self._state(0.3), [], ranges, cfg)
        self.assertTrue(any(o["cmd"] == "charge" for o in out))       # WIP15: zone broken (0.3): 0.77 of its men do
        st = self._state(0.3)
        st["units"][0].update(hp=3000, maxHp=3000)
        out = autopilot.engage_orders(st, [], ranges, cfg)
        self.assertTrue(any(o["cmd"] == "charge" and o["target"] == 9 for o in out))   # zone worn, men enough
        st = self._state(0.9)
        st["units"][1].update(morale=0.45)                              # shaken, not broken: support counts
        out = autopilot.engage_orders(st, [], ranges, cfg)
        self.assertFalse(any(o["cmd"] == "charge" for o in out))


class Wip11FixScoreboard(unittest.TestCase):
    """The dry-run victory of 2026-11-13 15:20:06 is moved to dry_runs, totals and the model's line corrected."""
    def _sb(self):
        h = [{"ended": "a", "outcome": "defeat", "points": 0, "model": "m", "own_men_lost": 100,
              "enemy_men_lost_seen": 20},
             {"ended": "b", "outcome": "interrupted", "points": 0, "model": "m", "own_men_lost": 5,
              "enemy_men_lost_seen": 1},
             {"ended": "c", "outcome": "victory", "points": 3, "model": "m", "own_men_lost": 50,
              "enemy_men_lost_seen": 80, "kd_men": 1.6}]
        return {"battles": 3, "points": 3, "victories": 1, "draws": 0, "defeats": 1, "unknown": 0, "no_contest": 0,
                "interrupted": 1, "men_lost": 155, "enemy_men_lost_seen": 101, "history": h,
                "by_model": {"m": {"battles": 3, "points": 3, "victories": 1, "defeats": 1, "draws": 0,
                                   "men_lost": 155, "enemy_men_lost_seen": 101}}}

    def test_game_ai_battle_moved(self):
        import fix_scoreboard
        new, to_dry, removed, _ = fix_scoreboard.fix(self._sb(), {"c": "test"})
        self.assertEqual([h["ended"] for h in to_dry], ["c"])
        self.assertEqual((new["battles"], new["points"], new["victories"], new["interrupted"]), (2, 0, 0, 1))
        self.assertEqual(new["by_model"]["m"]["victories"], 0)
        self.assertEqual(new["by_model"]["m"]["men_lost"], 105)
        self.assertEqual(new["dry_runs"][0]["commander"], "game AI (dry run)")
        self.assertEqual(removed, [])
        again, to_dry2, _, _ = fix_scoreboard.fix(new, {"c": "test"})
        self.assertEqual(to_dry2, [])
        self.assertEqual(len(again["dry_runs"]), 1)

    def test_victories_kept_by_default(self):
        import fix_scoreboard
        new, _, removed, _ = fix_scoreboard.fix(self._sb(), {})
        self.assertEqual((new["victories"], removed), (1, []))

    def test_log_scan(self):
        import fix_scoreboard, tempfile
        def battle(ai_flag, ended):
            unit = {"id": 1, "side": "South", "kind": "Infantry", "ai": ai_flag}
            return [{"kind": "state", "payload": {"playerSide": "North", "units": [unit]}},
                    {"kind": "battle_report", "payload": {"ended": ended}}]
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "battle-1.jsonl"), "w") as fh:
                for rec in battle(True, "dry") + battle(False, "played"):
                    fh.write(json.dumps(rec) + "\n")
            found = fix_scoreboard.game_ai_battles_from_logs(tmp)
        self.assertEqual(set(found), {"dry"})


class Wip11UnseenLine(unittest.TestCase):
    """Kettle Run, 2026-11-13: unseen fire pulled Trimble out of the line twice (plugin reflex, then the server)."""
    def _state(self, neighbour_x):
        me = {"id": 1, "side": "South", "kind": "Infantry", "x": 0.0, "z": 0.0, "dx": 0.0, "dz": 1.0, "hp": 2400,
              "maxHp": 2500, "morale": 0.9, "status": "", "range": 200}
        nb = {"id": 2, "side": "South", "kind": "Infantry", "x": neighbour_x, "z": 0.0, "dx": 0.0, "dz": 1.0,
              "hp": 2500, "maxHp": 2500, "morale": 1.0, "status": "", "range": 200}
        foe = {"id": 9, "side": "North", "kind": "Infantry", "x": 0.0, "z": 380.0, "hp": 1700, "maxHp": 1750,
               "morale": 0.95, "status": ""}
        return {"playerSide": "North", "units": [me, nb, foe]}

    def test_step_stays_in_the_line(self):
        import terrain_rules
        out = terrain_rules.unseen_orders(self._state(300.0), {1: 2460}, None, [], 0.5)
        self.assertEqual(out, [])                                 # 220 ahead of its neighbour: refused, holds (WIP12)
        cfg = {"unseen_line_ahead": 300.0}
        out = terrain_rules.unseen_orders(self._state(300.0), {1: 2460}, None, [], 0.5, cfg=cfg)
        self.assertGreater(out[0]["z"], 0)                        # within the allowed distance: it closes in
        out = terrain_rules.unseen_orders(self._state(900.0), {1: 2460}, None, [], 0.5, cfg=cfg)
        self.assertEqual(out, [])                                 # neighbour 900 away: already alone, no step
        out = terrain_rules.unseen_orders(self._state(900.0), {1: 2460}, None, [], 0.5,
                                          cfg=dict(cfg, unseen_refused_holds=False))
        self.assertLess(out[0]["z"], 0)                           # the WIP11 fallback, when switched back on

    def test_hold_line(self):
        import terrain_rules
        cfg = {"unseen_line_ahead": 300.0}
        out = terrain_rules.unseen_orders(self._state(300.0), {1: 2460}, None, [], 0.5, cfg=cfg, hold_line=True)
        self.assertEqual(out, [])                                 # the plan defends: never forward, holds

    def test_reflex_settings_follow_the_plan(self):
        config = planner_server.load_config(os.path.join(SERVER, "config.json"))
        config["backend"] = "placeholder"
        c = planner_server.Commander(config)
        cmd = c.reflex_command(False)
        self.assertFalse(cmd["unseen_hold_line"])
        for key in ("unseen_chase_screens", "unseen_line_ahead", "unseen_neighbour_max", "cavalry"):
            self.assertIn(key, cmd)
        c.plan_info = {"mode": "DEFEND"}
        self.assertTrue(c.hold_line())
        self.assertTrue(c.reflex_command(False)["unseen_hold_line"])
        self.assertTrue(c.sent_hold_line)


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


# ---------------------------------------------------------------------------------------------------------
# 0.1.4-beta

class Sink:
    """Stands for the socket file of the game: keeps what the server sends."""
    def __init__(self):
        self.sent = []

    def write(self, text):
        self.sent += [json.loads(l) for l in text.splitlines() if l.strip()]

    def flush(self):
        pass


class Model:
    """Stub backend: counts the calls; answers are JSON texts, exceptions are raised."""
    supports_schema = False

    def __init__(self, *answers):
        self.answers, self.calls, self.last_info = list(answers), 0, {}

    def complete(self, system, user, **kw):
        self.calls += 1
        a = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(a, Exception):
            raise a
        return a


PLAIN = json.dumps({"reasoning": "Hold.", "plan": "Take Logan Cross from the south.", "orders": []})


def make_commander(*answers, **economy):
    config = planner_server.load_config(os.path.join(SERVER, "no-such-config.json"))   # the built-in defaults
    config["backend"] = "placeholder"
    config["assessment"] = {"enabled": False}
    config["economy"].update(economy)
    commander = planner_server.Commander(config)
    commander.backend = Model(*(answers or (PLAIN,)))
    commander.goals = GOALS
    return commander, config


def feed(commander, config, msg):
    sink = Sink()
    with redirect_stdout(io.StringIO()):
        planner_server.handle(sink, msg, os.devnull, commander, config)
    return sink.sent


class CallEconomy(unittest.TestCase):
    def test_model_calls_are_spaced_by_min_call_gap(self):
        commander, config = make_commander()
        feed(commander, config, battle(5, 5, 1800.0))
        self.assertEqual(commander.backend.calls, 1)                 # first state: always a call
        for t in (1830.0, 1860.0, 1900.0):                           # inside min_call_gap_s (150): staff work only
            feed(commander, config, battle(5, 5, t))
        self.assertEqual(commander.backend.calls, 1)
        self.assertEqual(commander.skipped_turns, 3)
        feed(commander, config, battle(5, 5, 1800.0 + 430.0))        # past max_gap_s (420): called whatever happens
        self.assertEqual(commander.backend.calls, 2)

    def test_a_critical_event_calls_the_model_at_once(self):
        commander, config = make_commander()
        feed(commander, config, battle(5, 5, 1800.0))
        taken = battle(5, 5, 1830.0)
        taken["objectives"] = [dict(OBJECTIVE, side="South")]        # the objective changed hands
        feed(commander, config, taken)
        self.assertEqual(commander.backend.calls, 2)
        broken = battle(5, 5, 1860.0)
        broken["objectives"] = [dict(OBJECTIVE, side="South")]
        broken["units"][0]["status"] = "routing"                     # a brigade broke
        feed(commander, config, broken)
        self.assertEqual(commander.backend.calls, 3)

    def test_soft_states_freeze_the_game_only_for_a_model_call(self):
        commander, config = make_commander()
        first = dict(battle(5, 5, 1800.0), soft=True)
        sent = feed(commander, config, first)
        self.assertEqual([m["cmd"] for m in sent if m["cmd"] in ("freeze", "plan_done")], ["freeze", "plan_done"])
        sent = feed(commander, config, dict(battle(5, 5, 1830.0), soft=True))
        self.assertNotIn("freeze", [m["cmd"] for m in sent])         # quiet turn: the game keeps running
        self.assertEqual(sent[-1]["cmd"], "plan_done")
        self.assertEqual(sent[-1]["next_in"], config["timing"]["staff_interval_s"])
        sent = feed(commander, config, battle(5, 5, 1860.0))         # plugin 0.1.3: no freeze, old interval
        self.assertNotIn("freeze", [m["cmd"] for m in sent])
        self.assertEqual(sent[-1]["next_in"], config["timing"]["engaged_interval_s"])


class Roster(unittest.TestCase):
    def systems(self, **economy):
        commander, config = make_commander(**economy)
        seen = []
        real = commander.backend.complete
        commander.backend.complete = lambda system, user, **kw: (seen.append((system, user)), real(system, user))[1]
        feed(commander, config, battle(5, 5, 1800.0))
        late = battle(5, 5, 2300.0)
        late["units"] += [unit(100 + k, "Infantry", "South", 1000 + 60 * k, 3300) for k in range(14)]
        feed(commander, config, late)
        self.assertEqual(len(seen), 2)
        return seen

    def test_late_brigades_do_not_rewrite_the_cached_system_prompt(self):
        (sys1, _), (sys2, user2) = self.systems()
        self.assertEqual(sys1, sys2)                                 # identical: read from the cache
        self.assertIn("100 | Infantry 100 |", user2)                 # the late brigades are in the unit table

    def test_roster_additions_can_be_switched_on(self):
        (sys1, _), (sys2, _) = self.systems(roster_max_folds=1)
        self.assertNotEqual(sys1, sys2)
        self.assertIn("Infantry 100", sys2)


class Prisoners(unittest.TestCase):
    """A captured unit changes side in the game (seen in the battle logs of 2026-11-10)."""

    def states(self):
        s1 = battle(4, 4, 1800.0)
        s2 = battle(4, 4, 1900.0)
        s2["units"][0].update(side="North", status="captured", hp=1200)    # our brigade 1 is taken prisoner
        s3 = battle(4, 4, 2000.0)
        s3["units"][0].update(hp=1100)                                       # ...and freed with 1100 men
        return s1, s2, s3

    def test_the_report_counts_a_prisoner_for_its_own_side(self):
        import report
        rep = report.BattleReport()
        s1, s2, s3 = self.states()
        rep.update(s1)
        rep.update(s2)
        self.assertEqual(rep.ai_side, "South")
        self.assertEqual(rep.own_start, 6000.0)
        self.assertEqual(rep.own_loss, 1500.0)                       # its men are lost while it is captured
        self.assertEqual(rep.lost_ids, {1})
        self.assertEqual(rep.foes_broken, set())                     # not "an enemy unit broken"
        self.assertEqual(rep.foe_loss, 0.0)
        rep.update(s3)
        self.assertEqual(rep.own_start, 6000.0)                      # freed: not a new brigade
        self.assertEqual(rep.own_loss, 400.0)
        self.assertEqual(rep.lost_ids, set())
        taken = battle(4, 4, 2100.0)
        taken["units"][0].update(hp=1100)
        taken["units"][4].update(side="South", status="captured", hp=900)   # we capture enemy 5001
        rep.update(taken)
        self.assertEqual(rep.own_start, 6000.0)
        self.assertEqual(rep.foes_broken, {5001})
        self.assertEqual(rep.foe_loss, 900.0)
        self.assertEqual(rep.lost_ids, set())

    def test_prisoners_do_not_call_the_model(self):
        commander, config = make_commander(new_enemy_men=1000)
        s1, s2, _ = self.states()
        feed(commander, config, s1)
        feed(commander, config, dict(s2, time=2000.0))               # past min_call_gap_s
        self.assertEqual(commander.new_foe_men, 0.0)                 # our prisoner is no "new enemy force"
        taken = battle(4, 4, 2200.0)
        taken["units"][4].update(side="South", status="captured")
        commander.last_call_snap = commander.call_snapshot(s1)
        self.assertNotIn(5001, commander.call_snapshot(taken)["own"])   # prisoners we took: no "reinforcements"
        text = prompting.build_user_prompt(taken, [], [])
        self.assertIn("(+1 enemy units shattered or captured, not listed)", text)
        self.assertNotIn("of your units", text)


class EveryTurnMode(unittest.TestCase):
    def test_without_quiet_turns_the_states_keep_the_long_interval(self):
        # skip_quiet_turns off = one model call per state: a state every staff_interval_s would be a call every
        # 30 game seconds
        commander, config = make_commander(skip_quiet_turns=False)
        sent = feed(commander, config, dict(battle(5, 5, 1800.0), soft=True))
        self.assertEqual(sent[-1]["next_in"], config["timing"]["engaged_interval_s"])
        sent = feed(commander, config, dict(battle(5, 5, 1860.0), soft=True))
        self.assertEqual(commander.backend.calls, 2)
        self.assertIn("freeze", [m["cmd"] for m in sent])


class LostAnswers(unittest.TestCase):
    def test_a_lost_answer_keeps_the_staff_work_and_is_asked_again(self):
        from backends import BackendError
        commander, config = make_commander(BackendError("timeout"), PLAIN)
        sent = feed(commander, config, battle(6, 2, 1800.0))
        self.assertEqual(sent[-1]["cmd"], "plan_done")               # the game is never left frozen
        self.assertTrue(any(m.get("auto") for m in sent))            # the server's own orders still went out
        self.assertTrue(commander.retry_call)
        feed(commander, config, battle(6, 2, 1830.0))                # asked again at the next state
        self.assertEqual(commander.backend.calls, 2)
        self.assertFalse(commander.retry_call)
        self.assertEqual(commander.fail_streak, 0)

    def test_a_failing_backend_is_tried_less_and_less_often(self):
        from backends import BackendError
        commander, config = make_commander(BackendError("not logged in"))
        for t in (1800.0, 1830.0):
            feed(commander, config, battle(5, 5, t))
        self.assertEqual(commander.backend.calls, 2)                 # one immediate retry
        feed(commander, config, battle(5, 5, 1860.0))                # then 60 battle seconds of patience
        self.assertEqual(commander.backend.calls, 2)
        feed(commander, config, battle(5, 5, 1895.0))
        self.assertEqual(commander.backend.calls, 3)
        feed(commander, config, battle(5, 5, 1990.0))                # then 120
        self.assertEqual(commander.backend.calls, 3)
        feed(commander, config, battle(5, 5, 2020.0))
        self.assertEqual(commander.backend.calls, 4)

    def test_answers_written_with_slips_are_repaired(self):
        load = prompting.load_answer
        hold = [{"cmd": "hold", "id": 1}]
        self.assertEqual(load('```json\n{"reasoning": "x", "orders": [{"cmd": "hold", "id": 1}]}\n```')["orders"], hold)
        self.assertEqual(load('{"reasoning": "x", "orders": [{"cmd": "hold", "id": 1}}]}')["orders"], hold)   # extra brace
        self.assertEqual(load('{"reasoning": "x", "orders": [{"cmd": "hold", "id": 1},],}')["orders"], hold)  # commas
        cut = load('{"reasoning": "x", "orders": [{"cmd": "hold", "id": 1}, {"cmd": "mo')                     # cut off
        self.assertEqual(cut["orders"][0], hold[0])
        # beyond repair as a whole: the flat orders are salvaged one by one, with the reasoning and the plan
        mess = ('{"reasoning": "He said \\"charge\\" twice", "plan": "North road", "orders": [{"cmd": "hold", "id": 1} '
                '{"cmd": "attack", "id": 2, "target": 5001}], "assaults": [{"objective": "Logan Cross"}] oops }')
        got = load(mess)
        self.assertTrue(got["_salvaged"])
        self.assertEqual([o["cmd"] for o in got["orders"]], ["hold", "attack"])
        self.assertEqual(got["reasoning"], 'He said "charge" twice')
        self.assertEqual(got["plan"], "North road")
        self.assertEqual(got["assaults"][0]["objective"], "Logan Cross")
        self.assertEqual(prompting.parse_answer(mess)[1], got["orders"])
        for bad in ("", "I cannot answer.", '{"reasoning": "only words'):
            with self.assertRaises(ValueError):
                load(bad)


class AssaultCommand(unittest.TestCase):
    def test_an_empty_assaults_list_changes_nothing(self):
        self.assertIsNone(prompting.extract_assaults(json.dumps({"reasoning": "x", "orders": [], "assaults": []})))
        answer = json.dumps({"reasoning": "x", "orders": [], "assaults": []})
        commander, config = make_commander(answer)
        state = battle(6, 2, 1800.0)
        state["objectives"] = [OBJECTIVE]
        directive = [{"objective": "Logan Cross", "group": [1, 2, 3], "launch": "now"}]
        commander.directives = list(directive)
        commander.phase_start = 0.0                                  # the map began 30 minutes ago
        feed(commander, config, state)
        self.assertEqual(commander.directives, directive)
        mem = commander.assault_mems["Logan Cross#0"]
        self.assertTrue(mem.get("launched"))
        feed(commander, config, dict(state, time=2300.0))            # a second answer with "assaults": []
        self.assertEqual(commander.backend.calls, 2)
        self.assertTrue(commander.assault_mems["Logan Cross#0"].get("launched"))   # not back to STAGING
        release = json.dumps({"reasoning": "x", "orders": [],
                              "assaults": [{"objective": "Logan Cross", "launch": "release"}]})
        commander.backend.answers = [release]
        feed(commander, config, dict(state, time=2800.0))
        self.assertFalse(commander.assault_mems["Logan Cross#0"].get("launched"))  # "release" hands it back

    def launched(self):
        state = battle(6, 2, 1800.0)
        plan = {"mode": "ATTACK", "targets": [OBJECTIVE]}
        mem = {"launched": True, "group": [1, 2, 3], "start_hp": {1: 1500.0, 2: 1500.0, 3: 1500.0}}
        return state, plan, mem

    def run_assault(self, state, plan, mem):
        with redirect_stdout(io.StringIO()):
            return assault.assault_orders(state, [], plan, None, {}, {}, {"fire": 500}, None, mem)

    def test_losses_are_counted_brigade_by_brigade_since_the_launch(self):
        state, plan, mem = self.launched()
        units = {u["id"]: u for u in state["units"]}
        units[1]["hp"], units[2]["hp"] = 1150, 1150
        units[3].update(hp=1400, morale=0.3)                         # shaken: leaves the group, but is not "lost"
        self.run_assault(state, plan, mem)
        self.assertTrue(mem["launched"])
        self.assertNotIn(3, mem["group"])
        started = sum(mem["start_hp"].values())                      # a fresh brigade took its place: 4 x 1500
        self.assertEqual(started, 6000.0)
        self.assertAlmostEqual(mem["loss_share"], 800 / started, places=3)   # 0.1.3 said 2 of 3 brigades "lost"
        units[3]["status"] = "routing"                               # routing: still only its dead count
        self.run_assault(state, plan, mem)
        self.assertTrue(mem["launched"])
        self.assertAlmostEqual(mem["loss_share"], 800 / started, places=3)
        units[3]["status"] = "shattered"                             # destroyed: counts in full
        self.run_assault(state, plan, mem)
        self.assertFalse(mem["launched"])                            # (350 + 350 + 1500) / 6000 = 37 % >= 35 %
        self.assertGreater(mem["paused_until"], state["time"])

    def test_staging_spots_are_kept_between_states(self):
        state = battle(6, 2, 1800.0)
        plan = {"mode": "ATTACK", "targets": [OBJECTIVE]}
        mem = {}
        self.run_assault(state, plan, mem)
        spots = dict(mem["stage"])
        for u in state["units"][:6]:
            u["z"] += 40                                             # the group walks: its centre moves
        state["time"] += 60.0
        self.run_assault(state, plan, mem)
        self.assertEqual(mem["stage"], spots)                        # same spots: no new move orders
        state["time"] += 300.0                                       # stage_refresh_s: computed again
        self.run_assault(state, plan, mem)
        self.assertGreater(mem["stage_time"], 1800.0)


class MoveReports(unittest.TestCase):
    def test_done_canceled_frees_the_pending_move(self):
        commander, _ = make_commander()
        commander.pending_moves = {1: (100.0, 200.0, 50.0), 2: (300.0, 400.0, 50.0)}
        commander.pending_expiry = {1: 500.0, 2: 500.0}
        commander.note_event({"type": "done", "id": 1, "canceled": True})
        self.assertNotIn(1, commander.pending_moves)
        self.assertNotIn(1, commander.pending_expiry)
        self.assertEqual(commander.events, [])                       # not an arrival
        self.assertEqual(commander.manual_arrivals, 0)
        commander.note_event({"type": "done", "id": 2, "canceled": False})
        self.assertNotIn(2, commander.pending_moves)
        self.assertEqual(commander.manual_arrivals, 1)
        self.assertIn("reached its destination", commander.events[0])
        commander.note_event({"type": "done", "id": 7, "canceled": True})   # unknown unit: ignored
        self.assertEqual(commander.manual_arrivals, 1)


class BattleEnd(unittest.TestCase):
    def test_a_mission_end_at_the_start_of_a_map_is_ignored(self):
        from unittest import mock
        commander, config = make_commander()
        feed(commander, config, battle(5, 5, 10.0))
        feed(commander, config, {"type": "battle_end", "resultKind": "mission", "result": "Mission finished"})
        self.assertIsNotNone(commander.report)                       # the battle goes on, memory kept
        self.assertEqual(commander.report.states, 1)
        self.assertEqual(commander.llm_calls, 1)
        with mock.patch.object(planner_server, "record", lambda **k: {"battles": 0}), \
                mock.patch.object(planner_server, "scoreboard_line", lambda s: ""):
            feed(commander, config, {"type": "battle_end", "resultKind": "battle", "result": "Victory"})
        self.assertIsNone(commander.report)                          # the player's end screen always closes it

    def test_a_mission_end_later_in_the_battle_is_a_phase(self):
        # WIP17 (Antietam 2026-11-15): "Mission finished" closes a phase of a chained battle; one report at the end
        from unittest import mock
        commander, config = make_commander()
        for t in (10.0, 40.0, 70.0):
            feed(commander, config, battle(5, 5, t))
        saved = []
        with mock.patch.object(planner_server, "record", lambda **k: saved.append(k["report"]) or {"battles": 0}), \
                mock.patch.object(planner_server, "scoreboard_line", lambda s: ""):
            feed(commander, config, {"type": "battle_end", "resultKind": "mission", "result": "Draw"})
            self.assertIsNotNone(commander.report)                   # the battle goes on
            self.assertEqual(commander.phases_done, 1)
            feed(commander, config, battle(5, 5, 100.0))
            feed(commander, config, {"type": "battle_end", "resultKind": "battle", "result": "Defeat"})
        self.assertIsNone(commander.report)
        self.assertEqual(len(saved), 1)
        self.assertEqual((saved[0]["game_result_kind"], saved[0]["phases"]), ("battle", 2))
        self.assertEqual(commander.phases_done, 0)

    def test_a_battle_left_after_a_phase_keeps_its_result(self):
        from unittest import mock
        commander, config = make_commander()
        for t in (10.0, 40.0, 70.0):
            feed(commander, config, battle(5, 5, t))
        saved = []
        with mock.patch.object(planner_server, "record", lambda **k: saved.append(k["report"]) or {"battles": 0}), \
                mock.patch.object(planner_server, "scoreboard_line", lambda s: ""), redirect_stdout(io.StringIO()):
            feed(commander, config, {"type": "battle_end", "resultKind": "mission", "result": "Draw"})
            commander.finish_battle(None, None, os.devnull)          # disconnect or a new map
        self.assertEqual(len(saved), 1)
        self.assertEqual((saved[0]["game_result_kind"], saved[0]["phases"]), ("mission", 1))


class FinalChargeAgain(unittest.TestCase):
    def setup(self):
        mk = lambda i, side, x, z: {"id": i, "side": side, "kind": "Infantry", "x": x, "z": z, "hp": 1500,
                                    "maxHp": 1500, "morale": 1.0, "status": ""}
        units = [mk(1, "South", 0.0, 1100.0), mk(2, "South", 200.0, 1100.0), mk(9, "North", 100.0, 1500.0)]
        target = {"name": "Hill", "x": 100.0, "z": 1600.0, "side": "North", "captureRange": 200}
        state = {"playerSide": "North", "time": 5000.0, "units": units, "briefing": {"timeLeftS": 600}}
        return state, target

    def charge(self, state, target, mem, last):
        import final_charge
        with redirect_stdout(io.StringIO()):
            final_charge.final_charge_orders(state, [], target, None, dict(mem), None, quiet=True)  # prompt preview
            _, new, _ = final_charge.final_charge_orders(state, [], target, None, mem, None, last)
        for o in new:
            last[o["id"]] = o
        return sorted(o["id"] for o in new if o["cmd"] == "charge")

    def test_a_charge_thrown_back_goes_in_again_after_recharge_s(self):
        state, target = self.setup()
        mem, last = {}, {}
        self.assertEqual(self.charge(state, target, mem, last), [1, 2])
        state["time"] += 30.0
        self.assertEqual(self.charge(state, target, mem, last), [])          # still running in
        state["time"] += 70.0                                                # 100 s after the charge: thrown back
        self.assertEqual(self.charge(state, target, mem, last), [1, 2])
        state["time"] += 30.0
        self.assertEqual(self.charge(state, target, mem, last), [])


# ---------------------------------------------------------------------------------------------------------
# 0.1.4, after the battle of 2026-11-11 13:24

def soldier(uid, side, x, z, kind="Infantry", **extra):
    u = {"id": uid, "name": f"{kind} {uid}", "kind": kind, "side": side, "x": float(x), "z": float(z), "hp": 1500.0,
         "maxHp": 1500.0, "morale": 1.0, "fatigue": 1.0, "status": "", "range": 400.0, "stars": 1}
    u.update(extra)
    return u


class Rotation(unittest.TestCase):
    def test_return_morale_follows_the_situation(self):
        import relief
        quiet = {"playerSide": "North", "units": [soldier(1, "South", 0, 0), soldier(9, "North", 0, 3000)]}
        self.assertEqual(relief.situation_level(quiet), ("calm", 0.75))
        fight = {"playerSide": "North", "units": [soldier(k, "South", 100 * k, 0) for k in range(1, 6)]
                 + [soldier(9, "North", 200, 400)]}
        self.assertEqual(relief.situation_level(fight), ("tense", 0.7))
        for u in fight["units"][:2]:
            u["morale"] = 0.4
        self.assertEqual(relief.situation_level(fight), ("critical", 0.65))
        self.assertEqual(relief.situation_level(quiet, stop_loss=True)[0], "calm")   # no contact: nothing to rotate

    def test_a_resting_brigade_waits_for_the_return_morale(self):
        import relief
        u = soldier(1, "South", 0, 0, morale=0.72)
        last = {1: {"cmd": "fallback", "id": 1, "relief": True}}
        try:
            relief.set_return_morale(0.75, "calm")
            self.assertTrue(relief.is_resting(u, last))
            relief.set_return_morale(0.7, "tense")
            self.assertFalse(relief.is_resting(u, last))
        finally:
            relief.set_return_morale(None)

    def test_newcomers_of_an_assault_need_eve_morale(self):
        mine = [soldier(k, "South", 100 * k, 0, morale=m) for k, m in ((1, 0.95), (2, 0.85), (3, 0.72), (4, 0.7))]
        cfg = dict(assault.DEFAULT_ASSAULT, group_share=1.0, group_max=4)
        group = assault.select_group(mine, [], {"x": 0.0, "z": 1000.0}, cfg, {}, join_morale=0.8)
        self.assertEqual(sorted(u["id"] for u in group), [1, 2])
        weak = [soldier(k, "South", 100 * k, 0, morale=0.7) for k in (1, 2, 3)]
        self.assertEqual(len(assault.select_group(weak, [], {"x": 0.0, "z": 1000.0}, cfg, {}, join_morale=0.8)),
                         cfg["group_min"])                    # too few rested brigades: topped up to the minimum

    def test_final_charge_takes_rested_brigades(self):
        import final_charge
        units = [soldier(1, "South", 0, 1100, morale=0.95), soldier(2, "South", 200, 1100, morale=0.9),
                 soldier(3, "South", 400, 1100, morale=0.75), soldier(9, "North", 100, 1500)]
        target = {"name": "Hill", "x": 100.0, "z": 1600.0, "side": "North", "captureRange": 200}
        state = {"playerSide": "North", "time": 5000.0, "units": units, "briefing": {"timeLeftS": 600}}
        with redirect_stdout(io.StringIO()):
            _, new, _ = final_charge.final_charge_orders(state, [], target, {"keep_back": 0}, {})
        self.assertEqual(sorted(o["id"] for o in new), [1, 2])


class AssaultTactics(unittest.TestCase):
    def defence(self):
        # three defenders facing south (towards our army); #52 is the weak one, alone on the east
        foes = [soldier(50, "North", 0, 2000, dz=-1.0, dx=0.0, stars=2), soldier(51, "North", 150, 2050, dz=-1.0, dx=0.0),
                soldier(52, "North", 900, 2000, dz=-1.0, dx=0.0, morale=0.55, hp=700.0, stars=0)]
        return foes

    def test_the_weak_point_is_the_weakest_and_least_supported_defender(self):
        foes = self.defence()
        self.assertEqual(assault.weak_point(foes)["id"], 52)
        foes[1]["morale"] = 0.5                               # a slightly weaker one appears: the choice is kept
        self.assertEqual(assault.weak_point(foes, {"weak": 52})["id"], 52)

    def test_the_group_stages_on_the_flank_of_the_weak_point(self):
        foes = self.defence()
        mine = [soldier(k, "South", 300 + 60 * k, 600) for k in range(1, 7)]
        state = {"playerSide": "North", "time": 1800.0, "units": mine + foes}
        obj = {"name": "Ridge", "x": 300.0, "z": 2100.0, "side": "North", "captureRange": 150}
        mem = {}
        with redirect_stdout(io.StringIO()):
            assault.assault_orders(state, [], {"mode": "ATTACK", "targets": [obj]}, None, {}, {}, {"fire": 400},
                                   None, mem)
        self.assertEqual(mem["weak"], 52)
        self.assertEqual(mem["weak_info"]["flank"], "left")   # its own left (east, it faces south): away from the others
        xs = [x for x, _ in mem["stage"].values()]
        self.assertGreater(min(xs), 900 + 200)                # the whole group stands east of the weak point
        lines = assault.assault_lines(state, {"mode": "ATTACK", "targets": [obj]}, None, mem, {"fire": 400})
        self.assertTrue(any("WEAK POINT: #52" in l and "left flank" in l for l in lines))

    def launched(self, morale=0.9, stars=2):
        foes = [soldier(50, "North", 0, 2000, dz=-1.0, dx=0.0, morale=0.9)]
        mine = [soldier(1, "South", -100, 1600, morale=morale, stars=stars), soldier(2, "South", 100, 1600, morale=morale, stars=stars)]
        state = {"playerSide": "North", "time": 3000.0, "units": mine + foes}
        obj = {"name": "Ridge", "x": 0.0, "z": 2100.0, "side": "North", "captureRange": 150}
        mem = {"launched": True, "group": [1, 2], "start_hp": {1: 1500.0, 2: 1500.0}}
        return state, obj, mem

    def charges(self, state, obj, mem):
        with redirect_stdout(io.StringIO()):
            _, new = assault.assault_orders(state, [], {"mode": "ATTACK", "targets": [obj]}, None, {}, {},
                                            {"fire": 400}, None, mem)
        return sorted(o["id"] for o in new if o["cmd"] == "charge")

    def test_fresh_brigades_good_in_melee_charge_a_steady_defender_together(self):
        self.assertEqual(self.charges(*self.launched()), [1, 2])
        self.assertEqual(self.charges(*self.launched(morale=0.75)), [])          # not fresh enough
        state, obj, mem = self.launched(stars=1)
        for u in state["units"][:2]:
            u["hp"] = 1200.0                                                   # fewer men, no stars: no mass charge
        self.assertEqual(self.charges(state, obj, mem), [])

    def test_a_brigade_on_the_flank_charges(self):
        state, obj, mem = self.launched(morale=0.75, stars=1)
        state["units"][2].update(dx=1.0, dz=0.0)          # the defender faces east: our brigades are on its flank
        self.assertEqual(self.charges(state, obj, mem), [1, 2])

    def test_trading_fire_from_cover_instead_of_chasing(self):
        import terrain as T
        n = 40
        grid = ["G" * n for _ in range(n)]
        for r in range(22, 26):
            grid[r] = "G" * 18 + "W" * 6 + "G" * 16          # a wheat field 600-700 north of the brigades, west side
        tmap = T.TerrainMap({"minX": -1000, "minZ": 1000, "maxX": 1000, "maxZ": 3000, "step": 50.0, "terrain": grid,
                             "heights": ["0" * n for _ in range(n)], "legend": {"G": "Grass", "W": "Wheat"},
                             "rules": {"Infantry": {"Grass": "Speed 100%\\nCover 50%\\nDamage 100%",
                                                    "Wheat": "Speed 90%\\nCover 120%\\nDamage 100%"}}})
        foes = [soldier(50, "North", 0, 2600, dz=-1.0, dx=0.0, morale=0.9)]
        mine = [soldier(1, "South", 0, 2250, morale=0.7)]
        state = {"playerSide": "North", "time": 3000.0, "units": mine + foes}
        obj = {"name": "Ridge", "x": 0.0, "z": 2700.0, "side": "North", "captureRange": 150}
        mem = {"launched": True, "group": [1], "start_hp": {1: 1500.0}}
        with redirect_stdout(io.StringIO()):
            _, new = assault.assault_orders(state, [], {"mode": "ATTACK", "targets": [obj]}, None, {}, {},
                                            {"fire": 400}, tmap, mem)
        self.assertEqual(len(new), 1)
        self.assertNotEqual(new[0]["cmd"], "attack")          # never a chase over open ground
        if new[0]["cmd"] == "move":
            self.assertEqual(tmap.name_at(new[0]["x"], new[0]["z"]), "Wheat")


class Batteries(unittest.TestCase):
    def test_smoothbore_comes_up_beside_a_steady_brigade(self):
        import battery
        line = soldier(1, "South", 0, 1600, width=150.0)
        gun = soldier(5, "South", 300, -400, kind="Artillery", range=1100.0, limber="ready",
                      weapon="gun_6pdr_Gun", width=216.0)
        foe = soldier(9, "North", 0, 2000)
        state = {"playerSide": "North", "time": 3000.0, "units": [line, gun, foe]}
        out = battery.battery_orders(state, [], None, None, {}, {})
        self.assertEqual([(o["cmd"], o["id"]) for o in out], [("move", 5)])
        d = math.hypot(out[0]["x"] - foe["x"], out[0]["z"] - foe["z"])
        self.assertTrue(430 <= d <= 560, d)                   # about 460 from the enemy, beside the brigade
        self.assertLess(math.hypot(out[0]["x"] - line["x"], out[0]["z"] - line["z"]), 260)
        from prompting import threatened_batteries
        placed = dict(gun, x=out[0]["x"], z=out[0]["z"])
        self.assertEqual(threatened_batteries([line, placed], [dict(foe, z=1900.0)]), [])   # its guard covers it
        clock = {5: 2950.0}
        self.assertEqual(battery.battery_orders(state, [], None, None, {}, clock), [])   # cooldown
        alone = {"playerSide": "North", "time": 3000.0, "units": [gun, foe]}
        self.assertEqual(battery.battery_orders(alone, [], None, None, {}, {}), [])     # no guard: it stays

    def test_rifled_guns_stay_behind_the_line(self):
        import battery
        line = soldier(1, "South", 0, 1600)
        gun = soldier(5, "South", 0, -1000, kind="Artillery", range=1450.0, limber="ready",
                      weapon="gun_10pdr_Parrott_Rifle_RF")
        foe = soldier(9, "North", 0, 2000)
        out = battery.battery_orders({"playerSide": "North", "time": 1.0, "units": [line, gun, foe]}, [], None, None, {}, {})
        d = math.hypot(out[0]["x"] - foe["x"], out[0]["z"] - foe["z"])
        self.assertAlmostEqual(d, 0.8 * 1450, delta=80)


class Wagons(unittest.TestCase):
    def state(self, ammo=0.25):
        line = [soldier(k, "South", 150 * k, 1600, ammo=ammo) for k in range(1, 4)]
        wagon = soldier(20, "South", 0, 0, kind="Supply", supplyStock=0.9, supplyRange=450.0)
        foes = [soldier(9, "North", 150, 2000)]
        return {"playerSide": "North", "time": 3000.0, "units": line + [wagon] + foes}

    def test_the_wagon_drives_up_when_several_units_of_the_line_run_low(self):
        import supply
        out = supply.supply_orders(self.state(), [], None)
        moves = [o for o in out if o["cmd"] == "move" and o["id"] == 20]
        self.assertEqual(len(moves), 1)
        spot = moves[0]
        self.assertGreaterEqual(math.hypot(spot["x"] - 150, spot["z"] - 2000), 300)     # not near the enemy
        covered = sum(1 for k in (1, 2, 3) if math.hypot(spot["x"] - 150 * k, spot["z"] - 1600) <= 450)
        self.assertGreaterEqual(covered, 2)

    def test_the_wagon_waits_behind_the_line_otherwise(self):
        import supply
        out = supply.supply_orders(self.state(ammo=0.9), [], None)
        moves = [o for o in out if o["cmd"] == "move" and o["id"] == 20]
        self.assertEqual(len(moves), 1)
        d = math.hypot(moves[0]["x"] - 150, moves[0]["z"] - 2000)
        self.assertAlmostEqual(d, 750, delta=100)


class MarchColumns(unittest.TestCase):
    """Road column on long marches, back in line 600 from a known enemy (march.py)."""

    def state(self, own_z, foe_z=None, t=100.0, **extra):
        units = [unit(1, "Infantry", "South", 1000, own_z, **extra)]
        if foe_z is not None:
            units.append(unit(9, "Infantry", "North", 1000, foe_z))
        return {"playerSide": "North", "time": t, "units": units}

    def run_march(self, state, orders=(), pending=None, columns=None, gaps=None, **cfg):
        import march
        columns = {} if columns is None else columns
        gaps = {} if gaps is None else gaps
        out = march.march_orders(state, list(orders), pending or {}, columns, gaps, cfg or None)
        return out, columns, gaps

    def test_a_long_march_far_from_the_enemy_goes_in_road_column(self):
        move = {"cmd": "move", "id": 1, "x": 1000, "z": 2000}
        out, columns, _ = self.run_march(self.state(0, 3000), [move])
        self.assertEqual(out, [{"cmd": "formation", "id": 1, "value": "RoadColumn", "auto": True}])
        self.assertIn(1, columns)

    def test_no_column_for_a_short_move_nor_near_the_enemy(self):
        short = {"cmd": "move", "id": 1, "x": 1000, "z": 400}
        self.assertEqual(self.run_march(self.state(0, 3000), [short])[0], [])
        move = {"cmd": "move", "id": 1, "x": 1000, "z": -2000}
        self.assertEqual(self.run_march(self.state(0, 700), [move])[0], [])       # 700 < 600 + margin 150
        self.assertEqual(self.run_march(self.state(0, 3000), [dict(move, id=1)],
                                        columns=None, kinds=["Cavalry"])[0], [])  # infantry not in "kinds"

    def test_a_column_deploys_at_600_from_a_known_enemy(self):
        pending = {1: (1000, 3000, 0.0)}
        out, columns, _ = self.run_march(self.state(0, 650), pending=pending, columns={1: 0.0})
        self.assertEqual(out, [])                                                 # 650: still in column
        out, columns, _ = self.run_march(self.state(0, 600), pending=pending, columns={1: 0.0})
        self.assertEqual(out, [{"cmd": "formation", "id": 1, "value": "Line", "auto": True}])
        self.assertEqual(columns, {})

    def test_a_closing_gap_deploys_one_state_early(self):
        pending = {1: (1000, 3000, 0.0)}
        gaps = {1: (70.0, 720.0)}                                                 # 720 -> 650 in one state
        out, _, _ = self.run_march(self.state(0, 650, t=100.0), pending=pending, columns={1: 0.0}, gaps=gaps)
        self.assertEqual([o["value"] for o in out], ["Line"])                     # 580 by the next state
        out, _, _ = self.run_march(self.state(0, 650, t=100.0), pending=pending, columns={1: 0.0},
                                   gaps={1: (70.0, 720.0)}, anticipate=False)
        self.assertEqual(out, [])

    def test_a_remembered_enemy_counts(self):
        import march
        columns = {1: 0.0}
        seen = [{"id": 9, "x": 1000, "z": 500, "t": 50.0}]
        out = march.march_orders(self.state(0, None), [], {1: (1000, 3000, 0.0)}, columns, {}, None, seen)
        self.assertEqual([o["value"] for o in out], ["Line"])
        columns = {1: 0.0}
        old = [{"id": 9, "x": 1000, "z": 500, "t": -900.0}]                       # seen too long ago
        out = march.march_orders(self.state(0, None), [], {1: (1000, 3000, 0.0)}, columns, {}, None, old)
        self.assertEqual(out, [])

    def test_a_column_deploys_when_the_march_ends_or_an_attack_replaces_it(self):
        out, _, _ = self.run_march(self.state(0, 3000), columns={1: 0.0})         # no pending move left
        self.assertEqual([o["value"] for o in out], ["Line"])
        attack = {"cmd": "attack", "id": 1, "target": 9}
        out, _, _ = self.run_march(self.state(0, 3000), [attack], {1: (1000, 2500, 0.0)}, {1: 0.0})
        self.assertEqual([o["value"] for o in out], ["Line"])
        out, _, _ = self.run_march(self.state(2900, 9000), pending={1: (1000, 3000, 0.0)}, columns={1: 0.0})
        self.assertEqual([o["value"] for o in out], ["Line"])                     # 100 from its destination
        switch = {"cmd": "gait", "id": 1, "value": "Run"}                         # a switch does not end the march
        out, _, _ = self.run_march(self.state(0, 3000), [switch], {1: (1000, 2500, 0.0)}, {1: 0.0})
        self.assertEqual(out, [])

    def test_a_routing_column_is_put_back_in_line_and_a_captured_one_forgotten(self):
        out, columns, _ = self.run_march(self.state(0, 3000, status="routing"),
                                         pending={1: (1000, 2500, 0.0)}, columns={1: 0.0})
        self.assertEqual([o["value"] for o in out], ["Line"])
        out, columns, _ = self.run_march(self.state(0, 3000, status="captured"), columns={1: 0.0})
        self.assertEqual((out, columns), ([], {}))

    def test_switched_off_brings_the_columns_back_in_line(self):
        out, columns, _ = self.run_march(self.state(0, 3000), pending={1: (1000, 2500, 0.0)}, columns={1: 0.0},
                                         enabled=False)
        self.assertEqual(([o["value"] for o in out], columns), (["Line"], {}))

    def test_the_server_sends_the_formation_before_the_move_and_keeps_the_march_pending(self):
        answer = json.dumps({"reasoning": "March.", "orders": [{"cmd": "move", "id": 1, "x": 1000, "z": 3000}]})
        commander, config = make_commander(answer)
        commander.goals = []
        state = dict(self.state(0, 5000, t=1800.0), type="state", objectives=[])
        sent = [m for m in feed(commander, config, state) if m.get("id") == 1]
        self.assertEqual([m["cmd"] for m in sent], ["formation", "move"])
        self.assertEqual(sent[0]["value"], "RoadColumn")
        self.assertIn(1, commander.pending_moves)
        self.assertNotEqual((commander.last_cmds.get(1) or {}).get("cmd"), "formation")
        near = dict(self.state(200, 790, t=1830.0), type="state", objectives=[])  # the enemy is 590 away now
        sent = [m for m in feed(commander, config, near) if m.get("id") == 1]
        self.assertEqual([(m["cmd"], m.get("value")) for m in sent], [("formation", "Line")])
        self.assertIn(1, commander.pending_moves)                                 # the march goes on, in line


class RoadsInThePrompt(unittest.TestCase):
    def tmap(self, rows):
        import terrain as T
        rules = {"Infantry": {"Grass": "Speed 100%", "Road": "Speed 100%", "Forest": "Speed 66%"}}
        return T.TerrainMap({"minX": 0, "minZ": 0, "maxX": 100, "maxZ": 100, "step": 25.0, "terrain": rows,
                             "heights": ["0000"] * 4, "legend": {".": "Grass", "=": "Road", "f": "Forest"},
                             "rules": rules})

    def test_a_map_without_road_cells_says_nothing_about_roads(self):
        tmap = self.tmap(["..ff"] * 4)
        text = tmap.prompt_text()
        self.assertFalse(tmap.has("Road"))
        self.assertNotIn("Road", text)
        self.assertIn("- Forest: Speed 66%", text)
        system = prompting.build_system_prompt("South", 20, "notes", text, None, "rules", has_roads=False)
        self.assertNotIn("Roads (=)", system)
        self.assertNotIn("__", system)

    def test_a_map_with_road_cells_keeps_them(self):
        tmap = self.tmap(["..=f"] * 4)
        text = tmap.prompt_text()
        self.assertTrue(tmap.has("Road"))
        self.assertIn("= = Road", text)
        self.assertIn("- Road: Speed 100%", text)
        system = prompting.build_system_prompt("South", 20, "notes", text, None, "rules", has_roads=True)
        self.assertIn("Roads (=)", system)

    def test_the_formation_line_says_who_sets_the_formations(self):
        import march
        system = prompting.build_system_prompt("South", 20, "notes", formation_note=march.march_note())
        self.assertIn("Do not order formations", system)
        self.assertIn("600 from a known enemy", system)
        system = prompting.build_system_prompt("South", 20, "notes", formation_note=march.march_note({"enabled": False}))
        self.assertIn('"cmd": "formation"', system)
        self.assertIn('"cmd": "formation"', prompting.build_system_prompt("South", 20, "notes"))


SHILOH_GOALS = [
    {"result": "Victory",
     "or": [{"type": "CaptureObjectivePoint", "state": False, "message": "Hold Spain Field", "objective": "SpainField"},
            {"type": "KillRatio", "state": True, "message": "Inflict at least 20% more casualties than enemy",
             "ratio": 1.2, "condition": "MoreOrEquals"}],
     "and": [{"type": "CaptureObjectivePoint", "state": True, "message": "Hold Pittsburg Landing",
              "objective": "PitsLanding"}]},
    {"result": "Draw", "or": [{"type": "CaptureObjectivePoint", "state": True, "message": "Hold Pittsburg Landing",
                               "objective": "PitsLanding"}], "and": []},
    {"result": "Defeat", "or": [], "and": []},
]
LANDING = {"name": "Pittsburg Landing", "x": 1000, "z": 3900, "side": "North", "radius": 400, "captureRange": 400,
           "victoryPoints": 500}
SPAIN = {"name": "Spain Field", "x": 0, "z": 0, "side": "South", "radius": 400, "captureRange": 200,
         "victoryPoints": 500}


class Wip4Rules(unittest.TestCase):
    """0.1.4 WIP4, from the battle of 2026-11-11 15:27."""

    def outnumbered(self, time_s=1500.0):
        st = battle(3, 9, time_s)
        st["objectives"] = [dict(LANDING), dict(SPAIN)]
        st["phaseTime"] = time_s
        return st

    def test_the_plan_abandons_an_assault_it_cannot_win_and_names_the_draw(self):
        st = self.outnumbered()
        plain = goals.make_plan(SHILOH_GOALS, st, st["objectives"], 1.0, 30.0)
        self.assertNotEqual(plain["mode"], "ATTACK")           # 25 minutes of build-up no longer force the attack
        self.assertTrue(plain["need_cap"])
        self.assertLess(plain["overall"], plain["abandon_ratio"])
        res = goals.make_plan(SHILOH_GOALS, st, st["objectives"], 1.0, 30.0, cfg={"force_abandon": True})
        self.assertEqual(res["mode"], "DEFEND")
        self.assertEqual(res["targets"], [])
        self.assertIn("assault abandoned", res["posture"])
        self.assertIn("DRAW", res["posture"])
        self.assertEqual([o["name"] for o in res["hold"]], ["Spain Field"])

    def test_a_casualty_goal_raises_the_abandon_ratio(self):
        st = self.outnumbered()
        with_kd = goals.make_plan(SHILOH_GOALS, st, st["objectives"], 1.0, 5.0)
        without = goals.make_plan(GOALS, battle(3, 9), [OBJECTIVE], 1.0, 5.0)
        self.assertAlmostEqual(with_kd["abandon_ratio"], 0.6)
        self.assertAlmostEqual(without["abandon_ratio"], 0.6)   # GOALS has a kill ratio too (its draw condition)

    def test_the_server_latches_the_abandon_and_ignores_new_assaults(self):
        cmd = planner_server.Commander(dict(planner_server.load_config(os.path.join(SERVER, "config.json")),
                                            llm_plus=False))       # the plan exists in the full system only
        cmd.goals = SHILOH_GOALS
        early = self.outnumbered(600.0)
        with redirect_stdout(io.StringIO()):
            first = cmd.make_plan(early, early["objectives"])
            self.assertFalse(cmd.assault_abandoned)             # before minute 20: not yet
            late = self.outnumbered(1500.0)
            cmd.directives = [{"objective": "Pittsburg Landing", "launch": "now"}]
            res = cmd.make_plan(late, late["objectives"])
        self.assertIsNotNone(first)
        self.assertTrue(cmd.assault_abandoned)
        self.assertEqual(res["mode"], "DEFEND")
        self.assertEqual(cmd.directives, [])
        strong = battle(9, 9, 1800.0)
        strong["objectives"], strong["phaseTime"] = [dict(LANDING), dict(SPAIN)], 1800.0
        with redirect_stdout(io.StringIO()):
            cmd.make_plan(strong, strong["objectives"])
        self.assertFalse(cmd.assault_abandoned)                 # ratio 1.0 > 0.8: the question is open again

    def capture_state(self, x, z, enemy_at=None):
        units = [unit(1, "Cavalry", "South", x, z), unit(2, "Infantry", "South", 3000, 3000)]
        if enemy_at:
            units.append(unit(5001, "Infantry", "North", *enemy_at))
        else:
            units.append(unit(5001, "Infantry", "North", 5000, 5000))
        return {"type": "state", "time": 100.0, "playerSide": "North", "units": units,
                "objectives": [dict(SPAIN, side="North")]}

    def test_a_move_ending_just_outside_the_capture_range_is_put_onto_the_point(self):
        import discipline
        st = self.capture_state(900, 0)
        stats = {}
        out, _ = discipline.discipline_orders(st, [{"cmd": "move", "id": 1, "x": 217.0, "z": 0.0}], None, {}, {}, stats)
        self.assertLessEqual(math.hypot(out[0]["x"], out[0]["z"]), 0.5 * 200)
        self.assertNotIn("_capture", out[0])
        # a defended objective is an attack, not a walk: the move is left alone
        st = self.capture_state(900, 0, enemy_at=(100, 100))
        out, _ = discipline.discipline_orders(st, [{"cmd": "move", "id": 1, "x": 217.0, "z": 0.0}], None, {}, {}, {})
        self.assertEqual(out[0]["x"], 217.0)

    def test_a_capturing_unit_stays_and_an_idle_one_steps_in(self):
        import discipline
        st = self.capture_state(50, 0)                           # inside the range: it is capturing
        out, _ = discipline.discipline_orders(st, [{"cmd": "move", "id": 1, "x": -1600.0, "z": -480.0}], None, {}, {}, {})
        self.assertEqual([o for o in out if o["id"] == 1], [])   # the move away is dropped
        st = self.capture_state(217, 0)                          # 17 outside, no order: it steps in
        out, _ = discipline.discipline_orders(st, [], None, {}, {}, {})
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0]["auto"])
        self.assertLessEqual(math.hypot(out[0]["x"], out[0]["z"]), 0.5 * 200)
        status = discipline.capture_status(st)
        self.assertEqual(status["Spain Field"][0], "out")

    def test_a_running_march_is_not_reissued_for_a_small_change(self):
        import discipline
        st = battle(2, 2)
        pending = {1: (2000.0, 2000.0, 0.0)}
        near = [{"cmd": "move", "id": 1, "x": 2100.0, "z": 2050.0}]
        far = [{"cmd": "move", "id": 1, "x": 2400.0, "z": 2000.0}]
        self.assertEqual(discipline.discipline_orders(st, near, None, pending, {}, {})[0], [])
        self.assertEqual(len(discipline.discipline_orders(st, far, None, pending, {}, {})[0]), 1)
        self.assertEqual(len(discipline.discipline_orders(st, near, None, {}, {}, {})[0]), 1)

    def test_a_battery_that_does_not_move_gets_no_more_marches(self):
        import discipline
        mem = {}
        blocked = set()
        for k in range(4):
            st = battle(1, 1, 100.0 + 60.0 * k)
            st["units"].append(unit(50, "Artillery", "South", 1000, 1000, limber="ready"))
            out, blocked = discipline.discipline_orders(st, [{"cmd": "move", "id": 50, "x": 1000.0, "z": 2500.0}],
                                                        None, {}, mem, {})
            if blocked:
                break
        self.assertEqual(blocked, {50})
        self.assertEqual(out, [])
        # a short step (made by hand) is still sent
        out, _ = discipline.discipline_orders(st, [{"cmd": "move", "id": 50, "x": 1000.0, "z": 1100.0}], None, {}, mem, {})
        self.assertEqual(len(out), 1)

    def test_wagons_run_on_long_trips(self):
        import discipline
        st = battle(1, 1)
        st["units"].append(unit(60, "Supply", "South", 0, 0, supplyStock=1.0))
        mem = {}
        out, _ = discipline.discipline_orders(st, [{"cmd": "move", "id": 60, "x": 0.0, "z": 1500.0}], None, {}, mem, {})
        self.assertIn({"cmd": "gait", "id": 60, "value": "Run", "auto": True}, out)
        out, _ = discipline.discipline_orders(st, [{"cmd": "move", "id": 60, "x": 0.0, "z": 1600.0}], None, {}, mem, {})
        self.assertEqual([o["cmd"] for o in out], ["move"])       # not repeated at every move

    def test_a_dry_brigade_leaves_the_line_and_rests_until_rearmed(self):
        st = battle(2, 2)
        st["units"][0]["ammo"] = 0.0
        drop, added = relief.relief_orders(st, [{"cmd": "hold", "id": 1}], None, {}, {}, None, {}, {})
        self.assertIn(1, drop)
        self.assertEqual(added[0]["cmd"], "fallback")
        last = {1: {"cmd": "fallback", "id": 1, "relief": True}}
        self.assertTrue(relief.is_resting(dict(st["units"][0], morale=0.9, ammo=0.1), last))
        self.assertFalse(relief.is_resting(dict(st["units"][0], morale=0.9, ammo=0.6), last))

    def test_the_weapon_table_names_breech_loaders_and_repeaters(self):
        self.assertGreaterEqual(equipment.load_shoot_types(), 50)
        self.assertEqual(equipment.shoot_class("rifle_Spencer_RF"), ("repeater", 7))
        self.assertEqual(equipment.shoot_class("carbine_Smith50"), ("breech", 0))        # missed by the name words
        self.assertEqual(equipment.shoot_class("carbine_Colt1855Sabel"), ("revolver", 6))
        self.assertIsNone(equipment.shoot_class("rifle_Of_A_Mod_RF"))
        self.assertEqual(equipment.enemy_bore({"weapon": "rifle_Henry_RF", "kind": "Infantry"}), "repeater 15")
        self.assertEqual(equipment.enemy_bore({"weapon": "rifle_Enfield57_RF", "kind": "Infantry"}), "rifled")
        self.assertGreater(equipment.fire_weight({"weapon": "rifle_Spencer_RF"}), 1.5)
        self.assertEqual(equipment.fire_weight({"weapon": "rifle_Of_A_Mod_RF"}), 1.0)

    def test_garrison_advice_follows_the_ratio_and_the_plan(self):
        import situation
        self.assertIn("picket only", situation.garrison_advice(1.3, "ATTACK", True, True, False))
        self.assertIn("picket only", situation.garrison_advice(0.4, "DEFEND", True, True, False))
        self.assertIn("one steady brigade", situation.garrison_advice(0.9, "DEFEND", True, True, False))
        self.assertIn("line covers", situation.garrison_advice(0.9, "DEFEND", True, True, True))



class FakeWoods:
    """Forest for z < 0, grass elsewhere."""
    def fire_value(self, x, z, kind="Infantry"):
        return 1.2 if z < 0 else 0.5

    def best_fire_spot(self, ux, uz, tx, tz, rng, kind="Infantry", taken=(), max_move=None, **kw):
        if uz < 0 or (max_move is not None and uz > max_move):
            return None
        return (ux, -20.0, "Forest", 1.2)


class Wip6Woods(unittest.TestCase):
    def test_woods_mode_pulls_open_units_back_and_redirects_moves(self):
        st = battle(2, 1)
        st["units"][0].update(x=0.0, z=100.0)              # in the open, enemy in range
        st["units"][1].update(x=500.0, z=-300.0)           # already in the woods
        foe = [u for u in st["units"] if u["side"] == "North"][0]
        foe.update(x=0.0, z=350.0)
        st["objectives"] = []
        orders = [{"cmd": "move", "id": 2, "x": 100.0, "z": 120.0}]
        kept, new = terrain_rules.woods_orders(st, FakeWoods(), orders, cfg={}, stats={})
        self.assertEqual(kept[0]["z"], -20.0)               # the model's move into the open goes to the wood's edge
        self.assertEqual([(o["id"], o["z"]) for o in new], [(1, -20.0)])

    def test_the_last_brigade_on_a_held_objective_stays(self):
        st = battle(1, 1)
        st["units"][0].update(x=0.0, z=100.0)
        [u for u in st["units"] if u["side"] == "North"][0].update(x=0.0, z=350.0)
        st["objectives"] = [{"name": "Hill", "x": 0.0, "z": 120.0, "side": "South", "captureRange": 200}]
        _, new = terrain_rules.woods_orders(st, FakeWoods(), [], cfg={}, stats={})
        self.assertEqual(new, [])



MEETING_GOALS = [
    {"result": "Victory", "or": [], "and": [
        {"type": "CaptureObjectivePoint", "state": False, "message": "Hold Meeting point", "objective": "HanoverCourt"},
        {"type": "LossRatio", "state": True, "message": "Lose less than 40% of your army", "ratio": 0.6,
         "condition": "MoreOrEquals"}]},
    {"result": "Draw", "or": [], "and": [
        {"type": "LossRatio", "state": True, "message": "Lose less than 40% of your army", "ratio": 0.6,
         "condition": "MoreOrEquals"}]},
    {"result": "Defeat", "or": [], "and": []},
]
MEETING = {"name": "Meeting point", "x": 1300.0, "z": 3700.0, "side": "Neutral", "radius": 400, "captureRange": 200,
           "victoryPoints": 100}


class Wip7Rules(unittest.TestCase):
    """0.1.4 WIP7, from the battle of 2026-11-12 10:12."""

    def test_with_the_numbers_the_plan_takes_the_objective_the_player_needs(self):
        st = battle(9, 3, 600.0)
        st["objectives"] = [dict(MEETING)]
        res = goals.make_plan(MEETING_GOALS, st, st["objectives"], 1.0, 5.0, 600.0, 0.0)
        self.assertEqual(res["mode"], "ATTACK")
        self.assertTrue(res["secure"])
        self.assertEqual([o["name"] for o in res["targets"]], ["Meeting point"])
        even = battle(4, 4, 600.0)
        even["objectives"] = [dict(MEETING)]
        res = goals.make_plan(MEETING_GOALS, even, even["objectives"], 1.0, 5.0, 600.0, 0.0)
        self.assertNotEqual(res["mode"], "ATTACK")              # ratio 1.0: no
        res = goals.make_plan(MEETING_GOALS, battle(5, 4, 600.0) | {"objectives": [dict(MEETING)]},
                              [dict(MEETING)], 1.0, 5.0, 600.0, 0.0, cfg={"secure_latched": True})
        self.assertEqual(res["mode"], "ATTACK")                 # 1.25: kept once chosen

    def test_a_stop_loss_cannot_trip_again_during_its_cooldown(self):
        st = battle(6, 6, 1800.0)
        trend = (900.0, 100.0)
        tripped = goals.make_plan(GOALS, st, [OBJECTIVE], 0.5, 20.0, 900.0, 100.0, None, trend)
        self.assertTrue(tripped["stop_loss"])
        calm = goals.make_plan(GOALS, st, [OBJECTIVE], 0.5, 20.0, 900.0, 100.0, {"stop_loss_cooldown": True}, trend)
        self.assertFalse(calm["stop_loss"])

    def test_an_end_of_day_timer_is_not_a_deadline(self):
        st = battle(2, 2)
        st["briefing"] = {"timeLeftS": 680 * 60.0, "missionElapsedS": 40 * 60.0}
        self.assertIsNone(assault.phase_clock(st))
        st["briefing"] = {"timeLeftS": 50 * 60.0, "missionElapsedS": 40 * 60.0}
        self.assertAlmostEqual(assault.phase_clock(st)[0], 40 / 90)

    def test_the_assault_group_grows_to_one_and_a_half_times_the_defenders(self):
        mine = [unit(i, "Infantry", "South", 1000 + 100 * i, 3000, hp=1000) for i in range(1, 9)]
        foes = [unit(5001 + k, "Infantry", "North", 1300, 3700, hp=1000) for k in range(4)]
        cfg = dict(assault.DEFAULT_ASSAULT)
        need = 1.5 * assault.group_worth(foes)
        group = assault.select_group(mine, foes, dict(MEETING), cfg, {}, need=need)
        self.assertGreaterEqual(assault.group_worth(group), need)
        self.assertEqual(len(group), 6)
        small = assault.select_group(mine, foes, dict(MEETING), cfg, {})
        self.assertLess(len(small), 6)                           # the old share of the brigades
        mine[0]["offmap"] = True
        self.assertNotIn(1, [u["id"] for u in assault.select_group(mine, foes, dict(MEETING), cfg, {}, need=need)])

    def test_a_large_group_stages_in_two_wings(self):
        group = [unit(i, "Infantry", "South", 1000 + 150 * i, 3000) for i in range(1, 7)]
        spots = assault.stage_spots(group, dict(MEETING), dict(assault.DEFAULT_ASSAULT), {"fire": 400}, group, [])
        bearings = sorted(math.degrees(math.atan2(z - MEETING["z"], x - MEETING["x"])) for x, z in spots.values())
        self.assertGreater(bearings[-1] - bearings[0], 60.0)

    def test_units_off_the_field_get_no_orders_and_are_left_alone(self):
        import discipline
        st = battle(2, 1)
        st["units"][0].update(z=4990.0, ai=False)
        terrain = open_terrain()
        terrain.max_z = 4880.0
        self.assertEqual(discipline.mark_offmap(st, terrain), {1})
        out, _ = discipline.discipline_orders(st, [{"cmd": "move", "id": 1, "x": 1000.0, "z": 3000.0},
                                                   {"cmd": "hold", "id": 2}], None, {}, {}, {})
        # 0.1.4 WIP9: no "release" (it cancelled the game's entry march)
        self.assertEqual(sorted((o["cmd"], o["id"]) for o in out), [("hold", 2)])

    def test_a_brigade_under_enfilade_gets_its_flank_covered(self):
        import flank
        own = unit(1, "Infantry", "South", 1000, 3000, dx=0.0, dz=1.0)
        helper = unit(2, "Infantry", "South", 1700, 2800, dx=0.0, dz=1.0)
        front = unit(5001, "Infantry", "North", 1000, 3300)
        side = unit(5002, "Infantry", "North", 1300, 3000)
        st = {"type": "state", "time": 100.0, "playerSide": "North", "units": [own, helper, front, side]}
        drop, new = flank.flank_orders(st, [], None, {}, stats={})
        self.assertEqual(new, [{"cmd": "attack", "id": 2, "target": 5002, "auto": True}])
        alone = {"type": "state", "time": 100.0, "playerSide": "North",
                 "units": [dict(own, morale=0.6), front, side]}
        _, new = flank.flank_orders(alone, [], None, {}, stats={})
        self.assertEqual(new[0]["cmd"], "fallback")
        self.assertIn("#1 by #5002", flank.flank_lines(alone)[0])



class Wip8Withdrawal(unittest.TestCase):
    """0.1.4 WIP8, from the battle of 2026-11-12 13:24."""

    def front(self, morale=0.4, n_own=4, n_foe=8):
        st = battle(n_own, n_foe, 1800.0)
        for u in st["units"]:
            if u["side"] == "South":
                u.update(z=3600.0, morale=morale)
        return st

    def test_rally_point_is_out_of_reach_and_on_the_map(self):
        import withdraw
        st = self.front()
        terrain = open_terrain()
        x, z, ux, uz = withdraw.rally_point(st, terrain, dict(withdraw.DEFAULT_WITHDRAW))
        foes = [u for u in st["units"] if u["side"] == "North"]
        self.assertGreaterEqual(min(math.hypot(x - e["x"], z - e["z"]) for e in foes), 900.0 - 1.0)
        self.assertTrue(terrain.inside(x, z))
        self.assertLess(uz, 0.0)                                  # away from the enemy (north is +z here)

    def test_a_failing_outnumbered_line_withdraws_with_a_rearguard(self):
        import withdraw
        st = self.front(morale=0.4)
        st["units"].append(unit(90, "Skirmish", "South", 1100, 3550, morale=0.9))
        st["objectives"] = [dict(OBJECTIVE, side="South")]      # ours still: not a lost battle
        w = withdraw.Withdrawal()
        self.assertEqual(w.update_mode(st, {"overall": 0.5, "kd": 0.9, "mode": "DEFEND"}, {}), "WITHDRAW")
        ids, out = w.army_orders(st, open_terrain(), [], {})
        self.assertEqual(w.rearguard, [90])
        moves = [o for o in out if o["cmd"] == "move"]
        self.assertEqual(len(moves), 4)
        _, again = w.army_orders(st, open_terrain(), [], {})
        self.assertEqual([o for o in again if o["cmd"] == "move"], [])       # same rally: nothing re-sent
        st["time"] += 60.0
        self.assertEqual(w.update_mode(st, {"overall": 0.5, "kd": 0.9}, {}), "WITHDRAW")   # not over after 1 min

    def test_a_lost_battle_is_preserved(self):
        import withdraw
        st = self.front(morale=0.8)
        st["objectives"] = [dict(OBJECTIVE, side="North")]
        st["phaseTime"] = 1800.0
        w = withdraw.Withdrawal()
        plan = {"overall": 0.5, "kd": 0.8, "mode": "DEFEND", "abandoned": True}
        self.assertEqual(w.update_mode(st, plan, {}), "PRESERVE")
        self.assertIn("PRESERVE", w.lines()[0])
        self.assertEqual(w.update_mode(st, dict(plan, overall=1.1), {}), None)

    def test_a_resting_brigade_goes_out_of_reach(self):
        import withdraw
        st = battle(1, 1)
        st["units"][0].update(x=1000.0, z=3500.0, morale=0.4)
        [u for u in st["units"] if u["side"] == "North"][0].update(x=1000.0, z=3900.0)
        ids, out = withdraw.rest_orders(st, open_terrain(), [], {1}, None, {}, (), {})
        self.assertEqual(ids, {1})
        self.assertGreaterEqual(3900.0 - out[0]["z"], 700.0)

    def test_an_uncovered_battery_packs_up_and_pulls_back(self):
        import withdraw
        st = battle(0, 1)
        st["units"].append(unit(50, "Artillery", "South", 1000, 3500, limber="ready", range=1000))
        foe = [u for u in st["units"] if u["side"] == "North"][0]
        foe.update(x=1000.0, z=3850.0)
        ids, out = withdraw.battery_escape_orders(st, open_terrain(), [], None, {foe["id"]: (1000.0, 3950.0)})
        self.assertEqual([o["cmd"] for o in out], ["limber", "move"])
        self.assertLess(out[1]["z"], 3500.0)

    def test_fire_goes_to_the_enemy_closing_in_and_masked_batteries_move(self):
        import fire
        st = battle(2, 2)
        a, b = [u for u in st["units"] if u["side"] == "South"]
        e1, e2 = [u for u in st["units"] if u["side"] == "North"]
        a.update(x=1000.0, z=3500.0); b.update(x=1300.0, z=3500.0)
        e1.update(x=1000.0, z=3800.0); e2.update(x=1500.0, z=3800.0)
        prev = {e1["id"]: (1000.0, 3900.0), e2["id"]: (1500.0, 3800.0)}
        out = fire.fire_orders(st, open_terrain(), [], None, {}, prev, (), {})
        self.assertEqual({(o["id"], o["target"]) for o in out if o["cmd"] == "range_attack"},
                         {(1, e1["id"]), (2, e1["id"])})
        gun = unit(50, "Artillery", "South", 1000, 3200, range=1000)
        st2 = {"type": "state", "time": 100.0, "playerSide": "North", "units": [gun, dict(a), dict(e1)]}
        mem = {}
        out = fire.fire_orders(st2, open_terrain(), [], {"focus": False}, mem, {}, (), {})
        self.assertEqual(out, [])                             # WIP12: masked once, not moved yet
        out = fire.fire_orders(st2, open_terrain(), [], {"focus": False}, mem, {}, (), {})
        self.assertEqual(out[0]["cmd"], "move")
        self.assertIsNone(fire.masker(dict(gun, x=out[0]["x"], z=out[0]["z"]), e1, [a]))

    def test_routed_units_are_not_marked_off_the_field(self):
        import discipline
        st = battle(2, 1)
        st["units"][0].update(z=4990.0, status="shattered", ai=False)
        terrain = open_terrain()
        terrain.max_z = 4880.0
        self.assertEqual(discipline.mark_offmap(st, terrain), set())



class Wip9Rules(unittest.TestCase):
    """0.1.4 WIP9, from the battle of 2026-11-12 14:48."""

    def test_the_game_field_and_the_plugin_flag_decide_what_is_off_the_field(self):
        import discipline
        st = battle(3, 1)
        st["units"][0].update(x=5900.0)                 # inside the stage's field, beyond the old terrain scan
        st["units"][1].update(offField=True)            # the game's own test says outside
        st["field"] = [0.0, 0.0, 7000.0, 6000.0]
        terrain = open_terrain()
        terrain.max_x = 5000.0                          # stale scan of the first stage
        self.assertEqual(discipline.mark_offmap(st, terrain), {2})
        del st["field"]                                 # old plugin: the terrain scan decides
        self.assertEqual(discipline.mark_offmap(st, terrain), {1, 2})

    def test_units_off_the_field_do_not_count_in_the_force_ratio(self):
        from situation import strength
        units = [unit(1, "Infantry", "South", 0, 0), unit(2, "Infantry", "South", 0, 0, offmap=True)]
        self.assertAlmostEqual(strength(units), strength(units[:1]))

    def test_a_terrain_update_keeps_the_battle(self):
        cmd = planner_server.Commander(planner_server.load_config(os.path.join(SERVER, "config.json")))
        n = 60
        msg = {"type": "terrain", "minX": 0, "minZ": 0, "maxX": 6000, "maxZ": 6000, "step": 100,
               "terrain": ["." * n] * n, "heights": ["1" * n] * n, "legend": {".": "Grass"}, "objectives": [OBJECTIVE]}
        with redirect_stdout(io.StringIO()):
            cmd.note_terrain(msg, os.devnull)
            report = cmd.report
            cmd.assault_mem = {"kept": True}
            wide = dict(msg, update=True, maxX=9000, terrain=["." * 90] * n, heights=["1" * 90] * n)
            cmd.note_terrain(wide, os.devnull)
        self.assertIs(cmd.report, report)
        self.assertEqual(cmd.assault_mem, {"kept": True})
        self.assertEqual(cmd.terrain.max_x, 9000)

    def test_idle_wagons_wait_apart_behind_the_line(self):
        import supply
        line = [unit(i, "Infantry", "South", 1000 + 300 * i, 3500) for i in range(6)]
        foes = [unit(5001 + i, "Infantry", "North", 1000 + 300 * i, 3900) for i in range(6)]
        spots = supply.park_spots(line, foes, 3, dict(supply.DEFAULT_SUPPLY))
        for a in range(3):
            for b in range(a + 1, 3):
                self.assertGreaterEqual(math.hypot(spots[a][0] - spots[b][0], spots[a][1] - spots[b][1]), 390.0)
        self.assertTrue(all(z < 3500 for _, z in spots))   # behind the line

    def test_a_skirmish_screen_is_not_a_unit_lost(self):
        from report import BattleReport
        r = BattleReport()
        brigade = unit(1, "Infantry", "South", 0, 0, hp=1200)
        screen = unit(2, "Skirmish", "South", 0, 0, hp=60)
        foe = unit(5001, "Infantry", "North", 0, 900)
        r.update({"time": 0.0, "playerSide": "North", "units": [brigade, screen, foe]})
        r.update({"time": 60.0, "playerSide": "North", "units": [dict(brigade, hp=1260), foe]})  # back in its brigade
        self.assertEqual(r.units_lost(), 0)
        self.assertAlmostEqual(r.own_loss, 0.0)
        r.update({"time": 120.0, "playerSide": "North",
                  "units": [dict(brigade, hp=1260), dict(screen, id=3, status="shattered"), foe]})
        self.assertEqual((r.units_lost(), r.skirmishers_lost()), (0, 1))

    def test_a_held_objective_is_faced_one_for_one_with_one_target(self):
        import tactics
        obj = dict(OBJECTIVE, side="South")
        mine = [unit(i, "Infantry", "South", 3900 + 100 * i, 3900) for i in range(1, 5)]
        foes = [unit(5001, "Infantry", "North", 3800, 4600), unit(5002, "Infantry", "North", 4300, 4700)]
        st = {"type": "state", "time": 100.0, "playerSide": "North", "units": mine + foes, "objectives": [obj]}
        ids, new = tactics.hold_line_orders(st, open_terrain(), [], {"mode": "DEFEND"}, None, {})
        moves = [o for o in new if o["cmd"] == "move"]
        self.assertEqual(len(moves), 2)                                  # one brigade per enemy brigade
        self.assertEqual({(o["fx"], o["fz"]) for o in moves}, {(3800.0, 4600.0), (4300.0, 4700.0)})
        # in position and in range: both fire on the same enemy brigade
        mine2 = [unit(1, "Infantry", "South", 3950, 4200), unit(2, "Infantry", "South", 4150, 4200)]
        foes2 = [unit(5001, "Infantry", "North", 3950, 4500), unit(5002, "Infantry", "North", 4250, 4520, hp=700)]
        st2 = dict(st, units=mine2 + foes2)
        mem = {}
        _, first = tactics.hold_line_orders(st2, open_terrain(), [], {"mode": "DEFEND"}, {"hold_tolerance": 400}, mem)
        fire = [o for o in first if o["cmd"] == "range_attack"]
        self.assertEqual(len({o["target"] for o in fire}), 1)
        self.assertEqual(len(fire), 2)

    def test_an_isolated_enemy_brigade_is_hunted(self):
        import tactics
        mine = [unit(1, "Infantry", "South", 1000, 1000), unit(2, "Infantry", "South", 1200, 1000)]
        lone = unit(5001, "Infantry", "North", 1100, 1500, hp=900)
        far = unit(5002, "Infantry", "North", 3000, 3000)
        st = {"type": "state", "time": 100.0, "playerSide": "North", "units": mine + [lone, far]}
        ids, new = tactics.hunt_orders(st, [], {"mode": "ATTACK"}, None, {})
        self.assertEqual({(o["id"], o["target"]) for o in new}, {(1, 5001), (2, 5001)})
        friend = unit(5003, "Infantry", "North", 1300, 1700)          # not alone any more
        st["units"].append(friend)
        self.assertEqual(tactics.hunt_orders(st, [], {"mode": "ATTACK"}, None, {})[1], [])

    def test_a_routing_enemy_is_charged_again(self):
        import tactics
        cav = unit(1, "Cavalry", "South", 1000, 1000)
        inf = unit(2, "Infantry", "South", 1050, 1000)
        beaten = unit(5001, "Infantry", "North", 1000, 1250, morale=0.2, status="routing")
        st = {"type": "state", "time": 100.0, "playerSide": "North", "units": [cav, inf, beaten]}
        _, new = tactics.pursuit_orders(st, [], {"mode": "ATTACK"}, None, {})
        self.assertEqual(new, [{"cmd": "charge", "id": 1, "target": 5001, "auto": True}])
        st["units"].append(unit(5002, "Infantry", "North", 1100, 1350))   # a steady enemy covers it
        self.assertEqual(tactics.pursuit_orders(st, [], {"mode": "ATTACK"}, None, {})[1], [])

    def test_fresh_arrivals_are_pointed_at_the_end_of_the_enemy_line(self):
        import tactics
        mem = {}
        army = [unit(i, "Infantry", "South", 1000 + 200 * i, 1000) for i in range(1, 4)]
        foes = [unit(5000 + i, "Infantry", "North", 1000 + 200 * i, 1600) for i in range(1, 6)]
        tactics.note_field({"time": 0.0, "playerSide": "North", "units": army + foes}, mem)
        late = unit(9, "Infantry", "South", 2600, 1100)
        st = {"time": 300.0, "playerSide": "North", "units": army + [late] + foes}
        tactics.note_field(st, mem)
        lines = tactics.arrivals_lines(st, mem)
        self.assertEqual(len(lines), 1)
        self.assertIn("#9", lines[0])
        self.assertIn("#5005", lines[0])                                # the eastern end, nearest the arrival


class Wip10Rules(unittest.TestCase):
    """0.1.4 WIP10, from the battle of 2026-11-13 (Malvern Hill)."""

    def test_staging_spots_stay_out_of_the_enemys_reach(self):
        import assault
        obj = dict(MEETING)
        group = [unit(i, "Infantry", "South", 1000 + 150 * i, 2600) for i in range(1, 5)]
        # the defenders stand in front of the objective, towards us
        foes = [unit(5000 + i, "Infantry", "North", 1100 + 200 * i, 3250) for i in range(3)]
        spots = assault.stage_spots(group, obj, dict(assault.DEFAULT_ASSAULT), {"fire": 400}, group, foes,
                                    open_terrain())
        for x, z in spots.values():
            self.assertGreaterEqual(min(math.hypot(x - e["x"], z - e["z"]) for e in foes), 589.0)

    def test_brigades_sent_together_to_a_flank_are_not_alone(self):
        import cohesion
        units = [unit(1, "Infantry", "South", 0, 0), unit(2, "Infantry", "South", 100, 0),
                 unit(3, "Infantry", "South", 200, 0)]
        state = {"playerSide": "North", "units": units}
        two = [{"cmd": "move", "id": 2, "x": 100.0, "z": 3000.0}, {"cmd": "move", "id": 3, "x": 300.0, "z": 3000.0}]
        drop, _ = cohesion.cohesion_orders(state, two, [{"x": 0.0, "z": 300.0}])
        self.assertEqual(drop, set())
        drop, _ = cohesion.cohesion_orders(state, two[:1], [{"x": 0.0, "z": 300.0}])
        self.assertEqual(drop, {2})

    def test_no_cover_search_for_batteries_on_the_rally_line(self):
        import terrain as terrain_mod
        import withdraw
        n = 60
        rows = ["." * n for _ in range(n)]
        rows[35] = "." * 10 + "F" * 5 + "." * 45            # woods just beside the line
        t = terrain_mod.TerrainMap({"minX": 0, "minZ": 0, "maxX": 6000, "maxZ": 6000, "step": 100,
                                    "terrain": rows, "heights": ["1" * n] * n,
                                    "legend": {".": "Grass", "F": "Forest"}, "objectives": []})
        units = [unit(1, "Artillery", "South", 1250, 3450), unit(2, "Infantry", "South", 1250, 3450)]
        cfg = dict(withdraw.DEFAULT_WITHDRAW)
        gun = withdraw.line_spots(units[:1], 1250, 3450, 0.0, -1.0, cfg, t)[1]
        inf = withdraw.line_spots(units[1:], 1250, 3450, 0.0, -1.0, cfg, t)[2]
        self.assertEqual(t.name_at(*gun), "Grass")
        self.assertEqual(t.name_at(*inf), "Forest")

    def test_the_withdrawal_stands_on_its_line_and_falls_back_when_pressed(self):
        import withdraw
        st = battle(4, 4, 1800.0)
        for u in st["units"]:
            if u["side"] == "South":
                u.update(z=3600.0, morale=0.8)
        st["objectives"] = [dict(OBJECTIVE, side="North")]
        st["phaseTime"] = 1800.0
        w = withdraw.Withdrawal()
        plan = {"overall": 0.5, "kd": 0.8, "mode": "DEFEND", "abandoned": True}
        self.assertEqual(w.update_mode(st, plan, {}), "PRESERVE")
        stats = {}
        _, out = w.army_orders(st, open_terrain(), [], stats)
        spots = {o["id"]: (o["x"], o["z"]) for o in out if o["cmd"] == "move"}
        first = w.rally
        for u in st["units"]:
            if u["id"] in spots:
                u["x"], u["z"] = spots[u["id"]]            # the line arrives
        st["time"] += 120.0
        w.army_orders(st, open_terrain(), [], stats)
        self.assertTrue(w.standing())
        st["time"] += 30.0
        _, out = w.army_orders(st, open_terrain(), [], stats)
        self.assertIs(w.rally, first)                      # it holds the line while not pressed
        self.assertEqual([o for o in out if o["cmd"] == "move"], [])
        # the enemy comes on, close, in strength: next bound
        line = [u for u in st["units"] if u["id"] in w.line_ids]
        for k, e in enumerate(u for u in st["units"] if u["side"] == "North"):
            e["x"], e["z"] = line[k % len(line)]["x"], line[k % len(line)]["z"] + 150.0
        st["time"] += 90.0
        w.army_orders(st, open_terrain(), [], stats)
        self.assertIsNot(w.rally, first)
        self.assertFalse(w.standing())

    def test_a_screen_falls_back_from_cavalry_and_from_a_charge(self):
        import skirmish
        owner = unit(1, "Infantry", "South", 1000, 1000)
        screen = unit(31, "Skirmish", "South", 1000, 1300, owner=1)
        cav = unit(5001, "Cavalry", "North", 1000, 1700)
        st = {"time": 100.0, "playerSide": "North", "units": [owner, screen, cav]}
        ids, out = skirmish.skirmish_orders(st, open_terrain(), [], {}, {"t": 70.0}, {})
        move = [o for o in out if o["cmd"] == "move"][0]
        self.assertEqual(move["id"], 31)
        self.assertLess(move["z"], 1300.0)                 # back towards its brigade
        # an infantry unit closing in fast (a charge)
        inf = unit(5002, "Infantry", "North", 1000, 1550)
        st = {"time": 100.0, "playerSide": "North", "units": [owner, screen, inf]}
        ids, out = skirmish.skirmish_orders(st, open_terrain(), [], {}, {"t": 70.0}, {5002: (1000.0, 1700.0)})
        self.assertIn(31, ids)
        ids, out = skirmish.skirmish_orders(st, open_terrain(), [], {}, {"t": 70.0}, {5002: (1000.0, 1560.0)})
        self.assertNotIn(31, ids)                          # walking: no panic

    def test_screens_are_detached_for_flank_marches_and_the_rearguard(self):
        import skirmish
        a = unit(1, "Infantry", "South", 1000, 1000, canScout=True)
        b = unit(2, "Infantry", "South", 1150, 1000, canScout=True)
        c = unit(3, "Infantry", "South", 3000, 1000, canScout=True)
        foe = unit(5001, "Infantry", "North", 3000, 4000)
        st = {"time": 100.0, "playerSide": "North", "units": [a, b, c, foe]}
        orders = [{"cmd": "move", "id": 1, "x": 1000.0, "z": 2500.0}, {"cmd": "move", "id": 2, "x": 1200.0, "z": 2500.0}]
        _, out = skirmish.skirmish_orders(st, open_terrain(), orders, {}, {}, {}, rearguard=[3])
        det = sorted(o["id"] for o in out if o["cmd"] == "detach")
        self.assertEqual(len(det), 2)
        self.assertIn(3, det)                              # the rearguard brigade
        self.assertEqual(len(set(det) & {1, 2}), 1)        # one screen leads the flank group

    def test_the_model_may_detach_and_recall(self):
        st = battle(2, 1)
        st["units"][0]["canScout"] = True
        st["units"].append(unit(31, "Skirmish", "South", 900, 3500, owner=1))
        import prompting
        out = prompting.sanitize([{"cmd": "detach", "id": 1}, {"cmd": "detach", "id": 2},
                                  {"cmd": "recall", "id": 31}], st, 10)
        self.assertEqual(sorted((o["cmd"], o["id"]) for o in out), [("detach", 1), ("recall", 31)])


class Wip12FreshCharges(unittest.TestCase):
    """Thoroughfare Gap, 2026-11-13 15:48: the model's charges by fresh brigades through forest were all turned
    into attacks, the plan defended at 5.8 to 1, batteries marched 32 times."""
    def test_fresh_brigade_keeps_its_charge_through_woods(self):
        import terrain_rules
        t = TerrainRuleTests.terrain(self)
        state = {"time": 600.0, "playerSide": "North", "units": [
            unit(1, "Infantry", "South", 250, 200), unit(50, "Infantry", "North", 650, 200, morale=0.4)]}
        out = terrain_rules.filter_orders([{"cmd": "charge", "id": 1, "target": 50}], state, t, {"charge": 500})
        self.assertEqual(out[0]["cmd"], "charge")                 # fresh, 400 away through dense forest
        state["units"][0].update(fatigue=0.7)
        out = terrain_rules.filter_orders([{"cmd": "charge", "id": 1, "target": 50}], state, t, {"charge": 500})
        self.assertEqual(out[0]["cmd"], "attack")                 # tired: the old rule

    def test_plan_attacks_with_the_numbers_even_when_every_condition_is_met(self):
        import goals
        g = [{"result": "Victory", "or": [], "and": [
                 {"type": "CaptureObjectivePoint", "state": True, "message": "Hold Logan Cross", "hidden": False,
                  "objective": "LoganCross"},
                 {"type": "KillRatio", "state": False, "message": "Inflict at least 5% more casualties than enemy",
                  "hidden": False, "ratio": 1.05, "condition": "MoreOrEquals"}]},
             {"result": "Draw", "or": [], "and": [
                 {"type": "KillRatio", "state": False, "message": "Inflict at least 10% more casualties than enemy",
                  "hidden": False, "ratio": 1.1, "condition": "MoreOrEquals"}]},
             {"result": "Defeat", "or": [], "and": []}]
        strong = battle(6, 2)
        plan = goals.make_plan(g, strong, [OBJECTIVE], 1.0, 10)
        self.assertEqual(plan["mode"], "ATTACK")
        self.assertTrue(plan["secure"])
        even = battle(3, 2)
        self.assertEqual(goals.make_plan(g, even, [OBJECTIVE], 1.0, 10)["mode"], "DEFEND")

    def test_firing_guarded_battery_stays(self):
        import battery
        line = soldier(1, "South", 0, 1600, width=150.0)
        gun = soldier(5, "South", 100, 1550, kind="Artillery", range=1100.0, limber="ready",
                      weapon="gun_10pdr_Parrott", width=216.0)
        foe = soldier(9, "North", 0, 2000)
        state = {"playerSide": "North", "time": 3000.0, "units": [line, gun, foe]}
        stats = {}
        self.assertEqual(battery.battery_orders(state, [], None, None, {}, {}, stats), [])
        self.assertIn("batteries left in place (firing, guarded)", stats)

    def test_fresh_tag_in_charge_opportunities(self):
        from prompting import charge_opportunities
        me = unit(1, "Infantry", "South", 0, 0, chargeRange=500)
        foe = unit(9, "Infantry", "North", 0, 300, morale=0.65)
        lines = charge_opportunities([me], [foe], {"charge": 500})
        self.assertTrue(any("FRESH" in l and "#9" in l for l in lines), lines)


class Wip13LlmOnly(unittest.TestCase):
    """2026-11-14: Marc wants to test the model alone, without the server's staff work."""
    def setUp(self):
        self.cwd = os.getcwd()
        os.chdir(SERVER)

    def tearDown(self):
        os.chdir(self.cwd)

    def _run(self, llm_only):
        config = planner_server.load_config("config.json")
        config["backend"] = "placeholder"
        config["llm_only"] = llm_only
        commander = planner_server.Commander(config)
        seen = {}

        class Stub:
            supports_schema = False
            last_info = {}

            def complete(self, system, user, **kw):
                seen["system"], seen["user"] = system, user
                return json.dumps({"reasoning": "Hold.", "orders": [{"cmd": "hold", "id": 1}]})

        commander.backend = Stub()
        state = battle(5, 5)
        commander.goals = GOALS
        with redirect_stdout(io.StringIO()):
            commander.track(state)
            orders = commander.plan(state, os.devnull)
        return commander, orders, seen

    def test_only_the_model_orders_reach_the_game(self):
        commander, orders, seen = self._run(True)
        self.assertEqual([(o["cmd"], o["id"]) for o in orders], [("hold", 1)])
        self.assertIn("MODEL-ONLY MODE", seen["system"])
        self.assertNotIn("STRATEGIC PLAN", seen["user"])
        self.assertIsNone(commander.plan_info)
        self.assertFalse(commander.reflex_command(False)["enabled"])

    def test_full_system_unchanged(self):
        commander, orders, seen = self._run(False)
        self.assertNotIn("MODEL-ONLY MODE", seen["system"])
        self.assertTrue(commander.reflex_command(False)["enabled"])


def map_with(rows, heights, legend):
    import terrain
    return terrain.TerrainMap({"minX": 0, "minZ": 0, "maxX": 100 * len(rows[0]), "maxZ": 100 * len(rows),
                               "step": 100, "terrain": rows, "heights": heights, "legend": legend,
                               "objectives": []})


class Wip13StaffWork(unittest.TestCase):
    """Crampton's Gap and Second Manassas (2026-11-13/14): counter-battery, holding cover, rallying on high
    ground, a line lengthened to an isolated brigade, paired charges of veterans."""
    def test_rifled_battery_fires_at_an_enemy_battery(self):
        import fire
        gun = soldier(1, "South", 1000, 1000, kind="Artillery", range=1250.0, weapon="gun_10pdr_Parrott_Rifle_RF",
                      limber="ready")
        enemy_gun = soldier(9, "North", 1000, 1900, kind="Artillery", range=1100.0, weapon="gun_12pdr_Napoleon")
        foot = soldier(8, "North", 1000, 2300)
        state = {"playerSide": "North", "time": 600.0, "units": [gun, enemy_gun, foot]}
        out = fire.fire_orders(state, None, [], {"focus": False}, {}, {}, (), {})
        self.assertEqual(out, [{"cmd": "range_attack", "id": 1, "target": 9, "auto": True}])
        foot["z"] = 1300.0                                 # infantry 300 from the guns: canister work, not this
        self.assertEqual(fire.fire_orders(state, None, [], {"focus": False}, {}, {}, (), {}), [])
        # WIP17: smoothbores duel too, unless foot or horse is within 400 (rifled: 350)
        smooth = dict(gun, weapon="gun_12pdr_Napoleon"); foot["z"] = 2300.0
        state["units"] = [smooth, enemy_gun, foot]
        self.assertEqual(fire.fire_orders(state, None, [], {"focus": False}, {}, {}, (), {}),
                         [{"cmd": "range_attack", "id": 1, "target": 9, "auto": True}])
        foot["z"] = 1380.0
        self.assertEqual(fire.fire_orders(state, None, [], {"focus": False}, {}, {}, (), {}), [])
        state["units"] = [gun, enemy_gun, foot]
        self.assertEqual(len(fire.fire_orders(state, None, [], {"focus": False}, {}, {}, (), {})), 1)

    def test_brigade_in_woods_holds_to_0_3_on_defend(self):
        import relief
        t = map_with(["FFFFF"] * 5, ["11111"] * 5, {"F": "Forest"})
        u = soldier(1, "South", 250, 150, morale=0.45)
        state = {"playerSide": "North", "time": 600.0, "units": [u, soldier(9, "North", 250, 450)]}
        drop, new = relief.relief_orders(state, [], {"replace": False}, {}, {}, t, {}, plan_mode="DEFEND")
        self.assertEqual(new, [])
        drop, new = relief.relief_orders(state, [], {"replace": False}, {}, {}, t, {}, plan_mode="ATTACK")
        self.assertEqual(new[0]["cmd"], "fallback")
        u["morale"] = 0.25
        drop, new = relief.relief_orders(state, [], {"replace": False}, {}, {}, t, {}, plan_mode="DEFEND")
        self.assertEqual(new[0]["cmd"], "fallback")

    def test_broken_brigade_rallies_on_high_ground(self):
        import relief
        # the enemy is north (high z); the hill is south-east of the brigade
        heights = ["11199", "11199", "11199", "11199", "11111", "11111", "11111", "11111", "11111", "11111"]
        t = map_with(["....."] * 10, heights, {".": "Grass"})
        u = soldier(1, "South", 250, 650, morale=0.2)
        state = {"playerSide": "North", "time": 600.0, "units": [u, soldier(9, "North", 250, 1000 + 400)]}
        t2 = map_with(["....."] * 20, heights + ["11111"] * 10, {".": "Grass"})
        drop, new = relief.relief_orders(state, [], {"replace": False}, {}, {}, t2, {}, plan_mode="DEFEND")
        self.assertEqual(len(new), 1)
        o = new[0]
        self.assertTrue(o.get("rally"))
        self.assertLess(o["z"], 650)                       # away from the enemy
        self.assertEqual(t2.height_at(o["x"], o["z"]), 9)  # on the hill
        self.assertTrue(relief.is_resting(u, {1: o}))

    def test_isolated_brigade_in_works_is_joined_not_recalled(self):
        import cohesion
        rows = ["#" + "." * 29] * 30
        t = map_with(rows, ["1" * 30] * 30, {"#": "Fortifications", ".": "Grass"})
        lone = soldier(1, "South", 50, 1500)
        line = [soldier(k, "South", 900 + 150 * k, 1500) for k in range(2, 6)]
        foe = soldier(9, "North", 50, 2600)
        state = {"playerSide": "North", "time": 600.0, "units": [lone] + line + [foe]}
        drop, out = cohesion.cohesion_orders(state, [], [], plan_mode="DEFEND", terrain=t, mem={})
        self.assertNotIn(1, {o["id"] for o in out})        # it stays in the works
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["id"], 2)                  # the nearest line brigade goes to stand beside it
        self.assertLess(abs(out[0]["x"] - 50 - 170), 1)
        drop, out = cohesion.cohesion_orders(state, [], [], plan_mode="ATTACK", terrain=t, mem={})
        self.assertEqual([o["id"] for o in out], [1])      # the old recall on an attack plan

    def test_two_fresh_veterans_charge_a_steady_brigade_together(self):
        import autopilot
        a = soldier(1, "South", 100, 100, stars=2)
        b = soldier(2, "South", 600, 300, stars=2)
        e = soldier(9, "North", 300, 300, morale=0.9)
        state = {"playerSide": "North", "time": 1200.0, "units": [a, b, e]}
        out = autopilot.engage_orders(state, [], {"fire": 400, "charge": 500}, {})
        self.assertFalse(any(o["cmd"] == "charge" for o in out))   # WIP15: steady zone: prepare by fire first
        e["morale"] = 0.55                                 # worn down by fire: the zone verdict is GO
        out = autopilot.engage_orders(state, [], {"fire": 400, "charge": 500}, {})
        self.assertEqual(sorted((o["cmd"], o["id"], o["target"]) for o in out if o["cmd"] == "charge"),
                         [("charge", 1, 9), ("charge", 2, 9)])
        pair = "paired charges (two fresh veteran brigades on one enemy brigade)"
        b["stars"] = 1
        st = {}
        autopilot.engage_orders(state, [], {"fire": 400, "charge": 500}, {}, stats=st)
        self.assertNotIn(pair, st)
        b["stars"] = 2
        e["hp"] = 2500.0                                   # 3000 men against 2500: under 1.3 to 1
        st = {}
        autopilot.engage_orders(state, [], {"fire": 400, "charge": 500}, {}, stats=st)
        self.assertNotIn(pair, st)


class Wip14ExchangeAndFlanks(unittest.TestCase):
    """South Mountain (2026-11-14): reserves fed into a losing open sector facing woods; flank attacks unanswered."""
    def _map(self):
        # grass everywhere except a forest strip at x 0-600 (the AI side, west) and one at x 1400-2000 (enemy, east)
        rows = ["FFFFFF........FFFFFF"] * 20
        return map_with(rows, ["1" * 20] * 20, {".": "Grass", "F": "Forest"})

    def _losing_tracker(self, x, z):
        import exchange
        tr = exchange.ExchangeTracker()
        u = soldier(1, "South", x, z)
        foe = soldier(9, "North", x + 400, z)
        tr.update({"playerSide": "North", "time": 0.0, "units": [u, foe]})
        u["hp"] -= 600.0
        foe["hp"] -= 100.0
        tr.update({"playerSide": "North", "time": 60.0, "units": [u, foe]})
        return tr, u, foe

    def test_losing_open_sector_with_cover_behind_is_a_trap(self):
        import exchange
        t = self._map()
        tr, u, foe = self._losing_tracker(900, 1000)
        self.assertTrue(tr.losing(900, 1000))
        self.assertTrue(exchange.is_trap(tr, t, 900, 1000, foe))
        self.assertFalse(exchange.is_trap(tr, t, 900, 1900, foe))          # another sector
        ids, out = exchange.pull_orders({"playerSide": "North", "time": 60.0, "units": [u, foe]}, t, [], tr)
        self.assertEqual(len(out), 1)
        self.assertLess(out[0]["x"], 600)                                  # back into the forest
        self.assertEqual(t.name_at(out[0]["x"], out[0]["z"]), "Forest")

    def test_no_replacement_into_a_trap(self):
        import exchange, relief
        t = self._map()
        tr, u, foe = self._losing_tracker(900, 1000)
        u["morale"] = 0.4
        fresh = soldier(2, "South", 300, 1300)
        state = {"playerSide": "North", "time": 60.0, "units": [u, fresh, foe]}
        trap = lambda x, z, e: exchange.is_trap(tr, t, x, z, e)
        drop, new = relief.relief_orders(state, [], {}, {}, {}, t, {}, plan_mode="DEFEND", trap=trap)
        self.assertFalse(any(o["id"] == 2 for o in new))
        drop, new = relief.relief_orders(state, [], {}, {}, {}, t, {}, plan_mode="DEFEND")
        self.assertTrue(any(o["id"] == 2 for o in new))                   # the old behaviour without the tracker

    def test_exchange_lines_compare_both_grounds(self):
        import exchange
        t = self._map()
        tr, u, foe = self._losing_tracker(900, 1000)
        foe["x"] = 1300.0
        enemy_in_woods = soldier(8, "North", 1450, 1000)
        u["x"] = 1000.0
        lines = exchange.exchange_lines({"playerSide": "North", "time": 60.0, "units": [u, enemy_in_woods]}, t, tr)
        text = "\n".join(lines)
        self.assertIn("EXCHANGE BY GROUND", text)
        self.assertIn("on grass (1.00) vs #8 on forest (0.49)", text)
        self.assertIn("LOSING SECTORS", text)

    def test_flank_threat_and_refusal(self):
        import exchange
        line = [soldier(k, "South", 1000, 400 + 200 * k) for k in range(1, 5)]       # z 600..1200, facing east
        reserve = soldier(5, "South", 300, 1000)
        gun = soldier(6, "South", 700, 2300, kind="Artillery")
        front = [soldier(20 + k, "North", 1600, 400 + 200 * k) for k in range(1, 5)]
        round_end = soldier(30, "North", 1200, 1800)                                  # 600 beyond the north end
        state = {"playerSide": "North", "time": 900.0, "units": line + [reserve, gun] + front + [round_end]}
        threats = exchange.flank_threats(state)
        kinds = sorted(t["kind"] for t in threats)
        self.assertIn("end", kinds)
        self.assertIn("battery", kinds)
        self.assertTrue(any("beyond the end of your line" in l for l in exchange.threat_lines(state, threats)))
        ids, out = exchange.refuse_flank_orders(state, None, [], threats, {})
        moved = {o["id"]: o for o in out}
        self.assertIn(5, moved)                                                       # the free brigade refuses it
        self.assertIn(6, moved)                                                       # the lone battery falls back
        self.assertLess(abs(moved[6]["z"] - 1200), 300)


class Wip15ChargeZoneSectorsAndLlmPlus(unittest.TestCase):
    """Crampton's Gap, model alone (2026-11-14 18:15): a charge on a shaken brigade among 6,500 steady men; a flank
    outnumbered 5 to 1 while brigades waited on the other; the model alone did better than the full staff."""
    def test_zone_verdicts(self):
        from prompting import charge_zone
        target = soldier(9, "North", 0, 300, morale=0.25)
        mine = [soldier(1, "South", 0, 0), soldier(2, "South", 200, 0)]
        self.assertEqual(charge_zone(target, mine, [target])["verdict"], "GO")
        steady = [soldier(10 + k, "North", 150 * k - 150, 450, morale=0.95) for k in range(3)]
        z = charge_zone(target, mine, [target] + steady)
        self.assertEqual(z["verdict"], "TOO FEW")           # 3,000 against 6,000 in the zone
        one = steady[:1]                                   # 3,000 against 3,000, zone morale 0.6: fire first
        self.assertEqual(charge_zone(target, mine, [target] + one)["verdict"], "PREPARE")
        reserve = soldier(20, "North", 0, 1100, morale=0.95)                # 800 behind, nobody near it
        self.assertEqual(charge_zone(target, mine, [target, reserve])["verdict"], "RECONSIDER")

    def test_charge_lines_carry_the_count(self):
        from prompting import charge_opportunities
        target = soldier(9, "North", 0, 300, morale=0.25)
        steady = [soldier(10 + k, "North", 150 * k - 150, 450, morale=0.95) for k in range(3)]
        lines = charge_opportunities([soldier(1, "South", 0, 0)], [target] + steady, {"charge": 500})
        self.assertIn("zone 600: yours 1500 vs 6000 men", lines[0])
        self.assertTrue(lines[0].endswith("TOO FEW"))

    def test_force_by_sector(self):
        import exchange
        line = [soldier(k, "South", 0, 300 * k) for k in range(1, 7)]       # z 300..1800, facing east
        foes = [soldier(20 + k, "North", 600, 300 + 100 * k) for k in range(5)]   # all on the low end
        foes.append(soldier(30, "North", 600, 1700))
        text = "\n".join(exchange.force_lines({"playerSide": "North", "time": 0.0, "units": line + foes}))
        self.assertIn("OUTNUMBERED", text)
        self.assertIn("Shift a brigade from the", text)

    def _run(self, mode):
        config = planner_server.load_config(os.path.join(SERVER, "config.json"))
        config["backend"] = "placeholder"
        config["llm_only"], config["llm_plus"] = mode == "llm_only", mode == "llm_plus"
        commander = planner_server.Commander(config)
        seen = {}

        class Stub:
            supports_schema = False
            last_info = {}

            def complete(self, system, user, **kw):
                seen["system"], seen["user"] = system, user
                return json.dumps({"reasoning": "Hold.", "orders": [{"cmd": "hold", "id": 1}]})

        commander.backend = Stub()
        state = battle(5, 5)
        commander.goals = GOALS
        cwd = os.getcwd()
        os.chdir(SERVER)
        try:
            with redirect_stdout(io.StringIO()):
                commander.track(state)
                orders = commander.plan(state, os.devnull)
        finally:
            os.chdir(cwd)
        return commander, orders, seen

    def test_llm_plus_mode(self):
        self.assertEqual(planner_server.command_mode({"llm_plus": True}), "llm_plus")
        self.assertEqual(planner_server.command_mode({"llm_plus": True, "llm_only": True}), "llm_only")
        self.assertEqual(planner_server.command_mode({}), "full")
        commander, orders, seen = self._run("llm_plus")
        self.assertIn("MODEL-PLUS MODE", seen["system"])
        self.assertIsNone(commander.plan_info)
        self.assertIn(("hold", 1), [(o["cmd"], o["id"]) for o in orders])
        self.assertTrue(all(o.get("auto") for o in orders if (o["cmd"], o["id"]) != ("hold", 1)))
        r = commander.reflex_command(False)
        self.assertTrue(r["enabled"])
        self.assertFalse(r["unseen"])
        self.assertEqual(planner_server.load_config(os.path.join(SERVER, "config.json"))["llm_plus"], True)


class Wip16AssaultColumn(unittest.TestCase):
    """Thoroughfare Gap (2026-11-15, llm_plus): 1.5 to 1 at 36-47 min, never more than 4 brigades near the Gap;
    the game's AI closed in from 4-6 directions. Marc's assault column, with envelopment and reinforcements."""
    def _army(self):
        o = {"name": "Gap", "x": 0.0, "z": 0.0, "side": "North"}
        mine = [soldier(k, "South", -2500 + 200 * (k % 5), -300 + 200 * (k // 5)) for k in range(1, 11)]
        mine += [soldier(20, "South", -2600, 0, kind="Skirmish"), soldier(21, "South", -2700, 0, kind="Cavalry"),
                 soldier(22, "South", -2800, 0, kind="Artillery")]
        foes = [soldier(50 + k, "North", 100 * k - 100, 100, morale=0.9) for k in range(3)]
        return {"playerSide": "North", "time": 2000.0, "objectives": [o], "units": mine + foes}

    def _walk(self, state, orders, step=70.0):
        by = {u["id"]: u for u in state["units"]}
        for o in orders:
            if o["cmd"] == "move" and o["id"] in by:
                u = by[o["id"]]
                dx, dz = o["x"] - u["x"], o["z"] - u["z"]
                n = math.hypot(dx, dz)
                u["_dest"] = (o["x"], o["z"]) if n > 0 else None
        for u in state["units"]:
            d = u.get("_dest")
            if d:
                dx, dz = d[0] - u["x"], d[1] - u["z"]
                n = math.hypot(dx, dz)
                f = min(1.0, (step * (0.5 if u["id"] % 3 == 0 else 1.0)) / n) if n else 1.0   # some are slower
                u["x"] += dx * f
                u["z"] += dz * f
        state["time"] += 20.0

    def test_parse_and_offer(self):
        import column
        d = column.parse_directive({"assault_column": {"objective": "Gap", "from": [[-2000, 0], [0, -2000]]}})
        self.assertEqual(d["from"], [[-2000.0, 0.0], [0.0, -2000.0]])
        self.assertEqual(column.parse_directive({"assault_column": {"cancel": True}}), {"cancel": True})
        self.assertIsNone(column.parse_directive({"orders": []}))
        offer = column.column_offer(self._army())
        self.assertIn("ASSAULT COLUMN possible on Gap", offer)

    def test_column_gathers_advances_together_and_charges(self):
        import column
        st = self._army()
        col = column.AssaultColumn()
        msg = col.command({"objective": "Gap", "from": [[-2000, 0]], "go": True}, st)
        self.assertIn("8 brigades", msg)                       # 80 % of 10
        stats, charged, lines_at_charge = {}, [], []
        for _ in range(400):
            ids, out = col.orders(st, [], None, stats)
            if any(o["cmd"] == "charge" for o in out):
                charged = [o for o in out if o["cmd"] == "charge"]
                inf = [u for u in st["units"] if u["id"] in ids and u["kind"] == "Infantry"]
                lines_at_charge = [-u["x"] for u in inf]          # depth along the approach (from the west)
                break
            # the defenders wear down under the column's fire once it is close
            if col.active and col.active["phase"] == "prepare":
                for e in st["units"]:
                    if e["side"] == "North":
                        e["morale"] = max(0.3, e["morale"] - 0.1)
            self._walk(st, out)
        self.assertTrue(charged, stats)
        self.assertGreaterEqual(len(charged), 8)               # infantry + cavalry
        self.assertLess(max(lines_at_charge) - min(lines_at_charge), 160 + 2 * 120)   # together: two ranks deep
        self.assertLess(min(lines_at_charge), 550 + 120)
        self.assertIn("assault column steps (every group on the same line)", stats)
        self.assertIsNone(col.active)

    def test_envelopment_two_groups_and_cancel(self):
        import column
        st = self._army()
        col = column.AssaultColumn()
        col.command({"objective": "Gap", "from": [[-2000, 0], [0, -2000]], "go": True}, st)
        self.assertEqual(len(col.active["groups"]), 2)
        self.assertEqual(sorted(len(g["inf"]) for g in col.active["groups"]), [4, 4])
        ids, out = col.orders(st, [{"cmd": "fallback", "id": 1}], None, {})
        self.assertNotIn(1, {o["id"] for o in out})         # a fallback of the model stands
        for u in st["units"]:
            if u["side"] == "South":
                u["morale"] = 0.3
        ids, out = col.orders(st, [], None, {})
        self.assertIsNone(col.active)
        self.assertIn("cancelled", col.last)
        self.assertTrue(all(o["cmd"] == "move" for o in out))   # back to the gather line

    def test_reinforcement_lines(self):
        import column
        army = [soldier(k, "South", 0, 200 * k) for k in range(1, 5)]
        late = soldier(9, "South", 2000, 3000)
        foe = soldier(50, "North", 2300, 3200)
        st = {"playerSide": "North", "time": 4000.0, "units": army + [late, foe]}
        lines = column.reinforcement_lines(st, {9: 3900.0})
        self.assertIn("REINFORCEMENTS cut off", lines[0])
        self.assertIn("#9", lines[1])
        self.assertEqual(column.reinforcement_lines(st, {}), [])

    def test_llm_plus_runs_the_column(self):
        config = planner_server.load_config(os.path.join(SERVER, "config.json"))
        config["backend"] = "placeholder"
        commander = planner_server.Commander(config)
        st = self._army()
        st["units"][0]["id"] = 1

        class Stub:
            supports_schema = False
            last_info = {}

            def complete(self, system, user, **kw):
                return json.dumps({"reasoning": "Column.", "orders": [{"cmd": "hold", "id": 1}],
                                   "assault_column": {"objective": "Gap", "from": [[-2000, 0]], "go": True}})

        commander.backend = Stub()
        cwd = os.getcwd()
        os.chdir(SERVER)
        try:
            with redirect_stdout(io.StringIO()):
                commander.track(st)
                orders = commander.plan(st, os.devnull)
        finally:
            os.chdir(cwd)
        self.assertIsNotNone(commander.column.active)
        members = commander.column.members()
        self.assertIn(1, members)
        self.assertFalse(any(o["id"] == 1 and o["cmd"] == "hold" for o in orders))   # taken over by the column
        self.assertTrue(any(o["id"] in members and o.get("auto") for o in orders))

class Wip17AntietamFixes(unittest.TestCase):
    """Antietam (2026-11-15): counter-battery, crossings, field works, phases of a chained battle."""
    def _guns(self):
        gun = soldier(1, "South", 1000, 1000, kind="Artillery", range=1250.0, weapon="gun_3in_Ordnance_Rifle_RF",
                      limber="ready")
        enemy_gun = soldier(9, "North", 1000, 1900, kind="Artillery", range=1100.0, weapon="gun_12pdr_Napoleon")
        far_foot = soldier(8, "North", 1000, 2100)
        return {"playerSide": "North", "time": 600.0, "units": [gun, enemy_gun, far_foot]}

    def test_rifled_override_and_counter_battery_block(self):
        import fire
        st = self._guns()
        orders = [{"cmd": "range_attack", "id": 1, "target": 8}]           # infantry 1,100 away
        out = fire.counter_battery_override(st, orders, None, {})
        self.assertEqual(out, [{"cmd": "range_attack", "id": 1, "target": 9, "auto": True}])
        st["units"][2]["z"] = 1700.0                                     # infantry at 700: the model's choice stands
        self.assertEqual(fire.counter_battery_override(st, orders, None, {}), orders)
        lines = fire.counter_battery_lines(self._guns())
        self.assertIn("COUNTER-BATTERY", lines[0])
        self.assertIn("#1 (rifled): #9 at 900", lines[1])

    def test_crossing_lines(self):
        import terrain
        import works
        grid = ["." * 10] * 2 + ["~~~~B~~~~~"] + ["." * 10] * 7
        t = terrain.TerrainMap({"minX": 0, "minZ": 0, "maxX": 1000, "maxZ": 1000, "step": 100, "terrain": grid,
                                "heights": ["1" * 10] * 10, "legend": {".": "Grass", "~": "Water", "B": "Bridge"},
                                "objectives": []})
        reserve = soldier(1, "South", 450, 1000)
        foe = soldier(9, "North", 450, -300)
        st = {"playerSide": "North", "time": 600.0, "units": [reserve, foe],
              "objectives": [{"name": "Bridge", "x": 450, "z": 300, "side": "South"}]}
        lines = works.crossing_lines(st, t)
        self.assertIn("CROSSINGS", lines[0])
        self.assertIn("THREATENED AND EMPTY", lines[1])
        self.assertIn("nearest reserve #1", lines[1])
        reserve["z"] = 300.0
        self.assertIn("contested", works.crossing_lines(st, t)[1])

    def test_fortification_lines_and_fortify_order(self):
        import works
        brig = soldier(1, "South", 1000, 1000)
        inside = soldier(2, "South", 1500, 1000, fort=True)
        foe = soldier(9, "North", 1000, 2000)
        st = {"playerSide": "North", "time": 600.0, "units": [brig, inside, foe],
              "objectives": [{"name": "Hill", "x": 1000, "z": 1200, "side": "South"}],
              "fortifications": [{"name": "w1", "x": 1000, "z": 1300, "hp": 100, "free": True},
                                 {"name": "w2", "x": 1500, "z": 1000, "hp": 100, "free": False, "occupant": 2},
                                 {"name": "w3", "x": 5000, "z": 5000, "hp": 100, "free": True}]}
        lines = works.fortification_lines(st)
        self.assertIn("1 of your brigades in works", lines[0])
        self.assertEqual(len(lines), 2)
        self.assertIn("free work at 1000,1300", lines[1])
        self.assertIn("nearest brigade #1", lines[1])
        clean = prompting.sanitize([{"cmd": "fortify", "id": 1, "x": 1000, "z": 1300},
                                    {"cmd": "fortify", "id": 2}], st, 10)
        self.assertEqual(clean, [{"cmd": "fortify", "id": 1, "x": 1000.0, "z": 1300.0}])

    def test_merge_phases_in_the_scoreboard(self):
        import fix_scoreboard as fs
        h = [{"ended": "2026-11-15 14:50:09", "outcome": "draw", "points": 1, "model": "m",
              "own_men_lost": 100, "enemy_men_lost_seen": 50},
             {"ended": "2026-11-15 15:54:20", "outcome": "draw", "points": 1, "model": "m",
              "own_men_lost": 200, "enemy_men_lost_seen": 100},
             {"ended": "2026-11-15 16:38:03", "outcome": "defeat", "points": 0, "model": "m",
              "own_men_lost": 300, "enemy_men_lost_seen": 150},
             {"ended": "2026-11-15 17:00:00", "outcome": "no_contest", "points": 0, "model": "m",
              "own_men_lost": 0, "enemy_men_lost_seen": 0}]
        sb = fs.totals(h)
        sb["by_model"] = {"m": {"battles": 4, "points": 2, "victories": 0, "defeats": 1, "draws": 2,
                                "men_lost": 600, "enemy_men_lost_seen": 300}}
        sb["history"] = h
        reports = {"2026-11-15 14:50:09": {"game_result_kind": "mission"},
                   "2026-11-15 15:54:20": {"game_result_kind": "mission"},
                   "2026-11-15 17:00:00": {"duration_s": 0}}
        new, merged, excluded = fs.merge_phases(sb, reports)
        self.assertEqual(len(new["history"]), 1)
        final = new["history"][0]
        self.assertEqual((final["outcome"], final["phases"], final["own_men_lost"], final["enemy_men_lost_seen"]),
                         ("defeat", 3, 600, 300))
        self.assertEqual((new["battles"], new["points"], new["draws"]), (1, 0, 0))
        self.assertEqual(len(new["merged_phases"]), 2)
        self.assertEqual(len(new["excluded"]), 1)
        self.assertEqual(len(sb["history"]), 4)                          # the original is left untouched


if __name__ == "__main__":
    unittest.main()
