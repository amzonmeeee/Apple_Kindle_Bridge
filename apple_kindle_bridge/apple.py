"""Inspect Apple Books without changing its databases or inferring reader positions."""
from __future__ import annotations

import contextlib
from datetime import datetime, timedelta, timezone
import hashlib
import math
from pathlib import Path
import plistlib
import sqlite3
import time
from urllib.parse import unquote, urlparse


class InspectionError(Exception):
    pass


LIBRARY_FIELDS = (
    "Z_PK", "ZASSETID", "ZASSETGUID", "ZEPUBID", "ZTITLE", "ZAUTHOR", "ZPATH",
    "ZCONTENTTYPE", "ZSTATE", "ZISHIDDEN", "ZREADINGPROGRESS",
    "ZBOOKHIGHWATERMARKPROGRESS", "ZISFINISHED", "ZLASTOPENDATE",
    "ZLASTENGAGEDDATE", "ZMODIFICATIONDATE", "ZLOCATIONSERVERMAXMODIFICATIONDATE",
)
LOCATION_FIELDS = (
    "Z_PK", "ZANNOTATIONASSETID", "ZANNOTATIONTYPE", "ZANNOTATIONDELETED",
    "ZANNOTATIONLOCATION", "ZANNOTATIONMODIFICATIONDATE", "ZANNOTATIONUUID",
    "ZFUTUREPROOFING8", "ZFUTUREPROOFING10", "ZPLUSERDATA",
)


def discover(home: Path | None = None) -> tuple[Path, Path | None]:
    base = (home or Path.home()) / "Library/Containers/com.apple.iBooksX/Data/Documents"

    def find(folder: str, required: bool) -> Path | None:
        found = sorted((base / folder).glob("*.sqlite"))
        if len(found) > 1:
            raise InspectionError(f"Multiple {folder} databases; choose an explicit path: " + ", ".join(map(str, found)))
        if not found and required:
            raise InspectionError(f"No Apple Books database found under {base / folder}")
        return found[0] if found else None

    return find("BKLibrary", True), find("AEAnnotation", False)


@contextlib.contextmanager
def snapshot(source: Path, timeout: float = 10):
    """SQLite backup includes committed WAL data; never use immutable=1 on a live DB."""
    if not source.is_file():
        raise InspectionError(f"Database not found: {source}")
    src = db = None
    deadline = time.monotonic() + timeout

    def progress(_status, _remaining, _total):
        if time.monotonic() > deadline:
            raise InspectionError(f"Snapshot timed out: {source}")

    try:
        src = sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
        src.execute("PRAGMA query_only=ON")
        db = sqlite3.connect(":memory:")
        src.backup(db, pages=128, progress=progress, sleep=0.05)
        src.close()
        src = None
        integrity = [row[0] for row in db.execute("PRAGMA quick_check")]
        if integrity != ["ok"]:
            raise InspectionError(f"SQLite quick_check failed for {source}: {integrity}")
        db.execute("PRAGMA query_only=ON")
        db.row_factory = sqlite3.Row
        yield db
    except sqlite3.Error as exc:
        raise InspectionError(f"Cannot read {source}: {exc}") from exc
    finally:
        if src is not None:
            src.close()
        if db is not None:
            db.close()


def read_rows(db, table, wanted, required):
    # Names are fixed by this module; values never become SQL identifiers.
    columns = {row["name"]: row["type"] for row in db.execute(f'PRAGMA table_info("{table}")')}
    if not columns:
        raise InspectionError(f"Required table missing: {table}")
    missing = set(required) - columns.keys()
    if missing:
        raise InspectionError(f"Required columns missing in {table}: {', '.join(sorted(missing))}")
    selected = [name for name in wanted if name in columns]
    sql = "SELECT " + ", ".join(f'"{name}"' for name in selected) + f' FROM "{table}" ORDER BY "Z_PK"'
    rows = [dict(row) for row in db.execute(sql)]
    return rows, {"table": table, "columns": columns, "missing_optional_columns": sorted(set(wanted) - columns.keys())}


def apple_date(value):
    if value is None or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    try:
        return (datetime(2001, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=value)).isoformat()
    except (ValueError, OverflowError):
        return None


def progress_value(value):
    valid = isinstance(value, (int, float)) and math.isfinite(value) and 0 <= value <= 1
    raw = repr(value) if isinstance(value, float) and not math.isfinite(value) else value
    return {"fraction": raw, "valid_fraction": valid}


def file_status(raw):
    if not raw:
        return {"path": None, "status": "no_path"}
    if not isinstance(raw, str):
        return {"path": None, "status": "unsupported_path_value"}
    if raw.startswith("file:"):
        parsed = urlparse(raw)
        if parsed.netloc not in ("", "localhost"):
            return {"path": raw, "status": "unsupported_file_host"}
        raw = unquote(parsed.path)
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        return {"path": raw, "status": "relative_path_unresolved"}
    try:
        kind = "directory" if candidate.is_dir() else "file" if candidate.is_file() else "missing"
        return {"path": str(candidate), "status": kind, "extension": candidate.suffix.lower()}
    except OSError as exc:
        return {"path": raw, "status": "unreadable", "error": str(exc)}


def page_data_evidence(blob):
    """Expose observed page metadata, never arbitrary archived context text."""
    if blob is None:
        return None
    if not isinstance(blob, bytes):
        return {"status": "unexpected_value_type"}
    result = {"byte_count": len(blob), "sha256": hashlib.sha256(blob).hexdigest()}
    if len(blob) > 1024 * 1024:
        return {**result, "status": "too_large_to_parse"}
    try:
        decoded = plistlib.loads(blob)
    except (ValueError, TypeError, OverflowError, plistlib.InvalidFileException):
        return {**result, "status": "unparsed"}
    if isinstance(decoded, dict) and decoded.get("class") == "BKPageLocation":
        result["status"] = "page_location_candidate"
        for key in ("pageOffset",):
            value = decoded.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                result[key + "_raw"] = value
        parent = decoded.get("super")
        if isinstance(parent, dict):
            value = parent.get("ordinal")
            if isinstance(value, int) and not isinstance(value, bool):
                result["ordinal_raw"] = value
    else:
        result["status"] = "unparsed_archive"
    return result


def reading_evidence(record):
    return {
        "row_id": record["Z_PK"], "type_raw": record.get("ZANNOTATIONTYPE"),
        "deleted_raw": record.get("ZANNOTATIONDELETED"),
        "location_raw": record.get("ZANNOTATIONLOCATION"),
        "fraction_raw": record.get("ZFUTUREPROOFING10"),
        "furthest_fraction_raw": record.get("ZFUTUREPROOFING8"),
        "page_data": page_data_evidence(record.get("ZPLUSERDATA")),
        "modified_at_raw": record.get("ZANNOTATIONMODIFICATIONDATE"),
        "modified_at": apple_date(record.get("ZANNOTATIONMODIFICATIONDATE")),
        "role": "apple_auto_bookmark_candidate",
        "resume_behavior_verified": False,
    }


def inspect_library(library: Path, annotations: Path | None = None):
    captured = datetime.now(timezone.utc).isoformat()
    with snapshot(library) as db:
        rows, library_schema = read_rows(db, "ZBKLIBRARYASSET", LIBRARY_FIELDS, ("Z_PK", "ZASSETID", "ZTITLE", "ZREADINGPROGRESS"))
    library_schema["snapshot_started_at"] = captured
    library_schema["snapshot_finished_at"] = datetime.now(timezone.utc).isoformat()
    library_schema["quick_check"] = "ok"
    location_rows = []
    annotation_schema = None
    if annotations:
        annotation_started = datetime.now(timezone.utc).isoformat()
        with snapshot(annotations) as db:
            location_rows, annotation_schema = read_rows(db, "ZAEANNOTATION", LOCATION_FIELDS, ("Z_PK", "ZANNOTATIONASSETID", "ZANNOTATIONLOCATION"))
        annotation_schema["snapshot_started_at"] = annotation_started
        annotation_schema["snapshot_finished_at"] = datetime.now(timezone.utc).isoformat()
        annotation_schema["quick_check"] = "ok"

    locations_by_asset = {}
    reading_by_asset = {}
    for row in location_rows:
        if row.get("ZANNOTATIONTYPE") == 3:
            # Type 3 is the observed automatic bookmark in py-apple-books.
            # Keep every record, including NULL anchors and deleted records.
            reading_by_asset.setdefault(row.get("ZANNOTATIONASSETID"), []).append(reading_evidence(row))
        if row.get("ZANNOTATIONLOCATION") is not None:
            locations_by_asset.setdefault(row.get("ZANNOTATIONASSETID"), []).append({
                "row_id": row["Z_PK"], "annotation_uuid": row.get("ZANNOTATIONUUID"),
                "type_raw": row.get("ZANNOTATIONTYPE"), "deleted_raw": row.get("ZANNOTATIONDELETED"),
                "location_raw": row["ZANNOTATIONLOCATION"],
                "modified_at": apple_date(row.get("ZANNOTATIONMODIFICATIONDATE")),
                "modified_at_raw": row.get("ZANNOTATIONMODIFICATIONDATE"),
                "role": "unclassified_annotation_location",
            })

    books = []
    counts = {}
    for row in rows:
        asset_id = row["ZASSETID"]
        if asset_id:
            counts[asset_id] = counts.get(asset_id, 0) + 1
        books.append({
            "row_id": row["Z_PK"], "asset_id": asset_id, "asset_guid": row.get("ZASSETGUID"),
            "epub_id": row.get("ZEPUBID"), "title": row["ZTITLE"], "author": row.get("ZAUTHOR"),
            "file": file_status(row.get("ZPATH")), "path_raw": row.get("ZPATH"),
            "content_type_raw": row.get("ZCONTENTTYPE"), "state_raw": row.get("ZSTATE"),
            "hidden_raw": row.get("ZISHIDDEN"), "finished_raw": row.get("ZISFINISHED"),
            "progress": progress_value(row["ZREADINGPROGRESS"]),
            "high_watermark": progress_value(row.get("ZBOOKHIGHWATERMARKPROGRESS")),
            "timestamps": {key: {"raw": row.get(key), "utc": apple_date(row.get(key))}
                           for key in ("ZLASTOPENDATE", "ZLASTENGAGEDDATE", "ZMODIFICATIONDATE", "ZLOCATIONSERVERMAXMODIFICATIONDATE")},
            "location_candidates": locations_by_asset.get(asset_id, []) if asset_id else [],
            "reading_position_records": reading_by_asset.get(asset_id, []) if asset_id else [],
            "resume_location_verified": False,
        })
    known_ids = {book["asset_id"] for book in books if book["asset_id"]}
    return {
        "schema_version": 1, "captured_at": captured, "completed_at": datetime.now(timezone.utc).isoformat(),
        "read_only": True,
        "sources": {"library": str(library.resolve()), "annotations": str(annotations.resolve()) if annotations else None},
        "source_schemas": {"library": library_schema, "annotations": annotation_schema},
        "position_interpretation_reference": "https://github.com/vgnshiyer/py-apple-books/blob/main/py_apple_books/models/annotation.py",
        "limitations": [
            "Each database is consistent separately; these are not an atomic cross-database snapshot.",
            "Annotation locations are candidates, not verified current resume positions; deleted rows stay labelled.",
            "File existence does not establish complete local download, DRM status, or readability.",
            "No database writes, location conversion, device transfer, or iCloud propagation is performed.",
        ],
        "summary": {
            "books": len(books),
            "books_with_progress": sum(b["progress"]["valid_fraction"] and b["progress"]["fraction"] > 0 for b in books),
            "finished": sum(b["finished_raw"] == 1 for b in books),
            "local_path_exists": sum(b["file"]["status"] in ("file", "directory") for b in books),
            "books_with_location_candidates": sum(bool(b["location_candidates"]) for b in books),
            "books_with_auto_bookmark_candidates": sum(any(r["deleted_raw"] != 1 for r in b["reading_position_records"]) for b in books),
            "annotation_rows": len(location_rows),
            "unmatched_annotation_rows": sum(row.get("ZANNOTATIONASSETID") not in known_ids for row in location_rows),
            "missing_asset_ids": sum(not b["asset_id"] for b in books),
            "duplicate_asset_ids": sorted(key for key, count in counts.items() if count > 1),
            "invalid_progress_values": sum(b["progress"]["fraction"] is not None and not b["progress"]["valid_fraction"] for b in books),
        },
        "books": books,
    }


def compare(before, after):
    def index(data):
        if data.get("schema_version") != 1:
            raise InspectionError("Unsupported snapshot schema_version")
        result = {}
        for book in data["books"]:
            key = book["asset_id"]
            if not key or key in result:
                raise InspectionError("Cannot compare snapshots with missing or duplicate asset IDs")
            result[key] = book
        return result

    old, new = index(before), index(after)
    tracked = ("progress", "high_watermark", "finished_raw", "location_candidates", "reading_position_records", "timestamps", "file")
    changes = []
    for key in sorted(old.keys() & new.keys()):
        delta = {field: {"before": old[key].get(field), "after": new[key].get(field)}
                 for field in tracked if old[key].get(field) != new[key].get(field)}
        if delta:
            changes.append({"asset_id": key, "title": new[key].get("title"), "changes": delta})
    return {"added": sorted(new.keys() - old.keys()), "removed": sorted(old.keys() - new.keys()), "changed": changes}
