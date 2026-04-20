# Copyright (C) 2023, Princeton University.
# This source code is licensed under the BSD 3-Clause license found in the LICENSE file in the root directory
# of this source tree.

# Authors: Lingjie Mei


import bpy
import numpy as np
import trimesh
from mathutils import Vector

import infinigen.core.util.blender as butil
from infinigen.assets.utils.decorate import read_co
from infinigen.core.util.blender import select_none


def center(obj):
    return (Vector(obj.bound_box[0]) + Vector(obj.bound_box[-2])) * obj.scale / 2.0


def origin2lowest(obj, vertical=False, centered=False, approximate=False):
    co = read_co(obj)
    if not len(co):
        return
    i = np.argmin(co[:, -1])
    if approximate:
        indices = np.argsort(co[:, -1])
        obj.location = -np.mean(co[indices[: len(co) // 10]], 0)
        obj.location[-1] = -co[i, -1]
    elif centered:
        obj.location = -center(obj)
        obj.location[-1] = -co[i, -1]
    elif vertical:
        obj.location[-1] = -co[i, -1]
    else:
        obj.location = -co[i]
    butil.apply_transform(obj, loc=True)


def origin2highest(obj):
    co = read_co(obj)
    i = np.argmax(co[:, -1])
    obj.location = -co[i]
    butil.apply_transform(obj, loc=True)


def origin2leftmost(obj):
    co = read_co(obj)
    i = np.argmin(co[:, 0])
    obj.location = -co[i]
    butil.apply_transform(obj, loc=True)


def data2mesh(vertices=(), edges=(), faces=(), name=""):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, edges, faces)
    mesh.update()
    return mesh


def mesh2obj(mesh):
    obj = bpy.data.objects.new(mesh.name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    return obj


def trimesh2obj(trimesh):
    obj = butil.object_from_trimesh(trimesh, "")
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    return obj


def obj2trimesh(obj):
    butil.modify_mesh(obj, "TRIANGULATE", min_vertices=3)
    vertices = read_co(obj)
    arr = np.zeros(len(obj.data.polygons) * 3)
    obj.data.polygons.foreach_get("vertices", arr)
    faces = arr.reshape(-1, 3)
    return trimesh.Trimesh(vertices, faces)


def new_cube(**kwargs):
    kwargs["location"] = kwargs.get("location", (0, 0, 0))
    bpy.ops.mesh.primitive_cube_add(**kwargs)
    return bpy.context.active_object


def new_bbox(x, x_, y, y_, z, z_):
    obj = new_cube()
    obj.location = (x + x_) / 2, (y + y_) / 2, (z + z_) / 2
    obj.scale = (x_ - x) / 2, (y_ - y) / 2, (z_ - z) / 2
    butil.apply_transform(obj, True)
    return obj


# --------------------------------------------------------------------------- #
# Axis-aligned non-cuboid primitives (sit alongside ``new_bbox`` in the DSL)
# --------------------------------------------------------------------------- #

def _resolve_prism_axes(
    x0, y0, z0, x1, y1, z1, rise_x, rise_y, rise_z, fn_name,
):
    """Resolve (base_axis, rise_axis, thick_axis, base_sign, rise_sign) from
    the flat-arg form used by ``new_tri_prism`` / ``new_half_cylinder``.

    The base segment must be axis-aligned (exactly one of dx/dy/dz nonzero).
    The rise direction must also be axis-aligned (exactly one of rise_x/y/z
    nonzero) and perpendicular to the base axis. The remaining axis is the
    thickness axis, automatically derived.
    """
    base_delta = (x1 - x0, y1 - y0, z1 - z0)
    base_axes = [i for i, d in enumerate(base_delta) if abs(d) > 1e-9]
    if len(base_axes) != 1:
        raise ValueError(
            f"{fn_name}: base segment must be axis-aligned (exactly one of "
            f"dx/dy/dz nonzero); got delta={base_delta}"
        )
    base_axis = base_axes[0]
    base_sign = 1.0 if base_delta[base_axis] > 0 else -1.0

    rise = (rise_x, rise_y, rise_z)
    rise_axes = [i for i, d in enumerate(rise) if abs(d) > 1e-9]
    if len(rise_axes) != 1:
        raise ValueError(
            f"{fn_name}: rise direction must be axis-aligned with exactly one "
            f"nonzero component; got (rise_x={rise_x}, rise_y={rise_y}, "
            f"rise_z={rise_z})"
        )
    rise_axis = rise_axes[0]
    if rise_axis == base_axis:
        raise ValueError(
            f"{fn_name}: rise direction must be perpendicular to the base "
            f"axis (base axis is {'xyz'[base_axis]})"
        )
    rise_sign = 1.0 if rise[rise_axis] > 0 else -1.0

    thick_axis = ({0, 1, 2} - {base_axis, rise_axis}).pop()
    return base_axis, rise_axis, thick_axis, base_sign, rise_sign


def new_tri_prism(
    x0, y0, z0, x1, y1, z1,
    height, thickness,
    rise_x=0, rise_y=0, rise_z=1,
):
    """Create an isoceles triangular prism (gable / pediment / awning).

    The triangle's base segment is the axis-aligned line from ``(x0,y0,z0)``
    to ``(x1,y1,z1)``. The apex sits at the base midpoint offset by
    ``height`` along the ``(rise_x, rise_y, rise_z)`` direction (must be a
    single axis-aligned ±1 vector, perpendicular to the base axis). The 2D
    triangle is then extruded by ``thickness`` along the remaining (third)
    axis; sign of ``thickness`` picks the extrusion direction.

    Defaults (``rise_x=0, rise_y=0, rise_z=1``) place the apex straight up
    along +Z and extrude through the remaining axis (Y if base is along X).

    Returns the new mesh object linked to the active collection.
    """
    base_axis, rise_axis, thick_axis, _, rise_sign = _resolve_prism_axes(
        x0, y0, z0, x1, y1, z1, rise_x, rise_y, rise_z, "new_tri_prism",
    )
    if height <= 0:
        raise ValueError("new_tri_prism: height must be positive")

    base_mid = [(x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2]
    apex = list(base_mid)
    apex[rise_axis] += rise_sign * height

    front = [[x0, y0, z0], [x1, y1, z1], apex]
    back = []
    for v in front:
        v2 = list(v)
        v2[thick_axis] += thickness
        back.append(v2)
    verts = front + back  # 0..2 = front (b0, b1, apex), 3..5 = back

    faces = [
        (0, 1, 2),       # front triangle
        (3, 5, 4),       # back triangle
        (0, 3, 4, 1),    # base quad
        (1, 4, 5, 2),    # base_end -> apex slope quad
        (2, 5, 3, 0),    # apex -> base_start slope quad
    ]
    if thickness < 0:
        faces = [tuple(reversed(f)) for f in faces]

    mesh = data2mesh(verts, faces=faces, name="tri_prism")
    obj = mesh2obj(mesh)
    return obj


def new_half_cylinder(
    x0, y0, z0, x1, y1, z1,
    height, thickness,
    rise_x=0, rise_y=0, rise_z=1,
    segments=16,
):
    """Create a half-elliptical-cylinder prism (arched window head, half-round
    dormer, segmental arch, etc.).

    The flat diameter of the half-disk runs from ``(x0,y0,z0)`` to
    ``(x1,y1,z1)`` along an axis-aligned segment; the arc bulges along
    ``(rise_x, rise_y, rise_z)`` (single axis-aligned +/-1 vector,
    perpendicular to the base axis) by ``height``. The arc is parameterized
    as a half-ellipse with horizontal semi-axis ``base_length / 2`` and
    vertical semi-axis ``height``:

      - height == base_length / 2 -> true semicircle (perfect half-disk)
      - height <  base_length / 2 -> squat / segmental arch
      - height >  base_length / 2 -> tall / stilted ellipse

    The half-disk is then extruded by ``thickness`` along the remaining
    (third) axis; sign picks the direction.

    ``segments`` controls arc tessellation (number of edges spanning the
    half-ellipse). Default 16 is smooth at typical facade scale.

    Returns the new mesh object linked to the active collection.
    """
    base_axis, rise_axis, thick_axis, base_sign, rise_sign = _resolve_prism_axes(
        x0, y0, z0, x1, y1, z1, rise_x, rise_y, rise_z, "new_half_cylinder",
    )
    if height <= 0:
        raise ValueError("new_half_cylinder: height must be positive")
    if segments < 3:
        raise ValueError("new_half_cylinder: segments must be >= 3")
    base_length = abs((x1 - x0, y1 - y0, z1 - z0)[base_axis])
    radius = base_length / 2.0

    base_mid = [(x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2]

    # Front-face arc: theta=0 at base_end, theta=pi at base_start. n verts
    # (segments + 1) including both diameter endpoints. Half-ellipse with
    # horizontal semi-axis = radius, vertical semi-axis = height.
    n = segments + 1
    front = []
    for i in range(n):
        theta = (i / segments) * np.pi
        v = list(base_mid)
        v[base_axis] = base_mid[base_axis] + base_sign * radius * np.cos(theta)
        v[rise_axis] = base_mid[rise_axis] + rise_sign * height * np.sin(theta)
        front.append(v)

    back = []
    for v in front:
        v2 = list(v)
        v2[thick_axis] += thickness
        back.append(v2)
    verts = front + back  # 0..n-1 = front arc, n..2n-1 = back arc

    front_face = tuple(range(n))
    back_face = tuple(range(2 * n - 1, n - 1, -1))
    faces = [front_face, back_face]
    for i in range(n - 1):
        faces.append((i, i + 1, n + i + 1, n + i))
    # Bottom diameter face. Winding chosen so the outward normal points
    # opposite to the rise direction (i.e. away from the dome).
    faces.append((n - 1, 2 * n - 1, n, 0))

    if thickness < 0:
        faces = [tuple(reversed(f)) for f in faces]

    mesh = data2mesh(verts, faces=faces, name="half_cylinder")
    obj = mesh2obj(mesh)
    return obj


def new_bbox_2d(x, x_, y, y_, z=0):
    obj = new_plane()
    obj.location = (x + x_) / 2, (y + y_) / 2, z
    obj.scale = (x_ - x) / 2, (y_ - y) / 2, 1
    butil.apply_transform(obj, True)
    return obj


def new_icosphere(**kwargs):
    kwargs["location"] = kwargs.get("location", (0, 0, 0))
    bpy.ops.mesh.primitive_ico_sphere_add(**kwargs)
    return bpy.context.active_object


def new_circle(**kwargs):
    kwargs["location"] = kwargs.get("location", (1, 0, 0))
    bpy.ops.mesh.primitive_circle_add(**kwargs)
    obj = bpy.context.active_object
    butil.apply_transform(obj, loc=True)
    return obj


def new_base_circle(**kwargs):
    kwargs["location"] = kwargs.get("location", (0, 0, 0))
    bpy.ops.mesh.primitive_circle_add(**kwargs)
    obj = bpy.context.active_object
    return obj


def new_empty(**kwargs):
    kwargs["location"] = kwargs.get("location", (0, 0, 0))
    bpy.ops.object.empty_add(**kwargs)
    obj = bpy.context.active_object
    obj.scale = kwargs.get("scale", (1, 1, 1))
    return obj


def new_plane(**kwargs):
    kwargs["location"] = kwargs.get("location", (0, 0, 0))
    bpy.ops.mesh.primitive_plane_add(**kwargs)
    obj = bpy.context.active_object
    butil.apply_transform(obj, loc=True)
    return obj


def new_cylinder(**kwargs):
    kwargs["location"] = kwargs.get("location", (0, 0, 0.5))
    kwargs["depth"] = kwargs.get("depth", 1)
    bpy.ops.mesh.primitive_cylinder_add(**kwargs)
    obj = bpy.context.active_object
    butil.apply_transform(obj, loc=True)
    return obj


def new_base_cylinder(**kwargs):
    bpy.ops.mesh.primitive_cylinder_add(**kwargs)
    obj = bpy.context.active_object
    butil.apply_transform(obj, loc=True)
    return obj


def new_grid(**kwargs):
    kwargs["location"] = kwargs.get("location", (0, 0, 0))
    bpy.ops.mesh.primitive_grid_add(**kwargs)
    obj = bpy.context.active_object
    butil.apply_transform(obj, loc=True)
    return obj


def new_line(subdivisions=1, scale=1.0):
    vertices = np.stack(
        [
            np.linspace(0, scale, subdivisions + 1),
            np.zeros(subdivisions + 1),
            np.zeros(subdivisions + 1),
        ],
        -1,
    )
    edges = np.stack([np.arange(subdivisions), np.arange(1, subdivisions + 1)], -1)
    obj = mesh2obj(data2mesh(vertices, edges))
    return obj


def join_objects(obj):
    butil.select_none()
    if not isinstance(obj, list):
        obj = [obj]
    if len(obj) == 1:
        return obj[0]
    bpy.context.view_layer.objects.active = obj[0]
    butil.select_none()
    butil.select(obj)
    bpy.ops.object.join()
    obj = bpy.context.active_object
    obj.location = 0, 0, 0
    obj.rotation_euler = 0, 0, 0
    obj.scale = 1, 1, 1
    butil.select_none()
    return obj


def separate_loose(obj):
    select_none()
    objs = butil.split_object(obj)
    i = np.argmax([len(o.data.vertices) for o in objs])
    obj = objs[i]
    objs.remove(obj)
    butil.delete(objs)
    return obj
