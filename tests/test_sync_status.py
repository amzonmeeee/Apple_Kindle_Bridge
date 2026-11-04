import unittest
from unittest import mock

from apple_kindle_bridge import sync_status


def apple(uid, text, note=None, color='yellow', deleted=False, updated=100):
    return uid, {'id': uid, 'text': text, 'key': text, 'color': color, 'underline': False,
                 'note': note, 'updated': updated, 'deleted': deleted}


def kindle(kid, text, note=None, color='yellow', updated=100):
    return kid, {'id': kid, 'text': text, 'key': text, 'color': color, 'underline': False,
                 'note': note, 'updated': updated, 'pending_upload': False}


def value(note=None, color='yellow'):
    return {'color': color, 'underline': False, 'note': note}


class HighlightChanges(unittest.TestCase):
    def run_changes(self, apple_items, kindle_items, baseline=None, kindle_edits=False):
        with mock.patch.object(sync_status, 'apple_highlights', return_value=dict(apple_items)), \
             mock.patch.object(sync_status, 'kindle_highlights', return_value=dict(kindle_items)):
            changes, _, _ = sync_status.highlight_changes(None, baseline or {}, 0, kindle_edits)
        return {(c['kind'], c['target']): c for c in changes}

    def test_new_items_go_to_the_other_side(self):
        found = self.run_changes([apple('a1', 'alpha')], [kindle('k1', 'beta')])
        self.assertIn(('add', 'kindle'), found)
        self.assertIn(('add', 'apple'), found)

    def test_matching_text_without_baseline_is_quiet(self):
        self.assertEqual(self.run_changes([apple('a1', 'alpha')], [kindle('k1', 'alpha')]), {})

    def test_different_notes_default_to_newer_side(self):
        found = self.run_changes([apple('a1', 'alpha', note='old', updated=1)],
                                 [kindle('k1', 'alpha', note='new', updated=2)])
        change = found[('differs', 'apple')]
        self.assertTrue(change['selected'])
        self.assertEqual(change['kindle_value']['note'], 'new')

    def test_newer_apple_edit_waits_for_kindle_capture(self):
        found = self.run_changes([apple('a1', 'alpha', note='new', updated=3)],
                                 [kindle('k1', 'alpha', note='old', updated=2)])
        change = found[('differs', 'kindle')]
        self.assertFalse(change['supported'])
        self.assertFalse(change['selected'])

    def test_baseline_detects_kindle_deletion(self):
        base = {'highlights': [{'apple': 'a1', 'kindle': 'k1', 'apple_value': value(), 'kindle_value': value()}]}
        found = self.run_changes([apple('a1', 'alpha')], [], base)
        self.assertIn(('delete', 'apple'), found)

    def test_baseline_detects_apple_deletion(self):
        base = {'highlights': [{'apple': 'a1', 'kindle': 'k1', 'apple_value': value(), 'kindle_value': value()}]}
        found = self.run_changes([apple('a1', 'alpha', deleted=True)], [kindle('k1', 'alpha')], base)
        self.assertFalse(found[('delete', 'kindle')]['supported'])

    def test_captured_codes_enable_kindle_deletes(self):
        base = {'highlights': [{'apple': 'a1', 'kindle': 'k1', 'apple_value': value(), 'kindle_value': value()}]}
        found = self.run_changes([apple('a1', 'alpha', deleted=True)], [kindle('k1', 'alpha')], base, kindle_edits=True)
        self.assertTrue(found[('delete', 'kindle')]['supported'])
        self.assertTrue(found[('delete', 'kindle')]['selected'])

    def test_baseline_detects_kindle_note_edit(self):
        base = {'highlights': [{'apple': 'a1', 'kindle': 'k1', 'apple_value': value(), 'kindle_value': value()}]}
        found = self.run_changes([apple('a1', 'alpha')], [kindle('k1', 'alpha', note='added')], base)
        self.assertEqual(found[('update', 'apple')]['kindle_value']['note'], 'added')

    def test_both_sides_edited_is_a_conflict(self):
        base = {'highlights': [{'apple': 'a1', 'kindle': 'k1', 'apple_value': value(), 'kindle_value': value()}]}
        found = self.run_changes([apple('a1', 'alpha', note='A', updated=5)],
                                 [kindle('k1', 'alpha', note='K', updated=9)], base)
        self.assertEqual(found[('conflict', 'apple')]['default_target'], 'apple')

    def test_unchanged_link_is_quiet(self):
        base = {'highlights': [{'apple': 'a1', 'kindle': 'k1', 'apple_value': value(), 'kindle_value': value()}]}
        self.assertEqual(self.run_changes([apple('a1', 'alpha')], [kindle('k1', 'alpha')], base), {})


class Titles(unittest.TestCase):
    def test_title_normalization(self):
        from apple_kindle_bridge.library import norm_title
        self.assertEqual(norm_title('《黎智英傳》'), norm_title('黎智英傳'))
        self.assertEqual(norm_title('Pride and Prejudice'), norm_title('pride and  prejudice'))


if __name__ == '__main__':
    unittest.main()
