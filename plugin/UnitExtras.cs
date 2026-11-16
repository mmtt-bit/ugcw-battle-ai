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
            // 0.1.4 WIP10: skirmish screens. A screen carries the brigade it came from; a brigade that can detach one
            // (the game's own "pop skirmishers" test) carries canScout.
            try
            {
                GOAP.ScoutModel sc = u as GOAP.ScoutModel;
                if (sc != null) o["owner"] = sc.ownerUnitID;
                else if (CanDetach(u)) o["canScout"] = true;
            }
            catch (Exception) { }
            // 0.1.4 WIP9: the game's own test (TerrainController.InWorldBounds): a reinforcement still walking in from
            // outside the field. Sent only when true, so the server need not guess from its terrain scan.
            try { if (!Commands.OnField(u)) o["offField"] = true; }
            catch (Exception) { }
            // 0.1.4 WIP17: the unit holds a field work (GOAP.UnitModel.Fortification). Sent only when true.
            try { if (u.Fortification != null) o["fort"] = true; }
            catch (Exception) { }
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
                // 0.1.4 WIP11: the height the game's rules use (GOAP.UnitModel.altitude, 0 = lowest ground of the map,
                // 1 = highest, read from the ground under the unit). RangeAttack.RangeDmg compares shooter and target
                // (difference clamped to -1..1); Morale.Update and get_SpottingRange use the unit's own value.
                o["alt"] = Math.Round(u.altitude, 3);
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
                // Corps the unit belongs to (-1 when none) and, for a general, the radius in which his corps bonuses
                // reach his brigades.
                object corps = ReadProperty(u, "CorpsId");
                if (corps != null) o["corps"] = Convert.ToInt32(corps);
                if (u.Kind.ToString() == "General")
                {
                    object radius = ReadProperty(u, "CommandRadius");
                    if (radius != null) o["commandRadius"] = Math.Round(Convert.ToDouble(radius), 0);
                }
            }
            catch (Exception) { }
            try
            {
                // Cavalry: mounted or dismounted (like limbered / unlimbered for artillery), and whether it may
                // dismount at all (the game forbids it to shock cavalry and inside fortifications).
                if (u is GOAP.CavalryModel)
                {
                    o["mount"] = MountState(u);
                    o["canDismount"] = CanDismount(u);
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
            if (value != "pack" && Commands.HasRoute(u.id))
            {
                // 0.1.4 WIP9: never unlimber a battery on its march (it would stop where it is). 7 unpacks reached
                // marching batteries on 2026-11-12 14:48 (the state had been read before the move started).
                UnityEngine.Debug.Log("[UgcwAi] Limber " + u.id + " -> " + value + " ignored: the battery is on its march");
                return;
            }
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

        // "mounted", "dismounting", "dismounted" or "mounting" (EUnitState 18 = Dismounting, 19 = Dismounted;
        // enableDismounting tells the direction of a change in progress).
        public static string MountState(GOAP.UnitModel u)
        {
            bool[] flags = ReadField(u, "flags") as bool[];
            bool changing = flags != null && flags.Length > 18 && flags[18];
            bool down = flags != null && flags.Length > 19 && flags[19];
            object wants = ReadField(u, "enableDismounting");
            bool toFoot = wants is bool && (bool)wants;
            if (changing) return toFoot ? "dismounting" : "mounting";
            return down ? "dismounted" : "mounted";
        }

        // Same rule as the game's dismount button (ButtonsContainer.OnDismountClick): cavalry only, not shock
        // cavalry (weapon melee damage above Config.gameSettings.unitSettings.cavalry.shockCavalryThreshold),
        // and not inside a fortification.
        public static bool CanDismount(GOAP.UnitModel u)
        {
            if (!(u is GOAP.CavalryModel)) return false;
            try
            {
                object weapon = ReadProperty(u, "Weapon");
                object melee = weapon != null ? ReadField(weapon, "meleeDamage") : null;
                Type config = typeof(GOAP.UnitModel).Assembly.GetType("Config");
                object settings = config != null ? config.GetField("gameSettings",
                    System.Reflection.BindingFlags.Static | System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.NonPublic).GetValue(null) : null;
                object unitSettings = settings != null ? ReadField(settings, "unitSettings") : null;
                object cavalry = unitSettings != null ? ReadField(unitSettings, "cavalry") : null;
                object threshold = cavalry != null ? ReadField(cavalry, "shockCavalryThreshold") : null;
                if (melee != null && threshold != null && Convert.ToDouble(melee) > Convert.ToDouble(threshold)) return false;
            }
            catch (Exception) { }
            if (ReadProperty(u, "Fortification") != null) return false;
            return true;
        }

        // Executes {"cmd":"mount","id":9,"value":"dismount"|"mount"} for a cavalry unit, as the game's dismount button
        // does (UnitModel.IsDismounting = true dismounts, false mounts again).
        public static void SetMount(GOAP.UnitModel u, string value)
        {
            if (u == null || !u.IsAlive || !(u is GOAP.CavalryModel)) return;
            bool dismount = value == "dismount";
            if (dismount && !CanDismount(u))
            {
                UnityEngine.Debug.Log("[UgcwAi] Mount " + u.id + ": this cavalry cannot dismount (shock cavalry or fortification)");
                return;
            }
            try { if (u.IsUnderAIControl) u.aiData.commander.RemoveUnit(u); }
            catch (Exception) { }
            System.Reflection.PropertyInfo p = typeof(GOAP.UnitModel).GetProperty("IsDismounting",
                System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.NonPublic);
            if (p == null || !p.CanWrite) { UnityEngine.Debug.LogWarning("[UgcwAi] Mount: IsDismounting not found"); return; }
            p.SetValue(u, dismount, null);
            UnityEngine.Debug.Log("[UgcwAi] Mount " + u.id + " -> " + value + " (" + MountState(u) + ")");
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
        // 0.1.4 WIP10: the tests of ButtonsContainer.IsPopScoutButtonEnabled (without the selection and mission ones)
        public static bool CanDetach(GOAP.UnitModel u)
        {
            return u != null && u.Kind == EUnitKind.Infantry && u.IsAlive && u.canCreateScout && !u.IsCaptured
                   && Rebalance.Methods.CanDetachSkirmisher(u);
        }

        // The game's "pop skirmishers" button (GameInputController.PopScoutAction): the brigade detaches a screen,
        // which walks a little ahead by itself (ScoutModel.MoveAfterPop).
        public static void Detach(GOAP.UnitModel u)
        {
            if (!CanDetach(u))
            {
                UnityEngine.Debug.Log("[UgcwAi] Detach " + u.id + " refused: this brigade cannot detach skirmishers now");
                return;
            }
            u.CreateScout();
            UnityEngine.Debug.Log("[UgcwAi] Detach " + u.id + ": skirmishers detached");
        }

        // The game's "push skirmishers" button (GameInputController.PushScoutAction): the screen walks back into its
        // brigade (Planner.PushScout).
        public static void Recall(GOAP.UnitModel u)
        {
            GOAP.ScoutModel sc = u as GOAP.ScoutModel;
            if (sc == null)
            {
                UnityEngine.Debug.Log("[UgcwAi] Recall " + u.id + " refused: not a skirmish screen");
                return;
            }
            GOAP.Planner.instance.PushScout(sc);
            UnityEngine.Debug.Log("[UgcwAi] Recall " + u.id + ": back to brigade " + sc.ownerUnitID
                                  + " (return delay " + u.ReturnDelayProgress().ToString("0.00") + ")");
        }

        // 0.1.4 WIP17 (Antietam 2026-11-15: 703 work cells, never more than 3 AI brigades in them). Executes
        // {"cmd":"fortify","id":N,"x":X,"z":Z}: the brigade marches into the free work nearest X,Z (within 150 of it),
        // or without x/z into the free work nearest to it within 400. The same call as the player's right click on
        // the work's shield (Fortification.OnHudPointerDown): GOAP.Planner.TakeFortification(work, unit, true).
        // (Unit.TakeFortification is not used: it teleports the unit, it is meant for reinforcements placed at start.)
        public static void Fortify(GOAP.UnitModel u, bool hasPoint, float x, float z)
        {
            if (u == null || !u.IsAlive) return;
            if (u.Fortification != null)
            {
                UnityEngine.Debug.Log("[UgcwAi] Fortify " + u.id + ": already in a work");
                return;
            }
            if (!u.abilProps.fortify)
            {
                UnityEngine.Debug.Log("[UgcwAi] Fortify " + u.id + ": this unit cannot hold works");
                return;
            }
            System.Collections.IList works = ActiveWorks();
            if (works == null) return;
            UnityEngine.Vector2 up = u.PositionV2;          // y = the map's z
            float cx = hasPoint ? x : up.x, cz = hasPoint ? z : up.y;
            float limit = hasPoint ? 150f : 400f;
            string mySide = u.Side.ToString();
            Fortification best = null;
            float bestD = limit;
            for (int i = 0; i < works.Count; i++)
            {
                Fortification f = works[i] as Fortification;
                if (f == null || f.assignedUnit != null || f.Hp <= 0f || !f.IsSupported(u)) continue;
                string allowed = f.allowedSide.ToString();
                if ((allowed == "North" || allowed == "South") && allowed != mySide) continue;
                UnityEngine.Vector3 p = f.transform.position;
                float d = (float)Math.Sqrt((p.x - cx) * (p.x - cx) + (p.z - cz) * (p.z - cz));
                if (d < bestD) { bestD = d; best = f; }
            }
            if (best == null)
            {
                UnityEngine.Debug.Log("[UgcwAi] Fortify " + u.id + ": no free work within " + limit + " of "
                          + Math.Round(cx, 0) + "," + Math.Round(cz, 0));
                return;
            }
            GOAP.Planner.instance.TakeFortification(best, u, true);
            UnityEngine.Debug.Log("[UgcwAi] Fortify " + u.id + ": into " + best.name + " at "
                      + Math.Round(best.transform.position.x, 0) + "," + Math.Round(best.transform.position.z, 0));
        }

        // FortificationsManager.activeFortifications is private in the game: read it with reflection
        private static System.Reflection.FieldInfo activeWorksField;
        private static System.Collections.IList ActiveWorks()
        {
            FortificationsManager fm = FortificationsManager.instance;
            if (fm == null) return null;
            if (activeWorksField == null)
                activeWorksField = typeof(FortificationsManager).GetField("activeFortifications",
                    System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic
                    | System.Reflection.BindingFlags.Public);
            return activeWorksField != null ? activeWorksField.GetValue(fm) as System.Collections.IList : null;
        }

        public static void WriteRoot(JObject root)
        {
            // 0.1.4 WIP17: the field works of the current stage: position, hit points, free or held (occupant id)
            try
            {
                System.Collections.IList list = ActiveWorks();
                if (list != null)
                {
                    JArray works = new JArray();
                    for (int i = 0; i < list.Count; i++)
                    {
                        Fortification f = list[i] as Fortification;
                        if (f == null) continue;
                        UnityEngine.Vector3 p = f.transform.position;
                        JObject w = new JObject();
                        w["name"] = f.name;
                        w["x"] = Math.Round(p.x, 1);
                        w["z"] = Math.Round(p.z, 1);
                        w["hp"] = Math.Round(f.Hp, 0);
                        GOAP.UnitModel au = f.assignedUnit as GOAP.UnitModel;
                        w["free"] = au == null;
                        if (au != null) w["occupant"] = au.id;
                        try { w["side"] = f.allowedSide.ToString(); } catch (Exception) { }
                        works.Add(w);
                    }
                    if (works.Count > 0) root["fortifications"] = works;
                }
            }
            catch (Exception) { }
            // 0.1.4 WIP9: the playing field of the current stage [minX, minZ, maxX, maxZ]. TerrainController.SetLevel
            // moves it when a battle stage opens a new part of the map (2026-11-12 14:48: the field grew east to
            // x = 3,900 while the server's terrain scan stopped at x = 1,610).
            try
            {
                TerrainController tc = TerrainController.instance;
                if (tc != null)
                    root["field"] = new JArray(Math.Round(tc.minGameFieldPos.x, 1), Math.Round(tc.minGameFieldPos.y, 1),
                                               Math.Round(tc.maxGameFieldPos.x, 1), Math.Round(tc.maxGameFieldPos.y, 1));
            }
            catch (Exception) { }
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
