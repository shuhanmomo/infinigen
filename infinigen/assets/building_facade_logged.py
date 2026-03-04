import numpy as np

from infinigen.assets.utils.object import join_objects, new_bbox
from infinigen.core.placement.factory import AssetFactory


class BuildingFacadeFactoryLogged(AssetFactory):
    """Logged facade generator that preserves semantic layers.

    Differences from sanitized object-level generators:
    - Keep semantic labels (wall/window/door/roof) as object names + custom attrs.
    - Group same semantic type into one scene object.
    """

    def __init__(self, factory_seed, coarse=False):
        super().__init__(factory_seed=factory_seed, coarse=coarse)
        self.ground_h = 4.0
        self.floor_h = 3.5
        self.height = 11.0
        self.tile_w = 4.0
        self.side_margin = 0.5

        self.door_h = 2.6
        self.door_w = 1.8
        self.sill = 1.0
        self.win_h = 1.8
        self.opening_protrusion = 0.08

        self.depth = 0.25
        self.roof_thickness = 0.3

        self._semantic_specs = None

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
        pts = [
            self._transform_xy(x0, y0, rot_k, tx, ty),
            self._transform_xy(x0, y1, rot_k, tx, ty),
            self._transform_xy(x1, y0, rot_k, tx, ty),
            self._transform_xy(x1, y1, rot_k, tx, ty),
        ]
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return min(xs), max(xs), min(ys), max(ys)

    def _new_bucket(self):
        return {"wall": [], "window": [], "door": [], "roof": []}

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

    def _add_box(
        self,
        bucket,
        specs,
        semantic,
        x0,
        x1,
        y0,
        y1,
        z0,
        z1,
        rot_k,
        tx,
        ty,
    ):
        if not (
            self._valid_extent(x0, x1)
            and self._valid_extent(y0, y1)
            and self._valid_extent(z0, z1)
        ):
            return

        wx0, wx1, wy0, wy1 = self._transform_bounds(x0, x1, y0, y1, rot_k, tx, ty)
        obj = new_bbox(wx0, wx1, wy0, wy1, z0, z1)
        bucket[semantic].append(obj)
        specs[semantic].append((wx0, wx1, wy0, wy1, z0, z1))

    def _place_window_bay(self, bucket, specs, bay_x, band_z, y0, y1, t):
        bx0, bx1 = bay_x
        z0, z1 = band_z
        bw = bx1 - bx0
        pad = min(0.45, 0.2 * bw)

        wx0 = bx0 + pad
        wx1 = bx1 - pad
        wz0 = z0 + self.sill
        wz1 = min(wz0 + self.win_h, z1 - 0.05)

        rot_k, tx, ty = t
        if not (self._valid_extent(wx0, wx1) and self._valid_extent(wz0, wz1)):
            return

        self._add_box(
            bucket,
            specs,
            "window",
            wx0,
            wx1,
            y0 - self.opening_protrusion,
            y1 + self.opening_protrusion,
            wz0,
            wz1,
            rot_k,
            tx,
            ty,
        )

    def _place_entrance_bay(self, bucket, specs, bay_x, band_z, y0, y1, t):
        bx0, bx1 = bay_x
        z0, z1 = band_z
        bw = bx1 - bx0
        door_w = min(self.door_w, 0.65 * bw)
        cx = 0.5 * (bx0 + bx1)
        dx0 = max(bx0, cx - door_w / 2.0)
        dx1 = min(bx1, cx + door_w / 2.0)
        dz1 = min(z0 + self.door_h, z1)

        rot_k, tx, ty = t
        self._add_box(
            bucket,
            specs,
            "door",
            dx0,
            dx1,
            y0 - self.opening_protrusion,
            y1 + self.opening_protrusion,
            z0,
            dz1,
            rot_k,
            tx,
            ty,
        )

    def _typical_floor_band(self, bucket, specs, width, band_z, y0, y1, t):
        bays = self._repeat_to_fill(self.side_margin, width - self.side_margin, self.tile_w)
        for bay in bays:
            self._place_window_bay(bucket, specs, bay, band_z, y0, y1, t)

    def _ground_floor_band(self, bucket, specs, width, band_z, y0, y1, t):
        bays = self._repeat_to_fill(self.side_margin, width - self.side_margin, self.tile_w)
        if not bays:
            span0 = self.side_margin
            span1 = max(self.side_margin, width - self.side_margin)
            if self._valid_extent(span0, span1):
                self._place_entrance_bay(bucket, specs, (span0, span1), band_z, y0, y1, t)
            return

        for bay in bays[:-1]:
            self._place_window_bay(bucket, specs, bay, band_z, y0, y1, t)
        self._place_entrance_bay(bucket, specs, bays[-1], band_z, y0, y1, t)

    def _build_single_facade(self, bucket, specs, width, kind, y0, y1, transform):
        floors = self._vertical_partition()
        for i, band_z in enumerate(floors):
            if i == 0 and kind == "FRONT":
                self._ground_floor_band(bucket, specs, width, band_z, y0, y1, transform)
            else:
                self._typical_floor_band(bucket, specs, width, band_z, y0, y1, transform)

    def create_asset(self, **params):
        front_width = float(params.get("front_width", np.random.uniform(12.0, 22.0)))
        side_width = float(params.get("side_width", np.random.uniform(10.0, 18.0)))

        bucket = self._new_bucket()
        specs = {k: [] for k in bucket.keys()}

        # Four main walls (single slab per side).
        self._add_box(
            bucket, specs, "wall", 0.0, front_width, 0.0, self.depth, 0.0, self.height, 0, 0.0, 0.0
        )
        self._add_box(
            bucket, specs, "wall", 0.0, front_width, 0.0, self.depth, 0.0, self.height, 2, front_width, side_width
        )
        self._add_box(
            bucket, specs, "wall", 0.0, side_width, 0.0, self.depth, 0.0, self.height, 1, front_width, 0.0
        )
        self._add_box(
            bucket, specs, "wall", 0.0, side_width, 0.0, self.depth, 0.0, self.height, 3, 0.0, side_width
        )

        # FRONT facade
        self._build_single_facade(
            bucket=bucket,
            specs=specs,
            width=front_width,
            kind="FRONT",
            y0=0.0,
            y1=self.depth,
            transform=(0, 0.0, 0.0),
        )

        # BACK facade
        self._build_single_facade(
            bucket=bucket,
            specs=specs,
            width=front_width,
            kind="SIDE",
            y0=0.0,
            y1=self.depth,
            transform=(2, front_width, side_width),
        )

        # RIGHT facade
        self._build_single_facade(
            bucket=bucket,
            specs=specs,
            width=side_width,
            kind="SIDE",
            y0=0.0,
            y1=self.depth,
            transform=(1, front_width, 0.0),
        )

        # LEFT facade
        self._build_single_facade(
            bucket=bucket,
            specs=specs,
            width=side_width,
            kind="SIDE",
            y0=0.0,
            y1=self.depth,
            transform=(3, 0.0, side_width),
        )

        # Roof
        roof = new_bbox(
            0.0,
            front_width,
            0.0,
            side_width,
            self.height,
            self.height + self.roof_thickness,
        )
        bucket["roof"].append(roof)
        specs["roof"].append(
            (
                0.0,
                front_width,
                0.0,
                side_width,
                self.height,
                self.height + self.roof_thickness,
            )
        )

        parent = None
        grouped = {}
        for semantic, objs in bucket.items():
            if not objs:
                continue
            obj = join_objects(objs) if len(objs) > 1 else objs[0]
            obj.name = f"facade_{semantic}"
            obj["semantic_type"] = semantic
            grouped[semantic] = obj

        if grouped:
            import bpy

            parent = bpy.data.objects.new("building_facade_logged", None)
            bpy.context.collection.objects.link(parent)
            for o in grouped.values():
                o.parent = parent

        self._semantic_specs = {
            "meta": {
                "front_width": front_width,
                "side_width": side_width,
                "height": self.height,
                "ground_h": self.ground_h,
                "floor_h": self.floor_h,
                "tile_w": self.tile_w,
                "side_margin": self.side_margin,
                "depth": self.depth,
                "roof_thickness": self.roof_thickness,
            },
            "parts": specs,
        }

        return parent if parent is not None else roof

    def export_logged_script(self, output_path: str) -> str:
        if self._semantic_specs is None:
            raise RuntimeError("No logged specs found. Run create_asset/spawn_asset first.")

        meta = self._semantic_specs["meta"]
        parts = self._semantic_specs["parts"]

        with open(output_path, "w", encoding="utf-8") as f:
            f.write("import bpy\n")
            f.write("from infinigen.assets.utils.object import join_objects, new_bbox\n\n")
            f.write("# Logged facade script (semantic-preserving)\n")
            f.write(f"# front_width={meta['front_width']:.6f}, side_width={meta['side_width']:.6f}\n\n")
            f.write("grouped = {}\n\n")

            for semantic in ["wall", "window", "door", "roof"]:
                f.write(f"# {semantic.upper()} parts\n")
                f.write("objs = []\n")
                for (x0, x1, y0, y1, z0, z1) in parts.get(semantic, []):
                    f.write(
                        "objs.append(new_bbox("
                        f"{x0:.9f}, {x1:.9f}, {y0:.9f}, {y1:.9f}, {z0:.9f}, {z1:.9f}"
                        "))\n"
                    )
                f.write("if len(objs) > 1:\n")
                f.write("    obj = join_objects(objs)\n")
                f.write("elif len(objs) == 1:\n")
                f.write("    obj = objs[0]\n")
                f.write("else:\n")
                f.write("    obj = None\n")
                f.write("if obj is not None:\n")
                f.write(f'    obj.name = "facade_{semantic}"\n')
                f.write(f'    obj["semantic_type"] = "{semantic}"\n')
                f.write(f'    grouped["{semantic}"] = obj\n\n')

            f.write('parent = bpy.data.objects.new("building_facade_logged", None)\n')
            f.write("bpy.context.collection.objects.link(parent)\n")
            f.write("for o in grouped.values():\n")
            f.write("    o.parent = parent\n")

        return output_path

    def export_sanitized_script(self, output_path: str) -> str:
        # Keep generate_logged_assets.py compatibility while preserving semantic layers.
        return self.export_logged_script(output_path)
