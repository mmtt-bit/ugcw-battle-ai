using System;
using System.Collections.Generic;
using GOAP;
using GOAP.Action;
using GOAP.Precondition;
using Newtonsoft.Json.Linq;
using UnityEngine;

namespace UgcwAi
{
    // Reflexes: fast reactions of the AI army that run inside the game between two planning turns, without
    // asking the language model (no tokens). The model sets the intent; the reflexes handle what cannot wait
    // for the next turn. Each reflex that fires writes a short event line; the planner server shows the
    // events of the last interval to the model in the next turn (they never trigger a turn by themselves).
    //
    //   FACE      a unit whose flank or rear is threatened by a close enemy turns to face it (if no closer
    //             enemy stands in front of it).
    //   BRACE     a unit charged while marching stops and stands; a unit charged shoots at the charger;
    //             once the charger is locked in melee, a fresh neighbour (infantry or mounted cavalry)
    //             charges it.
    //   UNSEEN    a unit losing men with no visible enemy within its own fire range (shooters hidden in woods or
    //             wheat, camouflaged by a perk, or out-ranging it) charges, closes in or opens the distance,
    //             depending on "unseen_aggressiveness" (the general's doctrine) and on its freshness.
    //   SAFETY    a threatened battery switches to canister and, with no infantry to cover it, steps back
    //             (fallback, stays unlimbered); a supply wagon or a general with an enemy too close moves away;
    //             a unit in contact whose morale collapses falls back at once.
    //
    // Settings come from the server ({"cmd":"reflexes", ...}, see Configure); every reflex has a cooldown per
    // unit. Units still under the game's own AI and the player's units are never touched.
    //
    // HOW TO USE (dnSpy): add this class (Compile), then recompile Commands, Snapshot and Runner from this package.
    public static class Reflexes
    {
        // Settings (game units / seconds). Overwritten by Configure().
        public static bool Enabled = false;   // off until the server sends its settings (never in dry run)
        // Hide the movement / attack arrows the game draws for the AI's orders: they tell the human player where
        // the AI is going. Set by the server ("hide_orders", config overlay.show_ai_orders); on by default.
        public static bool HideOrders = true;
        private static float nextArrowTick;
        public static bool Face = true, Brace = true, Safety = true;
        public static float TickSeconds = 0.5f;
        public static float FaceRadius = 350f, FaceAngle = 60f, FaceCooldown = 20f;
        public static float BraceRadius = 250f, CounterRadius = 300f, CounterMorale = 0.7f, BraceCooldown = 15f;
        public static float CanisterRange = 300f, BatteryCover = 200f, BatteryDanger = 150f;
        public static float WagonDanger = 450f, GeneralDanger = 400f, RunAway = 300f;
        public static float PanicMorale = 0.3f, PanicContact = 300f, SafetyCooldown = 20f;
        public static int MaxEvents = 40;
        public static bool Unseen = true, UnseenAdvance = false;
        public static float UnseenLoss = 6f, UnseenShare = 0.003f, UnseenReach = 650f, UnseenWindow = 60f;
        public static float UnseenCooldown = 25f, UnseenAdvanceMorale = 0.7f, UnseenStep = 150f;
        public static float UnseenAggressiveness = 0.5f, UnseenMinRange = 100f, UnseenChargeReach = 400f, UnseenCloseGap = 200f;
        private static readonly Dictionary<uint, float> lastHp = new Dictionary<uint, float>();
        private static readonly Dictionary<uint, float> lossAcc = new Dictionary<uint, float>();

        private static float nextTick;
        private static readonly Dictionary<string, float> cooldowns = new Dictionary<string, float>();
        private static readonly List<string> events = new List<string>();

        public static void Configure(JObject o)
        {
            try
            {
                Enabled = Bool(o, "enabled", Enabled);
                Face = Bool(o, "face", Face);
                Brace = Bool(o, "brace", Brace);
                Safety = Bool(o, "safety", Safety);
                TickSeconds = Num(o, "tick_s", TickSeconds);
                FaceRadius = Num(o, "face_radius", FaceRadius);
                FaceAngle = Num(o, "face_angle", FaceAngle);
                FaceCooldown = Num(o, "face_cooldown_s", FaceCooldown);
                BraceRadius = Num(o, "brace_radius", BraceRadius);
                CounterRadius = Num(o, "counter_radius", CounterRadius);
                CounterMorale = Num(o, "counter_morale", CounterMorale);
                BraceCooldown = Num(o, "brace_cooldown_s", BraceCooldown);
                CanisterRange = Num(o, "canister_range", CanisterRange);
                BatteryCover = Num(o, "battery_cover", BatteryCover);
                BatteryDanger = Num(o, "battery_danger", BatteryDanger);
                WagonDanger = Num(o, "wagon_danger", WagonDanger);
                GeneralDanger = Num(o, "general_danger", GeneralDanger);
                RunAway = Num(o, "run_away", RunAway);
                PanicMorale = Num(o, "panic_morale", PanicMorale);
                PanicContact = Num(o, "panic_contact", PanicContact);
                SafetyCooldown = Num(o, "safety_cooldown_s", SafetyCooldown);
                HideOrders = Bool(o, "hide_orders", HideOrders);
                Unseen = Bool(o, "unseen", Unseen);
                UnseenAdvance = Bool(o, "unseen_advance", UnseenAdvance);
                UnseenLoss = Num(o, "unseen_loss", UnseenLoss);
                UnseenShare = Num(o, "unseen_share", UnseenShare);
                UnseenReach = Num(o, "unseen_reach", UnseenReach);
                UnseenWindow = Mathf.Max(5f, Num(o, "unseen_window_s", UnseenWindow));
                UnseenCooldown = Num(o, "unseen_cooldown_s", UnseenCooldown);
                UnseenAdvanceMorale = Num(o, "unseen_advance_morale", UnseenAdvanceMorale);
                UnseenStep = Num(o, "unseen_step", UnseenStep);
                UnseenAggressiveness = Num(o, "unseen_aggressiveness", UnseenAdvance ? 0.8f : UnseenAggressiveness);
                UnseenMinRange = Num(o, "unseen_min_range", UnseenMinRange);
                UnseenChargeReach = Num(o, "unseen_charge_reach", UnseenChargeReach);
                UnseenCloseGap = Num(o, "unseen_close_gap", UnseenCloseGap);
                lastHp.Clear(); lossAcc.Clear();
                Debug.Log("[UgcwAi] Reflexes configured: enabled=" + Enabled + " face=" + Face + " brace=" + Brace
                          + " safety=" + Safety);
            }
            catch (Exception e) { Debug.LogWarning("[UgcwAi] Reflexes.Configure: " + e.Message); }
        }

        // Events since the last state message (the list is emptied).
        public static JArray DrainEvents()
        {
            JArray a = new JArray();
            lock (events)
            {
                foreach (string e in events) a.Add(e);
                events.Clear();
            }
            return a;
        }

        // Called from Runner.Update every frame (planning = a planning pause is running); works every TickSeconds
        // of play. Commands is not referenced here, so this class compiles before Commands.
        public static void Tick(bool planning)
        {
            if (HideOrders) HideArrows();
            if (!Enabled || planning) return;
            BattleLogic bl = BattleLogic.instance;
            if (bl == null || bl.GameSpeed <= 0f) return;
            if (Time.time < nextTick) return;
            nextTick = Time.time + TickSeconds;
            UnitManager um = MonoBehaviourSingleton<UnitManager>.instance;
            if (um == null || um.unitsCount == 0) return;
            try
            {
                List<UnitModel> mine = new List<UnitModel>(), foes = new List<UnitModel>();
                for (int i = 0; i < um.unitsCount; i++)
                {
                    UnitModel u = um.units[i];
                    if (u == null || !u.IsAlive) continue;
                    if (u.side == RuntimeVars.playerSide) { if (!Broken(u)) foes.Add(u); }
                    else mine.Add(u);
                }
                if (foes.Count == 0) return;
                foreach (UnitModel u in mine)
                {
                    if (u.IsUnderAIControl || Broken(u)) continue;
                    string kind = u.kind.ToString();
                    try
                    {
                        if (Unseen && UnseenReflex(u, kind, foes)) continue;
                        if (Safety && SafetyReflex(u, kind, mine, foes)) continue;
                        if (Brace && BraceReflex(u, kind, mine, foes)) continue;
                        if (Face) FaceReflex(u, kind, foes);
                    }
                    catch (Exception e) { Debug.LogWarning("[UgcwAi] Reflex on " + u.id + ": " + e.Message); }
                }
            }
            catch (Exception e) { Debug.LogWarning("[UgcwAi] Reflexes.Tick: " + e.Message); }
        }

        // ---------------------------------------------------------------- reflexes

        private static bool SafetyReflex(UnitModel u, string kind, List<UnitModel> mine, List<UnitModel> foes)
        {
            UnitModel e = NearestSeen(u, foes, true);
            if (e == null) return false;
            float d = Dist(u, e);
            if (kind == "Artillery")
            {
                bool closeThreat = e.kind.ToString() == "Infantry" || e.kind.ToString() == "Cavalry";
                if (!closeThreat) return false;
                if (d <= CanisterRange && Ready(u, "canister", SafetyCooldown))
                {
                    UnitExtras.SetAmmo(u, "canister");
                    Note(u, "canister", "battery #" + u.id + " switched to canister (#" + e.id + " at " + (int)d + ")");
                }
                if (d <= BatteryDanger && !Covered(u, e, mine) && Ready(u, "battery_back", SafetyCooldown))
                {
                    u.CancelActions();
                    Planner.instance.ManualFallback(u, 15f);
                    Note(u, "battery_back", "battery #" + u.id + " stepped back, uncovered, #" + e.id + " at " + (int)d);
                    return true;
                }
                return false;
            }
            if ((kind == "Supply" && d <= WagonDanger) || (kind == "General" && d <= GeneralDanger))
            {
                if (!Ready(u, "away", SafetyCooldown)) return true;
                Vector2 away = u.PositionV2 - e.PositionV2;
                if (away.sqrMagnitude < 1f) return true;
                away.Normalize();
                MoveTo(u, u.PositionV2 + away * RunAway, away);
                Note(u, "away", (kind == "Supply" ? "wagon #" : "general #") + u.id + " moved away from #" + e.id
                     + " (" + (int)d + ")");
                return true;
            }
            if ((kind == "Infantry" || kind == "Cavalry" || kind == "Skirmish") && u.morale < PanicMorale
                && d <= PanicContact && !u.State(EUnitState.MeleeCombat) && !u.State(EUnitState.Fallback)
                && Ready(u, "panic", SafetyCooldown))
            {
                u.CancelActions();
                Planner.instance.ManualFallback(u, 20f);
                Note(u, "panic", "#" + u.id + " fell back, morale " + u.morale.ToString("0.00") + " in contact with #" + e.id);
                return true;
            }
            return false;
        }

        private static bool BraceReflex(UnitModel u, string kind, List<UnitModel> mine, List<UnitModel> foes)
        {
            if (kind != "Infantry" && kind != "Skirmish" && kind != "Cavalry") return false;
            if (u.State(EUnitState.MeleeCombat))
            {
                // Locked in melee: a fresh neighbour charges the enemy that is fighting us.
                UnitModel enemy = NearestSeen(u, foes, true);
                if (enemy == null || Dist(u, enemy) > 120f || !enemy.State(EUnitState.MeleeCombat)) return false;
                if (!Ready(u, "counter", BraceCooldown)) return false;
                UnitModel helper = null;
                float best = CounterRadius;
                foreach (UnitModel n in mine)
                {
                    if (n == u || n.IsUnderAIControl || Broken(n) || n.morale < CounterMorale) continue;
                    string nk = n.kind.ToString();
                    if (nk != "Infantry" && nk != "Cavalry") continue;
                    if (nk == "Cavalry" && UnitExtras.MountState(n) != "mounted") continue;
                    if (n.State(EUnitState.MeleeCombat) || n.State(EUnitState.Charging)) continue;
                    float dn = Dist(n, enemy);
                    if (dn < best) { best = dn; helper = n; }
                }
                if (helper == null) return false;
                helper.CancelActions();
                Planner.instance.ManualCharge(helper, enemy, false);
                Note(u, "counter", "#" + helper.id + " charged #" + enemy.id + " locked in melee with #" + u.id);
                return true;
            }
            // A charge coming at this unit?
            UnitModel charger = null;
            float cd = BraceRadius;
            foreach (UnitModel e in foes)
            {
                if (!e.State(EUnitState.Charging)) continue;
                float d = Dist(u, e);
                if (d > cd || !u.CanSee(e)) continue;
                Vector2 toU = u.PositionV2 - e.PositionV2;
                Vector2 dir = new Vector2(e.Direction.x, e.Direction.z);
                if (toU.sqrMagnitude < 1f || dir.sqrMagnitude < 0.01f) continue;
                if (Vector2.Dot(toU.normalized, dir.normalized) < 0.8f) continue;   // not running at us
                cd = d; charger = e;
            }
            if (charger == null || !Ready(u, "brace", BraceCooldown)) return false;
            if (kind == "Cavalry" && UnitExtras.MountState(u) == "mounted" && u.morale >= CounterMorale)
            {
                u.CancelActions();
                Planner.instance.ManualCharge(u, charger, false);
                Note(u, "brace", "cavalry #" + u.id + " met the charge of #" + charger.id + " head on");
                return true;
            }
            u.CancelActions();
            Planner.instance.PlayerRangeAttack(u, charger, false);
            Note(u, "brace", "#" + u.id + " stopped and fired at charging #" + charger.id + " (" + (int)cd + ")");
            return true;
        }

        private static void FaceReflex(UnitModel u, string kind, List<UnitModel> foes)
        {
            if (kind != "Infantry" && kind != "Skirmish" && kind != "Cavalry") return;
            if (u.State(EUnitState.MeleeCombat) || u.State(EUnitState.Charging) || u.State(EUnitState.Walking)
                || u.State(EUnitState.Running) || u.State(EUnitState.Fallback)) return;
            Vector2 fwd = new Vector2(u.Direction.x, u.Direction.z);
            if (fwd.sqrMagnitude < 0.01f) return;
            fwd.Normalize();
            float cosLimit = Mathf.Cos(FaceAngle * Mathf.Deg2Rad);
            UnitModel threat = null, front = null;
            float td = FaceRadius, fd = float.MaxValue;
            foreach (UnitModel e in foes)
            {
                string ek = e.kind.ToString();
                if (ek != "Infantry" && ek != "Cavalry" && ek != "Skirmish") continue;
                float d = Dist(u, e);
                if (d > FaceRadius * 1.5f || !u.CanSee(e)) continue;
                Vector2 to = (e.PositionV2 - u.PositionV2);
                if (to.sqrMagnitude < 1f) continue;
                float c = Vector2.Dot(fwd, to.normalized);
                if (c >= cosLimit) { if (d < fd) fd = d; }
                else if (d < td) { td = d; threat = e; }
            }
            if (threat == null || fd <= td * 1.2f) return;     // a closer enemy is already in front: keep facing it
            if (!Ready(u, "face", FaceCooldown)) return;
            Vector2 dir = (threat.PositionV2 - u.PositionV2).normalized;
            MoveTo(u, u.PositionV2, dir);
            Note(u, "face", "#" + u.id + " turned to face #" + threat.id + " on its flank/rear (" + (int)td + ")");
        }

        // Losses while no visible enemy stands within the unit's own fire range: the shooters are hidden (woods,
        // wheat, a camouflage perk) or out-range it, so the unit cannot answer. Losses are summed with a decay each
        // tick. The answer depends on the general's aggressiveness (UnseenAggressiveness, 0 careful .. 1 reckless):
        //   >= 0.7  fresh infantry or mounted cavalry charges a skirmisher or shaken enemy in reach; fresh infantry
        //           or skirmishers advance toward the nearest visible enemy (or straight ahead) to find the shooters;
        //   >= 0.4  fresh infantry or skirmishers close in only on a visible enemy just out of their range;
        //   else    (and for artillery, supply and tired units) the unit opens the distance.
        private static bool UnseenReflex(UnitModel u, string kind, List<UnitModel> foes)
        {
            float hp = u.hp, prev;
            bool known = lastHp.TryGetValue(u.id, out prev);
            lastHp[u.id] = hp;
            float acc;
            lossAcc.TryGetValue(u.id, out acc);
            // losses summed over about UnseenWindow seconds: slow attrition by skirmishers adds up too
            acc = acc * Mathf.Exp(-TickSeconds / UnseenWindow) + (known ? Mathf.Max(0f, prev - hp) : 0f);
            lossAcc[u.id] = acc;
            if (kind == "General" || u.State(EUnitState.MeleeCombat) || u.State(EUnitState.Fallback)
                || u.State(EUnitState.Charging) || u.State(EUnitState.Walking) || u.State(EUnitState.Running))
                return false;                                         // fighting or following an order
            float threshold = Mathf.Max(UnseenLoss, UnseenShare * u.MaxHP);
            if (acc < threshold) return false;
            UnitModel seen = NearestSeen(u, foes, true);
            float seenD = seen != null ? Dist(u, seen) : float.MaxValue;
            float myRange = Mathf.Max(u.effectiveRange, UnseenMinRange);
            if (seenD <= myRange * 1.1f) return false;                // it can shoot back at what it sees
            if (!Ready(u, "unseen", UnseenCooldown)) return false;
            lossAcc[u.id] = 0f;

            bool mounted = kind == "Cavalry" && UnitExtras.MountState(u) == "mounted";
            bool fresh = u.morale >= UnseenAdvanceMorale && u.hp >= 0.6f * u.MaxHP;
            float a = UnseenAggressiveness;
            string tag = "#" + u.id + " under fire, shooters unseen or out of range (" + (int)acc + " men): ";
            Vector2 fwd = new Vector2(u.Direction.x, u.Direction.z);

            if (a >= 0.7f && fresh && seen != null && (kind == "Infantry" || mounted) && seenD <= UnseenChargeReach
                && (seen.kind.ToString() == "Skirmish" || seen.morale < 0.5f))
            {
                u.CancelActions();
                Planner.instance.ManualCharge(u, seen, false);
                Note(u, "unseen", tag + "charged #" + seen.id);
                return true;
            }
            bool foot = kind == "Infantry" || kind == "Skirmish";
            bool advance = foot && fresh && (a >= 0.7f || (a >= 0.4f && seen != null && seenD <= myRange + UnseenCloseGap));
            if (advance)
            {
                Vector2 to, pos;
                if (seen != null)
                {
                    to = (seen.PositionV2 - u.PositionV2).normalized;
                    pos = u.PositionV2 + to * Mathf.Max(0f, seenD - myRange * 0.8f);
                    Note(u, "unseen", tag + "closed in on #" + seen.id + " to answer its fire");
                }
                else
                {
                    if (fwd.sqrMagnitude < 0.01f) return false;
                    to = fwd.normalized;
                    pos = u.PositionV2 + to * UnseenStep;
                    Note(u, "unseen", tag + "advanced to find the shooters");
                }
                MoveTo(u, pos, to);
                return true;
            }
            // open the distance: away from the nearest visible enemy, else back from where the unit faces
            Vector2 away = seen != null ? (u.PositionV2 - seen.PositionV2) : -fwd;
            if (away.sqrMagnitude < 0.01f) return false;
            away.Normalize();
            if (foot)
            {
                u.CancelActions();
                Planner.instance.ManualFallback(u, 20f);
                Note(u, "unseen", tag + "fell back to open the distance");
            }
            else
            {
                MoveTo(u, u.PositionV2 + away * (mounted ? RunAway + 100f : RunAway), kind == "Supply" ? away : -away);
                Note(u, "unseen", tag + "moved out of range");
            }
            return true;
        }

        // Removes the order arrows of the AI's units (the game draws them for orders given "as a player").
        private static void HideArrows()
        {
            if (Time.realtimeSinceStartup < nextArrowTick) return;
            nextArrowTick = Time.realtimeSinceStartup + 0.1f;
            try
            {
                UnitManager um = MonoBehaviourSingleton<UnitManager>.instance;
                if (um == null) return;
                for (int i = 0; i < um.unitsCount; i++)
                {
                    UnitModel u = um.units[i];
                    if (u != null && u.IsAlive && u.side != RuntimeVars.playerSide) u.CleanupArrow();
                }
            }
            catch (Exception) { }
        }

        // ---------------------------------------------------------------- helpers

        private static bool Broken(UnitModel u)
        {
            return u.IsCaptured || u.State(EUnitState.Retreating) || u.State(EUnitState.Shutter)
                || u.State(EUnitState.Surrendered);
        }

        private static float Dist(UnitModel a, UnitModel b)
        {
            return (a.PositionV2 - b.PositionV2).magnitude;
        }

        private static UnitModel NearestSeen(UnitModel u, List<UnitModel> foes, bool needSight)
        {
            UnitModel best = null;
            float bd = float.MaxValue;
            foreach (UnitModel e in foes)
            {
                float d = Dist(u, e);
                if (d >= bd) continue;
                if (needSight && !u.CanSee(e)) continue;
                bd = d; best = e;
            }
            return best;
        }

        // A steady friendly infantry unit within BatteryCover of the battery and nearer the enemy than the battery.
        private static bool Covered(UnitModel battery, UnitModel enemy, List<UnitModel> mine)
        {
            float de = Dist(battery, enemy);
            foreach (UnitModel n in mine)
            {
                if (n == battery || Broken(n) || n.kind.ToString() != "Infantry" || n.morale < 0.4f) continue;
                if (Dist(n, battery) <= BatteryCover && Dist(n, enemy) < de) return true;
            }
            return false;
        }

        private static bool Ready(UnitModel u, string reflex, float cooldown)
        {
            string key = u.id + ":" + reflex;
            float until;
            if (cooldowns.TryGetValue(key, out until) && Time.time < until) return false;
            cooldowns[key] = Time.time + cooldown;
            return true;
        }

        private static void Note(UnitModel u, string reflex, string text)
        {
            string line = "[" + FormatClock() + "] " + reflex + ": " + text;
            lock (events)
            {
                events.Add(line);
                if (events.Count > MaxEvents) events.RemoveAt(0);
            }
            Debug.Log("[UgcwAi] Reflex " + reflex + ": " + text);
        }

        private static string FormatClock()
        {
            float t = BattleLogic.instance != null ? BattleLogic.instance.TimeSinceBattleStart : 0f;
            int s = (int)t;
            return (s / 60) + ":" + (s % 60).ToString("00");
        }

        // Turn in place (pos = current position) or walk to pos, facing dir on arrival, like the server's moves.
        private static void MoveTo(UnitModel u, Vector2 pos, Vector2 dir)
        {
            TerrainController.instance.ClipWithWorldBounds(ref pos);
            u.CancelActions();
            GOAP.Target.NavMeshPath path = GOAP.Target.NavMeshPath.Create(u, Extensions.ConvertPos(pos),
                new Vector3(dir.x, 0f, dir.y), true);
            Planner.instance.MovePlayerToTargetWithFire(u, path, new OnActionCompleteDelegate(OnReflexMoveDone),
                UnitsCollisionWithFire.Create(u), u.BaseSpeed);
        }

        private static void OnReflexMoveDone(UnitModel unit, bool isCanceled) { }

        private static float Num(JObject o, string key, float def)
        {
            return o[key] != null ? (float)o[key] : def;
        }

        private static bool Bool(JObject o, string key, bool def)
        {
            return o[key] != null ? (bool)o[key] : def;
        }
    }
}
