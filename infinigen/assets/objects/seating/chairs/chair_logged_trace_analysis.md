# Chair Logged Trace Analysis

## Purpose

This note summarizes the limitations of the current logged chair data
representation for reverse-engineering parametric structure.

It compares:

- the human-authored generator in `data/chair/chair_generator.py`
- the flattened logged output in `data/chair/variant_041/Chair_sanitized_annotated.py`

This is a data-analysis note only. It does not propose changes to roadmap item
`3.1a`, which should treat data generation as out of scope.

## Executive Summary

The current logged representation preserves exact execution behavior, but in
important places it is too close to the realized mesh state and too far from the
compact construction rules that generated that state.

The main failure mode is not simply "too many constants". The deeper issue is
that the logged script often records the **evaluated result of a hidden rule**
as a literal array, coordinate dump, or boolean mask. That makes the reverse
engineering target much harder:

> recover latent variables and derivation rules from an executed trace,
> not merely rename constants in a flattened script.

The logged trace is still useful because it exposes part order, helper-scale
operations, and exact geometry-preserving behavior. But it degrades several key
forms of generative structure into literal replay.

## What The Human Generator Encodes

The human-authored generator is genuinely low-dimensional and generative.

### 1. Root parameters are explicit

`ChairFactoryLogged.__init__()` samples a compact latent state:

- global size parameters such as `width`, `size`, `thickness`
- shape controls such as `seat_mid_x`, `seat_mid_z`, `seat_front`
- leg controls such as `leg_type`, `leg_height`, `leg_x_offset`, `leg_y_offset`
- back controls such as `back_height`, `back_type`, `back_profile`
- arm controls such as `arm_y`, `arm_z`, `arm_mid`, `arm_profile`

These are the real free parameters of the family.

### 2. Geometry is derived from those parameters

Examples:

- `make_seat()` derives anchor coordinates from `width`, `size`, `thickness`,
  `seat_mid_x`, `seat_mid_z`, and `seat_front`.
- `make_legs()` derives the four legs from shared seat-relative templates plus
  `leg_x_offset`, `leg_y_offset`, and `leg_height`.
- `make_back_decors()` derives edge selections from predicates over
  `back_profile` and `back_height`, not from hand-written masks.
- `make_arms()` derives start/end points by reading the live seat/back geometry
  and perturbing them with compact controls such as `arm_y`, `arm_z`, and
  `arm_mid`.

### 3. Some low-level operators are still generative

The presence of `write_co(...)`, `select_edges(...)`, and
`bridge_edge_loops(...)` is not inherently a problem in the human generator.
Those calls are still driven by compact controls or by predicates on current
geometry. For example:

- `make_back_decors()` computes edge selections from `back_profile`
- `write_co(...)` applies a rule to live geometry, rather than replaying one
  frozen coordinate array captured from a single finished mesh

This means the issue is not the operator choice alone. The issue is whether the
operator inputs are derived from compact rules or copied from one realized
variant.

## What The Logged Flattened Script Preserves

The flattened script does preserve several useful signals:

- the order of construction steps
- repeated use of the same primitive operations
- some semantic part names such as `seat`, `upper_backrest`, `lower_backrest`
- symmetry hints from mirrored coordinates and repeated calls
- exact geometry behavior for a specific seed

This is enough for helper discovery and partial semantic grouping.

## What The Logged Flattened Script Loses

## 1. Root variables disappear

The flattened script does not expose family-level latent controls like:

- `width`
- `size`
- `leg_height`
- `back_profile`
- `arm_y`
- `arm_z`

Instead, it records their evaluated consequences as explicit anchor coordinates,
locations, or modifier values.

Example:

- in the generator, leg starts and ends are computed from seat-relative
  templates plus offsets
- in the flattened script, each leg is emitted as its own concrete
  `align_bezier(...)` call with already-resolved coordinates

## 2. Derived relations become literal geometry

The generator encodes relations such as:

- "these two back posts are offset versions of seat-relative anchors"
- "these arm endpoints are chosen from the live seat/back geometry"
- "these bars are sampled at a fractional height along the legs"

The flattened script records only the final coordinates, not the relation that
produced them.

This turns a compact dependency into a literal replay problem.

## 3. Predicate-based edge selection degrades into hardcoded masks

One of the clearest losses is in panel/backrest construction.

In the generator, the bridge region is selected by a geometric predicate:

- compute edge centers
- select edges whose `z` lies in a range derived from `back_profile` and
  `back_height`

In the flattened script, that same structure becomes explicit boolean masks such
as:

- `[False, False, ..., True, True, ...]`
- `[True, True, True, False, ...]`

This is a major degradation because the mask is the evaluated result of the
selection rule, not the rule itself.

A model consuming the flattened script has no direct clue that:

- the repeated `True` region corresponds to a structural span
- the span is tied to a profile interval
- the mask should vary when topology or profile changes

## 4. Live geometry transforms degrade into frozen coordinate dumps

Another major loss happens around joined panels / armrest panel construction.

In the generator, code such as:

- join cloned objects
- read live coordinates
- shift coordinates by `back_thickness`
- apply bridging based on current geometry

is still generative.

In `variant_041`, the logged output instead contains:

- one huge `write_co(...)` coordinate array
- two explicit `select_edges(...)` masks
- fixed `bridge_edge_loops(...)` parameters

That turns a derivation over current geometry into a one-topology replay trace.

## 5. Symmetry is only partially visible

The logged trace often contains symmetric literals, but the symmetry is not
expressed as a rule. It is visible only indirectly via:

- sign-flipped coordinates
- duplicated left/right calls
- paired object names

This is weaker than the generator's representation, where symmetry is often
implied by shared templates, mirrored logic, or paired construction from compact
controls.

## 6. Semantic naming drifts under execution logging

Some semantic structure remains, but the logged output also introduces names
like:

- `obj_14`
- `obj_15`
- `armrest_03`

which are artifacts of execution order rather than of design intent.

This makes it harder for an LLM to infer that a joined intermediate object is
really part of a back-panel or top-rail construction rule.

## 7. Finalization noise is mixed with construction logic

The flattened script interleaves:

- creation
- coordinate replay
- edit-mode selection/mutation
- modifier application
- final rotation and transform application

This is faithful as an execution log, but it mixes stable generative structure
with late-stage finalization details. That raises the reasoning burden for the
LLM because it must separate:

- what defines the object family
- what only normalizes/export-prepares the current variant

## Concrete Example: Back / Panel Construction

This is the clearest contrast.

### Human generator

`make_back_decors()` expresses:

- clone the back posts
- join them
- widen by `back_thickness`
- select edge bands from `back_profile` and `back_height`
- bridge those selected regions
- optionally create vertical-bar structure from `back_vertical_cuts`

This is a compact, causal description.

```python
def make_back_decors(self, backs, finalize=True):
        obj = join_objects([deep_clone_obj(b) for b in backs])
        x, y, z = read_co(obj).T
        x += np.where(x > 0, self.back_thickness / 2, -self.back_thickness / 2)
        write_co(obj, np.stack([x, y, z], -1))
        smoothness = uniform(0, 1)
        profile_shape_factor = uniform(0, 0.4)
        with butil.ViewportMode(obj, "EDIT"):
            bpy.ops.mesh.select_mode(type="EDGE")
            center = read_edge_center(obj)
            for z_min, z_max in self.back_profile:
                select_edges(
                    obj,
                    (z_min * self.back_height <= center[:, -1])
                    & (center[:, -1] <= z_max * self.back_height),
                )
                bpy.ops.mesh.bridge_edge_loops(
                    number_cuts=64,
                    interpolation="LINEAR",
                    smoothness=smoothness,
                    profile_shape_factor=profile_shape_factor,
                )
            bpy.ops.mesh.select_loose()
            bpy.ops.mesh.delete()
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
                bpy.ops.mesh.select_mode(type="EDGE")
                bpy.ops.mesh.select_all(action="SELECT")
                bpy.ops.mesh.bridge_edge_loops(
                    number_cuts=self.back_vertical_cuts,
                    interpolation="LINEAR",
                    smoothness=smoothness,
                    profile_shape_factor=profile_shape_factor,
                )
                bpy.ops.mesh.select_all(action="INVERT")
                bpy.ops.mesh.delete()
                bpy.ops.mesh.select_all(action="SELECT")
                bpy.ops.mesh.delete(type="ONLY_FACE")
            remove_edges(other, np.abs(read_edge_direction(other)[:, -1]) < 0.5)
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
            co = read_co(obj)
            co[:, 1] *= self.back_partial_scale
            write_co(obj, co)
        for p in parts:
            write_attribute(p, 1, "panel", "FACE")
        return parts
```

### Flattened `variant_041`

The corresponding logged region expresses:

- clone two concrete objects
- join them
- write an explicit coordinate array with hundreds of scalar values
- select edges using two hardcoded masks
- bridge with fixed parameters

This is no longer a compact construction rule. It is a replay of one realized
mesh state.

```python
obj.name = "obj_14"
objs.append(bpy.data.objects["obj_14"])
obj = deep_clone_obj(bpy.data.objects["obj_7"])
obj.name = "obj_15"
objs.append(bpy.data.objects["obj_15"])
obj = join_objects([bpy.data.objects["obj_14"], bpy.data.objects["obj_15"]])
obj.name = "obj_16"
objs.append(bpy.data.objects["obj_16"])
write_co(bpy.data.objects["obj_16"], np.array([[-0.223702373, 0.023152348, 0.406952053], [-0.223686101, 0.023132995, 0.393725008], [-0.223637688, 0.023075495, 0.380962431], [-0.223557862, 0.022980653, 0.368652582], [-0.223447310, 0.022849292, 0.356783688], [-0.223306688, 0.022682220, 0.345344007], [-0.223136696, 0.022480253, 0.334321767], [-0.222937989, 0.022244208, 0.323705167], [-0.222711327, 0.021974899, 0.313482642], [-0.222457352, 0.021673139, 0.303642243], [-0.222176748, 0.021339748, 0.294172347], [-0.221870201, 0.020975541, 0.285061121], [-0.221538382, 0.020581324, 0.276296854], [-0.221182006, 0.020157926, 0.267867804], [-0.220801743, 0.019706149, 0.259762168], [-0.220398309, 0.019226816, 0.251968294], [-0.219972345, 0.018720746, 0.244474337], [-0.219524565, 0.018188745, 0.237268567], [-0.219055640, 0.017631631, 0.230339259], [-0.218566256, 0.017050218, 0.223674655], [-0.218057113, 0.016445324, 0.217262983], [-0.217528882, 0.015817765, 0.211092502], [-0.216982293, 0.015168350, 0.205151469], [-0.216417971, 0.014497895, 0.199428126], [-0.215836617, 0.013807219, 0.193910718], [-0.215238931, 0.013097137, 0.188587517], [-0.214625614, 0.012368463, 0.183446780], [-0.213997307, 0.011622012, 0.178476706], [-0.213354724, 0.010858599, 0.173665583], [-0.212698551, 0.010079041, 0.169001654], [-0.212029474, 0.009284148, 0.164473146], [-0.211348193, 0.008474741, 0.160068333], [-0.210655364, 0.007651629, 0.155775443], [-0.209951701, 0.006815637, 0.151582778], [-0.209237861, 0.005967569, 0.147478521], [-0.208514588, 0.005108247, 0.143450975], [-0.207782494, 0.004238481, 0.139488339], [-0.207042309, 0.003359091, 0.135578901], [-0.206294718, 0.002470888, 0.131710902], [-0.205540391, 0.001574691, 0.127872601], [-0.204779985, 0.000671308, 0.124052204], [-0.204014229, -0.000238437, 0.120237984], [-0.203243809, -0.001153734, 0.116418205], [-0.202469426, -0.002073765, 0.112581126], [-0.201691704, -0.002997717, 0.108714953], [-0.200911390, -0.003924774, 0.104807973], [-0.200129154, -0.004854120, 0.100848421], [-0.199345695, -0.005784942, 0.096824557], [-0.198561626, -0.006716426, 0.092724599], [-0.197777736, -0.007647755, 0.088536829], [-0.196994650, -0.008578112, 0.084249482], [-0.196213069, -0.009506686, 0.079850823], [-0.195433664, -0.010432659, 0.075329080], [-0.194657134, -0.011355216, 0.070672512], [-0.193884181, -0.012273542, 0.065869369], [-0.193115445, -0.013186824, 0.060907893], [-0.192351671, -0.014094245, 0.055776343], [-0.191593515, -0.014994990, 0.050462965], [-0.190841647, -0.015888246, 0.044956002], [-0.190096783, -0.016773194, 0.039243720], [-0.189359593, -0.017649023, 0.033314344], [-0.188630762, -0.018514914, 0.027156144], [-0.187910961, -0.019370057, 0.020757359], [-0.187200876, -0.020213632, 0.014106240], [-0.186501282, -0.021044826, 0.007191037], [-0.185812774, -0.021862824, 0.000000000], [0.223702373, 0.023152348, 0.406952053], [0.223686101, 0.023132995, 0.393725008], [0.223637688, 0.023075495, 0.380962431], [0.223557862, 0.022980653, 0.368652582], [0.223447310, 0.022849292, 0.356783688], [0.223306688, 0.022682220, 0.345344007], [0.223136696, 0.022480253, 0.334321767], [0.222937989, 0.022244208, 0.323705167], [0.222711327, 0.021974899, 0.313482642], [0.222457352, 0.021673139, 0.303642243], [0.222176748, 0.021339748, 0.294172347], [0.221870201, 0.020975541, 0.285061121], [0.221538382, 0.020581324, 0.276296854], [0.221182006, 0.020157926, 0.267867804], [0.220801743, 0.019706149, 0.259762168], [0.220398309, 0.019226816, 0.251968294], [0.219972345, 0.018720746, 0.244474337], [0.219524565, 0.018188745, 0.237268567], [0.219055640, 0.017631631, 0.230339259], [0.218566256, 0.017050218, 0.223674655], [0.218057113, 0.016445324, 0.217262983], [0.217528882, 0.015817765, 0.211092502], [0.216982293, 0.015168350, 0.205151469], [0.216417971, 0.014497895, 0.199428126], [0.215836617, 0.013807219, 0.193910718], [0.215238931, 0.013097137, 0.188587517], [0.214625614, 0.012368463, 0.183446780], [0.213997307, 0.011622012, 0.178476706], [0.213354724, 0.010858599, 0.173665583], [0.212698551, 0.010079041, 0.169001654], [0.212029474, 0.009284148, 0.164473146], [0.211348193, 0.008474741, 0.160068333], [0.210655364, 0.007651629, 0.155775443], [0.209951701, 0.006815637, 0.151582778], [0.209237861, 0.005967569, 0.147478521], [0.208514588, 0.005108247, 0.143450975], [0.207782494, 0.004238481, 0.139488339], [0.207042309, 0.003359091, 0.135578901], [0.206294718, 0.002470888, 0.131710902], [0.205540391, 0.001574691, 0.127872601], [0.204779985, 0.000671308, 0.124052204], [0.204014229, -0.000238437, 0.120237984], [0.203243809, -0.001153734, 0.116418205], [0.202469426, -0.002073765, 0.112581126], [0.201691704, -0.002997717, 0.108714953], [0.200911390, -0.003924774, 0.104807973], [0.200129154, -0.004854120, 0.100848421], [0.199345695, -0.005784942, 0.096824557], [0.198561626, -0.006716426, 0.092724599], [0.197777736, -0.007647755, 0.088536829], [0.196994650, -0.008578112, 0.084249482], [0.196213069, -0.009506686, 0.079850823], [0.195433664, -0.010432659, 0.075329080], [0.194657134, -0.011355216, 0.070672512], [0.193884181, -0.012273542, 0.065869369], [0.193115445, -0.013186824, 0.060907893], [0.192351671, -0.014094245, 0.055776343], [0.191593515, -0.014994990, 0.050462965], [0.190841647, -0.015888246, 0.044956002], [0.190096783, -0.016773194, 0.039243720], [0.189359593, -0.017649023, 0.033314344], [0.188630762, -0.018514914, 0.027156144], [0.187910961, -0.019370057, 0.020757359], [0.187200876, -0.020213632, 0.014106240], [0.186501282, -0.021044826, 0.007191037], [0.185812774, -0.021862824, 0.000000000]]))
with butil.ViewportMode(bpy.data.objects["obj_16"], "EDIT"):
    bpy.ops.mesh.select_mode(type="EDGE")
    select_edges(bpy.data.objects["obj_16"], [False, False, False, False, False, False, False, False, False, False, False, False, True, True, True, True, True, True, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, True, True, True, True, True, True, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False])
    bpy.ops.mesh.bridge_edge_loops(number_cuts=64, interpolation="LINEAR", smoothness=0.178077286, profile_shape_factor=0.102849172)
    select_edges(bpy.data.objects["obj_16"], [True, True, True, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, True, True, True, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False])
    bpy.ops.mesh.bridge_edge_loops(number_cuts=64, interpolation="LINEAR", smoothness=0.178077286, profile_shape_factor=0.102849172)
    bpy.ops.mesh.select_loose()
    bpy.ops.mesh.delete()
butil.modify_mesh(bpy.data.objects["obj_16"], 'SOLIDIFY', thickness=0.040776913115597634, offset=0)
butil.modify_mesh(bpy.data.objects["obj_16"], 'BEVEL', width=0.006707264964442234, segments=8)

```


## Diagnosis

The current logged representation is best described as:

- **good for exact behavior capture**
- **good enough for helper discovery and part grouping**
- **weak for latent parameter recovery when a construction step is lowered all
  the way to evaluated geometry**

The hardest cases are precisely the ones that matter most for Phase 3:

- repeated panels
- joined structures
- topology-sensitive edit-mode operations
- selections currently expressed as mesh-sized masks
- coordinates currently expressed as full arrays rather than compact profiles

## Implications For Reverse Engineering

The flattened script should be treated as an executed trace, not as a direct
declaration of true free parameters.

For reverse engineering, the most important distinction is:

- **good literals**: compact controls that still behave like a schema, profile,
  ratio, interval, or branch parameter
- **bad literals**: arrays or masks whose size scales with instance count or
  mesh topology

The current chair logged output contains both.

The problem is not that all literals are wrong. The problem is that the logged
format does not mark which literals are:

- causal controls
- derived intermediate values
- topology-bound replay artifacts

That ambiguity is what later analysis stages must resolve.

## Out-Of-Scope Follow-Up Ideas

These are intentionally outside the scope of `3.1a`, but they are the natural
data-side follow-ups suggested by this inspection:

- Export an additional higher-level command-history trace when available.
- Preserve predicate-style selection logic when it exists instead of only
  logging evaluated masks.
- Preserve compact profile/range controls when they generate a mesh transform,
  rather than only logging the transformed coordinates.
- Keep the exact flattened script for behavior validation, but pair it with a
  more semantically faithful trace for reverse-engineering tasks.

## Bottom Line

The current logged chair data is not useless or fundamentally wrong. It already
contains enough structure to support helper discovery and some semantic
decomposition.

But for latent dependency induction, it has a specific weakness:

it often replaces a compact generative rule with the literal result of running
that rule on one mesh instance.

That makes the reverse-engineering task substantially harder, because the model
must infer not only which constants vary, but also which long literals are not
true parameters at all.
