"""Terrain model built from the "terrain" message sent by the plugin (see TerrainScan.cs).

The plugin samples the game's own terrain map on a regular grid. This module turns that grid
into compact text for the LLM prompt and answers geometric questions: what terrain is at a
point, what lies along a line, where are the fords and bridges, where is the nearest
passable spot.
"""
import math

# In the overview, linear features are shown as soon as one cell is present in a block.
LINEAR_PRIORITY = ("Bridge", "Ford", "Road")
# Area features are shown when they cover at least 30% of a block (first match wins).
AREA_PRIORITY = ("Fortifications", "WaterNoPass", "Water", "DenseForest", "Forest",
                 "Mud", "Scrub", "Wheatfield", "Grass")
IMPASSABLE = ("WaterNoPass",)
WATER = ("Water", "WaterNoPass")
CROSSINGS = ("Ford", "Bridge")


class TerrainMap:
    def __init__(self, msg):
        self.min_x, self.min_z = float(msg["minX"]), float(msg["minZ"])
        self.max_x, self.max_z = float(msg["maxX"]), float(msg["maxZ"])
        self.step = float(msg["step"])
        self.grid = list(msg["terrain"])      # grid[row][col]; the row index grows with z
        self.heights = list(msg["heights"])   # same shape; digits 0 (low) to 9 (high)
        self.rows = len(self.grid)
        self.cols = len(self.grid[0]) if self.rows else 0
        if self.rows == 0 or self.cols == 0 or self.step <= 0:
            raise ValueError("empty terrain grid")
        if any(len(r) != self.cols for r in self.grid) or len(self.heights) != self.rows \
                or any(len(r) != self.cols for r in self.heights):
            raise ValueError("terrain rows have inconsistent sizes")
        self.legend = dict(msg["legend"])     # symbol -> terrain name
        self.symbol_of = {name: sym for sym, name in self.legend.items()}
        self.objectives = list(msg.get("objectives", []))
        self.rules = dict(msg.get("rules", {}))

    # ---- point queries -------------------------------------------------------------
    def inside(self, x, z):
        return self.min_x <= x < self.max_x and self.min_z <= z < self.max_z

    def _cell(self, x, z):
        col = min(self.cols - 1, max(0, int((x - self.min_x) // self.step)))
        row = min(self.rows - 1, max(0, int((z - self.min_z) // self.step)))
        return col, row

    def name_at(self, x, z):
        col, row = self._cell(x, z)
        return self.legend.get(self.grid[row][col], "Unknown")

    def height_at(self, x, z):
        col, row = self._cell(x, z)
        return int(self.heights[row][col])

    def clamp(self, x, z):
        half = self.step / 2.0
        return (min(max(x, self.min_x + half), self.max_x - half),
                min(max(z, self.min_z + half), self.max_z - half))

    def passable(self, x, z):
        return self.inside(x, z) and self.name_at(x, z) not in IMPASSABLE

    def nearest_passable(self, x, z, max_rings=6):
        """Return the closest passable point (x, z) or None. Out-of-map points are clamped."""
        x, z = self.clamp(x, z)
        if self.passable(x, z):
            return x, z
        for ring in range(1, max_rings + 1):
            best = None
            for dc in range(-ring, ring + 1):
                for dr in range(-ring, ring + 1):
                    if max(abs(dc), abs(dr)) != ring:
                        continue
                    px, pz = x + dc * self.step, z + dr * self.step
                    if self.passable(px, pz):
                        d = math.hypot(dc, dr)
                        if best is None or d < best[0]:
                            best = (d, px, pz)
            if best:
                return best[1], best[2]
        return None

    # ---- text rendering ------------------------------------------------------------
    def _block_symbol(self, c0, c1, r0, r1):
        counts, total = {}, 0
        for r in range(r0, r1):
            row = self.grid[r]
            for c in range(c0, c1):
                name = self.legend.get(row[c], "Unknown")
                counts[name] = counts.get(name, 0) + 1
                total += 1
        for name in LINEAR_PRIORITY:
            if counts.get(name):
                return self.symbol_of.get(name, "?")
        for name in AREA_PRIORITY:
            if counts.get(name, 0) / total >= 0.3:
                return self.symbol_of.get(name, "?")
        return self.symbol_of.get(max(counts, key=counts.get), "?")

    def _render(self, max_cols, cell_fn):
        block = max(1, int(math.ceil(self.cols / float(max_cols))))
        rows_out = []
        for r0 in range(0, self.rows, block):
            r1 = min(self.rows, r0 + block)
            text = "".join(cell_fn(c0, min(self.cols, c0 + block), r0, r1)
                           for c0 in range(0, self.cols, block))
            z_center = self.min_z + (r0 + r1) / 2.0 * self.step
            rows_out.append((z_center, text))
        rows_out.reverse()  # largest z at the top
        label_w = len(str(int(self.max_z))) + 1
        width = len(rows_out[0][1])
        ruler = [" "] * width
        for k in range(0, width, 10):
            label = str(int(self.min_x + (k + 0.5) * block * self.step))
            for i, ch in enumerate(label):
                if k + i < width:
                    ruler[k + i] = ch
        lines = [" " * (label_w + 1) + "".join(ruler)]
        lines += [f"{int(z):>{label_w}} {text}" for z, text in rows_out]
        return "\n".join(lines), block * self.step

    def overview(self, max_cols=60):
        """ASCII terrain map. Returns (text, size of one character in game units)."""
        return self._render(max_cols, self._block_symbol)

    def heights_overview(self, max_cols=40):
        def avg(c0, c1, r0, r1):
            vals = [int(self.heights[r][c]) for r in range(r0, r1) for c in range(c0, c1)]
            return str(int(round(sum(vals) / float(len(vals)))))
        return self._render(max_cols, avg)

    # ---- features ------------------------------------------------------------------
    def crossings(self):
        """Clusters of Ford and Bridge cells: [{'kind','x','z','width','depth'}]."""
        seen, out = set(), []
        for kind in CROSSINGS:
            sym = self.symbol_of.get(kind)
            if not sym:
                continue
            for r in range(self.rows):
                for c in range(self.cols):
                    if self.grid[r][c] != sym or (r, c) in seen:
                        continue
                    stack, cells = [(r, c)], []
                    seen.add((r, c))
                    while stack:
                        cr, cc = stack.pop()
                        cells.append((cr, cc))
                        for dr in (-1, 0, 1):
                            for dc in (-1, 0, 1):
                                nr, nc = cr + dr, cc + dc
                                if (0 <= nr < self.rows and 0 <= nc < self.cols
                                        and (nr, nc) not in seen and self.grid[nr][nc] == sym):
                                    seen.add((nr, nc))
                                    stack.append((nr, nc))
                    cs = [c for _, c in cells]
                    rs = [r for r, _ in cells]
                    out.append({
                        "kind": kind,
                        "x": round(self.min_x + (sum(cs) / len(cs) + 0.5) * self.step),
                        "z": round(self.min_z + (sum(rs) / len(rs) + 0.5) * self.step),
                        "width": round((max(cs) - min(cs) + 1) * self.step),
                        "depth": round((max(rs) - min(rs) + 1) * self.step),
                    })
        return sorted(out, key=lambda f: (f["x"], f["z"]))

    def route_report(self, x1, z1, x2, z2):
        """Short description of the terrain along the straight line between two points."""
        dist = math.hypot(x2 - x1, z2 - z1)
        if dist < 1:
            return "same spot"
        n = max(2, int(dist // (self.step / 2.0)))
        seg = dist / n
        lengths = {}
        for i in range(n):
            t = (i + 0.5) / n
            name = self.name_at(x1 + (x2 - x1) * t, z1 + (z2 - z1) * t)
            lengths[name] = lengths.get(name, 0.0) + seg
        top = sorted(lengths.items(), key=lambda kv: -kv[1])[:4]
        text = ", ".join(f"{k} {v:.0f}" for k, v in top)
        water = sum(v for k, v in lengths.items() if k in WATER)
        cross = sum(v for k, v in lengths.items() if k in CROSSINGS)
        if water > 0:
            text += f"; water {water:.0f}" + (f" (ford/bridge {cross:.0f})" if cross else " (no ford/bridge)")
        elif cross:
            text += f"; ford/bridge {cross:.0f}"
        return f"{dist:.0f} away: {text}; height {self.height_at(x1, z1)}->{self.height_at(x2, z2)}"

    # ---- movement cost (from the game's own terrain tooltips) ----------------------
    DEFAULT_SPEED = {"Grass": 1.0, "Road": 1.0, "Wheatfield": 0.9, "Scrub": 0.45, "Mud": 0.33, "Forest": 0.66,
                     "DenseForest": 0.6, "Water": 0.05, "WaterNoPass": 0.0, "Bridge": 0.6, "Ford": 0.15,
                     "Fortifications": 0.7}
    DEFAULT_STEALTH = {"Forest": 1.0, "DenseForest": 5.0, "Wheatfield": 0.5, "Scrub": 0.25, "Mud": 0.25}

    def _rule_value(self, terrain, field, kind="Infantry"):
        """A percentage from the game's tooltip text ("Speed 66%" -> 0.66), or None."""
        table = self.rules.get(kind) or self.rules.get("Infantry") or {}
        text = str(table.get(terrain) or "")
        for line in text.split("\n"):
            if line.strip().lower().startswith(field.lower()):
                digits = "".join(ch for ch in line if ch.isdigit() or ch == ".")
                try:
                    return float(digits) / 100.0
                except ValueError:
                    return None
        return None

    def speed_of(self, terrain, kind="Infantry"):
        v = self._rule_value(terrain, "Speed", kind)
        return v if v is not None else self.DEFAULT_SPEED.get(terrain, 1.0)

    def stealth_of(self, terrain, kind="Infantry"):
        v = self._rule_value(terrain, "Stealth", kind)
        return v if v is not None else self.DEFAULT_STEALTH.get(terrain, 0.0)

    def path_profile(self, x1, z1, x2, z2, kind="Infantry", slow_below=0.7):
        """Straight-line march from (x1, z1) to (x2, z2): (distance, effective distance on open ground,
        share of the way on slow terrain). Effective distance = sum of each piece / its speed factor."""
        dist = math.hypot(x2 - x1, z2 - z1)
        if dist < 1:
            return 0.0, 0.0, 0.0
        n = max(2, int(dist // (self.step / 2.0)))
        seg = dist / n
        eff, slow = 0.0, 0.0
        for i in range(n):
            t = (i + 0.5) / n
            name = self.name_at(x1 + (x2 - x1) * t, z1 + (z2 - z1) * t)
            sp = max(self.speed_of(name, kind), 0.05)
            eff += seg / sp
            if sp < slow_below:
                slow += seg
        return dist, eff, slow / dist

    def is_slow(self, x, z, kind="Infantry", slow_below=0.7):
        return self.speed_of(self.name_at(x, z), kind) < slow_below

    def nearest_open(self, x, z, kind="Infantry", max_dist=250.0, slow_below=0.7):
        """The nearest passable point on fast terrain (speed >= slow_below) within max_dist, else None."""
        if not self.is_slow(x, z, kind, slow_below) and self.passable(x, z):
            return x, z
        best, bd = None, max_dist + 1
        step = self.step
        rings = int(max_dist // step) + 1
        for r in range(1, rings + 1):
            for k in range(8 * r):
                ang = 2 * math.pi * k / (8 * r)
                px, pz = self.clamp(x + math.cos(ang) * r * step, z + math.sin(ang) * r * step)
                if not self.passable(px, pz) or self.is_slow(px, pz, kind, slow_below):
                    continue
                d = math.hypot(px - x, pz - z)
                if d < bd:
                    best, bd = (px, pz), d
            if best is not None:
                return best
        return None

    def nearest_hiding_place(self, x, z, max_dist=600.0, min_stealth=0.5, min_dist=0.0):
        """The nearest cell whose terrain hides troops (stealth from the tooltips: forest, dense forest,
        wheat...), as (x, z, terrain name, distance), or None."""
        col0, row0 = self._cell(x, z)
        rings = int(max_dist // self.step) + 1
        best = None
        for r in range(0, rings + 1):
            for row in range(row0 - r, row0 + r + 1):
                for col in (range(col0 - r, col0 + r + 1) if row in (row0 - r, row0 + r) else (col0 - r, col0 + r)):
                    if not (0 <= row < self.rows and 0 <= col < self.cols):
                        continue
                    name = self.legend.get(self.grid[row][col], "")
                    if self.stealth_of(name) < min_stealth:
                        continue
                    cx = self.min_x + (col + 0.5) * self.step
                    cz = self.min_z + (row + 0.5) * self.step
                    d = math.hypot(cx - x, cz - z)
                    if min_dist <= d <= max_dist and (best is None or d < best[3]):
                        best = (round(cx), round(cz), name, round(d))
            if best is not None:
                return best
        return None

    # ---- firing positions (cover and damage from the game's tooltips) ----------------
    DEFAULT_COVER = {"Grass": 0.5, "Road": 0.5, "Wheatfield": 1.15, "Scrub": 0.5, "Mud": 0.5, "Forest": 1.5,
                     "DenseForest": 1.6, "Water": 0.01, "Bridge": 0.01, "Ford": 0.01, "Fortifications": 2.0}
    DEFAULT_DAMAGE = {"Wheatfield": 0.9, "Scrub": 0.9, "Mud": 0.95, "Forest": 0.8, "DenseForest": 0.7,
                      "Water": 0.5, "Bridge": 0.6, "Ford": 0.5, "Fortifications": 0.8}

    def cover_of(self, terrain, kind="Infantry"):
        v = self._rule_value(terrain, "Cover", kind)
        return v if v is not None else self.DEFAULT_COVER.get(terrain, 0.5)

    def damage_of(self, terrain, kind="Infantry"):
        v = self._rule_value(terrain, "Damage", kind)
        return v if v is not None else self.DEFAULT_DAMAGE.get(terrain, 1.0)

    def fire_value(self, x, z, kind="Infantry"):
        """How good a spot is to stand and fire from: protection (cover) times own fire (damage).
        Open grass 0.5, wheat about 1.0, forest 1.2, fortifications 1.6."""
        name = self.name_at(x, z)
        return self.cover_of(name, kind) * self.damage_of(name, kind)

    def best_fire_spot(self, ux, uz, tx, tz, rng, kind="Infantry", taken=(), max_move=None, arc_deg=40.0,
                       cover_weight=700.0, keep_apart=120.0):
        """A firing position against the target at (tx, tz): on an arc around the target, inside the fire range,
        trading the march (at real speed) against the protection of the spot. Returns (x, z, terrain, value) or
        None. `taken` are spots already given to other units; `max_move` limits the distance from the unit."""
        base = math.atan2(uz - tz, ux - tx)
        best, best_cost = None, None
        for frac in (0.7, 0.8, 0.9):
            r = rng * frac
            for k in range(-int(arc_deg // 8), int(arc_deg // 8) + 1):
                ang = base + math.radians(8.0 * k)
                x, z = self.clamp(tx + math.cos(ang) * r, tz + math.sin(ang) * r)
                if not self.passable(x, z):
                    continue
                if max_move is not None and math.hypot(x - ux, z - uz) > max_move:
                    continue
                if any(math.hypot(x - px, z - pz) < keep_apart for px, pz in taken):
                    continue
                _, eff, _ = self.path_profile(ux, uz, x, z, kind)
                value = self.fire_value(x, z, kind)
                cost = eff - cover_weight * (value - 0.5)
                if best_cost is None or cost < best_cost:
                    best, best_cost = (round(x, 1), round(z, 1), self.name_at(x, z), round(value, 2)), cost
        return best

    # ---- prompt section ------------------------------------------------------------
    def prompt_text(self, overview_cols=60, height_cols=40, show_heights=True, show_rules=True):
        lines = []
        lines.append(f"Playable area: x from {self.min_x:.0f} to {self.max_x:.0f}, "
                     f"z from {self.min_z:.0f} to {self.max_z:.0f}.")
        lines.append("Legend: " + ", ".join(f"{s} = {n}" for s, n in self.legend.items()))
        text, cell = self.overview(overview_cols)
        lines.append(f"TERRAIN MAP (one character = about {cell:.0f} x {cell:.0f} units; "
                     "each row is labelled with its z coordinate, the largest z is at the top; "
                     "the ruler above gives x):")
        lines.append(text)
        if show_heights:
            text, cell = self.heights_overview(height_cols)
            lines.append(f"RELIEF MAP (same layout, one character = about {cell:.0f} units; "
                         "digits go from 0 = lowest ground to 9 = highest ground):")
            lines.append(text)
        crossings = self.crossings()
        if crossings:
            lines.append("FORDS AND BRIDGES (kind at x,z, size width x depth):")
            for f in crossings[:25]:
                lines.append(f"- {f['kind']} at {f['x']},{f['z']} ({f['width']} x {f['depth']})")
        else:
            lines.append("FORDS AND BRIDGES: none detected.")
        if self.objectives:
            lines.append("OBJECTIVES (name at x,z, capture radius, held by):")
            for o in self.objectives:
                lines.append(f"- {o.get('name')} at {o.get('x')},{o.get('z')} "
                             f"(radius {o.get('captureRange', o.get('radius'))}, "
                             f"held by {o.get('side')}, {o.get('victoryPoints', '?')} victory points)")
        if show_rules and self.rules:
            lines.append("TERRAIN EFFECTS, as described by the game itself:")
            base = self.rules.get("Infantry", {})
            for terrain, hint in base.items():
                lines.append(f"- {terrain}: {hint}")
            for kind, table in self.rules.items():
                if kind == "Infantry":
                    continue
                for terrain, hint in table.items():
                    if hint != base.get(terrain):
                        lines.append(f"- {kind} on {terrain}: {hint}")
        return "\n".join(lines)
