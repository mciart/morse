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

from PyQt5.QtGui import QTextDocument
from keyboard_output import KeyboardOutput


# Independent examples from the published MorseWriter chart, not derived from
# the application's action metadata (which is what these tests verify).
PUNCTUATION_CODES = {
    "121212": ".", "221122": ",", "112211": "?", "121122": "!",
    "212121": ":", "11121": ";", "12221": "@", "21222": "#",
    "211121": "$", "122121": "%", "21122": "&", "12111": "*",
    "12211": "+", "2221": "-", "12212": "=", "22112": "/",
    "211111": "\\", "121221": "'", "22122": '"', "111221": "(",
    "211221": ")", "121112": "<", "221121": ">", "212112": "^",
    "11221": "_",
}
FUNCTION_CODES = (
    "112222", "111222", "111122", "111112", "111111", "121111",
    "122111", "122211", "122221", "122222", "212222", "211222",
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
SHORT_DIGIT_CODES = dict(zip("0123456789", (
    "211", "1", "2", "12", "11", "21", "22", "122", "112", "111",
)))


class MappingActionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = morse.CustomApplication.instance() or morse.CustomApplication([])

    def setUp(self):
        project = Path(__file__).resolve().parents[1]
        data_path = str(project / "user_data")
        self.enterContext(patch.object(morse, "user_data_dir", data_path, create=True))
        self.enterContext(patch.object(morse, "get_user_data_dir", return_value=data_path))
        temporary = self.enterContext(TemporaryDirectory())
        config_path = Path(temporary) / "config.json"
        config_path.write_text(json.dumps(dict(
            morse.DEFAULT_CONFIG, keylen=3, withsound=False, guide_layout='main',
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
        self.enterContext(patch.object(morse.AudioDeviceSelector, "play_audio"))
        self.quit_app = self.enterContext(patch.object(self.app, "quit"))

        real_audio = morse.ToneAudio
        self.enterContext(patch.object(morse, 'ToneAudio',
                                       side_effect=lambda parent: real_audio(parent, backend_enabled=False)))
        manager = morse.ConfigManager(str(config_path))
        self.layout = morse.LayoutManager(str(project / "user_data" / "layouts.json"))
        self.window = morse.Window(layoutManager=self.layout, configManager=manager)
        self.backend = Mock(spec=["press", "release", "send", "write"])
        self.window.key_output = KeyboardOutput(backend=self.backend)
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
                # Switching pages already schedules the previous view's deletion.
                pass
        self.app.sendPostedEvents(None, morse.QtCore.QEvent.DeferredDelete)
        self.app.processEvents()

    def start_input(self):
        self.window.GOButton.click()
        self.app.processEvents()
        self.views.append(self.window.codeslayoutview)
        self.assertIsNotNone(self.window.listenerThread)
        self.assertEqual(self.layout.active_layout_name, "desktop")
        # The normal settings now always open the unified guide. These legacy
        # mapping tests deliberately enter the compatibility layout internally.
        self.window.changeLayout('main')
        self.views.append(self.window.codeslayoutview)
        self.assertEqual(self.layout.active_layout_name, "main")

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

    def select_page(self, name):
        selector = self.window.codeslayoutview.layout_selector
        index = selector.findData(name)
        self.assertGreaterEqual(index, 0)
        selector.setCurrentIndex(index)
        selector.activated.emit(index)
        self.views.append(self.window.codeslayoutview)
        self.assertEqual(self.layout.active_layout_name, name)

    def test_repaired_navigation_codes_emit_the_required_system_keys(self):
        for code, key in (("221211", "shift+tab"), ("221111", "windows"),
                          ("211122", "menu")):
            with self.subTest(code=code, key=key):
                self.backend.reset_mock()
                self.enter_code(code)
                self.assertEqual(self.backend.mock_calls, [call.send(key)])
                self.assertEqual(self.window.key_output.held_modifiers, ())

    def test_all_25_punctuation_codes_emit_the_displayed_character(self):
        for code, character in PUNCTUATION_CODES.items():
            with self.subTest(code=code, character=character):
                self.backend.reset_mock()
                self.enter_code(code)
                self.assertEqual(self.backend.mock_calls, [call.write(character, exact=True)])

    def test_function_keys_and_number_page_work_without_text_state(self):
        self.window.clearTextState()
        for number, code in enumerate(FUNCTION_CODES, 1):
            with self.subTest(function=number):
                self.backend.reset_mock()
                self.enter_code(code)
                self.assertEqual(self.backend.mock_calls, [call.send(f"f{number}")])
        self.enter_code("21112")  # Main -> number page.
        self.assertEqual(self.layout.active_layout_name, "number")
        self.assertIsNone(self.window.typestate)
        self.backend.reset_mock()
        self.enter_code("1")
        self.enter_code("1212")
        self.enter_code("221")
        self.assertEqual(self.backend.mock_calls,
                         [call.send("1"), call.send("enter"), call.write("+", exact=True)])

    def test_main_letters_digits_and_number_short_codes_never_expand_abbreviations(self):
        for character, code in {**LETTER_CODES, **DIGIT_CODES}.items():
            with self.subTest(page="main", character=character):
                self.backend.reset_mock()
                self.enter_code(code)
                self.enter_code("1122")  # Complete the word, including c, u, 2, and 4.
                self.assertEqual(self.backend.mock_calls,
                                 [call.send(character), call.send("space")])
        self.enter_code("21112")
        for character, code in SHORT_DIGIT_CODES.items():
            with self.subTest(page="number", character=character):
                self.backend.reset_mock()
                self.enter_code(code)
                self.enter_code("1212")
                self.assertEqual(self.backend.mock_calls,
                                 [call.send(character), call.send("enter")])

    def test_typing_abbreviation_waits_for_space_before_expanding(self):
        self.enter_code("111211")  # Main -> typing page.
        self.enter_code("2121")
        self.assertEqual(self.backend.mock_calls, [call.send("c")])
        self.assertEqual(self.window.typestate.text, "c")
        self.backend.reset_mock()
        self.enter_code("1122")
        self.assertEqual(self.backend.mock_calls, [call.send("space"),
                         call.send("backspace"), call.send("backspace"),
                         call.write("see ", exact=True)])
        self.assertEqual(self.window.typestate.text, "see ")

    def test_abbreviation_expansion_preserves_case_and_replaces_the_complete_prefix(self):
        self.enter_code("111211")
        for character in "afaik":
            self.enter_code(LETTER_CODES[character])
        self.backend.write.assert_not_called()
        self.assertEqual(self.window.typestate.text, "afaik")
        self.enter_code("1122")
        self.backend.write.assert_called_once_with("as far as I know ", exact=True)
        self.assertEqual(self.window.typestate.text, "as far as I know ")

    def test_ctrl_v_is_a_one_shot_shortcut_through_real_codes(self):
        self.enter_code("21212")  # Ctrl.
        self.assertEqual(self.window.key_output.held_modifiers, ("ctrl",))
        self.enter_code("1112")   # V consumes the one-shot Ctrl.
        self.enter_code("1112")   # A subsequent V is plain text.
        self.assertEqual(self.backend.mock_calls, [call.press("ctrl"), call.send("v"),
                                                 call.release("ctrl"), call.send("v")])
        self.assertEqual(self.window.typestate.text, "v")
        self.assertEqual(self.window.key_output.held_modifiers, ())

    def test_original_repeat_ctrl_v_repeat_sequence_retains_then_releases_ctrl(self):
        self.enter_code("12")  # A prior action must never be replayed by the lock code.
        self.backend.reset_mock()
        self.enter_code("121121")
        self.assertTrue(self.window.repeaton)
        self.assertEqual(self.backend.mock_calls, [])
        self.enter_code("21212")
        self.enter_code("1112")
        self.assertEqual(self.backend.mock_calls, [call.press("ctrl"), call.send("v")])
        self.assertEqual(self.window.key_output.held_modifiers, ("ctrl",))
        self.assertIsNone(self.window.repeat_character_timer)
        self.enter_code("121121")
        self.assertEqual(self.backend.mock_calls,
                         [call.press("ctrl"), call.send("v"), call.release("ctrl")])
        self.assertFalse(self.window.repeaton)
        self.assertEqual(self.window.typestate.text, "a")

    def test_pause_settings_and_exit_release_a_locked_ctrl(self):
        for index, action in enumerate(("pause", "settings", "exit")):
            with self.subTest(action=action):
                if index:
                    self.window.stopIt()
                    self.start_input()
                self.enter_code("121121")
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

    def test_page_navigation_preserves_listener_and_displays_every_active_code(self):
        listener = self.window.listenerThread
        for page in ("main", "typing", "mouse", "number", "main"):
            with self.subTest(page=page):
                self.select_page(page)
                view = self.window.codeslayoutview
                entries = {item["code"]: item for item in self.layout.get_active_layout()["items"]
                           if not item.get("emptyspace")}
                self.assertEqual(set(view.crs), set(entries))
                for code, item in entries.items():
                    representation = view.crs[code]
                    self.assertIs(representation.item, item)
                    self.assertEqual(representation.code, code.replace("1", ".").replace("2", "-"))
                    displayed = QTextDocument()
                    displayed.setHtml(representation.character.text())
                    expected_label = item["_action"].getlabel()
                    if self.window.config["upperchars"]:
                        expected_label = expected_label.upper()
                    self.assertEqual(displayed.toPlainText(), expected_label)
                self.assertIs(self.window.listenerThread, listener)
                self.assertTrue(listener.keep_running)
        self.enter_code("22121")  # Morse navigation also keeps the existing listener.
        self.assertEqual(self.layout.active_layout_name, "mouse")
        self.assertIs(self.window.listenerThread, listener)
        self.start_listener.assert_called_once_with()
        self.assertEqual(self.backend.mock_calls, [])

    def test_sound_and_codeset_execute_app_commands_without_unknown_key_output(self):
        self.assertFalse(self.window.config["withsound"])
        self.enter_code("121211")
        self.assertTrue(self.window.config["withsound"])
        self.assertTrue(self.window.withSound.isChecked())
        self.enter_code("121211")
        self.assertFalse(self.window.config["withsound"])
        self.assertFalse(self.window.withSound.isChecked())
        listener = self.window.listenerThread
        self.enter_code("22212")
        self.assertEqual(self.layout.active_layout_name, "mouse")
        self.assertIs(self.window.listenerThread, listener)
        self.assertEqual(self.backend.mock_calls, [])

    def test_mouse_double_click_codes_reach_the_correct_mouse_button(self):
        self.enter_code("22121")
        with patch.object(morse.mouse, "double_click") as double_click:
            self.enter_code("2122")
            self.enter_code("2222")
        self.assertEqual(double_click.call_args_list,
                         [call(button=morse.mouse.LEFT), call(button=morse.mouse.RIGHT)])
        self.assertEqual(self.backend.mock_calls, [])


if __name__ == "__main__":
    unittest.main()
