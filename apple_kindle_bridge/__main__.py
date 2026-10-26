"""Apple Books inspection, position conversion, and explicit highlight imports."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

from .apple import InspectionError, compare, discover, inspect_library
from .epub import LocationError


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
    parser = argparse.ArgumentParser(description="Apple Books bridge; native highlight writes require --apply.")
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
    for name in ("kindle-highlights", "apple-highlights"):
        native = commands.add_parser(name, help="Transfer one book's highlights through the native apps")
        native.add_argument("--config", type=Path, default=Path('.runtime/native.json'))
        native.add_argument("--asset-id", required=True)
        native.add_argument("--kindle-book-id", required=True)
        if name == "kindle-highlights":
            native.add_argument("--annotation-uuid")
        native.add_argument("--backup-dir", type=Path, default=Path('state/native-backups'))
        native.add_argument("--apply", action="store_true")
        native.add_argument("--output", type=Path, required=True)
    highlights = commands.add_parser("highlights-export", help="Export private Apple Books highlights and notes without reader writes")
    highlights.add_argument("--library-db", type=Path)
    highlights.add_argument("--annotations-db", type=Path)
    highlights.add_argument("--asset-id")
    highlights.add_argument("--output", type=Path, required=True)
    highlight_plan = commands.add_parser("highlights-plan", help="Preview one book's highlight ranges for KOReader without reader writes")
    highlight_plan.add_argument("export", type=Path)
    highlight_plan.add_argument("epub", type=Path)
    highlight_plan.add_argument("--asset-id", required=True)
    highlight_plan.add_argument("--reader-file", type=Path, required=True)
    highlight_plan.add_argument("--output", type=Path, required=True)
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
    ko_file = commands.add_parser("kosync-document", help="Prepare a private EPUB copy and its KOReader binary key")
    ko_file.add_argument("epub", type=Path)
    ko_file.add_argument("--output", type=Path, required=True)
    ko_pull = commands.add_parser("kosync-pull", help="Read the existing KOReader progress service and verify its position")
    ko_pull.add_argument("epub", type=Path)
    ko_pull.add_argument("--reader-file", type=Path, required=True)
    ko_pull.add_argument("--dom-version", type=int, required=True)
    ko_pull.add_argument("--server")
    ko_pull.add_argument("--output", type=Path, required=True)
    for name in ("sync-baseline", "sync-plan", "sync-check"):
        cmd = commands.add_parser(name, help="Reconcile verified positions without reader writes")
        cmd.add_argument("apple", type=Path)
        cmd.add_argument("koreader", type=Path)
        cmd.add_argument("--output", type=Path, required=True)
        if name == "sync-plan":
            cmd.add_argument("--baseline", type=Path)
            cmd.add_argument("--prefer", choices=("apple", "koreader"))
        elif name == "sync-check":
            cmd.add_argument("--plan", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command in ("kindle-highlights", "apple-highlights"):
            if args.output.expanduser().exists():
                raise InspectionError("Output already exists; choose a new report name before importing")
            if args.command == "kindle-highlights":
                from .native_highlights import transfer
                result = transfer(args.config, args.asset_id, args.kindle_book_id,
                                  args.backup_dir, args.apply, args.annotation_uuid)
            else:
                from .native_reverse import transfer
                result = transfer(args.config, args.asset_id, args.kindle_book_id,
                                  args.backup_dir, args.apply)
            save_json(args.output, result)
            print(json.dumps({"output": str(args.output.resolve()), **result['summary'],
                              "write_performed": result['write_performed'],
                              "inserted_rows": result.get('inserted_rows', 0)}, indent=2))
            return 2 if result['summary'].get('refused') else 0
        elif args.command == "highlights-plan":
            from .highlight_plan import preview_highlights
            result = preview_highlights(json.loads(args.export.read_text()), args.asset_id,
                                        args.epub, args.reader_file)
            save_json(args.output, result)
            print(json.dumps({"output": str(args.output.resolve()), **result['summary']}, indent=2))
            return 2 if result['summary']['refused'] else 0
        elif args.command == "highlights-export":
            from .highlights import export_highlights
            if args.library_db:
                library, annotations = args.library_db, args.annotations_db
            else:
                library, annotations = discover()
                annotations = args.annotations_db or annotations
            if annotations is None:
                raise InspectionError("Supply --annotations-db or use Apple Books database discovery")
            result = export_highlights(library.expanduser(), annotations.expanduser(), args.asset_id)
            save_json(args.output, result)
            print(json.dumps({"output": str(args.output.resolve()), **result['summary']}, indent=2))
            return 0
        elif args.command in ("kosync-document", "kosync-pull"):
            from .kosync import document, pull
            result = (document(args.epub) if args.command == "kosync-document"
                      else pull(args.epub, args.reader_file, args.dom_version, args.server))
            save_json(args.output, result)
            print(json.dumps({"output": str(args.output.resolve()),
                              **{k: result[k] for k in ("kind", "status", "document", "reader_file") if k in result}},
                             ensure_ascii=False, indent=2))
            return 0 if args.command == "kosync-document" or result['status'] == 'verified_engine_source_position' else 2
        elif args.command in ("sync-baseline", "sync-plan", "sync-check"):
            from .sync import baseline, plan, check_plan
            apple, koreader = json.loads(args.apple.read_text()), json.loads(args.koreader.read_text())
            if args.command == "sync-baseline":
                result = baseline(apple, koreader)
            elif args.command == "sync-plan":
                common = json.loads(args.baseline.read_text()) if args.baseline else None
                result = plan(apple, koreader, common, args.prefer)
            else:
                result = check_plan(json.loads(args.plan.read_text()), apple, koreader)
            save_json(args.output, result)
            print(json.dumps({"output": str(args.output.resolve()),
                              **{k: result[k] for k in ("kind", "action", "reason", "status") if k in result}},
                             ensure_ascii=False, indent=2))
            return 2 if result.get("action") in ("conflict", "choose_initial_source") else 0
        elif args.command in ("to-koreader", "from-koreader"):
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
    except (InspectionError, LocationError, OSError, ValueError, KeyError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
