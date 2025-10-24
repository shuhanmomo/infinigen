import argparse
import sys
from pathlib import Path

import bpy


def parse_args(argv=None) -> argparse.Namespace:
    if argv is None:
        argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    else:
        argv = []

    p = argparse.ArgumentParser(
        description="Run a sanitized Infinigen script and save a .blend"
    )
    p.add_argument(
        "--script",
        default=None,
        help="Path to sanitized script (e.g., outputs/chairs/variant_041/Chair_sanitized.py)",
    )
    p.add_argument(
        "--dir",
        default=None,
        help="Optional directory to batch-replay all sanitized scripts (recursively)",
    )
    p.add_argument(
        "--pattern",
        default="Chair_sanitized.py",
        help="Filename pattern to search under --dir (default: Chair_sanitized.py)",
    )
    p.add_argument(
        "--output",
        default=None,
        help="Optional path for the resulting .blend (default: scene_replay.blend beside the script)",
    )
    p.add_argument(
        "--no-clear",
        action="store_true",
        help="Do not clear scene before running the sanitized script",
    )
    return p.parse_args(argv)


def run_sanitized(
    script_path: Path, output_blend: Path, clear_scene: bool = True
) -> None:
    # Ensure repo root is on sys.path so imports in sanitized scripts resolve
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    if clear_scene:
        try:
            # Lazy import to avoid hard dependency
            from infinigen.core.util import blender as butil  # type: ignore

            butil.clear_scene()
        except Exception:
            # Fallback: brute-clear
            for obj in list(bpy.data.objects):
                bpy.data.objects.remove(obj, do_unlink=True)

    # Execute the sanitized script in its own __main__ context
    import runpy

    runpy.run_path(str(script_path), run_name="__main__")

    # Save the result
    output_blend.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(output_blend))


def main() -> int:
    args = parse_args()
    ran_any = False

    # Batch mode
    if args.dir:
        root = Path(args.dir).resolve()
        if not root.exists():
            raise FileNotFoundError(f"Directory not found: {root}")
        scripts = sorted(root.rglob(args.pattern))
        for sp in scripts:
            outp = sp.parent / "scene_replay.blend"
            print(f"[run_sanitized] Running: {sp}")
            run_sanitized(sp, outp, clear_scene=not args.no_clear)
            print(f"[run_sanitized] Saved: {outp}")
            ran_any = True

    # Single-file mode
    if args.script:
        script_path = Path(args.script).resolve()
        if not script_path.exists():
            raise FileNotFoundError(f"Sanitized script not found: {script_path}")
        if args.output:
            output_blend = Path(args.output).resolve()
        else:
            output_blend = script_path.parent / "scene_replay.blend"
        print(f"[run_sanitized] Running: {script_path}")
        run_sanitized(script_path, output_blend, clear_scene=not args.no_clear)
        print(f"[run_sanitized] Saved: {output_blend}")
        ran_any = True

    if not ran_any:
        print("[run_sanitized] Nothing to do (no --script and no --dir matches)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
