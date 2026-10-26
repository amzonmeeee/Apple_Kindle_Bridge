import copy
import unittest

from apple_kindle_bridge.sync import SyncError, baseline, check_plan, plan


def report(offset, side):
    # Synthetic evidence for reconciliation rules; not an engine test.
    return {'status': 'verified_engine_source_position',
            'direction': 'apple_cfi_to_koreader' if side == 'apple' else 'koreader_to_apple_cfi',
            'epub_copy_sha256': 'a' * 64, 'dom_version': 20260812,
            'xpointer': '/body/DocFragment[1]/body/p/text().' + str(offset),
            'cfi_raw': 'epubcfi(/6/2!/4/2/1:' + str(offset) + ')',
            'endpoints': [{'text_sha256': 'b' * 64, 'source_coordinate': {
                'document': 'chapter.xhtml', 'spine_index': 0, 'kind': 'text',
                'cfi_steps': [4, 2, 1], 'utf16_offset': offset}}]}


class ReconciliationTests(unittest.TestCase):
    def test_initial_state_needs_explicit_source_unless_equal(self):
        a, k = report(20, 'apple'), report(40, 'koreader')
        self.assertEqual(plan(a, k)['action'], 'choose_initial_source')
        self.assertEqual(plan(a, k, prefer='koreader')['action'], 'koreader_to_apple')
        with self.assertRaises(SyncError):
            baseline(a, k)
        self.assertEqual(plan(a, report(20, 'koreader'))['action'], 'no_change')

    def test_backward_movement_wins_when_only_one_side_changed(self):
        a, k = report(100, 'apple'), report(100, 'koreader')
        common = baseline(a, k)
        for side in ('apple', 'koreader'):
            with self.subTest(side=side):
                current_a = report(20, 'apple') if side == 'apple' else a
                current_k = report(20, 'koreader') if side == 'koreader' else k
                result = plan(current_a, current_k, common)
                self.assertEqual(result['action'], side + '_to_' + ('koreader' if side == 'apple' else 'apple'))
                self.assertEqual(result['proposed_target']['source_position']['coordinate']['utf16_offset'], 20)
                self.assertFalse(result['baseline_advanced'])
                self.assertFalse(result['write_performed'])

    def test_concurrent_moves_conflict_even_if_one_is_further_ahead(self):
        common = baseline(report(100, 'apple'), report(100, 'koreader'))
        a, k = report(20, 'apple'), report(200, 'koreader')
        self.assertEqual(plan(a, k, common)['action'], 'conflict')
        self.assertEqual(plan(a, k, common, prefer='apple')['action'], 'apple_to_koreader')

    def test_wrong_book_or_changed_evidence_rejects_stale_plan(self):
        a, k = report(20, 'apple'), report(40, 'koreader')
        result = plan(a, k, prefer='apple')
        self.assertEqual(check_plan(result, a, k)['status'], 'preconditions_match')
        with self.assertRaises(SyncError):
            check_plan(result, report(21, 'apple'), k)
        changed = copy.deepcopy(k)
        changed['epub_copy_sha256'] = 'c' * 64
        with self.assertRaises(SyncError):
            plan(a, changed)


if __name__ == '__main__':
    unittest.main()
