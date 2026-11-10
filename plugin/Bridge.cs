using System;
using System.Collections.Generic;
using System.Net.Sockets;
using System.Text;
using System.Threading;

namespace UgcwAi
{
	// Token: 0x0200055D RID: 1373
	public static class Bridge
	{
		// Token: 0x06001DE3 RID: 7651 RVA: 0x000C73A0 File Offset: 0x000C55A0
		public static void Start(string host, int port)
		{
			if (Bridge.running)
			{
				return;
			}
			Bridge.running = true;
			new Thread(delegate()
			{
				Bridge.Loop(host, port);
			})
			{
				IsBackground = true
			}.Start();
		}

		// Token: 0x06001DE4 RID: 7652 RVA: 0x000C73F0 File Offset: 0x000C55F0
		public static void Send(string line)
		{
			object obj = Bridge.gate;
			lock (obj)
			{
				if (Bridge.outbox.Count > 50)
				{
					Bridge.outbox.Dequeue();
				}
				Bridge.outbox.Enqueue(line);
			}
		}

		// Token: 0x06001DE5 RID: 7653 RVA: 0x000C7448 File Offset: 0x000C5648
		public static bool TryReceive(out string line)
		{
			object obj = Bridge.gate;
			lock (obj)
			{
				if (Bridge.inbox.Count > 0)
				{
					line = Bridge.inbox.Dequeue();
					return true;
				}
			}
			line = null;
			return false;
		}

		// Token: 0x06001DE6 RID: 7654 RVA: 0x000C74A0 File Offset: 0x000C56A0
		private static void Loop(string host, int port)
		{
			while (Bridge.running)
			{
				TcpClient tcpClient = null;
				try
				{
					tcpClient = new TcpClient();
					tcpClient.Connect(host, port);
					tcpClient.NoDelay = true;
					NetworkStream stream = tcpClient.GetStream();
					Bridge.Connected = true;
					StringBuilder stringBuilder = new StringBuilder();
					byte[] array = new byte[4096];
					while (Bridge.running)
					{
						string text = null;
						object obj = Bridge.gate;
						lock (obj)
						{
							if (Bridge.outbox.Count > 0)
							{
								text = Bridge.outbox.Dequeue();
							}
						}
						if (text != null)
						{
							byte[] bytes = Encoding.UTF8.GetBytes(text + "\n");
							stream.Write(bytes, 0, bytes.Length);
						}
						else if (stream.DataAvailable)
						{
							int num = stream.Read(array, 0, array.Length);
							if (num <= 0)
							{
								break;
							}
							stringBuilder.Append(Encoding.UTF8.GetString(array, 0, num));
							int num2;
							while ((num2 = stringBuilder.ToString().IndexOf('\n')) >= 0)
							{
								string text2 = stringBuilder.ToString(0, num2).Trim();
								stringBuilder.Remove(0, num2 + 1);
								if (text2.Length > 0)
								{
									obj = Bridge.gate;
									lock (obj)
									{
										Bridge.inbox.Enqueue(text2);
									}
								}
							}
						}
						else
						{
							Thread.Sleep(10);
						}
					}
				}
				catch (Exception)
				{
				}
				finally
				{
					Bridge.Connected = false;
					if (tcpClient != null)
					{
						try
						{
							tcpClient.Close();
						}
						catch (Exception)
						{
						}
					}
				}
				Thread.Sleep(2000);
			}
		}

		// Token: 0x04001C7F RID: 7295
		private static readonly object gate = new object();

		// Token: 0x04001C80 RID: 7296
		private static readonly Queue<string> inbox = new Queue<string>();

		// Token: 0x04001C81 RID: 7297
		private static readonly Queue<string> outbox = new Queue<string>();

		// Token: 0x04001C82 RID: 7298
		private static volatile bool running;

		// Token: 0x04001C83 RID: 7299
		public static volatile bool Connected;
	}
}
