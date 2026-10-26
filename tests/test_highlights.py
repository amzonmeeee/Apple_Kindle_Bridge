import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from apple_kindle_bridge.apple import InspectionError
from apple_kindle_bridge.highlights import export_highlights
from apple_kindle_bridge.__main__ import save_json


class HighlightExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.library = self.root / 'library.sqlite'
        self.annotations = self.root / 'annotations.sqlite'
        with sqlite3.connect(self.library) as db:
            db.execute('CREATE TABLE ZBKLIBRARYASSET (Z_PK INTEGER PRIMARY KEY, ZASSETID TEXT, ZTITLE TEXT, ZAUTHOR TEXT)')
            db.executemany('INSERT INTO ZBKLIBRARYASSET VALUES (?,?,?,?)',
                           [(1, 'book-a', 'Example', 'Author'), (2, 'book-b', 'Other', 'Author')])
        self.writer = sqlite3.connect(self.annotations)
        self.addCleanup(self.writer.close)
        self.writer.execute('PRAGMA journal_mode=WAL')
        self.writer.execute('PRAGMA wal_autocheckpoint=0')
        self.writer.execute('''CREATE TABLE ZAEANNOTATION (
            Z_PK INTEGER PRIMARY KEY, ZANNOTATIONUUID TEXT, ZANNOTATIONASSETID TEXT,
            ZANNOTATIONTYPE INTEGER, ZANNOTATIONDELETED INTEGER,
            ZANNOTATIONSELECTEDTEXT TEXT, ZANNOTATIONNOTE TEXT, ZANNOTATIONLOCATION TEXT,
            ZANNOTATIONSTYLE INTEGER, ZANNOTATIONISUNDERLINE INTEGER,
            ZANNOTATIONCREATIONDATE REAL, ZANNOTATIONMODIFICATIONDATE REAL,
            ZFUTUREPROOFING5 TEXT)''')
        self.writer.executemany('INSERT INTO ZAEANNOTATION VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)', [
            (1, 'u1', 'book-a', 2, 0, 'A passage 測試', 'A private note', 'epubcfi(/6/2!/4/2/1:0)', 3, 0, 0, 60, None),
            (2, 'u2', 'book-a', 2, 1, 'Deleted passage', None, 'old-cfi', 0, 1, 0, 120, 'Chapter'),
            (3, 'u3', 'book-a', 3, 0, 'Resume context', None, 'resume-cfi', 0, 0, 0, 120, None),
            (4, 'u4', 'book-b', 2, 0, 'Other passage', None, 'other-cfi', 4, 0, 0, 120, 'Chapter'),
        ])
        self.writer.commit()

    def hashes(self):
        return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in (self.library, self.annotations, Path(str(self.annotations) + '-wal'))}

    def test_wal_export_preserves_notes_and_tombstones_without_source_writes(self):
        before = self.hashes()
        result = export_highlights(self.library, self.annotations)
        self.assertEqual(self.hashes(), before)
        self.assertEqual(result['summary']['records'], 3)
        self.assertEqual(result['summary']['deleted'], 1)
        first, deleted, _ = result['highlights']
        self.assertEqual(first['text'], 'A passage 測試')
        self.assertEqual(first['note'], 'A private note')
        self.assertEqual(first['created_at'], '2001-01-01T00:00:00+00:00')
        self.assertEqual(first['origin'], 'unknown')
        self.assertEqual(first['source_issues'], [])
        self.assertFalse(first['target_position_verified'])
        self.assertEqual(deleted['source_issues'], ['source_deleted'])
        self.assertNotIn('Resume context', json.dumps(result))
        target = self.root / 'highlights.json'
        save_json(target, result)
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads(target.read_text()), result)

    def test_explicit_book_filter_does_not_match_titles_or_sql(self):
        result = export_highlights(self.library, self.annotations, 'book-b')
        self.assertEqual([r['uuid'] for r in result['highlights']], ['u4'])
        self.assertEqual(export_highlights(self.library, self.annotations, "' OR 1=1 --")['summary']['records'], 0)

    def test_ambiguous_identity_and_unknown_deletion_are_not_silently_dropped(self):
        self.writer.execute("UPDATE ZAEANNOTATION SET ZANNOTATIONUUID='u1', ZANNOTATIONDELETED=NULL, ZANNOTATIONSELECTEDTEXT=NULL WHERE Z_PK=2")
        self.writer.commit()
        result = export_highlights(self.library, self.annotations, 'book-a')
        self.assertEqual(result['summary']['records'], 2)
        self.assertEqual(result['summary']['without_source_issues'], 0)
        first, second = result['highlights']
        self.assertIn('duplicate_source_identity', first['source_issues'])
        self.assertEqual(second['deletion_state'], 'unknown')
        self.assertIn('missing_selected_text', second['source_issues'])

    def test_changed_required_schema_fails_instead_of_empty_export(self):
        self.writer.execute('ALTER TABLE ZAEANNOTATION RENAME COLUMN ZANNOTATIONTYPE TO CHANGED_TYPE')
        self.writer.commit()
        with self.assertRaisesRegex(InspectionError, 'ZANNOTATIONTYPE'):
            export_highlights(self.library, self.annotations)


if __name__ == '__main__':
    unittest.main()
