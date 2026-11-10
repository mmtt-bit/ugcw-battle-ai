using System;
using UnityEngine;

namespace UgcwAi
{
	// Token: 0x0200055B RID: 1371
	public static class Bootstrap
	{
		// Token: 0x06001DD9 RID: 7641 RVA: 0x000C6CE8 File Offset: 0x000C4EE8
		public static void Init()
		{
			if (GameObject.Find("UgcwAiRunner") != null)
			{
				return;
			}
			GameObject gameObject = new GameObject("UgcwAiRunner");
			UnityEngine.Object.DontDestroyOnLoad(gameObject);
			gameObject.AddComponent<Runner>();
			Bridge.Start("127.0.0.1", 8765);
			Debug.Log("[UgcwAi] loads");
		}
	}
}
