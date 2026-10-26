import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from apple_kindle_bridge.highlight_plan import preview_highlights
from apple_kindle_bridge.koreader import PROBE, ROOT


class HighlightPreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.book = self.root / 'book.epub'
        (self.book / 'META-INF').mkdir(parents=True)
        (self.book / 'OPS').mkdir()
        (self.book / 'META-INF/container.xml').write_text(
            '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">'
            '<rootfiles><rootfile full-path="OPS/book.opf" media-type="application/oebps-package+xml"/>'
            '</rootfiles></container>')
        (self.book / 'OPS/book.opf').write_text(
            '<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="uid">'
            '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
            '<dc:title>Highlight fixture</dc:title><dc:language>en</dc:language>'
            '<dc:identifier id="uid">urn:uuid:highlight-fixture</dc:identifier></metadata>'
            '<manifest><item id="c" href="chapter.xhtml" '
            'media-type="application/xhtml+xml"/></manifest><spine><itemref idref="c"/></spine></package>')
        (self.book / 'OPS/chapter.xhtml').write_text(
            '<html xmlns="http://www.w3.org/1999/xhtml"><head/><body>'
            '<p>A😀B<em>inline</em>tail</p><p>A😀B</p></body></html>')
        self.reader = self.root / 'reader.epub'
        self.pack_reader()
        self.row = {'asset_id': 'book-a', 'uuid': 'uuid-a', 'row_id': 1,
                    'deletion_state': 'active', 'deleted_raw': 0, 'source_issues': [],
                    'text': '😀Binlinetail', 'note': 'Keep this note',
                    'location_raw': 'epubcfi(/6/2!/4/2,/1:1,/3:4)',
                    'style_raw': 3, 'underline_raw': 0}
        self.export = {'kind': 'apple_books_highlights', 'schema_version': 1,
                       'highlights': [self.row]}

    def pack_reader(self):
        with zipfile.ZipFile(self.reader, 'w') as archive:
            for path in self.book.rglob('*'):
                if path.is_file():
                    archive.write(path, path.relative_to(self.book).as_posix())

    @unittest.skipUnless(PROBE.is_file() and (ROOT / '.runtime/node/node_modules/jsdom').is_dir(),
                         'Requires the position conversion runtime')
    def test_real_engine_range_preview_and_text_mismatch(self):
        wrong_text = {**self.row, 'uuid': 'uuid-b', 'text': 'Different selected text'}
        self.export['highlights'].append(wrong_text)
        result = preview_highlights(self.export, 'book-a', self.book, self.reader)
        self.assertEqual(result['summary'], {'records': 2, 'verified_preview': 1, 'refused': 1, 'skipped': 0})
        good, bad = result['records']
        self.assertTrue(good['verification']['source_selection_text_verified'])
        self.assertEqual(good['annotation']['note'], 'Keep this note')
        self.assertNotEqual(good['target']['pos0'], good['target']['pos1'])
        self.assertEqual([p['offset_codepoints'] for p in good['verification']['endpoints']], [1, 4])
        self.assertEqual(bad['reason'], 'highlight_text_mismatch')
        self.assertNotIn('target', bad)
        self.assertFalse(result['write_performed'])
        self.assertFalse(result['device_verified'])
        # A note edit keeps the transfer identity but changes the source revision.
        revised = copy.deepcopy(self.export)
        revised['highlights'] = [{**self.row, 'note': 'Edited note'}]
        with patch('apple_kindle_bridge.highlight_plan.convert_cfi', return_value=good['verification']):
            updated = preview_highlights(revised, 'book-a', self.book, self.reader)['records'][0]
        self.assertEqual(updated['transfer_id'], good['transfer_id'])
        self.assertNotEqual(updated['source_revision_sha256'], good['source_revision_sha256'])

    def test_duplicate_id_and_deleted_record_do_not_reach_converter(self):
        self.export['highlights'] = [self.row, dict(self.row),
                                     {**self.row, 'uuid': 'deleted', 'deletion_state': 'deleted', 'deleted_raw': 1}]
        with patch('apple_kindle_bridge.highlight_plan.convert_cfi') as convert:
            result = preview_highlights(self.export, 'book-a', self.book, self.reader)
        convert.assert_not_called()
        self.assertEqual(result['summary'], {'records': 3, 'verified_preview': 0, 'refused': 2, 'skipped': 1})
        self.assertTrue(all('target' not in r for r in result['records']))

    def test_different_reader_edition_is_rejected_before_conversion(self):
        (self.book / 'OPS/chapter.xhtml').write_text('<html><head/><body><p>Other edition</p></body></html>')
        with patch('apple_kindle_bridge.highlight_plan.convert_cfi') as convert:
            with self.assertRaisesRegex(ValueError, 'different content'):
                preview_highlights(self.export, 'book-a', self.book, self.reader)
        convert.assert_not_called()


if __name__ == '__main__':
    unittest.main()
