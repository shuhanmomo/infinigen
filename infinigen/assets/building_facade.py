import json
import os

import bpy
import numpy as np

from infinigen.assets.utils.object import new_bbox
from infinigen.core.placement.factory import AssetFactory
from infinigen.core.util.math import FixedSeed


class BuildingFacadeFactory(AssetFactory):
    def __init__(self, factory_seed, coarse=False):
        super().__init__(factory_seed=factory_seed, coarse=coarse)
        with FixedSeed(factory_seed):
            self.ground_h = np.random.uniform(3.5, 5.0)
            self.floor_h = np.random.uniform(3.0, 4.0)
            self.height = np.random.uniform(8.0, 16.0)
            self.tile_w = np.random.uniform(3.0, 5.0)
            self.side_margin = np.random.uniform(0.3, 0.8)

            self.door_h = np.random.uniform(2.4, 3.0)
            self.door_w = np.random.uniform(1.4, 2.2)
            self.sill = np.random.uniform(0.8, 1.2)
            self.win_h = np.random.uniform(1.4, 2.2)
            self.opening_protrusion = np.random.uniform(0.05, 0.12)

            self.depth = np.random.uniform(0.2, 0.35)
            self.roof_thickness = np.random.uniform(0.2, 0.4)

        self._obj_to_label = {}
        self._label_counters = {}

    def _next_name(self, label):
        """Generate a unique name like 'window_01' and record the mapping."""
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
        """Rotate (x, y) by rot_k * 90 degrees CCW, then translate."""
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

    def _add_named_box(self, parts, label, x0, x1, y0, y1, z0, z1,
                       rot_k=0, tx=0.0, ty=0.0):
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
        parts.append(obj)

    def _vertical_partition(self):
        floors = []
        z = 0.0
        first_h = min(self.ground_h, self.height)
        floors.append((z, z + first_h))
        z += first_h
        while z < self.height - 1e-6:
            h = min(self.floor_h, self.height - z)
            floors.append((z, z + h))
            z += h
        return floors

    def _repeat_to_fill(self, start, end, step):
        span = max(0.0, end - start)
        if span <= 1e-6:
            return []
        n_bays = max(1, int(np.floor(span / max(step, 1e-6) + 0.5)))
        bay_w = span / n_bays
        return [(start + i * bay_w, start + (i + 1) * bay_w) for i in range(n_bays)]

    def _place_window(self, parts, bay_x, band_z, y0, y1, transform):
        bx0, bx1 = bay_x
        z0, z1 = band_z
        bw = bx1 - bx0
        pad = min(0.45, 0.2 * bw)
        wx0, wx1 = bx0 + pad, bx1 - pad
        wz0 = z0 + self.sill
        wz1 = min(wz0 + self.win_h, z1 - 0.05)

        if not (self._valid_extent(wx0, wx1) and self._valid_extent(wz0, wz1)):
            return

        rot_k, tx, ty = transform
        self._add_named_box(
            parts, "window", wx0, wx1,
            y0 - self.opening_protrusion, y1 + self.opening_protrusion,
            wz0, wz1, rot_k, tx, ty,
        )

    def _place_door(self, parts, bay_x, band_z, y0, y1, transform):
        bx0, bx1 = bay_x
        z0, z1 = band_z
        bw = bx1 - bx0
        door_w = min(self.door_w, 0.65 * bw)
        cx = 0.5 * (bx0 + bx1)
        dx0 = max(bx0, cx - door_w / 2.0)
        dx1 = min(bx1, cx + door_w / 2.0)
        dz1 = min(z0 + self.door_h, z1)

        rot_k, tx, ty = transform
        self._add_named_box(
            parts, "door", dx0, dx1,
            y0 - self.opening_protrusion, y1 + self.opening_protrusion,
            z0, dz1, rot_k, tx, ty,
        )

    def _build_facade(self, parts, width, kind, y0, y1, transform):
        floors = self._vertical_partition()
        for i, band_z in enumerate(floors):
            bays = self._repeat_to_fill(
                self.side_margin, width - self.side_margin, self.tile_w,
            )
            if i == 0 and kind == "FRONT":
                if not bays:
                    span0 = self.side_margin
                    span1 = max(self.side_margin, width - self.side_margin)
                    if self._valid_extent(span0, span1):
                        self._place_door(
                            parts, (span0, span1), band_z, y0, y1, transform,
                        )
                    continue
                for bay in bays[:-1]:
                    self._place_window(parts, bay, band_z, y0, y1, transform)
                self._place_door(parts, bays[-1], band_z, y0, y1, transform)
            else:
                for bay in bays:
                    self._place_window(parts, bay, band_z, y0, y1, transform)

    def create_asset(self, **params):
        self._obj_to_label = {}
        self._label_counters = {}

        front_width = float(params.get("front_width", np.random.uniform(12.0, 22.0)))
        side_width = float(params.get("side_width", np.random.uniform(10.0, 18.0)))

        parts = []

        # (facade_width, facade_kind, (rot_k, translate_x, translate_y))
        facade_configs = [
            (front_width, "FRONT", (0, 0.0, 0.0)),
            (front_width, "SIDE", (2, front_width, side_width)),
            (side_width, "SIDE", (1, front_width, 0.0)),
            (side_width, "SIDE", (3, 0.0, side_width)),
        ]

        for width, kind, transform in facade_configs:
            rot_k, tx, ty = transform
            self._add_named_box(
                parts, "wall",
                0.0, width, 0.0, self.depth, 0.0, self.height,
                rot_k, tx, ty,
            )
            self._build_facade(parts, width, kind, 0.0, self.depth, transform)

        self._add_named_box(
            parts, "roof",
            0.0, front_width, 0.0, side_width,
            self.height, self.height + self.roof_thickness,
        )

        parent = bpy.data.objects.new("building_facade", None)
        bpy.context.collection.objects.link(parent)
        for obj in parts:
            obj.parent = parent

        return parent

    def write_obj_to_label(self, output_dir):
        """Write obj_to_label.json mapping each object name to its semantic label."""
        os.makedirs(output_dir, exist_ok=True)
        path = os.path.join(str(output_dir), "obj_to_label.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self._obj_to_label, f, indent=2)
        return path
