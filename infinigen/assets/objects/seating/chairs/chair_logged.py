import bpy
import numpy as np
from numpy.random import uniform
from typing import Iterable, List, Optional, Tuple

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
            for obj in legs:
                co = deco.read_co(obj)
                locs.append(co[np.argmin(np.abs(co[:, -1] - z_height))])
            objs.append(
                self.solidify(bezier_curve(np.stack([locs[0], locs[3]], -1)), 0)
            )
            objs.append(
                self.solidify(bezier_curve(np.stack([locs[1], locs[2]], -1)), 0)
            )
        if self.has_leg_y_bar:
            z_height = -self.leg_height * uniform(*self.leg_offset_bar)
            locs = []
            for obj in legs:
                co = deco.read_co(obj)
                locs.append(co[np.argmin(np.abs(co[:, -1] - z_height))])
            objs.append(
                self.solidify(bezier_curve(np.stack([locs[0], locs[1]], -1)), 1)
            )
            objs.append(
                self.solidify(bezier_curve(np.stack([locs[2], locs[3]], -1)), 1)
            )
        for o in objs:
            write_attribute(o, 1, "limb", "FACE")
        return objs

    def make_back_decors(self, backs, finalize=True):
        obj = join_objects([deep_clone_obj(b) for b in backs])
        x, y, z = deco.read_co(obj).T
        x += np.where(x > 0, self.back_thickness / 2, -self.back_thickness / 2)
        write_co(obj, np.stack([x, y, z], -1))
        smoothness = uniform(0, 1)
        profile_shape_factor = uniform(0, 0.4)
        with butil.ViewportMode(obj, "EDIT"):
            SCRIPT_LOGGER.write(
                f'with butil.ViewportMode({SCRIPT_LOGGER.fmt_obj(obj)}, "EDIT"):'
            )
            SCRIPT_LOGGER.increase_indent()
            SCRIPT_LOGGER.write('bpy.ops.mesh.select_mode(type="EDGE")')
            bpy.ops.mesh.select_mode(type="EDGE")
            center = deco.read_edge_center(obj)
            for z_min, z_max in self.back_profile:
                select_edges(
                    obj,
                    (z_min * self.back_height <= center[:, -1])
                    & (center[:, -1] <= z_max * self.back_height),
                )
                SCRIPT_LOGGER.write(
                    f'bpy.ops.mesh.bridge_edge_loops(number_cuts={64}, interpolation="LINEAR", smoothness={smoothness:.9f}, profile_shape_factor={profile_shape_factor:.9f})'
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
            with butil.ViewportMode(other, "EDIT"):
                SCRIPT_LOGGER.write(
                    f'with butil.ViewportMode({SCRIPT_LOGGER.fmt_obj(other)}, "EDIT"):'
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
            remove_edges(other, np.abs(deco.read_edge_direction(other)[:, -1]) < 0.5)
            remove_vertices(other, lambda x, y, z: z < -self.thickness / 2)
            remove_vertices(
                other,
                lambda x, y, z: z
                > (self.back_profile[0][0] + self.back_profile[0][1])
                * self.back_height
                / 2,
            )
            parts.append(self.solidify(other, 2, self.back_thickness))
        elif self.back_type == "partial":
            co = deco.read_co(obj)
            co[:, 1] *= self.back_partial_scale
            write_co(obj, co)
        for p in parts:
            write_attribute(p, 1, "panel", "FACE")
        return parts

    def make_arms(self, base, backs):
        co = deco.read_co(base)
        end = co[np.argmin(co[:, 0] - (np.abs(co[:, 1] + self.arm_y) < 0.02))]
        end[0] += self.arm_thickness / 4
        end_ = end.copy()
        end_[0] = -end[0]
        objs = []
        co = deco.read_co(backs[0])
        start = co[np.argmin(co[:, 0] - (np.abs(co[:, -1] - self.arm_z) < 0.02))]
        start[0] -= self.arm_thickness / 4
        start_ = start.copy()
        start_[0] = -start[0]
        for start, end in zip([start, start_], [end, end_]):
            mid = np.array(
                [
                    end[0] + self.arm_mid[0] * (-1 if end[0] > 0 else 1),
                    end[1] + self.arm_mid[1],
                    start[2] + self.arm_mid[2],
                ]
            )
            obj = align_bezier(
                np.stack([start, mid, end], -1),
                np.array(
                    [
                        [end[0] - start[0], end[1] - start[1], 0],
                        [0, 1 / np.sqrt(2), 1 / np.sqrt(2)],
                        [0, 0, 1],
                    ]
                ),
                [1, *self.arm_profile, 1],
            )
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
                    dx = self.arm_thickness if end[0] < 0 else -self.arm_thickness
                    SCRIPT_LOGGER.write(
                        f"bpy.ops.mesh.extrude_edges_move(TRANSFORM_OT_translate={{'value': ({dx:.9f}, 0.000000000, 0.000000000)}})"
                    )
                    bpy.ops.mesh.extrude_edges_move(
                        TRANSFORM_OT_translate={
                            "value": (
                                (
                                    self.arm_thickness
                                    if end[0] < 0
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
                "from infinigen.assets.utils.decorate import write_attribute, write_co, remove_edges, remove_vertices, select_edges, solidify, subsurf\n"
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
