using System;
using Newtonsoft.Json.Linq;
using UnityEngine;

namespace UgcwAi
{
    // Tells the planner server how the battle ended. When a battle ends the game writes two lines
    // to its log:
    //     Mission finished. Result=<color=yellow>Defeat</color>
    //     Battle finished. Result=<color=yellow>Victory</color>
    // The "Battle finished" line is the battle result from the human player's point of view (it comes
    // from the battle objectives of the briefing). The "Mission finished" line is a different, internal
    // result: after a battle the human player had won, it still said Defeat. So both are sent and the
    // server relies on the battle one. We listen to Unity's log callback, remember the text, and send
    // the message from the main thread in Tick().
    //
    // Setup:
    //   1. Add this class (right-click the UgcwAi namespace > Add Class).
    //   2. Call BattleResult.Init() and BattleResult.Tick() in Runner.Update, next to TerrainScan.Tick().
    //   3. In TerrainScan, "Objectives()" must be "internal static JArray Objectives()".
    //   4. MissionGoals.cs (separate class) provides the final state of the briefing goals.
    public static class BattleResult
    {
        private static volatile string pendingMission;
        private static volatile string pendingBattle;
        private static float pendingSince;
        private static bool hooked;

        public static void Init()
        {
            if (hooked) return;
            hooked = true;
            Application.logMessageReceived += OnLog;
            Debug.Log("[UgcwAi] BattleResult hook installed");
        }

        private static string Extract(string condition, string prefix)
        {
            int i = condition.IndexOf(prefix, StringComparison.Ordinal);
            if (i < 0) return null;
            string result = condition.Substring(i + prefix.Length);
            // strip Unity rich text tags such as <color=yellow>...</color>
            while (true)
            {
                int a = result.IndexOf('<');
                int b = result.IndexOf('>');
                if (a < 0 || b < a) break;
                result = result.Remove(a, b - a + 1);
            }
            return result.Trim();
        }

        private static void OnLog(string condition, string stackTrace, LogType type)
        {
            if (condition == null) return;
            string battle = Extract(condition, "Battle finished. Result=");
            if (battle != null)
            {
                pendingBattle = battle;
                if (pendingMission == null) pendingSince = Time.realtimeSinceStartup;
            }
            string mission = Extract(condition, "Mission finished. Result=");
            if (mission != null)
            {
                pendingMission = mission;
                pendingSince = Time.realtimeSinceStartup;
            }
        }

        public static void Tick()
        {
            string mission = pendingMission, battle = pendingBattle;
            if (mission == null && battle == null) return;
            // The battle line follows the mission line: give it a moment to arrive.
            if (battle == null && Time.realtimeSinceStartup - pendingSince < 3f) return;
            pendingMission = null;
            pendingBattle = null;
            try
            {
                JObject msg = new JObject();
                msg["type"] = "battle_end";
                msg["result"] = battle != null ? battle : mission;     // the human player's battle result
                msg["resultKind"] = battle != null ? "battle" : "mission";
                msg["missionResult"] = mission;                        // internal text, for reference only
                msg["playerSide"] = RuntimeVars.playerSide.ToString();
                msg["objectives"] = TerrainScan.Objectives();          // final owner of each objective ("side")
                msg["battleGoals"] = MissionGoals.Describe();          // final state of the briefing goals
                Bridge.Send(msg.ToString(Newtonsoft.Json.Formatting.None));
                Debug.Log("[UgcwAi] battle_end sent: " + msg["result"] + " (" + msg["resultKind"] + ")");
            }
            catch (Exception e) { Debug.LogWarning("[UgcwAi] battle_end failed: " + e.Message); }
        }
    }
}
