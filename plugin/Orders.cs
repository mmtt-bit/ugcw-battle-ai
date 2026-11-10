using System;
using GOAP;
using Newtonsoft.Json.Linq;
using UnityEngine;

namespace UgcwAi
{
	// Token: 0x02000561 RID: 1377
	public static class Orders
	{
		// Token: 0x06001DF5 RID: 7669 RVA: 0x000C804C File Offset: 0x000C624C
		public static bool TryExecute(string cmd, JObject o)
		{
			if (cmd == "attack" || cmd == "charge" || cmd == "range_attack")
			{
				Orders.Engage(cmd, (uint)o["id"], (uint)o["target"]);
			}
			else if (cmd == "hold")
			{
				Orders.Hold((uint)o["id"]);
			}
			else if (cmd == "fallback")
			{
				Orders.Fallback((uint)o["id"], (o["duration"] != null) ? ((float)o["duration"]) : 20f);
			}
			else if (cmd == "formation")
			{
				Orders.SetFormation((uint)o["id"], (string)o["value"]);
			}
			else
			{
				if (!(cmd == "gait"))
				{
					return false;
				}
				Orders.SetGait((uint)o["id"], (string)o["value"]);
			}
			return true;
		}

		// Token: 0x06001DF6 RID: 7670 RVA: 0x000C7DC4 File Offset: 0x000C5FC4
		private static UnitModel Find(uint id)
		{
			UnitManager instance = MonoBehaviourSingleton<UnitManager>.instance;
			if (instance == null)
			{
				return null;
			}
			for (int i = 0; i < instance.unitsCount; i++)
			{
				UnitModel unitModel = instance.units[i];
				if (unitModel != null && unitModel.id == id)
				{
					return unitModel;
				}
			}
			return null;
		}

		// Token: 0x06001DF7 RID: 7671 RVA: 0x000C8188 File Offset: 0x000C6388
		private static UnitModel Controllable(uint id)
		{
			UnitModel unitModel = Orders.Find(id);
			if (unitModel == null || !unitModel.IsAlive || unitModel.side == RuntimeVars.playerSide)
			{
				return null;
			}
			if (unitModel.IsUnderAIControl)
			{
				unitModel.aiData.commander.RemoveUnit(unitModel);
			}
			return unitModel;
		}

		// Token: 0x06001DF8 RID: 7672 RVA: 0x000C81D4 File Offset: 0x000C63D4
		private static void Engage(string kind, uint id, uint targetId)
		{
			UnitModel unitModel = Orders.Find(id);
			UnitModel unitModel2 = Orders.Find(targetId);
			if (unitModel == null || unitModel2 == null || !unitModel2.IsAlive || unitModel2.side == unitModel.side)
			{
				return;
			}
			UnitModel unitModel3 = Orders.Controllable(id);
			if (unitModel3 == null)
			{
				return;
			}
			unitModel3.CancelActions();
			if (kind == "attack")
			{
				Planner.instance.ManualChaseTarget(unitModel3, unitModel2, false);
			}
			else if (kind == "charge")
			{
				Planner.instance.ManualCharge(unitModel3, unitModel2, false);
			}
			else
			{
				Planner.instance.PlayerRangeAttack(unitModel3, unitModel2, false);
			}
			Debug.Log(string.Concat(new object[]
			{
				"[UgcwAi] ",
				kind,
				" ",
				unitModel3.id,
				" -> ",
				unitModel2.id
			}));
		}

		// Token: 0x06001DF9 RID: 7673 RVA: 0x000C82AC File Offset: 0x000C64AC
		private static void Hold(uint id)
		{
			UnitModel unitModel = Orders.Controllable(id);
			if (unitModel == null)
			{
				return;
			}
			unitModel.CancelActions();
			Planner.instance.HoldPosition(unitModel, false);
			Debug.Log("[UgcwAi] hold " + unitModel.id);
		}

		// Token: 0x06001DFA RID: 7674 RVA: 0x000C82F0 File Offset: 0x000C64F0
		private static void Fallback(uint id, float duration)
		{
			UnitModel unitModel = Orders.Controllable(id);
			if (unitModel == null)
			{
				return;
			}
			unitModel.CancelActions();
			Planner.instance.ManualFallback(unitModel, duration);
			Debug.Log(string.Concat(new object[]
			{
				"[UgcwAi] fallback ",
				unitModel.id,
				" for ",
				duration,
				"s"
			}));
		}

		// Token: 0x06001DFB RID: 7675 RVA: 0x000C835C File Offset: 0x000C655C
		private static void SetFormation(uint id, string value)
		{
			UnitModel unitModel = Orders.Controllable(id);
			if (unitModel == null)
			{
				return;
			}
			if (value == "Line")
			{
				unitModel.Formation = EFormation.Line;
			}
			else
			{
				if (!(value == "RoadColumn"))
				{
					Debug.Log("[UgcwAi] Unknown formation: " + value);
					return;
				}
				unitModel.Formation = EFormation.RoadColumn;
			}
			Debug.Log(string.Concat(new object[]
			{
				"[UgcwAi] formation ",
				unitModel.id,
				" = ",
				value
			}));
		}

		// Token: 0x06001DFC RID: 7676 RVA: 0x000C83E4 File Offset: 0x000C65E4
		private static void SetGait(uint id, string value)
		{
			UnitModel unitModel = Orders.Controllable(id);
			if (unitModel == null)
			{
				return;
			}
			if (value == "Run")
			{
				unitModel.MovementMode = EMovementMode.Run;
			}
			else
			{
				if (!(value == "Walk"))
				{
					Debug.Log("[UgcwAi] Unknown gait: " + value);
					return;
				}
				unitModel.MovementMode = EMovementMode.Walk;
			}
			Debug.Log(string.Concat(new object[]
			{
				"[UgcwAi] gait ",
				unitModel.id,
				" = ",
				value
			}));
		}
	}
}
