import sqlite3
import unittest
from apple_kindle_bridge.apple_position import bookmark, write_bookmark
from apple_kindle_bridge.native_position import codepoint_offset, exact_index, unique_start


class PositionWriteTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.db.row_factory = sqlite3.Row
        self.db.execute('CREATE TABLE ZAEANNOTATION (Z_PK INTEGER PRIMARY KEY, Z_OPT INTEGER, '
                        'ZANNOTATIONUUID TEXT,ZANNOTATIONLOCATION TEXT,ZANNOTATIONMODIFICATIONDATE REAL,'
                        'ZFUTUREPROOFING8 TEXT,ZFUTUREPROOFING10 TEXT,ZPLUSERDATA BLOB,'
                        'ZANNOTATIONASSETID TEXT,ZANNOTATIONTYPE INTEGER,ZANNOTATIONDELETED INTEGER,'
                        'ZFUTUREPROOFING6 TEXT,ZFUTUREPROOFING11 TEXT)')
        self.db.execute("INSERT INTO ZAEANNOTATION VALUES(1,2,'uuid','later',1.1,'0.9','0.6',NULL,'book',3,0,NULL,NULL)")
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_backward_write_keeps_furthest_progress_and_identity(self):
        before = bookmark(self.db, 'book')
        with self.db:
            write_bookmark(self.db, 'book', before, 'earlier')
        after = bookmark(self.db, 'book')
        self.assertEqual(after['ZANNOTATIONLOCATION'], 'earlier')
        for key in ('ZANNOTATIONUUID', 'ZFUTUREPROOFING8', 'ZFUTUREPROOFING10'):
            self.assertEqual(after[key], before[key])
        self.assertIsInstance(after['ZANNOTATIONMODIFICATIONDATE'], float)

    def test_concurrent_reader_change_is_not_overwritten(self):
        before = bookmark(self.db, 'book')
        self.db.execute("UPDATE ZAEANNOTATION SET ZANNOTATIONLOCATION='user moved'")
        self.db.commit()
        with self.assertRaises(ValueError), self.db:
            write_bookmark(self.db, 'book', before, 'stale requested position')
        self.assertEqual(bookmark(self.db, 'book')['ZANNOTATIONLOCATION'], 'user moved')

    def test_utf16_offsets_do_not_shift_after_emoji(self):
        self.assertEqual(codepoint_offset('a😀b', 3), 2)
        with self.assertRaises(ValueError):
            codepoint_offset('a😀b', 2)

    def test_passage_ambiguity_and_nontext_positions_are_refused(self):
        with self.assertRaises(ValueError):
            unique_start('same same', 'same')
        with self.assertRaises(ValueError):
            exact_index([1, 2, 5], 3)
