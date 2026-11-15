"""0.1.4 WIP16: the ASSAULT COLUMN, a macro command of the model executed by the server in llm_plus mode.

Thoroughfare Gap (2026-11-15 11:42, llm_plus): at 36-47 min the AI had 15,800 men against 10,300 seen, yet never
more than 4 brigades within 900 of the Gap; one melee in three hours. The game's own AI on the same map (dry run,
2026-11-13 14:31) closed in from 4-6 directions with 4-7 brigades within 900, 13 melees in the hour, took the Gap
at 62 min. Marc's design: gather a large force (about 80 % of the infantry), one or two brigades in front to take
the fire, the charging brigades behind; advance so that all arrive together; at 500-600 from the objective every
unit charges except the exhausted; prepare with the guns when the advantage is not certain; skirmishers on the
flanks, cavalry behind for the exploitation. Several approach points split the column into groups that arrive
together from several sides (envelopment).

The model sends, in its answer:
  "assault_column": {"objective": "<name>" | [x, z], "from": [x, z] | [[x, z], [x, z]], "go": true}
  "assault_column": {"cancel": true}
Phases: gather (out of range, in two ranks per group) -> advance (step by step, every group on the same line, the
next step only when the units have closed up) -> prepare (at the charge line, fire until the zone verdict is GO,
for at most prepare_max_s) -> charge (every unit with morale and stamina 0.5+ charges the nearest enemy) -> done.
Cancelled by the model, when the column's average morale drops under cancel_morale, or when the zone count stays
TOO FEW / RECONSIDER for too long at the charge line: the column then falls back to its gather line.
"""
import math

from prompting import DEAD_STATUSES, charge_zone, split_units, unit_status

DEFAULT_COLUMN = {
    "enabled": True,
    "share": 0.8,               # share of the fit infantry taken into the column (the rest is the reserve)
    "fit_morale": 0.6,          # a brigade is fit for the column with this morale...
    "fit_stamina": 0.5,         # ...and this stamina
    "gather_distance": 1250.0,  # front rank of the gather line, from the objective (out of rifle range)
    "rank_gap": 160.0,          # the charging rank stands this far behind the front rank
    "file_gap": 190.0,          # brigades side by side this far apart
    "screen_count": 1,          # brigades in the front rank per group (2 for groups of 6 or more)
    "gather_ready": 0.8,        # share of the units within gather_tolerance of their spot to start the advance
    "gather_tolerance": 160.0,
    "gather_timeout_s": 720.0,  # the advance starts after this even if some are late
    "step": 150.0,              # the column advances by this much per step
    "step_ready": 0.8,          # share of the units within step_tolerance of the current step line to go on
    "step_tolerance": 120.0,
    "step_timeout_s": 150.0,    # a step is forced after this
    "charge_distance": 550.0,   # the front rank's line when the charge is judged (500-600 from the objective)
    "prepare_max_s": 300.0,     # fire at most this long at the charge line before deciding
    "charge_min_morale": 0.5,   # units under this morale or stamina do not charge (they hold)
    "charge_min_stamina": 0.5,
    "cancel_morale": 0.45,      # the column's average morale under this: cancelled, back to the gather line
    "cancel_wait_s": 180.0,     # TOO FEW or RECONSIDER this long at the charge line: cancelled
    "skirmish_out": 260.0,      # skirmishers this far out on each flank of the front rank
    "cavalry_back": 450.0,      # cavalry this far behind the charging rank
    "battery_line": 1100.0,     # batteries of the column this far from the objective, on the flanks
}


def _d(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _xz(u):
    return (u["x"], u["z"])


def objective_point(spec, state):
    """(name, x, z) of the objective named or given as [x, z]; None if not found."""
    if isinstance(spec, (list, tuple)) and len(spec) >= 2:
        try:
            return ("point", float(spec[0]), float(spec[1]))
        except (TypeError, ValueError):
            return None
    name = str(spec or "").strip().lower()
    for o in state.get("objectives") or []:
        if name and name in (str(o.get("name") or "").lower(), str(o.get("id") or "").lower()):
            return (o.get("name"), float(o["x"]), float(o["z"]))
    objs = state.get("objectives") or []
    if not name and len(objs) == 1:
        o = objs[0]
        return (o.get("name"), float(o["x"]), float(o["z"]))
    return None


def parse_directive(data):
    """The cleaned "assault_column" of an answer dict, or None when absent."""
    raw = data.get("assault_column") if isinstance(data, dict) else None
    if not isinstance(raw, dict):
        return None
    if raw.get("cancel"):
        return {"cancel": True}
    out = {"objective": raw.get("objective"), "go": bool(raw.get("go", True))}
    pts = raw.get("from")
    froms = []
    if isinstance(pts, (list, tuple)) and pts:
        if isinstance(pts[0], (list, tuple)):
            cand = pts[:3]
        else:
            cand = [pts]
        for p in cand:
            try:
                froms.append([float(p[0]), float(p[1])])
            except (TypeError, ValueError, IndexError):
                pass
    out["from"] = froms
    return out


def fit(u, cfg):
    return (u["kind"] == "Infantry" and unit_status(u) == "" and u["morale"] >= float(cfg["fit_morale"])
            and float(u.get("fatigue", 1.0)) >= float(cfg["fit_stamina"]))


class AssaultColumn:
    """One running column (or none)."""

    def __init__(self, cfg=None):
        self.cfg = {**DEFAULT_COLUMN, **(cfg or {})}
        self.reset()

    def reset(self):
        self.active = None       # dict while a column runs
        self.last = None         # short text of how the last column ended

    # ---- starting and stopping -------------------------------------------------------------------------------
    def command(self, directive, state):
        """Apply the model's directive. Returns a text for the server log."""
        if directive is None or not self.cfg["enabled"]:
            return ""
        if directive.get("cancel"):
            if self.active:
                self._end(state, "cancelled by you")
                return "Assault column cancelled by the model"
            return ""
        if self.active and not directive.get("go", True):
            return ""
        obj = objective_point(directive.get("objective"), state)
        if obj is None:
            return f"Assault column ignored: objective {directive.get('objective')!r} not found"
        if self.active and self.active["objective"][0] == obj[0] and \
                [g["from"] for g in self.active["groups"]] == (directive.get("from") or [g["from"] for g in self.active["groups"]]):
            return ""                                   # the same column, already running
        mine, foes = split_units(state)
        o = (obj[1], obj[2])
        froms = directive.get("from") or []
        if not froms:
            # straight from the army's centre
            inf = [u for u in mine if u["kind"] == "Infantry" and unit_status(u) not in DEAD_STATUSES]
            if not inf:
                return "Assault column ignored: no infantry"
            cx = sum(u["x"] for u in inf) / len(inf)
            cz = sum(u["z"] for u in inf) / len(inf)
            froms = [[cx, cz]]
        cands = sorted((u for u in mine if fit(u, self.cfg)), key=lambda u: _d(_xz(u), o))
        n = max(1, int(round(len([u for u in mine if u["kind"] == "Infantry"
                                  and unit_status(u) not in DEAD_STATUSES]) * float(self.cfg["share"]))))
        chosen = cands[:n]
        if len(chosen) < 2 * len(froms):
            return f"Assault column ignored: only {len(chosen)} fit brigades for {len(froms)} approach(es)"
        groups = [{"from": f, "inf": [], "skirm": [], "cav": [], "guns": []} for f in froms]
        dirs = []
        for f in froms:
            dx, dz = f[0] - o[0], f[1] - o[1]
            nn = math.hypot(dx, dz) or 1.0
            dirs.append((dx / nn, dz / nn))
        # each brigade to the group whose approach line is nearest, keeping the groups balanced
        for u in sorted(chosen, key=lambda u: -float(u["hp"])):
            order = sorted(range(len(groups)), key=lambda i: _d(_xz(u), (o[0] + dirs[i][0] * 1250,
                                                                     o[1] + dirs[i][1] * 1250)))
            cap = math.ceil(len(chosen) / len(groups))
            for i in order:
                if len(groups[i]["inf"]) < cap:
                    groups[i]["inf"].append(u["id"])
                    break
        taken = {u["id"] for u in chosen}
        for u in mine:
            if u["id"] in taken or unit_status(u) in DEAD_STATUSES:
                continue
            gi = min(range(len(groups)), key=lambda i: _d(_xz(u), (o[0] + dirs[i][0] * 1250, o[1] + dirs[i][1] * 1250)))
            if u["kind"] == "Skirmish" and len(groups[gi]["skirm"]) < 2:
                groups[gi]["skirm"].append(u["id"])
            elif u["kind"] == "Cavalry" and len(groups[gi]["cav"]) < 2:
                groups[gi]["cav"].append(u["id"])
            elif u["kind"] == "Artillery" and len(groups[gi]["guns"]) < 2:
                groups[gi]["guns"].append(u["id"])
        now = float(state.get("time", 0.0))
        for g, dd in zip(groups, dirs):
            g["dir"] = dd
            by_id = {u["id"]: u for u in mine}
            # the front rank: the biggest brigades (they take the fire)
            screens = 2 if len(g["inf"]) >= 6 else int(self.cfg["screen_count"])
            ranked = sorted(g["inf"], key=lambda i: -float(by_id[i]["hp"]))
            g["front"] = ranked[:screens]
            g["back"] = ranked[screens:]
        self.active = {"objective": obj, "groups": groups, "phase": "gather", "since": now, "line": None,
                       "start": now, "charged": []}
        return (f"Assault column on {obj[0]}: {len(chosen)} brigades in {len(groups)} group(s), gathering at "
                f"{self.cfg['gather_distance']:.0f}")

    def _end(self, state, why):
        a = self.active
        self.active = None
        self.last = f"{why} at {float(state.get('time', 0.0)) / 60:.0f} min" + (f" (on {a['objective'][0]})" if a else "")

    def members(self):
        if not self.active:
            return set()
        out = set()
        for g in self.active["groups"]:
            out |= set(g["inf"]) | set(g["skirm"]) | set(g["cav"]) | set(g["guns"])
        return out

    # ---- geometry ----------------------------------------------------------------------------------------------
    def _spots(self, g, dist, live_ids):
        """{unit id: (x, z, facing_x, facing_z)} with the front rank at dist from the objective."""
        o = (self.active["objective"][1], self.active["objective"][2])
        dx, dz = g["dir"]
        px, pz = -dz, dx                                  # along the rank
        fg, rg = float(self.cfg["file_gap"]), float(self.cfg["rank_gap"])
        spots = {}

        def rank(ids, d):
            ids = [i for i in ids if i in live_ids]
            for k, i in enumerate(ids):
                off = (k - (len(ids) - 1) / 2.0) * fg
                spots[i] = (o[0] + dx * d + px * off, o[1] + dz * d + pz * off, o[0], o[1])
            return len(ids)

        nf = rank(g["front"], dist)
        nb = rank(g["back"], dist + rg)
        half = (max(nf, nb) - 1) / 2.0 * fg + float(self.cfg["skirmish_out"])
        sk = [i for i in g["skirm"] if i in live_ids]
        for k, i in enumerate(sk):
            side = -1 if k % 2 == 0 else 1
            spots[i] = (o[0] + dx * dist + px * side * half, o[1] + dz * dist + pz * side * half, o[0], o[1])
        cv = [i for i in g["cav"] if i in live_ids]
        for k, i in enumerate(cv):
            off = (k - (len(cv) - 1) / 2.0) * fg
            d = dist + rg + float(self.cfg["cavalry_back"])
            spots[i] = (o[0] + dx * d + px * off, o[1] + dz * d + pz * off, o[0], o[1])
        gn = [i for i in g["guns"] if i in live_ids]
        for k, i in enumerate(gn):
            side = -1 if k % 2 == 0 else 1
            d = max(float(self.cfg["battery_line"]), dist + rg)
            spots[i] = (o[0] + dx * d + px * side * (half - 60), o[1] + dz * d + pz * side * (half - 60), o[0], o[1])
        return spots

    # ---- each state --------------------------------------------------------------------------------------------
    def orders(self, state, model_orders, terrain=None, stats=None):
        """(ids taken over, orders) for this state. Model orders for column members are replaced, except
        fallback (a broken brigade may always step back)."""
        a = self.active
        if not a:
            return set(), []
        now = float(state.get("time", 0.0))
        mine, foes = split_units(state)
        by_id = {u["id"]: u for u in mine if unit_status(u) not in DEAD_STATUSES}
        live_ids = set(by_id)
        members = [i for i in self.members() if i in live_ids]
        inf = [by_id[i] for g in a["groups"] for i in g["inf"] if i in live_ids]
        if len(inf) < 2:
            self._end(state, "dissolved (too few brigades left)")
            return set(), []
        avg = sum(u["morale"] for u in inf) / len(inf)
        o = (a["objective"][1], a["objective"][2])

        def bump(k):
            if stats is not None:
                stats[k] = stats.get(k, 0) + 1

        if avg < float(self.cfg["cancel_morale"]) and a["phase"] != "charge":
            back = self._back(state, members, by_id)
            self._end(state, f"cancelled: the column's morale fell to {avg:.2f}")
            bump("assault columns cancelled (morale)")
            return back
        keep = {o_["id"] for o_ in model_orders if o_["cmd"] == "fallback"}
        take = [i for i in members if i not in keep]
        out = []

        def to_spots(dist, allow_fire=False):
            res = []
            reached = total = 0
            for g in a["groups"]:
                for i, (x, z, fx, fz) in self._spots(g, dist, live_ids).items():
                    if i in keep:
                        continue
                    u = by_id[i]
                    total += 1 if u["kind"] == "Infantry" else 0
                    near = math.hypot(u["x"] - x, u["z"] - z)
                    if u["kind"] == "Infantry" and near <= float(self.cfg["step_tolerance"]):
                        reached += 1
                    if u["kind"] == "Artillery" and allow_fire:
                        tgt = min(foes, key=lambda e: _d(_xz(e), o), default=None)
                        if tgt is not None and near <= 200:
                            res.append({"cmd": "range_attack", "id": i, "target": tgt["id"], "auto": True})
                            continue
                    if near > 40:
                        res.append({"cmd": "move", "id": i, "x": round(x, 1), "z": round(z, 1),
                                    "fx": round(fx, 1), "fz": round(fz, 1), "auto": True})
            return res, reached, total

        if a["phase"] == "gather":
            res, reached, total = to_spots(float(self.cfg["gather_distance"]), allow_fire=True)
            ready = total and reached / total >= float(self.cfg["gather_ready"])
            if ready or now - a["since"] >= float(self.cfg["gather_timeout_s"]):
                a["phase"], a["since"], a["line"] = "advance", now, float(self.cfg["gather_distance"])
                bump("assault columns gathered and advancing")
            out += res
        if a["phase"] == "advance":
            res, reached, total = to_spots(a["line"], allow_fire=True)
            closed = total and reached / total >= float(self.cfg["step_ready"])
            if closed or now - a["since"] >= float(self.cfg["step_timeout_s"]):
                nxt = max(float(self.cfg["charge_distance"]), a["line"] - float(self.cfg["step"]))
                if a["line"] <= float(self.cfg["charge_distance"]):
                    a["phase"], a["since"] = "prepare", now
                else:
                    a["line"], a["since"] = nxt, now
                    res, _, _ = to_spots(a["line"], allow_fire=True)
                    bump("assault column steps (every group on the same line)")
            out += res
        if a["phase"] == "prepare":
            zone = self.zone(state)
            if zone["verdict"] == "GO" or now - a["since"] >= float(self.cfg["prepare_max_s"]) and \
                    zone["own"] >= 0.75 * zone["enemy"]:
                a["phase"] = "charge"
            elif zone["verdict"] in ("TOO FEW", "RECONSIDER") and now - a["since"] >= float(self.cfg["cancel_wait_s"]):
                back = self._back(state, members, by_id)
                self._end(state, f"cancelled at the charge line: {zone['verdict']} "
                                 f"({zone['own']:.0f} vs {zone['enemy']:.0f} men)")
                bump("assault columns cancelled (zone count)")
                return back
            else:
                # fire: the front rank and the guns shoot, the charging rank holds
                for g in a["groups"]:
                    for i in g["front"]:
                        if i in live_ids and i not in keep:
                            u = by_id[i]
                            tgt = min(foes, key=lambda e: math.hypot(e["x"] - u["x"], e["z"] - u["z"]), default=None)
                            if tgt is not None:
                                out.append({"cmd": "range_attack", "id": i, "target": tgt["id"], "auto": True})
                    for i in g["back"]:
                        if i in live_ids and i not in keep:
                            out.append({"cmd": "hold", "id": i, "auto": True})
                    for i in g["guns"]:
                        if i in live_ids and i not in keep:
                            tgt = min(foes, key=lambda e: _d(_xz(e), o), default=None)
                            if tgt is not None:
                                out.append({"cmd": "range_attack", "id": i, "target": tgt["id"], "auto": True})
                bump("assault column preparing by fire at the charge line")
        if a["phase"] == "charge":
            live_foes = [e for e in foes if unit_status(e) not in DEAD_STATUSES and e["kind"] != "General"]
            n = 0
            for g in a["groups"]:
                for i in g["front"] + g["back"] + g["cav"]:
                    if i not in live_ids or i in keep:
                        continue
                    u = by_id[i]
                    if u["morale"] < float(self.cfg["charge_min_morale"]) or \
                            float(u.get("fatigue", 1.0)) < float(self.cfg["charge_min_stamina"]):
                        out.append({"cmd": "hold", "id": i, "auto": True})
                        continue
                    tgt = min(live_foes, key=lambda e: math.hypot(e["x"] - u["x"], e["z"] - u["z"]), default=None)
                    if tgt is None:
                        continue
                    out.append({"cmd": "charge", "id": i, "target": tgt["id"], "auto": True})
                    n += 1
            bump("assault column general charges")
            if stats is not None:
                stats["brigades charging in an assault column"] = stats.get("brigades charging in an assault column", 0) + n
            self._end(state, f"charged with {n} units")
        ids = {o_["id"] for o_ in out}
        return ids | set(take), out

    def _back(self, state, members, by_id):
        """On a cancel (called before the column is cleared): every member back to its gather spot."""
        out = []
        for g in self.active["groups"]:
            for i, (x, z, fx, fz) in self._spots(g, float(self.cfg["gather_distance"]), set(by_id)).items():
                out.append({"cmd": "move", "id": i, "x": round(x, 1), "z": round(z, 1),
                            "fx": round(fx, 1), "fz": round(fz, 1), "auto": True})
        return {o["id"] for o in out}, out

    def zone(self, state):
        """The zone count of charge_zone for the defenders (enemy within 600 of the objective, their morale, fresh
        reserves), with YOUR side counted as the whole column at the charge line (its charging rank stands 160
        behind the front rank, so beyond 600 of the objective)."""
        from prompting import BROKEN_ZONE_MORALE, BROKEN_ZONE_RATIO, CHARGE_ZONE_MORALE, CHARGE_ZONE_RATIO, \
            NO_CHARGE_MORALE
        a = self.active
        mine, foes = split_units(state)
        o = {"x": a["objective"][1], "z": a["objective"][2], "kind": "Point", "hp": 0, "morale": 0.0, "id": -1}
        z = charge_zone(o, mine, foes)
        reach = float(self.cfg["charge_distance"]) + float(self.cfg["rank_gap"]) + 150.0
        ids = self.members()
        own = sum(float(u["hp"]) for u in mine if u["id"] in ids and u["kind"] in ("Infantry", "Cavalry")
                  and unit_status(u) not in DEAD_STATUSES and u["morale"] >= NO_CHARGE_MORALE
                  and math.hypot(u["x"] - o["x"], u["z"] - o["z"]) <= reach)
        z["own"] = max(z["own"], own)
        need = BROKEN_ZONE_RATIO if (z["enemy"] > 0 and z["morale"] < BROKEN_ZONE_MORALE) else CHARGE_ZONE_RATIO
        if z["own"] < need * z["enemy"]:
            z["verdict"] = "TOO FEW"
        elif z["reserves"]:
            z["verdict"] = "RECONSIDER"
        elif z["enemy"] > 0 and z["morale"] >= CHARGE_ZONE_MORALE:
            z["verdict"] = "PREPARE"
        else:
            z["verdict"] = "GO"
        return z

    # ---- what the model reads ----------------------------------------------------------------------------------
    def lines(self, state, offer=None):
        out = []
        a = self.active
        if a:
            mine, _ = split_units(state)
            live = {u["id"] for u in mine if unit_status(u) not in DEAD_STATUSES}
            desc = []
            for g in a["groups"]:
                desc.append(f"from ({g['from'][0]:.0f}, {g['from'][1]:.0f}): front "
                            + ", ".join(f"#{i}" for i in g["front"] if i in live)
                            + "; charging rank " + (", ".join(f"#{i}" for i in g["back"] if i in live) or "none"))
            line = f", front rank {a['line']:.0f} from it" if a.get("line") else ""
            out.append(f"ASSAULT COLUMN on {a['objective'][0]}: phase {a['phase'].upper()}{line}. Groups: "
                       + " | ".join(desc) + ". The server moves these units; send \"assault_column\": "
                       "{\"cancel\": true} to stop it. A fallback order of yours still applies.")
        elif self.last:
            out.append(f"ASSAULT COLUMN: the last one ended ({self.last}).")
        if offer and not a:
            out.append(offer)
        return out


def column_offer(state, cfg=None):
    """An ASSAULT COLUMN suggestion when the objective is the enemy's, the fit infantry outnumbers the enemy seen
    within 1,200 of it by 1.5 to 1 or more, and at least 4 brigades are fit."""
    cfg = {**DEFAULT_COLUMN, **(cfg or {})}
    me = "North" if state.get("playerSide") == "South" else "South"
    mine, foes = split_units(state)
    fitb = [u for u in mine if fit(u, cfg)]
    if len(fitb) < 4:
        return None
    best = None
    for o in state.get("objectives") or []:
        if str(o.get("side")) == me:
            continue
        p = (float(o["x"]), float(o["z"]))
        enemy = sum(float(e["hp"]) for e in foes if e["kind"] in ("Infantry", "Cavalry")
                    and unit_status(e) not in DEAD_STATUSES and _d(_xz(e), p) <= 1200.0)
        own = sum(float(u["hp"]) for u in fitb) * float(cfg["share"])
        if enemy <= 0 or own / enemy >= 1.5:
            r = own / enemy if enemy > 0 else 99.0
            if best is None or r > best[0]:
                best = (r, o, own, enemy)
    if not best:
        return None
    r, o, own, enemy = best
    return (f"ASSAULT COLUMN possible on {o.get('name')}: {int(len(fitb) * float(cfg['share']) + 0.5)} fit brigades "
            f"(about {own:.0f} men) against {enemy:.0f} enemy men seen within 1200 of it"
            + (f" ({r:.1f} to 1)" if r < 99 else "") + ". Send \"assault_column\": {\"objective\": \""
            + str(o.get("name")) + "\", \"from\": [[x, z], [x, z]], \"go\": true} with one approach point (or two or "
            "three for an envelopment) on the sides to come from.")


def reinforcement_lines(state, arrived, window_s=1800.0, apart=800.0, enemy_near=1000.0):
    """WIP16 REINFORCEMENTS: brigades of yours that arrived during the battle (arrived: id -> battle time first
    seen) and stand apart from the army with the enemy near (Thoroughfare Gap 2026-11-15: Law 1st and 2nd arrived
    1,550 behind the line at 66 min, faced 3-5 enemy brigades alone and were captured while 5 fresh brigades were
    out of contact)."""
    now = float(state.get("time", 0.0))
    mine, foes = split_units(state)
    live = [u for u in mine if unit_status(u) not in DEAD_STATUSES]
    inf = [u for u in live if u["kind"] == "Infantry"]
    enemy = [e for e in foes if e["kind"] in ("Infantry", "Cavalry") and unit_status(e) not in DEAD_STATUSES]
    new = [u for u in inf if u["id"] in arrived and now - arrived[u["id"]] <= window_s]
    new_ids = {u["id"] for u in new}
    rows = []
    for u in new:
        others = [x for x in inf if x["id"] not in new_ids]
        if not others:
            continue
        df = min(_d(_xz(x), _xz(u)) for x in others)
        if df < apart:
            continue
        near = [e for e in enemy if _d(_xz(e), _xz(u)) <= enemy_near]
        if not near:
            continue
        free = [x for x in others if x["morale"] >= 0.8 and unit_status(x) == ""
                and all(_d(_xz(e), _xz(x)) > 700.0 for e in enemy)]
        rows.append(f"- #{u['id']} {u['name']} ({u['hp']:.0f} men, morale {u['morale']:.2f}) arrived "
                    f"{(now - arrived[u['id']]) / 60:.0f} min ago, {df:.0f} from your army, "
                    f"{len(near)} enemy brigade(s) ({sum(float(e['hp']) for e in near):.0f} men) within "
                    f"{enemy_near:.0f}; fresh brigades of yours out of contact: "
                    + (", ".join(f"#{x['id']}" for x in free[:4]) or "none"))
    if rows:
        rows.insert(0, "REINFORCEMENTS cut off from the army (decide this turn: join them with one or two fresh "
                       "brigades, strike the same enemy together from both sides as a pincer, or pull them back "
                       "to the army; never leave them alone):")
    return rows
