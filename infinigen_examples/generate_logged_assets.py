import argparse
import os
from pathlib import Path

import bpy
import numpy as np

from infinigen.core import init
from infinigen.core.util import blender as butil
from infinigen.core.util.math import FixedSeed

# Import the logged chair factory
from infinigen.assets.objects.seating.chairs.chair_logged import ChairFactoryLogged


def make_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", type=int, nargs="*", default=[41, 42])
    parser.add_argument(
        "--start_seed", type=int, default=None, help="Start seed for range generation"
    )
    parser.add_argument(
        "--variants",
        type=int,
        default=0,
        help="Number of sequential variants to generate from start_seed",
    )
    parser.add_argument("--output_root", type=Path, default=Path("outputs/chairs"))
    parser.add_argument("--resolution", type=str, default="1024x1024")
    parser.add_argument("--samples", type=int, default=64)
    parser.add_argument("--save_blend", action="store_true")
    parser.add_argument("--export_script", action="store_true", default=True)
    parser.add_argument("--configs", type=str, nargs="+", default=[])
    parser.add_argument("--overrides", type=str, nargs="+", default=[])
    return init.parse_args_blender(parser)


def generate_one(seed: int, output_root: Path):
    # Prepare scene per variant
    butil.clear_scene()
    scene = bpy.context.scene
    scene.render.filepath = str(output_root)

    # Output folder
    out_dir = output_root / f"variant_{seed:03d}"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Generate asset
    fac = ChairFactoryLogged(seed)
    with FixedSeed(seed):
        parent = fac.spawn_asset(seed)

    # Save .blend if requested
    blend_path = out_dir / "scene.blend"
    if ARGS.save_blend:
        butil.save_blend(blend_path, autopack=True)

    # Export sanitized script if requested
    if ARGS.export_script:
        script_path = out_dir / "Chair_sanitized.py"
        fac.export_sanitized_script(str(script_path))

    if ARGS.save_blend:
        print(f"Saved: {blend_path}")
    if ARGS.export_script:
        print(f"Saved: {out_dir / 'Chair_sanitized.py'}")


def main(args):
    # Load gin configs so blender/cycles configuration has required parameters
    init.apply_gin_configs(
        ["infinigen_examples/configs_indoor", "infinigen_examples/configs_nature"],
        configs=args.configs,
        overrides=args.overrides,
        skip_unknown=True,
    )

    # One-time Blender configuration
    init.configure_blender()

    # Set render settings
    res_x, res_y = map(int, args.resolution.split("x"))
    bpy.context.scene.render.resolution_x = res_x
    bpy.context.scene.render.resolution_y = res_y
    bpy.context.scene.cycles.samples = args.samples

    args.output_root.mkdir(parents=True, exist_ok=True)

    # Compute seed list based on either explicit --seeds or --start_seed/--variants
    seeds = list(args.seeds) if args.seeds else []
    if args.start_seed is not None and args.variants and args.variants > 0:
        seeds = [args.start_seed + i for i in range(args.variants)]
    elif not seeds:
        seeds = [41, 42]

    global ARGS
    ARGS = args

    for seed in seeds:
        generate_one(seed, args.output_root)


if __name__ == "__main__":
    args = make_args()
    main(args)
