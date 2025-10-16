"""Generate a single asset and capture the low-level Blender call sequence.

This script is intended to run *inside* Blender (``blender -b --python`` or
``python -m infinigen.launch_blender``).  It instruments ``bpy.ops``
invocations as well as a few utility helpers from Infinigen so that every
update to the scene is recorded.  The resulting JSON/text logs can then be
used as training data for library-learning research or to study the
procedural pipeline at a lower level.

The default configuration generates a single chair via
``ChairFactory``.  You can supply an alternative ``AssetFactory`` by passing
``--factory infinigen.path.to.ClassName``.

Example usage (from the repository root)::

    blender/blender.exe -b --python \
        infinigen_examples/generate_assets_with_logging.py -- \
        --factory infinigen.assets.objects.seating.chairs.chair.ChairFactory \
        --seed 42 --output-dir _out/logged_chairs

The script intentionally keeps the feature set minimal for now – it produces
the asset, saves a ``.blend`` file (unless ``--no-save-blend`` is supplied),
and emits two log files:

* ``<factory>_<seed>_ops.json`` – structured data suitable for downstream
  processing.
* ``<factory>_<seed>_ops.txt`` – human-readable summary of the operations.

Future factories can reuse this script without modification because the
instrumentation is generic.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from contextlib import contextmanager
import functools
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import math
from mathutils import Vector
from typing import Any, Callable, Dict, Iterable, List, Tuple
from collections import defaultdict
import subprocess

import bpy
from bpy.ops import _BPyOpsSubModOp

from infinigen.core import init
from infinigen.core.util import blender as butil

# Functions inside infinigen.core.util.blender we want to patch for logging
BUTIL_FUNCS_TO_PATCH = ["apply_transform", "modify_mesh", "delete", "save_blend"]
from infinigen.core.util.math import FixedSeed


# ---------------------------------------------------------------------------
# Utility data structures


def _to_builtin(value: Any, *, max_depth: int = 4) -> Any:
    """Best-effort conversion to JSON serialisable structures.

    ``bpy`` exposes many custom types.  For logging purposes, represent them
    using ``repr`` while leaving numbers/strings intact.
    """

    if max_depth <= 0:
        return repr(value)

    if isinstance(value, (int, float, str, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple, set)):
        return [_to_builtin(v, max_depth=max_depth - 1) for v in value]
    if isinstance(value, dict):
        return {
            str(k): _to_builtin(v, max_depth=max_depth - 1) for k, v in value.items()
        }
    if hasattr(value, "tolist"):
        try:
            return value.tolist()
        except Exception:  # noqa: BLE001
            pass
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:  # noqa: BLE001
            pass
    # Special handling for mathutils types (Vectors, Matrices, etc.).
    if hasattr(value, "to_tuple"):
        try:
            return value.to_tuple()
        except:  # noqa: BLE001 - fall back to repr
            pass
    if hasattr(value, "to_list"):
        try:
            return value.to_list()
        except:  # noqa: BLE001
            pass
    return repr(value)


def _current_active_name() -> str | None:
    obj = bpy.context.view_layer.objects.active
    return obj.name if obj is not None else None


def _current_selected_names() -> List[str]:
    return [obj.name for obj in bpy.context.selected_objects]


@dataclass
class LogEntry:
    kind: str
    name: str
    args: Any
    kwargs: Any
    status: str = "ok"
    result: Any | None = None
    error: str | None = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "name": self.name,
            "args": self.args,
            "kwargs": self.kwargs,
            "status": self.status,
            "result": self.result,
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# Instrumentation helpers


class OperationLogger:
    """Collects log entries and manages monkey-patches."""

    def __init__(self) -> None:
        self.original_call: Callable | None = None
        self.original_class_call: Callable | None = None
        self.patched = False
        self.entries: List[LogEntry] = []

    def install(self) -> None:
        if self.patched:
            return

        self.original_call = _BPyOpsSubModOp.__call__

        def patched_call(op_self, *args, **kwargs):  # type: ignore[override]
            return self._patched_call(op_self, *args, **kwargs)

        _BPyOpsSubModOp.__call__ = patched_call  # type: ignore[assignment]

        for name in BUTIL_FUNCS_TO_PATCH:
            func = getattr(butil, name)
            setattr(butil, name, self.wrap_butil(name, func))

        self.patched = True

    def uninstall(self) -> None:
        if not self.patched:
            return

        _BPyOpsSubModOp.__call__ = self.original_call  # type: ignore[assignment]

        for name in BUTIL_FUNCS_TO_PATCH:
            func = getattr(butil, name)
            if hasattr(func, "__wrapped__"):
                setattr(butil, name, func.__wrapped__)

        self.patched = False

    def wrap_butil(self, name: str, func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        def wrapped(*args, **kwargs):
            entry = LogEntry(
                kind="butil",
                name=name,
                args=_to_builtin(args),
                kwargs=_to_builtin(kwargs),
            )
            try:
                result = func(*args, **kwargs)
                entry.result = _to_builtin(result)
            except Exception as exc:  # noqa: BLE001
                entry.status = "error"
                entry.error = repr(exc)
                raise
            finally:
                self.entries.append(entry)

            return result

        return wrapped

    def wrap_op(
        self, path: tuple[str, ...], op: Callable[..., Any]
    ) -> Callable[..., Any]:
        @functools.wraps(op)
        def wrapped(*args, **kwargs):
            entry = LogEntry(
                kind="bpy.ops",
                name=path[-1],
                args=_to_builtin(args),
                kwargs=_to_builtin(kwargs),
            )
            try:
                result = op(*args, **kwargs)
                entry.result = _to_builtin(result)
            except Exception as exc:  # noqa: BLE001
                entry.status = "error"
                entry.error = repr(exc)
                raise
            finally:
                self.entries.append(entry)

            return result

        return wrapped

    def _patched_call(self, op_self, *args, **kwargs):
        try:
            idname = op_self.idname()
        except AttributeError:
            idname = op_self.idname_str()
        path = tuple(idname.split("."))
        op = self.original_call.__get__(op_self, _BPyOpsSubModOp)  # type: ignore[arg-type]
        wrapped = self.wrap_op(path, op)
        return wrapped(*args, **kwargs)

    def as_text(self) -> str:
        lines = []
        for entry in self.entries:
            head = f"[{entry.kind}] {entry.name}"
            body = json.dumps(
                {
                    "args": entry.args,
                    "kwargs": entry.kwargs,
                    "status": entry.status,
                    "result": entry.result,
                    "error": entry.error,
                },
                ensure_ascii=False,
            )
            lines.append(f"{head} {body}")
        return "\n".join(lines)


@contextmanager
def logging_context(logger: OperationLogger) -> Iterable[None]:
    logger.install()
    try:
        yield
    finally:
        logger.uninstall()


# ---------------------------------------------------------------------------
# Asset generation


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cli", action="store_true", help="Run main when invoking from Blender CLI"
    )
    parser.add_argument(
        "--factory",
        default="infinigen.assets.objects.seating.chairs.chair.ChairFactory",
        help="Dotted path to the AssetFactory to instantiate",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Base seed; variants increment from this value",
    )
    parser.add_argument(
        "--variants",
        type=int,
        default=1,
        help="Number of assets to generate (seeds increase sequentially)",
    )
    parser.add_argument(
        "--render", action="store_true", help="Render each generated asset"
    )
    parser.add_argument(
        "--resolution", type=int, nargs=2, default=[512, 512], help="Render resolution"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("_out/asset_logging"),
        help="Directory where logs and blend files are written",
    )
    parser.add_argument(
        "--no-save-blend",
        action="store_true",
        help="Skip writing a .blend file (logging only)",
    )
    parser.add_argument(
        "--metadata",
        action="store_true",
        help="Dump factory attributes in the JSON log",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print log entries to stdout as they are captured",
    )
    parser.add_argument(
        "--configs",
        type=str,
        nargs="+",
        default=[],
        help="Gin config files to load before running the factory",
    )
    parser.add_argument(
        "--overrides",
        type=str,
        nargs="+",
        default=[],
        help="Gin override strings",
    )

    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    else:
        argv = []
    return parser.parse_args(argv)


def import_factory(path: str) -> type:
    module_path, _, class_name = path.rpartition(".")
    if not module_path:
        raise ValueError(f"Factory path must include a module: {path!r}")
    module = importlib.import_module(module_path)
    try:
        factory_cls = getattr(module, class_name)
    except AttributeError as exc:  # noqa: BLE001
        raise ImportError(
            f"Factory {class_name!r} not found in module {module_path!r}"
        ) from exc
    return factory_cls


def dump_logs(
    logger: OperationLogger,
    output_dir: Path,
    prefix: str,
    *,
    metadata: Dict[str, Any] | None = None,
) -> Path | None:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_doc = {
        "created_at": datetime.utcnow().isoformat() + "Z",
        "entries": [entry.as_dict() for entry in logger.entries],
    }
    clean_script_path: Path | None = None
    if metadata and metadata.get("generated_object"):
        obj = bpy.data.objects.get(metadata["generated_object"])
        if obj is not None:
            json_doc["asset"] = _collect_mesh_snapshot(obj)
            child_snapshots = []
            for child in obj.children_recursive:
                child_snapshots.append(_collect_mesh_snapshot(child))
            if child_snapshots:
                json_doc["asset_children"] = child_snapshots
    if metadata:
        json_doc["metadata"] = metadata

    json_path = output_dir / f"{prefix}_ops.json"
    json_path.write_text(json.dumps(json_doc, indent=2, ensure_ascii=False))

    text_path = output_dir / f"{prefix}_ops.txt"
    text_path.write_text(logger.as_text())
    # Also produce a replay script for deterministic regeneration.
    dump_replay_script(logger, output_dir, prefix, metadata=metadata)
    asset_snapshot = json_doc.get("asset")
    if asset_snapshot:
        child_snapshots = json_doc.get("asset_children", [])
        clean_script_path = _dump_clean_mesh_script(
            asset_snapshot, child_snapshots or [], output_dir, prefix
        )

    return clean_script_path


def _format_value(value: Any) -> str:
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, (int, float)):
        return repr(value)
    if value is None:
        return "None"
    if isinstance(value, str):
        lowered = value.strip()
        if lowered.startswith("bpy.data"):
            return f"resolve({repr(lowered)})"
        if lowered.startswith("butil."):
            return lowered
        if lowered.startswith("array(") and lowered.endswith(")"):
            inner = lowered[6:-1]
            if ", dtype" in inner:
                inner = inner.split(", dtype")[0]
            return f"tuple({inner})"
        return repr(value)
    if isinstance(value, list):
        return "[" + ", ".join(_format_value(v) for v in value) + "]"
    if isinstance(value, tuple):
        inner = ", ".join(_format_value(v) for v in value)
        if len(value) == 1:
            inner += ","
        return f"({inner})"
    if isinstance(value, dict):
        items = ", ".join(f"{repr(k)}: {_format_value(v)}" for k, v in value.items())
        return f"{{{items}}}"
    return repr(value)


def _op_name_to_call(name: str) -> str:
    if "_OT_" not in name:
        raise ValueError(f"Unexpected operator idname: {name}")
    category, op = name.split("_OT_")
    return f"bpy.ops.{category.lower()}.{op.lower()}"


def _split_mesh_components(obj: bpy.types.Object) -> List[Dict[str, Any]]:
    mesh = obj.data
    vert_count = len(mesh.vertices)
    if vert_count == 0:
        return []

    parent = list(range(vert_count))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for edge in mesh.edges:
        v1, v2 = edge.vertices
        union(v1, v2)

    groups: Dict[int, List[int]] = defaultdict(list)
    for vid in range(vert_count):
        groups[find(vid)].append(vid)

    components: List[Dict[str, Any]] = []
    for cid, verts in enumerate(groups.values()):
        vert_set = set(verts)
        index_map = {old: new for new, old in enumerate(verts)}
        vertices = [tuple(mesh.vertices[v].co) for v in verts]
        faces: List[tuple[int, ...]] = []
        for poly in mesh.polygons:
            if all(v in vert_set for v in poly.vertices):
                faces.append(tuple(index_map[v] for v in poly.vertices))
        if not faces:
            continue
        components.append(
            {
                "name": f"{obj.name}_part_{cid}",
                "matrix_world": [list(row) for row in obj.matrix_world],
                "vertices": vertices,
                "faces": faces,
            }
        )
    return components


def _collect_mesh_snapshot(obj: bpy.types.Object) -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "name": obj.name,
        "matrix_world": [list(row) for row in obj.matrix_world],
        "type": obj.type,
    }
    if obj.type == "MESH":
        components = _split_mesh_components(obj)
        data["components"] = components
        mods: List[Dict[str, Any]] = []
        for mod in obj.modifiers:
            settings: Dict[str, Any] = {}
            for prop in dir(mod):
                if prop.startswith("_"):
                    continue
                if prop in {"bl_rna", "rna_type", "type", "name"}:
                    continue
                try:
                    value = getattr(mod, prop)
                except AttributeError:
                    continue
                if isinstance(value, (int, float, str, bool)):
                    settings[prop] = value
                elif isinstance(value, (tuple, list)):
                    settings[prop] = list(value)
            if settings:
                mods.append({"type": mod.type, "settings": settings})
        if mods:
            data["modifiers"] = mods
    elif obj.type == "CURVE":
        curve = obj.data
        curve_data = []
        for spline in curve.splines:
            points = []
            if spline.type == "BEZIER":
                for bp in spline.bezier_points:
                    points.append(
                        {
                            "co": tuple(bp.co),
                            "handle_left": tuple(bp.handle_left),
                            "handle_right": tuple(bp.handle_right),
                            "tilt": bp.tilt,
                            "weight": bp.weight,
                        }
                    )
            else:
                for p in spline.points:
                    points.append(
                        {
                            "co": tuple(p.co),
                            "weight": p.weight,
                        }
                    )
            curve_data.append(
                {
                    "type": spline.type,
                    "cyclic_u": spline.use_cyclic_u,
                    "points": points,
                }
            )
        data["curve"] = curve_data
    return data


def dump_replay_script(
    logger: OperationLogger,
    output_dir: Path,
    prefix: str,
    metadata: Dict[str, Any] | None = None,
    objects: List[bpy.types.Object] | None = None,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    script_path = output_dir / f"{prefix}_replay.py"

    lines: List[str] = []
    lines.append("# Auto-generated replay script")
    if metadata:
        lines.append(f"# Metadata: {json.dumps(metadata, ensure_ascii=False)}")
    lines.append("import argparse")
    lines.append("import sys")
    lines.append("import bpy")
    lines.append("from infinigen.core.util import blender as butil")
    lines.append("")
    default_output = None
    if metadata and "blend_file" in metadata:
        default_output = Path(metadata["blend_file"]).with_name(
            Path(metadata["blend_file"]).stem + "_replay.blend"
        )
    if default_output is None:
        default_output = (output_dir / f"{prefix}_replay.blend").resolve()

    lines.append("")
    lines.append("def parse_args(argv=None):")
    lines.append("    if argv is None:")
    lines.append("        argv = sys.argv")
    lines.append("    if '--' in argv:")
    lines.append("        argv = argv[argv.index('--') + 1:]")
    lines.append("    else:")
    lines.append("        argv = []")
    lines.append(
        "    parser = argparse.ArgumentParser(description='Replay logged asset')"
    )
    lines.append(
        f"    parser.add_argument('--output-blend', default={repr(default_output)}, help='Path to save the replayed .blend file')"
    )
    lines.append(
        "    parser.add_argument('--skip-save', action='store_true', help='Do not save a .blend file after replay')"
    )
    lines.append("    return parser.parse_args(argv)")
    lines.append("")
    lines.append("def run(args):")
    lines.append("    butil.clear_scene()")

    for idx, entry in enumerate(logger.entries, start=1):
        if entry.kind == "bpy.ops":
            call = _op_name_to_call(entry.name)
        else:
            call = entry.name

        args_source: List[str] = []
        if isinstance(entry.args, (list, tuple)):
            for arg in entry.args:
                args_source.append(_format_value(arg))
        elif entry.args not in (None, []):
            args_source.append(_format_value(entry.args))

        kwargs_items: List[str] = []
        if isinstance(entry.kwargs, dict):
            for key, value in entry.kwargs.items():
                if key == "poll":
                    continue
                kwargs_items.append(f"{key}={_format_value(value)}")

        call_parts = args_source + kwargs_items
        if call_parts:
            call_line = f"{call}({', '.join(call_parts)})"
        else:
            call_line = f"{call}()"

        lines.append(f"    {call_line}")

    lines.append("")
    lines.append("if __name__ == '__main__':")
    lines.append("    _args = parse_args()")
    lines.append("    run(_args)")
    lines.append("    if not _args.skip_save:")
    lines.append("        bpy.ops.wm.save_as_mainfile(filepath=_args.output_blend)")

    script_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _format_tuple(seq: Iterable[Any]) -> str:
    return "(" + ", ".join(repr(v) for v in seq) + ")"


def _dump_clean_mesh_script(
    asset: Dict[str, Any],
    children: List[Dict[str, Any]],
    output_dir: Path,
    prefix: str,
) -> Path:
    script_path = output_dir / f"{prefix}_clean.py"
    lines: List[str] = []
    lines.append("# Clean low-level replay script")
    lines.append("import argparse")
    lines.append("import json")
    lines.append("import sys")
    lines.append("import bpy")
    lines.append("from mathutils import Matrix")
    lines.append("")
    lines.append("def parse_args(argv=None):")
    lines.append(
        "    parser = argparse.ArgumentParser(description='Clean asset replay')"
    )
    lines.append(
        "    parser.add_argument('--output-blend', default=None, help='Optional path to save the resulting blend file')"
    )
    lines.append(
        "    parser.add_argument('--skip-save', action='store_true', help='Do not save a .blend file')"
    )
    lines.append("    if argv is None:")
    lines.append("        argv = sys.argv")
    lines.append("    if '--' in argv:")
    lines.append("        argv = argv[argv.index('--') + 1:]")
    lines.append("    else:")
    lines.append("        argv = []")
    lines.append("    return parser.parse_args(argv)")
    lines.append("")
    lines.append("def clear_scene():")
    lines.append("    for obj in list(bpy.data.objects):")
    lines.append("        bpy.data.objects.remove(obj, do_unlink=True)")
    lines.append("")
    lines.append("def create_mesh(name, vertices, faces):")
    lines.append("    mesh = bpy.data.meshes.new(name)")
    lines.append("    mesh.from_pydata(vertices, [], faces)")
    lines.append("    mesh.update()")
    lines.append("    obj = bpy.data.objects.new(name, mesh)")
    lines.append("    bpy.context.collection.objects.link(obj)")
    lines.append("    return obj")
    lines.append("")
    components: List[Dict[str, Any]] = []
    if asset.get("components"):
        components.extend(asset["components"])
    for child in children:
        if child.get("components"):
            components.extend(child["components"])
    lines.append(f"COMPONENT_COUNT = {len(components)}")
    lines.append("")
    comp_json = json.dumps(components)
    lines.append(f"components = json.loads({comp_json!r})")
    for idx, comp in enumerate(components):
        name = f"obj{idx + 1}"
        verts = comp.get("vertices", [])
        faces = comp.get("faces", [])
        matrix = comp.get("matrix_world") or asset.get("matrix_world")
        lines.append(f"vertices_{idx} = []")
        for chunk in [verts[i : i + 256] for i in range(0, len(verts), 256)]:
            lines.append(f"vertices_{idx}.extend({[tuple(v) for v in chunk]!r})")
        lines.append(f"faces_{idx} = []")
        for chunk in [faces[i : i + 256] for i in range(0, len(faces), 256)]:
            lines.append(f"faces_{idx}.extend({[tuple(f) for f in chunk]!r})")
        lines.append(f"comp_{idx} = {{'name': 'obj{idx + 1}', 'matrix': {matrix!r}}}")
        lines.append(f"comp_{idx}['vertices'] = vertices_{idx}")
        lines.append(f"comp_{idx}['faces'] = faces_{idx}")
    lines.append("")
    lines.append("def run(args):")
    lines.append("    clear_scene()")
    lines.append("    created = []")
    lines.append("    for idx, comp in enumerate(components):")
    lines.append("        name = comp.get('name', f'obj{idx+1}')")
    lines.append("        verts = [tuple(v) for v in comp.get('vertices', [])]")
    lines.append("        faces = [tuple(f) for f in comp.get('faces', [])]")
    lines.append("        obj = create_mesh(name, verts, faces)")
    lines.append("        matrix = comp.get('matrix_world')")
    lines.append("        if matrix:")
    lines.append("            obj.matrix_world = Matrix(matrix)")
    lines.append("        created.append(obj)")
    lines.append("    if not args.skip_save and args.output_blend:")
    lines.append("        bpy.ops.wm.save_as_mainfile(filepath=args.output_blend)")
    lines.append("    return created")
    lines.append("")
    lines.append("if __name__ == '__main__':")
    lines.append("    _args = parse_args()")
    lines.append("    run(_args)")
    script_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return script_path


def collect_factory_metadata(factory_instance: Any) -> Dict[str, Any]:
    data: Dict[str, Any] = {}
    for name in dir(factory_instance):
        if name.startswith("_"):
            continue
        try:
            value = getattr(factory_instance, name)
        except Exception:  # noqa: BLE001
            continue
        if callable(value):
            continue
        data[name] = _to_builtin(value)
    return data


def main(argv: List[str]) -> int:
    args = parse_args(argv)

    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    factory_cls = import_factory(args.factory)

    # Prepare Blender / Infinigen environment
    init.apply_gin_configs(
        ["infinigen_examples/configs_indoor", "infinigen_examples/configs_nature"],
        configs=args.configs,
        overrides=args.overrides,
        skip_unknown=True,
    )
    init.configure_blender()
    butil.clear_scene()

    logger = OperationLogger()

    clean_scripts: List[Tuple[int, Path]] = []
    seeds = [args.seed + i for i in range(args.variants)]
    if args.verbose:
        print(f"[generate_assets_with_logging] Starting with seeds {seeds}")
    for offset, seed in enumerate(seeds):
        variation_dir = output_dir / f"variant_{seed:03d}"
        variation_dir.mkdir(parents=True, exist_ok=True)
        meta: Dict[str, Any] = {
            "factory": args.factory,
            "seed": seed,
        }

        with logging_context(logger):
            if args.verbose:
                print(
                    f"[generate_assets_with_logging] Logging enabled… (seed={seed})",
                    file=sys.stderr,
                )

            with FixedSeed(seed):
                fac = factory_cls(seed)

            placeholder = None
            with FixedSeed(seed):
                placeholder = fac.spawn_placeholder(seed, (0, 0, 0), (0, 0, 0))
            if args.metadata:
                meta["placeholder_name"] = placeholder.name

            with FixedSeed(seed):
                asset = fac.spawn_asset(seed, placeholder=placeholder)

            fac.finalize_assets(asset)

            meta["generated_object"] = getattr(asset, "name", None)

            if not args.no_save_blend:
                blend_path = variation_dir / f"{factory_cls.__name__}_{seed:03d}.blend"
                butil.save_blend(blend_path, autopack=True)
                meta["blend_file"] = str(blend_path)

        prefix = f"{factory_cls.__name__}_{seed:03d}"
        script_path = dump_logs(
            logger,
            variation_dir,
            prefix,
            metadata=meta if args.metadata else None,
        )
        logger.entries.clear()

        if args.render and script_path:
            _render_clean_script(script_path, variation_dir, args)

    return 0


def _render_clean_script(
    script: Path, output_dir: Path, args: argparse.Namespace
) -> None:
    blend_path = script.with_suffix(".blend")
    if not blend_path.exists():
        return
    bpy.ops.wm.open_mainfile(filepath=str(blend_path))
    scene = bpy.context.scene
    scene.render.resolution_x, scene.render.resolution_y = args.resolution
    if scene.camera is None:
        bpy.ops.object.camera_add(
            location=(3.0, -3.0, 2.0), rotation=(math.radians(75), 0, math.radians(45))
        )
        scene.camera = bpy.context.active_object
    scene.render.filepath = str((output_dir / f"{script.stem}.png").resolve())
    bpy.ops.render.render(write_still=True)


if __name__ == "__main__":
    print("[generate_assets_with_logging] Running as script", sys.argv)
    raise SystemExit(main(sys.argv))
