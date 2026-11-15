// Add this method inside the Snapshot class (dnSpy: right-click Snapshot > Edit Class, paste it
// next to Build). Then, in Build(), inside the loop that fills each unit object (the one that
// writes "morale" and "fatigue"), add one line:   o["status"] = StatusOf(u);
// where "o" is the JObject of the unit and "u" is the GOAP.UnitModel. Use your own variable names.
//
// The flags below come from UnitModel: Retreating (set by Retreat() when morale <= 0.05, i.e. a
// routing unit), Shutter (shattered), Surrendered (captured), Fallback / WaveringFallback and
// MeleeCombat. If EUnitState is in a namespace, add the matching "using" at the top.
public static string StatusOf(GOAP.UnitModel u)
{
    if (u.IsCaptured || u.State(EUnitState.Surrendered)) return "captured";
    if (u.State(EUnitState.Shutter)) return "shattered";
    if (u.State(EUnitState.Retreating)) return "routing";
    if (u.State(EUnitState.WaveringFallback) || u.State(EUnitState.Fallback)) return "fallback";
    if (u.State(EUnitState.MeleeCombat)) return "melee";
    return "";
}

// FACING (new): also write the direction each unit faces, next to "status", in the same loop:
//     o["dx"] = Math.Round(u.Direction.x, 2);
//     o["dz"] = Math.Round(u.Direction.z, 2);
// u.Direction is the unit's forward vector (UnitModel.Direction). Without these two fields the
// server cannot tell which way a unit faces and just skips the facing hints.

// OBJECTIVES (new): so the AI knows who owns each objective during the battle, add this line in
// Snapshot.Build(), right after root["playerSide"] = ... :
//     root["objectives"] = TerrainScan.Objectives();
// (TerrainScan.Objectives must be "internal static", see BattleResult.cs.) Each objective carries
// "side" (current owner), "victoryPoints", "radius" and "captureRange". Without this line the
// server falls back to the owners recorded at the start of the battle.
