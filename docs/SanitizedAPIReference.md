## Sanitized API Reference (Chair_sanitized imports)

This section documents the low-level helper functions used by sanitized scripts (e.g., `outputs/chairs/variant_041/Chair_sanitized.py`). Each entry lists purpose, inputs, outputs/return, side-effects, and notes for replay fidelity.

### Module: infinigen.assets.utils.draw

- bezier_curve(anchors, vector_locations=())
  - Purpose: Create a mesh from a 3D Bezier curve profile (seat outline, rails, etc.).
  - Inputs:
    - anchors: tuple of three numpy arrays (x, y, z) defining control points in object space.
    - vector_locations: list of indices where the curve uses vector handles (sharp transitions); empty means automatic.
  - Returns: bpy.types.Object (MESH) created and linked to the active collection.
  - Side-effects: Links new object to scene; object name assigned afterward by script.
  - Notes: Often followed by weld/mirror/solidify/subsurf and edit-mode grid fill.

- align_bezier(points, axes=None, scale=None)
  - Purpose: Generate a curved limb/back element by aligning a Bezier edge path between start/end points, with optional axis/scale profiles.
  - Inputs:
    - points: numpy array of shape (3, N) or equivalent describing positions along the limb.
    - axes: list/array of direction vectors or None to infer.
    - scale: list/array of profile scales along the path, or None.
  - Returns: bpy.types.Object (MESH), linked to the scene.
  - Side-effects: Links new object. Scripts often set `obj.location` then apply transform.
  - Notes: Common for legs/backs/arms; typically followed by weld and radius/solidify.

### Module: infinigen.assets.utils.decorate

- write_attribute(obj, value, name, domain="POINT", data_type="FLOAT")
  - Purpose: Write/ensure a mesh attribute with a constant value across a given domain (e.g., mark faces as "limb" or "panel").
  - Inputs:
    - obj: target MESH object.
    - value: numeric or integer constant to write.
    - name: attribute name (string).
    - domain: one of "POINT", "EDGE", "FACE".
    - data_type: Blender attribute type (e.g., "FLOAT", "INT").
  - Returns: None.
  - Side-effects: Ensures attribute exists on `obj.data.attributes` and sets values.
  - Notes: Sanitized scripts may omit semantic attributes if not required for geometry reproduction.

- write_co(obj, arr)
  - Purpose: Overwrite vertex coordinates with the provided array.
  - Inputs: obj (MESH), arr (numpy array of shape (V, 3)).
  - Returns: obj.
  - Side-effects: Modifies mesh vertex positions in-place.

- remove_edges(obj, idxs)
  - Purpose: Remove edges by indices (list of ints).
  - Inputs: obj (MESH), idxs (iterable of edge indices).
  - Returns: obj.
  - Side-effects: Deletes edges from mesh; may remove faces as a consequence.

- remove_vertices(obj, idxs)
  - Purpose: Remove vertices by indices (list of ints) and associated elements.
  - Inputs: obj (MESH), idxs (iterable of vertex indices).
  - Returns: obj.
  - Side-effects: Topology changes; indices will be re-numbered.

- select_edges(obj, idxs)
  - Purpose: Select edges by indices in EDIT mode.
  - Inputs: obj (MESH), idxs (iterable of edge indices or boolean mask).
  - Returns: obj.
  - Side-effects: Requires EDIT mode; selection state is modified.

- subsurf(obj, levels, simple=False)
  - Purpose: Add/adjust a Subdivision Surface modifier.
  - Inputs: obj (MESH), levels (int), simple (bool for Simple subdivision).
  - Returns: obj.
  - Side-effects: Adds/updates a SUBSURF modifier; may or may not apply immediately.

- solidify(obj, axis, thickness)
  - Purpose: Give thickness or radius to limbs/panels.
  - Inputs: obj (MESH), axis (int or semantic), thickness (float).
  - Returns: obj.
  - Side-effects: Depending on limb style, either uses a custom nodegroup (radius) or adds SOLIDIFY and BEVEL.

### Module: infinigen.assets.utils.object

- join_objects(objs)
  - Purpose: Join multiple mesh objects into the first active object.
  - Inputs: list of bpy.types.Object (MESH).
  - Returns: The active/merged object (MESH).
  - Side-effects: Selection/active state; removes other objects by merging data.
  - Notes: Sanitized scripts generally avoid global final join; may join specific temporary parts during back decor creation.

- new_bbox(xmin, xmax, ymin, ymax, zmin, zmax)
  - Purpose: Create a bounding-box mesh primitive.
  - Inputs: 6 floats defining the extents in object space.
  - Returns: bpy.types.Object (MESH) for the box, linked to the scene.

### Module: infinigen.assets.utils.nodegroup

- geo_radius
  - Purpose: Nodegroup function/reference used to add a thickness/radius via Geometry Nodes.
  - Usage: Passed to `surface.add_geomod(obj, geo_radius, ...)`.
  - Notes: In sanitized scripts, only `geo_radius` is referenced (other closures are not serializable and are skipped).

### Module: infinigen.core.util.blender as butil

- modify_mesh(obj, type, apply=True, name=None, return_mod=False, ng_inputs=None, show_viewport=None, **kwargs)
  - Purpose: Add a modifier of `type` with given parameters; optionally apply it.
  - Inputs:
    - obj: MESH object.
    - type: string (e.g., 'WELD', 'MIRROR', 'SOLIDIFY', 'BEVEL', 'SUBSURF').
    - kwargs: modifier properties (e.g., merge_threshold, levels, width, segments, offset).
  - Returns: obj (or obj, mod if `return_mod=True` and not applied).
  - Side-effects: Creates and optionally applies a Blender modifier in correct order.

- apply_transform(obj, loc=False, rot=True, scale=True)
  - Purpose: Apply object transforms (location, rotation, scale).
  - Inputs: obj (Object), flags booleans.
  - Returns: None.
  - Side-effects: Bakes transforms into mesh data.

- apply_modifiers(obj, mod=None, quiet=True)
  - Purpose: Apply one or multiple modifiers.
  - Inputs: obj (MESH), mod (name/obj/list or None for all).
  - Returns: None (or object depending on mode).
  - Side-effects: Applies modifiers in order; may remove attributes/material slots.

- deep_clone_obj(obj) [from infinigen.core.util.blender]
  - Purpose: Duplicate object and its mesh data, linking clone to scene.
  - Inputs: obj (Object).
  - Returns: cloned bpy.types.Object.
  - Side-effects: New object/memory allocation.

### Module: infinigen.core.surface as surface

- add_geomod(obj, nodegroup, apply=False, input_args=None, input_kwargs=None)
  - Purpose: Add a Geometry Nodes modifier based on a nodegroup (e.g., `geo_radius`) and optionally apply.
  - Inputs: obj (MESH), nodegroup (callable/ref), apply (bool), input_args (list), input_kwargs (dict).
  - Returns: obj (or modifier depending on usage).
  - Side-effects: Adds nodes modifier; may be applied (baked) to geometry.
  - Notes: Sanitized scripts only use resolvable nodegroups like `geo_radius`.

## Replay and Context Notes

- Many operations require OBJECT vs EDIT mode and correct selection/active object. Sanitized scripts explicitly open EDIT blocks with `ViewportMode` and issue the ops in-order.
- All parameters are constants; scripts rename objects in creation order (`obj_1..obj_N`) and reference them by stable names.
- Dematerialized outputs: sanitized scripts do not assign materials; geometry/attributes/modifiers are sufficient to reproduce shape.

### Sanitized Script API Reference

This reference documents the low-level helper functions imported at the top of sanitized scripts (e.g., `Chair_sanitized.py`). These are the only calls that appear in sanitized outputs and are considered stable for reconstruction and RAG.

Notes
- All numeric parameters in sanitized scripts are concrete constants (no symbolic values).
- Object arguments are Blender `bpy.types.Object` references; in sanitized code they appear as `bpy.data.objects["obj_k"]`.
- Unless specified, functions mutate objects in-place and return either the modified object or `None`.

Imports covered
- `import bpy`
- `import numpy as np`
- `from infinigen.assets.utils.decorate import write_attribute, write_co, remove_edges, remove_vertices, select_edges, solidify, subsurf`
- `from infinigen.assets.utils.draw import bezier_curve, align_bezier`
- `from infinigen.assets.utils.object import join_objects, new_bbox`
- `from infinigen.assets.utils.nodegroup import geo_radius`
- `from infinigen.core.util import blender as butil` (primarily `modify_mesh`, `apply_transform`)
- `from infinigen.core import surface` (primarily `add_geomod`)
- `from infinigen.core.util.blender import deep_clone_obj`

Function reference

1) draw.bezier_curve
```
def bezier_curve(anchors, vector_locations=(), resolution=None, to_mesh=True):
    n = [len(r) for r in anchors if isinstance(r, Sized)][0]
    anchors = np.array(
        [
            np.array(r, dtype=float) if isinstance(r, Sized) else np.full(n, r)
            for r in anchors
        ]
    )
    bpy.ops.curve.primitive_bezier_curve_add(location=(0, 0, 0))
    obj = bpy.context.active_object

    if n > 2:
        with butil.ViewportMode(obj, "EDIT"):
            bpy.ops.curve.subdivide(number_cuts=n - 2)
    points = obj.data.splines[0].bezier_points
    for i in range(n):
        points[i].co = anchors[:, i]
    for i in range(n):
        if i in vector_locations:
            points[i].handle_left_type = "VECTOR"
            points[i].handle_right_type = "VECTOR"
        else:
            points[i].handle_left_type = "AUTO"
            points[i].handle_right_type = "AUTO"
    obj.data.splines[0].resolution_u = resolution if resolution is not None else 12
    if not to_mesh:
        return obj
    return curve2mesh(obj)
```


2) draw.align_bezier
```
def align_bezier(
    anchors, axes=None, scale=None, vector_locations=(), resolution=None, to_mesh=True
):
    obj = bezier_curve(anchors, vector_locations, resolution, False)
    points = obj.data.splines[0].bezier_points
    if scale is None:
        scale = np.ones(2 * len(points) - 2)
    if axes is None:
        axes = [None] * len(points)
    scale = [1, *scale, 1]
    for i, p in enumerate(points):
        a = axes[i]
        if a is None:
            continue
        a = np.array(a)
        p.handle_left_type = "FREE"
        p.handle_right_type = "FREE"
        proj_left = np.array(p.handle_left - p.co) @ a * a
        p.handle_left = (
            np.array(p.co)
            + proj_left
            / np.linalg.norm(proj_left)
            * np.linalg.norm(p.handle_left - p.co)
            * scale[2 * i]
        )
        proj_right = np.array(p.handle_right - p.co) @ a * a
        p.handle_right = (
            np.array(p.co)
            + proj_right
            / np.linalg.norm(proj_right)
            * np.linalg.norm(p.handle_right - p.co)
            * scale[2 * i + 1]
        )
    if not to_mesh:
        return obj
    return curve2mesh(obj)
```

3) decorate.subsurf
```
def subsurf(obj, levels, simple=False):
    if levels > 0:
        butil.modify_mesh(
            obj,
            "SUBSURF",
            levels=levels,
            render_levels=levels,
            subdivision_type="SIMPLE" if simple else "CATMULL_CLARK",
        )

```

4) decorate.solidify
```
def solidify(obj, axis, thickness):
    axes = [0, 1, 2]
    axes.remove(axis)
    u = np.zeros(3)
    u[axes[0]] = thickness
    v = np.zeros(3)
    v[axes[1]] = thickness
    butil.select_none()
    with butil.ViewportMode(obj, "EDIT"):
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.mesh.extrude_edges_move(TRANSFORM_OT_translate={"value": u})
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.mesh.extrude_region_move(TRANSFORM_OT_translate={"value": v})
    obj.location = -(u + v) / 2
    butil.apply_transform(obj, True)
    return obj

```

5) decorate.write_co
```
def write_co(obj, arr):
    try:
        obj.data.vertices.foreach_set("co", arr.reshape(-1))
    except RuntimeError as e:
        raise RuntimeError(
            f"Failed to set vertices.co on {obj.name=}. Object has {len(obj.data.vertices)} verts, "
            f"{arr.shape=}"
        ) from e

```

6) decorate.write_attribute
```
def write_attribute(obj, fn, name, domain="POINT", data_type="FLOAT"):
    def geo_attribute(nw: NodeWrangler):
        geometry = nw.new_node(
            Nodes.GroupInput, expose_input=[("NodeSocketGeometry", "Geometry", None)]
        )
        attr = surface.eval_argument(nw, fn, position=nw.new_node(Nodes.InputPosition))
        geometry = nw.new_node(
            Nodes.StoreNamedAttribute,
            input_kwargs={"Geometry": geometry, "Name": name, "Value": attr},
            attrs={"domain": domain, "data_type": data_type},
        )
        nw.new_node(Nodes.GroupOutput, input_kwargs={"Geometry": geometry})

    surface.add_geomod(obj, geo_attribute, apply=True)

```

7) decorate.remove_vertices
```
def remove_vertices(obj, to_delete):
    if not isinstance(to_delete, Iterable):
        x, y, z = read_co(obj).T
        to_delete = to_delete(x, y, z)
    to_delete = np.nonzero(to_delete)[0]
    with butil.ViewportMode(obj, "EDIT"):
        bm = bmesh.from_edit_mesh(obj.data)
        bm.verts.ensure_lookup_table()
        geom = [bm.verts[_] for _ in to_delete]
        bmesh.ops.delete(bm, geom=geom)
        bmesh.update_edit_mesh(obj.data)
    return obj
```

8) decorate.remove_edges
```
def remove_edges(obj, to_delete):
    if not isinstance(to_delete, Iterable):
        x, y, z = read_edge_center(obj).T
        to_delete = to_delete(x, y, z)
    to_delete = np.nonzero(to_delete)[0]
    with butil.ViewportMode(obj, "EDIT"):
        bm = bmesh.from_edit_mesh(obj.data)
        bm.edges.ensure_lookup_table()
        geom = [bm.edges[_] for _ in to_delete]
        bmesh.ops.delete(bm, geom=geom, context="EDGES_FACES")
        bmesh.update_edit_mesh(obj.data)
    return obj
```

9) decorate.select_edges
```
def select_edges(obj, to_select):
    if not isinstance(to_select, Iterable):
        x, y, z = read_edge_center(obj).T
        to_select = to_select(x, y, z)
    to_select = np.nonzero(to_select)[0]
    with butil.ViewportMode(obj, "EDIT"):
        bpy.ops.mesh.select_mode(type="EDGE")
        bpy.ops.mesh.select_all(action="DESELECT")
        bm = bmesh.from_edit_mesh(obj.data)
        bm.edges.ensure_lookup_table()
        for i in to_select:
            bm.edges[i].select_set(True)
        bm.select_flush(False)
        bmesh.update_edit_mesh(obj.data)
    return obj
```

10) object.join_objects
```
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
```

11) object.new_bbox
```
def new_bbox(x, x_, y, y_, z, z_):
    obj = new_cube()
    obj.location = (x + x_) / 2, (y + y_) / 2, (z + z_) / 2
    obj.scale = (x_ - x) / 2, (y_ - y) / 2, (z_ - z) / 2
    butil.apply_transform(obj, True)
    return obj

```

12) nodegroup.geo_radius
```
def geo_radius(
    nw: NodeWrangler,
    radius,
    resolution=6,
    merge_distance=0.004,
    rotation=0,
    to_align_tilt=True,
    align_tilt_axis=(0, 0, 1),
):
    skeleton = nw.new_node(
        Nodes.GroupInput, expose_input=[("NodeSocketGeometry", "Geometry", None)]
    )
    radius = surface.eval_argument(nw, radius)
    curve = nw.new_node(Nodes.MeshToCurve, [skeleton])
    if to_align_tilt:
        curve = align_tilt(nw, curve, align_tilt_axis)
    skeleton = nw.new_node(
        Nodes.SetCurveRadius, input_kwargs={"Curve": curve, "Radius": radius}
    )
    geometry = nw.curve2mesh(
        skeleton,
        nw.new_node(
            Nodes.Transform,
            [nw.new_node(Nodes.CurveCircle, input_kwargs={"Resolution": resolution})],
            input_kwargs={"Rotation": [0, 0, rotation]},
        ),
    )
    if merge_distance > 0:
        geometry = nw.new_node(Nodes.MergeByDistance, [geometry, None, merge_distance])
    nw.new_node(Nodes.GroupOutput, input_kwargs={"Geometry": geometry})

```

13) surface.add_geomod
```
def add_geomod(
    objs,
    geo_func,
    name=None,
    apply=False,
    reuse=False,
    input_args=None,
    input_kwargs=None,
    attributes=None,
    show_viewport=True,
    selection=None,
    domains=None,
    input_attributes=None,
):
    if input_args is None:
        input_args = []
    if input_kwargs is None:
        input_kwargs = {}
    if attributes is None:
        attributes = []
    if domains is None:
        domains = ["POINT"] * len(attributes)
    if input_attributes is None:
        input_attributes = [None] * 128

    if name is None:
        name = geo_func.__name__
    if not isinstance(objs, list):
        objs = [objs]
    elif len(objs) == 0:
        return None

    if selection is not None:
        input_kwargs["selection"] = selection

    ng = None
    for obj in objs:
        mod = obj.modifiers.new(name=name, type="NODES")
        mod.show_viewport = False

        if mod is None:
            raise ValueError(
                f"Attempted to surface.add_geomod({obj=}), yet created modifier was None. "
                f"Check that {obj.type=} supports geo modifiers"
            )

        mod.show_viewport = show_viewport
        if ng is None:  # Create a unique node_group for the first one only
            if reuse and name in bpy.data.node_groups:
                mod.node_group = bpy.data.node_groups[name]
            else:
                # print("input_kwargs", input_kwargs, geo_func.__name__)
                if mod.node_group is None:
                    group = geometry_node_group_empty_new()
                    mod.node_group = group
                nw = NodeWrangler(mod)
                geo_func(nw, *input_args, **input_kwargs)
            ng = mod.node_group
            ng.name = name
        else:
            mod.node_group = ng

        non_geometries = [
            o
            for o in ng_outputs(mod.node_group).values()
            if o.socket_type != "NodeSocketGeometry"
        ]
        if len(non_geometries) != len(attributes):
            raise Exception(
                f"has {len(non_geometries)} identifiers, but {len(attributes)} attributes. Specifically, "
                f"{non_geometries=} and {attributes=}"
            )
        for o, att_name in zip(non_geometries, attributes):
            # attributes are a 1-indexed list, and Geometry is the first element, so we start from 2
            # while f'Output_{i}_attribute_name' not in
            mod[o.identifier + "_attribute_name"] = att_name
        for o, domain in zip(non_geometries, domains):
            o.attribute_domain = domain

        inputs = ng_inputs(mod.node_group)
        if not any(att_name is None for att_name in input_attributes):
            raise Exception("None should be provided for Geometry inputs.")
        for i, att_name in zip(inputs.values(), input_attributes):
            o = i.identifier
            if att_name is not None:
                mod[f"{o}_use_attribute"] = True
                mod[f"{o}_attribute_name"] = att_name

    if apply:
        for obj in objs:
            butil.apply_modifiers(obj, name)
        return None

    return mod

```

14) butil.modify_mesh
- Purpose: Create/configure/apply a standard Blender modifier on an object (e.g., `WELD`, `MIRROR`, `SOLIDIFY`, `SUBSURF`, `BEVEL`).
- Signature: `butil.modify_mesh(obj: bpy.types.Object, type: str, **kwargs) -> bpy.types.Object`
- Args: `type` one of Blender modifier types; keyword args are modifier settings, emitted as constants.
- Returns: The object.

15) butil.apply_transform
- Purpose: Apply object transforms (location/rotation/scale) to bake geometry.
- Signature: `butil.apply_transform(obj: bpy.types.Object, loc: bool=False, rot: bool=True, scale: bool=True) -> None`
- Sanitized usage: Typically `rot=True, scale=True` (and sometimes `loc=True`), emitted explicitly.

16) deep_clone_obj
```
def deep_clone_obj(obj, keep_modifiers=False, keep_materials=False):
    new_obj = obj.copy()
    new_obj.data = obj.data.copy()
    if not keep_modifiers:
        for mod in new_obj.modifiers:
            new_obj.modifiers.remove(mod)
    if not keep_materials:
        while len(new_obj.data.materials) > 0:
            new_obj.data.materials.pop()
    bpy.context.collection.objects.link(new_obj)
    return new_obj
```

Examples (schematic)
```python
# Create a seat surface from anchors and fill
obj = bezier_curve((np.array([...]), np.array([...]), np.array([...])), [4])
butil.modify_mesh(obj, 'WELD', merge_threshold=0.001)
with butil.ViewportMode(obj, 'EDIT'):
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.mesh.fill_grid(use_interp_simple=True)

# Round a limb with geometry nodes
surface.add_geomod(obj, geo_radius, apply=True, input_args=[0.02, 32], input_kwargs={})

# Apply transforms
obj.rotation_euler.z += 1.5707963267948966
butil.apply_transform(obj)
```


