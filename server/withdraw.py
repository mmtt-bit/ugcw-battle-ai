"""Tactical withdrawal, preservation, rest and battery escape (0.1.4 WIP8, from the battle of 2026-11-12 13:24).

What that battle measured (Cold Harbor, 12,800 men against 15,000 to 20,000 seen):
- Morale only comes back away from the enemy: -0.031 a minute within 500 of the nearest enemy, +0.021 a minute
  between 500 and 800. Men lost: 9.7 a minute within 500, 2.3 beyond.
- The 181 fallback orders moved the brigades 51 m (median): the nearest enemy went from 440 to 475 m and 61 % of
  them were still within 500. A fallback is a step back by hand, not a withdrawal; the brigades never recovered and
  the player could fire on one brigade at a time while the others were too weak to threaten him.
- The batteries "stepped back" by hand when the enemy closed in and were overrun (Hardaway, Jones).

Three answers, by scale:
1. REST: a brigade relieved by the server (relief.py) that is no longer in melee walks to a rest spot at least
   `rest_distance` from every visible enemy, behind the line, in cover when there is some, and stays there until
   its morale is back.
2. WITHDRAW (tactical withdrawal): outnumbered and the line failing (half of the brigades in contact shaken), the
   army breaks contact: every brigade but a rearguard goes to a rally line `rally_distance` from the enemy; the
   rearguard (skirmishers, cavalry, the freshest brigade) holds cover between the two, fires, and falls back to the
   rally line when the enemy is close. It ends when the withdrawn brigades have their morale back, or after
   `withdraw_max_s`.
3. PRESERVE (battle lost): the player holds the objectives the result needs, the casualty race is lost and the
   force ratio is bad: the same withdrawal, to a rally area far from the enemy, kept for the rest of the battle;
   only shaken or isolated enemy units are engaged. The army is kept for the next battle of the campaign.
"""
import math

from supply import DEAD_STATUSES, nearest, split_units, unit_status

DEFAULT_WITHDRAW = {
    "enabled": True,
    # rest of relieved brigades
    "rest": True,
    "rest_distance": 700.0,          # a resting brigade stands at least this far from every visible enemy
    "rest_morale": 0.65,             # ...until its morale is back to this
    # tactical withdrawal
    "withdraw": True,
    "withdraw_ratio": 0.7,           # force ratio under which a failing line withdraws
    "withdraw_shaken_share": 0.5,    # share of the brigades in contact under `shaken_morale` that makes the line "failing"
    "shaken_morale": 0.5,
    "withdraw_min_contact": 3,       # at least this many brigades in contact
    "withdraw_end_morale": 0.6,      # the withdrawal ends when the withdrawn brigades average this morale...
    "withdraw_max_s": 600.0,         # ...or after this long
    "withdraw_cooldown_s": 300.0,    # and cannot start again before this long
    # preservation
    "preserve": True,
    "preserve_ratio": 0.6,           # force ratio under which a lost battle is preserved
    "preserve_kd": 1.0,              # ...with the estimated kill ratio under this
    "preserve_minute": 25.0,         # ...not before this minute
    "preserve_resume_ratio": 1.0,    # it ends only above this force ratio
    # geometry
    "rally_distance": 900.0,         # rally line: at least this far from every visible enemy
    "edge_margin": 150.0,            # ...and this far inside the map
    "spacing": 170.0,
    "rearguard": 2,                  # units kept between the enemy and the rally line
    "rearguard_min_morale": 0.55,
    "rearguard_release": 250.0,      # the rearguard falls back to the rally line with an enemy this close
    "disengage": 250.0,              # a unit with an enemy closer than this first gets a fallback, then the move
    "reissue_shift": 200.0,          # a new rally spot is sent only when it moves more than this
    "rally_keep_s": 240.0,           # the rally point is kept this long...
    "rally_threat_share": 0.6,       # ...unless an enemy comes within this share of rally_distance of it
    "withdraw_min_s": 150.0,         # a withdrawal lasts at least this long
    # 0.1.4 WIP10: withdrawal by bounds (2026-11-13: the army ran back for the whole of phase 2, pursued, never
    # rested and never fired back: 5,937 men lost for 1,601 seen)
    "bounds": True,
    "bound_arrive_share": 0.7,       # the main body "stands" when this share of the line is at its spots...
    "bound_arrive_s": 300.0,         # ...or after this long
    "bound_min_stand_s": 60.0,       # a line stands at least this long before the next bound
    "pressed_close": 200.0,          # the line is pressed: a third of it with an enemy this close...
    "pressed_morale": 0.4,           # ...or the brigades in contact average under this morale...
    "pressed_ratio": 1.6,            # ...or the enemy within 700 of the line is this many times its strength
    "counter_charge": True,          # a standing line charges a beaten enemy unit within 250 (tactics.pursuit)
    # batteries
    "battery_escape": True,
    "battery_threat": 450.0,         # an enemy infantry or cavalry unit this close, coming closer...
    "battery_cover": 250.0,          # ...with no steady infantry of ours this close to the battery...
    "battery_back": 400.0,           # ...and the battery packs up and goes this far back
}

PASS = ("ammo", "formation", "gait", "limber", "release", "detach", "recall")


def _d(ax, az, bx, bz):
    return math.hypot(ax - bx, az - bz)


def _fighting_foes(state):
    _, foes = split_units(state)
    return [e for e in foes if unit_status(e) not in DEAD_STATUSES and e["kind"] != "Supply"]


def _strength(units):
    # units still off the field do not fight (0.1.4 WIP9, see situation.strength)
    return sum(float(u["hp"]) * (0.5 + 0.5 * float(u.get("morale", 1.0))) for u in units if not u.get("offmap"))


def rally_point(state, terrain, cfg, units=None):
    """A point at least `rally_distance` from every visible enemy, inside the map, behind the army (away from the
    enemy), in cover when possible. Returns (x, z, ux, uz): the point and the direction away from the enemy."""
    mine, _ = split_units(state)
    foes = _fighting_foes(state)
    units = [u for u in (units or mine) if unit_status(u) not in DEAD_STATUSES and not u.get("offmap")] or mine
    cx = sum(u["x"] for u in units) / len(units)
    cz = sum(u["z"] for u in units) / len(units)
    if not foes:
        return cx, cz, 0.0, 0.0
    ex = sum(e["x"] for e in foes) / len(foes)
    ez = sum(e["z"] for e in foes) / len(foes)
    d = _d(cx, cz, ex, ez) or 1.0
    ux, uz = (cx - ex) / d, (cz - ez) / d
    want = float(cfg["rally_distance"])
    margin = float(cfg["edge_margin"])
    best = None
    for ang in (0, 25, -25, 50, -50, 75, -75):
        a = math.radians(ang)
        vx, vz = ux * math.cos(a) - uz * math.sin(a), ux * math.sin(a) + uz * math.cos(a)
        for step in range(0, 3001, 100):
            x, z = cx + vx * step, cz + vz * step
            if terrain is not None:
                if not (terrain.min_x + margin <= x <= terrain.max_x - margin
                        and terrain.min_z + margin <= z <= terrain.max_z - margin):
                    break
                if not terrain.passable(x, z):
                    continue
            near = min(_d(x, z, e["x"], e["z"]) for e in foes)
            if near >= want:
                cover = terrain.fire_value(x, z, "Infantry") if terrain is not None else 0.5
                score = step + 400.0 * abs(ang) / 75.0 - 300.0 * cover
                if best is None or score < best[0]:
                    best = (score, x, z, vx, vz)
                break
    if best is None:                                  # nowhere far enough: the farthest point found straight back
        x, z = cx + ux * 800.0, cz + uz * 800.0
        if terrain is not None:
            x = min(max(x, terrain.min_x + margin), terrain.max_x - margin)
            z = min(max(z, terrain.min_z + margin), terrain.max_z - margin)
            p = terrain.nearest_passable(x, z)
            if p is not None:
                x, z = p
        return x, z, ux, uz
    return best[1], best[2], best[3], best[4]


def line_spots(units, x0, z0, ux, uz, cfg, terrain, taken=()):
    """Spots along a line through (x0, z0), across the direction (ux, uz), one per unit; each moved to the best
    cover within 150 when there is some."""
    px, pz = -uz, ux
    order = sorted(units, key=lambda u: (u["x"] - x0) * px + (u["z"] - z0) * pz)
    spots, used = {}, list(taken)
    for k, u in enumerate(order):
        off = (k - (len(order) - 1) / 2.0) * float(cfg["spacing"])
        x, z = x0 + px * off, z0 + pz * off
        if terrain is not None:
            p = terrain.nearest_passable(x, z)
            if p is not None:
                x, z = p
            # 0.1.4 WIP10: no cover search for batteries and wagons (woods block a battery's fire and slow it down;
            # terrain_rules then moved them out again: 237 corrections and 19 % of the time in woods on 2026-11-13)
            if (u["kind"] not in ("Artillery", "Supply") and terrain.fire_value(x, z, u["kind"]) < 1.0
                    and hasattr(terrain, "nearest_hiding_place")):
                h = terrain.nearest_hiding_place(x, z, 150.0)
                if h is not None and all(_d(h[0], h[1], a, b) > 80.0 for a, b in used):
                    x, z = h[0], h[1]
        used.append((x, z))
        spots[u["id"]] = (round(x, 1), round(z, 1))
    return spots


def preserve_due(plan, state, cfg, minutes):
    """The battle is lost on every count the server can see: the result needs objectives the player holds (the
    plan attacks nothing or has given the assault up), the casualty race is lost, the force ratio is bad."""
    if not plan or minutes < float(cfg["preserve_minute"]):
        return False
    ratio = plan.get("overall")
    kd = plan.get("kd")
    if ratio is None or kd is None:
        return False
    mine, _ = split_units(state)
    side = mine[0]["side"] if mine else None
    player = state.get("playerSide")
    objs = state.get("objectives") or []
    held_by_player = [o for o in objs if o.get("side") == player]
    ours = [o for o in objs if o.get("side") == side]
    lost_ground = bool(held_by_player) and not ours
    return (lost_ground and float(ratio) < float(cfg["preserve_ratio"]) and float(kd) < float(cfg["preserve_kd"])
            and (plan.get("abandoned") or plan.get("mode") != "ATTACK" or float(ratio) < 0.5))


def withdraw_due(state, ratio, cfg):
    """Outnumbered and the line failing."""
    if ratio is None or float(ratio) >= float(cfg["withdraw_ratio"]):
        return False
    mine, _ = split_units(state)
    foes = _fighting_foes(state)
    front = [u for u in mine if u["kind"] == "Infantry" and unit_status(u) in ("", "fallback", "melee")
             and any(_d(u["x"], u["z"], e["x"], e["z"]) <= 500.0 for e in foes)]
    if len(front) < int(cfg["withdraw_min_contact"]):
        return False
    shaken = sum(1 for u in front if float(u["morale"]) < float(cfg["shaken_morale"]))
    return shaken >= float(cfg["withdraw_shaken_share"]) * len(front)


class Withdrawal:
    """State kept between turns by the planner."""

    def __init__(self, cfg=None):
        self.cfg = {**DEFAULT_WITHDRAW, **(cfg or {})}
        self.mode = None            # None, "WITHDRAW" or "PRESERVE"
        self.since = 0.0
        self.ended = -1e9
        self.rearguard = []
        self.sent = {}              # unit id -> (x, z) last sent
        self.members = set()
        self.rally = None           # (x, z, ux, uz, time): kept so that the spots do not follow the army around
        self.phase = "move"         # WIP10 bounds: "move" (main body going to its line) or "stand" (holding it)
        self.phase_t = 0.0
        self.line_ids = set()       # the brigades of the line (main body infantry, skirmishers, cavalry)
        self.fire_sent = {}         # unit id -> (target, time) of the standing line's fire

    def reset(self):
        self.__init__(self.cfg)

    def active(self):
        return self.mode is not None

    # ---------------------------------------------------------------------------------------------------------
    def update_mode(self, state, plan, stats=None):
        cfg = self.cfg
        if not cfg["enabled"]:
            return None
        now = float(state.get("time", 0.0))
        minutes = float(state.get("phaseTime", now)) / 60.0
        ratio = (plan or {}).get("overall")
        mine, _ = split_units(state)
        if self.mode == "PRESERVE":
            if ratio is not None and float(ratio) >= float(cfg["preserve_resume_ratio"]):
                print(f"  PRESERVE ended: force ratio {float(ratio):.2f}")
                self._end(now)
            return self.mode
        if cfg["preserve"] and preserve_due(plan, state, cfg, minutes):
            print(f"  PRESERVE: the battle is lost (objectives held by the player, kill ratio "
                  f"{float(plan.get('kd') or 0):.2f}, force ratio {float(ratio):.2f}): the army withdraws and is kept")
            self._start("PRESERVE", now, stats)
            return self.mode
        if self.mode == "WITHDRAW":
            members = [u for u in mine if u["id"] in self.members and unit_status(u) not in DEAD_STATUSES]
            avg = sum(float(u["morale"]) for u in members) / len(members) if members else 0.0
            done = members and avg >= float(cfg["withdraw_end_morale"]) and now - self.since >= float(cfg["withdraw_min_s"])
            if done or now - self.since >= float(cfg["withdraw_max_s"]):
                print(f"  WITHDRAW ended: average morale {avg:.2f} after {(now - self.since) / 60:.0f} min")
                self._end(now)
            return self.mode
        if (cfg["withdraw"] and now - self.ended >= float(cfg["withdraw_cooldown_s"])
                and withdraw_due(state, ratio, cfg)):
            print(f"  WITHDRAW: outnumbered (force ratio {float(ratio):.2f}) and the line is failing: break contact")
            self._start("WITHDRAW", now, stats)
        return self.mode

    def _start(self, mode, now, stats):
        self.mode, self.since, self.rearguard, self.sent, self.members = mode, now, [], {}, set()
        self.rally, self.phase, self.phase_t, self.line_ids = None, "move", now, set()
        self.rear_owners = set()
        if stats is not None:
            key = f"{mode.lower()} started"
            stats[key] = stats.get(key, 0) + 1

    def _end(self, now):
        self.mode, self.ended, self.rearguard, self.sent, self.members = None, now, [], {}, set()
        self.rally, self.phase, self.phase_t, self.line_ids = None, "move", now, set()
        self.rear_owners = set()

    def standing(self):
        return self.mode is not None and self.phase == "stand"

    def _pressed(self, line, foes):
        """The standing line can no longer hold: enemies at its throat, its brigades in contact shaken, or far
        outnumbered where it stands."""
        cfg = self.cfg
        if not line or not foes:
            return False
        close = sum(1 for u in line if unit_status(u) == "melee"
                    or (nearest(u, foes) or (None, 1e9))[1] <= float(cfg["pressed_close"]))
        if close >= max(1, len(line) // 3):
            return True
        contact = [u for u in line if (nearest(u, foes) or (None, 1e9))[1] <= 500.0]
        if contact and sum(float(u["morale"]) for u in contact) / len(contact) < float(cfg["pressed_morale"]):
            return True
        cx = sum(u["x"] for u in line) / len(line)
        cz = sum(u["z"] for u in line) / len(line)
        near_foes = [e for e in foes if _d(cx, cz, e["x"], e["z"]) <= 700.0]
        mine_s = sum(float(u["hp"]) * (0.5 + 0.5 * float(u["morale"])) for u in line)
        foe_s = sum(float(e["hp"]) * (0.5 + 0.5 * float(e.get("morale", 1.0))) for e in near_foes)
        return mine_s > 0 and foe_s > float(cfg["pressed_ratio"]) * mine_s

    # ---------------------------------------------------------------------------------------------------------
    def army_orders(self, state, terrain, orders, stats=None):
        """Orders of the withdrawal: (ids the server now drives, orders). Model orders for those ids are dropped
        by the caller, except ammo, formation, gait, limber."""
        if self.mode is None:
            return set(), []
        cfg = self.cfg
        mine, _ = split_units(state)
        foes = _fighting_foes(state)
        units = [u for u in mine if unit_status(u) not in DEAD_STATUSES and not u.get("offmap")
                 and u["kind"] in ("Infantry", "Skirmish", "Cavalry", "Artillery", "Supply", "General")]
        if not units:
            return set(), []
        now = float(state.get("time", 0.0))
        if cfg.get("bounds", True):
            # 0.1.4 WIP10: withdrawal by bounds. The main body goes to a line out of reach and STANDS there (in
            # cover, firing at whoever follows in the open, its morale coming back when the enemy keeps away); a new
            # bound starts only when that line is pressed, with a rearguard (and its skirmish screens) covering it.
            line_now = [u for u in units if u["id"] in self.line_ids and u["id"] not in self.rearguard]
            if self.rally is None:
                keep = False
            elif self.phase == "stand":
                keep = not (now - self.phase_t >= float(cfg["bound_min_stand_s"]) and self._pressed(line_now, foes))
                if not keep:
                    self.rearguard = []                  # a new rearguard, from the line that was pressed
                    if stats is not None:
                        stats["withdrawal: a new bound back (the standing line was pressed)"] = \
                            stats.get("withdrawal: a new bound back (the standing line was pressed)", 0) + 1
            else:
                keep = True
        else:
            keep = self.rally is not None and now - self.rally[4] < float(cfg["rally_keep_s"])
            if keep and foes:
                close = min(_d(self.rally[0], self.rally[1], e["x"], e["z"]) for e in foes)
                keep = close >= float(cfg["rally_threat_share"]) * float(cfg["rally_distance"])
        if not keep:
            self.rally = rally_point(state, terrain, cfg, units) + (now,)
            self.phase, self.phase_t, self.sent = "move", now, {}
        rx, rz, ux, uz, _ = self.rally
        # rearguard: skirmishers, cavalry, then the freshest brigades, in cover between the army and the enemy
        if not self.rearguard:
            cands = [u for u in units if u["kind"] in ("Skirmish", "Cavalry", "Infantry")
                     and float(u["morale"]) >= float(cfg["rearguard_min_morale"]) and unit_status(u) == ""]
            cands.sort(key=lambda u: ({"Skirmish": 0, "Cavalry": 1}.get(u["kind"], 2), -float(u["morale"])))
            self.rearguard = [u["id"] for u in cands[:int(cfg["rearguard"])]]
            self.rear_since = now
        out, ids = [], set()
        rear = {u["id"]: u for u in units if u["id"] in self.rearguard}
        for uid, u in rear.items():
            near = nearest(u, foes)
            ids.add(uid)
            if near and near[1] <= float(cfg["rearguard_release"]) or float(u["morale"]) < 0.35:
                self.rearguard.remove(uid)               # its job is done: it joins the others below
                ids.discard(uid)
                continue
            if near and near[1] <= 1.1 * float(u.get("range") or 400):
                out.append({"cmd": "range_attack", "id": uid, "target": near[0]["id"], "auto": True})
        # 0.1.4 WIP10: the skirmish screens of the rearguard brigades stay behind with them (skirmish.py drives them)
        self.rear_owners = getattr(self, "rear_owners", set()) | set(self.rearguard)
        screens_back = {u["id"] for u in units if u["kind"] == "Skirmish" and u.get("owner") in self.rear_owners}
        mainbody = [u for u in units if u["id"] not in self.rearguard and u["id"] not in screens_back]
        line = [u for u in mainbody if u["kind"] in ("Infantry", "Skirmish", "Cavalry")]
        back = [u for u in mainbody if u["kind"] in ("Artillery", "Supply", "General")]
        spots = line_spots(line, rx, rz, ux, uz, cfg, terrain)
        spots.update(line_spots(back, rx + ux * 250.0, rz + uz * 250.0, ux, uz, cfg, terrain,
                                taken=list(spots.values())))
        self.line_ids = {u["id"] for u in line}
        if cfg.get("bounds", True) and self.phase == "move" and line:
            there = sum(1 for u in line if _d(u["x"], u["z"], *spots[u["id"]]) <= 150.0)
            if there >= float(cfg["bound_arrive_share"]) * len(line) or now - self.phase_t >= float(cfg["bound_arrive_s"]):
                self.phase, self.phase_t = "stand", now
                if stats is not None:
                    stats["withdrawal: the main body stands on its line"] = \
                        stats.get("withdrawal: the main body stands on its line", 0) + 1
        standing = cfg.get("bounds", True) and self.phase == "stand"
        if standing and foes:
            # the standing line fires: every brigade at its spot with an enemy in range fires on the enemy most of
            # them reach (the nearest to the line when equal)
            at_spot = [u for u in line if _d(u["x"], u["z"], *spots[u["id"]]) <= 150.0 and unit_status(u) == ""]

            def reach(e):
                return [u for u in at_spot if _d(u["x"], u["z"], e["x"], e["z"]) <= 1.05 * float(u.get("range") or 400)]
            best = max(foes, key=lambda e: (len(reach(e)), -min((_d(u["x"], u["z"], e["x"], e["z"]) for u in at_spot),
                                                               default=0.0))) if at_spot else None
            for u in (reach(best) if best is not None else []):
                ids.add(u["id"])
                prev = self.fire_sent.get(u["id"])
                if prev and prev[0] == best["id"] and now - prev[1] < 60.0:
                    out.append({"cmd": "_keep", "id": u["id"]})      # firing already: nothing new to send
                    continue
                self.fire_sent[u["id"]] = (best["id"], now)
                out.append({"cmd": "range_attack", "id": u["id"], "target": best["id"], "auto": True})
                if stats is not None:
                    stats["withdrawal: the standing line fires on the enemy following it"] = \
                        stats.get("withdrawal: the standing line fires on the enemy following it", 0) + 1
        fired = {o["id"] for o in out if o["cmd"] in ("range_attack", "_keep")}
        out = [o for o in out if o["cmd"] != "_keep"]
        for u in mainbody:
            if u["id"] in fired:
                self.members.add(u["id"])
                continue
            sx, sz = spots[u["id"]]
            self.members.add(u["id"])
            ids.add(u["id"])
            near = nearest(u, foes)
            if near and (near[1] <= float(cfg["disengage"]) or unit_status(u) == "melee") and u["kind"] != "Artillery":
                out.append({"cmd": "fallback", "id": u["id"], "duration": 30.0, "auto": True})
                continue
            old = self.sent.get(u["id"])
            if old and _d(old[0], old[1], sx, sz) < float(cfg["reissue_shift"]):
                continue
            if _d(u["x"], u["z"], sx, sz) < 60.0:
                continue
            self.sent[u["id"]] = (sx, sz)
            o = {"cmd": "move", "id": u["id"], "x": sx, "z": sz, "auto": True}
            if near:
                o["fx"], o["fz"] = round(near[0]["x"], 1), round(near[0]["z"], 1)
            if u["kind"] == "Artillery" and str(u.get("limber") or "") == "ready":
                out.append({"cmd": "limber", "id": u["id"], "value": "pack", "auto": True})
            out.append(o)
            if u["kind"] in ("Infantry", "Supply") and _d(u["x"], u["z"], sx, sz) > 300.0:
                out.append({"cmd": "gait", "id": u["id"], "value": "Run", "auto": True})
            if stats is not None:
                key = f"{self.mode.lower()}: units sent to the rally line"
                stats[key] = stats.get(key, 0) + 1
        return ids, out

    def lines(self):
        if self.mode == "PRESERVE":
            return ["PRESERVE (battle lost: player holds the objectives, casualty race lost, outnumbered): the server "
                    "withdraws the army to a rally area far from the enemy and keeps it there; rearguard "
                    + (", ".join(f"#{i}" for i in self.rearguard) or "none")
                    + ". Engage only shaken or isolated enemy units that come close. Every man saved counts in "
                      "the next battle."]
        if self.mode == "WITHDRAW":
            return ["TACTICAL WITHDRAWAL (outnumbered, line failing): the server pulls the army back to a rally line "
                    f"out of the enemy's reach to recover morale; rearguard "
                    + (", ".join(f"#{i}" for i in self.rearguard) or "none")
                    + " covers it from cover. Do not order the withdrawing brigades forward; it ends when their "
                      "morale is back."]
        return []


# -------------------------------------------------------------------------------------------------------------
def rest_orders(state, terrain, orders, resting_ids, cfg, sent, skip_ids=(), stats=None):
    """REST: a resting brigade (relieved, morale not back) that stands within `rest_distance` of the enemy and is
    not in melee walks to a spot that far, behind the line. `sent`: id -> spot already sent."""
    cfg = {**DEFAULT_WITHDRAW, **(cfg or {})}
    if not cfg["enabled"] or not cfg["rest"] or not resting_ids:
        return set(), []
    mine, _ = split_units(state)
    foes = _fighting_foes(state)
    if not foes:
        return set(), []
    want = float(cfg["rest_distance"])
    ordered = {o["id"] for o in orders if o["cmd"] not in PASS}
    out, ids = [], set()
    for u in mine:
        if u["id"] not in resting_ids or u["id"] in skip_ids or unit_status(u) in DEAD_STATUSES + ("melee",):
            continue
        near = nearest(u, foes)
        if near is None or near[1] >= want or float(u["morale"]) >= float(cfg["rest_morale"]):
            continue
        if unit_status(u) == "fallback" or near[1] <= float(cfg["disengage"]):
            continue                                    # let the fallback open the distance first
        e = near[0]
        d = near[1] or 1.0
        ux, uz = (u["x"] - e["x"]) / d, (u["z"] - e["z"]) / d
        x, z = u["x"] + ux * (want - d + 100.0), u["z"] + uz * (want - d + 100.0)
        if terrain is not None:
            m = float(cfg["edge_margin"])
            x = min(max(x, terrain.min_x + m), terrain.max_x - m)
            z = min(max(z, terrain.min_z + m), terrain.max_z - m)
            p = terrain.nearest_passable(x, z)
            if p is not None:
                x, z = p
            if hasattr(terrain, "nearest_hiding_place"):
                h = terrain.nearest_hiding_place(x, z, 200.0)
                if h is not None and min(_d(h[0], h[1], f["x"], f["z"]) for f in foes) >= want - 100.0:
                    x, z = h[0], h[1]
        old = sent.get(u["id"])
        if old and _d(old[0], old[1], x, z) < float(cfg["reissue_shift"]):
            ids.add(u["id"])
            continue
        sent[u["id"]] = (x, z)
        ids.add(u["id"])
        out.append({"cmd": "move", "id": u["id"], "x": round(x, 1), "z": round(z, 1), "auto": True})
        if u["id"] in ordered and stats is not None:
            stats["model orders to resting brigades replaced by a rest move"] = \
                stats.get("model orders to resting brigades replaced by a rest move", 0) + 1
        if stats is not None:
            stats["resting brigades sent out of the enemy's reach (rest_distance)"] = \
                stats.get("resting brigades sent out of the enemy's reach (rest_distance)", 0) + 1
    return ids, out


def battery_escape_orders(state, terrain, orders, cfg, prev_pos, skip_ids=(), stats=None):
    """A battery with enemy infantry or cavalry coming within `battery_threat` and no steady infantry of ours near
    it packs up and goes back `battery_back`, behind the nearest steady brigade when there is one. The plugin's
    battery_back reflex only steps it back by hand. `prev_pos`: enemy id -> (x, z) at the previous state."""
    cfg = {**DEFAULT_WITHDRAW, **(cfg or {})}
    if not cfg["enabled"] or not cfg["battery_escape"]:
        return set(), []
    mine, foes = split_units(state)
    live = [e for e in foes if unit_status(e) not in DEAD_STATUSES and e["kind"] in ("Infantry", "Cavalry")]
    steady = [u for u in mine if u["kind"] == "Infantry" and unit_status(u) == "" and float(u["morale"]) >= 0.5]
    ordered = {o["id"] for o in orders if o["cmd"] in ("move", "fallback")}
    out, ids = [], set()
    for b in mine:
        if b["kind"] != "Artillery" or unit_status(b) in DEAD_STATUSES or b["id"] in skip_ids or b["id"] in ordered:
            continue
        threats = []
        for e in live:
            d = _d(b["x"], b["z"], e["x"], e["z"])
            if d > float(cfg["battery_threat"]):
                continue
            p = prev_pos.get(e["id"])
            closing = p is None or _d(b["x"], b["z"], p[0], p[1]) > d + 15.0
            if closing:
                threats.append((d, e))
        if not threats:
            continue
        if any(_d(b["x"], b["z"], v["x"], v["z"]) <= float(cfg["battery_cover"]) for v in steady):
            continue
        d, e = min(threats, key=lambda t: t[0])
        ux, uz = (b["x"] - e["x"]) / (d or 1.0), (b["z"] - e["z"]) / (d or 1.0)
        x, z = b["x"] + ux * float(cfg["battery_back"]), b["z"] + uz * float(cfg["battery_back"])
        behind = [v for v in steady if _d(v["x"], v["z"], e["x"], e["z"]) > d]
        if behind:
            v = min(behind, key=lambda v: _d(v["x"], v["z"], b["x"], b["z"]))
            dv = _d(v["x"], v["z"], e["x"], e["z"]) or 1.0
            x, z = v["x"] + (v["x"] - e["x"]) / dv * 200.0, v["z"] + (v["z"] - e["z"]) / dv * 200.0
        if terrain is not None:
            m = float(cfg["edge_margin"])
            x = min(max(x, terrain.min_x + m), terrain.max_x - m)
            z = min(max(z, terrain.min_z + m), terrain.max_z - m)
            p = terrain.nearest_passable(x, z)
            if p is not None:
                x, z = p
        ids.add(b["id"])
        if str(b.get("limber") or "") == "ready":
            out.append({"cmd": "limber", "id": b["id"], "value": "pack", "auto": True})
        out.append({"cmd": "move", "id": b["id"], "x": round(x, 1), "z": round(z, 1), "auto": True})
        if stats is not None:
            stats["batteries packed up and pulled back from an approaching enemy (no infantry cover)"] = \
                stats.get("batteries packed up and pulled back from an approaching enemy (no infantry cover)", 0) + 1
    return ids, out
