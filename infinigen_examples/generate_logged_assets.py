import argparse
import os
from pathlib import Path

import bpy
import numpy as np
import sys

sys.path.append("./")
sys.path.append("../")
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
    parser.add_argument(
        "--export_refactored",
        action="store_true",
        help="Export refactored-style script (prog_pred_blender.py) for evaluator comparison",
    )
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
        print(f"Saved: {script_path}")

    # Export refactored script for evaluator comparison
    if ARGS.export_refactored:
        # Create evaluator-compatible structure: variant_{idx}/{subdir}/prog_*.py
        # prog_gold_blender.py = primitive script (sanitized)
        # prog_pred_blender.py = refactored script (helper calls)
        eval_dir = out_dir / "Chair_infinigen"
        eval_dir.mkdir(parents=True, exist_ok=True)

        gold_path = eval_dir / "prog_gold_blender.py"
        pred_path = eval_dir / "prog_pred_blender.py"

        # Export primitive as gold
        fac.export_sanitized_script(str(gold_path))
        print(f"Saved: {gold_path}")

        # Export refactored as pred
        fac.export_refactored_script(str(pred_path))
        print(f"Saved: {pred_path}")

    if ARGS.save_blend:
        print(f"Saved: {blend_path}")


def export_codebank(output_path: Path):
    """Export Infinigen chair helper functions as a codebank.py file."""
    codebank_content = '''"""Infinigen Chair Helper Functions (Codebank).

This file contains the high-level helper functions from the Infinigen
ChairFactory, extracted as standalone functions for evaluator comparison.
"""

import bpy
import numpy as np
from numpy.random import uniform
from infinigen.assets.utils.decorate import (
    write_attribute, write_co, read_co, read_edge_center,
    read_edge_direction, remove_edges, remove_vertices,
    select_edges, solidify, subsurf,
)
from infinigen.assets.utils.draw import bezier_curve, align_bezier
from infinigen.assets.utils.object import join_objects, new_bbox
from infinigen.assets.utils.nodegroup import geo_radius
from infinigen.core.util import blender as butil
from infinigen.core import surface
from infinigen.core.util.blender import deep_clone_obj


def make_seat(width, size, thickness, bevel_width, seat_back, seat_mid,
              seat_mid_x, seat_mid_z, seat_front, is_seat_round, is_seat_subsurf):
    """Create the chair seat."""
    x_anchors = np.array([0, 0.1, 1, seat_mid_x, seat_back, 0]) * width / 2
    y_anchors = np.array([-seat_front, -seat_front, -1, -seat_mid, 0, 0]) * size
    z_anchors = np.array([0, 0, 0, seat_mid_z, 0, 0]) * thickness
    vector_locations = [4] if is_seat_round else [2, 4]
    obj = bezier_curve((x_anchors, y_anchors, z_anchors), vector_locations)
    butil.modify_mesh(obj, "MIRROR")
    with butil.ViewportMode(obj, "EDIT"):
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.mesh.fill_grid(use_interp_simple=True)
    butil.modify_mesh(obj, "SOLIDIFY", thickness=thickness, offset=0)
    subsurf(obj, 1, not is_seat_subsurf)
    butil.modify_mesh(obj, "BEVEL", width=bevel_width, segments=8)
    return obj


def make_limb(leg_ends, leg_starts, leg_type, limb_profile, leg_thickness, size):
    """Create limb objects (used for legs and backs)."""
    objs = []
    for leg_start, leg_end in zip(leg_starts, leg_ends):
        if leg_type == "up-curved":
            axes = [(0, 0, 1), None]
            scale = [limb_profile, 1]
        elif leg_type == "down-curved":
            axes = [None, (0, 0, 1)]
            scale = [1, limb_profile]
        else:
            axes = None
            scale = None
        obj = align_bezier(np.stack([leg_start, leg_end], -1), axes, scale)
        obj.location = (
            np.array([
                1 if leg_start[0] < 0 else -1,
                1 if leg_start[1] < -size / 2 else -1,
                0,
            ]) * leg_thickness / 2
        )
        butil.apply_transform(obj, True)
        objs.append(obj)
    return objs


def make_legs(width, size, seat_back, leg_x_offset, leg_y_offset, leg_height,
              leg_type, limb_profile, leg_thickness):
    """Create the four chair legs."""
    leg_starts = np.array([
        [-seat_back, 0, 0], [-1, -1, 0], [1, -1, 0], [seat_back, 0, 0]
    ]) * np.array([[width / 2, size, 0]])
    leg_ends = leg_starts.copy()
    leg_ends[[0, 1], 0] -= leg_x_offset
    leg_ends[[2, 3], 0] += leg_x_offset
    leg_ends[[0, 3], 1] += leg_y_offset[0]
    leg_ends[[1, 2], 1] -= leg_y_offset[1]
    leg_ends[:, -1] = -leg_height
    return make_limb(leg_ends, leg_starts, leg_type, limb_profile, leg_thickness, size)


def make_backs(width, seat_back, back_x_offset, back_y_offset, back_height,
               leg_type, limb_profile, leg_thickness, size):
    """Create the two backrest posts."""
    back_starts = np.array([[-seat_back, 0, 0], [seat_back, 0, 0]]) * width / 2
    back_ends = back_starts.copy()
    back_ends[:, 0] += np.array([back_x_offset, -back_x_offset])
    back_ends[:, 1] = back_y_offset
    back_ends[:, 2] = back_height
    return make_limb(back_starts, back_ends, leg_type, limb_profile, leg_thickness, size)


def make_leg_decors(legs, has_leg_x_bar, has_leg_y_bar, leg_height,
                    leg_offset_bar, leg_thickness, is_leg_round, bevel_width):
    """Create stretcher bars between legs."""
    objs = []
    if has_leg_x_bar:
        z_height = -leg_height * uniform(*leg_offset_bar)
        locs = []
        for obj in legs:
            co = read_co(obj)
            locs.append(co[np.argmin(np.abs(co[:, -1] - z_height))])
        bar1 = bezier_curve(np.stack([locs[0], locs[3]], -1))
        bar2 = bezier_curve(np.stack([locs[1], locs[2]], -1))
        for bar in [bar1, bar2]:
            solidify_limb(bar, 0, leg_thickness, is_leg_round, bevel_width)
        objs.extend([bar1, bar2])
    if has_leg_y_bar:
        z_height = -leg_height * uniform(*leg_offset_bar)
        locs = []
        for obj in legs:
            co = read_co(obj)
            locs.append(co[np.argmin(np.abs(co[:, -1] - z_height))])
        bar1 = bezier_curve(np.stack([locs[0], locs[1]], -1))
        bar2 = bezier_curve(np.stack([locs[2], locs[3]], -1))
        for bar in [bar1, bar2]:
            solidify_limb(bar, 1, leg_thickness, is_leg_round, bevel_width)
        objs.extend([bar1, bar2])
    return objs


def make_back_decors(backs, back_thickness, thickness, back_profile, back_height,
                     back_type, back_vertical_cuts, back_partial_scale, bevel_width, is_leg_round):
    """Create backrest panel/bars."""
    obj = join_objects([deep_clone_obj(b) for b in backs])
    x, y, z = read_co(obj).T
    x += np.where(x > 0, back_thickness / 2, -back_thickness / 2)
    write_co(obj, np.stack([x, y, z], -1))
    smoothness = uniform(0, 1)
    profile_shape_factor = uniform(0, 0.4)
    with butil.ViewportMode(obj, "EDIT"):
        bpy.ops.mesh.select_mode(type="EDGE")
        center = read_edge_center(obj)
        for z_min, z_max in back_profile:
            select_edges(obj, (z_min * back_height <= center[:, -1]) & (center[:, -1] <= z_max * back_height))
            bpy.ops.mesh.bridge_edge_loops(number_cuts=64, interpolation="LINEAR",
                                           smoothness=smoothness, profile_shape_factor=profile_shape_factor)
        bpy.ops.mesh.select_loose()
        bpy.ops.mesh.delete()
    butil.modify_mesh(obj, "SOLIDIFY", thickness=np.minimum(thickness, back_thickness), offset=0)
    butil.modify_mesh(obj, "BEVEL", width=bevel_width, segments=8)
    parts = [obj]
    if back_type == "vertical-bar":
        other = join_objects([deep_clone_obj(b) for b in backs])
        with butil.ViewportMode(other, "EDIT"):
            bpy.ops.mesh.select_mode(type="EDGE")
            bpy.ops.mesh.select_all(action="SELECT")
            bpy.ops.mesh.bridge_edge_loops(number_cuts=back_vertical_cuts, interpolation="LINEAR",
                                           smoothness=smoothness, profile_shape_factor=profile_shape_factor)
            bpy.ops.mesh.select_all(action="INVERT")
            bpy.ops.mesh.delete()
            bpy.ops.mesh.select_all(action="SELECT")
            bpy.ops.mesh.delete(type="ONLY_FACE")
        remove_edges(other, np.abs(read_edge_direction(other)[:, -1]) < 0.5)
        remove_vertices(other, lambda x, y, z: z < -thickness / 2)
        remove_vertices(other, lambda x, y, z: z > (back_profile[0][0] + back_profile[0][1]) * back_height / 2)
        solidify_limb(other, 2, back_thickness, is_leg_round, bevel_width)
        parts.append(other)
    elif back_type == "partial":
        co = read_co(obj)
        co[:, 1] *= back_partial_scale
        write_co(obj, co)
    return parts


def make_arms(seat, backs, arm_thickness, arm_height, arm_y, arm_z, arm_mid,
              arm_profile, is_leg_round, bevel_width):
    """Create armrests."""
    co = read_co(seat)
    end = co[np.argmin(co[:, 0] - (np.abs(co[:, 1] + arm_y) < 0.02))]
    end[0] += arm_thickness / 4
    end_ = end.copy()
    end_[0] = -end[0]
    objs = []
    co = read_co(backs[0])
    start = co[np.argmin(co[:, 0] - (np.abs(co[:, -1] - arm_z) < 0.02))]
    start[0] -= arm_thickness / 4
    start_ = start.copy()
    start_[0] = -start[0]
    for start, end in zip([start, start_], [end, end_]):
        mid = np.array([
            end[0] + arm_mid[0] * (-1 if end[0] > 0 else 1),
            end[1] + arm_mid[1],
            start[2] + arm_mid[2],
        ])
        obj = align_bezier(
            np.stack([start, mid, end], -1),
            np.array([
                [end[0] - start[0], end[1] - start[1], 0],
                [0, 1 / np.sqrt(2), 1 / np.sqrt(2)],
                [0, 0, 1],
            ]),
            [1, *arm_profile, 1],
        )
        if is_leg_round:
            surface.add_geomod(obj, geo_radius, apply=True, input_args=[arm_thickness / 2, 32],
                              input_kwargs={"to_align_tilt": False})
        else:
            with butil.ViewportMode(obj, "EDIT"):
                bpy.ops.mesh.select_all(action="SELECT")
                dx = arm_thickness if end[0] < 0 else -arm_thickness
                bpy.ops.mesh.extrude_edges_move(TRANSFORM_OT_translate={"value": (dx, 0, 0)})
            butil.modify_mesh(obj, "SOLIDIFY", thickness=arm_height, offset=0)
        objs.append(obj)
    return objs


def solidify_limb(obj, axis, thickness, is_leg_round, bevel_width):
    """Apply solidify to a limb object."""
    if is_leg_round:
        solidify(obj, axis, thickness)
        butil.modify_mesh(obj, "BEVEL", width=bevel_width, segments=8)
    else:
        surface.add_geomod(obj, geo_radius, apply=True, input_args=[thickness / 2, 32])
    return obj


def finalize_parts(parts):
    """Apply final rotation and transforms to all parts."""
    for o in parts:
        o.rotation_euler.z += np.pi / 2
        butil.apply_transform(o)
    return parts
'''
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(codebank_content)
    print(f"Saved: {output_path}")


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

    # Export codebank if refactored mode is enabled
    if args.export_refactored:
        codebank_path = args.output_root / "codebank.py"
        export_codebank(codebank_path)

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
