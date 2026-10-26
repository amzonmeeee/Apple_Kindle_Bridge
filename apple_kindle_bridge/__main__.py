"""Read-only Apple Books inventory and experimental position conversion."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

from .apple import InspectionError, compare, discover, inspect_library


def save_json(path, data):
    path = path.expanduser().resolve()
    if path.exists():
        raise InspectionError(f"Output already exists; choose a new snapshot name: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            temp = Path(handle.name)
            json.dump(data, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
        # Hard linking publishes a complete file and refuses concurrent overwrites.
        os.link(temp, path)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description="Read-only Apple Books inspection; no sync writes.")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("inspect", "export"):
        cmd = commands.add_parser(name)
        cmd.add_argument("--library-db", type=Path)
        cmd.add_argument("--annotations-db", type=Path)
        if name == "export":
            cmd.add_argument("--output", type=Path, required=True)
    diff = commands.add_parser("diff")
    diff.add_argument("before", type=Path)
    diff.add_argument("after", type=Path)
    positions = commands.add_parser("positions", help="Resolve saved Apple CFI candidates against locally available EPUBs")
    positions.add_argument("inventory", type=Path)
    positions.add_argument("--output", type=Path, required=True)
    to_ko = commands.add_parser("to-koreader", help="Convert a CFI and verify its position with real CRengine")
    to_ko.add_argument("epub", type=Path)
    to_ko.add_argument("cfi")
    to_ko.add_argument("--output", type=Path, required=True)
    from_ko = commands.add_parser("from-koreader", help="Convert a verified XPointer to source EPUB CFI")
    from_ko.add_argument("epub", type=Path)
    from_ko.add_argument("xpointer")
    from_ko.add_argument("--end-xpointer")
    from_ko.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command in ("to-koreader", "from-koreader"):
            from .koreader import convert_cfi, convert_xpointer
            result = (convert_cfi(args.epub, args.cfi) if args.command == "to-koreader"
                      else convert_xpointer(args.epub, args.xpointer, args.end_xpointer))
            save_json(args.output, result)
            print(json.dumps({"output": str(args.output.resolve()), "status": result["status"],
                              **{k: result[k] for k in ("xpointer", "cfi", "detail") if k in result}},
                             ensure_ascii=False, indent=2))
            return 0 if result["status"] == "verified_engine_source_position" else 2
        elif args.command == "positions":
            from .epub import inspect_positions
            result = inspect_positions(json.loads(args.inventory.read_text()))
            save_json(args.output, result)
            result = {"output": str(args.output.resolve()), "summary": result["summary"]}
        elif args.command == "diff":
            result = compare(json.loads(args.before.read_text()), json.loads(args.after.read_text()))
        else:
            if args.library_db:
                library, annotations = args.library_db, args.annotations_db
            else:
                library, annotations = discover()
                if args.annotations_db:
                    annotations = args.annotations_db
            result = inspect_library(library.expanduser(), annotations.expanduser() if annotations else None)
            if args.command == "export":
                save_json(args.output, result)
                result = {"output": str(args.output.resolve()), **result["summary"]}
            else:
                result = {"sources": result["sources"], **result["summary"], "limitations": result["limitations"]}
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except (InspectionError, OSError, ValueError, KeyError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
