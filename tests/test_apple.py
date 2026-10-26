import hashlib
import json
from pathlib import Path
import plistlib
import sqlite3
import tempfile
import unittest

from apple_kindle_bridge.apple import InspectionError, apple_date, compare, discover, inspect_library, page_data_evidence, snapshot
from apple_kindle_bridge.__main__ import save_json


class AppleBooksTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.library = self.root / "library.sqlite"
        self.writer = sqlite3.connect(self.library)
        self.writer.execute("PRAGMA journal_mode=WAL")
        self.writer.execute("PRAGMA wal_autocheckpoint=0")
        self.writer.execute("CREATE TABLE ZBKLIBRARYASSET (Z_PK INTEGER PRIMARY KEY, ZASSETID TEXT, ZTITLE TEXT, ZREADINGPROGRESS REAL, ZBOOKHIGHWATERMARKPROGRESS REAL, ZPATH TEXT, ZISFINISHED INTEGER, ZISHIDDEN INTEGER)")
        self.epub = self.root / "expanded book.epub"
        self.epub.mkdir()
        self.writer.execute("INSERT INTO ZBKLIBRARYASSET VALUES (1,'book-1','Example',0.4,0.8,?,0,0)", (self.epub.as_uri(),))
        self.writer.commit()

    def tearDown(self):
        self.writer.close()
        self.directory.cleanup()

    def source_digests(self):
        return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (self.library, Path(str(self.library) + "-wal"))}

    def test_live_wal_is_included_and_source_unchanged(self):
        before = self.source_digests()
        result = inspect_library(self.library)
        self.assertEqual(result["summary"]["books"], 1)
        self.assertEqual(result["books"][0]["progress"]["fraction"], 0.4)
        self.assertEqual(result["books"][0]["high_watermark"]["fraction"], 0.8)
        self.assertEqual(result["books"][0]["file"]["status"], "directory")
        self.assertEqual(self.source_digests(), before)

    def test_snapshot_is_query_only(self):
        with snapshot(self.library) as db:
            with self.assertRaises(sqlite3.OperationalError):
                db.execute("DELETE FROM ZBKLIBRARYASSET")
        self.assertEqual(self.writer.execute("SELECT COUNT(*) FROM ZBKLIBRARYASSET").fetchone()[0], 1)

    def test_missing_database_is_not_created(self):
        missing = self.root / "missing.sqlite"
        with self.assertRaises(InspectionError):
            inspect_library(missing)
        self.assertFalse(missing.exists())

    def test_schema_drift_fails_clearly(self):
        self.writer.execute("ALTER TABLE ZBKLIBRARYASSET RENAME COLUMN ZREADINGPROGRESS TO RENAMED")
        self.writer.commit()
        with self.assertRaisesRegex(InspectionError, "ZREADINGPROGRESS"):
            inspect_library(self.library)

    def test_optional_columns_and_annotations_are_explicit(self):
        result = inspect_library(self.library)
        self.assertIn("ZEPUBID", result["source_schemas"]["library"]["missing_optional_columns"])
        self.assertIsNone(result["source_schemas"]["annotations"])
        self.assertEqual(result["books"][0]["location_candidates"], [])

    def test_annotations_are_not_claimed_as_current_positions(self):
        annotations = self.root / "annotations.sqlite"
        db = sqlite3.connect(annotations)
        db.execute("CREATE TABLE ZAEANNOTATION (Z_PK INTEGER PRIMARY KEY, ZANNOTATIONASSETID TEXT, ZANNOTATIONLOCATION TEXT, ZANNOTATIONTYPE INTEGER, ZANNOTATIONDELETED INTEGER)")
        db.executemany("INSERT INTO ZAEANNOTATION VALUES (?,?,?,?,?)", [
            (1, "book-1", "epubcfi(/6/2!/4/2:0)", 3, 0),
            (2, "book-1", "old-position", 1, 1),
            (3, "orphan", "unmatched-position", 0, 0),
        ])
        db.commit()
        db.close()
        result = inspect_library(self.library, annotations)
        book = result["books"][0]
        self.assertFalse(book["resume_location_verified"])
        self.assertEqual(book["location_candidates"][1]["deleted_raw"], 1)
        self.assertTrue(all(row["role"] == "unclassified_annotation_location" for row in book["location_candidates"]))
        self.assertEqual(result["summary"]["unmatched_annotation_rows"], 1)

    def test_auto_bookmark_without_cfi_is_retained(self):
        annotations = self.root / "annotations.sqlite"
        db = sqlite3.connect(annotations)
        db.execute("CREATE TABLE ZAEANNOTATION (Z_PK INTEGER PRIMARY KEY, ZANNOTATIONASSETID TEXT, ZANNOTATIONLOCATION TEXT, ZANNOTATIONTYPE INTEGER, ZANNOTATIONDELETED INTEGER, ZFUTUREPROOFING10 TEXT, ZPLUSERDATA BLOB)")
        blob = plistlib.dumps({"class": "BKPageLocation", "pageOffset": 13, "super": {"ordinal": 0, "class": "BKLocation"}})
        db.execute("INSERT INTO ZAEANNOTATION VALUES (1,'book-1',NULL,3,0,'0.2',?)", (blob,))
        db.commit()
        db.close()
        result = inspect_library(self.library, annotations)
        book = result["books"][0]
        self.assertEqual(book["location_candidates"], [])
        evidence = book["reading_position_records"][0]
        self.assertIsNone(evidence["location_raw"])
        self.assertEqual(evidence["fraction_raw"], "0.2")
        self.assertEqual(evidence["page_data"]["pageOffset_raw"], 13)
        self.assertFalse(evidence["resume_behavior_verified"])
        self.assertEqual(result["summary"]["books_with_auto_bookmark_candidates"], 1)
        self.assertEqual(result["source_schemas"]["annotations"]["quick_check"], "ok")

    def test_archived_context_text_is_not_exported(self):
        blob = plistlib.dumps({"$archiver": "NSKeyedArchiver", "$objects": ["private excerpt"]})
        result = page_data_evidence(blob)
        self.assertEqual(result["status"], "unparsed_archive")
        self.assertNotIn("private excerpt", json.dumps(result))
        self.assertEqual(page_data_evidence(b"not a plist")["status"], "unparsed")

    def test_diff_retains_backwards_reading_progress(self):
        before = inspect_library(self.library)
        self.writer.execute("UPDATE ZBKLIBRARYASSET SET ZREADINGPROGRESS=0.2")
        self.writer.commit()
        after = inspect_library(self.library)
        delta = compare(before, after)["changed"][0]["changes"]
        self.assertEqual(delta["progress"]["after"]["fraction"], 0.2)
        self.assertNotIn("high_watermark", delta)
        self.assertEqual(compare(after, after)["changed"], [])

    def test_duplicate_ids_are_reported_not_silently_merged(self):
        self.writer.execute("INSERT INTO ZBKLIBRARYASSET (Z_PK,ZASSETID,ZTITLE,ZREADINGPROGRESS) VALUES (2,'book-1','Duplicate',0.5)")
        self.writer.commit()
        result = inspect_library(self.library)
        self.assertEqual(result["summary"]["duplicate_asset_ids"], ["book-1"])
        with self.assertRaisesRegex(InspectionError, "duplicate"):
            compare(result, result)

    def test_ambiguous_discovery_refuses_to_guess(self):
        folder = self.root / "Library/Containers/com.apple.iBooksX/Data/Documents/BKLibrary"
        folder.mkdir(parents=True)
        (folder / "one.sqlite").touch()
        (folder / "two.sqlite").touch()
        with self.assertRaisesRegex(InspectionError, "Multiple"):
            discover(self.root)

    def test_export_is_private_and_refuses_overwrite(self):
        target = self.root / "snapshot.json"
        save_json(target, {"check": "測試"})
        self.assertEqual(json.loads(target.read_text()), {"check": "測試"})
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(InspectionError):
            save_json(target, {"replacement": True})
        self.assertEqual(json.loads(target.read_text()), {"check": "測試"})

    def test_invalid_progress_is_reported_without_clamping(self):
        self.writer.execute("UPDATE ZBKLIBRARYASSET SET ZREADINGPROGRESS=1.2")
        self.writer.commit()
        result = inspect_library(self.library)
        self.assertEqual(result["summary"]["invalid_progress_values"], 1)
        self.assertEqual(result["books"][0]["progress"]["fraction"], 1.2)

    def test_apple_epoch_is_not_unix_epoch(self):
        self.assertEqual(apple_date(0), "2001-01-01T00:00:00+00:00")
        self.assertIsNone(apple_date(float("inf")))


if __name__ == "__main__":
    unittest.main()
