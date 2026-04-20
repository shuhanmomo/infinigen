import bpy
import numpy as np
from numpy.random import uniform
from typing import Any, Dict, Iterable, List, Optional, Tuple
import sys

sys.path.append("./")
sys.path.append("../")
# Import modules (not names) so we can wrap low-level calls
from infinigen.assets.composition import material_assignments
from infinigen.assets.utils import decorate as deco
from infinigen.assets.utils import draw as draw_utils
from infinigen.assets.utils.object import (
    join_objects as join_objects_impl,
    new_bbox as new_bbox_impl,
)
from infinigen.assets.utils.nodegroup import geo_radius
from infinigen.core import surface as surface_mod
from infinigen.core.placement.factory import AssetFactory
from infinigen.core.surface import NoApply
from infinigen.core.util import blender as butil
from infinigen.core.util.blender import deep_clone_obj as deep_clone_obj_impl
from infinigen.core.util.math import FixedSeed
from infinigen.core.util.random import log_uniform, weighted_sample
from infinigen.core.util.random import random_general as rg


class _SanitizedLogger:
    def __init__(self):
        self.lines: List[str] = []
        self.used_imports: set[Tuple[str, str]] = set()
        self.obj_counter: int = 0
        self.obj_name_map: dict[int, str] = {}
        self.indent_level: int = 0
        self._capture_stack: List[List[str]] = []

    def reset(self):
        self.lines.clear()
        self.used_imports.clear()
        self.obj_counter = 0
        self.obj_name_map.clear()
        self.indent_level = 0
        self._capture_stack.clear()

    def fmt_array(self, arr: np.ndarray) -> str:
        a = np.asarray(arr)
        flat = ", ".join(f"{x:.9f}" for x in a.reshape(-1))
        shape = a.shape
        if len(shape) == 1:
            return f"np.array([{flat}])"
        # Reconstruct nested list for 2D or 3D
        if len(shape) == 2:
            rows = []
            for i in range(shape[0]):
                row = ", ".join(f"{x:.9f}" for x in a[i])
                rows.append(f"[{row}]")
            return f"np.array([" + ", ".join(rows) + "])"
        if len(shape) == 3:
            planes = []
            for i in range(shape[0]):
                rows = []
                for j in range(shape[1]):
                    row = ", ".join(f"{x:.9f}" for x in a[i, j])
                    rows.append(f"[{row}]")
                planes.append("[" + ", ".join(rows) + "]")
            return f"np.array([" + ", ".join(planes) + "])"
        return f"np.array([{flat}]).reshape{shape}"

    def fmt_list_nested(self, value) -> str:
        if value is None:
            return "None"
        if isinstance(value, (list, tuple, np.ndarray)):
            if isinstance(value, np.ndarray):
                value = value.tolist()
            inner = ", ".join(
                (
                    self.fmt_list_nested(v)
                    if isinstance(v, (list, tuple)) or v is None
                    else f"{float(v):.8f}"
                )
                for v in value
            )
            open_b, close_b = (
                ("[", "]")
                if isinstance(value, list) or isinstance(value, np.ndarray)
                else ("(", ")")
            )
            return f"{open_b}{inner}{close_b}"
        # Numbers
        try:
            return f"{float(value):.8f}"
        except Exception:
            return repr(value)

    def fmt_obj(self, obj: bpy.types.Object) -> str:
        name = self.obj_name_map.get(id(obj))
        if not name:
            # Fallback to actual object name
            name = obj.name
        safe = name.replace('"', '\\"')
        return f'bpy.data.objects["{safe}"]'

    def add_import(self, module: str, name: str):
        self.used_imports.add((module, name))

    def next_obj_name(self) -> str:
        self.obj_counter += 1
        return f"obj_{self.obj_counter}"

    def register_obj(self, obj: bpy.types.Object) -> str:
        name = self.next_obj_name()
        self.obj_name_map[id(obj)] = name
        self.write(f'obj.name = "{name}"')
        self.write(f"objs.append({self.fmt_obj(obj)})")
        return name

    def write(self, s: str):
        line = ("    " * self.indent_level) + s
        if self._capture_stack:
            self._capture_stack[-1].append(line)
        else:
            self.lines.append(line)

    def increase_indent(self):
        self.indent_level += 1

    def decrease_indent(self):
        self.indent_level = max(0, self.indent_level - 1)

    def begin_capture(self):
        self._capture_stack.append([])

    def end_capture(self) -> List[str]:
        return self._capture_stack.pop() if self._capture_stack else []


SCRIPT_LOGGER = _SanitizedLogger()


class _RefactoredLogger:
    """Logger for producing refactored-style output (helper calls only).

    Produces a main script that calls high-level helpers with explicit parameters,
    suitable for comparison with the evaluator's refactored script format.
    """

    def __init__(self):
        self.lines: List[str] = []

    def reset(self):
        self.lines.clear()

    def write(self, s: str):
        self.lines.append(s)

    def log_call(self, helper_name: str, result_var: str, **kwargs):
        """Log a helper function call."""
        args_parts = []
        for k, v in kwargs.items():
            if isinstance(v, bool):
                args_parts.append(f"{k}={v}")
            elif isinstance(v, str):
                args_parts.append(f'{k}="{v}"')
            elif isinstance(v, (int, float)):
                args_parts.append(f"{k}={v}")
            elif isinstance(v, (list, tuple)):
                args_parts.append(f"{k}={list(v)}")
            elif isinstance(v, np.ndarray):
                args_parts.append(f"{k}={v.tolist()}")
            else:
                args_parts.append(f"{k}={repr(v)}")
        args_str = ", ".join(args_parts)
        self.write(f"{result_var} = {helper_name}({args_str})")


REFACTORED_LOGGER = _RefactoredLogger()


# Wrappers for low-level functions (create or mutate) to record constant calls
def bezier_curve(
    anchors: Tuple[np.ndarray, np.ndarray, np.ndarray], vector_locations=()
):
    SCRIPT_LOGGER.add_import("infinigen.assets.utils.draw", "bezier_curve")
    # Capture internal low-level logs first
    SCRIPT_LOGGER.begin_capture()
    obj = draw_utils.bezier_curve(anchors, vector_locations)
    captured = SCRIPT_LOGGER.end_capture()
    x, y, z = anchors
    # Emit creation first
    SCRIPT_LOGGER.write(
        "obj = bezier_curve(("
        + f"{SCRIPT_LOGGER.fmt_array(x)}, {SCRIPT_LOGGER.fmt_array(y)}, {SCRIPT_LOGGER.fmt_array(z)}"
        + "), "
        + str(list(vector_locations))
        + ")"
    )
    # Register and rename mapping
    orig_name = obj.name
    name = SCRIPT_LOGGER.register_obj(obj)
    obj.name = name
    # Replay captured calls with object reference replaced
    default_ref = f'bpy.data.objects["{orig_name}"]'
    new_ref = SCRIPT_LOGGER.fmt_obj(obj)
    for s in captured:
        SCRIPT_LOGGER.write(s.replace(default_ref, new_ref))
    return obj


def align_bezier(points: np.ndarray, axes=None, scale=None):
    SCRIPT_LOGGER.add_import("infinigen.assets.utils.draw", "align_bezier")
    # Capture internal logs
    SCRIPT_LOGGER.begin_capture()
    obj = draw_utils.align_bezier(points, axes, scale)
    captured = SCRIPT_LOGGER.end_capture()
    axes_str = SCRIPT_LOGGER.fmt_list_nested(axes)
    scale_str = SCRIPT_LOGGER.fmt_list_nested(scale)
    # Emit creation first
    SCRIPT_LOGGER.write(
        "obj = align_bezier("
        + SCRIPT_LOGGER.fmt_array(points)
        + ", "
        + axes_str
        + ", "
        + scale_str
        + ")"
    )
    # Register and rename mapping
    orig_name = obj.name
    name = SCRIPT_LOGGER.register_obj(obj)
    obj.name = name
    default_ref = f'bpy.data.objects["{orig_name}"]'
    new_ref = SCRIPT_LOGGER.fmt_obj(obj)
    for s in captured:
        SCRIPT_LOGGER.write(s.replace(default_ref, new_ref))
    return obj


def _emit_bezier_curve_symbolic(anchors_expr_str: str, vector_locations, anchors_arr):
    """Like the bezier_curve wrapper, but emits ``anchors_expr_str`` verbatim
    instead of dumping the resolved (x, y, z) anchor arrays. The execution still
    uses the actual ``anchors_arr``."""
    SCRIPT_LOGGER.add_import("infinigen.assets.utils.draw", "bezier_curve")
    SCRIPT_LOGGER.begin_capture()
    obj = draw_utils.bezier_curve(anchors_arr, vector_locations)
    captured = SCRIPT_LOGGER.end_capture()
    SCRIPT_LOGGER.write(
        f"obj = bezier_curve({anchors_expr_str}, {list(vector_locations)})"
    )
    orig_name = obj.name
    name = SCRIPT_LOGGER.register_obj(obj)
    obj.name = name
    default_ref = f'bpy.data.objects["{orig_name}"]'
    new_ref = SCRIPT_LOGGER.fmt_obj(obj)
    for s in captured:
        SCRIPT_LOGGER.write(s.replace(default_ref, new_ref))
    return obj


def _emit_align_bezier_symbolic(points_expr_str: str, axes, scale, points_arr):
    """Like the align_bezier wrapper, but emits ``points_expr_str`` verbatim
    instead of dumping the resolved 3xN points array."""
    SCRIPT_LOGGER.add_import("infinigen.assets.utils.draw", "align_bezier")
    SCRIPT_LOGGER.begin_capture()
    obj = draw_utils.align_bezier(points_arr, axes, scale)
    captured = SCRIPT_LOGGER.end_capture()
    if isinstance(axes, np.ndarray):
        axes_str = SCRIPT_LOGGER.fmt_array(axes)
    else:
        axes_str = SCRIPT_LOGGER.fmt_list_nested(axes)
    scale_str = SCRIPT_LOGGER.fmt_list_nested(scale)
    SCRIPT_LOGGER.write(
        f"obj = align_bezier({points_expr_str}, {axes_str}, {scale_str})"
    )
    orig_name = obj.name
    name = SCRIPT_LOGGER.register_obj(obj)
    obj.name = name
    default_ref = f'bpy.data.objects["{orig_name}"]'
    new_ref = SCRIPT_LOGGER.fmt_obj(obj)
    for s in captured:
        SCRIPT_LOGGER.write(s.replace(default_ref, new_ref))
    return obj


def write_attribute(obj: bpy.types.Object, fn, name, domain="POINT", data_type="FLOAT"):
    # Do NOT log semantic attributes like 'limb' or 'panel' in the sanitized script
    return deco.write_attribute(obj, fn, name, domain, data_type)


def write_co(obj: bpy.types.Object, arr: np.ndarray):
    SCRIPT_LOGGER.add_import("infinigen.assets.utils.decorate", "write_co")
    SCRIPT_LOGGER.write(
        f"write_co({SCRIPT_LOGGER.fmt_obj(obj)}, {SCRIPT_LOGGER.fmt_array(np.asarray(arr))})"
    )
    return deco.write_co(obj, arr)


def remove_vertices(obj: bpy.types.Object, to_delete):
    SCRIPT_LOGGER.add_import("infinigen.assets.utils.decorate", "remove_vertices")
    if not isinstance(to_delete, Iterable):
        x, y, z = deco.read_co(obj).T
        mask = to_delete(x, y, z)
        idxs = np.where(np.asarray(mask))[0].tolist()
    else:
        idxs = list(to_delete)
    SCRIPT_LOGGER.write(f"remove_vertices({SCRIPT_LOGGER.fmt_obj(obj)}, {idxs})")
    return deco.remove_vertices(obj, idxs)


def remove_edges(obj: bpy.types.Object, to_delete):
    SCRIPT_LOGGER.add_import("infinigen.assets.utils.decorate", "remove_edges")
    if not isinstance(to_delete, Iterable):
        x, y, z = deco.read_edge_center(obj).T
        mask = to_delete(x, y, z)
        idxs = np.where(np.asarray(mask))[0].tolist()
    else:
        idxs = list(to_delete)
    SCRIPT_LOGGER.write(f"remove_edges({SCRIPT_LOGGER.fmt_obj(obj)}, {idxs})")
    return deco.remove_edges(obj, idxs)


def select_edges(obj: bpy.types.Object, to_select):
    SCRIPT_LOGGER.add_import("infinigen.assets.utils.decorate", "select_edges")
    if not isinstance(to_select, Iterable):
        x, y, z = deco.read_edge_center(obj).T
        mask = to_select(x, y, z)
        idxs = np.where(np.asarray(mask))[0].tolist()
    else:
        idxs = list(to_select)
    SCRIPT_LOGGER.write(f"select_edges({SCRIPT_LOGGER.fmt_obj(obj)}, {idxs})")
    return deco.select_edges(obj, idxs)


def subsurf(obj: bpy.types.Object, levels: int, simple: bool = False):
    SCRIPT_LOGGER.add_import("infinigen.assets.utils.decorate", "subsurf")
    SCRIPT_LOGGER.write(
        f"subsurf({SCRIPT_LOGGER.fmt_obj(obj)}, {int(levels)}, {bool(simple)})"
    )
    return deco.subsurf(obj, levels, simple)


def solidify(obj: bpy.types.Object, axis: int, thickness: float):
    SCRIPT_LOGGER.add_import("infinigen.assets.utils.decorate", "solidify")
    SCRIPT_LOGGER.write(
        f"solidify({SCRIPT_LOGGER.fmt_obj(obj)}, {int(axis)}, {float(thickness)})"
    )
    return deco.solidify(obj, axis, thickness)


def join_objects(objs: List[bpy.types.Object]):
    SCRIPT_LOGGER.add_import("infinigen.assets.utils.object", "join_objects")
    obj = join_objects_impl(objs)
    refs = ", ".join(SCRIPT_LOGGER.fmt_obj(o) for o in objs)
    SCRIPT_LOGGER.write(f"obj = join_objects([{refs}])")
    name = SCRIPT_LOGGER.register_obj(obj)
    obj.name = name
    return obj


def new_bbox(xmin, xmax, ymin, ymax, zmin, zmax):
    SCRIPT_LOGGER.add_import("infinigen.assets.utils.object", "new_bbox")
    obj = new_bbox_impl(xmin, xmax, ymin, ymax, zmin, zmax)
    SCRIPT_LOGGER.write(
        f"obj = new_bbox({float(xmin):.9f}, {float(xmax):.9f}, {float(ymin):.9f}, {float(ymax):.9f}, {float(zmin):.9f}, {float(zmax):.9f})"
    )
    name = SCRIPT_LOGGER.register_obj(obj)
    obj.name = name
    return obj


def deep_clone_obj(obj: bpy.types.Object):
    SCRIPT_LOGGER.add_import("infinigen.core.util.blender", "deep_clone_obj")
    clone = deep_clone_obj_impl(obj)
    SCRIPT_LOGGER.write(f"obj = deep_clone_obj({SCRIPT_LOGGER.fmt_obj(obj)})")
    name = SCRIPT_LOGGER.register_obj(clone)
    clone.name = name
    return clone


# Monkeypatch module functions for logging
_orig_modify_mesh = butil.modify_mesh
_orig_apply_transform = butil.apply_transform


def _logged_modify_mesh(obj, *args, **kwargs):
    SCRIPT_LOGGER.add_import("infinigen.core.util", "blender as butil")
    # Log call with explicit kwargs where present
    args_list = ", ".join(repr(a) for a in args)
    if kwargs:
        kwargs_str = ", ".join(f"{k}={repr(v)}" for k, v in kwargs.items())
        sep = ", " if args_list else ""
        call = f"butil.modify_mesh({SCRIPT_LOGGER.fmt_obj(obj)}{(', ' + args_list) if args_list else ''}{sep}{kwargs_str})"
    else:
        call = (
            f"butil.modify_mesh({SCRIPT_LOGGER.fmt_obj(obj)})"
            if not args_list
            else f"butil.modify_mesh({SCRIPT_LOGGER.fmt_obj(obj)}, {args_list})"
        )
    SCRIPT_LOGGER.write(call)
    return _orig_modify_mesh(obj, *args, **kwargs)


def _logged_apply_transform(obj, *args, **kwargs):
    SCRIPT_LOGGER.add_import("infinigen.core.util", "blender as butil")
    args_list = ", ".join(repr(a) for a in args)
    if kwargs:
        kwargs_str = ", ".join(f"{k}={repr(v)}" for k, v in kwargs.items())
        sep = ", " if args_list else ""
        call = f"butil.apply_transform({SCRIPT_LOGGER.fmt_obj(obj)}{(', ' + args_list) if args_list else ''}{sep}{kwargs_str})"
    else:
        call = (
            f"butil.apply_transform({SCRIPT_LOGGER.fmt_obj(obj)})"
            if not args_list
            else f"butil.apply_transform({SCRIPT_LOGGER.fmt_obj(obj)}, {args_list})"
        )
    SCRIPT_LOGGER.write(call)
    return _orig_apply_transform(obj, *args, **kwargs)


butil.modify_mesh = _logged_modify_mesh
butil.apply_transform = _logged_apply_transform


_orig_add_geomod = surface_mod.add_geomod


def _logged_add_geomod(obj, nodegroup, apply=False, input_args=None, input_kwargs=None):
    SCRIPT_LOGGER.add_import("infinigen.core", "surface")
    # Only log when we have concrete constant arguments; skip empty to avoid invalid calls
    if input_args and len(input_args) > 0:
        SCRIPT_LOGGER.write(
            f"surface.add_geomod({SCRIPT_LOGGER.fmt_obj(obj)}, geo_radius, apply={bool(apply)}, input_args={list(input_args)}, input_kwargs={input_kwargs or {}})"
        )
    return _orig_add_geomod(
        obj, nodegroup, apply=apply, input_args=input_args, input_kwargs=input_kwargs
    )


surface_mod.add_geomod = _logged_add_geomod


class ChairFactoryLogged(AssetFactory):
    back_types = (
        "weighted_choice",
        (1, "whole"),
        (1, "partial"),
        (1, "horizontal-bar"),
        (1, "vertical-bar"),
    )

    def __init__(self, factory_seed, coarse=False):
        super().__init__(factory_seed, coarse)
        with FixedSeed(self.factory_seed):
            self.width = uniform(0.4, 0.5)
            self.size = uniform(0.38, 0.45)
            self.thickness = uniform(0.04, 0.08)
            self.bevel_width = self.thickness * (0.1 if uniform() < 0.4 else 0.5)
            self.seat_back = uniform(0.7, 1.0) if uniform() < 0.75 else 1.0
            self.seat_mid = uniform(0.7, 0.8)
            self.seat_mid_x = uniform(
                self.seat_back + self.seat_mid * (1 - self.seat_back), 1
            )
            self.seat_mid_z = uniform(0, 0.5)
            self.seat_front = uniform(1.0, 1.2)
            self.is_seat_round = uniform() < 0.6
            self.is_seat_subsurf = uniform() < 0.5

            self.leg_thickness = uniform(0.04, 0.06)
            self.limb_profile = uniform(1.5, 2.5)
            self.leg_height = uniform(0.45, 0.5)
            self.back_height = uniform(0.4, 0.5)
            self.is_leg_round = uniform() < 0.5
            self.leg_type = np.random.choice(
                ["vertical", "straight", "up-curved", "down-curved"]
            )

            self.leg_x_offset = 0
            self.leg_y_offset = 0, 0
            self.back_x_offset = 0
            self.back_y_offset = 0

            self.has_leg_x_bar = uniform() < 0.6
            self.has_leg_y_bar = uniform() < 0.6
            self.leg_offset_bar = uniform(0.2, 0.4), uniform(0.6, 0.8)

            self.has_arm = uniform() < 0.7
            self.arm_thickness = uniform(0.04, 0.06)
            self.arm_height = self.arm_thickness * uniform(0.6, 1)
            self.arm_y = uniform(0.8, 1) * self.size
            self.arm_z = uniform(0.3, 0.6) * self.back_height
            self.arm_mid = np.array(
                [uniform(-0.03, 0.03), uniform(-0.03, 0.09), uniform(-0.09, 0.03)]
            )
            self.arm_profile = log_uniform(0.1, 3, 2)

            self.back_thickness = uniform(0.04, 0.05)
            self.back_type = rg(self.back_types)
            self.back_profile = [(0, 1)]
            self.back_vertical_cuts = np.random.randint(1, 4)
            self.back_partial_scale = uniform(1, 1.4)

            limb_surface_gen_class = weighted_sample(material_assignments.furniture_leg)
            self.limb_surface_material_gen = limb_surface_gen_class()
            self.limb_surface = self.limb_surface_material_gen()

            surface_gen_class = weighted_sample(
                material_assignments.furniture_hard_surface
            )
            self.surface_material_gen = surface_gen_class()
            self.surface = self.surface_material_gen()

            if uniform() < 0.3:
                self.panel_surface = self.surface
            else:
                self.panel_surface = weighted_sample(
                    material_assignments.furniture_hard_surface
                )()()

            scratch_prob, edge_wear_prob = material_assignments.wear_tear_prob
            scratch, edge_wear = material_assignments.wear_tear
            self.scratch = None if uniform() > scratch_prob else scratch()
            self.edge_wear = None if uniform() > edge_wear_prob else edge_wear()

            self.clothes_scatter = NoApply()
            self.post_init()

    def post_init(self):
        with FixedSeed(self.factory_seed):
            if self.leg_type == "vertical":
                self.leg_x_offset = 0
                self.leg_y_offset = 0, 0
                self.back_x_offset = 0
                self.back_y_offset = 0
            else:
                self.leg_x_offset = self.width * uniform(0.05, 0.2)
                self.leg_y_offset = self.size * uniform(0.05, 0.2, 2)
                self.back_x_offset = self.width * uniform(-0.1, 0.15)
                self.back_y_offset = self.size * uniform(0.1, 0.25)

            match self.back_type:
                case "partial":
                    self.back_profile = ((uniform(0.4, 0.8), 1),)
                case "horizontal-bar":
                    n_cuts = np.random.randint(2, 4)
                    locs = uniform(1, 2, n_cuts).cumsum()
                    locs = locs / locs[-1]
                    ratio = uniform(0.5, 0.75)
                    locs = np.array(
                        [
                            (p + ratio * (l - p), l)
                            for p, l in zip([0, *locs[:-1]], locs)
                        ]
                    )
                    lowest = uniform(0, 0.4)
                    self.back_profile = locs * (1 - lowest) + lowest
                case "vertical-bar":
                    self.back_profile = ((uniform(0.8, 0.9), 1),)
                case _:
                    self.back_profile = [(0, 1)]

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        obj = new_bbox(
            -self.width / 2 - max(self.leg_x_offset, self.back_x_offset),
            self.width / 2 + max(self.leg_x_offset, self.back_x_offset),
            -self.size - self.leg_y_offset[1] - self.leg_thickness * 0.5,
            max(self.leg_y_offset[0], self.back_y_offset),
            -self.leg_height,
            self.back_height * 1.2,
        )
        obj.rotation_euler.z += np.pi / 2
        butil.apply_transform(obj)
        return obj

    def create_asset(self, **params) -> bpy.types.Object:
        SCRIPT_LOGGER.reset()
        self._last_objs: List[bpy.types.Object] = []

        obj = self.make_seat()
        legs = self.make_legs()
        backs = self.make_backs()

        parts = [obj] + legs + backs
        parts.extend(self.make_leg_decors(legs))
        if self.has_arm:
            parts.extend(self.make_arms(obj, backs))
        parts.extend(self.make_back_decors(backs))

        for o in legs:
            self.solidify(o, 2)
        for o in backs:
            self.solidify(o, 2, self.back_thickness)

        for o in parts:
            o.rotation_euler.z += np.pi / 2
            SCRIPT_LOGGER.write(
                f"{SCRIPT_LOGGER.fmt_obj(o)}.rotation_euler.z += {np.pi/2}"
            )
            butil.apply_transform(o)

        with FixedSeed(self.factory_seed):
            for o in parts:
                surface_mod.assign_material(o, self.surface)
                # Assign only if attribute exists on this object (runtime only)
                if getattr(o.data, "attributes", None) and o.data.attributes.get(
                    "panel"
                ):
                    surface_mod.assign_material(
                        o, self.panel_surface, selection="panel"
                    )
                if getattr(o.data, "attributes", None) and o.data.attributes.get(
                    "limb"
                ):
                    surface_mod.assign_material(o, self.limb_surface, selection="limb")

        self._last_objs = parts

        parent = bpy.data.objects.new("chair_logged", None)
        bpy.context.collection.objects.link(parent)
        for o in parts:
            o.parent = parent
        return parent

    def finalize_assets(self, assets):
        pass

    def make_seat(self):
        x_anchors = (
            np.array(
                [
                    0,
                    0.1,
                    1,
                    self.seat_mid_x,
                    self.seat_back,
                    0,
                ]
            )
            * self.width
            / 2
        )
        y_anchors = (
            np.array([-self.seat_front, -self.seat_front, -1, -self.seat_mid, 0, 0])
            * self.size
        )
        z_anchors = np.array([0, 0, 0, self.seat_mid_z, 0, 0]) * self.thickness
        vector_locations = [4] if self.is_seat_round else [2, 4]
        obj = bezier_curve((x_anchors, y_anchors, z_anchors), vector_locations)
        butil.modify_mesh(obj, "MIRROR")
        with butil.ViewportMode(obj, "EDIT"):
            SCRIPT_LOGGER.write(
                f'with butil.ViewportMode({SCRIPT_LOGGER.fmt_obj(obj)}, "EDIT"):'
            )
            SCRIPT_LOGGER.increase_indent()
            SCRIPT_LOGGER.write('bpy.ops.mesh.select_all(action="SELECT")')
            bpy.ops.mesh.select_all(action="SELECT")
            SCRIPT_LOGGER.write("bpy.ops.mesh.fill_grid(use_interp_simple=True)")
            bpy.ops.mesh.fill_grid(use_interp_simple=True)
            SCRIPT_LOGGER.decrease_indent()
        butil.modify_mesh(obj, "SOLIDIFY", thickness=self.thickness, offset=0)
        subsurf(obj, 1, not self.is_seat_subsurf)
        butil.modify_mesh(obj, "BEVEL", width=self.bevel_width, segments=8)
        return obj

    def make_legs(self):
        leg_starts = np.array(
            [[-self.seat_back, 0, 0], [-1, -1, 0], [1, -1, 0], [self.seat_back, 0, 0]]
        ) * np.array([[self.width / 2, self.size, 0]])
        leg_ends = leg_starts.copy()
        leg_ends[[0, 1], 0] -= self.leg_x_offset
        leg_ends[[2, 3], 0] += self.leg_x_offset
        leg_ends[[0, 3], 1] += self.leg_y_offset[0]
        leg_ends[[1, 2], 1] -= self.leg_y_offset[1]
        leg_ends[:, -1] = -self.leg_height
        return self.make_limb(leg_ends, leg_starts)

    def make_limb(self, leg_ends, leg_starts):
        objs = []
        for leg_start, leg_end in zip(leg_starts, leg_ends):
            match self.leg_type:
                case "up-curved":
                    axes = [(0, 0, 1), None]
                    scale = [self.limb_profile, 1]
                case "down-curved":
                    axes = [None, (0, 0, 1)]
                    scale = [1, self.limb_profile]
                case _:
                    axes = None
                    scale = None
            obj = align_bezier(np.stack([leg_start, leg_end], -1), axes, scale)
            obj.location = (
                np.array(
                    [
                        1 if leg_start[0] < 0 else -1,
                        1 if leg_start[1] < -self.size / 2 else -1,
                        0,
                    ]
                )
                * self.leg_thickness
                / 2
            )
            sx = 1 if leg_start[0] < 0 else -1
            sy = 1 if leg_start[1] < -self.size / 2 else -1
            SCRIPT_LOGGER.write(
                f"{SCRIPT_LOGGER.fmt_obj(obj)}.location = np.array([{sx}, {sy}, 0]) * {self.leg_thickness:.9f} / 2"
            )
            butil.apply_transform(obj, True)
            objs.append(obj)
        return objs

    def make_backs(self):
        back_starts = (
            np.array([[-self.seat_back, 0, 0], [self.seat_back, 0, 0]]) * self.width / 2
        )
        back_ends = back_starts.copy()
        back_ends[:, 0] += np.array([self.back_x_offset, -self.back_x_offset])
        back_ends[:, 1] = self.back_y_offset
        back_ends[:, 2] = self.back_height
        return self.make_limb(back_starts, back_ends)

    def make_leg_decors(self, legs):
        objs = []
        if self.has_leg_x_bar:
            z_height = -self.leg_height * uniform(*self.leg_offset_bar)
            locs = []
            SCRIPT_LOGGER.add_import("infinigen.assets.utils.decorate", "read_co")
            for i, leg in enumerate(legs):
                co = deco.read_co(leg)
                pt = co[np.argmin(np.abs(co[:, -1] - z_height))]
                SCRIPT_LOGGER.write(f"co = read_co({SCRIPT_LOGGER.fmt_obj(leg)})")
                SCRIPT_LOGGER.write(
                    f"loc_{i} = co[np.argmin(np.abs(co[:, -1] - {z_height:.9f}))]"
                )
                locs.append(pt)
            arr_03 = np.stack([locs[0], locs[3]], -1)
            b0 = _emit_bezier_curve_symbolic(
                "np.stack([loc_0, loc_3], -1)", (), arr_03
            )
            objs.append(self.solidify(b0, 0))
            arr_12 = np.stack([locs[1], locs[2]], -1)
            b1 = _emit_bezier_curve_symbolic(
                "np.stack([loc_1, loc_2], -1)", (), arr_12
            )
            objs.append(self.solidify(b1, 0))
        if self.has_leg_y_bar:
            z_height = -self.leg_height * uniform(*self.leg_offset_bar)
            locs = []
            SCRIPT_LOGGER.add_import("infinigen.assets.utils.decorate", "read_co")
            for i, leg in enumerate(legs):
                co = deco.read_co(leg)
                pt = co[np.argmin(np.abs(co[:, -1] - z_height))]
                SCRIPT_LOGGER.write(f"co = read_co({SCRIPT_LOGGER.fmt_obj(leg)})")
                SCRIPT_LOGGER.write(
                    f"loc_{i} = co[np.argmin(np.abs(co[:, -1] - {z_height:.9f}))]"
                )
                locs.append(pt)
            arr_01 = np.stack([locs[0], locs[1]], -1)
            b2 = _emit_bezier_curve_symbolic(
                "np.stack([loc_0, loc_1], -1)", (), arr_01
            )
            objs.append(self.solidify(b2, 1))
            arr_23 = np.stack([locs[2], locs[3]], -1)
            b3 = _emit_bezier_curve_symbolic(
                "np.stack([loc_2, loc_3], -1)", (), arr_23
            )
            objs.append(self.solidify(b3, 1))
        for o in objs:
            write_attribute(o, 1, "limb", "FACE")
        return objs

    def make_back_decors(self, backs, finalize=True):
        obj = join_objects([deep_clone_obj(b) for b in backs])
        obj_ref = SCRIPT_LOGGER.fmt_obj(obj)

        # X-shift on live geometry: emit read_co -> in-place modify -> write_co
        # Preserves the np.where(co[:,0] > 0, +h, -h) rule with a single scalar literal.
        bt2 = self.back_thickness / 2
        SCRIPT_LOGGER.add_import("infinigen.assets.utils.decorate", "read_co")
        SCRIPT_LOGGER.add_import("infinigen.assets.utils.decorate", "write_co")
        SCRIPT_LOGGER.write(f"co = read_co({obj_ref})")
        SCRIPT_LOGGER.write(
            f"co[:, 0] += np.where(co[:, 0] > 0, {bt2:.9f}, {-bt2:.9f})"
        )
        SCRIPT_LOGGER.write(f"write_co({obj_ref}, co)")
        co = deco.read_co(obj)
        co[:, 0] += np.where(co[:, 0] > 0, bt2, -bt2)
        deco.write_co(obj, co)

        smoothness = uniform(0, 1)
        profile_shape_factor = uniform(0, 0.4)
        with butil.ViewportMode(obj, "EDIT"):
            SCRIPT_LOGGER.write(f'with butil.ViewportMode({obj_ref}, "EDIT"):')
            SCRIPT_LOGGER.increase_indent()
            SCRIPT_LOGGER.write('bpy.ops.mesh.select_mode(type="EDGE")')
            bpy.ops.mesh.select_mode(type="EDGE")

            # `c = read_edge_center(obj)` once, matching the original code's single read
            SCRIPT_LOGGER.add_import(
                "infinigen.assets.utils.decorate", "read_edge_center"
            )
            SCRIPT_LOGGER.add_import(
                "infinigen.assets.utils.decorate", "select_edges"
            )
            SCRIPT_LOGGER.write(f"c = read_edge_center({obj_ref})")
            center = deco.read_edge_center(obj)
            bh = self.back_height
            for z_min, z_max in self.back_profile:
                # Predicate-form selection: keep the geometric rule with small literals
                mask = (z_min * bh <= center[:, -1]) & (center[:, -1] <= z_max * bh)
                SCRIPT_LOGGER.write(
                    f"select_edges({obj_ref}, "
                    f"({float(z_min):.9f} * {bh:.9f} <= c[:, -1]) "
                    f"& (c[:, -1] <= {float(z_max):.9f} * {bh:.9f}))"
                )
                # IMPORTANT: select_edges runs np.nonzero on its arg, so it expects
                # a boolean mask (or a callable), not a list of pre-computed indices.
                deco.select_edges(obj, mask)
                SCRIPT_LOGGER.write(
                    f'bpy.ops.mesh.bridge_edge_loops(number_cuts=64, interpolation="LINEAR", smoothness={smoothness:.9f}, profile_shape_factor={profile_shape_factor:.9f})'
                )
                bpy.ops.mesh.bridge_edge_loops(
                    number_cuts=64,
                    interpolation="LINEAR",
                    smoothness=smoothness,
                    profile_shape_factor=profile_shape_factor,
                )
            SCRIPT_LOGGER.write("bpy.ops.mesh.select_loose()")
            bpy.ops.mesh.select_loose()
            SCRIPT_LOGGER.write("bpy.ops.mesh.delete()")
            bpy.ops.mesh.delete()
            SCRIPT_LOGGER.decrease_indent()
        butil.modify_mesh(
            obj,
            "SOLIDIFY",
            thickness=np.minimum(self.thickness, self.back_thickness),
            offset=0,
        )
        if finalize:
            butil.modify_mesh(obj, "BEVEL", width=self.bevel_width, segments=8)
        parts = [obj]
        if self.back_type == "vertical-bar":
            other = join_objects([deep_clone_obj(b) for b in backs])
            other_ref = SCRIPT_LOGGER.fmt_obj(other)
            with butil.ViewportMode(other, "EDIT"):
                SCRIPT_LOGGER.write(
                    f'with butil.ViewportMode({other_ref}, "EDIT"):'
                )
                SCRIPT_LOGGER.increase_indent()
                SCRIPT_LOGGER.write('bpy.ops.mesh.select_mode(type="EDGE")')
                bpy.ops.mesh.select_mode(type="EDGE")
                SCRIPT_LOGGER.write('bpy.ops.mesh.select_all(action="SELECT")')
                bpy.ops.mesh.select_all(action="SELECT")
                SCRIPT_LOGGER.write(
                    f'bpy.ops.mesh.bridge_edge_loops(number_cuts={self.back_vertical_cuts}, interpolation="LINEAR", smoothness={smoothness:.9f}, profile_shape_factor={profile_shape_factor:.9f})'
                )
                bpy.ops.mesh.bridge_edge_loops(
                    number_cuts=self.back_vertical_cuts,
                    interpolation="LINEAR",
                    smoothness=smoothness,
                    profile_shape_factor=profile_shape_factor,
                )
                SCRIPT_LOGGER.write('bpy.ops.mesh.select_all(action="INVERT")')
                bpy.ops.mesh.select_all(action="INVERT")
                SCRIPT_LOGGER.write("bpy.ops.mesh.delete()")
                bpy.ops.mesh.delete()
                SCRIPT_LOGGER.write('bpy.ops.mesh.select_all(action="SELECT")')
                bpy.ops.mesh.select_all(action="SELECT")
                SCRIPT_LOGGER.write('bpy.ops.mesh.delete(type="ONLY_FACE")')
                bpy.ops.mesh.delete(type="ONLY_FACE")
                SCRIPT_LOGGER.decrease_indent()

            # remove_edges with predicate over edge-direction z component
            SCRIPT_LOGGER.add_import(
                "infinigen.assets.utils.decorate", "read_edge_direction"
            )
            SCRIPT_LOGGER.add_import(
                "infinigen.assets.utils.decorate", "remove_edges"
            )
            d = deco.read_edge_direction(other)
            mask = np.abs(d[:, -1]) < 0.5
            SCRIPT_LOGGER.write(f"d = read_edge_direction({other_ref})")
            SCRIPT_LOGGER.write(
                f"remove_edges({other_ref}, np.abs(d[:, -1]) < 0.5)"
            )
            # remove_edges expects a boolean mask (or callable), not pre-computed indices.
            deco.remove_edges(other, mask)

            # remove_vertices: z < -thickness/2
            SCRIPT_LOGGER.add_import(
                "infinigen.assets.utils.decorate", "remove_vertices"
            )
            thresh1 = -self.thickness / 2
            x, y, z = deco.read_co(other).T
            mask = z < thresh1
            SCRIPT_LOGGER.write(f"co = read_co({other_ref})")
            SCRIPT_LOGGER.write(
                f"remove_vertices({other_ref}, co[:, -1] < {thresh1:.9f})"
            )
            # remove_vertices expects a boolean mask (or callable), not pre-computed indices.
            deco.remove_vertices(other, mask)

            # remove_vertices: z > (z_min + z_max) * back_height / 2
            zmin0 = float(self.back_profile[0][0])
            zmax0 = float(self.back_profile[0][1])
            thresh2 = (zmin0 + zmax0) * bh / 2
            x, y, z = deco.read_co(other).T
            mask = z > thresh2
            SCRIPT_LOGGER.write(f"co = read_co({other_ref})")
            SCRIPT_LOGGER.write(
                f"remove_vertices({other_ref}, "
                f"co[:, -1] > ({zmin0:.9f} + {zmax0:.9f}) * {bh:.9f} / 2)"
            )
            deco.remove_vertices(other, mask)

            parts.append(self.solidify(other, 2, self.back_thickness))
        elif self.back_type == "partial":
            scale = self.back_partial_scale
            SCRIPT_LOGGER.add_import("infinigen.assets.utils.decorate", "read_co")
            SCRIPT_LOGGER.add_import("infinigen.assets.utils.decorate", "write_co")
            SCRIPT_LOGGER.write(f"co = read_co({obj_ref})")
            SCRIPT_LOGGER.write(f"co[:, 1] *= {scale:.9f}")
            SCRIPT_LOGGER.write(f"write_co({obj_ref}, co)")
            co = deco.read_co(obj)
            co[:, 1] *= scale
            deco.write_co(obj, co)
        for p in parts:
            write_attribute(p, 1, "panel", "FACE")
        return parts

    def make_arms(self, base, backs):
        SCRIPT_LOGGER.add_import("infinigen.assets.utils.decorate", "read_co")

        # Live-geometry derivation for arm 0's anchors. Emit the read_co + argmin
        # chain once (matches the actual single execution); inline the realized
        # scalars (arm_y, arm_thickness, arm_z) as literals.
        base_ref = SCRIPT_LOGGER.fmt_obj(base)
        co = deco.read_co(base)
        end = co[np.argmin(co[:, 0] - (np.abs(co[:, 1] + self.arm_y) < 0.02))]
        end[0] += self.arm_thickness / 4
        SCRIPT_LOGGER.write(f"co = read_co({base_ref})")
        SCRIPT_LOGGER.write(
            f"end = co[np.argmin(co[:, 0] - (np.abs(co[:, 1] + {self.arm_y:.9f}) < 0.02))]"
        )
        SCRIPT_LOGGER.write(f"end[0] += {self.arm_thickness:.9f} / 4")
        end_ = end.copy()
        end_[0] = -end[0]

        back0_ref = SCRIPT_LOGGER.fmt_obj(backs[0])
        co = deco.read_co(backs[0])
        start = co[np.argmin(co[:, 0] - (np.abs(co[:, -1] - self.arm_z) < 0.02))]
        start[0] -= self.arm_thickness / 4
        SCRIPT_LOGGER.write(f"co = read_co({back0_ref})")
        SCRIPT_LOGGER.write(
            f"start = co[np.argmin(co[:, 0] - (np.abs(co[:, -1] - {self.arm_z:.9f}) < 0.02))]"
        )
        SCRIPT_LOGGER.write(f"start[0] -= {self.arm_thickness:.9f} / 4")
        start_ = start.copy()
        start_[0] = -start[0]

        objs = []
        starts_pair = [start, start_]
        ends_pair = [end, end_]
        scale_list = [1, *self.arm_profile, 1]
        scale_str = SCRIPT_LOGGER.fmt_list_nested(scale_list)
        am0, am1, am2 = (
            float(self.arm_mid[0]),
            float(self.arm_mid[1]),
            float(self.arm_mid[2]),
        )

        for it_idx, (s, e) in enumerate(zip(starts_pair, ends_pair)):
            # For arm 1, the anchors are the sign-flipped copies of arm 0's anchors.
            # Emit them as fresh independent literals (no end_/start_ relation).
            if it_idx == 1:
                SCRIPT_LOGGER.write(
                    f"end = np.array([{e[0]:.9f}, {e[1]:.9f}, {e[2]:.9f}])"
                )
                SCRIPT_LOGGER.write(
                    f"start = np.array([{s[0]:.9f}, {s[1]:.9f}, {s[2]:.9f}])"
                )

            mid = np.array(
                [
                    e[0] + self.arm_mid[0] * (-1 if e[0] > 0 else 1),
                    e[1] + self.arm_mid[1],
                    s[2] + self.arm_mid[2],
                ]
            )
            # Preserve the within-call expression for `mid` instead of dumping
            # a resolved 3-vector. Sign of the x-offset depends on end[0].
            sign_x = -1 if e[0] > 0 else 1
            SCRIPT_LOGGER.write(
                "mid = np.array(["
                f"end[0] + {am0:.9f} * {sign_x}, "
                f"end[1] + {am1:.9f}, "
                f"start[2] + {am2:.9f}"
                "])"
            )

            axes = np.array(
                [
                    [e[0] - s[0], e[1] - s[1], 0],
                    [0, 1 / np.sqrt(2), 1 / np.sqrt(2)],
                    [0, 0, 1],
                ]
            )
            axes_str = (
                "np.array(["
                "[end[0] - start[0], end[1] - start[1], 0], "
                "[0, 1/np.sqrt(2), 1/np.sqrt(2)], "
                "[0, 0, 1]"
                "])"
            )
            points_arr = np.stack([s, mid, e], -1)
            # Use the symbolic-emit helper so the log references `start`, `mid`, `end`
            # rather than a frozen 3x3 array dump.
            SCRIPT_LOGGER.add_import("infinigen.assets.utils.draw", "align_bezier")
            SCRIPT_LOGGER.begin_capture()
            obj = draw_utils.align_bezier(points_arr, axes, scale_list)
            captured = SCRIPT_LOGGER.end_capture()
            SCRIPT_LOGGER.write(
                f"obj = align_bezier(np.stack([start, mid, end], -1), {axes_str}, {scale_str})"
            )
            orig_name = obj.name
            name = SCRIPT_LOGGER.register_obj(obj)
            obj.name = name
            default_ref = f'bpy.data.objects["{orig_name}"]'
            new_ref = SCRIPT_LOGGER.fmt_obj(obj)
            for line in captured:
                SCRIPT_LOGGER.write(line.replace(default_ref, new_ref))

            if self.is_leg_round:
                surface_mod.add_geomod(
                    obj,
                    geo_radius,
                    apply=True,
                    input_args=[self.arm_thickness / 2, 32],
                    input_kwargs={"to_align_tilt": False},
                )
            else:
                with butil.ViewportMode(obj, "EDIT"):
                    SCRIPT_LOGGER.write(
                        f'with butil.ViewportMode({SCRIPT_LOGGER.fmt_obj(obj)}, "EDIT"):'
                    )
                    SCRIPT_LOGGER.increase_indent()
                    SCRIPT_LOGGER.write('bpy.ops.mesh.select_all(action="SELECT")')
                    bpy.ops.mesh.select_all(action="SELECT")
                    dx = self.arm_thickness if e[0] < 0 else -self.arm_thickness
                    SCRIPT_LOGGER.write(
                        f"bpy.ops.mesh.extrude_edges_move(TRANSFORM_OT_translate={{'value': ({dx:.9f}, 0.000000000, 0.000000000)}})"
                    )
                    bpy.ops.mesh.extrude_edges_move(
                        TRANSFORM_OT_translate={
                            "value": (
                                (
                                    self.arm_thickness
                                    if e[0] < 0
                                    else -self.arm_thickness
                                ),
                                0,
                                0,
                            )
                        }
                    )
                    SCRIPT_LOGGER.decrease_indent()
                butil.modify_mesh(obj, "SOLIDIFY", thickness=self.arm_height, offset=0)
            write_attribute(obj, 1, "limb", "FACE")
            objs.append(obj)
        return objs

    def solidify(self, obj, axis, thickness=None):
        if thickness is None:
            thickness = self.leg_thickness
        if self.is_leg_round:
            solidify(obj, axis, thickness)
            butil.modify_mesh(obj, "BEVEL", width=self.bevel_width, segments=8)
        else:
            surface_mod.add_geomod(
                obj, geo_radius, apply=True, input_args=[thickness / 2, 32]
            )
        write_attribute(obj, 1, "limb", "FACE")
        return obj

    def export_sanitized_script(self, output_path: str) -> str:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("import bpy\n")
            f.write("import numpy as np\n")
            # Static imports for used helpers
            f.write(
                "from infinigen.assets.utils.decorate import write_attribute, write_co, read_co, read_edge_center, read_edge_direction, remove_edges, remove_vertices, select_edges, solidify, subsurf\n"
            )
            f.write(
                "from infinigen.assets.utils.draw import bezier_curve, align_bezier\n"
            )
            f.write(
                "from infinigen.assets.utils.object import join_objects, new_bbox\n"
            )
            f.write("from infinigen.assets.utils.nodegroup import geo_radius\n")
            f.write("from infinigen.core.util import blender as butil\n")
            f.write("from infinigen.core import surface\n")
            f.write("from infinigen.core.util.blender import deep_clone_obj\n\n")
            f.write("objs = []\n\n")
            for line in SCRIPT_LOGGER.lines:
                f.write(line + "\n")
        return output_path

    def export_refactored_script(self, output_path: str) -> str:
        """Export a refactored-style script showing helper calls with inline values.

        This produces a main script with inline parameter values (not declarations),
        suitable for fair LOC comparison with primitive scripts.
        """
        p = self._get_params_dict()

        def fmt(v):
            if isinstance(v, bool):
                return str(v)
            elif isinstance(v, str):
                return f'"{v}"'
            elif isinstance(v, (list, tuple)):
                return str(list(v))
            return str(v)

        with open(output_path, "w", encoding="utf-8") as f:
            f.write("import bpy\n")
            f.write("import numpy as np\n")
            f.write("from codebank import (\n")
            f.write("    make_seat, make_legs, make_backs,\n")
            f.write("    make_leg_decors, make_back_decors, make_arms,\n")
            f.write("    solidify_limb, finalize_parts,\n")
            f.write(")\n\n")

            # Main script with inline values
            f.write("parts = []\n")
            f.write(
                f"seat = make_seat({fmt(p['width'])}, {fmt(p['size'])}, {fmt(p['thickness'])}, {fmt(p['bevel_width'])}, {fmt(p['seat_back'])}, {fmt(p['seat_mid'])}, {fmt(p['seat_mid_x'])}, {fmt(p['seat_mid_z'])}, {fmt(p['seat_front'])}, {fmt(p['is_seat_round'])}, {fmt(p['is_seat_subsurf'])})\n"
            )
            f.write("parts.append(seat)\n")
            f.write(
                f"legs = make_legs({fmt(p['width'])}, {fmt(p['size'])}, {fmt(p['seat_back'])}, {fmt(p['leg_x_offset'])}, {fmt(p['leg_y_offset'])}, {fmt(p['leg_height'])}, {fmt(p['leg_type'])}, {fmt(p['limb_profile'])}, {fmt(p['leg_thickness'])})\n"
            )
            f.write("parts.extend(legs)\n")
            f.write(
                f"backs = make_backs({fmt(p['width'])}, {fmt(p['seat_back'])}, {fmt(p['back_x_offset'])}, {fmt(p['back_y_offset'])}, {fmt(p['back_height'])}, {fmt(p['leg_type'])}, {fmt(p['limb_profile'])}, {fmt(p['leg_thickness'])}, {fmt(p['size'])})\n"
            )
            f.write("parts.extend(backs)\n")
            f.write(
                f"leg_decors = make_leg_decors(legs, {fmt(p['has_leg_x_bar'])}, {fmt(p['has_leg_y_bar'])}, {fmt(p['leg_height'])}, {fmt(p['leg_offset_bar'])}, {fmt(p['leg_thickness'])}, {fmt(p['is_leg_round'])}, {fmt(p['bevel_width'])})\n"
            )
            f.write("parts.extend(leg_decors)\n")
            if p["has_arm"]:
                f.write(
                    f"arms = make_arms(seat, backs, {fmt(p['arm_thickness'])}, {fmt(p['arm_height'])}, {fmt(p['arm_y'])}, {fmt(p['arm_z'])}, {fmt(p['arm_mid'])}, {fmt(p['arm_profile'])}, {fmt(p['is_leg_round'])}, {fmt(p['bevel_width'])})\n"
                )
                f.write("parts.extend(arms)\n")
            f.write(
                f"back_decors = make_back_decors(backs, {fmt(p['back_thickness'])}, {fmt(p['thickness'])}, {fmt(p['back_profile'])}, {fmt(p['back_height'])}, {fmt(p['back_type'])}, {fmt(p['back_vertical_cuts'])}, {fmt(p['back_partial_scale'])}, {fmt(p['bevel_width'])}, {fmt(p['is_leg_round'])})\n"
            )
            f.write("parts.extend(back_decors)\n")
            f.write("for leg in legs:\n")
            f.write(
                f"    solidify_limb(leg, 2, {fmt(p['leg_thickness'])}, {fmt(p['is_leg_round'])}, {fmt(p['bevel_width'])})\n"
            )
            f.write("for back in backs:\n")
            f.write(
                f"    solidify_limb(back, 2, {fmt(p['back_thickness'])}, {fmt(p['is_leg_round'])}, {fmt(p['bevel_width'])})\n"
            )
            f.write("finalize_parts(parts)\n")

        return output_path

    def _get_params_dict(self) -> Dict[str, Any]:
        """Get all parameters as a dictionary."""
        return {
            "width": float(self.width),
            "size": float(self.size),
            "thickness": float(self.thickness),
            "bevel_width": float(self.bevel_width),
            "seat_back": float(self.seat_back),
            "seat_mid": float(self.seat_mid),
            "seat_mid_x": float(self.seat_mid_x),
            "seat_mid_z": float(self.seat_mid_z),
            "seat_front": float(self.seat_front),
            "is_seat_round": bool(self.is_seat_round),
            "is_seat_subsurf": bool(self.is_seat_subsurf),
            "leg_thickness": float(self.leg_thickness),
            "limb_profile": float(self.limb_profile),
            "leg_height": float(self.leg_height),
            "is_leg_round": bool(self.is_leg_round),
            "leg_type": str(self.leg_type),
            "leg_x_offset": float(self.leg_x_offset),
            "leg_y_offset": (float(self.leg_y_offset[0]), float(self.leg_y_offset[1])),
            "back_height": float(self.back_height),
            "back_thickness": float(self.back_thickness),
            "back_x_offset": float(self.back_x_offset),
            "back_y_offset": float(self.back_y_offset),
            "back_type": str(self.back_type),
            "back_profile": [(float(p[0]), float(p[1])) for p in self.back_profile],
            "back_vertical_cuts": int(self.back_vertical_cuts),
            "back_partial_scale": float(self.back_partial_scale),
            "has_leg_x_bar": bool(self.has_leg_x_bar),
            "has_leg_y_bar": bool(self.has_leg_y_bar),
            "leg_offset_bar": (
                float(self.leg_offset_bar[0]),
                float(self.leg_offset_bar[1]),
            ),
            "has_arm": bool(self.has_arm),
            "arm_thickness": float(self.arm_thickness),
            "arm_height": float(self.arm_height),
            "arm_y": float(self.arm_y),
            "arm_z": float(self.arm_z),
            "arm_mid": [float(x) for x in self.arm_mid],
            "arm_profile": [float(x) for x in self.arm_profile],
        }

    def export_parametric_script(self, output_path: str) -> str:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("import bpy\n")
            f.write("import numpy as np\n")
            f.write(
                "from infinigen.assets.utils.decorate import write_attribute, write_co, read_co, read_edge_center, read_edge_direction, remove_edges, remove_vertices, select_edges, solidify, subsurf\n"
            )
            f.write(
                "from infinigen.assets.utils.draw import bezier_curve, align_bezier\n"
            )
            f.write(
                "from infinigen.assets.utils.object import join_objects, new_bbox\n"
            )
            f.write("from infinigen.assets.utils.nodegroup import geo_radius\n")
            f.write("from infinigen.core.util import blender as butil\n\n")
            # Parameter block (captured from this factory instance)
            params = {
                "width": float(self.width),
                "size": float(self.size),
                "thickness": float(self.thickness),
                "bevel_width": float(self.bevel_width),
                "seat_back": float(self.seat_back),
                "seat_mid": float(self.seat_mid),
                "seat_mid_x": float(self.seat_mid_x),
                "seat_mid_z": float(self.seat_mid_z),
                "seat_front": float(self.seat_front),
                "is_seat_round": bool(self.is_seat_round),
                "is_seat_subsurf": bool(self.is_seat_subsurf),
                "leg_thickness": float(self.leg_thickness),
                "limb_profile": float(self.limb_profile),
                "leg_height": float(self.leg_height),
                "back_height": float(self.back_height),
                "is_leg_round": bool(self.is_leg_round),
                "leg_x_offset": float(self.leg_x_offset),
                "back_x_offset": float(self.back_x_offset),
                "back_y_offset": float(self.back_y_offset),
                "has_leg_x_bar": bool(self.has_leg_x_bar),
                "has_leg_y_bar": bool(self.has_leg_y_bar),
                "has_arm": bool(self.has_arm),
                "arm_thickness": float(self.arm_thickness),
                "arm_y": float(self.arm_y),
                "arm_z": float(self.arm_z),
                "back_thickness": float(self.back_thickness),
                "back_vertical_cuts": int(self.back_vertical_cuts),
                "back_partial_scale": float(self.back_partial_scale),
            }
            # leg_y_offset and leg_offset_bar can be tuples
            f.write("# Parameters\n")
            for k, v in params.items():
                if isinstance(v, bool):
                    f.write(f"{k} = {str(v)}\n")
                elif isinstance(v, (int, float)):
                    f.write(f"{k} = {v}\n")
                else:
                    f.write(f"{k} = {repr(v)}\n")
            f.write(
                f"leg_y_offset = ({float(self.leg_y_offset[0])}, {float(self.leg_y_offset[1])})\n"
            )
            f.write(
                f"leg_offset_bar = ({float(self.leg_offset_bar[0])}, {float(self.leg_offset_bar[1])})\n\n"
            )
            # Begin script body reconstructing key arrays before making low-level calls.
            f.write("objs = []\n\n")
            # Seat
            f.write("# Seat\n")
            f.write(
                "x_anchors = np.array([0, 0.1, 1, seat_mid_x, seat_back, 0]) * width / 2\n"
            )
            f.write(
                "y_anchors = np.array([-seat_front, -seat_front, -1, -seat_mid, 0, 0]) * size\n"
            )
            f.write("z_anchors = np.array([0, 0, 0, seat_mid_z, 0, 0]) * thickness\n")
            f.write("vector_locations = [4] if is_seat_round else [2, 4]\n")
            f.write(
                "obj = bezier_curve((x_anchors, y_anchors, z_anchors), vector_locations)\n"
            )
            f.write('obj.name = "obj_1"\nobjs.append(bpy.data.objects["obj_1"])\n')
            f.write(
                "butil.modify_mesh(bpy.data.objects['obj_1'], 'WELD', merge_threshold=0.001)\n"
            )
            f.write("butil.modify_mesh(bpy.data.objects['obj_1'], 'MIRROR')\n")
            f.write('with butil.ViewportMode(bpy.data.objects["obj_1"], "EDIT"):\n')
            f.write('    bpy.ops.mesh.select_all(action="SELECT")\n')
            f.write("    bpy.ops.mesh.fill_grid(use_interp_simple=True)\n")
            f.write(
                "butil.modify_mesh(bpy.data.objects['obj_1'], 'SOLIDIFY', thickness=thickness, offset=0)\n"
            )
            f.write("subsurf(bpy.data.objects['obj_1'], 1, not is_seat_subsurf)\n")
            f.write(
                "butil.modify_mesh(bpy.data.objects['obj_1'], 'SUBSURF', levels=1, render_levels=1, subdivision_type='CATMULL_CLARK')\n"
            )
            f.write(
                "butil.modify_mesh(bpy.data.objects['obj_1'], 'BEVEL', width=bevel_width, segments=8)\n\n"
            )

            # Legs
            f.write("# Legs\n")
            f.write(
                "leg_starts = np.array([[-seat_back, 0, 0], [-1, -1, 0], [1, -1, 0], [seat_back, 0, 0]]) * np.array([[width/2, size, 0]])\n"
            )
            f.write("leg_ends = leg_starts.copy()\n")
            f.write("leg_ends[[0,1],0] -= leg_x_offset\n")
            f.write("leg_ends[[2,3],0] += leg_x_offset\n")
            f.write("leg_ends[[0,3],1] += leg_y_offset[0]\n")
            f.write("leg_ends[[1,2],1] -= leg_y_offset[1]\n")
            f.write("leg_ends[:,2] = -leg_height\n")
            f.write("def limb_axes_scale(leg_type, limb_profile):\n")
            f.write("    if leg_type == 'up-curved':\n")
            f.write("        return [(0,0,1), None], [limb_profile, 1]\n")
            f.write("    if leg_type == 'down-curved':\n")
            f.write("        return [None, (0,0,1)], [1, limb_profile]\n")
            f.write("    return None, None\n")
            f.write(
                "axes, scale = limb_axes_scale('up-curved' if False else 'down-curved' if False else 'straight', limb_profile)\n"
            )
            f.write("# Emit four limbs\n")
            f.write("objs_idx = 2\n")
            f.write("for i in range(4):\n")
            f.write("    start = leg_starts[i]\n")
            f.write("    end = leg_ends[i]\n")
            f.write("    obj = align_bezier(np.stack([start, end], -1), axes, scale)\n")
            f.write("    sx = 1 if start[0] < 0 else -1\n")
            f.write("    sy = 1 if start[1] < -size/2 else -1\n")
            f.write('    obj.name = f"obj_{objs_idx}"\n')
            f.write("    objs.append(bpy.data.objects[obj.name])\n")
            f.write(
                "    butil.modify_mesh(bpy.data.objects[obj.name], 'WELD', merge_threshold=0.001)\n"
            )
            f.write(
                "    bpy.data.objects[obj.name].location = np.array([sx, sy, 0]) * leg_thickness / 2\n"
            )
            f.write("    butil.apply_transform(bpy.data.objects[obj.name], True)\n")
            f.write("    if is_leg_round:\n")
            f.write("        solidify(bpy.data.objects[obj.name], 2, leg_thickness)\n")
            f.write(
                "        butil.modify_mesh(bpy.data.objects[obj.name], 'BEVEL', width=bevel_width, segments=8)\n"
            )
            f.write("    else:\n")
            f.write("        from infinigen.core import surface\n")
            f.write(
                "        surface.add_geomod(bpy.data.objects[obj.name], geo_radius, apply=True, input_args=[leg_thickness/2, 32], input_kwargs={})\n"
            )
            f.write("    objs_idx += 1\n\n")

            # Backs\n"
            f.write("# Backs\n")
            f.write(
                "back_starts = np.array([[-seat_back, 0, 0], [seat_back, 0, 0]]) * width / 2\n"
            )
            f.write("back_ends = back_starts.copy()\n")
            f.write("back_ends[:,0] += np.array([back_x_offset, -back_x_offset])\n")
            f.write("back_ends[:,1] = back_y_offset\n")
            f.write("back_ends[:,2] = back_height\n")
            f.write("for i in range(2):\n")
            f.write(
                "    obj = align_bezier(np.stack([back_starts[i], back_ends[i]], -1), None, None)\n"
            )
            f.write('    obj.name = f"obj_{objs_idx}"\n')
            f.write("    objs.append(bpy.data.objects[obj.name])\n")
            f.write(
                "    butil.modify_mesh(bpy.data.objects[obj.name], 'WELD', merge_threshold=0.001)\n"
            )
            f.write("    # solidify backs\n")
            f.write("    if is_leg_round:\n")
            f.write("        solidify(bpy.data.objects[obj.name], 2, back_thickness)\n")
            f.write("    else:\n")
            f.write("        from infinigen.core import surface\n")
            f.write(
                "        surface.add_geomod(bpy.data.objects[obj.name], geo_radius, apply=True, input_args=[back_thickness/2, 32], input_kwargs={})\n"
            )
            f.write("    objs_idx += 1\n\n")

            # Final rotation/apply transforms per-part (equivalent to factory's finalization)\n"
            f.write("# Final rotation/apply transforms\n")
            f.write("for o in objs:\n")
            f.write(
                "    bpy.data.objects[o.name].rotation_euler.z += 1.5707963267948966\n"
            )
            f.write("    butil.apply_transform(bpy.data.objects[o.name])\n")
            f.write("\n")
        return output_path
