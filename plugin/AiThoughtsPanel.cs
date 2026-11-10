using UnityEngine;

namespace UgcwAi
{
    // Small text panel in the left edge of the screen, halfway up that shows the AI commander's latest thought:
    // plan mode, kill/death and a short version of its reasoning. Each new thought replaces the
    // previous one. It is drawn with Unity's immediate-mode GUI on top of everything, so it does not
    // touch the game's own interface. F6 shows or hides it.
    //
    // HOW TO USE (dnSpy, once):
    //   1. Add this class in the UgcwAi namespace, compile.
    //   2. Commands.cs: the "thought" branch is already in the file provided (replace Commands.Execute).
    //   3. In the Runner class (the one with Update), add a new method:
    //          private void OnGUI() { AiThoughtsPanel.Draw(); }
    //      and in Runner.Update add:   if (Input.GetKeyDown(KeyCode.F6)) AiThoughtsPanel.Visible = !AiThoughtsPanel.Visible;
    //   4. Compile, then File > Save Module.
    public static class AiThoughtsPanel
    {
        public static bool Visible = true;
        private static string mode = "";
        private static float kd = -1f;
        private static float time;
        private static string text = "";
        private static GUIStyle style;
        private static Texture2D background;

        // Panel size and distance from the screen corner (pixels at 1080p, scaled with the screen height).
        private const float Width = 460f;
        private const float Margin = 10f;
        // Vertical position on the left edge: 0 = top, 0.5 = middle, 1 = bottom.
        private const float VerticalPosition = 0.5f;

        public static void Set(string newMode, float newKd, float battleTime, string newText)
        {
            mode = newMode ?? "";
            kd = newKd;
            time = battleTime;
            text = newText ?? "";
        }

        public static void Draw()
        {
            if (!Visible || string.IsNullOrEmpty(text)) return;
            try
            {
                float k = Screen.height / 1080f;
                if (k < 0.7f) k = 0.7f;
                if (style == null)
                {
                    background = new Texture2D(1, 1);
                    background.SetPixel(0, 0, new Color(0f, 0f, 0f, 0.62f));
                    background.Apply();
                    style = new GUIStyle(GUI.skin.label);
                    style.wordWrap = true;
                    style.richText = true;
                    style.normal.textColor = Color.white;
                    style.normal.background = background;
                    style.alignment = TextAnchor.UpperLeft;
                    style.padding = new RectOffset(8, 8, 6, 6);
                }
                style.fontSize = Mathf.RoundToInt(14f * k);
                string head = "<b>AI COMMANDER</b>  " + (mode.Length > 0 ? "[" + mode + "]  " : "")
                              + (kd >= 0f ? "kill/death " + kd.ToString("0.00") + "  " : "")
                              + "(" + Mathf.FloorToInt(time / 60f) + " min)";
                string body = head + "\n" + text;
                float w = Width * k;
                float h = style.CalcHeight(new GUIContent(body), w);
                GUI.depth = -1000;
                GUI.Label(new Rect(Margin * k, (Screen.height - h) * VerticalPosition, w, h), body, style);
            }
            catch (System.Exception) { }
        }
    }
}
