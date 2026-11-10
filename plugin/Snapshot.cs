using System;
using GOAP;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace UgcwAi
{
	// Token: 0x0200055F RID: 1375
	public static class Snapshot
	{
		// Token: 0x06001DEA RID: 7658 RVA: 0x000C76A8 File Offset: 0x000C58A8
		public static string Build()
		{
			UnitManager instance = MonoBehaviourSingleton<UnitManager>.instance;
			if (instance == null || instance.unitsCount == 0)
			{
				return null;
			}
			JObject jobject = new JObject();
			jobject["type"] = "state";
			jobject["time"] = ((BattleLogic.instance != null) ? BattleLogic.instance.TimeSinceBattleStart : 0f);
			jobject["playerSide"] = RuntimeVars.playerSide.ToString();
			jobject["objectives"] = TerrainScan.Objectives();
			jobject["battleGoals"] = MissionGoals.Describe();
			jobject["briefing"] = MissionGoals.Briefing();
			jobject["reflexEvents"] = Reflexes.DrainEvents();   // what the in-game reflexes did since the last turn
			UnitExtras.WriteRoot(jobject);
			JArray jarray = new JArray();
			for (int i = 0; i < instance.unitsCount; i++)
			{
				UnitModel unitModel = instance.units[i];
				if (unitModel != null && unitModel.IsAlive && (unitModel.side != RuntimeVars.playerSide || Snapshot.SeenByAi(instance, unitModel)))
				{
					JObject jobject2 = new JObject();
					jobject2["id"] = unitModel.id;
					jobject2["name"] = unitModel.name;
					jobject2["side"] = unitModel.side.ToString();
					jobject2["kind"] = unitModel.kind.ToString();
					jobject2["x"] = Math.Round((double)unitModel.PositionV2.x, 1);
					jobject2["z"] = Math.Round((double)unitModel.PositionV2.y, 1);
					jobject2["hp"] = Math.Round((double)unitModel.hp, 1);
					jobject2["maxHp"] = Math.Round((double)unitModel.MaxHP, 1);
					jobject2["morale"] = Math.Round((double)unitModel.morale, 3);
					jobject2["fatigue"] = Math.Round((double)unitModel.condition, 3);
					jobject2["status"] = Snapshot.StatusOf(unitModel);
					jobject2["dx"] = Math.Round((double)unitModel.Direction.x, 2);
					jobject2["dz"] = Math.Round((double)unitModel.Direction.z, 2);
					jobject2["ai"] = unitModel.IsUnderAIControl;
					UnitExtras.Write(unitModel, jobject2);
					jarray.Add(jobject2);
				}
			}
			jobject["units"] = jarray;
			return jobject.ToString(Formatting.None, new JsonConverter[0]);
		}

		// Token: 0x06001DEB RID: 7659 RVA: 0x000C79A8 File Offset: 0x000C5BA8
		private static bool SeenByAi(UnitManager um, UnitModel target)
		{
			for (int i = 0; i < um.unitsCount; i++)
			{
				UnitModel unitModel = um.units[i];
				if (unitModel != null && unitModel.IsAlive && unitModel.side != RuntimeVars.playerSide && unitModel.CanSee(target))
				{
					return true;
				}
			}
			return false;
		}

		// Token: 0x06001DEC RID: 7660 RVA: 0x000C79F4 File Offset: 0x000C5BF4
		public static string StatusOf(UnitModel u)
		{
			if (u.IsCaptured || u.State(EUnitState.Surrendered))
			{
				return "captured";
			}
			if (u.State(EUnitState.Shutter))
			{
				return "shattered";
			}
			if (u.State(EUnitState.Retreating))
			{
				return "routing";
			}
			if (u.State(EUnitState.WaveringFallback) || u.State(EUnitState.Fallback))
			{
				return "fallback";
			}
			if (u.State(EUnitState.MeleeCombat))
			{
				return "melee";
			}
			return "";
		}
	}
}
