import unittest

from apple_kindle_bridge.annotation_colors import apple_style, kindle_color


class AnnotationColorTests(unittest.TestCase):
    def test_shared_colors_keep_their_meaning_in_both_directions(self):
        for style, color in ((2, 'blue'), (3, 'yellow'), (4, 'pink')):
            self.assertEqual(kindle_color(style), color)
            self.assertEqual(apple_style(color), style)

    def test_unmatched_colors_do_not_silently_become_yellow(self):
        for style in (0, 1, 5, None, 99):
            with self.assertRaises(ValueError):
                kindle_color(style)
        for color in ('orange', 'purple', None, ''):
            with self.assertRaises(ValueError):
                apple_style(color)

    def test_underlines_remain_a_separate_style(self):
        self.assertEqual(apple_style('yellow', underline=True), 0)
        self.assertEqual(kindle_color(0, underline=True), 'yellow')
