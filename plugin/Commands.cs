using System;
using System.Collections.Generic;
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
                    // Optional "path": [[x,z], ...] waypoints walked in order before the destination (a route along
                    // roads and open ground drawn by the server, like a player's mouse-drawn path).
                    bool hasFace = o["fx"] != null && o["fz"] != null;
                    List<Vector2> legs = new List<Vector2>();
                    JArray path = o["path"] as JArray;
                    if (path != null)
                        foreach (JToken p in path)
                            if (p is JArray && ((JArray)p).Count >= 2) legs.Add(new Vector2((float)p[0], (float)p[1]));
                    legs.Add(new Vector2((float)o["x"], (float)o["z"]));
                    StartRoute((uint)o["id"], legs, hasFace, hasFace ? (float)o["fx"] : 0f, hasFace ? (float)o["fz"] : 0f);
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
                else if (cmd == "reflexes") Reflexes.Configure(o);
                else if (cmd == "mount")
                {
                    GOAP.UnitModel rider = Find((uint)o["id"]);
                    if (rider != null && rider.side != RuntimeVars.playerSide) UnitExtras.SetMount(rider, (string)o["value"]);
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

        // Route state per unit: the legs still to walk, the final facing, and a generation number so that the
        // "canceled" callback of a replaced order never clears the route of the new one.
        private class Route { public List<Vector2> legs; public bool hasFace; public Vector2 face; public int gen; }
        private static readonly Dictionary<uint, Route> routes = new Dictionary<uint, Route>();
        private static int routeGen;

        private static void StartRoute(uint id, List<Vector2> legs, bool hasFace, float fx, float fz)
        {
            Route r = new Route { legs = legs, hasFace = hasFace, face = new Vector2(fx, fz), gen = ++routeGen };
            routes[id] = r;
            NextLeg(id, r);
        }

        private static void NextLeg(uint id, Route r)
        {
            if (r.legs.Count == 0) { routes.Remove(id); return; }
            Vector2 target = r.legs[0];
            r.legs.RemoveAt(0);
            bool last = r.legs.Count == 0;
            // at a waypoint, face along the next leg (no wheel back at the bend); at the end, the asked facing
            bool face = last ? r.hasFace : true;
            Vector2 f = last ? r.face : r.legs[0];
            Move(id, target.x, target.y, face, f.x, f.y, r.gen, last);
        }

        private static void Move(uint id, float x, float z, bool hasFace, float fx, float fz, int gen, bool last)
        {
            GOAP.UnitModel u = Find(id);
            if (u == null || !u.IsAlive || u.side == RuntimeVars.playerSide) { routes.Remove(id); return; }
            if (u.IsUnderAIControl) u.aiData.commander.RemoveUnit(u);   // take the unit away from the native AI
            Vector2 target2 = new Vector2(x, z);
            TerrainController.instance.ClipWithWorldBounds(ref target2);
            Vector2 dir2 = target2 - u.PositionV2;
            bool inPlace = dir2.sqrMagnitude < 1f;
            if (inPlace && !hasFace)
            {
                Route r0;
                if (!last && routes.TryGetValue(id, out r0) && r0.gen == gen) NextLeg(id, r0);
                return;
            }
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
            int myGen = gen;
            GOAP.Planner.instance.MovePlayerToTargetWithFire(
                u, path,
                new GOAP.Action.OnActionCompleteDelegate((unit, canceled) => OnLegDone(unit, canceled, myGen)),
                GOAP.Precondition.UnitsCollisionWithFire.Create(u),
                u.BaseSpeed);
            Debug.Log("[UgcwAi] Move " + u.id + " -> " + x + "," + z + (last ? "" : " (waypoint)"));
        }

        private static void OnLegDone(GOAP.UnitModel unit, bool isCanceled, int gen)
        {
            Route r;
            bool mine = routes.TryGetValue(unit.id, out r) && r.gen == gen;
            if (!mine && isCanceled) return;              // an older order replaced by a newer one: stay silent
            if (mine && !isCanceled && r.legs.Count > 0) { NextLeg(unit.id, r); return; }
            if (mine) routes.Remove(unit.id);
            OnDone(unit, isCanceled);
        }

        private static void OnDone(GOAP.UnitModel unit, bool isCanceled)
        {
            Bridge.Send("{\"type\":\"done\",\"id\":" + unit.id + ",\"canceled\":" + (isCanceled ? "true" : "false") + "}");
        }
    }
}
