"""Output regression tests use only a mock backend: no hooks or key injection."""

import unittest
from unittest.mock import Mock, call

from keyboard_output import KeyboardOutput


# Every punctuation entry in the MorseWriter key chart, including underscore.
PUNCTUATION = {
    ".": ".", ",": ",", "?": "shift+/", "!": "shift+1", ":": "shift+;",
    ";": ";", "@": "shift+2", "#": "shift+3", "$": "shift+4", "%": "shift+5",
    "&": "shift+7", "*": "shift+8", "+": "shift+=", "-": "-", "=": "=",
    "/": "/", "\\": "\\", "'": "'", '"': "shift+'", "(": "shift+9",
    ")": "shift+0", "<": "shift+,", ">": "shift+.", "^": "shift+6", "_": "shift+-",
}


class KeyboardOutputTests(unittest.TestCase):
    def setUp(self):
        self.backend = Mock(spec=["press", "release", "send", "write"])
        self.output = KeyboardOutput(self.backend)

    def test_all_punctuation_uses_exact_character_output(self):
        for character, key in PUNCTUATION.items():
            with self.subTest(character=character):
                self.backend.reset_mock()
                self.assertEqual(self.output.send(key, character), character)
                self.assertEqual(self.backend.mock_calls, [call.write(character, exact=True)])

    def test_letters_digits_and_whitespace_use_key_events(self):
        for key, character in (("a", "a"), ("7", "7"), ("space", " "),
                               ("enter", "\n"), ("tab", "\t"), ("backspace", "\b")):
            with self.subTest(key=key):
                self.backend.reset_mock()
                self.assertEqual(self.output.send(key, character), character)
                self.assertEqual(self.backend.mock_calls, [call.send(key)])

    def test_text_expansion_sends_literal_whitespace_as_named_keys(self):
        expansion = "hello world!\tnext\nline\rend "
        returned = "".join(self.output.send(char, char) for char in expansion)
        self.assertEqual(returned, expansion)
        self.assertEqual(self.backend.mock_calls, [
            call.send("h"), call.send("e"), call.send("l"), call.send("l"), call.send("o"),
            call.send("space"), call.send("w"), call.send("o"), call.send("r"), call.send("l"),
            call.send("d"), call.write("!", exact=True), call.send("tab"),
            call.send("n"), call.send("e"), call.send("x"), call.send("t"), call.send("enter"),
            call.send("l"), call.send("i"), call.send("n"), call.send("e"), call.send("enter"),
            call.send("e"), call.send("n"), call.send("d"), call.send("space"),
        ])

    def test_send_text_preserves_case_unicode_punctuation_and_whitespace(self):
        text = "I know 中文 café🙂: +2!\tNext\nline\rend "
        self.assertEqual(self.output.send_text(text), text)
        self.assertEqual(self.backend.mock_calls, [call.write(text, exact=True)])

    def test_send_text_ends_modifier_lock_before_writing(self):
        self.output.toggle_lock_mode()
        self.output.send("ctrl", modifier=True)
        self.output.send("shift", modifier=True)
        self.backend.reset_mock()
        self.assertEqual(self.output.send_text("Hello! "), "Hello! ")
        self.assertFalse(self.output.lock_mode)
        self.assertEqual(self.output.held_modifiers, ())
        self.assertEqual(self.backend.mock_calls, [call.release("shift"), call.release("ctrl"),
                                                call.write("Hello! ", exact=True)])

    def test_send_text_failure_leaves_no_owned_modifiers_or_lock(self):
        self.output.toggle_lock_mode()
        self.output.send("ctrl", modifier=True)
        self.backend.write.side_effect = RuntimeError("text failed")
        with self.assertRaisesRegex(RuntimeError, "text failed"):
            self.output.send_text("Hello! ")
        self.assertFalse(self.output.lock_mode)
        self.assertEqual(self.output.held_modifiers, ())
        self.backend.release.assert_called_once_with("ctrl")
        self.backend.send.assert_not_called()

    def test_windows_key_is_not_omitted_when_ctrl_is_held(self):
        self.output.send("ctrl", modifier=True)
        self.assertIsNone(self.output.send("windows"))
        self.assertEqual(self.backend.mock_calls, [call.press("ctrl"), call.send("windows"), call.release("ctrl")])

    def test_ctrl_v_is_a_one_shot_shortcut(self):
        self.assertIsNone(self.output.send("ctrl", modifier=True))
        self.assertEqual(self.output.held_modifiers, ("ctrl",))
        self.assertIsNone(self.output.send("v", "v"))
        self.assertEqual(self.output.held_modifiers, ())
        self.assertEqual(self.backend.mock_calls, [call.press("ctrl"), call.send("v"), call.release("ctrl")])
        self.assertEqual(self.output.send("v", "v"), "v")

    def test_locked_ctrl_survives_keys_until_lock_is_turned_off(self):
        self.assertTrue(self.output.toggle_lock_mode())
        self.output.send("ctrl", modifier=True)
        self.assertIsNone(self.output.send("v", "v"))
        self.assertIsNone(self.output.send("c", "c"))
        self.assertEqual(self.output.held_modifiers, ("ctrl",))
        self.assertFalse(self.output.toggle_lock_mode())
        self.assertEqual(self.output.held_modifiers, ())
        self.assertEqual(self.backend.mock_calls, [call.press("ctrl"), call.send("v"), call.send("c"), call.release("ctrl")])

    def test_repeat_toggle_never_replays_a_previous_action(self):
        self.output.send("a", "a")
        self.backend.reset_mock()
        for expected in (True, False, True, False):
            self.assertEqual(self.output.toggle_lock_mode(), expected)
        self.assertEqual(self.backend.mock_calls, [])

    def test_modifiers_toggle_off_individually(self):
        for key in ("shift", "ctrl", "alt", "windows", "left ctrl", "right shift"):
            with self.subTest(key=key):
                self.backend.reset_mock()
                self.output.send(key, modifier=True)
                self.output.send(key, modifier=True)
                self.assertEqual(self.output.held_modifiers, ())
                self.assertEqual(self.backend.mock_calls, [call.press(key), call.release(key)])

    def test_modifier_aliases_share_owned_state(self):
        self.output.send("cmd", modifier=True)
        self.output.send("windows", modifier=True)
        self.assertEqual(self.output.held_modifiers, ())
        self.assertEqual(self.backend.mock_calls, [call.press("windows"), call.release("windows")])

    def test_shift_capitalizes_letter_and_is_consumed(self):
        self.output.send("shift", modifier=True)
        self.assertEqual(self.output.send("a", "a"), "A")
        self.assertEqual(self.backend.mock_calls, [call.press("shift"), call.send("a"), call.release("shift")])
        self.assertEqual(self.output.send("a", "a"), "a")

    def test_shift_digits_and_own_caps_lock_update_prediction_text(self):
        self.output.send("shift", modifier=True)
        self.assertEqual(self.output.send("1", "1"), "!")
        self.assertIsNone(self.output.send("caps lock"))
        self.assertEqual(self.output.send("a", "a"), "A")
        self.output.send("shift", modifier=True)
        self.assertEqual(self.output.send("a", "a"), "a")
        self.output.send("caps lock")
        self.assertEqual(self.output.send("a", "a"), "a")

    def test_explicit_shift_tab_sends_chord_and_no_prediction_text(self):
        self.assertIsNone(self.output.send("shift+tab", "\t"))
        self.assertEqual(self.backend.mock_calls, [call.send("shift+tab")])

    def test_shift_tab_preserves_a_locked_shift(self):
        self.output.toggle_lock_mode()
        self.output.send("shift", modifier=True)
        self.assertIsNone(self.output.send("shift+tab", "\t"))
        self.assertEqual(self.output.held_modifiers, ("shift",))
        self.assertEqual(self.output.send("a", "a"), "A")
        self.assertEqual(self.backend.mock_calls, [call.press("shift"), call.send("tab"), call.send("a")])

    def test_exact_punctuation_suspends_and_restores_locked_shift(self):
        self.output.toggle_lock_mode()
        self.output.send("shift", modifier=True)
        self.assertEqual(self.output.send("shift+1", "!"), "!")
        self.assertEqual(self.output.held_modifiers, ("shift",))
        self.assertEqual(self.output.send("a", "a"), "A")
        self.assertEqual(self.backend.mock_calls, [call.press("shift"), call.release("shift"),
                         call.write("!", exact=True), call.press("shift"), call.send("a")])

    def test_punctuation_shortcuts_use_physical_key_combinations(self):
        for modifier in ("ctrl", "alt", "windows"):
            for character, key in PUNCTUATION.items():
                with self.subTest(modifier=modifier, character=character):
                    self.backend.reset_mock()
                    self.output.send(modifier, modifier=True)
                    self.assertIsNone(self.output.send(key, character))
                    chord = ["shift", ","] if key == "shift+," else key
                    self.assertEqual(self.backend.mock_calls, [call.press(modifier), call.send(chord), call.release(modifier)])

    def test_non_text_keys_do_not_return_prediction_text(self):
        for key in [f"f{i}" for i in range(1, 13)] + ["left", "delete", "menu", "windows", "shift+tab"]:
            with self.subTest(key=key):
                self.backend.reset_mock()
                self.assertIsNone(self.output.send(key))
                self.assertEqual(self.backend.mock_calls, [call.send(key)])

    def test_explicit_ctrl_shortcut_does_not_return_text(self):
        self.assertIsNone(self.output.send("ctrl+v", "v"))
        self.backend.send.assert_called_once_with("ctrl+v")

    def test_send_exception_releases_one_shot_modifiers(self):
        self.output.send("ctrl", modifier=True)
        self.output.send("shift", modifier=True)
        self.backend.send.side_effect = RuntimeError("send failed")
        with self.assertRaisesRegex(RuntimeError, "send failed"):
            self.output.send("v", "v")
        self.assertEqual(self.output.held_modifiers, ())
        self.assertEqual(self.backend.release.call_args_list, [call("v"), call("shift"), call("ctrl")])

    def test_write_exception_releases_one_shot_shift(self):
        self.output.send("shift", modifier=True)
        self.backend.write.side_effect = RuntimeError("write failed")
        with self.assertRaisesRegex(RuntimeError, "write failed"):
            self.output.send("shift+1", "!")
        self.assertEqual(self.output.held_modifiers, ())
        self.assertEqual(self.backend.mock_calls[-1], call.release("shift"))

    def test_reset_releases_only_owned_modifiers_and_clears_lock(self):
        self.output.toggle_lock_mode()
        self.output.send("ctrl", modifier=True)
        self.output.send("right shift", modifier=True)
        self.backend.reset_mock()
        self.output.reset()
        self.output.reset()
        self.assertFalse(self.output.lock_mode)
        self.assertEqual(self.output.held_modifiers, ())
        self.assertEqual(self.backend.mock_calls, [call.release("right shift"), call.release("ctrl")])

    def test_reset_attempts_every_release_and_retains_failed_ownership(self):
        self.output.toggle_lock_mode()
        self.output.send("ctrl", modifier=True)
        self.output.send("shift", modifier=True)
        self.backend.release.side_effect = [RuntimeError("release failed"), None]
        with self.assertRaisesRegex(RuntimeError, "release failed"):
            self.output.reset()
        self.assertFalse(self.output.lock_mode)
        self.assertEqual(self.output.held_modifiers, ("shift",))
        self.assertEqual(self.backend.release.call_args_list, [call("shift"), call("ctrl")])
        self.backend.release.side_effect = None
        self.output.reset()
        self.assertEqual(self.output.held_modifiers, ())

    def test_partial_modifier_press_failure_is_released(self):
        self.backend.press.side_effect = RuntimeError("press failed")
        with self.assertRaisesRegex(RuntimeError, "press failed"):
            self.output.send("ctrl", modifier=True)
        self.backend.release.assert_called_once_with("ctrl")
        self.assertEqual(self.output.held_modifiers, ())


if __name__ == "__main__":
    unittest.main()
