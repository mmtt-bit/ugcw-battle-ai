"""Road-aware routes for long marches.

A long straight move sends a brigade through whatever lies on the line: dense woods, scrub, a ford. The game's
own path finding only avoids what cannot be crossed, so the march runs at the speed of the slowest ground. Here
the server looks for the fastest way on the terrain grid (speed from the game's tooltips, roads slightly
preferred, as a player would draw the route with the mouse) and sends it as waypoints: the plugin walks the unit
from one waypoint to the next, facing along the next leg at each bend so the brigade does not wheel back.

Only moves longer than `min_distance` get a route, and only when it saves time on the straight line (or when the
unit stands outside the playing field, as reinforcements arriving at the start of a new phase do).
"""

import heapq
import math

DEFAULT_ROUTES = {
    "enabled": True,
    "min_distance": 500.0,       # shorter moves go straight
    "min_gain": 0.10,            # the route must be this much faster than the straight line (share)
    "road_preference": 0.85,     # cost factor of road / bridge cells (1 = no preference)
    "max_waypoints": 8,
    "straighten_tolerance": 1.06,  # a straight leg may cost this much more than the grid path it replaces
    "max_routes_per_turn": 12,
    "kinds": ["Infantry", "Artillery", "Supply", "Cavalry", "Skirmish"],
    "edge_margin": 120.0,        # a unit outside the field first walks this far inside it
}

ROAD_CELLS = ("Road", "Bridge")


def _cell_cost(terrain, name, kind, cfg):
    speed = terrain.speed_of(name, kind)
    if speed <= 0.02:
        return None                                  # impassable (deep water and the like)
    cost = 1.0 / speed
    if name in ROAD_CELLS:
        cost *= float(cfg["road_preference"])
    return cost


def grid_path(terrain, x1, z1, x2, z2, kind, cfg):
    """A* on the terrain grid, 8 neighbours. Returns ([(x, z), ...] cell centres, cost) or (None, None)."""
    c0, r0 = terrain._cell(x1, z1)
    c1, r1 = terrain._cell(x2, z2)
    cache = {}

    def cost_at(c, r):
        key = (c, r)
        if key not in cache:
            cache[key] = _cell_cost(terrain, terrain.legend.get(terrain.grid[r][c], "Unknown"), kind, cfg)
        return cache[key]

    best_speed = min(1.0, float(cfg["road_preference"]))
    h = lambda c, r: math.hypot(c - c1, r - r1) * best_speed
    openq = [(h(c0, r0), 0.0, c0, r0)]
    came, gbest = {}, {(c0, r0): 0.0}
    steps = [(1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0),
             (1, 1, 1.4142), (1, -1, 1.4142), (-1, 1, 1.4142), (-1, -1, 1.4142)]
    while openq:
        _, g, c, r = heapq.heappop(openq)
        if (c, r) == (c1, r1):
            break
        if g > gbest.get((c, r), math.inf):
            continue
        for dc, dr, length in steps:
            nc, nr = c + dc, r + dr
            if not (0 <= nc < terrain.cols and 0 <= nr < terrain.rows):
                continue
            k = cost_at(nc, nr)
            if k is None:
                continue
            ng = g + length * 0.5 * (k + (cost_at(c, r) or k))
            if ng < gbest.get((nc, nr), math.inf):
                gbest[(nc, nr)] = ng
                came[(nc, nr)] = (c, r)
                heapq.heappush(openq, (ng + h(nc, nr), ng, nc, nr))
    if (c1, r1) not in gbest:
        return None, None
    cells, cur = [], (c1, r1)
    while cur != (c0, r0):
        cells.append(cur)
        cur = came[cur]
    cells.append((c0, r0))
    cells.reverse()
    pts = [(terrain.min_x + (c + 0.5) * terrain.step, terrain.min_z + (r + 0.5) * terrain.step) for c, r in cells]
    return pts, gbest[(c1, r1)] * terrain.step


def _leg_cost(terrain, a, b, kind, cfg):
    """Cost of walking straight from a to b, in the same units as grid_path (distance / speed)."""
    dist = math.hypot(b[0] - a[0], b[1] - a[1])
    if dist < 1:
        return 0.0
    n = max(2, int(dist // (terrain.step / 2.0)))
    total = 0.0
    for i in range(n):
        t = (i + 0.5) / n
        name = terrain.name_at(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
        k = _cell_cost(terrain, name, kind, cfg)
        if k is None:
            return math.inf
        total += dist / n * k
    return total


def straighten(terrain, pts, kind, cfg):
    """Keep only the bends: from each kept point, jump to the farthest later point whose straight leg costs no more
    than the grid path it replaces (times a small tolerance)."""
    if len(pts) <= 2:
        return pts
    prefix = [0.0]
    for a, b in zip(pts, pts[1:]):
        prefix.append(prefix[-1] + _leg_cost(terrain, a, b, kind, cfg))
    tol = float(cfg["straighten_tolerance"])
    out, i = [pts[0]], 0
    while i < len(pts) - 1:
        j = len(pts) - 1
        while j > i + 1 and _leg_cost(terrain, pts[i], pts[j], kind, cfg) > tol * (prefix[j] - prefix[i]) + 1.0:
            j -= 1
        out.append(pts[j])
        i = j
    return out


def route(terrain, unit, x, z, cfg=None):
    """Waypoints [(x, z), ...] before the final point (x, z), or None to go straight."""
    cfg = {**DEFAULT_ROUTES, **(cfg or {})}
    if terrain is None or not cfg["enabled"] or unit["kind"] not in cfg["kinds"]:
        return None
    ux, uz = float(unit["x"]), float(unit["z"])
    if math.hypot(x - ux, z - uz) < float(cfg["min_distance"]):
        return None
    kind = "Artillery" if unit["kind"] in ("Artillery", "Supply") else (
        "Cavalry" if unit["kind"] == "Cavalry" else "Infantry")
    outside = not terrain.inside(ux, uz) or min(ux - terrain.min_x, terrain.max_x - ux,
                                                uz - terrain.min_z, terrain.max_z - uz) < terrain.step
    start = (ux, uz)
    entry = None
    if outside:
        # reinforcements at a new phase start outside (or on the edge of) the playing field: walk in first
        m = float(cfg["edge_margin"])
        ex = min(max(ux, terrain.min_x + m), terrain.max_x - m)
        ez = min(max(uz, terrain.min_z + m), terrain.max_z - m)
        spot = terrain.nearest_passable(ex, ez)
        if spot is not None:
            entry = spot
            start = spot
    pts, cost = grid_path(terrain, start[0], start[1], x, z, kind, cfg)
    if not pts:
        return [entry] if entry else None
    pts = straighten(terrain, [start] + pts[1:-1] + [(x, z)], kind, cfg)
    straight = _leg_cost(terrain, start, (x, z), kind, cfg)
    via = pts[1:-1]
    if not entry and (not via or cost >= straight * (1.0 - float(cfg["min_gain"]))):
        return None
    via = via[:int(cfg["max_waypoints"])]
    if entry:
        via = [entry] + via
    return [(round(px, 1), round(pz, 1)) for px, pz in via]


def add_routes(orders, state, terrain, cfg=None, stats=None):
    """Adds "path" (waypoints before the destination) to the long moves that gain from a route."""
    cfg = {**DEFAULT_ROUTES, **(cfg or {})}
    if terrain is None or not cfg["enabled"]:
        return orders
    by_id = {u["id"]: u for u in state.get("units", []) if u.get("side") != state.get("playerSide")}
    done = 0
    out = []
    for o in orders:
        u = by_id.get(o.get("id"))
        if (o.get("cmd") == "move" and u is not None and "path" not in o
                and done < int(cfg["max_routes_per_turn"])):
            try:
                via = route(terrain, u, float(o["x"]), float(o["z"]), cfg)
            except Exception as e:                    # a route is a bonus, never a reason to lose the order
                print(f"  Route for #{u['id']} failed: {e}")
                via = None
            if via:
                o = dict(o, path=[[px, pz] for px, pz in via])
                done += 1
                if stats is not None:
                    k = "long moves sent as road-aware routes (waypoints)"
                    stats[k] = stats.get(k, 0) + 1
        out.append(o)
    return out
