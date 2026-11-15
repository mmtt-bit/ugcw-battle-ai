"""Minimal bridge test, without any model: sends one move order to the first infantry unit of the AI side.
Use it only to check that the plugin and the socket work; the real server is planner_server.py."""
import json
import socket

HOST, PORT = "127.0.0.1", 8765

srv = socket.socket()
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind((HOST, PORT))
srv.listen(1)
print(f"Test server waiting for the game on {HOST}:{PORT} (close the window to stop)")

while True:
    conn, addr = srv.accept()
    print("Game connected:", addr)
    f = conn.makefile("rw", encoding="utf-8", newline="\n")
    sent = False
    try:
        for line in f:
            try:
                msg = json.loads(line)
            except ValueError:
                print("Ignoring invalid line:", line[:80])
                continue

            if msg.get("type") == "state":
                units = msg["units"]
                print(f"state: {len(units)} units, t={msg['time']:.0f}s")
                if not sent:
                    cands = [u for u in units
                             if u["side"] != msg["playerSide"] and u["kind"] == "Infantry"]
                    if cands:
                        u = cands[0]
                        order = {"cmd": "move", "id": u["id"], "x": u["x"] + 150, "z": u["z"]}
                        f.write(json.dumps(order) + "\n")
                        f.flush()
                        print("order sent:", order)
                        sent = True
            else:
                print("event:", msg)
    except OSError as e:
        print("Connection lost:", e)
    finally:
        try:
            f.close()
        except OSError:
            pass
        conn.close()
    print("Game disconnected, waiting for a new connection...")
