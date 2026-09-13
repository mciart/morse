"""Pinyin reaches the active IME as Latin key events; no OS input is injected."""

import unittest
from unittest.mock import Mock, call

from keyboard_output import KeyboardOutput


class PinyinOutputTests(unittest.TestCase):
    def setUp(self):
        self.backend = Mock(spec=['press', 'release', 'send', 'write'])
        self.output = KeyboardOutput(self.backend)

    def test_initial_and_final_are_sent_in_letter_order(self):
        self.assertEqual(self.output.send_pinyin('zh'), 'zh')
        self.assertEqual(self.output.send_pinyin('ang'), 'ang')
        self.assertEqual(self.backend.mock_calls, [
            call.send('z'), call.send('h'), call.send('a'), call.send('n'), call.send('g')])
        self.backend.write.assert_not_called()

    def test_v_and_combined_finals_use_real_letter_keys(self):
        for text in ('a', 'ch', 'sh', 'ing', 'iong', 'uan', 've', 'v'):
            with self.subTest(text=text):
                self.backend.reset_mock()
                self.assertEqual(self.output.send_pinyin(text), text)
                self.assertEqual(self.backend.mock_calls,
                                 [call.send(character) for character in text])

    def test_owned_ctrl_is_released_before_first_letter(self):
        self.output.send('ctrl', modifier=True)
        self.backend.reset_mock()
        self.assertEqual(self.output.send_pinyin('a'), 'a')
        self.assertEqual(self.backend.mock_calls, [call.release('ctrl'), call.send('a')])
        self.assertEqual(self.output.held_modifiers, ())

    def test_lock_and_all_owned_modifiers_are_cleared_before_letters(self):
        self.output.toggle_lock_mode()
        for modifier in ('ctrl', 'alt', 'right shift', 'windows'):
            self.output.send(modifier, modifier=True)
        self.backend.reset_mock()
        self.output.send_pinyin('zh')
        self.assertEqual(self.backend.mock_calls, [
            call.release('windows'), call.release('right shift'),
            call.release('alt'), call.release('ctrl'), call.send('z'), call.send('h')])
        self.assertFalse(self.output.lock_mode)
        self.assertEqual(self.output.held_modifiers, ())

    def test_invalid_text_has_no_backend_or_modifier_side_effect(self):
        self.output.toggle_lock_mode()
        self.output.send('ctrl', modifier=True)
        self.backend.reset_mock()
        for text in ('', 'ZH', 'a1', 'a b', 'a\n', 'nǐ', 'ü', '注音', '+', None):
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.output.send_pinyin(text)
        self.assertEqual(self.backend.mock_calls, [])
        self.assertTrue(self.output.lock_mode)
        self.assertEqual(self.output.held_modifiers, ('ctrl',))

    def test_partial_send_failure_releases_letter_and_stops_remaining_output(self):
        self.output.toggle_lock_mode()
        self.output.send('ctrl', modifier=True)
        self.backend.reset_mock()
        self.backend.send.side_effect = [None, RuntimeError('partial send failed')]
        with self.assertRaisesRegex(RuntimeError, 'partial send failed'):
            self.output.send_pinyin('zhang')
        self.assertEqual(self.backend.mock_calls, [
            call.release('ctrl'), call.send('z'), call.send('h'), call.release('h')])
        self.assertFalse(self.output.lock_mode)
        self.assertEqual(self.output.held_modifiers, ())
        self.backend.write.assert_not_called()

    def test_failed_modifier_release_prevents_letters_and_preserves_retry_ownership(self):
        self.output.toggle_lock_mode()
        self.output.send('ctrl', modifier=True)
        self.output.send('shift', modifier=True)
        self.backend.reset_mock()
        self.backend.release.side_effect = [RuntimeError('release failed'), None]
        with self.assertRaisesRegex(RuntimeError, 'release failed'):
            self.output.send_pinyin('ang')
        self.assertEqual(self.backend.mock_calls, [call.release('shift'), call.release('ctrl')])
        self.assertFalse(self.output.lock_mode)
        self.assertEqual(self.output.held_modifiers, ('shift',))
        self.backend.release.side_effect = None
        self.output.reset()
        self.assertEqual(self.output.held_modifiers, ())


if __name__ == '__main__':
    unittest.main()
