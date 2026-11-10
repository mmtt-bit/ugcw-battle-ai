using System;
using System.Text;
using GOAP;
using GOAP.Action;
using GOAP.Precondition;
using GOAP.Target;
using UnityEngine;

namespace UgcwAi
{
	// Token: 0x0200055C RID: 1372
	public class Runner : MonoBehaviour
	{
		// Token: 0x06001DDA RID: 7642 RVA: 0x000C6D38 File Offset: 0x000C4F38
		private void Update()
		{
			BattleResult.Init();
			TerrainScan.Tick();
			BattleResult.Tick();
			if (Input.GetKeyDown(KeyCode.F9))
			{
				Runner.TakeControl();
			}
			if (Input.GetKeyDown(KeyCode.F7))
			{
				Runner.TestMove();
			}
			if (Input.GetKeyDown(KeyCode.F8))
			{
				Runner.TogglePause();
			}
			if (Input.GetKeyDown(KeyCode.F6))
			{
				AiThoughtsPanel.Visible = !AiThoughtsPanel.Visible;
			}
			int num = 0;
			string line;
			while (num++ < 20 && Bridge.TryReceive(out line))
			{
				Commands.Execute(line);
			}
			if (Commands.AwaitingPlan && (!Bridge.Connected || Time.realtimeSinceStartup - Commands.AwaitingSince > 90f))
			{
				Debug.LogWarning("[UgcwAi] Planner timeout or disconnect, resuming the game");
				Commands.EndPlan();
			}
			if (Bridge.Connected && !Commands.AwaitingPlan && Time.time >= Commands.NextPlanAt && BattleLogic.instance != null && BattleLogic.instance.GameSpeed > 0f)
			{
				string text = Snapshot.Build();
				if (text != null)
				{
					Bridge.Send(text);
					Commands.BeginPlan();
				}
			}
			if (Time.realtimeSinceStartup < this.next)
			{
				return;
			}
			this.next = Time.realtimeSinceStartup + 2f;
			Runner.LogState();
		}

		// Token: 0x06001DDC RID: 7644 RVA: 0x000C6E60 File Offset: 0x000C5060
		private static void LogState()
		{
			UnitManager instance = MonoBehaviourSingleton<UnitManager>.instance;
			if (instance == null)
			{
				return;
			}
			StringBuilder stringBuilder = new StringBuilder();
			stringBuilder.AppendLine(string.Concat(new object[]
			{
				"[UgcwAi] units=",
				instance.unitsCount,
				" playerSide=",
				RuntimeVars.playerSide
			}));
			int num = 0;
			while (num < instance.unitsCount && num < 30)
			{
				UnitModel unitModel = instance.units[num];
				if (unitModel != null && unitModel.IsAlive)
				{
					stringBuilder.AppendLine(string.Concat(new object[]
					{
						unitModel.id,
						" ",
						unitModel.name,
						" ",
						unitModel.side,
						" ",
						unitModel.kind,
						" pos=",
						unitModel.position,
						" v2=",
						unitModel.PositionV2,
						" alt=",
						unitModel.altitude,
						" hp=",
						unitModel.hp,
						"/",
						unitModel.MaxHP,
						" cond=",
						unitModel.condition,
						" ai=",
						unitModel.IsUnderAIControl.ToString()
					}));
				}
				num++;
			}
			Debug.Log(stringBuilder.ToString());
		}

		// Token: 0x06001DDD RID: 7645 RVA: 0x000C700C File Offset: 0x000C520C
		private static void TakeControl()
		{
			try
			{
				UnitManager instance = MonoBehaviourSingleton<UnitManager>.instance;
				if (!(instance == null))
				{
					int num = 0;
					for (int i = 0; i < instance.unitsCount; i++)
					{
						UnitModel unitModel = instance.units[i];
						if (unitModel != null && unitModel.IsAlive && unitModel.side != RuntimeVars.playerSide && unitModel.IsUnderAIControl)
						{
							unitModel.aiData.commander.RemoveUnit(unitModel);
							num++;
						}
					}
					Debug.Log("[UgcwAi] units retaken from UGCW AI: " + num);
				}
			}
			catch (Exception arg)
			{
				Debug.LogError("[UgcwAi] TakeControl: " + arg);
			}
		}

		// Token: 0x06001DDE RID: 7646 RVA: 0x000C70B8 File Offset: 0x000C52B8
		private static void TestMove()
		{
			try
			{
				UnitManager instance = MonoBehaviourSingleton<UnitManager>.instance;
				if (instance == null)
				{
					Debug.Log("[UgcwAi] TestMove: no UnitManager");
				}
				else
				{
					int num = 0;
					int num2 = 0;
					for (int i = 0; i < instance.unitsCount; i++)
					{
						UnitModel unitModel = instance.units[i];
						if (unitModel != null && unitModel.IsAlive && unitModel.side != RuntimeVars.playerSide && !unitModel.IsUnderAIControl && unitModel.kind == EUnitKind.Infantry)
						{
							num++;
							UnitModel unitModel2 = null;
							float num3 = float.MaxValue;
							for (int j = 0; j < instance.unitsCount; j++)
							{
								UnitModel unitModel3 = instance.units[j];
								if (unitModel3 != null && unitModel3.IsAlive && unitModel3.side == RuntimeVars.playerSide)
								{
									float sqrMagnitude = (unitModel3.PositionV2 - unitModel.PositionV2).sqrMagnitude;
									if (sqrMagnitude < num3)
									{
										num3 = sqrMagnitude;
										unitModel2 = unitModel3;
									}
								}
							}
							if (unitModel2 != null)
							{
								Vector2 vector = unitModel2.PositionV2 - unitModel.PositionV2;
								if (vector.sqrMagnitude >= 1f)
								{
									vector.Normalize();
									Vector2 pos = unitModel.PositionV2 + vector * 200f;
									TerrainController.instance.ClipWithWorldBounds(ref pos);
									Vector3 dir = new Vector3(vector.x, 0f, vector.y);
									unitModel.CancelActions();
									GOAP.Target.NavMeshPath target = GOAP.Target.NavMeshPath.Create(unitModel, pos.ConvertPos(), dir, true);
									Planner.instance.MovePlayerToTargetWithFire(unitModel, target, new OnActionCompleteDelegate(Runner.OnMoveDone), UnitsCollisionWithFire.Create(unitModel), unitModel.BaseSpeed);
									Debug.Log(string.Concat(new object[]
									{
										"[UgcwAi] ordre de mouvement: ",
										unitModel.id,
										" ",
										unitModel.name
									}));
									num2++;
								}
							}
						}
					}
					Debug.Log(string.Concat(new object[]
					{
						"[UgcwAi] TestMove: candidats=",
						num,
						" ordres=",
						num2
					}));
				}
			}
			catch (Exception arg)
			{
				Debug.LogError("[UgcwAi] TestMove: " + arg);
			}
		}

		// Token: 0x06001DDF RID: 7647 RVA: 0x000133D0 File Offset: 0x000115D0
		private static void OnMoveDone(UnitModel unit, bool isCanceled)
		{
			Debug.Log("[UgcwAi] move finished: " + unit.name + " cancelled=" + isCanceled.ToString());
		}

		// Token: 0x06001DE0 RID: 7648 RVA: 0x000C7314 File Offset: 0x000C5514
		private static void TogglePause()
		{
			try
			{
				BattleLogic instance = BattleLogic.instance;
				if (!(instance == null))
				{
					if (instance.GameSpeed > 0f)
					{
						Runner.lastSpeed = instance.GameSpeed;
						instance.GameSpeed = 0f;
					}
					else
					{
						instance.GameSpeed = Runner.lastSpeed;
					}
					Debug.Log("[UgcwAi] GameSpeed=" + instance.GameSpeed);
				}
			}
			catch (Exception arg)
			{
				Debug.LogError("[UgcwAi] TogglePause: " + arg);
			}
		}

		// Token: 0x06001DE2 RID: 7650 RVA: 0x000133FF File Offset: 0x000115FF
		private void OnGUI()
		{
			AiThoughtsPanel.Draw();
		}

		// Token: 0x04001C7C RID: 7292
		private float next;

		// Token: 0x04001C7D RID: 7293
		private static float lastSpeed = 1f;

		// Token: 0x04001C7E RID: 7294
		private float nextState;
	}
}
