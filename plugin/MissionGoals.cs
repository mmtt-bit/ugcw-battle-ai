using System;
using System.Collections;
using System.Reflection;
using Newtonsoft.Json.Linq;

namespace UgcwAi
{
    // Reads the battle objectives of the current mission straight from the game, the same ones the
    // briefing screen shows to the human player ("Victory conditions"). Each entry has a result
    // (Victory, Draw or Defeat, always from the human player's point of view), a list of "or" goals
    // and a list of "and" goals, and each goal says whether it is met right now. The game decides
    // the battle result by taking the first entry whose goals are met (MissionManager.CalcBattleResult).
    //
    // The server turns them round for the AI: what makes the player win is what the AI must prevent.
    //
    // Most of these fields are not public in the game, so they are read with reflection: this
    // compiles whatever their visibility, and a field that cannot be read is simply left out.
    //
    // HOW TO USE (dnSpy, once):
    //   1. Add this class in the UgcwAi namespace (right-click the namespace > Add Class), Compile.
    //   2. In Snapshot.Build(), after  jobject["objectives"] = TerrainScan.Objectives();  add:
    //          jobject["battleGoals"] = MissionGoals.Describe();
    //      (BattleResult.cs sends the same data in the battle_end message, nothing else to do.)
    //      NEW: also add   jobject["briefing"] = MissionGoals.Briefing();   on the next line, so the AI reads the
    //      mission title and description (the briefing text) and the objective descriptions.
    //   3. Compile, then File > Save Module.
    public static class MissionGoals
    {
        private const BindingFlags Any = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;

        // Value of a field (public or not) of any object, a boxed struct included, or null.
        private static object Read(object o, string name)
        {
            if (o == null) return null;
            try
            {
                for (Type t = o.GetType(); t != null; t = t.BaseType)
                {
                    FieldInfo f = t.GetField(name, Any | BindingFlags.DeclaredOnly);
                    if (f != null) return f.GetValue(o);
                }
            }
            catch (Exception) { }
            return null;
        }

        // The briefing text of the current mission as the deployment screen shows it (title and description,
        // in the game language) plus the day / mission index. Nothing is sent when the game has no text.
        public static JObject Briefing()
        {
            JObject b = new JObject();
            try
            {
                object manager = Read(BattleLogic.instance, "missionManager");
                object mission = Prop(manager, "CurrentMission") ?? Read(manager, "activeMission");
                if (mission == null) return b;
                string name = Text(Prop(mission, "DeploymentName") ?? Read(mission, "deploymentName"));
                string description = Text(Prop(mission, "DeploymentDescription") ?? Read(mission, "deploymentDescription"));
                string next = Text(Prop(mission, "ContinueMessage") ?? Read(mission, "continueMessage"));
                if (!string.IsNullOrEmpty(name)) b["name"] = name;
                if (!string.IsNullOrEmpty(description)) b["description"] = description;
                if (!string.IsNullOrEmpty(next)) b["continue"] = next;
                object index = Prop(manager, "CurrentMissionIndex");
                if (index != null) b["index"] = index.ToString();
            }
            catch (Exception e) { UnityEngine.Debug.LogWarning("[UgcwAi] Briefing failed: " + e.Message); }
            return b;
        }

        private static object Prop(object o, string name)
        {
            if (o == null) return null;
            try
            {
                PropertyInfo p = o.GetType().GetProperty(name, Any);
                return p != null ? p.GetValue(o, null) : null;
            }
            catch (Exception) { return null; }
        }

        private static string Text(object v)
        {
            if (v == null) return null;
            string s = v as string ?? v.ToString();
            return s == null ? null : s.Trim();
        }

        public static JArray Describe()
        {
            JArray list = new JArray();
            try
            {
                object manager = Read(BattleLogic.instance, "missionManager");
                IEnumerable entries = Read(manager, "battleObjectives") as IEnumerable;
                if (entries == null) return list;
                foreach (object entry in entries)
                {
                    JObject o = new JObject();
                    object result = Read(entry, "result");
                    o["result"] = result != null ? result.ToString() : "";
                    o["or"] = Goals(Read(entry, "orObjectives") as IEnumerable);
                    o["and"] = Goals(Read(entry, "andObjectives") as IEnumerable);
                    list.Add(o);
                }
            }
            catch (Exception e) { UnityEngine.Debug.LogWarning("[UgcwAi] MissionGoals failed: " + e.Message); }
            return list;
        }

        private static JArray Goals(IEnumerable goals)
        {
            JArray array = new JArray();
            if (goals == null) return array;
            foreach (object item in goals)
            {
                BattleGoal.Base g = item as BattleGoal.Base;
                if (g != null) array.Add(Goal(g));
            }
            return array;
        }

        private static JObject Goal(BattleGoal.Base g)
        {
            JObject j = new JObject();
            j["type"] = g.GetType().Name;
            try { j["state"] = g.State; } catch (Exception) { }
            try { j["message"] = g.Message; } catch (Exception) { }
            try { j["hidden"] = g.IsHidden; } catch (Exception) { }
            // Objective point name, ratio and comparison of the goal types that have them.
            object name = Read(g, "objectivePointName");
            if (name != null) j["objective"] = name.ToString();
            string[] ratios = { "requiredLossRate", "requiredKillRate", "ratio" };
            for (int i = 0; i < ratios.Length; i++)
            {
                object v = Read(g, ratios[i]);
                if (v is float) { j["ratio"] = (float)v; break; }
            }
            object condition = Read(g, "condition");
            if (condition != null) j["condition"] = condition.ToString();
            return j;
        }
    }
}
