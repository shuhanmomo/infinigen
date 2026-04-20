import argparse
import ast
import copy
import importlib
import inspect
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

# Logged factories
from infinigen.assets.building_facade_logged import BuildingFacadeFactoryLogged
from infinigen.assets.building_facade_decor_logic_logged import (
    BuildingFacadeDecorFactoryLogged,
)
from infinigen.assets.building_facade_decor_logic_v2_logged import (
    BuildingFacadeDecorV2FactoryLogged,
)
from infinigen.assets.building_facade_mat_logged import BuildingFacadeMatFactoryLogged
from infinigen.assets.objects.seating.chairs.chair_logged import ChairFactoryLogged
from infinigen.assets.objects.seating.chairs.chair_logged_v2 import (
    ChairFactoryLogged as ChairFactoryLoggedV2,
)


def make_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--factory",
        type=str,
        default="chair",
        choices=[
            "chair",
            "chair_v2",
            "building_facade",
            "building_facade_decor",
            "building_facade_decor_v2",
            "building_facade_mat",
        ],
        help="Which logged factory to run",
    )
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
    parser.add_argument("--output_root", type=Path, default=None)
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


def _factory_spec(factory_name: str):
    """Return (factory_cls, sanitized_script_name, supports_refactored, eval_subdir).

    ``eval_subdir`` is the per-variant folder name where prog_gold_blender.py
    and prog_pred_blender.py go when ``--export_refactored`` is set; ``None``
    when the factory has no refactored exporter.
    """
    if factory_name == "chair":
        return ChairFactoryLogged, "chair_sanitized.py", True, "Chair_infinigen"
    if factory_name == "chair_v2":
        return ChairFactoryLoggedV2, "chair_sanitized.py", True, "Chair_infinigen"
    if factory_name == "building_facade":
        return (
            BuildingFacadeFactoryLogged,
            "building_facade_sanitized.py",
            False,
            None,
        )
    if factory_name == "building_facade_decor":
        return (
            BuildingFacadeDecorFactoryLogged,
            "building_facade_decor_sanitized.py",
            False,
            None,
        )
    if factory_name == "building_facade_decor_v2":
        return (
            BuildingFacadeDecorV2FactoryLogged,
            "building_facade_decor_v2_sanitized.py",
            True,
            "BuildingFacadeDecorV2_infinigen",
        )
    if factory_name == "building_facade_mat":
        return (
            BuildingFacadeMatFactoryLogged,
            "building_facade_mat_sanitized.py",
            True,
            "BuildingFacadeMat_infinigen",
        )
    raise ValueError(f"Unsupported factory {factory_name}")


def generate_one(seed: int, output_root: Path):
    # Prepare scene per variant
    butil.clear_scene()
    scene = bpy.context.scene
    scene.render.filepath = str(output_root)

    # Output folder
    out_dir = output_root / f"variant_{seed:03d}"
    out_dir.mkdir(parents=True, exist_ok=True)

    factory_cls, script_name, supports_refactored, eval_subdir = _factory_spec(
        ARGS.factory
    )

    # Generate asset
    fac = factory_cls(seed)
    with FixedSeed(seed):
        parent = fac.spawn_asset(seed)

    # Write object-name-to-label mapping
    if hasattr(fac, "write_obj_to_label"):
        label_path = fac.write_obj_to_label(str(out_dir))
        print(f"Saved: {label_path}")

    # Save .blend if requested. We also force-save when --export_refactored is
    # set, because the codebank/refactored script pair is meaningless without
    # the matching scene as a visual ground truth for evaluator comparison.
    blend_path = out_dir / "scene.blend"
    save_blend = ARGS.save_blend or ARGS.export_refactored
    if save_blend:
        butil.save_blend(blend_path, autopack=True)

    # Export sanitized script if requested
    if ARGS.export_script:
        script_path = out_dir / script_name
        fac.export_sanitized_script(str(script_path))
        print(f"Saved: {script_path}")

    # Export refactored script for evaluator comparison
    if ARGS.export_refactored and supports_refactored:
        # Create evaluator-compatible structure: variant_{idx}/{subdir}/prog_*.py
        # prog_gold_blender.py = primitive script (sanitized)
        # prog_pred_blender.py = refactored script (helper calls)
        eval_dir = out_dir / eval_subdir
        eval_dir.mkdir(parents=True, exist_ok=True)

        gold_path = eval_dir / "prog_gold_blender.py"
        pred_path = eval_dir / "prog_pred_blender.py"

        # Export primitive as gold
        fac.export_sanitized_script(str(gold_path))
        print(f"Saved: {gold_path}")

        # Export refactored as pred
        fac.export_refactored_script(str(pred_path))
        print(f"Saved: {pred_path}")
    elif ARGS.export_refactored and not supports_refactored:
        print(
            f"Skipping --export_refactored for {ARGS.factory}: refactored export not implemented."
        )

    if save_blend:
        print(f"Saved: {blend_path}")


# --------------------------------------------------------------------------- #
# Codebank extraction: take an original (non-logged) factory class and emit a
# codebank.py whose helper methods have been turned into standalone functions.
# --------------------------------------------------------------------------- #

# Per-factory mapping: factory_name -> (module path, class name, helper-method
# skip set). The skip set lists method names that are NOT helpers (i.e. lifecycle
# / orchestration entry points) and therefore should not appear in the codebank.
_CODEBANK_SOURCES: dict = {
    "chair": (
        "infinigen.assets.objects.seating.chairs.chair",
        "ChairFactory",
        {
            "__init__", "post_init",
            "create_asset", "create_placeholder",
            "spawn_asset", "spawn_placeholder",
            "finalize_assets",
        },
    ),
    "chair_v2": (
        "infinigen.assets.objects.seating.chairs.chair",
        "ChairFactory",
        {
            "__init__", "post_init",
            "create_asset", "create_placeholder",
            "spawn_asset", "spawn_placeholder",
            "finalize_assets",
        },
    ),
    "building_facade": (
        "infinigen.assets.building_facade",
        "BuildingFacadeFactory",
        {
            "__init__",
            "create_asset", "create_placeholder",
            "spawn_asset", "spawn_placeholder",
            "finalize_assets", "write_obj_to_label",
        },
    ),
    "building_facade_decor": (
        "infinigen.assets.building_facade_decor_logic",
        "BuildingFacadeDecorFactory",
        {
            "__init__",
            "create_asset", "create_placeholder",
            "spawn_asset", "spawn_placeholder",
            "finalize_assets", "write_obj_to_label",
        },
    ),
    "building_facade_decor_v2": (
        "infinigen.assets.building_facade_decor_logic_v2",
        "BuildingFacadeDecorV2Factory",
        {
            "__init__",
            "create_asset", "create_placeholder",
            "spawn_asset", "spawn_placeholder",
            "finalize_assets", "write_obj_to_label",
        },
    ),
    "building_facade_mat": (
        "infinigen.assets.building_facade_mat",
        "BuildingFacadeMatFactory",
        {
            "__init__",
            "create_asset", "create_placeholder",
            "spawn_asset", "spawn_placeholder",
            "finalize_assets", "write_obj_to_label",
        },
    ),
}


class _SelfAnalyzer(ast.NodeVisitor):
    """Walks a method body to collect:
    - `self_attrs`: data attributes referenced via `self.X` (excluding intra-
      class method calls)
    - `called_methods`: names of intra-class methods invoked via `self.X(...)`

    The two are used together to compute, for each method, the *transitive*
    set of state it (and its callees) need so the extracted standalone
    functions can forward state when calling each other.
    """

    def __init__(self, method_names: set):
        self._method_names = method_names
        self.self_attrs: set = set()
        self.called_methods: set = set()

    def visit_Call(self, node: ast.Call):
        if (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "self"
            and node.func.attr in self._method_names
        ):
            self.called_methods.add(node.func.attr)
            # Visit args / keywords but skip node.func so we don't also count
            # the method reference as a data attribute.
            for a in node.args:
                self.visit(a)
            for k in node.keywords:
                self.visit(k.value)
            return
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute):
        if isinstance(node.value, ast.Name) and node.value.id == "self":
            attr = node.attr
            if attr not in self._method_names:
                self.self_attrs.add(attr)
        self.generic_visit(node)


class _SelfRewriter(ast.NodeTransformer):
    """Rewrite `self.X` accesses inside a method body.

    - `self.X(...)` (intra-class method call) becomes `<rename[X]>(...)`, and
      we append explicit `kw=kw` forwarding for every state attribute the
      callee needs (computed as `transitive_attrs[X]`). The caller is
      guaranteed to have those names in scope because its own signature
      includes the union of all transitive state.
    - `self.X` (data load) becomes a bare `X` reference.
    - `self.X` (method ref without call) becomes a bare renamed reference;
      no auto-forwarding is possible here so the user must wrap manually.
    """

    def __init__(
        self,
        method_names: set,
        rename: dict,
        transitive_attrs: dict,
    ):
        self._method_names = method_names
        self._rename = rename
        self._transitive_attrs = transitive_attrs

    def visit_Call(self, node: ast.Call):
        if (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "self"
            and node.func.attr in self._method_names
        ):
            attr = node.func.attr
            new_func = ast.copy_location(
                ast.Name(id=self._rename.get(attr, attr), ctx=ast.Load()),
                node.func,
            )
            new_args = [self.visit(copy.deepcopy(a)) for a in node.args]
            already_kw = {k.arg for k in node.keywords if k.arg is not None}
            new_kws = [
                ast.keyword(arg=k.arg, value=self.visit(copy.deepcopy(k.value)))
                for k in node.keywords
            ]
            for state in sorted(self._transitive_attrs.get(attr, set())):
                if state in already_kw:
                    continue
                new_kws.append(ast.keyword(
                    arg=state,
                    value=ast.Name(id=state, ctx=ast.Load()),
                ))
            return ast.copy_location(
                ast.Call(func=new_func, args=new_args, keywords=new_kws),
                node,
            )
        return self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute):
        if isinstance(node.value, ast.Name) and node.value.id == "self":
            attr = node.attr
            if attr in self._method_names:
                return ast.copy_location(
                    ast.Name(id=self._rename.get(attr, attr), ctx=node.ctx),
                    node,
                )
            return ast.copy_location(ast.Name(id=attr, ctx=node.ctx), node)
        return self.generic_visit(node)


def _extract_codebank(source_path: Path, class_name: str, skip: set) -> str:
    """Extract helper methods of `class_name` from `source_path` as standalone
    functions, returning the full codebank.py source text."""
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    # 1. Collect top-level imports verbatim and their bound names (for collision
    #    detection with class method names).
    imports: list = []
    imported_names: set = set()
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            imports.append(node)
            for alias in node.names:
                bound = alias.asname or alias.name
                imported_names.add(bound.split(".")[0])

    # 2. Locate the factory class.
    cls = next(
        (
            n for n in tree.body
            if isinstance(n, ast.ClassDef) and n.name == class_name
        ),
        None,
    )
    if cls is None:
        raise ValueError(f"Class {class_name!r} not found in {source_path}")

    # 3. Inventory class-level statements: methods, plus any class-level
    #    constant assignments to expose as module-level names.
    methods = [n for n in cls.body if isinstance(n, ast.FunctionDef)]
    method_names = {m.name for m in methods}

    class_constants: list = []
    for node in cls.body:
        if isinstance(node, ast.Assign) and all(
            isinstance(t, ast.Name) for t in node.targets
        ):
            class_constants.append(node)

    # 4. Decide rename map: any extracted method whose name shadows an import
    #    gets prefixed with `_m_` so the body's `self.X(...)` rewrite doesn't
    #    accidentally call the imported helper of the same name.
    rename = {
        n: (f"_m_{n}" if n in imported_names else n) for n in method_names
    }

    # 5. Decide which methods to extract.
    def _is_extractable(m: ast.FunctionDef) -> bool:
        if m.name in skip or m.name.startswith("__"):
            return False
        if any(
            isinstance(d, ast.Name) and d.id == "property"
            for d in m.decorator_list
        ):
            return False
        return True

    extractable = [m for m in methods if _is_extractable(m)]

    # 6. Pre-pass: per-method direct state + intra-class call graph.
    direct_attrs: dict = {}
    called: dict = {}
    for m in extractable:
        analyzer = _SelfAnalyzer(method_names)
        for s in m.body:
            analyzer.visit(s)
        direct_attrs[m.name] = analyzer.self_attrs
        called[m.name] = analyzer.called_methods

    # 7. Fixed-point closure: a method's transitive state is its own direct
    #    state plus the transitive state of every intra-class method it calls.
    transitive_attrs: dict = {n: set(s) for n, s in direct_attrs.items()}
    changed = True
    while changed:
        changed = False
        for m_name, callees in called.items():
            for c_name in callees:
                if c_name not in transitive_attrs:
                    continue
                before = len(transitive_attrs[m_name])
                transitive_attrs[m_name] |= transitive_attrs[c_name]
                if len(transitive_attrs[m_name]) > before:
                    changed = True

    # 8. Emit pass: rewrite each method body and assemble its new signature.
    extracted: list = []
    for m in extractable:
        extracted.append(_convert_method(
            m, method_names, rename, transitive_attrs,
        ))

    if not extracted:
        raise ValueError(
            f"No extractable helper methods found on {class_name!r}; "
            f"skip set may be too broad."
        )

    # 6. Reassemble: imports + class constants + extracted functions.
    body = list(imports) + list(class_constants) + extracted
    new_module = ast.Module(body=body, type_ignores=[])
    ast.fix_missing_locations(new_module)
    code = ast.unparse(new_module)

    header = (
        f'"""Codebank for {class_name}.\n\n'
        f"Auto-generated from {source_path.as_posix()} by\n"
        f"infinigen_examples/generate_logged_assets.py. Helper methods have\n"
        f"been converted to standalone functions: `self` is dropped, data\n"
        f"attributes (self.X) become keyword-only parameters, and intra-class\n"
        f"method calls (self.foo(...)) are rewritten to bare calls.\n"
        f'"""\n\n'
    )
    return header + code + "\n"


def _convert_method(
    method: ast.FunctionDef,
    method_names: set,
    rename: dict,
    transitive_attrs: dict,
) -> ast.FunctionDef:
    """Convert one `def m(self, ...)` method into a standalone function.

    The new signature is `<original positional args minus self>` plus a kwarg-
    only block of every state attribute the method *transitively* needs (its
    own self.X reads union those of every helper it calls). Body rewrites are
    performed by `_SelfRewriter`, which also forwards state to intra-class
    calls.
    """
    decorators = [
        d for d in method.decorator_list
        if not (
            isinstance(d, ast.Name) and d.id in {"staticmethod", "classmethod"}
        )
    ]

    new_args = copy.deepcopy(method.args)
    if new_args.args and new_args.args[0].arg in {"self", "cls"}:
        new_args.args = new_args.args[1:]

    rewriter = _SelfRewriter(method_names, rename, transitive_attrs)
    new_body = [rewriter.visit(copy.deepcopy(s)) for s in method.body]

    # Don't double-add a kwarg if the original signature already has it as a
    # positional parameter (rare but possible for facade-style helpers).
    existing = {a.arg for a in new_args.args} | {a.arg for a in new_args.kwonlyargs}
    for name in sorted(transitive_attrs.get(method.name, set())):
        if name in existing:
            continue
        new_args.kwonlyargs.append(ast.arg(arg=name, annotation=None))
        new_args.kw_defaults.append(None)

    return ast.FunctionDef(
        name=rename.get(method.name, method.name),
        args=new_args,
        body=new_body,
        decorator_list=decorators,
        returns=method.returns,
        type_comment=None,
    )


def export_codebank(output_path: Path, factory_name: str):
    """Generate a codebank.py for the given factory by extracting helper
    methods from the original (non-logged) generator class via AST."""
    if factory_name not in _CODEBANK_SOURCES:
        raise ValueError(
            f"No codebank source registered for factory {factory_name!r}. "
            f"Add an entry to _CODEBANK_SOURCES."
        )
    module_path, class_name, skip = _CODEBANK_SOURCES[factory_name]
    module = importlib.import_module(module_path)
    source_path = Path(inspect.getfile(module))
    code = _extract_codebank(source_path, class_name, skip)
    output_path.write_text(code, encoding="utf-8")
    print(f"Saved: {output_path}")


def main(args):
    if args.output_root is None:
        defaults = {
            "chair": "outputs/chairs",
            "chair_v2": "outputs/chairs_v2",
            "building_facade": "outputs/building_facade_logged",
            "building_facade_decor": "outputs/building_facade_decor_logged",
            "building_facade_decor_v2": "outputs/building_facade_decor_v2_logged",
            "building_facade_mat": "outputs/building_facade_mat_logged",
        }
        args.output_root = Path(defaults.get(args.factory, "outputs/assets"))

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
        export_codebank(codebank_path, args.factory)

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
