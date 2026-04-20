"""Renaissance-palace-inspired facade decorator (v2).

Composition is location-driven, following the program from the prompt:

  - 3 story kinds:    GROUND / MID / TOP
  - 4 opening types:  door, ground_window, square_window,
                      triangular-pedimented window, round-pedimented window
  - bay kinds:        END / CENTER / NORMAL with widening factors
  - alternation:      MID stories alternate triangular- and round-pedimented
                      windows by ODD(floor + bay)
  - non-FRONT walls:  keep simple square windows everywhere

All windows on the same facade share a single window width so columns line
up vertically. Window heights are tied to that width:

  square_window  : h = 1.0 * w
  ground_window  : h = 1.2 * w
  mid window     : h = 2.0 * w

The four walls are inset at the corners (front/back walls own the corner
volumes, side walls stop short by `self.depth`), mirroring
`BuildingFacadeMatFactory`, so the four wall slabs do not overlap.
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


class BuildingFacadeDecorV2Factory(AssetFactory):
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

            # ---- bay program (Renaissance grid: END / CENTER wider) ----
            self.target_bay_w = np.random.uniform(2.6, 3.6)
            self.end_bay_factor = np.random.uniform(1.10, 1.18)
            self.center_bay_factor = np.random.uniform(1.18, 1.30)
            self.side_margin = np.random.uniform(0.45, 0.85)

            # ---- shared window proportions (per spec) ----
            # win_w = win_w_frac * NORMAL bay width on FRONT,
            # or win_w_frac * (single bay width) on non-FRONT.
            self.win_w_frac = np.random.uniform(0.46, 0.58)
            self.ground_win_h_factor = 1.2  # spec: ground h = 1.2 w
            self.mid_win_h_factor = 2.0     # spec: mid    h = 2.0 w
            self.square_win_h_factor = 1.0  # spec: square h = 1.0 w

            # ---- door ----
            self.door_w_factor = np.random.uniform(1.30, 1.55)
            self.door_h_factor = np.random.uniform(0.62, 0.74)

            # ---- ornament vocabulary ----
            # Convention (jambs touch the panel, no awkward inner gap):
            #   sill / lintel x-range = panel x-range exactly
            #   jamb            x-range = [panel-jw, panel] (touches panel)
            #   crown          x-range = [panel - jw - crown_extra,
            #                              panel + jw + crown_extra]
            self.sill_h = np.random.uniform(0.08, 0.13)
            self.lintel_h = np.random.uniform(0.16, 0.24)
            self.jamb_w = np.random.uniform(0.07, 0.12)
            self.crown_h = np.random.uniform(0.12, 0.20)
            self.crown_extra_overhang = np.random.uniform(0.06, 0.13)
            # Vertical gap between window-lintel top and window-crown bottom
            # (mirrors door_crown_gap so the crown floats above the lintel).
            self.window_crown_gap = np.random.uniform(0.08, 0.18)
            self.door_crown_h = np.random.uniform(0.18, 0.28)
            self.door_crown_gap = np.random.uniform(0.10, 0.20)
            self.door_crown_extra_w = np.random.uniform(0.10, 0.20)

            # ---- pediment (round / triangle), detached above mid windows.
            # Round pediment is now a half-ellipse via new_half_cylinder, so
            # both pediment kinds share a single, tunable rise. ----
            self.pediment_overhang = np.random.uniform(0.04, 0.09)
            self.pediment_gap = np.random.uniform(0.10, 0.20)
            # Flatter Renaissance-style pediments (rise = factor * win_w, so
            # rise / half-width = 2 * factor in [0.44, 0.76]).
            self.pediment_rise_factor = np.random.uniform(0.22, 0.38)
            self.pediment_segments = 24

            # ---- depth offsets ----
            self.opening_protrusion = np.random.uniform(0.06, 0.11)
            self.ornament_depth_extra = np.random.uniform(0.02, 0.05)

            # ---- vertical layout of windows within a band ----
            # (Mid windows have NO sill per spec, so mid_window_clearance
            # is the bare floor-to-panel offset.)
            self.ground_sill = np.random.uniform(0.85, 1.10)
            self.mid_window_clearance = np.random.uniform(0.55, 0.85)
            self.top_sill_frac = np.random.uniform(0.20, 0.32)
            # Larger inter-floor breathing room so pediments / lintels /
            # crowns never kiss the floor band above.
            self.inter_floor_gap = np.random.uniform(0.35, 0.60)

            self.height = (
                self.ground_h
                + self.n_mid_floors * self.mid_h
                + self.top_h
            )

        self._obj_to_label = {}
        self._label_counters = {}

    # ------------------------------------------------------------------ #
    # Naming / transform helpers (mirror BuildingFacadeMat / decor v1)
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
        self, parts, label, x0, x1, y0, y1, z0, z1,
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

    def _local_axis_extrusion(self, lx0, ly0, lx1, ly1_thick, rot_k, tx, ty):
        """Project two local segments to world: a base segment from (lx0, ly0)
        to (lx1, ly0), plus a thickness-end at (lx0, ly1_thick).

        Returns ((bx0_w, by0_w), (bx1_w, by1_w), thickness_signed).
        Exactly one of (dx, dy) between (bx0_w, by0_w) and the thickness-end
        is nonzero under axis-aligned rotation; that signed value is the
        ``thickness`` to pass to the auto-axis primitives.
        """
        bx0_w, by0_w = self._transform_xy(lx0, ly0, rot_k, tx, ty)
        bx1_w, by1_w = self._transform_xy(lx1, ly0, rot_k, tx, ty)
        tx0_w, ty0_w = self._transform_xy(lx0, ly1_thick, rot_k, tx, ty)
        dx_t = tx0_w - bx0_w
        dy_t = ty0_w - by0_w
        thickness = dy_t if abs(dy_t) > abs(dx_t) else dx_t
        return (bx0_w, by0_w), (bx1_w, by1_w), thickness

    def _add_tri_prism_named(
        self, parts, label, lx0, lx1, ly0, ly1, lz_base, height, transform,
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

    def _add_half_cyl_named(
        self, parts, label, lx0, lx1, ly0, ly1, lz_base, height, transform,
        segments=None,
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

    # ------------------------------------------------------------------ #
    # Story / bay program
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
        """Return [(bx0, bx1, bay_kind), ...].

        FRONT facade: odd number of bays; END (first/last) and CENTER (middle)
        are wider than NORMAL. Window widths derived from NORMAL bay width.

        Non-FRONT facades: equal-width bays, all "REGULAR".
        """
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

        # FRONT: force odd, >= 3 (need at least END/CENTER/END structure)
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
        n_normal = n_total - 3  # 2 END + 1 CENTER
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
        """Single window width shared by every opening on this facade."""
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

    # ------------------------------------------------------------------ #
    # Per-opening placers
    # ------------------------------------------------------------------ #

    def _opening_y_bounds(self, y0, y1):
        wy0 = y0 - self.opening_protrusion
        wy1 = y1 + self.opening_protrusion
        owy0 = wy0 - self.ornament_depth_extra
        owy1 = wy1 + self.ornament_depth_extra
        return wy0, wy1, owy0, owy1

    def _place_square_window(
        self, parts, bay_x, band_z, y0, y1, transform, win_w,
    ):
        """TOP-floor window or any non-FRONT window: just window_panel."""
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
            parts, "window_panel",
            wx0, wx1, wy0, wy1, wz0, wz1, rot_k, tx, ty,
        )

    def _place_ground_window(
        self, parts, bay_x, band_z, y0, y1, transform, win_w,
    ):
        """FRONT GROUND non-CENTER: window_panel + sill + jambs + lintel +
        window_crown (above the lintel with a vertical gap, wider than the
        jamb stack so it visibly caps the composition)."""
        z0, z1 = band_z
        bh = z1 - z0
        win_h = self.ground_win_h_factor * win_w

        # Reserve room above the window for lintel + crown_gap + crown
        # plus the inter-floor breathing room.
        head_room = (
            self.lintel_h + self.window_crown_gap
            + self.crown_h + self.inter_floor_gap
        )
        # Sill clearance must leave room for the sill cuboid below the panel.
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
            parts, "window_panel",
            wx0, wx1, wy0, wy1, wz0, wz1, rot_k, tx, ty,
        )
        # Sill: matches panel x-range exactly (sits directly under panel).
        self._add_named_box(
            parts, "sill",
            wx0, wx1,
            owy0, owy1, wz0 - self.sill_h, wz0,
            rot_k, tx, ty,
        )
        # Jambs touch panel on the inside and span the FULL composition
        # height -- bottom of sill to top of lintel. Sill / lintel use the
        # panel x-range exactly, so the jambs (just outside the panel)
        # never intersect them in x.
        self._add_named_box(
            parts, "jamb",
            wx0 - self.jamb_w, wx0,
            owy0, owy1, wz0 - self.sill_h, wz1 + self.lintel_h,
            rot_k, tx, ty,
        )
        self._add_named_box(
            parts, "jamb",
            wx1, wx1 + self.jamb_w,
            owy0, owy1, wz0 - self.sill_h, wz1 + self.lintel_h,
            rot_k, tx, ty,
        )
        # Lintel: matches panel x-range exactly, sits directly above panel.
        self._add_named_box(
            parts, "lintel",
            wx0, wx1,
            owy0, owy1, wz1, wz1 + self.lintel_h,
            rot_k, tx, ty,
        )
        # Window crown: floats above the lintel with a vertical gap,
        # extends beyond the jamb stack so it visibly caps the composition.
        crown_extra = self.jamb_w + self.crown_extra_overhang
        crown_z0 = wz1 + self.lintel_h + self.window_crown_gap
        crown_z1 = crown_z0 + self.crown_h
        self._add_named_box(
            parts, "window_crown",
            wx0 - crown_extra, wx1 + crown_extra,
            owy0, owy1, crown_z0, crown_z1,
            rot_k, tx, ty,
        )

    def _place_pedimented_window(
        self, parts, bay_x, band_z, y0, y1, transform, win_w, pediment_kind,
    ):
        """FRONT MID window: window_panel + detached pediment only.

        pediment_kind in {"triangular", "round"}. Both pediment kinds share a
        single rise (= self.pediment_rise_factor * win_w) -- the round one
        is now a half-ELLIPSE via new_half_cylinder(height=...), so its rise
        no longer has to equal half its base length.

        No sill, no jambs (per spec).
        """
        z0, z1 = band_z
        bh = z1 - z0
        win_h = self.mid_win_h_factor * win_w
        ped_rise = self.pediment_rise_factor * win_w

        # Stack from band bottom: clearance + win_h + pediment_gap + ped_rise
        # + inter_floor_gap. Shrink win_h first if the band is too short.
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
            parts, "window_panel",
            wx0, wx1, wy0, wy1, wz0, wz1, rot_k, tx, ty,
        )

        # Detached pediment slightly wider than the window panel.
        ped_lx0 = wx0 - self.pediment_overhang
        ped_lx1 = wx1 + self.pediment_overhang
        ped_z = wz1 + self.pediment_gap
        if pediment_kind == "triangular":
            self._add_tri_prism_named(
                parts, "tri_pediment",
                ped_lx0, ped_lx1, owy0, owy1, ped_z,
                height=ped_rise, transform=transform,
            )
        else:
            self._add_half_cyl_named(
                parts, "round_pediment",
                ped_lx0, ped_lx1, owy0, owy1, ped_z,
                height=ped_rise, transform=transform,
            )

    def _place_door(self, parts, bay_x, band_z, y0, y1, transform, win_w):
        """FRONT GROUND CENTER: door_panel + door_jamb + door_lintel +
        door_crown.

        Door jambs are aligned with the TOP of the door_lintel (no gap).
        Lintel matches door panel x-range (no horizontal overhang) so the
        jambs can extend up alongside it without clashing in x.
        """
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
            # Band too short for the full ornament stack; fall back to a
            # bare door_panel that still fits.
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
            parts, "door_panel",
            dx0, dx1, wy0, wy1, dz0, dz1, rot_k, tx, ty,
        )

        if head_room <= 0.0:
            # Bare-door fallback: jambs span just the door body.
            jamb_top = dz1
        else:
            jamb_top = dz1 + self.lintel_h

        # Door jambs touch panel on the inside; reach lintel top per spec.
        self._add_named_box(
            parts, "door_jamb",
            dx0 - self.jamb_w, dx0,
            owy0, owy1, dz0, jamb_top,
            rot_k, tx, ty,
        )
        self._add_named_box(
            parts, "door_jamb",
            dx1, dx1 + self.jamb_w,
            owy0, owy1, dz0, jamb_top,
            rot_k, tx, ty,
        )

        if head_room <= 0.0:
            return

        # Door lintel: matches door panel x-range so it sits "between" the
        # jambs (which extend up to the same height) without overlapping.
        self._add_named_box(
            parts, "door_lintel",
            dx0, dx1,
            owy0, owy1, dz1, dz1 + self.lintel_h,
            rot_k, tx, ty,
        )
        # Door crown: floats above lintel with vertical gap; wider than
        # the door + jambs so it caps the composition cleanly.
        crown_extra = self.jamb_w + self.door_crown_extra_w
        crown_z0 = dz1 + self.lintel_h + self.door_crown_gap
        crown_z1 = crown_z0 + self.door_crown_h
        self._add_named_box(
            parts, "door_crown",
            dx0 - crown_extra, dx1 + crown_extra,
            owy0, owy1, crown_z0, crown_z1,
            rot_k, tx, ty,
        )

    # ------------------------------------------------------------------ #
    # Facade orchestration
    # ------------------------------------------------------------------ #

    def _build_facade(self, parts, x_start, x_end, kind, y0, y1, transform):
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
                        parts, bay, band_z, y0, y1, transform, win_w,
                    )
                    continue
                if story == "GROUND":
                    if bay_idx == center_idx:
                        self._place_door(
                            parts, bay, band_z, y0, y1, transform, win_w,
                        )
                    else:
                        self._place_ground_window(
                            parts, bay, band_z, y0, y1, transform, win_w,
                        )
                elif story == "TOP":
                    self._place_square_window(
                        parts, bay, band_z, y0, y1, transform, win_w,
                    )
                else:  # MID
                    pediment = (
                        "triangular"
                        if (floor_idx + bay_idx) % 2 == 1
                        else "round"
                    )
                    self._place_pedimented_window(
                        parts, bay, band_z, y0, y1, transform, win_w,
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

        # Side walls inset by self.depth on both ends so the four wall slabs
        # meet at the corners without overlapping. Front/back own corners.
        facade_configs = [
            (0.0, self.front_width, "FRONT", (0, 0.0, 0.0)),
            (0.0, self.front_width, "BACK",  (2, self.front_width, self.side_width)),
            (self.depth, self.side_width - self.depth, "SIDE",
                (1, self.front_width, 0.0)),
            (self.depth, self.side_width - self.depth, "SIDE",
                (3, 0.0, self.side_width)),
        ]

        for x_start, x_end, kind, transform in facade_configs:
            rot_k, tx, ty = transform
            self._add_named_box(
                parts, "wall",
                x_start, x_end, 0.0, self.depth, 0.0, self.height,
                rot_k, tx, ty,
            )
            self._build_facade(
                parts, x_start, x_end, kind, 0.0, self.depth, transform,
            )

        # Roof slab capping the four walls.
        self._add_named_box(
            parts, "roof",
            0.0, self.front_width, 0.0, self.side_width,
            self.height, self.height + self.roof_thickness,
        )

        # No parent linking. Return a small anchor empty so AssetFactory's
        # spawn_asset has a single object to rename / position; the labeled
        # parts stay as top-level scene objects.
        anchor = bpy.data.objects.new("building_facade_decor_v2", None)
        bpy.context.collection.objects.link(anchor)
        return anchor

    def write_obj_to_label(self, output_dir):
        os.makedirs(output_dir, exist_ok=True)
        path = os.path.join(str(output_dir), "obj_to_label.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self._obj_to_label, f, indent=2)
        return path
