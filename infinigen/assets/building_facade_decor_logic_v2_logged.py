"""Logged version of BuildingFacadeDecorV2Factory.

Mirrors ``infinigen/assets/building_facade_mat_logged.py``: in addition to
producing the same Blender geometry as the source factory, it records every
emitted primitive in ``self._semantic_specs`` so we can later replay it as:

  - a flat sanitized ``new_bbox`` / ``new_tri_prism`` / ``new_half_cylinder``
    script (``export_sanitized_script`` / ``export_logged_script``), and
  - a refactored ``Generator`` class that calls codebank helpers
    (``export_refactored_script``).

The geometry logic is intentionally a copy of
``infinigen/assets/building_facade_decor_logic_v2.py``. Helper signatures
gain a ``specs`` list parameter (alongside ``parts``) so the per-call
primitive output is captured in insertion order; everything else is
identical.
"""

import json
import os

import bpy
import numpy as np

from infinigen.assets.utils.object import (
    new_bbox,
    new_half_cylinder,
    new_tri_prism,
)
from infinigen.core.placement.factory import AssetFactory
from infinigen.core.util.math import FixedSeed


class BuildingFacadeDecorV2FactoryLogged(AssetFactory):
    """Logged Renaissance-palace facade decorator (v2).

    See ``BuildingFacadeDecorV2Factory`` for the geometry / composition
    semantics. This subclass behaves identically at run-time and additionally
    captures a per-primitive log so the asset can be re-emitted as a
    sanitized script or a codebank-style refactored script.
    """

    def __init__(self, factory_seed, coarse=False):
        super().__init__(factory_seed=factory_seed, coarse=coarse)
        with FixedSeed(factory_seed):
            # ---- massing ----
            self.depth = np.random.uniform(0.28, 0.42)
            self.ground_h = np.random.uniform(4.6, 5.8)
            self.mid_h = np.random.uniform(3.6, 4.4)
            self.top_h = np.random.uniform(2.8, 3.5)
            self.n_mid_floors = int(np.random.randint(2, 5))
            self.roof_thickness = np.random.uniform(0.22, 0.40)

            # ---- bay program ----
            self.target_bay_w = np.random.uniform(2.6, 3.6)
            self.end_bay_factor = np.random.uniform(1.10, 1.18)
            self.center_bay_factor = np.random.uniform(1.18, 1.30)
            self.side_margin = np.random.uniform(0.45, 0.85)

            # ---- shared window proportions ----
            self.win_w_frac = np.random.uniform(0.46, 0.58)
            self.ground_win_h_factor = 1.2
            self.mid_win_h_factor = 2.0
            self.square_win_h_factor = 1.0

            # ---- door ----
            self.door_w_factor = np.random.uniform(1.30, 1.55)
            self.door_h_factor = np.random.uniform(0.62, 0.74)

            # ---- ornament vocabulary ----
            self.sill_h = np.random.uniform(0.08, 0.13)
            self.lintel_h = np.random.uniform(0.16, 0.24)
            self.jamb_w = np.random.uniform(0.07, 0.12)
            self.crown_h = np.random.uniform(0.12, 0.20)
            self.crown_extra_overhang = np.random.uniform(0.06, 0.13)
            self.window_crown_gap = np.random.uniform(0.08, 0.18)
            self.door_crown_h = np.random.uniform(0.18, 0.28)
            self.door_crown_gap = np.random.uniform(0.10, 0.20)
            self.door_crown_extra_w = np.random.uniform(0.10, 0.20)

            # ---- pediment ----
            self.pediment_overhang = np.random.uniform(0.04, 0.09)
            self.pediment_gap = np.random.uniform(0.10, 0.20)
            self.pediment_rise_factor = np.random.uniform(0.22, 0.38)
            self.pediment_segments = 24

            # ---- depth offsets ----
            self.opening_protrusion = np.random.uniform(0.06, 0.11)
            self.ornament_depth_extra = np.random.uniform(0.02, 0.05)

            # ---- vertical layout of windows within a band ----
            self.ground_sill = np.random.uniform(0.85, 1.10)
            self.mid_window_clearance = np.random.uniform(0.55, 0.85)
            self.top_sill_frac = np.random.uniform(0.20, 0.32)
            self.inter_floor_gap = np.random.uniform(0.35, 0.60)

            self.height = (
                self.ground_h
                + self.n_mid_floors * self.mid_h
                + self.top_h
            )

        self._obj_to_label = {}
        self._label_counters = {}
        self._semantic_specs = None

    # ------------------------------------------------------------------ #
    # Naming / transform helpers (mirror v2)
    # ------------------------------------------------------------------ #

    def _next_name(self, label):
        idx = self._label_counters.get(label, 0)
        self._label_counters[label] = idx + 1
        name = f"{label}_{idx:02d}"
        self._obj_to_label[name] = label
        return name

    @staticmethod
    def _valid_extent(a, b, eps=1e-6):
        return (b - a) > eps

    @staticmethod
    def _transform_xy(x, y, rot_k, tx, ty):
        if rot_k == 0:
            xr, yr = x, y
        elif rot_k == 1:
            xr, yr = -y, x
        elif rot_k == 2:
            xr, yr = -x, -y
        else:
            xr, yr = y, -x
        return xr + tx, yr + ty

    def _transform_bounds(self, x0, x1, y0, y1, rot_k, tx, ty):
        corners = [
            self._transform_xy(x0, y0, rot_k, tx, ty),
            self._transform_xy(x0, y1, rot_k, tx, ty),
            self._transform_xy(x1, y0, rot_k, tx, ty),
            self._transform_xy(x1, y1, rot_k, tx, ty),
        ]
        xs = [c[0] for c in corners]
        ys = [c[1] for c in corners]
        return min(xs), max(xs), min(ys), max(ys)

    def _add_named_box(
        self, parts, specs, label, x0, x1, y0, y1, z0, z1,
        rot_k=0, tx=0.0, ty=0.0,
    ):
        if not (
            self._valid_extent(x0, x1)
            and self._valid_extent(y0, y1)
            and self._valid_extent(z0, z1)
        ):
            return
        wx0, wx1, wy0, wy1 = self._transform_bounds(
            x0, x1, y0, y1, rot_k, tx, ty,
        )
        obj = new_bbox(wx0, wx1, wy0, wy1, z0, z1)
        obj.name = self._next_name(label)
        obj["semantic_type"] = label
        parts.append(obj)
        specs.append(("box", label, (wx0, wx1, wy0, wy1, z0, z1)))

    def _local_axis_extrusion(self, lx0, ly0, lx1, ly1_thick, rot_k, tx, ty):
        bx0_w, by0_w = self._transform_xy(lx0, ly0, rot_k, tx, ty)
        bx1_w, by1_w = self._transform_xy(lx1, ly0, rot_k, tx, ty)
        tx0_w, ty0_w = self._transform_xy(lx0, ly1_thick, rot_k, tx, ty)
        dx_t = tx0_w - bx0_w
        dy_t = ty0_w - by0_w
        thickness = dy_t if abs(dy_t) > abs(dx_t) else dx_t
        return (bx0_w, by0_w), (bx1_w, by1_w), thickness

    def _add_tri_prism_named(
        self, parts, specs, label, lx0, lx1, ly0, ly1, lz_base, height,
        transform,
    ):
        if not (self._valid_extent(lx0, lx1) and self._valid_extent(ly0, ly1)):
            return
        if height <= 1e-6:
            return
        rot_k, tx, ty = transform
        (bx0_w, by0_w), (bx1_w, by1_w), thickness = self._local_axis_extrusion(
            lx0, ly0, lx1, ly1, rot_k, tx, ty,
        )
        obj = new_tri_prism(
            bx0_w, by0_w, lz_base,
            bx1_w, by1_w, lz_base,
            height=height, thickness=thickness,
        )
        obj.name = self._next_name(label)
        obj["semantic_type"] = label
        parts.append(obj)
        specs.append((
            "tri", label,
            (bx0_w, by0_w, lz_base, bx1_w, by1_w, lz_base, height, thickness),
        ))

    def _add_half_cyl_named(
        self, parts, specs, label, lx0, lx1, ly0, ly1, lz_base, height,
        transform, segments=None,
    ):
        if not (self._valid_extent(lx0, lx1) and self._valid_extent(ly0, ly1)):
            return
        if height <= 1e-6:
            return
        if segments is None:
            segments = self.pediment_segments
        rot_k, tx, ty = transform
        (bx0_w, by0_w), (bx1_w, by1_w), thickness = self._local_axis_extrusion(
            lx0, ly0, lx1, ly1, rot_k, tx, ty,
        )
        obj = new_half_cylinder(
            bx0_w, by0_w, lz_base,
            bx1_w, by1_w, lz_base,
            height=height, thickness=thickness, segments=segments,
        )
        obj.name = self._next_name(label)
        obj["semantic_type"] = label
        parts.append(obj)
        specs.append((
            "half", label,
            (
                bx0_w, by0_w, lz_base, bx1_w, by1_w, lz_base,
                height, thickness, segments,
            ),
        ))

    # ------------------------------------------------------------------ #
    # Story / bay program (identical to v2)
    # ------------------------------------------------------------------ #

    def _partition_floors(self):
        floors = [(0.0, self.ground_h)]
        z = self.ground_h
        for _ in range(self.n_mid_floors):
            floors.append((z, z + self.mid_h))
            z += self.mid_h
        floors.append((z, z + self.top_h))
        return floors

    @staticmethod
    def _story_kind(floor_idx, n_floors):
        if floor_idx == 0:
            return "GROUND"
        if floor_idx == n_floors - 1:
            return "TOP"
        return "MID"

    def _partition_bays(self, x_start, x_end, kind):
        span = max(0.0, x_end - x_start)
        if span <= 1e-6:
            return []

        if kind != "FRONT":
            n = max(1, int(round(span / max(self.target_bay_w, 1e-6))))
            w = span / n
            return [
                (x_start + i * w, x_start + (i + 1) * w, "REGULAR")
                for i in range(n)
            ]

        n_total = max(3, int(round(span / max(self.target_bay_w, 1e-6))))
        if n_total % 2 == 0:
            cand = []
            if n_total - 1 >= 3:
                cand.append(n_total - 1)
            cand.append(n_total + 1)
            n_total = min(
                cand,
                key=lambda n: abs(span / n - self.target_bay_w),
            )

        end_f = self.end_bay_factor
        cen_f = self.center_bay_factor
        n_normal = n_total - 3
        normal_w = span / (2.0 * end_f + cen_f + n_normal)
        end_w = end_f * normal_w
        center_w = cen_f * normal_w

        bays = []
        x = x_start
        center_idx = n_total // 2
        for i in range(n_total):
            if i == 0 or i == n_total - 1:
                w, k = end_w, "END"
            elif i == center_idx:
                w, k = center_w, "CENTER"
            else:
                w, k = normal_w, "NORMAL"
            bays.append((x, x + w, k))
            x += w
        return bays

    def _facade_window_width(self, bays, kind):
        if not bays:
            return 0.0
        if kind == "FRONT":
            normal_w = next(
                (b[1] - b[0] for b in bays if b[2] == "NORMAL"),
                bays[0][1] - bays[0][0],
            )
            return self.win_w_frac * normal_w
        return self.win_w_frac * (bays[0][1] - bays[0][0])

    def _centered_window_x(self, bay_x, win_w):
        bx0, bx1 = bay_x
        cx = 0.5 * (bx0 + bx1)
        wx0 = max(bx0, cx - win_w / 2.0)
        wx1 = min(bx1, cx + win_w / 2.0)
        return wx0, wx1

    def _opening_y_bounds(self, y0, y1):
        wy0 = y0 - self.opening_protrusion
        wy1 = y1 + self.opening_protrusion
        owy0 = wy0 - self.ornament_depth_extra
        owy1 = wy1 + self.ornament_depth_extra
        return wy0, wy1, owy0, owy1

    # ------------------------------------------------------------------ #
    # Per-opening placers (identical to v2; specs threaded through)
    # ------------------------------------------------------------------ #

    def _place_square_window(
        self, parts, specs, bay_x, band_z, y0, y1, transform, win_w,
    ):
        z0, z1 = band_z
        bh = z1 - z0
        win_h = self.square_win_h_factor * win_w
        sill = min(self.top_sill_frac * bh, 0.45 * bh)
        wz0 = z0 + sill
        wz1 = wz0 + win_h
        if wz1 > z1 - self.inter_floor_gap:
            wz1 = z1 - self.inter_floor_gap
            wz0 = wz1 - win_h
        wx0, wx1 = self._centered_window_x(bay_x, win_w)
        if not (self._valid_extent(wx0, wx1) and self._valid_extent(wz0, wz1)):
            return
        rot_k, tx, ty = transform
        wy0, wy1, _, _ = self._opening_y_bounds(y0, y1)
        self._add_named_box(
            parts, specs, "window_panel",
            wx0, wx1, wy0, wy1, wz0, wz1, rot_k, tx, ty,
        )

    def _place_ground_window(
        self, parts, specs, bay_x, band_z, y0, y1, transform, win_w,
    ):
        z0, z1 = band_z
        bh = z1 - z0
        win_h = self.ground_win_h_factor * win_w

        head_room = (
            self.lintel_h + self.window_crown_gap
            + self.crown_h + self.inter_floor_gap
        )
        sill_clearance = max(self.ground_sill, self.sill_h + 0.05)
        wz0 = z0 + sill_clearance
        wz1 = wz0 + win_h
        if wz1 > z1 - head_room:
            wz1 = z1 - head_room
            wz0 = max(z0 + self.sill_h + 0.05, wz1 - win_h)

        wx0, wx1 = self._centered_window_x(bay_x, win_w)
        if not (self._valid_extent(wx0, wx1) and self._valid_extent(wz0, wz1)):
            return
        rot_k, tx, ty = transform
        wy0, wy1, owy0, owy1 = self._opening_y_bounds(y0, y1)

        self._add_named_box(
            parts, specs, "window_panel",
            wx0, wx1, wy0, wy1, wz0, wz1, rot_k, tx, ty,
        )
        self._add_named_box(
            parts, specs, "sill",
            wx0, wx1,
            owy0, owy1, wz0 - self.sill_h, wz0,
            rot_k, tx, ty,
        )
        self._add_named_box(
            parts, specs, "jamb",
            wx0 - self.jamb_w, wx0,
            owy0, owy1, wz0 - self.sill_h, wz1 + self.lintel_h,
            rot_k, tx, ty,
        )
        self._add_named_box(
            parts, specs, "jamb",
            wx1, wx1 + self.jamb_w,
            owy0, owy1, wz0 - self.sill_h, wz1 + self.lintel_h,
            rot_k, tx, ty,
        )
        self._add_named_box(
            parts, specs, "lintel",
            wx0, wx1,
            owy0, owy1, wz1, wz1 + self.lintel_h,
            rot_k, tx, ty,
        )
        crown_extra = self.jamb_w + self.crown_extra_overhang
        crown_z0 = wz1 + self.lintel_h + self.window_crown_gap
        crown_z1 = crown_z0 + self.crown_h
        self._add_named_box(
            parts, specs, "window_crown",
            wx0 - crown_extra, wx1 + crown_extra,
            owy0, owy1, crown_z0, crown_z1,
            rot_k, tx, ty,
        )

    def _place_pedimented_window(
        self, parts, specs, bay_x, band_z, y0, y1, transform, win_w,
        pediment_kind,
    ):
        z0, z1 = band_z
        bh = z1 - z0
        win_h = self.mid_win_h_factor * win_w
        ped_rise = self.pediment_rise_factor * win_w

        needed = (
            self.mid_window_clearance
            + win_h
            + self.pediment_gap
            + ped_rise
            + self.inter_floor_gap
        )
        if needed > bh:
            win_h = max(
                0.6 * win_w,
                bh
                - self.mid_window_clearance
                - self.pediment_gap
                - ped_rise
                - self.inter_floor_gap,
            )

        wz0 = z0 + self.mid_window_clearance
        wz1 = wz0 + win_h

        wx0, wx1 = self._centered_window_x(bay_x, win_w)
        if not (self._valid_extent(wx0, wx1) and self._valid_extent(wz0, wz1)):
            return
        rot_k, tx, ty = transform
        wy0, wy1, owy0, owy1 = self._opening_y_bounds(y0, y1)

        self._add_named_box(
            parts, specs, "window_panel",
            wx0, wx1, wy0, wy1, wz0, wz1, rot_k, tx, ty,
        )

        ped_lx0 = wx0 - self.pediment_overhang
        ped_lx1 = wx1 + self.pediment_overhang
        ped_z = wz1 + self.pediment_gap
        if pediment_kind == "triangular":
            self._add_tri_prism_named(
                parts, specs, "tri_pediment",
                ped_lx0, ped_lx1, owy0, owy1, ped_z,
                height=ped_rise, transform=transform,
            )
        else:
            self._add_half_cyl_named(
                parts, specs, "round_pediment",
                ped_lx0, ped_lx1, owy0, owy1, ped_z,
                height=ped_rise, transform=transform,
            )

    def _place_door(
        self, parts, specs, bay_x, band_z, y0, y1, transform, win_w,
    ):
        bx0, bx1 = bay_x
        z0, z1 = band_z
        bw = bx1 - bx0
        bh = z1 - z0

        door_w = min(self.door_w_factor * win_w, 0.85 * bw)
        head_room = (
            self.lintel_h + self.door_crown_gap
            + self.door_crown_h + self.inter_floor_gap
        )
        door_h = min(self.door_h_factor * bh, bh - head_room)
        if door_h <= 0.5 * win_w:
            door_h = min(self.door_h_factor * bh, bh - 0.05)
            head_room = 0.0

        cx = 0.5 * (bx0 + bx1)
        dx0 = cx - door_w / 2.0
        dx1 = cx + door_w / 2.0
        dz0 = z0
        dz1 = dz0 + door_h
        if not (self._valid_extent(dx0, dx1) and self._valid_extent(dz0, dz1)):
            return

        rot_k, tx, ty = transform
        wy0, wy1, owy0, owy1 = self._opening_y_bounds(y0, y1)

        self._add_named_box(
            parts, specs, "door_panel",
            dx0, dx1, wy0, wy1, dz0, dz1, rot_k, tx, ty,
        )

        if head_room <= 0.0:
            jamb_top = dz1
        else:
            jamb_top = dz1 + self.lintel_h

        self._add_named_box(
            parts, specs, "door_jamb",
            dx0 - self.jamb_w, dx0,
            owy0, owy1, dz0, jamb_top,
            rot_k, tx, ty,
        )
        self._add_named_box(
            parts, specs, "door_jamb",
            dx1, dx1 + self.jamb_w,
            owy0, owy1, dz0, jamb_top,
            rot_k, tx, ty,
        )

        if head_room <= 0.0:
            return

        self._add_named_box(
            parts, specs, "door_lintel",
            dx0, dx1,
            owy0, owy1, dz1, dz1 + self.lintel_h,
            rot_k, tx, ty,
        )
        crown_extra = self.jamb_w + self.door_crown_extra_w
        crown_z0 = dz1 + self.lintel_h + self.door_crown_gap
        crown_z1 = crown_z0 + self.door_crown_h
        self._add_named_box(
            parts, specs, "door_crown",
            dx0 - crown_extra, dx1 + crown_extra,
            owy0, owy1, crown_z0, crown_z1,
            rot_k, tx, ty,
        )

    # ------------------------------------------------------------------ #
    # Facade orchestration (identical structure to v2)
    # ------------------------------------------------------------------ #

    def _build_facade(
        self, parts, specs, x_start, x_end, kind, y0, y1, transform,
    ):
        floors = self._partition_floors()
        n_floors = len(floors)
        bays = self._partition_bays(
            x_start + self.side_margin,
            x_end - self.side_margin,
            kind,
        )
        n_bays = len(bays)
        if n_bays == 0:
            return
        win_w = self._facade_window_width(bays, kind)
        if win_w <= 1e-6:
            return
        center_idx = n_bays // 2

        for floor_idx, band_z in enumerate(floors):
            story = self._story_kind(floor_idx, n_floors)
            for bay_idx, (bx0, bx1, _bk) in enumerate(bays):
                bay = (bx0, bx1)
                if kind != "FRONT":
                    self._place_square_window(
                        parts, specs, bay, band_z, y0, y1, transform, win_w,
                    )
                    continue
                if story == "GROUND":
                    if bay_idx == center_idx:
                        self._place_door(
                            parts, specs, bay, band_z, y0, y1, transform,
                            win_w,
                        )
                    else:
                        self._place_ground_window(
                            parts, specs, bay, band_z, y0, y1, transform,
                            win_w,
                        )
                elif story == "TOP":
                    self._place_square_window(
                        parts, specs, bay, band_z, y0, y1, transform, win_w,
                    )
                else:
                    pediment = (
                        "triangular"
                        if (floor_idx + bay_idx) % 2 == 1
                        else "round"
                    )
                    self._place_pedimented_window(
                        parts, specs, bay, band_z, y0, y1, transform, win_w,
                        pediment_kind=pediment,
                    )

    # ------------------------------------------------------------------ #
    # Entry point
    # ------------------------------------------------------------------ #

    def create_asset(self, **params):
        self._obj_to_label = {}
        self._label_counters = {}

        self.front_width = float(
            params.get("front_width", np.random.uniform(14.0, 24.0))
        )
        self.side_width = float(
            params.get("side_width", np.random.uniform(11.0, 18.0))
        )

        parts = []
        specs = []

        facade_configs = [
            (0.0, self.front_width, "FRONT", (0, 0.0, 0.0)),
            (0.0, self.front_width, "BACK",
                (2, self.front_width, self.side_width)),
            (self.depth, self.side_width - self.depth, "SIDE",
                (1, self.front_width, 0.0)),
            (self.depth, self.side_width - self.depth, "SIDE",
                (3, 0.0, self.side_width)),
        ]

        for x_start, x_end, kind, transform in facade_configs:
            rot_k, tx, ty = transform
            self._add_named_box(
                parts, specs, "wall",
                x_start, x_end, 0.0, self.depth, 0.0, self.height,
                rot_k, tx, ty,
            )
            self._build_facade(
                parts, specs, x_start, x_end, kind, 0.0, self.depth, transform,
            )

        self._add_named_box(
            parts, specs, "roof",
            0.0, self.front_width, 0.0, self.side_width,
            self.height, self.height + self.roof_thickness,
        )

        anchor = bpy.data.objects.new("building_facade_decor_v2_logged", None)
        bpy.context.collection.objects.link(anchor)

        self._semantic_specs = {
            "meta": {
                "front_width": self.front_width,
                "side_width": self.side_width,
                "height": self.height,
                "depth": self.depth,
                "n_mid_floors": self.n_mid_floors,
            },
            "parts": specs,
        }
        return anchor

    # ------------------------------------------------------------------ #
    # Export helpers
    # ------------------------------------------------------------------ #

    def write_obj_to_label(self, output_dir):
        os.makedirs(output_dir, exist_ok=True)
        path = os.path.join(str(output_dir), "obj_to_label.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self._obj_to_label, f, indent=2)
        return path

    def export_logged_script(self, output_path: str) -> str:
        if self._semantic_specs is None:
            raise RuntimeError(
                "No logged specs found. Run create_asset / spawn_asset first."
            )

        parts_log = self._semantic_specs["parts"]

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(
                "from infinigen.assets.utils.object import ("
                "new_bbox, new_half_cylinder, new_tri_prism)\n\n"
            )
            f.write("# Renaissance v2 facade decor (each element is its own object)\n\n")

            counter = {}
            for kind, label, payload in parts_log:
                idx = counter.get(label, 0)
                counter[label] = idx + 1
                name = f"{label}_{idx:02d}"
                if kind == "box":
                    x0, x1, y0, y1, z0, z1 = payload
                    f.write(
                        f"obj = new_bbox("
                        f"{x0:.9f}, {x1:.9f}, {y0:.9f}, {y1:.9f}, "
                        f"{z0:.9f}, {z1:.9f})\n"
                    )
                elif kind == "tri":
                    bx0, by0, bz, bx1, by1, bz_, h, t = payload
                    f.write(
                        f"obj = new_tri_prism("
                        f"{bx0:.9f}, {by0:.9f}, {bz:.9f}, "
                        f"{bx1:.9f}, {by1:.9f}, {bz_:.9f}, "
                        f"height={h:.9f}, thickness={t:.9f})\n"
                    )
                elif kind == "half":
                    bx0, by0, bz, bx1, by1, bz_, h, t, segs = payload
                    f.write(
                        f"obj = new_half_cylinder("
                        f"{bx0:.9f}, {by0:.9f}, {bz:.9f}, "
                        f"{bx1:.9f}, {by1:.9f}, {bz_:.9f}, "
                        f"height={h:.9f}, thickness={t:.9f}, "
                        f"segments={int(segs)})\n"
                    )
                else:
                    raise ValueError(
                        f"Unknown spec kind {kind!r} for label {label!r}"
                    )
                f.write(f'obj.name = "{name}"\n\n')

        return output_path

    def export_sanitized_script(self, output_path: str) -> str:
        return self.export_logged_script(output_path)

    # ------------------------------------------------------------------ #
    # Refactored-script export (mirrors building_facade_mat_logged)
    # ------------------------------------------------------------------ #

    def _get_params_dict(self) -> dict:
        return {
            # massing
            "depth": float(self.depth),
            "ground_h": float(self.ground_h),
            "mid_h": float(self.mid_h),
            "top_h": float(self.top_h),
            "n_mid_floors": int(self.n_mid_floors),
            "roof_thickness": float(self.roof_thickness),
            # bay program
            "target_bay_w": float(self.target_bay_w),
            "end_bay_factor": float(self.end_bay_factor),
            "center_bay_factor": float(self.center_bay_factor),
            "side_margin": float(self.side_margin),
            # window proportions
            "win_w_frac": float(self.win_w_frac),
            "ground_win_h_factor": float(self.ground_win_h_factor),
            "mid_win_h_factor": float(self.mid_win_h_factor),
            "square_win_h_factor": float(self.square_win_h_factor),
            # door
            "door_w_factor": float(self.door_w_factor),
            "door_h_factor": float(self.door_h_factor),
            # ornament vocabulary
            "sill_h": float(self.sill_h),
            "lintel_h": float(self.lintel_h),
            "jamb_w": float(self.jamb_w),
            "crown_h": float(self.crown_h),
            "crown_extra_overhang": float(self.crown_extra_overhang),
            "window_crown_gap": float(self.window_crown_gap),
            "door_crown_h": float(self.door_crown_h),
            "door_crown_gap": float(self.door_crown_gap),
            "door_crown_extra_w": float(self.door_crown_extra_w),
            # pediment
            "pediment_overhang": float(self.pediment_overhang),
            "pediment_gap": float(self.pediment_gap),
            "pediment_rise_factor": float(self.pediment_rise_factor),
            "pediment_segments": int(self.pediment_segments),
            # depth offsets
            "opening_protrusion": float(self.opening_protrusion),
            "ornament_depth_extra": float(self.ornament_depth_extra),
            # vertical layout
            "ground_sill": float(self.ground_sill),
            "mid_window_clearance": float(self.mid_window_clearance),
            "top_sill_frac": float(self.top_sill_frac),
            "inter_floor_gap": float(self.inter_floor_gap),
            # derived / per-call
            "height": float(self.height),
            "front_width": float(self.front_width),
            "side_width": float(self.side_width),
        }

    def export_refactored_script(self, output_path: str) -> str:
        """Emit a ``Generator`` class with only ``__init__`` and ``generate``.

        ``generate()`` mirrors ``BuildingFacadeDecorV2Factory.create_asset``:
        a ``facade_configs`` list literal driving a four-iteration loop that
        emits one wall + one ``_build_facade`` per side, then a final roof
        slab. Codebank state (counters + label map + every facade param) is
        bundled into two local dicts at the top of ``generate()``.
        """
        if self._semantic_specs is None:
            raise RuntimeError(
                "No logged specs found. Run create_asset / spawn_asset first."
            )

        p = self._get_params_dict()

        def fmt(v):
            if isinstance(v, bool):
                return str(v)
            if isinstance(v, str):
                return f'"{v}"'
            if isinstance(v, (list, tuple)):
                return str(list(v))
            return str(v)

        # Kwarg lists must mirror the keyword-only blocks emitted by the AST
        # extractor for ``BuildingFacadeDecorV2Factory``. If a self.X
        # reference is added/removed inside one of these methods, regenerate
        # codebank.py and update the matching list here.
        box_kwargs = ["_label_counters", "_obj_to_label"]
        facade_kwargs = [
            "_label_counters", "_obj_to_label",
            "center_bay_factor", "crown_extra_overhang", "crown_h",
            "door_crown_extra_w", "door_crown_gap", "door_crown_h",
            "door_h_factor", "door_w_factor",
            "end_bay_factor", "ground_h", "ground_sill",
            "ground_win_h_factor", "inter_floor_gap", "jamb_w",
            "lintel_h", "mid_h", "mid_window_clearance",
            "mid_win_h_factor", "n_mid_floors", "opening_protrusion",
            "ornament_depth_extra", "pediment_gap", "pediment_overhang",
            "pediment_rise_factor", "pediment_segments",
            "side_margin", "sill_h", "square_win_h_factor",
            "target_bay_w", "top_h", "top_sill_frac",
            "win_w_frac", "window_crown_gap",
        ]

        def kw_dict_literal(kwargs: list) -> str:
            return "dict(" + ", ".join(f"{k}=self.{k}" for k in kwargs) + ")"

        with open(output_path, "w", encoding="utf-8") as f:
            f.write("from codebank import _add_named_box, _build_facade\n\n\n")
            f.write("class Generator:\n\n")

            f.write("    def __init__(self):\n")
            for k, v in p.items():
                f.write(f"        self.{k} = {fmt(v)}\n")
            f.write("        self._obj_to_label = {}\n")
            f.write("        self._label_counters = {}\n")
            f.write("\n")

            f.write("    def generate(self):\n")
            f.write("        parts = []\n")
            f.write(f"        box_kw = {kw_dict_literal(box_kwargs)}\n")
            f.write(f"        facade_kw = {kw_dict_literal(facade_kwargs)}\n\n")
            f.write(
                "        # Side walls are inset by self.depth on both ends so the four walls\n"
                "        # meet at the corners without overlap. Front/back walls own the\n"
                "        # corner volumes; the side walls stop short of them.\n"
            )
            f.write("        facade_configs = [\n")
            f.write(
                '            (0.0, self.front_width, "FRONT",'
                ' (0, 0.0, 0.0)),\n'
            )
            f.write(
                '            (0.0, self.front_width, "BACK",'
                ' (2, self.front_width, self.side_width)),\n'
            )
            f.write(
                '            (self.depth, self.side_width - self.depth, "SIDE",'
                ' (1, self.front_width, 0.0)),\n'
            )
            f.write(
                '            (self.depth, self.side_width - self.depth, "SIDE",'
                ' (3, 0.0, self.side_width)),\n'
            )
            f.write("        ]\n\n")

            f.write(
                "        for x_start, x_end, kind, transform in facade_configs:\n"
                "            rot_k, tx, ty = transform\n"
                "            _add_named_box(\n"
                '                parts, "wall",\n'
                "                x_start, x_end, 0.0, self.depth, 0.0, self.height,\n"
                "                rot_k, tx, ty,\n"
                "                **box_kw,\n"
                "            )\n"
                "            _build_facade(\n"
                "                parts, x_start, x_end, kind, 0.0, self.depth, transform,\n"
                "                **facade_kw,\n"
                "            )\n\n"
            )

            f.write(
                "        _add_named_box(\n"
                '            parts, "roof",\n'
                "            0.0, self.front_width, 0.0, self.side_width,\n"
                "            self.height, self.height + self.roof_thickness,\n"
                "            **box_kw,\n"
                "        )\n"
                "        return parts\n\n\n"
            )

            f.write('if __name__ == "__main__":\n')
            f.write("    Generator().generate()\n")

        return output_path
