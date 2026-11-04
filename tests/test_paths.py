import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

from apple_kindle_bridge import paths


class Retention(unittest.TestCase):
    def test_prune_keeps_recent_files(self):
        with tempfile.TemporaryDirectory() as folder:
            old, new = Path(folder, 'old.sqlite'), Path(folder, 'new.sqlite')
            old.write_text('x'); new.write_text('y')
            stale = time.time() - 31 * 86400
            os.utime(old, (stale, stale))
            self.assertEqual(paths.prune(folder), 1)
            self.assertFalse(old.exists())
            self.assertTrue(new.exists())

    def test_tidy_trims_large_log(self):
        with tempfile.TemporaryDirectory() as home, mock.patch.dict(os.environ, {'AKB_HOME': home}):
            log = Path(home, 'logs', 'errors.log')
            log.parent.mkdir()
            log.write_text('a' * 1_500_000)
            paths.tidy()
            self.assertLess(log.stat().st_size, 300_000)


class PdfHelpers(unittest.TestCase):
    def test_compact_keeps_letters_and_digits(self):
        from apple_kindle_bridge.pdf_position import compact
        text, index = compact('A b, 中 文!')
        self.assertEqual(text, 'ab中文')
        self.assertEqual(index, [0, 2, 5, 7])

    def test_pdf_colors_map_to_kindle(self):
        from apple_kindle_bridge.pdf_position import kindle_color
        self.assertEqual(kindle_color('#F9CD59'), 'yellow')
        self.assertEqual(kindle_color('#4A90E2'), 'blue')
        self.assertEqual(kindle_color('#F06292'), 'pink')
        self.assertEqual(kindle_color(None), 'yellow')


if __name__ == '__main__':
    unittest.main()
