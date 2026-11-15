"""0.1.4 WIP14: exchange of fire by ground, and the threats on the flanks of the line.

South Mountain (2026-11-14 09:14): in two 600 m squares of meadow and wheat east of the objective the AI lost
5,488 men against 498 enemy seen (11 to 1), while the player stood in forest. The 18 brigades sent there were all
server moves (120 replacements and 66 reserve commits between 45 and 130 min refilled the losing slots). Four
batteries were lost with no enemy seen within 600 two minutes before and no steady infantry within 520-1,700;
enemy brigades stood beyond the ends of the line in 44 states from 90 min on, with no warning in the prompt.

- ExchangeTracker: own losses and enemy losses seen over the last window_s, per sector of sector metres (an enemy
  loss is put in the sector of the nearest own unit). A sector is LOSING when own losses reach min_losses and are
  losing_ratio times the enemy losses seen there.
- A losing sector on open ground with better cover behind is a trap: no replacement, reserve or objective post
  goes into it, and its brigades are pulled back to the cover behind (pull_orders).
- exchange_lines / threat_lines: what the model reads (EXCHANGE BY GROUND, LOSING SECTORS, FLANK THREAT).
- flank_threats / refuse_flank_orders: enemy foot or horse beyond the end of the line, or near a battery with no steady
  brigade beside it; the nearest free healthy brigade refuses that flank, a lone battery falls back to the infantry.
"""
import math

from prompting import DEAD_STATUSES, nearest, split_units, unit_status

# Damage taken relative to grass, from the game's cover curve (UnitPreference.coverCurve minus the J&P correction,
# read from the game log on 2026-11-14). Road, scrub, mud and bridge are not measured: counted as grass.
COVER_FACTOR = {"Grass": 1.0, "Wheatfield": 0.63, "Forest": 0.49, "DenseForest": 0.46, "Fortifications": 0.42,
                "Water": 1.35, "Ford": 1.35, "Road": 1.0, "Scrub": 1.0, "Mud": 1.0, "Bridge": 1.0}
SHORT = {"Grass": "grass", "Wheatfield": "wheat", "Forest": "forest", "DenseForest": "dense forest",
         "Fortifications": "works", "Water": "water", "Ford": "ford", "Road": "road", "Scrub": "scrub",
         "Mud": "mud", "Bridge": "bridge"}

DEFAULT_EXCHANGE = {
    "enabled": True,
    "sector": 600.0,           # side of a sector, metres (South Mountain: hot zone flagged 74 of 89 states)
    "window_s": 600.0,         # losses counted over the last 10 minutes of battle
    "min_losses": 200.0,       # a sector is judged once you lost this many men there in the window
    "losing_ratio": 2.0,       # ...and LOSING when you lost this many times the enemy losses seen there
    "cover_search": 800.0,     # better cover looked for this far behind a brigade
    "better_cover": 0.8,       # "better" = a damage factor at most this share of the brigade's own ground
    "pull_back": True,         # brigades in a losing open sector go back to the cover behind them
    "pull_max_per_turn": 3,
    "pull_cooldown_s": 240.0,
    "contact": 500.0,          # a brigade is in contact (EXCHANGE BY GROUND) with an enemy this close
    "max_lines": 6,
    # flanks
    "force_by_sector": True,   # WIP15: FORCE BY SECTOR block in the prompt
    "flank_watch": True,
    "end_margin": 200.0,       # an enemy this far beyond the end of the line...
    "end_depth": 700.0,        # ...and at most this deep (from the line towards the enemy) is on the flank
    "battery_threat": 800.0,   # enemy foot or horse this close to a battery...
    "battery_guard": 300.0,    # ...with no steady infantry this close to it: the battery is exposed
    "refuse_flank": True,      # the nearest free healthy brigade is sent to face a flank threat
    "refuse_min_morale": 0.7,
    "refuse_max_distance": 1500.0,
    "refuse_gap": 170.0,
    "refuse_cooldown_s": 240.0,
    "battery_fallback": True,  # an exposed battery whose threat is still 350+ away falls back behind the infantry
    "battery_fallback_min": 350.0,
    "battery_fallback_cooldown_s": 300.0,
}


def _d(a, b):
    return math.hypot(a["x"] - b["x"], a["z"] - b["z"])


def ground_of(terrain, x, z):
    if terrain is None:
        return "Grass"
    try:
        return terrain.name_at(x, z) or "Grass"
    except Exception:
        return "Grass"


def factor(terrain, x, z):
    return COVER_FACTOR.get(ground_of(terrain, x, z), 1.0)


class ExchangeTracker:
    """Losses per sector over a sliding window. Call update(state) once per state message."""

    def __init__(self, cfg=None):
        self.cfg = {**DEFAULT_EXCHANGE, **(cfg or {})}
        self.reset()

    def reset(self):
        self.events = []        # (time, sector, own_lost, enemy_lost)
        self.prev = {}          # unit id -> (hp, x, z)
        self.pull_clock = {}

    def sector(self, x, z):
        s = float(self.cfg["sector"])
        return (int(math.floor(x / s)), int(math.floor(z / s)))

    def update(self, state):
        if not self.cfg["enabled"]:
            return
        now = float(state.get("time", 0.0))
        mine, foes = split_units(state)
        live_mine = [u for u in mine if u["kind"] in ("Infantry", "Cavalry", "Artillery", "Skirmish")]
        own_ids = {u["id"] for u in mine}
        for u in mine + foes:
            p = self.prev.get(u["id"])
            hp = float(u.get("hp", 0.0))
            if p and p[0] > hp:
                lost = p[0] - hp
                if u["id"] in own_ids:
                    self.events.append((now, self.sector(p[1], p[2]), lost, 0.0))
                elif live_mine:
                    near = min(live_mine, key=lambda m: math.hypot(m["x"] - p[1], m["z"] - p[2]))
                    if math.hypot(near["x"] - p[1], near["z"] - p[2]) <= 900.0:
                        self.events.append((now, self.sector(near["x"], near["z"]), 0.0, lost))
            self.prev[u["id"]] = (hp, u["x"], u["z"])
        horizon = now - float(self.cfg["window_s"])
        self.events = [e for e in self.events if e[0] >= horizon]

    def sums(self):
        out = {}
        for _, s, own, en in self.events:
            a = out.setdefault(s, [0.0, 0.0])
            a[0] += own
            a[1] += en
        return out

    def losing_sector(self, s, sums=None):
        own, en = (sums or self.sums()).get(s, (0.0, 0.0))
        return own >= float(self.cfg["min_losses"]) and own >= float(self.cfg["losing_ratio"]) * max(en, 1.0)

    def losing(self, x, z, sums=None):
        return self.cfg["enabled"] and self.losing_sector(self.sector(x, z), sums)

    def losing_sectors(self):
        sums = self.sums()
        return sorted(((s, v[0], v[1]) for s, v in sums.items() if self.losing_sector(s, sums)),
                      key=lambda t: -t[1])

    def centre(self, s):
        q = float(self.cfg["sector"])
        return ((s[0] + 0.5) * q, (s[1] + 0.5) * q)


def cover_behind(terrain, u, e, cfg):
    """Nearest passable spot up to cover_search behind u (away from e) whose ground takes at most better_cover
    times the damage of u's own ground; None if there is none."""
    if terrain is None:
        return None
    here = factor(terrain, u["x"], u["z"])
    dx, dz = u["x"] - e["x"], u["z"] - e["z"]
    n = math.hypot(dx, dz) or 1.0
    base = math.atan2(dz / n, dx / n)
    step = 100.0
    dist = step
    while dist <= float(cfg["cover_search"]) + 1e-6:
        best = None
        for deg in (0, -25, 25, -50, 50):
            a = base + math.radians(deg)
            x, z = u["x"] + math.cos(a) * dist, u["z"] + math.sin(a) * dist
            if hasattr(terrain, "passable") and not terrain.passable(x, z):
                continue
            f = factor(terrain, x, z)
            if f <= here * float(cfg["better_cover"]) and (best is None or (f, abs(deg)) < best[0]):
                best = ((f, abs(deg)), x, z)
        if best:
            return (round(best[1], 1), round(best[2], 1))
        dist += step
    return None


def is_trap(tracker, terrain, x, z, enemy, sums=None):
    """A losing sector where the spot is open ground and better cover lies behind it."""
    if tracker is None or not tracker.cfg["enabled"] or not tracker.losing(x, z, sums):
        return False
    if enemy is None:
        return True
    probe = {"x": x, "z": z}
    return cover_behind(terrain, probe, enemy, tracker.cfg) is not None


def pull_orders(state, terrain, orders, tracker, skip=(), pending_moves=None, plan_mode=None, stats=None):
    """Brigades standing in the open in a losing sector go back to the better cover behind them."""
    cfg = tracker.cfg
    if not (cfg["enabled"] and cfg["pull_back"]) or terrain is None or str(plan_mode or "").upper() == "ATTACK":
        return set(), []
    now = float(state.get("time", 0.0))
    mine, foes = split_units(state)
    live = [e for e in foes if unit_status(e) not in DEAD_STATUSES]
    if not live:
        return set(), []
    ordered = {o["id"] for o in orders if not o.get("auto")}   # the model's orders stand; the server's give way
    sums = tracker.sums()
    ids, out = set(), []
    for u in mine:
        if len(out) >= int(cfg["pull_max_per_turn"]):
            break
        if (u["kind"] != "Infantry" or u["id"] in skip or u["id"] in ordered or u["id"] in (pending_moves or {})
                or unit_status(u) != ""):
            continue
        if not tracker.losing(u["x"], u["z"], sums):
            continue
        if now - tracker.pull_clock.get(u["id"], -1e9) < float(cfg["pull_cooldown_s"]):
            continue
        near = nearest(u, live)
        if not near:
            continue
        spot = cover_behind(terrain, u, near[0], cfg)
        if spot is None:
            continue
        tracker.pull_clock[u["id"]] = now
        ids.add(u["id"])
        out.append({"cmd": "move", "id": u["id"], "x": spot[0], "z": spot[1],
                    "fx": round(near[0]["x"], 1), "fz": round(near[0]["z"], 1), "auto": True})
        if stats is not None:
            k = (f"brigades pulled out of a losing open sector to the cover behind "
                 f"(lost {cfg['losing_ratio']:g}+ to 1 there in 10 min)")
            stats[k] = stats.get(k, 0) + 1
    return ids, out


def exchange_lines(state, terrain, tracker):
    """EXCHANGE BY GROUND (the worst contacts) and LOSING SECTORS, for the model."""
    if tracker is None or not tracker.cfg["enabled"] or terrain is None:
        return []
    cfg = tracker.cfg
    mine, foes = split_units(state)
    live = [e for e in foes if e["kind"] in ("Infantry", "Skirmish", "Artillery") and unit_status(e) not in DEAD_STATUSES]
    rows = []
    for u in mine:
        if u["kind"] != "Infantry" or unit_status(u) in DEAD_STATUSES:
            continue
        near = nearest(u, live)
        if not near or near[1] > float(cfg["contact"]):
            continue
        e = near[0]
        gu, ge = ground_of(terrain, u["x"], u["z"]), ground_of(terrain, e["x"], e["z"])
        fu, fe = COVER_FACTOR.get(gu, 1.0), COVER_FACTOR.get(ge, 1.0)
        rows.append((fu / fe, u, e, gu, ge, fu, fe))
    lines = []
    bad = sorted((r for r in rows if r[0] >= 1.25), key=lambda r: -r[0])[:int(cfg["max_lines"])]
    if bad:
        lines.append("EXCHANGE BY GROUND (damage taken vs grass, game cover curve: grass 1, wheat 0.63, forest 0.49, "
                     "dense forest 0.46, works 0.42, water 1.35). Contacts where the ground is against you:")
        for ratio, u, e, gu, ge, fu, fe in bad:
            spot = cover_behind(terrain, u, e, cfg)
            tail = f"; better cover {math.hypot(spot[0] - u['x'], spot[1] - u['z']):.0f} behind" if spot else ""
            lines.append(f"- #{u['id']} {u['name']} on {SHORT.get(gu, gu)} ({fu:.2f}) vs #{e['id']} on "
                         f"{SHORT.get(ge, ge)} ({fe:.2f}): you lose about {ratio:.1f} to 1 at equal fire{tail}")
    losing = tracker.losing_sectors()[:3]
    if losing:
        lines.append("LOSING SECTORS (last 10 min; enemy losses counted only when seen): do not feed brigades into "
                     "them, fall back to the cover behind; the server sends no replacement or reserve there:")
        for s, own, en in losing:
            cx, cz = tracker.centre(s)
            here = [u for u in mine if tracker.sector(u["x"], u["z"]) == s and u["kind"] == "Infantry"]
            names = ", ".join(f"#{u['id']}" for u in here[:5]) or "none now"
            lines.append(f"- around ({cx:.0f}, {cz:.0f}): you lost {own:.0f}, enemy {en:.0f} seen; "
                         f"your brigades there: {names}")
    return lines


def _line_geometry(mine, foes):
    inf = [u for u in mine if u["kind"] == "Infantry" and unit_status(u) not in DEAD_STATUSES]
    enemy = [e for e in foes if e["kind"] in ("Infantry", "Cavalry") and unit_status(e) not in DEAD_STATUSES]
    if len(inf) < 2 or not enemy:
        return None
    mx = sum(u["x"] for u in inf) / len(inf)
    mz = sum(u["z"] for u in inf) / len(inf)
    ex = sum(e["x"] for e in enemy) / len(enemy)
    ez = sum(e["z"] for e in enemy) / len(enemy)
    ax = math.atan2(ez - mz, ex - mx)
    fx, fz = math.cos(ax), math.sin(ax)          # towards the enemy
    lx, lz = -fz, fx                             # along the line
    proj = sorted(((u["x"] - mx) * lx + (u["z"] - mz) * lz, u) for u in inf)
    return {"mx": mx, "mz": mz, "fx": fx, "fz": fz, "lx": lx, "lz": lz, "lo": proj[0], "hi": proj[-1],
            "inf": inf, "enemy": enemy}


def flank_threats(state, cfg=None):
    """[{kind: "end" | "battery", ...}]: enemy foot or horse beyond an end of the line, or near a lone battery."""
    cfg = {**DEFAULT_EXCHANGE, **(cfg or {})}
    if not cfg["flank_watch"]:
        return []
    mine, foes = split_units(state)
    g = _line_geometry(mine, foes)
    if g is None:
        return []
    out = []
    for sign, (p_end, end) in ((-1, g["lo"]), (1, g["hi"])):
        best = None
        for e in g["enemy"]:
            p = (e["x"] - g["mx"]) * g["lx"] + (e["z"] - g["mz"]) * g["lz"]
            depth = (e["x"] - g["mx"]) * g["fx"] + (e["z"] - g["mz"]) * g["fz"]
            beyond = (p - p_end) * sign
            if beyond > float(cfg["end_margin"]) and depth < float(cfg["end_depth"]):
                if best is None or _d(e, end) < _d(best[0], end):
                    best = (e, beyond)
        if best:
            out.append({"kind": "end", "sign": sign, "end": end, "enemy": best[0], "beyond": best[1],
                        "dist": _d(best[0], end)})
    steady = [u for u in g["inf"] if float(u.get("morale", 1.0)) >= 0.5]
    for b in mine:
        if b["kind"] != "Artillery" or unit_status(b) in DEAD_STATUSES:
            continue
        near = nearest(b, g["enemy"])
        if not near or near[1] > float(cfg["battery_threat"]):
            continue
        guard = min((_d(u, b) for u in steady), default=1e9)
        if guard > float(cfg["battery_guard"]):
            out.append({"kind": "battery", "battery": b, "enemy": near[0], "dist": near[1], "guard": guard})
    return out


def threat_lines(state, threats):
    lines = []
    for t in threats:
        e = t["enemy"]
        if t["kind"] == "end":
            lines.append(f"- #{e['id']} {e['name']} ({e['kind']}, {e['hp']:.0f} men) is {t['beyond']:.0f} beyond the "
                         f"end of your line at #{t['end']['id']} {t['end']['name']} ({t['dist']:.0f} from it): refuse "
                         "that flank (a brigade facing it beside the end, or a skirmish screen) before it turns it")
        else:
            b = t["battery"]
            lines.append(f"- battery #{b['id']} {b['name']}: enemy #{e['id']} ({e['kind']}) at {t['dist']:.0f}, no steady "
                         f"brigade within {t['guard']:.0f}: guard it with a brigade or pull it back behind the infantry")
    if lines:
        lines.insert(0, "FLANK THREAT (enemy round the end of your line or near a lone battery; the server sends the "
                        "nearest free brigade, you decide the rest):")
    return lines


def refuse_flank_orders(state, terrain, orders, threats, mem, skip=(), pending_moves=None, cfg=None, stats=None):
    """Refuse a threatened flank with the nearest free healthy brigade; a lone battery falls back to the infantry."""
    cfg = {**DEFAULT_EXCHANGE, **(cfg or {})}
    if not threats:
        return set(), []
    now = float(state.get("time", 0.0))
    mine, foes = split_units(state)
    live = [e for e in foes if unit_status(e) not in DEAD_STATUSES]
    ordered = {o["id"] for o in orders if not o.get("auto")}   # the model's orders stand; the server's give way
    ids, out = set(), []

    def free(u):
        return (u["kind"] == "Infantry" and u["id"] not in ordered and u["id"] not in ids and u["id"] not in skip
                and u["id"] not in (pending_moves or {}) and unit_status(u) == ""
                and float(u.get("morale", 1.0)) >= float(cfg["refuse_min_morale"])
                and (nearest(u, live) or (None, 1e9))[1] > 650.0)

    g = _line_geometry(mine, foes)
    for t in threats:
        e = t["enemy"]
        if t["kind"] == "end" and cfg["refuse_flank"] and g is not None:
            end = t["end"]
            key = ("end", t["sign"])
            if now - mem.get(key, -1e9) < float(cfg["refuse_cooldown_s"]):
                continue
            cands = [u for u in mine if free(u) and _d(u, end) <= float(cfg["refuse_max_distance"])]
            if not cands:
                if stats is not None:
                    k = "flank threat seen, no free brigade to refuse it"
                    stats[k] = stats.get(k, 0) + 1
                continue
            u = min(cands, key=lambda c: _d(c, end))
            # beside the end, turned towards the threat (half along the line, half back)
            gap = float(cfg["refuse_gap"])
            sx = end["x"] + g["lx"] * t["sign"] * gap * 0.7 - g["fx"] * gap * 0.7
            sz = end["z"] + g["lz"] * t["sign"] * gap * 0.7 - g["fz"] * gap * 0.7
            if terrain is not None and hasattr(terrain, "passable") and not terrain.passable(sx, sz):
                sx, sz = end["x"] - g["fx"] * gap, end["z"] - g["fz"] * gap
            mem[key] = now
            ids.add(u["id"])
            out.append({"cmd": "move", "id": u["id"], "x": round(sx, 1), "z": round(sz, 1),
                        "fx": round(e["x"], 1), "fz": round(e["z"], 1), "auto": True})
            if stats is not None:
                k = "flank refused: a free brigade sent beside the end of the line, facing the enemy round it"
                stats[k] = stats.get(k, 0) + 1
        elif t["kind"] == "battery" and cfg["battery_fallback"]:
            b = t["battery"]
            key = ("bat", b["id"])
            if (b["id"] in ordered or b["id"] in skip or b["id"] in (pending_moves or {})
                    or t["dist"] < float(cfg["battery_fallback_min"])
                    or now - mem.get(key, -1e9) < float(cfg["battery_fallback_cooldown_s"])):
                continue
            steady = [u for u in mine if u["kind"] == "Infantry" and unit_status(u) == ""
                      and float(u.get("morale", 1.0)) >= 0.5]
            if not steady:
                continue
            f = min(steady, key=lambda u: _d(u, b))
            if _d(f, b) > 1800.0:
                continue
            dx, dz = f["x"] - e["x"], f["z"] - e["z"]
            n = math.hypot(dx, dz) or 1.0
            sx, sz = f["x"] + dx / n * 150.0, f["z"] + dz / n * 150.0
            if terrain is not None and hasattr(terrain, "passable") and not terrain.passable(sx, sz):
                continue
            mem[key] = now
            ids.add(b["id"])
            out.append({"cmd": "move", "id": b["id"], "x": round(sx, 1), "z": round(sz, 1),
                        "fx": round(e["x"], 1), "fz": round(e["z"], 1), "auto": True})
            if stats is not None:
                k = "lone battery pulled back behind the infantry (enemy foot or horse near, no guard)"
                stats[k] = stats.get(k, 0) + 1
    return ids, out


def force_lines(state, cfg=None):
    """WIP15 FORCE BY SECTOR: your infantry and cavalry against the enemy seen, in the three thirds of your line
    (Crampton's Gap 18:15: 6,600 enemy men against 1,300 on one flank while 3-4 brigades waited on the other)."""
    cfg = {**DEFAULT_EXCHANGE, **(cfg or {})}
    if not cfg.get("force_by_sector", True):
        return []
    mine, foes = split_units(state)
    g = _line_geometry(mine, foes)
    if g is None:
        return []
    own = [u for u in mine if u["kind"] in ("Infantry", "Cavalry") and unit_status(u) not in DEAD_STATUSES]
    lo, hi = g["lo"][0], g["hi"][0]
    span = hi - lo
    if span < 300.0:
        return []
    def third(x, z):
        p = (x - g["mx"]) * g["lx"] + (z - g["mz"]) * g["lz"]
        return 0 if p < lo + span / 3 else (2 if p > hi - span / 3 else 1)
    sec = [{"own": [], "enemy": []} for _ in range(3)]
    for u in own:
        sec[third(u["x"], u["z"])]["own"].append(u)
    for e in g["enemy"]:
        sec[third(e["x"], e["z"])]["enemy"].append(e)
    names = [f"flank by #{g['lo'][1]['id']} {g['lo'][1]['name']}", "centre",
             f"flank by #{g['hi'][1]['id']} {g['hi'][1]['name']}"]
    men = lambda L: sum(float(x["hp"]) for x in L)
    lines = ["FORCE BY SECTOR (your infantry and cavalry vs the enemy seen, in the three thirds of your line):"]
    ratios = []
    for i, s in enumerate(sec):
        a, b = men(s["own"]), men(s["enemy"])
        r = b / a if a > 0 else (99.0 if b > 0 else 0.0)
        ratios.append(r)
        tag = (f": OUTNUMBERED {r:.1f} to 1" if r >= 1.5 else
               (f": you lead {a / b:.1f} to 1" if b > 0 and a / b >= 1.5 else ("" if b > 0 else ": no enemy seen")))
        lines.append(f"- {names[i]}: yours {len(s['own'])} units / {a:.0f} men vs {len(s['enemy'])} / {b:.0f}{tag}")
    worst = max(range(3), key=lambda i: ratios[i])
    best = min(range(3), key=lambda i: ratios[i])
    if ratios[worst] >= 1.5 and worst != best and ratios[best] <= 0.9 and len(sec[best]["own"]) >= 2:
        lines.append(f"  Shift a brigade from the {names[best]} to the {names[worst]} before that flank breaks; "
                     "keep one in reserve behind it.")
    return lines
