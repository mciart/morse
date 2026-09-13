"""Exercise shipped Morse codes through the UI with no OS hooks or key output."""

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, call, patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"

with patch("logging.basicConfig"):
    import MorseCodeGUI as morse

from keyboard_output import KeyboardOutput
from mouse_output import MouseOutput


# Fixed expectations, independent of the runtime table and action metadata.
# These 18 punctuation characters use the international-first code chart.
PUNCTUATION_CODES = {
    "121212": ".", "221122": ",", "112211": "?", "212122": "!",
    "222111": ":", "212121": ";", "122121": "@", "1112112": "$",
    "12111": "&", "12121": "+", "211112": "-", "21112": "=",
    "21121": "/", "122221": "'", "121121": '"', "21221": "(",
    "212212": ")", "112212": "_",
}
COMPUTER_PUNCTUATION_CODES = {
    "21222": "#", "1122121": "%", "1212111": "*", "211111": "\\",
    "121112": "<", "221121": ">", "212112": "^",
}
FUNCTION_CODES = (
    "112222", "111222", "111122", "111112", "111111", "121111",
    "122111", "122211", "1122221", "122222", "212222", "211222",
)
LETTER_CODES = dict(zip("abcdefghijklmnopqrstuvwxyz", (
    "12", "2111", "2121", "211", "1", "1121", "221", "1111", "11",
    "1222", "212", "1211", "22", "21", "222", "1221", "2212", "121",
    "111", "2", "112", "1112", "122", "2112", "2122", "2211",
)))
DIGIT_CODES = dict(zip("0123456789", (
    "22222", "12222", "11222", "11122", "11112", "11111", "21111",
    "22111", "22211", "22221",
)))
NAVIGATION_CODES = {
    "1212": "enter", "1122": "space", "2222": "backspace", "1221221": "tab",
    "221211": "shift+tab", "222112": "page up", "222121": "page down",
    "222212": "left", "222221": "right", "222211": "up", "222222": "down",
    "11211": "esc", "111121": "home", "21211": "end", "12112": "insert",
    "1221121": "delete", "221111": "windows", "211122": "menu", "112121": "caps lock",
}


class MappingActionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = morse.CustomApplication.instance() or morse.CustomApplication([])

    def setUp(self):
        project = Path(__file__).resolve().parents[1]
        temporary = self.enterContext(TemporaryDirectory())
        config_path = Path(temporary) / "config.json"
        config_path.write_text(json.dumps(dict(
            morse.DEFAULT_CONFIG, keylen=3, withsound=False,
            minLetterPause=60000, fastMorseMode=False,
        )), encoding="utf-8")

        self.start_listener = self.enterContext(patch.object(morse.KeyListenerThread, "start"))
        # Fail loudly if a regression bypasses the injectable output boundary.
        for name in ("hook", "hook_key", "press", "release", "send",
                     "press_and_release", "write"):
            self.enterContext(patch.object(morse.keyboard, name,
                                          side_effect=AssertionError("Unexpected OS keyboard access")))
        self.enterContext(patch.object(morse.keyboard, "is_pressed", return_value=False))
        for name in ("move", "click", "press", "release", "double_click"):
            self.enterContext(patch.object(morse.mouse, name,
                                          side_effect=AssertionError("Unexpected OS mouse output")))
        self.enterContext(patch.object(morse.QMessageBox, "information"))
        self.quit_app = self.enterContext(patch.object(self.app, "quit"))

        real_audio = morse.ToneAudio
        self.enterContext(patch.object(morse, 'ToneAudio',
                                       side_effect=lambda parent: real_audio(parent, backend_enabled=False)))
        manager = morse.ConfigManager(str(config_path))
        self.layout = morse.LayoutManager(str(project / "user_data" / "layouts.json"))
        self.window = morse.Window(layoutManager=self.layout, configManager=manager)
        self.backend = Mock(spec=["press", "release", "send", "write"])
        self.window.key_output = KeyboardOutput(backend=self.backend)
        self.mouse_backend = Mock(spec=["press", "release", "click", "double_click", "move"])
        self.window.mouse_output = MouseOutput(backend=self.mouse_backend)
        self.layout.set_actions(manager.initActions(self.window))
        self.window.postInit()
        self.views = []
        self.start_input()

    def tearDown(self):
        self.window.shutdown()
        self.window.trayIcon.hide()
        for widget in self.views + [self.window.audioSelector, self.window]:
            try:
                widget.hide()
                widget.deleteLater()
            except RuntimeError:
                # Returning to settings already deletes the previous guide.
                pass
        self.app.sendPostedEvents(None, morse.QtCore.QEvent.DeferredDelete)
        self.app.processEvents()

    def start_input(self):
        self.window.GOButton.click()
        self.app.processEvents()
        self.views.append(self.window.codeslayoutview)
        self.assertIsNotNone(self.window.listenerThread)
        self.assertEqual(self.layout.active_layout_name, "desktop")
        self.assertEqual(set(self.layout.layouts), {"desktop"})
        self.assertEqual(len(self.window.codeslayoutview.crs), 130)

    def enter_code(self, code):
        """Use the same Qt events as the three-key listener, including end-key."""
        listener = self.window.listenerThread
        self.assertIsNotNone(listener)
        for digit in code:
            role = int(digit) - 1
            key = ("space", "enter")[role]
            listener._emit_key(key, True, role, morse.time.monotonic())
            listener._emit_key(key, False, role, morse.time.monotonic())
        listener._emit_key("right ctrl", True, 2, morse.time.monotonic())
        listener._emit_key("right ctrl", False, 2, morse.time.monotonic())
        self.assertEqual(self.window.currentCharacter, [])
        view = self.window.codeslayoutview
        if view is not None and view not in self.views:
            self.views.append(view)

    def test_repaired_navigation_codes_emit_the_required_system_keys(self):
        for code, key in NAVIGATION_CODES.items():
            with self.subTest(code=code, key=key):
                self.backend.reset_mock()
                self.enter_code(code)
                self.assertEqual(self.backend.mock_calls, [call.send(key)])
                self.assertEqual(self.window.key_output.held_modifiers, ())

    def test_all_18_international_punctuation_codes_emit_the_displayed_character(self):
        self.assertEqual(len(PUNCTUATION_CODES), 18)
        for code, character in PUNCTUATION_CODES.items():
            with self.subTest(code=code, character=character):
                self.backend.reset_mock()
                self.enter_code(code)
                self.assertEqual(self.backend.mock_calls, [call.write(character, exact=True)])

    def test_computer_symbol_extensions_emit_their_literal_character(self):
        for code, character in COMPUTER_PUNCTUATION_CODES.items():
            with self.subTest(code=code, character=character):
                self.backend.reset_mock()
                self.enter_code(code)
                self.assertEqual(self.backend.mock_calls, [call.write(character, exact=True)])

    def test_backtick_has_its_own_code_and_does_not_emit_a_function_key(self):
        self.enter_code("1111111")
        self.assertEqual(self.backend.mock_calls, [call.write("`", exact=True)])

    def test_all_function_keys_include_the_f9_extension(self):
        for number, code in enumerate(FUNCTION_CODES, 1):
            with self.subTest(function=number):
                self.backend.reset_mock()
                self.enter_code(code)
                self.assertEqual(self.backend.mock_calls, [call.send(f"f{number}")])

    def test_all_letters_and_digits_emit_one_key_then_a_space(self):
        for character, code in {**LETTER_CODES, **DIGIT_CODES}.items():
            with self.subTest(character=character):
                self.backend.reset_mock()
                self.enter_code(code)
                self.enter_code("1122")
                self.assertEqual(self.backend.mock_calls,
                                 [call.send(character), call.send("space")])

    def test_ctrl_v_is_a_one_shot_shortcut_through_real_codes(self):
        self.enter_code("21212")  # Ctrl.
        self.assertEqual(self.window.key_output.held_modifiers, ("ctrl",))
        self.enter_code("1112")   # V consumes the one-shot Ctrl.
        self.enter_code("1112")   # A subsequent V is plain text.
        self.assertEqual(self.backend.mock_calls, [call.press("ctrl"), call.send("v"),
                                                 call.release("ctrl"), call.send("v")])
        self.assertEqual(self.window.key_output.held_modifiers, ())

    def test_each_modifier_is_released_after_the_next_character(self):
        for code, key in (('11212', 'shift'), ('12122', 'alt'),
                          ('21212', 'ctrl'), ('112122', 'windows')):
            with self.subTest(key=key):
                self.backend.reset_mock()
                self.enter_code(code)
                self.enter_code('12')
                self.assertEqual(self.backend.mock_calls,
                                 [call.press(key), call.send('a'), call.release(key)])
                self.assertEqual(self.window.key_output.held_modifiers, ())

    def test_modifier_lock_ctrl_v_unlock_sequence_retains_then_releases_ctrl(self):
        self.enter_code("12")  # A prior action must never be replayed by the lock code.
        self.backend.reset_mock()
        self.enter_code("1121121")
        self.assertTrue(self.window.repeaton)
        self.assertEqual(self.backend.mock_calls, [])
        self.enter_code("21212")
        self.enter_code("1112")
        self.assertEqual(self.backend.mock_calls, [call.press("ctrl"), call.send("v")])
        self.assertEqual(self.window.key_output.held_modifiers, ("ctrl",))
        self.enter_code("1121121")
        self.assertEqual(self.backend.mock_calls,
                         [call.press("ctrl"), call.send("v"), call.release("ctrl")])
        self.assertFalse(self.window.repeaton)

    def test_pause_settings_and_exit_release_a_locked_ctrl(self):
        for index, action in enumerate(("pause", "settings", "exit")):
            with self.subTest(action=action):
                if index:
                    self.window.stopIt()
                    self.start_input()
                self.enter_code("1121121")
                self.enter_code("21212")
                self.backend.reset_mock()
                listener = self.window.listenerThread
                if action == "pause":
                    self.window.onOffAction.trigger()
                elif action == "settings":
                    self.window.codeslayoutview.settingsRequested.emit()
                else:
                    self.window.quitAction.trigger()
                self.assertEqual(self.backend.mock_calls, [call.release("ctrl")])
                self.assertEqual(self.window.key_output.held_modifiers, ())
                self.assertFalse(self.window.key_output.lock_mode)
                self.assertFalse(self.window.repeaton)
                self.assertIsNone(self.window.listenerThread)
                self.assertFalse(listener.keep_running)
        self.quit_app.assert_called_once_with()

    def test_every_unified_code_is_displayed_with_one_live_listener(self):
        listener = self.window.listenerThread
        view = self.window.codeslayoutview
        entries = {item["code"]: item for item in self.layout.get_active_layout()["items"]}
        self.assertEqual(set(view.crs), set(entries))
        for code, item in entries.items():
            representation = view.crs[code]
            self.assertIs(representation.item, item)
            self.assertEqual(representation.code, code.replace("1", "•").replace("2", "–"))
            self.assertIsNotNone(item['_action'])
        self.assertIs(self.window.listenerThread, listener)
        self.assertTrue(listener.keep_running)
        self.start_listener.assert_called_once_with()
        self.assertEqual(self.backend.mock_calls, [])

    def test_sound_code_toggles_audio_without_emitting_a_keyboard_key(self):
        self.assertFalse(self.window.config["withsound"])
        self.enter_code("121211")
        self.assertTrue(self.window.config["withsound"])
        self.assertTrue(self.window.withSound.isChecked())
        self.enter_code("121211")
        self.assertFalse(self.window.config["withsound"])
        self.assertFalse(self.window.withSound.isChecked())
        listener = self.window.listenerThread
        self.assertEqual(self.layout.active_layout_name, "desktop")
        self.assertIs(self.window.listenerThread, listener)
        self.assertEqual(self.backend.mock_calls, [])

    def test_mouse_double_click_codes_reach_the_correct_mouse_button(self):
        self.enter_code("2122112")
        self.enter_code("2122212")
        self.assertEqual(self.mouse_backend.double_click.call_args_list,
                         [call(button=morse.mouse.LEFT), call(button=morse.mouse.RIGHT)])
        self.assertEqual(self.window.mouse_output.held_buttons, ())
        self.assertEqual(self.backend.mock_calls, [])

    def test_pause_settings_and_exit_release_mouse_buttons_held_by_morse(self):
        for index, action in enumerate(("pause", "settings", "exit")):
            with self.subTest(action=action):
                if index:
                    self.window.stopIt()
                    self.start_input()
                self.enter_code("2122121")  # Hold left.
                self.enter_code("2122221")  # Hold right.
                self.assertEqual(self.window.mouse_output.held_buttons, ("left", "right"))
                self.mouse_backend.reset_mock()
                if action == "pause":
                    self.window.onOffAction.trigger()
                elif action == "settings":
                    self.window.codeslayoutview.settingsRequested.emit()
                else:
                    self.window.quitAction.trigger()
                self.assertEqual(self.mouse_backend.mock_calls,
                                 [call.release("right"), call.release("left")])
                self.assertEqual(self.window.mouse_output.held_buttons, ())
                self.assertIsNone(self.window.listenerThread)
        self.quit_app.assert_called_once_with()

    def test_explicit_mouse_release_code_releases_only_our_held_buttons(self):
        self.enter_code("2122122")  # An idle release must not lift physical buttons.
        self.assertEqual(self.mouse_backend.mock_calls, [])
        self.enter_code("2122121")
        self.mouse_backend.reset_mock()
        self.enter_code("2122122")
        self.enter_code("2122122")
        self.assertEqual(self.mouse_backend.mock_calls, [call.release("left")])
        self.assertEqual(self.window.mouse_output.held_buttons, ())

    def test_click_and_double_click_end_the_existing_morse_drag(self):
        for code, operation in (("2122111", "click"), ("2122112", "double_click")):
            with self.subTest(operation=operation):
                self.enter_code("2122121")
                self.mouse_backend.reset_mock()
                self.enter_code(code)
                self.assertEqual(self.mouse_backend.mock_calls, [
                    call.release("left"), getattr(call, operation)(button="left"),
                ])
                self.assertEqual(self.window.mouse_output.held_buttons, ())
                self.window.resetOutput()
                self.assertEqual(self.mouse_backend.release.call_args_list, [call("left")])

    def test_keyboard_release_failure_does_not_skip_mouse_cleanup(self):
        self.enter_code("21212")  # Hold Ctrl.
        self.enter_code("2122121")
        self.mouse_backend.reset_mock()
        self.backend.release.side_effect = OSError("keyboard release failed")
        try:
            with self.assertLogs(level="ERROR"):
                self.assertFalse(self.window.resetOutput())
            self.mouse_backend.release.assert_called_once_with("left")
            self.assertEqual(self.window.mouse_output.held_buttons, ())
            self.assertEqual(self.window.key_output.held_modifiers, ("ctrl",))
        finally:
            self.backend.release.side_effect = None
            self.window.resetOutput()

    def test_mouse_movement_codes_keep_all_eight_directions_and_three_distances(self):
        directions = (
            ((1, 0), ('2111111', '2111112', '2111121')),
            ((-1, 0), ('2111122', '2111211', '2111212')),
            ((0, -1), ('2111221', '2111222', '2112111')),
            ((0, 1), ('2112112', '2112121', '2112122')),
            ((1, -1), ('2112211', '2112212', '2112221')),
            ((1, 1), ('2112222', '2121111', '2121112')),
            ((-1, -1), ('2121121', '2121122', '2121211')),
            ((-1, 1), ('2121212', '2121221', '2121222')),
        )
        for (x, y), codes in directions:
            for distance, code in zip((5, 40, 250), codes):
                with self.subTest(direction=(x, y), distance=distance):
                    self.mouse_backend.move.reset_mock()
                    self.enter_code(code)
                    self.mouse_backend.move.assert_called_once_with(x * distance, y * distance, False)
        self.assertEqual(self.backend.mock_calls, [])


if __name__ == "__main__":
    unittest.main()
