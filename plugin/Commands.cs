using System;
using Newtonsoft.Json.Linq;
using UnityEngine;

namespace UgcwAi
{
    // Executes the commands sent by the planner server (one JSON object per line).
    public static class Commands
    {
        public static bool AwaitingPlan;      // true while the server is planning and the game is paused
        public static float AwaitingSince;    // real time at which the pause started
        public static float NextPlanAt;       // game time (Time.time) before which no planning pause starts
        public static float NextDelay = 30f;  // seconds of play between two planning pauses (set by the server)
        private static float resumeSpeed = 1f;

        public static void Execute(string line)
        {
            try
            {
                JObject o = JObject.Parse(line);
                string cmd = (string)o["cmd"];
                if (cmd == "move")
                {
                    // Optional "fx","fz": a map point the unit should face when it arrives.
                    bool hasFace = o["fx"] != null && o["fz"] != null;
                    Move((uint)o["id"], (float)o["x"], (float)o["z"], hasFace,
                         hasFace ? (float)o["fx"] : 0f, hasFace ? (float)o["fz"] : 0f);
                }
                else if (cmd == "ammo")
                {
                    GOAP.UnitModel unit = Find((uint)o["id"]);
                    if (unit != null && unit.side != RuntimeVars.playerSide) UnitExtras.SetAmmo(unit, (string)o["value"]);
                }
                else if (cmd == "limber")
                {
                    GOAP.UnitModel battery = Find((uint)o["id"]);
                    if (battery != null && battery.side != RuntimeVars.playerSide) UnitExtras.SetLimber(battery, (string)o["value"]);
                }
                else if (cmd == "supply")
                {
                    GOAP.UnitModel wagon = Find((uint)o["id"]);
                    if (wagon != null && wagon.side != RuntimeVars.playerSide)
                        UnitExtras.SetSupply(wagon, o["artillery"] != null, o["artillery"] != null && (bool)o["artillery"],
                                             o["infantry"] != null, o["infantry"] != null && (bool)o["infantry"]);
                }
                else if (cmd == "thought") AiThoughtsPanel.Set((string)o["mode"], o["kd"] != null ? (float)o["kd"] : -1f,
                                                                o["time"] != null ? (float)o["time"] : 0f, (string)o["text"]);
                else if (cmd == "pause") SetSpeed(0f);
                else if (cmd == "resume") SetSpeed(1f);
                else if (cmd == "plan_done")
                {
                    if (o["next_in"] != null) NextDelay = Mathf.Clamp((float)o["next_in"], 5f, 900f);
                    EndPlan();
                }
                else if (!Orders.TryExecute(cmd, o)) Debug.Log("[UgcwAi] Unknown command: " + cmd);
            }
            catch (Exception e) { Debug.LogError("[UgcwAi] Invalid command: " + e); }
        }

        public static void BeginPlan()
        {
            BattleLogic bl = BattleLogic.instance;
            if (bl == null || bl.GameSpeed <= 0f) return;   // never override a manual pause
            resumeSpeed = bl.GameSpeed;
            bl.GameSpeed = 0f;
            AwaitingPlan = true;
            AwaitingSince = Time.realtimeSinceStartup;
        }

        public static void EndPlan()
        {
            BattleLogic bl = BattleLogic.instance;
            if (bl != null && AwaitingPlan) bl.GameSpeed = resumeSpeed;
            AwaitingPlan = false;
            // The delay starts when the game resumes and is counted in game time, so the time the
            // model spends thinking while the game is paused never eats into it.
            NextPlanAt = Time.time + NextDelay;
        }

        private static void SetSpeed(float v)
        {
            if (BattleLogic.instance != null) BattleLogic.instance.GameSpeed = v;
        }

        private static GOAP.UnitModel Find(uint id)
        {
            GOAP.UnitManager um = GOAP.UnitManager.instance;
            if (um == null) return null;
            for (int i = 0; i < um.unitsCount; i++)
            {
                GOAP.UnitModel u = um.units[i];
                if (u != null && u.id == id) return u;
            }
            return null;
        }

        private static void Move(uint id, float x, float z, bool hasFace, float fx, float fz)
        {
            GOAP.UnitModel u = Find(id);
            if (u == null || !u.IsAlive || u.side == RuntimeVars.playerSide) return;
            if (u.IsUnderAIControl) u.aiData.commander.RemoveUnit(u);   // take the unit away from the native AI
            Vector2 target2 = new Vector2(x, z);
            TerrainController.instance.ClipWithWorldBounds(ref target2);
            Vector2 dir2 = target2 - u.PositionV2;
            bool inPlace = dir2.sqrMagnitude < 1f;
            if (inPlace && !hasFace) return;
            if (!inPlace) dir2.Normalize();
            if (hasFace)
            {
                // Final facing: towards the given point (so the line faces the enemy, not the march direction).
                Vector2 face2 = new Vector2(fx, fz) - target2;
                if (face2.sqrMagnitude > 1f) { face2.Normalize(); dir2 = face2; }
                else if (inPlace) return;
            }
            u.CancelActions();
            GOAP.Target.NavMeshPath path = GOAP.Target.NavMeshPath.Create(
                u, Extensions.ConvertPos(target2), new Vector3(dir2.x, 0f, dir2.y), true);
            GOAP.Planner.instance.MovePlayerToTargetWithFire(
                u, path,
                new GOAP.Action.OnActionCompleteDelegate(OnDone),
                GOAP.Precondition.UnitsCollisionWithFire.Create(u),
                u.BaseSpeed);
            Debug.Log("[UgcwAi] Move " + u.id + " -> " + x + "," + z);
        }

        private static void OnDone(GOAP.UnitModel unit, bool isCanceled)
        {
            Bridge.Send("{\"type\":\"done\",\"id\":" + unit.id + ",\"canceled\":" + (isCanceled ? "true" : "false") + "}");
        }
    }
}
