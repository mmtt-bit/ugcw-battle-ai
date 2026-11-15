using System;
using System.Collections.Generic;
using System.Text;
using System.Text.RegularExpressions;
using Newtonsoft.Json.Linq;
using UnityEngine;

namespace UgcwAi
{
    // Sends a one-off description of the battlefield to the planner server: terrain types, relief,
    // objective points and the game's own terrain rules. It is sent again for every new battle and
    // every time the server (re)connects. Call TerrainScan.Tick() every frame from Runner.Update.
    public static class TerrainScan
    {
        private static object lastTerrain;   // the TerrainController instance we last described
        private static bool wasConnected;
        private static int failures;
        private static Vector4 lastField;      // the playing field last described (minX, minZ, maxX, maxZ)
        private static float nextFieldCheck;

        // Terrain types in the order of the legend sent to the server.
        private static readonly ETerrain[] AllTypes =
        {
            ETerrain.Grass, ETerrain.Wheatfield, ETerrain.Scrub, ETerrain.Mud, ETerrain.Forest,
            ETerrain.DenseForest, ETerrain.Water, ETerrain.WaterNoPass, ETerrain.Road,
            ETerrain.Bridge, ETerrain.Ford, ETerrain.Fortifications
        };

        // Terrain types whose effects (as described by the game) are sent to the server.
        private static readonly ETerrain[] RuleTypes =
        {
            ETerrain.Grass, ETerrain.Wheatfield, ETerrain.Scrub, ETerrain.Mud, ETerrain.Forest,
            ETerrain.DenseForest, ETerrain.Water, ETerrain.Road, ETerrain.Bridge, ETerrain.Ford,
            ETerrain.Fortifications
        };

        public static void Tick()
        {
            bool connected = Bridge.Connected;
            TerrainController tc = TerrainController.instance;
            GOAP.UnitManager um = GOAP.UnitManager.instance;
            bool ready = connected && tc != null && um != null && um.unitsCount > 0;
            bool newBattle = !object.ReferenceEquals(tc, lastTerrain);
            // 0.1.4 WIP9: a battle stage can open a new part of the map (TerrainController.SetLevel moves the playing
            // field). The description is then sent again with "update": true, so the server keeps its battle state.
            bool fieldMoved = false;
            if (ready && wasConnected && !newBattle && Time.realtimeSinceStartup >= nextFieldCheck)
            {
                nextFieldCheck = Time.realtimeSinceStartup + 2f;
                fieldMoved = Vector4.Distance(FieldOf(tc), lastField) > 1f;
            }
            if (ready && (!wasConnected || newBattle || fieldMoved))
            {
                try
                {
                    string json = Build(tc);
                    if (json != null && fieldMoved) json = "{\"update\":true," + json.Substring(1);
                    if (json != null)
                    {
                        lastField = FieldOf(tc);
                        if (fieldMoved) Debug.Log("[UgcwAi] The playing field changed: terrain description sent again");
                        Bridge.Send(json);
                        lastTerrain = tc;
                        failures = 0;
                        if (newBattle)
                        {
                            // A new battle: plan right away, and forget any pause left from the last one.
                            Commands.NextPlanAt = 0f;
                            Commands.AwaitingPlan = false;
                        }
                        Debug.Log("[UgcwAi] Terrain description queued (" + json.Length + " chars)");
                    }
                }
                catch (Exception e)
                {
                    failures++;
                    if (failures >= 3)
                    {
                        lastTerrain = tc;   // give up for this battle instead of failing every frame
                        lastField = FieldOf(tc);
                        Debug.LogError("[UgcwAi] Terrain scan failed, giving up for this battle: " + e);
                    }
                }
            }
            wasConnected = connected;
        }

        private static Vector4 FieldOf(TerrainController tc)
        {
            return new Vector4(tc.minGameFieldPos.x, tc.minGameFieldPos.y, tc.maxGameFieldPos.x, tc.maxGameFieldPos.y);
        }

        private static char SymbolOf(ETerrain t)
        {
            switch (t)
            {
                case ETerrain.Grass: return '.';
                case ETerrain.Wheatfield: return 'w';
                case ETerrain.Scrub: return 's';
                case ETerrain.Mud: return 'm';
                case ETerrain.Forest: return 'f';
                case ETerrain.DenseForest: return 'F';
                case ETerrain.Water: return '~';
                case ETerrain.WaterNoPass: return 'X';
                case ETerrain.Road: return '=';
                case ETerrain.Bridge: return 'B';
                case ETerrain.Ford: return ':';
                case ETerrain.Fortifications: return '#';
                default: return '?';
            }
        }

        private static string Build(TerrainController tc)
        {
            TerrainModifiersManager tm = TerrainModifiersManager.instance;
            if (tm == null) return null;

            // The playable area, in the same (x, z) coordinates as the units.
            float minX = tc.minGameFieldPos.x, minZ = tc.minGameFieldPos.y;
            float maxX = tc.maxGameFieldPos.x, maxZ = tc.maxGameFieldPos.y;
            if (maxX <= minX || maxZ <= minZ) return null;

            // Sample on a regular grid, coarser if the map is very large (about 25000 cells at most).
            float step = 25f;
            while (((maxX - minX) / step) * ((maxZ - minZ) / step) > 25000f) step += 5f;
            int cols = Mathf.CeilToInt((maxX - minX) / step);
            int rows = Mathf.CeilToInt((maxZ - minZ) / step);

            JArray terrainRows = new JArray();
            JArray heightRows = new JArray();
            StringBuilder tr = new StringBuilder();
            StringBuilder hr = new StringBuilder();
            for (int r = 0; r < rows; r++)
            {
                tr.Length = 0;
                hr.Length = 0;
                float z = minZ + (r + 0.5f) * step;
                for (int c = 0; c < cols; c++)
                {
                    float x = minX + (c + 0.5f) * step;
                    tr.Append(SymbolOf(tm.GetTerrain(x, z)));
                    float h = Mathf.Clamp01(tc.GetNormalizedHeight(x, z));
                    hr.Append((char)('0' + Mathf.Min(9, (int)(h * 10f))));   // 0 = lowest, 9 = highest
                }
                terrainRows.Add(tr.ToString());
                heightRows.Add(hr.ToString());
            }

            JObject legend = new JObject();
            foreach (ETerrain t in AllTypes) legend[SymbolOf(t).ToString()] = t.ToString();

            JObject root = new JObject();
            root["type"] = "terrain";
            root["minX"] = Math.Round(minX, 1);
            root["minZ"] = Math.Round(minZ, 1);
            root["maxX"] = Math.Round(maxX, 1);
            root["maxZ"] = Math.Round(maxZ, 1);
            root["step"] = step;
            root["cols"] = cols;
            root["rows"] = rows;
            root["terrain"] = terrainRows;
            root["heights"] = heightRows;
            root["legend"] = legend;
            root["objectives"] = Objectives();
            root["rules"] = Rules();
            root["altitudeCurves"] = AltitudeCurves();
            root["coverCurve"] = CoverCurve();
            return root.ToString(Newtonsoft.Json.Formatting.None);
        }

        // 0.1.4 WIP11: the three curves of UnitPreference that turn height into an effect. Their values are stored in
        // the game's assets, not in the code, so they are sampled here (11 points each), sent with the terrain and
        // written to the game log once per description:
        //   accuracy  x = shooter altitude - target altitude (-1..1); GOAP.Action.RangeAttack.RangeDmg: a value
        //             above 0 raises the low end of the damage roll by that share, below 0 lowers the high end;
        //   morale    x = the unit's altitude (0..1); GOAP.Modifier.Morale.Update multiplies the morale regeneration;
        //   spotting  x = the unit's altitude (0..1); GOAP.UnitModel.get_SpottingRange multiplies the spotting range.
        private static JObject AltitudeCurves()
        {
            JObject o = new JObject();
            try
            {
                UnitPreference up = MonoBehaviourSingleton<UnitPreference>.instance;
                if (up == null) return o;
                o["accuracy"] = SampleCurve(up.altitudeAccuracyDependency, -1f, 1f);
                o["morale"] = SampleCurve(up.altitudeMoraleDependency, 0f, 1f);
                o["spotting"] = SampleCurve(up.altitudeSpottingDependency, 0f, 1f);
                Debug.Log("[UgcwAi] Altitude curves [x, value]: " + o.ToString(Newtonsoft.Json.Formatting.None));
            }
            catch (Exception e) { Debug.LogWarning("[UgcwAi] Altitude curves: " + e.Message); }
            return o;
        }

        // 0.1.4 WIP13: the curve that turns the target's cover into damage. GOAP.Action.RangeAttack.Shoot (and
        // MeleeAndRangeAttack.Shoot) multiply the damage by
        //   coverCurve.Evaluate(c) - Rebalance.Methods.GetCoverCurveModifier(c)
        // with c = target.cover x GetArtilleryPenetration(shooter); the J&P correction is 0.1 - 0.15 c up to c = 0.53,
        // then 0. Terrain cover (GOAP.UnitModel.CalcCover): grass 0.25, wheat 0.55, forest 0.67, dense forest 0.70,
        // fortified ground 0.75, water 0, cavalry -0.05. Sampled from -0.1 to 1.0 every 0.05 (23 points), plus the
        // exact cover of each terrain, sent with the terrain and written to the game log once per description.
        private static readonly float[] TerrainCoverPoints = { -0.05f, 0f, 0.25f, 0.55f, 0.67f, 0.7f, 0.75f };

        private static JArray CoverCurve()
        {
            JArray a = new JArray();
            try
            {
                UnitPreference up = MonoBehaviourSingleton<UnitPreference>.instance;
                if (up == null || up.coverCurve == null) return a;
                a = SampleCurve(up.coverCurve, -0.1f, 1f, 22);
                JArray at = new JArray();
                foreach (float x in TerrainCoverPoints)
                    at.Add(new JArray(Math.Round(x, 2), Math.Round(up.coverCurve.Evaluate(x), 4)));
                Debug.Log("[UgcwAi] Cover curve [cover, value]: " + a.ToString(Newtonsoft.Json.Formatting.None)
                          + " | at terrain cover: " + at.ToString(Newtonsoft.Json.Formatting.None));
            }
            catch (Exception e) { Debug.LogWarning("[UgcwAi] Cover curve: " + e.Message); }
            return a;
        }

        private static JArray SampleCurve(AnimationCurve c, float from, float to)
        {
            return SampleCurve(c, from, to, 10);
        }

        private static JArray SampleCurve(AnimationCurve c, float from, float to, int steps)
        {
            JArray a = new JArray();
            if (c == null) return a;
            for (int i = 0; i <= steps; i++)
            {
                float x = from + (to - from) * i / (float)steps;
                a.Add(new JArray(Math.Round(x, 2), Math.Round(c.Evaluate(x), 4)));
            }
            return a;
        }

        // Visible objective points (capture points) of the battle.
        internal static JArray Objectives()
        {
            JArray list = new JArray();
            try
            {
                MapPoint.ObjectivePoint[] points = UnityEngine.Object.FindObjectsOfType<MapPoint.ObjectivePoint>();
                foreach (MapPoint.ObjectivePoint p in points)
                {
                    if (p == null || p.isHidden || !p.IsValid) continue;   // IsValid: in the playable area and listed in the current mission's active objectives
                    JObject o = new JObject();
                    o["name"] = p.Name;
                    o["x"] = Math.Round(p.transform.position.x, 1);
                    o["z"] = Math.Round(p.transform.position.z, 1);
                    o["side"] = p.Side.ToString();
                    o["radius"] = Math.Round(p.radius, 1);
                    o["captureRange"] = Math.Round(p.captureRange, 1);
                    o["victoryPoints"] = p.victoryPoints;
                    try { o["description"] = p.Description; } catch (Exception) { }
                    try { o["priority"] = p.Priority; } catch (Exception) { }
                    try { o["startSide"] = p.startSide.ToString(); } catch (Exception) { }
                    list.Add(o);
                }
            }
            catch (Exception e) { Debug.LogWarning("[UgcwAi] Objectives not available: " + e.Message); }
            return list;
        }

        // The game's own description of what each terrain does, per unit kind (in the game language).
        private static JObject Rules()
        {
            JObject rules = new JObject();
            GOAP.UnitManager um = GOAP.UnitManager.instance;
            if (um == null) return rules;
            List<string> done = new List<string>();
            for (int i = 0; i < um.unitsCount; i++)
            {
                GOAP.UnitModel u = um.units[i];
                if (u == null || !u.IsAlive) continue;
                string kind = u.kind.ToString();
                if (kind != "Infantry" && kind != "Cavalry" && kind != "Artillery") continue;
                if (done.Contains(kind)) continue;
                done.Add(kind);
                JObject byTerrain = new JObject();
                foreach (ETerrain t in RuleTypes)
                {
                    try
                    {
                        string hint = u.GetTerrainHint(t);
                        if (!string.IsNullOrEmpty(hint))
                            byTerrain[t.ToString()] = Regex.Replace(hint, "<[^>]+>", "").Trim();
                    }
                    catch (Exception) { }
                }
                rules[kind] = byTerrain;
            }
            return rules;
        }
    }
}
