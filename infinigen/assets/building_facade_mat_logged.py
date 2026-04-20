import json
import os

import bpy
import numpy as np

from infinigen.assets.utils.object import new_bbox
from infinigen.core.placement.factory import AssetFactory
from infinigen.core.util.math import FixedSeed


class BuildingFacadeMatFactoryLogged(AssetFactory):
    """Logged facade generator with wall_material property.

    ``wall_material`` (brick | glass_curtain) is sampled per seed and drives
    material-dependent geometry: bay width, sill height, window proportions,
    and whether lintel / sill-course elements are emitted.
    """

    def __init__(self, factory_seed, coarse=False):
        super().__init__(factory_seed=factory_seed, coarse=coarse)
        with FixedSeed(factory_seed):
            # ---- non-geometry property ----
            self.wall_material = np.random.choice(["brick", "glass_curtain"])

            # ---- shared params (independent of material) ----
            self.ground_h = np.random.uniform(3.5, 5.0)
            self.floor_h = np.random.uniform(3.0, 4.0)
            self.side_margin = np.random.uniform(0.3, 0.8)
            self.door_h = np.random.uniform(2.4, 3.0)
            self.door_w = np.random.uniform(1.4, 2.2)
            self.roof_thickness = np.random.uniform(0.2, 0.4)

            # ---- material-dependent params ----
            if self.wall_material == "brick":
                self.n_upper_floors = int(np.random.randint(1, 4))
                self.tile_w = np.random.uniform(2.5, 4.0)
                self.sill = np.random.uniform(0.8, 1.3)
                self.win_h = np.random.uniform(1.4, 2.0)
                self.win_top_gap = 0.05
                self.depth = np.random.uniform(0.25, 0.40)
                self.opening_protrusion = np.random.uniform(0.05, 0.10)
                self.win_pad_frac = np.random.uniform(0.18, 0.25)
                self.lintel_h = np.random.uniform(0.12, 0.20)
                self.sill_course_h = np.random.uniform(0.08, 0.15)
                self.lintel_overhang = np.random.uniform(0.03, 0.08)
            else:  # glass_curtain
                self.n_upper_floors = int(np.random.randint(2, 7))
                self.tile_w = np.random.uniform(1.2, 2.0)
                self.sill = np.random.uniform(0.05, 0.15)
                self.win_top_gap = np.random.uniform(0.05, 0.15)
                self.win_h = self.floor_h - self.sill - self.win_top_gap
                self.depth = np.random.uniform(0.12, 0.22)
                self.opening_protrusion = np.random.uniform(0.08, 0.15)
                self.win_pad_frac = np.random.uniform(0.04, 0.08)
                self.lintel_h = 0.0
                self.sill_course_h = 0.0
                self.lintel_overhang = 0.0

            self.height = self.ground_h + self.n_upper_floors * self.floor_h

        self._obj_to_label = {}
        self._label_counters = {}
        self._semantic_specs = None

    # ------------------------------------------------------------------
    # Naming helpers
    # ------------------------------------------------------------------

    def _next_name(self, label):
        idx = self._label_counters.get(label, 0)
        self._label_counters[label] = idx + 1
        name = f"{label}_{idx:02d}"
        self._obj_to_label[name] = label
        return name

    # ------------------------------------------------------------------
    # Geometry helpers
    # ------------------------------------------------------------------

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

    def _add_named_box(self, parts, specs, label, x0, x1, y0, y1, z0, z1,
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
        specs.setdefault(label, []).append((wx0, wx1, wy0, wy1, z0, z1))

    # ------------------------------------------------------------------
    # Vertical / horizontal partitioning
    # ------------------------------------------------------------------

    def _vertical_partition(self):
        floors = [(0.0, self.ground_h)]
        z = self.ground_h
        for _ in range(self.n_upper_floors):
            floors.append((z, z + self.floor_h))
            z += self.floor_h
        return floors

    def _repeat_to_fill(self, start, end, step):
        span = max(0.0, end - start)
        if span <= 1e-6:
            return []
        n_bays = max(1, int(np.floor(span / max(step, 1e-6) + 0.5)))
        bay_w = span / n_bays
        return [(start + i * bay_w, start + (i + 1) * bay_w) for i in range(n_bays)]

    # ------------------------------------------------------------------
    # Bay placement
    # ------------------------------------------------------------------

    def _place_window(self, parts, specs, bay_x, band_z, y0, y1, transform):
        bx0, bx1 = bay_x
        z0, z1 = band_z
        bw = bx1 - bx0
        pad = min(0.45, self.win_pad_frac * bw)
        wx0, wx1 = bx0 + pad, bx1 - pad
        wz0 = z0 + self.sill
        wz1 = min(wz0 + self.win_h, z1 - self.win_top_gap)

        if not (self._valid_extent(wx0, wx1) and self._valid_extent(wz0, wz1)):
            return

        rot_k, tx, ty = transform
        wy0 = y0 - self.opening_protrusion
        wy1 = y1 + self.opening_protrusion

        self._add_named_box(
            parts, specs, "window", wx0, wx1, wy0, wy1, wz0, wz1,
            rot_k, tx, ty,
        )

        if self.lintel_h > 0:
            self._add_named_box(
                parts, specs, "lintel",
                wx0 - self.lintel_overhang, wx1 + self.lintel_overhang,
                wy0, wy1, wz1, wz1 + self.lintel_h,
                rot_k, tx, ty,
            )
        if self.sill_course_h > 0:
            self._add_named_box(
                parts, specs, "sill_course",
                wx0 - self.lintel_overhang, wx1 + self.lintel_overhang,
                wy0, wy1, wz0 - self.sill_course_h, wz0,
                rot_k, tx, ty,
            )

    def _place_door(self, parts, specs, bay_x, band_z, y0, y1, transform):
        bx0, bx1 = bay_x
        z0, z1 = band_z
        bw = bx1 - bx0
        door_w = min(self.door_w, 0.65 * bw)
        cx = 0.5 * (bx0 + bx1)
        dx0 = max(bx0, cx - door_w / 2.0)
        dx1 = min(bx1, cx + door_w / 2.0)
        dz1 = min(z0 + self.door_h, z1)

        rot_k, tx, ty = transform
        dy0 = y0 - self.opening_protrusion
        dy1 = y1 + self.opening_protrusion

        self._add_named_box(
            parts, specs, "door", dx0, dx1, dy0, dy1, z0, dz1,
            rot_k, tx, ty,
        )

        if self.lintel_h > 0:
            self._add_named_box(
                parts, specs, "lintel",
                dx0 - self.lintel_overhang, dx1 + self.lintel_overhang,
                dy0, dy1, dz1, dz1 + self.lintel_h,
                rot_k, tx, ty,
            )

    def _build_facade(self, parts, specs, x_start, x_end, kind, y0, y1, transform):
        floors = self._vertical_partition()
        for i, band_z in enumerate(floors):
            bays = self._repeat_to_fill(
                x_start + self.side_margin,
                x_end - self.side_margin,
                self.tile_w,
            )
            if i == 0 and kind == "FRONT":
                if not bays:
                    span0 = x_start + self.side_margin
                    span1 = max(span0, x_end - self.side_margin)
                    if self._valid_extent(span0, span1):
                        self._place_door(
                            parts, specs, (span0, span1),
                            band_z, y0, y1, transform,
                        )
                    continue
                for bay in bays[:-1]:
                    self._place_window(
                        parts, specs, bay, band_z, y0, y1, transform,
                    )
                self._place_door(
                    parts, specs, bays[-1], band_z, y0, y1, transform,
                )
            else:
                for bay in bays:
                    self._place_window(
                        parts, specs, bay, band_z, y0, y1, transform,
                    )

    # ------------------------------------------------------------------
    # Asset creation
    # ------------------------------------------------------------------

    def create_asset(self, **params):
        self._obj_to_label = {}
        self._label_counters = {}

        front_width = float(params.get("front_width", np.random.uniform(12.0, 22.0)))
        side_width = float(params.get("side_width", np.random.uniform(10.0, 18.0)))
        # Persist on self so export_refactored_script can bake them into the
        # generator's __init__.
        self.front_width = front_width
        self.side_width = side_width

        parts = []
        specs = {}

        # Side walls are inset by self.depth on both ends so the four walls
        # meet at the corners without overlap. Front/back walls own the
        # corners; side walls stop short of them.
        facade_configs = [
            (0.0, front_width, "FRONT", (0, 0.0, 0.0)),
            (0.0, front_width, "SIDE", (2, front_width, side_width)),
            (self.depth, side_width - self.depth, "SIDE", (1, front_width, 0.0)),
            (self.depth, side_width - self.depth, "SIDE", (3, 0.0, side_width)),
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
            0.0, front_width, 0.0, side_width,
            self.height, self.height + self.roof_thickness,
        )

        # NOTE: no parent linking. Anchor empty exists only as a return value
        # for the AssetFactory framework; labeled parts stay top-level.
        anchor = bpy.data.objects.new("building_facade_mat_logged", None)
        bpy.context.collection.objects.link(anchor)

        self._semantic_specs = {
            "meta": {
                "wall_material": self.wall_material,
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

        return anchor

    # ------------------------------------------------------------------
    # Export helpers
    # ------------------------------------------------------------------

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

        meta = self._semantic_specs["meta"]
        parts = self._semantic_specs["parts"]

        with open(output_path, "w", encoding="utf-8") as f:
            f.write("from infinigen.assets.utils.object import new_bbox\n\n")
            f.write(f"# wall_material={meta['wall_material']}\n\n")

            counter = {}
            for semantic in ["wall", "window", "lintel", "sill_course",
                             "door", "roof"]:
                for bounds in parts.get(semantic, []):
                    idx = counter.get(semantic, 0)
                    counter[semantic] = idx + 1
                    name = f"{semantic}_{idx:02d}"
                    x0, x1, y0, y1, z0, z1 = bounds
                    f.write(
                        f"obj = new_bbox("
                        f"{x0:.9f}, {x1:.9f}, {y0:.9f}, {y1:.9f}, "
                        f"{z0:.9f}, {z1:.9f})\n"
                    )
                    f.write(f'obj.name = "{name}"\n\n')

        return output_path

    def export_sanitized_script(self, output_path: str) -> str:
        return self.export_logged_script(output_path)

    # ------------------------------------------------------------------
    # Refactored-script export (mirrors chair_logged_v2.export_refactored_script)
    # ------------------------------------------------------------------

    def _get_params_dict(self) -> dict:
        """Return all generator parameters needed to reproduce the asset.

        These become ``self.<name> = <value>`` lines in the refactored script's
        ``__init__``. Includes both the constructor-time parameters AND the
        per-call ``front_width`` / ``side_width`` (set in ``create_asset``).
        """
        return {
            "wall_material": str(self.wall_material),
            "ground_h": float(self.ground_h),
            "floor_h": float(self.floor_h),
            "side_margin": float(self.side_margin),
            "door_h": float(self.door_h),
            "door_w": float(self.door_w),
            "roof_thickness": float(self.roof_thickness),
            "n_upper_floors": int(self.n_upper_floors),
            "tile_w": float(self.tile_w),
            "sill": float(self.sill),
            "win_h": float(self.win_h),
            "win_top_gap": float(self.win_top_gap),
            "depth": float(self.depth),
            "opening_protrusion": float(self.opening_protrusion),
            "win_pad_frac": float(self.win_pad_frac),
            "lintel_h": float(self.lintel_h),
            "sill_course_h": float(self.sill_course_h),
            "lintel_overhang": float(self.lintel_overhang),
            "height": float(self.height),
            "front_width": float(self.front_width),
            "side_width": float(self.side_width),
        }

    def export_refactored_script(self, output_path: str) -> str:
        """Emit a ``Generator`` class that calls codebank helpers.

        Layout mirrors ``chair_logged_v2.export_refactored_script``:

            class Generator:
                def __init__(self):
                    self.<param> = <inline value>
                    ...
                    self._obj_to_label = {}
                    self._label_counters = {}

                def generate(self):
                    parts = []
                    _add_named_box(parts, "wall", ..., **kw)
                    _build_facade(parts, ..., **kw)
                    ...
                    return parts

        The codebank functions are produced by the AST extractor in
        ``infinigen_examples/generate_logged_assets.py`` from
        ``BuildingFacadeMatFactory``. Their signatures expose every state
        attribute as a keyword-only parameter, so each helper invocation
        passes state explicitly via ``kw=self.kw``.
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
        # extractor for ``BuildingFacadeMatFactory``. If a self.X reference is
        # added/removed inside one of these methods, regenerate codebank.py and
        # update the matching list here.
        helper_kwargs = {
            "_add_named_box": [
                "_label_counters", "_obj_to_label",
            ],
            "_build_facade": [
                "_label_counters", "_obj_to_label",
                "door_h", "door_w", "floor_h", "ground_h",
                "lintel_h", "lintel_overhang", "n_upper_floors",
                "opening_protrusion", "side_margin", "sill",
                "sill_course_h", "tile_w", "win_h", "win_pad_frac",
                "win_top_gap",
            ],
        }

        def call(helper: str, *positional: str) -> str:
            kws = ", ".join(f"{n}=self.{n}" for n in helper_kwargs[helper])
            if positional:
                return f"{helper}({', '.join(positional)}, {kws})"
            return f"{helper}({kws})"

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

            # The four facade walls. Side walls are inset by self.depth on
            # both ends so corners are owned by front/back walls (no overlap).
            facades = [
                ("0.0", "self.front_width", '"FRONT"', "(0, 0.0, 0.0)"),
                ("0.0", "self.front_width", '"SIDE"',
                 "(2, self.front_width, self.side_width)"),
                ("self.depth", "self.side_width - self.depth", '"SIDE"',
                 "(1, self.front_width, 0.0)"),
                ("self.depth", "self.side_width - self.depth", '"SIDE"',
                 "(3, 0.0, self.side_width)"),
            ]
            for x_start, x_end, kind, transform in facades:
                rot_k, _, _ = transform.strip("()").split(",")
                tx_ty = transform.strip("()").split(",")
                tx = tx_ty[1].strip()
                ty = tx_ty[2].strip()
                wall_call = call(
                    "_add_named_box",
                    "parts", '"wall"', x_start, x_end,
                    "0.0", "self.depth", "0.0", "self.height",
                    rot_k.strip(), tx, ty,
                )
                f.write(f"        {wall_call}\n")
                facade_call = call(
                    "_build_facade",
                    "parts", x_start, x_end, kind,
                    "0.0", "self.depth", transform,
                )
                f.write(f"        {facade_call}\n")

            roof_call = call(
                "_add_named_box",
                "parts", '"roof"', "0.0", "self.front_width",
                "0.0", "self.side_width", "self.height",
                "self.height + self.roof_thickness",
            )
            f.write(f"        {roof_call}\n")
            f.write("        return parts\n\n\n")

            f.write('if __name__ == "__main__":\n')
            f.write("    Generator().generate()\n")

        return output_path
