using System;
using Newtonsoft.Json.Linq;

namespace UgcwAi
{
    // Equipment, veterancy, perks and ammunition of a unit, written into the unit's JSON object
    // of the state message. Every field is optional on the server side, and each read is guarded:
    // a field the game refuses to give simply stays out of the message.
    //
    // HOW TO USE (dnSpy, once):
    //   1. Add this file as a new class in the UgcwAi namespace (right-click the namespace > Add Class,
    //      paste, Compile).
    //   2. In Snapshot.Build(), in the loop that fills each unit object, right after the line that
    //      writes o["status"], add:      UnitExtras.Write(u, o);
    //      (use your own variable names: "u" is the GOAP.UnitModel and "o" its JObject).
    //   3. In Snapshot.Build(), next to root["playerSide"] = ..., add:     UnitExtras.WriteRoot(root);
    //   4. Compile, then File > Save Module.
    public static class UnitExtras
    {
        public static void Write(GOAP.UnitModel u, JObject o)
        {
            try
            {
                // Weapon asset name, for example "rifle_Mississippi_1841_RF".
                if (u.Weapon != null)
                {
                    o["weapon"] = u.Weapon.name;
                }
            }
            catch (Exception) { }
            try
            {
                // Current effective firing range, including the effect of the ammunition mode.
                o["range"] = Math.Round(u.effectiveRange, 0);
            }
            catch (Exception) { }
            try
            {
                // Veterancy: stars and level. The brigade's perks are unlocked one per level,
                // in the order of its skill list (the same rule as BrigadeModel.ApplySkills).
                o["stars"] = u.Stars;
                o["level"] = u.Level;
                GOAP.BrigadeModel b = u as GOAP.BrigadeModel;
                if (b != null && b.Skills != null)
                {
                    JArray perks = new JArray();
                    int n = Math.Min(b.Skills.Length, u.Level);
                    for (int i = 0; i < n; i++)
                    {
                        if (b.Skills[i] != null) perks.Add(b.Skills[i].name);
                    }
                    o["perks"] = perks;
                }
            }
            catch (Exception) { }
            try
            {
                // Share of the ammunition left.
                if (u.ammunitionTotalCost > 0f)
                {
                    o["ammo"] = Math.Round(Math.Min(1f, u.ammunitionCurrentCost / u.ammunitionTotalCost), 2);
                }
            }
            catch (Exception) { }
            try
            {
                // Frontage of the unit: the size of its line formation (width across the line, depth).
                // Brigade sizes differ a lot (Rebalance: up to 2500 men, 6000 with the very large size).
                object size = ReadField(u, "lineFormationSize");
                if (size is UnityEngine.Vector2)
                {
                    UnityEngine.Vector2 v2 = (UnityEngine.Vector2)size;
                    o["width"] = Math.Round(v2.x, 0);
                    o["depth"] = Math.Round(v2.y, 0);
                }
                else if (size is UnityEngine.Vector3)
                {
                    UnityEngine.Vector3 v3 = (UnityEngine.Vector3)size;
                    o["width"] = Math.Round(v3.x, 0);
                    o["depth"] = Math.Round(v3.z, 0);
                }
            }
            catch (Exception) { }
            try
            {
                // Ranges the game itself keeps on the unit: the distance at which it charges (UnitModel.chargeRange,
                // set from Rebalance.Methods.GetChargeRange) and, for cavalry, how far it sees (scouting).
                object charge = ReadField(u, "chargeRange");
                if (charge is float) o["chargeRange"] = Math.Round((float)charge, 0);
                if (u.Kind.ToString() == "Cavalry")
                {
                    object sees = ReadField(u, "spottingRange");
                    if (sees is float) o["spotting"] = Math.Round((float)sees, 0);
                }
            }
            catch (Exception) { }
            try
            {
                // Supply wagon: stock left, which kinds it feeds and the radius of its area.
                GOAP.SupplyModel sm = u as GOAP.SupplyModel;
                if (sm != null)
                {
                    if (sm.MaxSupplyCost > 0f) o["supplyStock"] = Math.Round(Math.Min(1f, sm.CurrentSupplyCost / sm.MaxSupplyCost), 2);
                    o["supplyArtillery"] = sm.SupplyArtillery;
                    o["supplyInfantry"] = sm.SupplyInfantry;
                    object range = ReadField(sm, "responseRange");
                    if (range is float) o["supplyRange"] = Math.Round((float)range, 0);
                }
            }
            catch (Exception) { }
            try
            {
                // Artillery ammunition mode: CanisterOnly = canister, CanisterAndShell = mixed, none = auto.
                if (u.Kind == EUnitKind.Artillery)
                {
                    o["ammoMode"] = u.CanisterOnly ? "canister" : (u.CanisterAndShell ? "mixed" : "auto");
                    o["shoot"] = u.shootType.ToString();
                    o["limber"] = LimberState(u);
                    o["limberInfo"] = LimberInfo(u);
                }
            }
            catch (Exception) { }
        }

        // ready = unlimbered and able to fire, packed = limbered (cannot fire), packing / unpacking = changing.
        // The game keeps these as two flags of the unit (EUnitState.Limbering = 16 and Limbered = 17);
        // the field "enableLimbering" says which way a change is going. Read with reflection so a name
        // that differs in this version just leaves the field out.
        private static string LimberState(GOAP.UnitModel u)
        {
            bool[] flags = ReadField(u, "flags") as bool[];
            if (flags == null || flags.Length <= 17) return "ready";
            if (flags[17]) return "packed";
            if (flags[16])
            {
                object up = ReadField(u, "enableLimbering");
                return (up is bool && !(bool)up) ? "unpacking" : "packing";
            }
            return "ready";
        }

        // Value of a field of any visibility along the type chain, or null.
        private static object ReadField(object o, string name)
        {
            const System.Reflection.BindingFlags Any = System.Reflection.BindingFlags.Instance
                | System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.NonPublic
                | System.Reflection.BindingFlags.DeclaredOnly;
            for (Type t = o.GetType(); t != null; t = t.BaseType)
            {
                System.Reflection.FieldInfo f = t.GetField(name, Any);
                if (f != null) return f.GetValue(o);
            }
            return null;
        }

        // Executes {"cmd":"supply","id":12,"artillery":true,"infantry":false} for a supply wagon:
        // which kinds of unit it rearms. A key that is missing leaves that switch as it is.
        public static void SetSupply(GOAP.UnitModel u, bool hasArtillery, bool artillery, bool hasInfantry, bool infantry)
        {
            GOAP.SupplyModel sm = u as GOAP.SupplyModel;
            if (sm == null || !sm.IsAlive) return;
            if (hasArtillery) sm.SupplyArtillery = artillery;
            if (hasInfantry) sm.SupplyInfantry = infantry;
            UnityEngine.Debug.Log("[UgcwAi] Supply " + u.id + " artillery=" + sm.SupplyArtillery + " infantry=" + sm.SupplyInfantry);
        }

        // Executes {"cmd":"limber","id":9,"value":"unpack"|"unpack_force"|"pack"} for an artillery unit.
        // "unpack" does what the limbering button does: IsLimbering = true packs the battery up, false unpacks
        // it so it can fire. A battery whose march was cancelled can be left packed with the internal
        // "_isLimbering" already false; the setter would then do nothing, so the field is first set to true.
        // "unpack_force" is for a battery that stayed packed after several normal unpack orders (the game's own
        // AI can pack it again): it clears the limbering state directly, the way ArtilleryLimbering.Update does
        // when the unlimbering time has run out. The state before and after goes to the log.
        public static void SetLimber(GOAP.UnitModel u, string value)
        {
            if (u == null || !u.IsAlive || u.Kind != EUnitKind.Artillery) return;
            // Like every other order (Orders.Controllable), take the battery away from the game's own AI commander.
            // Otherwise that AI can limber the battery up again right after the unpack (a battery got 25 unpack
            // orders in a row in one battle and never fired).
            try { if (u.IsUnderAIControl) u.aiData.commander.RemoveUnit(u); }
            catch (Exception e) { UnityEngine.Debug.LogWarning("[UgcwAi] Could not release the battery from the AI: " + e.Message); }
            string before = LimberInfo(u);
            if (value == "pack")
            {
                u.IsLimbering = true;
            }
            else
            {
                System.Reflection.FieldInfo f = typeof(GOAP.UnitModel).GetField("_isLimbering",
                    System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Public);
                if (f != null) f.SetValue(u, true);
                u.IsLimbering = false;
                if (value == "unpack_force") ForceUnpacked(u);
            }
            UnityEngine.Debug.Log("[UgcwAi] Limber " + u.id + " -> " + value + " | before: " + before + " | after: " + LimberInfo(u));
        }

        // Clears the packed / limbering flags and the timer by hand (see SetLimber, "unpack_force").
        private static void ForceUnpacked(GOAP.UnitModel u)
        {
            try
            {
                bool[] flags = ReadField(u, "flags") as bool[];
                if (flags != null && flags.Length > 17) { flags[16] = false; flags[17] = false; }
                WriteField(u, "limberingTime", 0f);
                WriteField(u, "enableLimbering", false);
                WriteField(u, "_isLimbering", false);
                System.Reflection.PropertyInfo mm = typeof(GOAP.UnitModel).GetProperty("MovementMode",
                    System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.NonPublic);
                if (mm != null && mm.CanWrite && mm.PropertyType.IsEnum)
                    mm.SetValue(u, Enum.ToObject(mm.PropertyType, 1), null);   // the value the game's own unpack path uses
            }
            catch (Exception e) { UnityEngine.Debug.LogWarning("[UgcwAi] Forced unpack failed: " + e.Message); }
        }

        // Compact dump of the limbering state, for the log and for the server (to see why a battery stays packed).
        public static string LimberInfo(GOAP.UnitModel u)
        {
            try
            {
                bool[] flags = ReadField(u, "flags") as bool[];
                bool f16 = flags != null && flags.Length > 16 && flags[16];
                bool f17 = flags != null && flags.Length > 17 && flags[17];
                object up = ReadField(u, "enableLimbering"), t = ReadField(u, "limberingTime");
                object inner = ReadField(u, "_isLimbering"), move = ReadField(u, "isInMove");
                return "limbering=" + f16 + " limbered=" + f17 + " enable=" + up + " _is=" + inner + " time=" + t + " inMove=" + move
                    + " aiControl=" + ReadProperty(u, "IsUnderAIControl");
            }
            catch (Exception) { return "?"; }
        }

        private static object ReadProperty(object o, string name)
        {
            try
            {
                System.Reflection.PropertyInfo p = o.GetType().GetProperty(name, System.Reflection.BindingFlags.Instance
                    | System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.NonPublic);
                return p != null ? p.GetValue(o, null) : null;
            }
            catch (Exception) { return null; }
        }

        private static void WriteField(object o, string name, object value)
        {
            const System.Reflection.BindingFlags Any = System.Reflection.BindingFlags.Instance
                | System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.NonPublic
                | System.Reflection.BindingFlags.DeclaredOnly;
            for (Type t = o.GetType(); t != null; t = t.BaseType)
            {
                System.Reflection.FieldInfo f = t.GetField(name, Any);
                if (f != null) { f.SetValue(o, value); return; }
            }
        }

        // Range at which canister is fired, so the server knows when to switch batteries to canister.
        public static void WriteRoot(JObject root)
        {
            // Rebalance.Methods.GetCanisterRange() exists only when the Rebalance mod is in the DLL: read with
            // reflection so this class compiles (and simply sends no value) without it.
            try
            {
                Type t = typeof(UnitExtras).Assembly.GetType("Rebalance.Methods");
                System.Reflection.MethodInfo m = t != null ? t.GetMethod("GetCanisterRange",
                    System.Reflection.BindingFlags.Static | System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.NonPublic) : null;
                if (m != null && m.GetParameters().Length == 0)
                    root["canisterRange"] = Math.Round(Convert.ToDouble(m.Invoke(null, null)), 0);
            }
            catch (Exception) { }
        }

        // Executes {"cmd":"ammo","id":9,"value":"auto"|"mixed"|"canister"} for an artillery unit.
        public static void SetAmmo(GOAP.UnitModel u, string mode)
        {
            if (u == null || !u.IsAlive || u.Kind != EUnitKind.Artillery) return;
            // Clear both flags first so the final state is exactly the requested one.
            u.CanisterOnly = false;
            u.CanisterAndShell = false;
            if (mode == "canister") u.CanisterOnly = true;
            else if (mode == "mixed") u.CanisterAndShell = true;
            UnityEngine.Debug.Log("[UgcwAi] Ammo " + u.id + " -> " + mode + " (range " + Math.Round(u.effectiveRange, 0) + ")");
        }
    }
}
