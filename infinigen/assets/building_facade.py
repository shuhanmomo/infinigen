import numpy as np

from infinigen.assets.utils.object import join_objects, new_bbox
from infinigen.core.placement.factory import AssetFactory


class BuildingFacadeFactory(AssetFactory):
    def __init__(self, factory_seed, coarse=False):
        super().__init__(factory_seed=factory_seed, coarse=coarse)

        # Facade composition parameters from requested pseudocode.
        self.ground_h = 4.0
        self.floor_h = 3.5
        self.height = 11.0
        self.tile_w = 4.0
        self.side_margin = 0.5

        # Opening proportions (simple boxes).
        self.door_h = 2.6
        self.door_w = 1.8
        self.sill = 1.0
        self.win_h = 1.8
        self.opening_protrusion = 0.08

        # Facade thickness in the non-width direction.
        self.depth = 0.25
        self.roof_thickness = 0.3

    @staticmethod
    def _valid_extent(a, b, eps=1e-6):
        return (b - a) > eps

    def _add_box(self, parts, x0, x1, y0, y1, z0, z1):
        if (
            self._valid_extent(x0, x1)
            and self._valid_extent(y0, y1)
            and self._valid_extent(z0, z1)
        ):
            parts.append(new_bbox(x0, x1, y0, y1, z0, z1))

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

        # Evenly distribute bays to avoid a tiny leftover last bay.
        target = max(step, 1e-6)
        n_bays = max(1, int(np.floor(span / target + 0.5)))
        bay_w = span / n_bays
        return [(start + i * bay_w, start + (i + 1) * bay_w) for i in range(n_bays)]

    def _place_window_bay(self, parts, bay_x, band_z, y0, y1):
        bx0, bx1 = bay_x
        z0, z1 = band_z
        bw = bx1 - bx0
        pad = min(0.45, 0.2 * bw)

        wx0 = bx0 + pad
        wx1 = bx1 - pad
        wz0 = z0 + self.sill
        wz1 = min(wz0 + self.win_h, z1 - 0.05)

        if not (self._valid_extent(wx0, wx1) and self._valid_extent(wz0, wz1)):
            return

        # Simple window box.
        wy0 = y0 - self.opening_protrusion
        wy1 = y1 + self.opening_protrusion
        self._add_box(parts, wx0, wx1, wy0, wy1, wz0, wz1)

    def _place_entrance_bay(self, parts, bay_x, band_z, y0, y1):
        bx0, bx1 = bay_x
        z0, z1 = band_z
        bw = bx1 - bx0
        door_w = min(self.door_w, 0.65 * bw)
        cx = 0.5 * (bx0 + bx1)
        dx0 = max(bx0, cx - door_w / 2.0)
        dx1 = min(bx1, cx + door_w / 2.0)
        dz1 = min(z0 + self.door_h, z1)

        # Simple door box.
        dy0 = y0 - self.opening_protrusion
        dy1 = y1 + self.opening_protrusion
        self._add_box(parts, dx0, dx1, dy0, dy1, z0, dz1)

    def _typical_floor_band(self, parts, width, band_z, y0, y1):
        bays = self._repeat_to_fill(self.side_margin, width - self.side_margin, self.tile_w)
        for bay in bays:
            self._place_window_bay(parts, bay, band_z, y0, y1)

    def _ground_floor_band(self, parts, width, band_z, y0, y1):
        bays = self._repeat_to_fill(self.side_margin, width - self.side_margin, self.tile_w)
        if not bays:
            # Fallback: force a single entrance bay between side margins.
            span0 = self.side_margin
            span1 = max(self.side_margin, width - self.side_margin)
            if self._valid_extent(span0, span1):
                self._place_entrance_bay(parts, (span0, span1), band_z, y0, y1)
            return

        for bay in bays[:-1]:
            self._place_window_bay(parts, bay, band_z, y0, y1)
        self._place_entrance_bay(parts, bays[-1], band_z, y0, y1)

    def _build_single_facade(self, width, kind, y0, y1):
        parts = []
        floors = self._vertical_partition()
        for i, band_z in enumerate(floors):
            if i == 0 and kind == "FRONT":
                self._ground_floor_band(parts, width, band_z, y0, y1)
            else:
                self._typical_floor_band(parts, width, band_z, y0, y1)
        return parts

    def create_asset(self, **params):
        front_width = float(params.get("front_width", np.random.uniform(12.0, 22.0)))
        side_width = float(params.get("side_width", np.random.uniform(10.0, 18.0)))

        parts = []

        # Four main wall slabs (one per side).
        parts.append(new_bbox(0.0, front_width, 0.0, self.depth, 0.0, self.height))  # front
        parts.append(
            new_bbox(0.0, front_width, side_width - self.depth, side_width, 0.0, self.height)
        )  # back
        parts.append(new_bbox(front_width - self.depth, front_width, 0.0, side_width, 0.0, self.height))  # right
        parts.append(new_bbox(0.0, self.depth, 0.0, side_width, 0.0, self.height))  # left

        # FRONT facade: entrance on ground floor.
        front_parts = self._build_single_facade(
            width=front_width,
            kind="FRONT",
            y0=0.0,
            y1=self.depth,
        )
        parts.extend(front_parts)

        # BACK facade: mirrored placement at far y.
        back_parts = self._build_single_facade(
            width=front_width,
            kind="SIDE",
            y0=0.0,
            y1=self.depth,
        )
        for obj in back_parts:
            obj.rotation_euler[2] = np.pi
            obj.location[0] += front_width
            obj.location[1] += side_width
        parts.extend(back_parts)

        # RIGHT facade.
        right_parts = self._build_single_facade(
            width=side_width,
            kind="SIDE",
            y0=0.0,
            y1=self.depth,
        )
        for obj in right_parts:
            obj.rotation_euler[2] = np.pi / 2
            obj.location[0] += front_width
        parts.extend(right_parts)

        # LEFT facade.
        left_parts = self._build_single_facade(
            width=side_width,
            kind="SIDE",
            y0=0.0,
            y1=self.depth,
        )
        for obj in left_parts:
            obj.rotation_euler[2] = -np.pi / 2
            obj.location[1] += side_width
        parts.extend(left_parts)

        # Roof slab.
        parts.append(
            new_bbox(
                0.0,
                front_width,
                0.0,
                side_width,
                self.height,
                self.height + self.roof_thickness,
            )
        )

        facade = join_objects(parts)
        facade.name = "building_facade"
        return facade
