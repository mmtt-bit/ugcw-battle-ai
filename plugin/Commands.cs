using System;
using System.Collections.Generic;
using Newtonsoft.Json.Linq;
using UnityEngine;

namespace UgcwAi
{
    // Executes the commands sent by the planner server (one JSON object per line).
    public static class Commands
    {
        public static bool AwaitingPlan;      // a state was sent and the server has not answered "plan_done" yet
        public static bool Frozen;            // the game is paused because the server is calling the model
        public static float AwaitingSince;    // real time at which the state was sent (or the pause started)
        public static float FreezeTimeout = 90f;   // real seconds a model call may pause the game (set by the server)
        public static float NextPlanAt;       // game time (Time.time) before which no planning pause starts
        public static float NextDelay = 30f;
        public static bool ArtilleryGameSpeed = true;   // artillery moves pass 0 like the game's mouse path move
        public static bool ArtilleryIgnoreThreatCancel = true;   // no "enemy in threat area" cancel on our battery moves
        // 0.1.4 WIP9: a battery asked to go farther than this (whole route) limbers up first and starts when packed.
        // Our moves never limber a battery by themselves: on 2026-11-12 every battery crossed the field by hand.
        public static float ArtilleryPackDistance = 150f;

        // True when the unit stands on the battlefield (inside the game's world bounds).
        public static bool OnField(GOAP.UnitModel u)
        {
            try
            {
                Vector2 p = u.PositionV2;
                return TerrainController.instance == null || TerrainController.instance.InWorldBounds(new Vector3(p.x, 0f, p.y));
            }
            catch (Exception) { return true; }
        }

        // 0.1.4 WIP9: a unit off the field is LEFT ALONE (it used to be "given back" to the game's AI).
        // Reinforcements stand outside the game's world bounds with IsUnderAIControl = false and the game walks them
        // in by itself. The WIP7 version called CancelActions(), which killed that entry march, and then
        // CommanderManager.AddUnit(), which the game refuses out of bounds ("Trying to add unit with position out of
        // the game bounds", 146 times on 2026-11-12 14:48): eight brigades and batteries stayed at x = -4,200 for
        // the whole battle. Nothing is done to the unit now; the server orders it once it is on the field.
        private static readonly HashSet<uint> leftToGame = new HashSet<uint>();
        public static void ReleaseToGame(GOAP.UnitModel u)
        {
            try
            {
                if (u != null && leftToGame.Add(u.id))
                    Debug.Log("[UgcwAi] Unit " + u.id + " is off the field: left alone until the game walks it in");
            }
            catch (Exception) { }
        }
        private static float resumeSpeed = 1f;
        private static bool pausedByUs;       // the pause of this model call was set by the plugin (not by the player)

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
                else if (cmd == "freeze")
                {
                    // the server is about to call the model: pause until its "plan_done"
                    if (o["max_s"] != null) FreezeTimeout = Mathf.Clamp((float)o["max_s"], 30f, 600f);
                    Freeze();
                }
                else if (cmd == "pause") SetSpeed(0f);
                else if (cmd == "resume") SetSpeed(1f);
                else if (cmd == "plan_done")
                {
                    if (o["next_in"] != null) NextDelay = Mathf.Clamp((float)o["next_in"], 5f, 900f);
                    EndPlan();
                }
                else if (cmd == "detach" || cmd == "recall")
                {
                    // 0.1.4 WIP10: skirmish screens. "detach" {id: brigade} = the game's "pop skirmishers" button;
                    // "recall" {id: skirmish screen} = its "push skirmishers" button (back into the brigade)
                    GOAP.UnitModel u = Find((uint)o["id"]);
                    if (u == null) Debug.Log("[UgcwAi] " + cmd + ": unit " + o["id"] + " not found");
                    else if (cmd == "detach") UnitExtras.Detach(u);
                    else UnitExtras.Recall(u);
                }
                else if (cmd == "fortify")
                {
                    // 0.1.4 WIP17: {id, x?, z?} = the player's right click on a work's shield (Fortification.OnHudPointerDown)
                    GOAP.UnitModel u = Find((uint)o["id"]);
                    if (u == null) Debug.Log("[UgcwAi] fortify: unit " + o["id"] + " not found");
                    else if (o["x"] != null && o["z"] != null) UnitExtras.Fortify(u, true, (float)o["x"], (float)o["z"]);
                    else UnitExtras.Fortify(u, false, 0f, 0f);
                }
                else
                {
                    if (!Orders.TryExecute(cmd, o)) Debug.Log("[UgcwAi] Unknown command: " + cmd);
                }
            }
            catch (Exception e) { Debug.LogError("[UgcwAi] Invalid command: " + e); }
        }

        // Marks the state message as coming from a plugin whose states do not pause the game ("soft" states):
        // the server then asks for a state often (its own staff work runs at each one) and sends "freeze" only
        // before a model call.
        public static string Stamp(string stateJson)
        {
            if (stateJson == null || stateJson.Length < 2 || stateJson[stateJson.Length - 1] != '}') return stateJson;
            return stateJson.Substring(0, stateJson.Length - 1) + ",\"soft\":true}";
        }

        // A state was just sent. The game keeps running: most states need no model call and are answered in a
        // few milliseconds.
        public static void BeginPlan()
        {
            AwaitingPlan = true;
            Frozen = false;
            AwaitingSince = Time.realtimeSinceStartup;
        }

        private static void Freeze()
        {
            if (!AwaitingPlan || Frozen) return;
            Frozen = true;
            AwaitingSince = Time.realtimeSinceStartup;
            BattleLogic bl = BattleLogic.instance;
            pausedByUs = bl != null && bl.GameSpeed > 0f;   // never override a manual pause
            if (!pausedByUs) return;
            resumeSpeed = bl.GameSpeed;
            bl.GameSpeed = 0f;
        }

        // True when the server did not answer in time (Runner then calls EndPlan).
        public static bool TimedOut()
        {
            if (!AwaitingPlan) return false;
            return Time.realtimeSinceStartup - AwaitingSince > (Frozen ? FreezeTimeout : 30f);
        }

        public static void EndPlan()
        {
            BattleLogic bl = BattleLogic.instance;
            if (bl != null && Frozen && pausedByUs) bl.GameSpeed = resumeSpeed;
            Frozen = false;
            pausedByUs = false;
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
        private class Route { public List<Vector2> legs; public bool hasFace; public Vector2 face; public int gen; public bool starting; }
        private static readonly Dictionary<uint, Route> routes = new Dictionary<uint, Route>();
        private static int routeGen;
        // Next legs to start at the next frame: (unit id, route generation). A leg must not be started from inside
        // the completion callback of the previous one: Move() calls CancelActions(), which fired that callback a
        // second time with canceled = true, and the route was dropped at its first waypoint.
        private static readonly List<KeyValuePair<uint, int>> dueLegs = new List<KeyValuePair<uint, int>>();

        // Called every frame by Runner.Update.
        public static void Tick()
        {
            if (dueLegs.Count == 0) return;
            KeyValuePair<uint, int>[] due = dueLegs.ToArray();
            dueLegs.Clear();
            foreach (KeyValuePair<uint, int> d in due)
            {
                Route r;
                if (routes.TryGetValue(d.Key, out r) && r.gen == d.Value) NextLeg(d.Key, r);
            }
        }

        // True while the server's route for this unit is being walked (or waits for the battery to limber up).
        public static bool HasRoute(uint id)
        {
            return routes.ContainsKey(id);
        }

        private static bool Flag(GOAP.UnitModel u, int i)
        {
            try
            {
                for (Type t = u.GetType(); t != null; t = t.BaseType)
                {
                    System.Reflection.FieldInfo f = t.GetField("flags", System.Reflection.BindingFlags.Instance
                        | System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.NonPublic
                        | System.Reflection.BindingFlags.DeclaredOnly);
                    if (f == null) continue;
                    bool[] flags = f.GetValue(u) as bool[];
                    return flags != null && flags.Length > i && flags[i];
                }
            }
            catch (Exception) { }
            return false;
        }

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
            r.starting = true;        // callbacks fired while this leg is being started are not its end
            try { Move(id, target.x, target.y, face, f.x, f.y, r.gen, last); }
            finally { r.starting = false; }
        }

        private static void Move(uint id, float x, float z, bool hasFace, float fx, float fz, int gen, bool last)
        {
            GOAP.UnitModel u = Find(id);
            if (u == null || !u.IsAlive || u.side == RuntimeVars.playerSide)
            {
                // the unit is gone (destroyed, captured): tell the server, or the move stays "pending" on its side
                Route gone;
                if (routes.TryGetValue(id, out gone) && gone.gen == gen)
                {
                    routes.Remove(id);
                    Bridge.Send("{\"type\":\"done\",\"id\":" + id + ",\"canceled\":true}");
                }
                return;
            }
            // 0.1.4 WIP7: a unit still outside the battlefield (reinforcements entering at the map edge) cannot be
            // moved by the planner: its move ends at once and it slides along the world bound. In the battle of
            // 2026-11-12 three brigades and a general stayed there for 149 minutes. Such a unit is left (or given
            // back) to the game's AI, which walks it in; the server orders it once it is on the field.
            // 0.1.4 WIP9: ReleaseToGame no longer touches the unit (see there).
            if (!OnField(u))
            {
                ReleaseToGame(u);
                Route off;
                if (routes.TryGetValue(id, out off) && off.gen == gen) routes.Remove(id);
                Bridge.Send("{\"type\":\"done\",\"id\":" + id + ",\"canceled\":true}");
                return;
            }
            if (u.IsUnderAIControl) u.aiData.commander.RemoveUnit(u);   // take the unit away from the native AI
            Vector2 target2 = new Vector2(x, z);
            TerrainController.instance.ClipWithWorldBounds(ref target2);
            Vector2 dir2 = target2 - u.PositionV2;
            bool inPlace = dir2.sqrMagnitude < 1f;
            if (inPlace && !hasFace)
            {
                // already there: next leg at the next frame, or the route is done (the server is told, so the
                // move does not stay "pending" on its side)
                Route r0;
                bool mine = routes.TryGetValue(id, out r0) && r0.gen == gen;
                if (!last && mine) dueLegs.Add(new KeyValuePair<uint, int>(id, gen));
                else if (mine) { routes.Remove(id); OnDone(u, false); }
                return;
            }
            if (!inPlace) dir2.Normalize();
            if (hasFace)
            {
                // Final facing: towards the given point (so the line faces the enemy, not the march direction).
                Vector2 face2 = new Vector2(fx, fz) - target2;
                if (face2.sqrMagnitude > 1f) { face2.Normalize(); dir2 = face2; }
                else if (inPlace)
                {
                    Route r1;
                    if (routes.TryGetValue(id, out r1) && r1.gen == gen) { routes.Remove(id); OnDone(u, false); }
                    return;
                }
            }
            bool packNow = false;
            if (u.Kind == EUnitKind.Artillery && !inPlace && !Flag(u, 17))
            {
                // 0.1.4 WIP9/WIP10: limber up for a long march (the whole route, not this leg alone). The game's Move
                // action limbers a battery by itself only when THIS leg is longer than limberingSwitchDistance and the
                // move is not a move with fire (Move.Process, flags 4/5/6): our routes are cut into short legs, so the
                // guns were pushed by hand. WIP9 limbered first and waited idle: the game's Idle.AttackTarget then
                // unlimbered the battery again as soon as an enemy was in range (86 "not packed" on 2026-11-13).
                // WIP10: the march starts at once; Move.Process stands still while IsLimbering, then moves limbered.
                float todo = (target2 - u.PositionV2).magnitude;
                Route rr;
                if (routes.TryGetValue(id, out rr) && rr.gen == gen)
                {
                    Vector2 prev = target2;
                    foreach (Vector2 leg in rr.legs) { todo += (leg - prev).magnitude; prev = leg; }
                }
                if (todo > ArtilleryPackDistance)
                {
                    // already limbering UP (flag 16 with enable=True): let it finish
                    packNow = !(Flag(u, 16) && UnitExtras.LimberInfo(u).Contains("enable=True"));
                    Debug.Log("[UgcwAi] Battery " + id + " limbers up for a march of " + Mathf.RoundToInt(todo) + " m");
                }
            }
            u.CancelActions();
            if (packNow) UnitExtras.SetLimber(u, "pack");   // after CancelActions, before the move starts
            GOAP.Target.NavMeshPath path = GOAP.Target.NavMeshPath.Create(
                u, Extensions.ConvertPos(target2), new Vector3(dir2.x, 0f, dir2.y), true);
            int myGen = gen;
            // The game's own mouse path move (GameInputController.OnLeftMouseUpPathMove) passes 0 as the last
            // argument. In the battle of 2026-11-11 all 237 artillery moves sent with u.BaseSpeed were cancelled at
            // once, while infantry moves worked. Artillery now uses the game's value; infantry keeps BaseSpeed until
            // tested (set ArtilleryGameSpeed = false to go back).
            bool gun = u.Kind == EUnitKind.Artillery;
            float speed = (gun && ArtilleryGameSpeed) ? 0f : u.BaseSpeed;
            float started = Time.time;
            string before = gun ? UnitExtras.LimberInfo(u) : null;
            // Planner.MovePlayerToTargetWithFire gives an artillery unit that is NOT on RuntimeVars.playerSide a cancel
            // condition: EnemyEnterArea(unit, ERange.InThreatArea). A battery with any enemy in its threat area (its
            // fire range) has its move cancelled at once: 27 of 27 artillery moves on 2026-11-11 evening, all within
            // 0.1 s. The server already decides when a battery may move near the enemy, so for that call the battery
            // is seen as the player's: playerSide is switched to the battery's side and put back right after (same
            // frame, nothing else runs in between).
            bool swapSide = gun && ArtilleryIgnoreThreatCancel && u.side != RuntimeVars.playerSide;
            var savedSide = RuntimeVars.playerSide;
            // The game's call starts with unit.Target = null, and UnitModel.set_Target updates selection and
            // highlights of the old target when unit.side == playerSide. Clear it here, with the real playerSide,
            // so the switch below cannot deselect or unhighlight one of the player's units.
            if (swapSide && u.Target != null) u.Target = null;
            if (swapSide) RuntimeVars.playerSide = u.side;
            try
            {
            GOAP.Planner.instance.MovePlayerToTargetWithFire(
                u, path,
                new GOAP.Action.OnActionCompleteDelegate((unit, canceled) =>
                {
                    // diagnostic: a battery move cancelled within 2 s is the bug of 2026-11-11
                    if (gun && canceled && Time.time - started < 2f)
                        Debug.Log("[UgcwAi] Artillery move " + unit.id + " cancelled after " + (Time.time - started).ToString("0.00")
                                  + " s | speed arg " + speed + " | before: " + before + " | now: " + UnitExtras.LimberInfo(unit));
                    OnLegDone(unit, canceled, myGen);
                }),
                GOAP.Precondition.UnitsCollisionWithFire.Create(u),
                speed);
            }
            finally
            {
                if (swapSide) RuntimeVars.playerSide = savedSide;
            }
            Debug.Log("[UgcwAi] Move " + u.id + " -> " + x + "," + z + (last ? "" : " (waypoint)")
                      + (gun ? " | artillery, speed arg " + speed + " | " + before : ""));
        }

        private static void OnLegDone(GOAP.UnitModel unit, bool isCanceled, int gen)
        {
            Route r;
            bool mine = routes.TryGetValue(unit.id, out r) && r.gen == gen;
            if (!mine && isCanceled) return;              // an older order replaced by a newer one: stay silent
            if (mine && r.starting) return;               // fired by the CancelActions() of the leg being started
            if (mine && !isCanceled && r.legs.Count > 0)
            {
                dueLegs.Add(new KeyValuePair<uint, int>(unit.id, gen));   // started by Tick() at the next frame
                return;
            }
            if (mine) routes.Remove(unit.id);
            OnDone(unit, isCanceled);
        }

        private static void OnDone(GOAP.UnitModel unit, bool isCanceled)
        {
            Bridge.Send("{\"type\":\"done\",\"id\":" + unit.id + ",\"canceled\":" + (isCanceled ? "true" : "false") + "}");
        }
    }
}
