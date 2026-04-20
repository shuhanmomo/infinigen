import json
import os

import bpy
import numpy as np

from infinigen.assets.utils.object import new_bbox
from infinigen.core.placement.factory import AssetFactory
from infinigen.core.util.math import FixedSeed


class BuildingFacadeDecorFactory(AssetFactory):
    """
    Location-conditioned facade generator in a strict cuboid language.

    This version removes both `wall_material` and any style-program latent.
    Decoration is assigned only from window location in the elevation.
    The front facade carries the full ornament grammar, while the remaining
    three facades stay comparatively modest.

    Location descriptors:
      - story kind: GROUND / MID / TOP
      - bay kind: END / CENTER / ADJ_CENTER / REGULAR
      - parity: retained as a lightweight alternating term if needed later

    Cuboid translation of the book-inspired ideas:
      - heavy ground-floor windows on the main facade
      - tall middle-floor windows with lintels
      - simpler, squarer top-floor windows
      - centered front door
      - location emphasis through blocky frames rather than curved pediments
    """

    def __init__(self, factory_seed, coarse=False):
        super().__init__(factory_seed=factory_seed, coarse=coarse)
        with FixedSeed(factory_seed):
            # ---- massing ----
            self.ground_h = np.random.uniform(4.0, 5.2)
            self.floor_h = np.random.uniform(3.0, 3.7)
            self.n_upper_floors = int(np.random.randint(2, 6))
            self.side_margin = np.random.uniform(0.40, 0.80)
            self.tile_w = np.random.uniform(2.6, 3.7)
            self.depth = np.random.uniform(0.25, 0.40)
            self.opening_protrusion = np.random.uniform(0.05, 0.10)
            self.roof_thickness = np.random.uniform(0.22, 0.40)

            # ---- door ----
            self.door_h = np.random.uniform(2.5, 3.1)
            self.door_w = np.random.uniform(1.5, 2.2)

            # ---- window proportions ----
            self.ground_sill = np.random.uniform(0.65, 0.95)
            self.upper_sill = np.random.uniform(0.80, 1.15)
            self.top_sill = np.random.uniform(0.55, 0.85)
            self.ground_win_h = np.random.uniform(1.8, 2.5)
            self.upper_win_h = np.random.uniform(1.45, 2.00)
            self.win_top_gap = np.random.uniform(0.10, 0.18)
            self.win_pad_frac = np.random.uniform(0.15, 0.23)
            self.top_square_frac = np.random.uniform(0.82, 0.98)

            # ---- ornament vocabulary ----
            self.sill_h = np.random.uniform(0.07, 0.13)
            self.lintel_h = np.random.uniform(0.16, 0.26)
            self.jamb_w = np.random.uniform(0.06, 0.13)
            self.frame_overhang = np.random.uniform(0.02, 0.07)
            self.panel_h = np.random.uniform(0.18, 0.34)
            self.panel_gap = np.random.uniform(0.05, 0.11)
            self.course_h = np.random.uniform(0.10, 0.17)
            self.cornice_h = np.random.uniform(0.14, 0.25)
            self.crown_h = np.random.uniform(0.10, 0.18)
            self.crown_wide_extra = np.random.uniform(0.08, 0.18)
            self.crown_narrow_extra = np.random.uniform(0.02, 0.08)
            self.ornament_depth_extra = np.random.uniform(0.01, 0.04)

            self.height = self.ground_h + self.n_upper_floors * self.floor_h

        self._obj_to_label = {}
        self._label_counters = {}

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
        self,
        parts,
        label,
        x0,
        x1,
        y0,
        y1,
        z0,
        z1,
        rot_k=0,
        tx=0.0,
        ty=0.0,
    ):
        if not (
            self._valid_extent(x0, x1)
            and self._valid_extent(y0, y1)
            and self._valid_extent(z0, z1)
        ):
            return
        wx0, wx1, wy0, wy1 = self._transform_bounds(
            x0,
            x1,
            y0,
            y1,
            rot_k,
            tx,
            ty,
        )
        obj = new_bbox(wx0, wx1, wy0, wy1, z0, z1)
        obj.name = self._next_name(label)
        obj["semantic_type"] = label
        parts.append(obj)

    def _vertical_partition(self):
        floors = [(0.0, self.ground_h)]
        z = self.ground_h
        for _ in range(self.n_upper_floors):
            floors.append((z, z + self.floor_h))
            z += self.floor_h
        return floors

    def _repeat_to_fill(self, start, end, step, force_odd=False):
        span = max(0.0, end - start)
        if span <= 1e-6:
            return []

        step = max(step, 1e-6)
        n_bays = max(1, int(np.floor(span / step + 0.5)))

        if force_odd and (n_bays % 2 == 0):
            candidates = []
            if n_bays - 1 >= 1:
                candidates.append(n_bays - 1)
            candidates.append(n_bays + 1)
            n_bays = min(candidates, key=lambda n: abs(span / n - step))

        bay_w = span / n_bays
        return [(start + i * bay_w, start + (i + 1) * bay_w) for i in range(n_bays)]

    def _story_kind(self, floor_idx, n_floors):
        if floor_idx == 0:
            return "GROUND"
        if floor_idx == n_floors - 1:
            return "TOP"
        return "MID"

    def _bay_kind(self, bay_idx, n_bays):
        if n_bays <= 0:
            return "REGULAR"
        center = n_bays // 2
        if bay_idx == 0 or bay_idx == n_bays - 1:
            return "END"
        if (n_bays % 2 == 1) and bay_idx == center:
            return "CENTER"
        if (n_bays % 2 == 1) and abs(bay_idx - center) == 1:
            return "ADJ_CENTER"
        return "REGULAR"

    def _window_opening(self, bay_x, band_z, story_kind, facade_kind):
        bx0, bx1 = bay_x
        z0, z1 = band_z
        bw = bx1 - bx0
        bh = z1 - z0

        if story_kind == "GROUND":
            sill = min(self.ground_sill, 0.42 * bh)
            win_h = min(self.ground_win_h, bh - sill - self.win_top_gap)
            pad_scale = 0.92
        elif story_kind == "TOP":
            sill = min(self.top_sill, 0.40 * bh)
            base_pad = min(0.45, self.win_pad_frac * bw * 1.05)
            clear_w = bw - 2.0 * base_pad
            avail_h = max(0.8, bh - sill - self.win_top_gap)
            win_h = min(avail_h, self.top_square_frac * clear_w)
            pad_scale = 1.05
        else:
            sill = min(0.26 * bh, 0.70 * self.upper_sill)
            avail_h = bh - sill - self.win_top_gap
            target_h = max(self.upper_win_h, 0.74 * bh)
            win_h = min(target_h, avail_h)
            pad_scale = 0.92 if facade_kind == "FRONT" else 0.98

        pad = min(0.45, self.win_pad_frac * bw * pad_scale)
        wx0, wx1 = bx0 + pad, bx1 - pad
        wz0 = z0 + sill
        wz1 = min(wz0 + win_h, z1 - self.win_top_gap)
        return wx0, wx1, wz0, wz1

    def _add_sill(self, parts, wx0, wx1, wz0, wy0, wy1, transform, scale=1.0):
        rot_k, tx, ty = transform
        h = self.sill_h * scale
        over = self.frame_overhang * scale
        self._add_named_box(
            parts,
            "sill",
            wx0 - over,
            wx1 + over,
            wy0,
            wy1,
            wz0 - h,
            wz0,
            rot_k,
            tx,
            ty,
        )

    def _add_lintel(
        self,
        parts,
        wx0,
        wx1,
        wz1,
        wy0,
        wy1,
        transform,
        scale=1.0,
        label="lintel",
        extra_width=0.0,
    ):
        rot_k, tx, ty = transform
        h = self.lintel_h * scale
        over = self.frame_overhang * scale
        self._add_named_box(
            parts,
            label,
            wx0 - over - extra_width,
            wx1 + over + extra_width,
            wy0,
            wy1,
            wz1,
            wz1 + h,
            rot_k,
            tx,
            ty,
        )

    def _add_jambs(
        self,
        parts,
        wx0,
        wx1,
        wz0,
        wz1,
        wy0,
        wy1,
        transform,
        scale=1.0,
        label="jamb",
        extend_to_lintel=True,
    ):
        rot_k, tx, ty = transform
        jw = self.jamb_w * scale
        over = self.frame_overhang * scale
        z0 = wz0 - self.sill_h * scale
        z1 = wz1 + self.lintel_h * scale if extend_to_lintel else wz1
        self._add_named_box(
            parts,
            label,
            wx0 - jw - over,
            wx0 - over,
            wy0,
            wy1,
            z0,
            z1,
            rot_k,
            tx,
            ty,
        )
        self._add_named_box(
            parts,
            label,
            wx1 + over,
            wx1 + jw + over,
            wy0,
            wy1,
            z0,
            z1,
            rot_k,
            tx,
            ty,
        )

    def _add_panel(self, parts, wx0, wx1, wz0, band_z, wy0, wy1, transform, scale=1.0):
        rot_k, tx, ty = transform
        z_band0, _ = band_z
        panel_h = self.panel_h * scale
        over = self.frame_overhang * scale
        jw = self.jamb_w * scale
        pz1 = wz0 - self.panel_gap * scale
        pz0 = max(z_band0 + 0.06, pz1 - panel_h)
        self._add_named_box(
            parts,
            "panel",
            wx0 - jw - over,
            wx1 + jw + over,
            wy0,
            wy1,
            pz0,
            pz1,
            rot_k,
            tx,
            ty,
        )

    def _add_crown(
        self, parts, crown_type, wx0, wx1, wz1, wy0, wy1, transform, scale=1.0
    ):
        rot_k, tx, ty = transform
        lintel_top = wz1 + self.lintel_h * scale
        h = self.crown_h * scale

        if crown_type == "flat":
            extra = self.crown_wide_extra * scale
            self._add_named_box(
                parts,
                "crown",
                wx0 - extra,
                wx1 + extra,
                wy0,
                wy1,
                lintel_top,
                lintel_top + h,
                rot_k,
                tx,
                ty,
            )
        elif crown_type == "step":
            wide = self.crown_wide_extra * scale
            narrow = self.crown_narrow_extra * scale
            h0 = 0.55 * h
            self._add_named_box(
                parts,
                "crown",
                wx0 - wide,
                wx1 + wide,
                wy0,
                wy1,
                lintel_top,
                lintel_top + h0,
                rot_k,
                tx,
                ty,
            )
            self._add_named_box(
                parts,
                "crown",
                wx0 - narrow,
                wx1 + narrow,
                wy0,
                wy1,
                lintel_top + h0,
                lintel_top + h,
                rot_k,
                tx,
                ty,
            )

    def _window_profile(self, story_kind, bay_kind, parity, facade_kind):
        spec = {
            "sill": False,
            "lintel": False,
            "lintel_scale": 1.0,
            "jambs": False,
            "panel": False,
            "crown": "none",
            "frame_scale": 1.0,
        }

        if facade_kind != "FRONT":
            if story_kind == "GROUND":
                spec.update(
                    {
                        "sill": True,
                        "lintel": True,
                        "lintel_scale": 1.05,
                        "frame_scale": 1.00,
                    }
                )
            elif story_kind == "MID":
                spec.update(
                    {
                        "lintel": True,
                        "lintel_scale": 1.20,
                        "frame_scale": 0.98,
                    }
                )
            else:  # TOP
                spec.update(
                    {
                        "frame_scale": 0.94,
                    }
                )
            return spec

        if story_kind == "GROUND":
            spec.update(
                {
                    "sill": True,
                    "lintel": True,
                    "lintel_scale": 1.10,
                    "jambs": True,
                    "panel": True,
                    "frame_scale": 1.12,
                }
            )
            if bay_kind == "CENTER":
                spec["frame_scale"] = 1.20
            elif bay_kind == "ADJ_CENTER":
                spec["frame_scale"] = 1.16
            elif bay_kind == "END":
                spec["frame_scale"] = 1.08

        elif story_kind == "MID":
            if bay_kind == "CENTER":
                spec.update(
                    {
                        "lintel": True,
                        "lintel_scale": 1.40,
                        "frame_scale": 1.06,
                    }
                )
            elif bay_kind in {"ADJ_CENTER", "END"}:
                spec.update(
                    {
                        "lintel": True,
                        "lintel_scale": 1.30,
                        "frame_scale": 1.04 if parity == 0 else 1.02,
                    }
                )
            else:
                spec.update(
                    {
                        "lintel": True,
                        "lintel_scale": 1.25,
                        "frame_scale": 1.00,
                    }
                )

        else:  # TOP
            spec.update(
                {
                    "frame_scale": 0.92,
                }
            )
            if bay_kind == "CENTER":
                spec["frame_scale"] = 0.96

        return spec

    def _add_story_decor(
        self, parts, width, band_z, story_kind, facade_kind, y0, y1, transform
    ):
        return

    def _place_window(
        self,
        parts,
        bay_x,
        band_z,
        y0,
        y1,
        transform,
        story_kind,
        bay_kind,
        parity,
        facade_kind,
    ):
        wx0, wx1, wz0, wz1 = self._window_opening(
            bay_x, band_z, story_kind, facade_kind
        )
        if not (self._valid_extent(wx0, wx1) and self._valid_extent(wz0, wz1)):
            return

        rot_k, tx, ty = transform
        if story_kind == "TOP":
            depth_scale = 0.25
        elif story_kind == "MID":
            depth_scale = 0.90
        else:
            depth_scale = 1.00

        opening_depth = self.opening_protrusion * depth_scale
        ornament_depth = self.ornament_depth_extra * depth_scale
        wy0 = y0 - opening_depth
        wy1 = y1 + opening_depth
        owy0 = wy0 - ornament_depth
        owy1 = wy1 + ornament_depth

        self._add_named_box(
            parts,
            "window",
            wx0,
            wx1,
            wy0,
            wy1,
            wz0,
            wz1,
            rot_k,
            tx,
            ty,
        )

        spec = self._window_profile(story_kind, bay_kind, parity, facade_kind)
        scale = spec["frame_scale"]

        if spec["sill"]:
            self._add_sill(parts, wx0, wx1, wz0, owy0, owy1, transform, scale=scale)
        if spec["lintel"]:
            self._add_lintel(
                parts,
                wx0,
                wx1,
                wz1,
                owy0,
                owy1,
                transform,
                scale=spec["lintel_scale"],
            )
        if spec["jambs"]:
            self._add_jambs(
                parts, wx0, wx1, wz0, wz1, owy0, owy1, transform, scale=scale
            )
        if spec["panel"]:
            self._add_panel(
                parts, wx0, wx1, wz0, band_z, owy0, owy1, transform, scale=scale
            )
        if spec["crown"] != "none":
            if not spec["lintel"]:
                self._add_lintel(
                    parts, wx0, wx1, wz1, owy0, owy1, transform, scale=scale
                )
            self._add_crown(
                parts, spec["crown"], wx0, wx1, wz1, owy0, owy1, transform, scale=scale
            )

    def _place_door(self, parts, bay_x, band_z, y0, y1, transform):
        bx0, bx1 = bay_x
        z0, z1 = band_z
        bw = bx1 - bx0
        door_w = min(self.door_w, 0.70 * bw)
        cx = 0.5 * (bx0 + bx1)
        dx0 = max(bx0, cx - door_w / 2.0)
        dx1 = min(bx1, cx + door_w / 2.0)
        dz1 = min(z0 + self.door_h, z1 - 0.05)

        rot_k, tx, ty = transform
        wy0 = y0 - self.opening_protrusion
        wy1 = y1 + self.opening_protrusion
        owy0 = wy0 - self.ornament_depth_extra
        owy1 = wy1 + self.ornament_depth_extra

        self._add_named_box(
            parts,
            "door",
            dx0,
            dx1,
            wy0,
            wy1,
            z0,
            dz1,
            rot_k,
            tx,
            ty,
        )
        self._add_lintel(
            parts,
            dx0,
            dx1,
            dz1,
            owy0,
            owy1,
            transform,
            scale=1.35,
            label="door_lintel",
            extra_width=self.jamb_w * 1.22,
        )
        self._add_jambs(
            parts,
            dx0,
            dx1,
            z0,
            dz1,
            owy0,
            owy1,
            transform,
            scale=1.22,
            label="door_jamb",
            extend_to_lintel=False,
        )
        gap = 0.35 * self.lintel_h * 1.35
        header_h = 0.90 * self.lintel_h * 1.35
        header_extra = 0.10 * (dx1 - dx0)
        self._add_named_box(
            parts,
            "door_crown",
            dx0 - header_extra,
            dx1 + header_extra,
            owy0,
            owy1,
            dz1 + self.lintel_h * 1.35 + gap,
            dz1 + self.lintel_h * 1.35 + gap + header_h,
            rot_k,
            tx,
            ty,
        )

    def _build_facade(self, parts, width, kind, y0, y1, transform):
        floors = self._vertical_partition()
        bays = self._repeat_to_fill(
            self.side_margin,
            width - self.side_margin,
            self.tile_w,
            force_odd=(kind == "FRONT"),
        )
        n_bays = len(bays)
        center_bay = n_bays // 2 if n_bays > 0 else None

        for floor_idx, band_z in enumerate(floors):
            story_kind = self._story_kind(floor_idx, len(floors))
            self._add_story_decor(
                parts, width, band_z, story_kind, kind, y0, y1, transform
            )

            for bay_idx, bay in enumerate(bays):
                bay_kind = self._bay_kind(bay_idx, n_bays)
                parity = (floor_idx + bay_idx) % 2

                if floor_idx == 0 and kind == "FRONT" and bay_idx == center_bay:
                    self._place_door(parts, bay, band_z, y0, y1, transform)
                else:
                    self._place_window(
                        parts,
                        bay,
                        band_z,
                        y0,
                        y1,
                        transform,
                        story_kind=story_kind,
                        bay_kind=bay_kind,
                        parity=parity,
                        facade_kind=kind,
                    )

    def create_asset(self, **params):
        self._obj_to_label = {}
        self._label_counters = {}

        front_width = float(params.get("front_width", np.random.uniform(12.0, 22.0)))
        side_width = float(params.get("side_width", np.random.uniform(10.0, 18.0)))

        parts = []

        facade_configs = [
            (front_width, "FRONT", (0, 0.0, 0.0)),
            (front_width, "SIDE", (2, front_width, side_width)),
            (side_width, "SIDE", (1, front_width, 0.0)),
            (side_width, "SIDE", (3, 0.0, side_width)),
        ]

        for width, kind, transform in facade_configs:
            rot_k, tx, ty = transform
            self._add_named_box(
                parts,
                "wall",
                0.0,
                width,
                0.0,
                self.depth,
                0.0,
                self.height,
                rot_k,
                tx,
                ty,
            )
            self._build_facade(parts, width, kind, 0.0, self.depth, transform)

        self._add_named_box(
            parts,
            "roof",
            0.0,
            front_width,
            0.0,
            side_width,
            self.height,
            self.height + self.roof_thickness,
        )

        parent = bpy.data.objects.new("building_facade_decor", None)
        parent["decor_logic"] = "location_conditioned_v1"
        bpy.context.collection.objects.link(parent)
        for obj in parts:
            obj.parent = parent

        return parent

    def write_obj_to_label(self, output_dir):
        os.makedirs(output_dir, exist_ok=True)
        path = os.path.join(str(output_dir), "obj_to_label.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self._obj_to_label, f, indent=2)
        return path
