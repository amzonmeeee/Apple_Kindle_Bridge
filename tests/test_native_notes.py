import unittest
from types import SimpleNamespace
from apple_kindle_bridge.native_reverse import attached_note


def annotation(dataset, start, end, metadata=None):
    return SimpleNamespace(dataset=dataset, start=start, end=end,
                           payload={'json_metadata': metadata or {}})


class NativeNoteTests(unittest.TestCase):
    def test_captured_offset_attaches_note_to_its_highlight(self):
        h = annotation(1, 11, 52)
        n = annotation(3, 58, 58, {'note_text': 'Keep the original note\n'})
        self.assertEqual(attached_note(h, [h, n], 6), 'Keep the original note\n')
        self.assertIsNone(attached_note(h, [h, n], 0))

    def test_shared_endpoint_is_not_a_unique_attachment(self):
        h = annotation(1, 11, 52)
        other = annotation(1, 20, 52)
        n = annotation(3, 52, 52, {'note_text': 'Which highlight?'})
        with self.assertRaises(ValueError):
            attached_note(h, [h, other, n], 0)

    def test_duplicate_notes_are_refused(self):
        h = annotation(1, 11, 52)
        n = annotation(3, 52, 52, {'note_text': 'one'})
        with self.assertRaises(ValueError):
            attached_note(h, [h, n, n], 0)
