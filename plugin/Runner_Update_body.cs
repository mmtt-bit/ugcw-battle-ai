// Full body of Runner.Update() for 0.1.4-beta: replace the whole body of the method with this (it is the same
// code as in Runner.cs; the nextState and next fields are no longer used).
// Changes compared to 0.1.3:
//  - Commands.Tick() starts the next leg of the waypoint routes (without it a route stops at its first waypoint);
//  - Reflexes.Tick(Commands.Frozen): the reflexes stop only while the game is paused for a model call;
//  - the state is stamped "soft" (Commands.Stamp) and no longer pauses the game: the server sends "freeze"
//    before a model call; the time-out is Commands.TimedOut();
//  - the unit dump every 2 seconds is gone (it is written once when F9 is pressed, see TakeControl).
BattleResult.Init();   // hooks Unity's log once (safe to call every frame)
TerrainScan.Tick();    // describes the battlefield to the planner server (new battle or new connection)
BattleResult.Tick();   // sends battle_end when the game reports the mission result

if (Input.GetKeyDown(KeyCode.F9)) TakeControl();
if (Input.GetKeyDown(KeyCode.F7)) TestMove();
if (Input.GetKeyDown(KeyCode.F8)) TogglePause();
if (Input.GetKeyDown(KeyCode.F6)) AiThoughtsPanel.Visible = !AiThoughtsPanel.Visible;

Commands.Tick();                  // next legs of the waypoint routes
Reflexes.Tick(Commands.Frozen);   // fast reactions between two model calls (not while the game is paused for one)

string line;
int guard = 0;
while (guard++ < 20 && Bridge.TryReceive(out line)) Commands.Execute(line);

// Safety net: never leave the game waiting or frozen if the server stops answering
if (Commands.AwaitingPlan && (!Bridge.Connected || Commands.TimedOut()))
{
    Debug.LogWarning("[UgcwAi] Planner timeout or disconnect, resuming the game");
    Commands.EndPlan();
}

// Send a state only while the game is running, and never before Commands.NextPlanAt (game time). The server
// decides the delay: long before contact, shorter once the armies meet. The state does not pause the game:
// the server answers most states at once with its own orders and sends "freeze" when it calls the model.
if (Bridge.Connected && !Commands.AwaitingPlan && Time.time >= Commands.NextPlanAt
    && BattleLogic.instance != null && BattleLogic.instance.GameSpeed > 0f)
{
    string s = Snapshot.Build();
    if (s != null)
    {
        Bridge.Send(Commands.Stamp(s));
        Commands.BeginPlan();
    }
}
