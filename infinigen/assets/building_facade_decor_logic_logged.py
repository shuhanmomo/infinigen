import json
import os

import bpy
import numpy as np

from infinigen.assets.building_facade_decor_logic import BuildingFacadeDecorFactory
from infinigen.assets.utils.object import new_bbox


class BuildingFacadeDecorFactoryLogged(BuildingFacadeDecorFactory):
    """Logged facade decor generator that preserves semantic layers.

    This mirrors :class:`BuildingFacadeDecorFactory` exactly, but records the
    world-space bounds of each emitted cuboid so the asset can be exported as a
    deterministic logged script.
    """

    def __init__(self, factory_seed, coarse=False):
        super().__init__(factory_seed=factory_seed, coarse=coarse)
        self._semantic_specs = None
        self._current_specs = None

    # ------------------------------------------------------------------
    # Geometry helpers
    # ------------------------------------------------------------------

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
        name = self._next_name(label)
        obj.name = name
        obj["semantic_type"] = label
        parts.append(obj)
        if self._current_specs is not None:
            self._current_specs.setdefault(label, []).append(
                (wx0, wx1, wy0, wy1, z0, z1)
            )

    # ------------------------------------------------------------------
    # Asset creation
    # ------------------------------------------------------------------

    def create_asset(self, **params):
        self._obj_to_label = {}
        self._label_counters = {}

        front_width = float(params.get("front_width", np.random.uniform(12.0, 22.0)))
        side_width = float(params.get("side_width", np.random.uniform(10.0, 18.0)))

        parts = []
        self._current_specs = {}

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

        parent = bpy.data.objects.new("building_facade_decor_logged", None)
        parent["decor_logic"] = "location_conditioned_v1"
        bpy.context.collection.objects.link(parent)
        for obj in parts:
            obj.parent = parent

        self._semantic_specs = {
            "meta": {
                "decor_logic": "location_conditioned_v1",
                "front_width": front_width,
                "side_width": side_width,
                "height": self.height,
                "ground_h": self.ground_h,
                "floor_h": self.floor_h,
                "n_upper_floors": self.n_upper_floors,
                "tile_w": self.tile_w,
                "side_margin": self.side_margin,
                "depth": self.depth,
                "roof_thickness": self.roof_thickness,
                "door_h": self.door_h,
                "door_w": self.door_w,
            },
            "parts": self._current_specs,
        }
        self._current_specs = None

        return parent

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

        semantic_order = [
            "wall",
            "window",
            "sill",
            "lintel",
            "jamb",
            "panel",
            "door",
            "door_lintel",
            "door_jamb",
            "door_crown",
            "roof",
        ]
        semantic_order.extend(
            s for s in parts.keys() if s not in semantic_order
        )

        with open(output_path, "w", encoding="utf-8") as f:
            f.write("import bpy\n")
            f.write("from infinigen.assets.utils.object import new_bbox\n\n")
            f.write("# Logged facade decor script (each element is its own object)\n")
            f.write(
                f"# decor_logic={meta['decor_logic']}, "
                f"front_width={meta['front_width']:.6f}, "
                f"side_width={meta['side_width']:.6f}\n\n"
            )
            f.write(
                'parent = bpy.data.objects.new("building_facade_decor_logged", None)\n'
            )
            f.write(f'parent["decor_logic"] = "{meta["decor_logic"]}"\n')
            f.write("bpy.context.collection.objects.link(parent)\n\n")

            counter = {}
            for semantic in semantic_order:
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
                    f.write(f'obj.name = "{name}"\n')
                    f.write(f'obj["semantic_type"] = "{semantic}"\n')
                    f.write("obj.parent = parent\n\n")

        return output_path

    def export_sanitized_script(self, output_path: str) -> str:
        return self.export_logged_script(output_path)
