### Sanitizing Procedural Generators into Deterministic Logged Scripts

This document defines rules and conventions for creating a "logged" variant of a procedural asset generator (e.g., `chair.py`) that can:
- Generate the asset normally inside Blender, and
- Emit a sanitized script that recreates the exact same asset using only low-level function calls with constant arguments.

The goal is a small, deterministic, dependency-light script that reproduces one concrete asset instance without randomization, high-level control flow, or semantic variable names.

## Outputs
- **Blender objects**: Generated as usual by the logged variant; do not merge parts into a single mesh. Each piece stays a separate object and is named `obj_1`, `obj_2`, ... in the Blender file.
- **Sanitized script**: A single Python file that, when executed in Blender, reconstructs the same asset instance. It uses only the allowed low-level calls (see below) and inlines all numeric values as constants.

## Allowed building blocks in sanitized scripts
Sanitized scripts must restrict themselves to calls that correspond to low-level geometry operations and data writes used by the original generator. Examples include (names illustrative):
- Geometry construction and editing helpers: `bezier_curve`, `align_bezier`, `subsurf`, `solidify`, `butil.modify_mesh`, `butil.apply_transform`, `write_co`, `write_attribute`, `remove_edges`, `remove_vertices`, `select_edges`, etc.
- Surface/material assignment helpers: `surface.assign_material`, or the minimal set needed to assign already-resolved materials.
- Object utilities: `join_objects` only if strictly required for a single sub-part; do not use it to merge all parts into one final object.

Notes:
- Import only the functions actually used by the sanitized script. Avoid importing factories, classes, or modules that provide high-level orchestration.
- No random utilities or seed management are allowed in the sanitized script.

## Disallowed constructs in sanitized scripts
- Classes, factory objects, or any high-level pipeline abstractions
- Randomness, seeds, or stochastic branching
- Semantic variable names (e.g., `limb`, `arm`, `back`). Use generic names only (see Naming).
- Derived variables or transformations whose values could be inlined as constants
- Conditional logic or loops that depend on runtime state

## Variable elimination and constant folding
The sanitized script must inline concrete numeric data everywhere. That means:
- Replace all symbolic parameters and intermediate computations with literal constants. Example: Instead of computing `obj.location = base + offset * scale`, directly write the resolved numeric vector assigned to `obj.location`.
- Evaluate all function inputs and geometry parameters during logging and emit them as literals. For example, calls like `align_bezier(points, axes, scale)` must provide fully resolved `points`, `axes`, and `scale` as numeric constants.
- Eliminate helper variables unless absolutely necessary for readability; if used, they must be neutral (e.g., `v1`, `p2`, `m1`) and never semantically named.

## Control-flow resolution
Resolve all control flow during logging and output only the taken path:
- If/else branches must be eliminated by emitting only the executed branch.
- Loops must be unrolled to explicit, repeated calls with constant arguments.
- Comprehensions are not allowed; emit concrete lists/tuples with literals.

## Object identity and naming
- Do not join all parts at the end. Keep each generated sub-part as its own object.
- Assign deterministic names in creation order: `obj_1`, `obj_2`, ..., `obj_N`.
- In the sanitized script, bind temporary references using neutral identifiers (e.g., `obj`, `objs = []`) and immediately set `obj.name = "obj_k"` after creation.

## Materials and attributes
- If the original generator assigns materials or attributes, the sanitized script should emit the same operations using constant arguments.
- If the original uses randomized or generator-bound materials, the logged variant must resolve to a specific material definition or node assignment. Avoid instantiating a new material generator in the sanitized script; instead, assign a concrete material that already exists or is fully specified by literal parameters.
- Attribute writes (e.g., marking limb/panel faces) must be preserved by calling low-level attribute APIs with constant values.

## Transforms and modifiers
- All transforms must be resolved to constants: locations, scales, rotations, and modifier parameters should be emitted as literal values.
- Modifier application order must match the original execution. Include explicit calls such as `butil.apply_transform`, `butil.modify_mesh` with constant parameters.

## Randomness and determinism
- The logged variant that runs inside Blender may use randomness as usual to generate the asset.
- When emitting the sanitized script, capture the concrete realization (post-randomization) and write only constants. The sanitized script must not import or call any random utilities.

## API and structure of a logged variant
The logged variant file (e.g., `chair_logged.py`) should:
- Expose the same public entry point(s) to create the asset normally inside Blender.
- Provide an additional entry point (e.g., `export_sanitized_script(output_path: str)`) that:
  - Runs generation (or receives an already-generated result),
  - Captures the executed low-level calls and their resolved parameters,
  - Writes a sanitized Python script containing only those calls with constants,
  - Preserves object-per-part creation and assigns names `obj_1..obj_N`.

Implementation guidance:
- Use a lightweight call-logger wrapper around allowed low-level functions. On invocation, it records the function name and fully-resolved arguments after evaluating any arrays, vectors, and control flow.
- Avoid relying on reading mesh data as the primary source of truth for reconstruction. Prefer logging the exact sequence of low-level calls as they happen, with their constant parameters. Mesh reads are acceptable for final touches where necessary, but should be minimized.

### How `chair_logged.py` was created from `chair.py`

1) Swap imports to module aliases so wrappers can be installed:
- Example: `from ... import decorate as deco`, `from ... import draw as draw_utils`, `from ...util import blender as butil`.

2) Wrap only low-level helpers used by the generator and emit constant calls:
- draw: `bezier_curve`, `align_bezier` → write `np.array` anchors/axes/scale literals.
- decorate: `write_co`, `remove_edges`, `remove_vertices`, `select_edges`, `subsurf`, `solidify`.
- object utils: `new_bbox`, `join_objects` (only where strictly needed inside a sub-step).
- core: `butil.modify_mesh`, `butil.apply_transform`.
- surface: only `add_geomod` when the nodegroup is resolvable (e.g., `geo_radius`); omit `assign_material` (dematerialized output).

3) Assign deterministic object names in creation order:
- Immediately after each creation, set `obj.name = "obj_k"` and record a stable reference used in subsequent calls.

4) Resolve control-flow and fold constants:
- Execute `ChairFactory` normally; log only the taken branches with concrete numeric parameters. Loops are unrolled into multiple constant calls.

5) Per-part finalization instead of global merge:
- Keep parts separate (no final `join`). If the original rotates/applies at the end, the logged variant rotates/applies per-part for simplicity (equivalent end pose).

6) Export sanitized script:
- Write a minimal file with only required imports and the recorded helper calls with constants. No factories/randomness/material generators.

### Applying to other generators (tables, lamps, ...)

- Identify the helper subset used by that generator and wrap them as above.
- Emit constants and object handles exactly as in `chair_logged.py`.
- Keep parts separate and name in creation order.
- Omit materials or replace with fully constant assignments if needed.

## Naming rules inside sanitized scripts
- Variables: only neutral names like `obj`, `objs`, `p1`, `p2`, `v1`, `v2`, `data`.
- Objects in Blender: assign `obj.name = "obj_k"` in deterministic order.
- Do not use semantic names like `limb`, `arm`, `back`, `seat`.

## Minimal sanitized script shape (illustrative)
This is not the actual code, just an outline of the expected structure:

```python
import bpy
import numpy as np
from infinigen.assets.utils.draw import bezier_curve, align_bezier
from infinigen.assets.utils.decorate import write_co, write_attribute
from infinigen.core.util import blender as butil
from infinigen.core import surface

objs = []

# Part 1
obj = bezier_curve((
    np.array([...]),  # x anchors
    np.array([...]),  # y anchors
    np.array([...])   # z anchors
), [2, 4])
obj.name = "obj_1"
objs.append(obj)

# Part 2
obj = align_bezier(np.array([[...], [...]]).T, axes=[...], scale=[...])
obj.location = np.array([c1, c2, c3])
butil.apply_transform(obj, True)
obj.name = "obj_2"
objs.append(obj)

# ... additional constant-parameter calls ...

# Optional: assign materials/attributes with concrete parameters
surface.assign_material(objs[0], SOME_MATERIAL)
write_attribute(objs[1], 1, "obj1", "FACE")
```

## Checklist
- Asset parts are separate objects; no final merge.
- Objects are named `obj_1..obj_N` deterministically.
- Only low-level, allowed functions are imported and called.
- No randomness, factories, classes, or semantic variable names.
- All parameters are constants; no computed variables or control flow.
- Modifier order and transform applications match the original execution.
- Materials/attributes are assigned via concrete, constant parameters.

## Notes for applying to other generators
The same rules apply across assets (tables, lamps, etc.). For each generator:
- Identify the low-level function subset it uses.
- Instrument those calls to log fully-resolved, constant parameters.
- Ensure the logged variant preserves multi-part object granularity and naming.
- Expose an export function to write the sanitized script for any specific instance.



