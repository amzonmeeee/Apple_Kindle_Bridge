import hashlib
from pathlib import Path
import tempfile
import unittest
import zipfile

from apple_kindle_bridge.epub import parse_cfi, resolve_cfi, LocationError


class CFIResolutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.book = Path(self.temp.name).resolve() / 'test.epub'
        (self.book / 'META-INF').mkdir(parents=True)
        (self.book / 'OPS').mkdir()
        (self.book / 'META-INF/container.xml').write_text('''<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OPS/package.opf"/></rootfiles></container>''')
        self.package = self.book / 'OPS/package.opf'
        self.package.write_text('''<package xmlns="http://www.idpf.org/2007/opf"><metadata/><manifest><item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref id="chapter-ref" idref="chapter"/></spine></package>''')
        self.document = self.book / 'OPS/chapter.xhtml'
        self.document.write_text('''<html xmlns="http://www.w3.org/1999/xhtml"><head/><body id="body"><p id="p1">A😀B<em>inline</em>tail<!--ignored-->text</p><p id="p,2">second</p><img id="img" alt="image"/></body></html>''')

    def tearDown(self):
        self.temp.cleanup()

    def cfi(self, local):
        return 'epubcfi(/6/2[chapter-ref]!' + local + ')'

    def resolve(self, local):
        return resolve_cfi(self.book, self.cfi(local))

    def test_utf16_offsets_are_not_python_character_counts(self):
        result = self.resolve('/4[body]/2[p1]/1:4')
        self.assertEqual(result['status'], 'resolved_source_point')
        point = result['endpoints'][0]
        self.assertEqual(point['text_utf16_length'], 4)
        self.assertEqual(point['utf16_offset'], 4)
        self.assertEqual(self.resolve('/4/2/1:5')['status'], 'offset_out_of_range')

    def test_ranges_preserve_both_endpoints(self):
        result = self.resolve('/4/2/1,:0,:3')
        self.assertEqual(result['status'], 'resolved_source_range')
        self.assertEqual([point['utf16_offset'] for point in result['endpoints']], [0, 3])
        self.assertEqual(self.resolve('/4/2/1,:3,:0')['status'], 'invalid_range_order')

    def test_odd_text_slots_include_coalesced_comment_tails(self):
        result = self.resolve('/4/2/3:8')
        self.assertEqual(result['endpoints'][0]['text_sha256'], hashlib.sha256(b'tailtext').hexdigest())
        self.assertEqual(self.resolve('/4/2/5')['status'], 'node_out_of_range')

    def test_assertions_are_checked_not_silently_dropped(self):
        self.assertEqual(self.resolve('/4/2[wrong]/1:0')['status'], 'id_assertion_mismatch')
        self.assertEqual(self.resolve('/4/4[p^,2]/1:0')['status'], 'resolved_source_point')

    def test_uri_decoding_and_hash_in_bare_assertion(self):
        encoded = 'book.epub#epubcfi(%2F6%2F2%5Bchapter-ref%5D!%2F4%2F2%2F1:0)'
        self.assertEqual(resolve_cfi(self.book, encoded)['status'], 'resolved_source_point')
        self.document.write_text('<html><head/><body><p id="p#1">test</p></body></html>')
        self.assertEqual(self.resolve('/4/2[p#1]/1:0')['status'], 'resolved_source_point')

    def test_side_bias_is_preserved_and_text_assertions_rejected(self):
        result = self.resolve('/4/2/1:0[;s=a]')
        self.assertEqual(result['endpoints'][0]['side_bias'], 'a')
        self.assertEqual(self.resolve('/4/2/1:0[,A]')['status'], 'unsupported_text_assertion')

    def test_image_alt_and_nonstandard_element_offset(self):
        self.assertEqual(self.resolve('/4/6[img]:5')['endpoints'][0]['kind'], 'image_alt_text')
        self.assertEqual(self.resolve('/4/2:0')['status'], 'unsupported_element_offset')

    def test_virtual_boundaries_and_implicit_zero(self):
        self.assertEqual(self.resolve('/4/0')['endpoints'][0]['kind'], 'virtual_before')
        self.assertEqual(self.resolve('/4/8')['endpoints'][0]['kind'], 'virtual_after')
        self.assertEqual(self.resolve('/4/2/1')['endpoints'][0]['utf16_offset'], 0)

    def test_apple_idref_assertion_is_explicit_compatibility_evidence(self):
        self.package.write_text(self.package.read_text().replace(' id="chapter-ref"', ''))
        result = resolve_cfi(self.book, 'epubcfi(/6/2[chapter]!/4/2/1:0)')
        self.assertEqual(result['status'], 'resolved_source_point')
        self.assertEqual(result['endpoints'][0]['compatibility_notes'], ['package_assertion_matches_idref_without_xml_id'])
        self.assertEqual(self.resolve('/4/2/1:0')['status'], 'id_assertion_mismatch')

    def test_zip_and_expanded_epub_resolve_identically(self):
        archive = Path(self.temp.name) / 'packed.epub'
        with zipfile.ZipFile(archive, 'w') as z:
            for file in self.book.rglob('*'):
                if file.is_file():
                    z.write(file, file.relative_to(self.book).as_posix())
        cfi = self.cfi('/4/2/1:0')
        self.assertEqual(resolve_cfi(archive, cfi), resolve_cfi(self.book, cfi))

    def test_uri_paths_are_decoded_once(self):
        self.document.rename(self.book / 'OPS/chapter%20.xhtml')
        self.package.write_text(self.package.read_text().replace('chapter.xhtml', 'chapter%2520.xhtml'))
        result = self.resolve('/4/2/1:0')
        self.assertEqual(result['endpoints'][0]['document'], 'OPS/chapter%20.xhtml')

    def test_path_escape_and_symlink_escape_are_rejected(self):
        original = self.package.read_text()
        self.package.write_text(original.replace('chapter.xhtml', '../../outside.xhtml'))
        self.assertEqual(self.resolve('/4/2/1:0')['status'], 'unsafe_resource_path')
        self.package.write_text(original)
        outside = Path(self.temp.name) / 'outside.xhtml'
        outside.write_text(self.document.read_text())
        self.document.unlink()
        self.document.symlink_to(outside)
        self.assertEqual(self.resolve('/4/2/1:0')['status'], 'unsafe_resource_path')

    def test_custom_entities_and_nested_indirection_are_not_guessed(self):
        self.document.write_text('<!DOCTYPE html [<!ENTITY secret SYSTEM "file:///etc/passwd">]><html/>')
        self.assertEqual(self.resolve('/4/2/1:0')['status'], 'unsupported_xml_entities')
        self.assertEqual(self.resolve('/4/2!/4/2')['status'], 'unsupported_indirection')

    def test_malformed_cf_is_rejected(self):
        for cfi in ('epubcfi(/6/2[x]!/4/1:0', 'epubcfi(/6/2[x]!/4/2[bad^q])', 'epubcfi(/6/02!/4/2)'):
            with self.subTest(cfi=cfi), self.assertRaises(LocationError):
                parse_cfi(cfi)


if __name__ == '__main__':
    unittest.main()
