"""Generate inspectable Blender scenes for BuildingFacadeDecorV2Factory.

Usage:
  blender -b --python _inspect_decor_v2.py -- --start_seed 41 --variants 5 \
        --output outputs/building_facade_decor_v2_inspect

For each seed:
  - clears the scene
  - constructs the factory with FixedSeed(seed)
  - runs create_asset() (parts land as top-level objects)
  - drops a small floor plane and a camera that frames the building
  - saves outputs/.../variant_<seed>/scene.blend
  - dumps obj_to_label.json next to it

Open the .blend in Blender to inspect; press F12 if you also want a render.
"""

import argparse
import sys
from pathlib import Path

import bpy
import numpy as np

import infinigen  # noqa: F401  (sets up sys.path inside the bundled blender)
from infinigen.assets.building_facade_decor_logic_v2 import (
    BuildingFacadeDecorV2Factory,
)
from infinigen.core.util import blender as butil
from infinigen.core.util.math import FixedSeed


def cli_args(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("--start_seed", type=int, default=41)
    parser.add_argument("--variants", type=int, default=5)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs") / "building_facade_decor_v2_inspect",
    )
    parser.add_argument(
        "--no_camera",
        action="store_true",
        help="Skip auto camera placement (useful in fully headless usage).",
    )
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    else:
        argv = []
    return parser.parse_args(argv)


def add_camera_for_building(front_w, side_w, height):
    """Drop a perspective camera that frames the whole building."""
    cx = front_w / 2.0
    cy = side_w / 2.0
    cz = height / 2.0
    diag = float(np.hypot(front_w, side_w))
    dist = max(diag * 1.6, height * 1.6, 25.0)

    cam_loc = (cx + dist * 0.85, cy - dist * 0.85, cz + height * 0.55)
    bpy.ops.object.camera_add(location=cam_loc)
    cam = bpy.context.active_object
    direction = np.array([cx - cam_loc[0], cy - cam_loc[1], cz - cam_loc[2]])
    rot_z = float(np.arctan2(direction[1], direction[0])) + np.pi / 2
    rot_x = float(np.arctan2(np.hypot(direction[0], direction[1]), -direction[2]))
    cam.rotation_euler = (rot_x, 0.0, rot_z)
    bpy.context.scene.camera = cam
    return cam


def add_simple_lighting():
    bpy.ops.object.light_add(type="SUN", location=(0, 0, 50))
    sun = bpy.context.active_object
    sun.data.energy = 4.0
    sun.rotation_euler = (np.deg2rad(-45), np.deg2rad(20), np.deg2rad(30))
    world = bpy.context.scene.world
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs[1].default_value = 0.5  # ambient strength


def build_one(seed, output_root, args):
    butil.clear_scene()
    fac = BuildingFacadeDecorV2Factory(factory_seed=seed)
    with FixedSeed(seed):
        anchor = fac.create_asset()
    n_parts = sum(
        1
        for o in bpy.context.collection.objects
        if o is not anchor and o.type == "MESH"
    )
    print(f"  seed {seed}: built {n_parts} parts "
          f"(front={fac.front_width:.2f}, side={fac.side_width:.2f}, "
          f"H={fac.height:.2f}, n_mid={fac.n_mid_floors})")

    if not args.no_camera:
        add_camera_for_building(fac.front_width, fac.side_width, fac.height)
        add_simple_lighting()

    out_dir = output_root / f"variant_{seed:03d}"
    out_dir.mkdir(parents=True, exist_ok=True)
    blend_path = out_dir / "scene.blend"
    butil.save_blend(str(blend_path), autopack=True)
    fac.write_obj_to_label(out_dir)
    print(f"           -> {blend_path}")
    return blend_path


def main(argv):
    args = cli_args(argv)
    args.output.mkdir(parents=True, exist_ok=True)
    print(f"Output root: {args.output.resolve()}")

    saved = []
    for i in range(args.variants):
        seed = args.start_seed + i
        try:
            saved.append(build_one(seed, args.output, args))
        except Exception as e:
            print(f"  seed {seed}: FAILED -- {e}")
            raise
    print(f"Saved {len(saved)} variant(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
