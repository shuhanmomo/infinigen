# Generating Logged Assets

This document explains how to generate Blender command logs and the derived clean, low-level Python programs that recreate Infinigen assets without relying on selection state.

## Quick Start

1. Launch Blender in batch mode with the logging script:

   ```powershell
   & "D:\OneDrive\Infinigen\blender\blender.exe" -b --python infinigen_examples/generate_assets_with_logging.py -- --seed 41 --variants 2 --output-dir _out/logged_chairs --metadata --render
   ```

   * `--seed` supplies the first seed; `--variants` controls how many consecutive variants are generated (`41`, `42`, … in this example).
   * Each variant is written to its own subdirectory: `_out/logged_chairs/variant_041`, `_out/logged_chairs/variant_042`, etc.
   * `--metadata` captures a baked mesh snapshot so the clean replay can be emitted.
   * `--render` produces a still render for each clean replay, stored alongside the recreated blend file.

2. Inspect the outputs inside each variant folder:

   * `variant_041/ChairFactory_041_ops.json` – raw operator log with mesh snapshots.
   * `variant_041/ChairFactory_041_replay.py` – verbatim replay script (includes selection/active state).
   * `variant_041/ChairFactory_041_clean.py` – streamlined low-level replay; components are named `obj1`, `obj2`, …
   * `variant_041/ChairFactory_041.blend` – original factory output.
   * `variant_041/ChairFactory_041_clean.blend` – deterministic rebuild from the clean script.
   * `variant_041/ChairFactory_041_clean.png` – optional render (present when `--render` is set).

3. Rebuild or render on demand:

   ```powershell
   & "D:\OneDrive\Infinigen\blender\blender.exe" -b --python _out/logged_chairs/variant_041/ChairFactory_041_clean.py
   ```

   The clean script regenerates the asset using only low-level mesh creation calls; no selection state or factory helpers are involved.

## How It Works

`generate_assets_with_logging.py` performs three tasks:

1. **Instrumentation** – wraps `_BPyOpsSubModOp.__call__` so every `bpy.ops` invocation is recorded alongside the parameters that Blender receives. Selected Blender utility functions (`butil.apply_transform`, `butil.modify_mesh`, etc.) are also logged.

2. **Mesh Snapshotting** – after the factory finishes, the script captures the final mesh and splits it into connected components. Each component stores constant vertex and face arrays along with the object matrix. Modifiers are baked into simple dictionaries containing their numeric settings. Component names are normalized (`obj1`, `obj2`, …) to avoid seed-specific identifiers.

3. **Replay Generation** – two scripts are emitted per variant:
   * `*_replay.py` replays the operator sequence (useful for debugging).
   * `*_clean.py` writes the baked vertex/face lists back into mesh datablocks, avoiding selection, active-object state, or high-level factory calls. When `--render` is used, the script automatically saves a `_clean.blend` and renders a still image in the same directory.

## Extending to Other Factories

* Pass a different factory with `--factory infinigen.assets.objects.tables.table.TableFactory` (for example).
* Use `--seed <base>` and `--variants <count>` to sample consecutive seeds automatically. Each variant gets its own subdirectory under the chosen output root.

## Troubleshooting

* **`bpy` import errors** – ensure you run inside Blender (`blender.exe -b --python ...`).
* **Missing modifiers in clean script** – only numeric settings are preserved; if a modifier relies on object pointers, extend `_collect_mesh_snapshot` to capture and recreate those relationships.
* **Large files** – complex assets can produce large vertex lists; consider externalizing the arrays (e.g., JSON or NumPy) if needed for your workflow.

