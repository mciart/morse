"""Offscreen UI regressions without system hooks or synthetic key presses."""

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"

# Importing the application must not truncate the user's log.
with patch("logging.basicConfig"):
    import MorseCodeGUI as morse


class WindowBehaviorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = morse.CustomApplication.instance() or morse.CustomApplication([])

    def setUp(self):
        project = Path(__file__).resolve().parents[1]
        self.enterContext(patch.object(morse, "user_data_dir", str(project / "user_data"), create=True))
        temporary = self.enterContext(TemporaryDirectory())
        config_path = Path(temporary) / "config.json"
        config_path.write_text(json.dumps(dict(
            morse.DEFAULT_CONFIG, keylen=3, withsound=False, minLetterPause=60000,
        )), encoding="utf-8")

        # Keep the real listener and its Qt signal, without starting an OS hook.
        self.start_listener = self.enterContext(patch.object(morse.KeyListenerThread, "start"))
        self.enterContext(patch.object(morse.keyboard, "hook_key", side_effect=AssertionError("Unexpected OS hook")))
        for name in ("press", "release", "press_and_release", "write"):
            self.enterContext(patch.object(morse.keyboard, name, side_effect=AssertionError("Unexpected key output")))
        self.enterContext(patch.object(morse.keyboard, "is_pressed", return_value=False))
        self.enterContext(patch.object(morse.QMessageBox, "information"))
        self.quit_app = self.enterContext(patch.object(self.app, "quit"))

        real_audio = morse.ToneAudio
        self.enterContext(patch.object(morse, 'ToneAudio',
                                       side_effect=lambda parent: real_audio(parent, backend_enabled=False)))
        manager = morse.ConfigManager(str(config_path))
        layout = morse.LayoutManager(str(project / "user_data" / "layouts.json"))
        self.window = morse.Window(layoutManager=layout, configManager=manager)
        layout.set_actions(manager.initActions(self.window))
        self.window.postInit()
        self.window.show()
        self.views = []
        self.app.processEvents()

    def tearDown(self):
        self.window.shutdown()
        self.window.trayIcon.hide()
        for widget in self.views + [self.window.audioSelector, self.window]:
            widget.hide()
            widget.deleteLater()
        self.app.sendPostedEvents(None, morse.QtCore.QEvent.DeferredDelete)
        self.app.processEvents()

    def start_input(self):
        self.window.GOButton.click()
        self.app.processEvents()
        view = self.window.codeslayoutview
        self.assertIsNotNone(view)
        self.views.append(view)
        self.assertTrue(view.isVisible())
        self.start_listener.assert_called_once_with()
        self.assertEqual(self.window.listenerThread.configured_keys, ["space", "enter", "right ctrl"])
        return view, self.window.listenerThread

    def add_pending_input(self):
        self.window.currentCharacter = [1, 2]
        self.window.lastKeyDownTime = 123
        self.window.repeaton = True
        self.window.startEndCharacterTimer()
        for name in ("fast_morse_mode_timer", "repeat_character_timer"):
            timer = morse.QTimer(self.window)
            timer.start(60000)
            setattr(self.window, name, timer)
        return [getattr(self.window, name) for name in (
            "endCharacterTimer", "fast_morse_mode_timer", "repeat_character_timer",
        )]

    def test_settings_close_minimizes_and_tray_restores_without_stopping(self):
        with patch.object(self.window, "stopIt", wraps=self.window.stopIt) as stop:
            self.assertFalse(self.window.close())
            self.app.processEvents()
            self.assertTrue(self.window.isMinimized())
            self.assertFalse(self.app.quitOnLastWindowClosed())
            stop.assert_not_called()
            self.quit_app.assert_not_called()

            self.window.trayIcon.activated.emit(morse.QSystemTrayIcon.Trigger)
            self.app.processEvents()
            self.assertTrue(self.window.isVisible())
            self.assertFalse(self.window.isMinimized())
            stop.assert_not_called()
            self.quit_app.assert_not_called()

    def test_chinese_choices_keep_config_identifiers_when_starting(self):
        for box, label, identifier in (
            (self.window.iconComboBoxKeyOne, "空格", "SPACE"),
            (self.window.iconComboBoxKeyTwo, "回车", "ENTER"),
            (self.window.iconComboBoxKeyThree, "右Ctrl", "RCTRL"),
        ):
            self.assertEqual(box.currentText(), label)
            self.assertEqual(box.currentData(), identifier)
        collected = self.window.collect_config()
        for key in ("keyone", "keytwo", "keythree", "SoundDit", "SoundDah", "SoundTyping", "winxaxis", "winyaxis"):
            self.assertEqual(collected[key], morse.DEFAULT_CONFIG[key])

        self.start_input()
        self.assertEqual(self.window.config, collected)

    def test_small_settings_window_keeps_actions_visible_while_scrolling(self):
        self.window.resize(360, 300)
        self.app.processEvents()
        self.assertLessEqual(self.window.width(), 360)
        self.assertLessEqual(self.window.height(), 300)
        scroll = self.window.settings_scroll.verticalScrollBar()
        self.assertGreater(scroll.maximum(), 0)
        for position in (0, scroll.maximum()):
            scroll.setValue(position)
            self.app.processEvents()
            for button in (self.window.DeviceButton, self.window.SaveButton, self.window.GOButton):
                origin = button.mapTo(self.window, morse.QtCore.QPoint(0, 0))
                self.assertTrue(button.isVisible())
                self.assertTrue(self.window.rect().contains(morse.QtCore.QRect(origin, button.size())))
                self.assertFalse(self.window.settings_scroll.isAncestorOf(button))
        self.window.SaveButton.click()
        with open(self.window.configManager.config_file, encoding='utf-8') as stream:
            self.assertEqual(json.load(stream), self.window.collect_config())
        self.start_input()

    def test_guide_options_default_to_fit_without_mouse_and_persist_changes(self):
        self.assertTrue(self.window.guideAutoFitCheckBox.isChecked())
        self.assertFalse(self.window.showMouseCheckBox.isChecked())
        view, _ = self.start_input()
        self.assertFalse(view.mouse_checkbox.isChecked())
        self.assertTrue(view.auto_fit_checkbox.isChecked())
        view.mouse_checkbox.click()
        view.auto_fit_checkbox.click()
        self.assertTrue(self.window.showMouseCheckBox.isChecked())
        self.assertFalse(self.window.guideAutoFitCheckBox.isChecked())
        with open(self.window.configManager.config_file, encoding='utf-8') as stream:
            saved = json.load(stream)
        self.assertTrue(saved['show_mouse'])
        self.assertFalse(saved['guide_auto_fit'])

    def test_code_close_and_tray_restore_preserve_active_input(self):
        view, listener = self.start_input()
        timers = self.add_pending_input()
        with patch.object(self.window, "stopIt", wraps=self.window.stopIt) as stop:
            for restore in (
                lambda: self.window.trayIcon.activated.emit(morse.QSystemTrayIcon.Trigger),
                lambda: self.window.trayIcon.activated.emit(morse.QSystemTrayIcon.DoubleClick),
                self.window.showWindowAction.trigger,
            ):
                with self.subTest(restore=restore):
                    self.assertFalse(view.close())
                    self.app.processEvents()
                    self.assertTrue(view.isMinimized())
                    self.assertIs(self.window.codeslayoutview, view)
                    self.assertIs(self.window.listenerThread, listener)
                    self.assertTrue(listener.keep_running)
                    self.assertTrue(all(timer.isActive() for timer in timers))
                    self.assertEqual(self.window.currentCharacter, [1, 2])

                    restore()
                    self.app.processEvents()
                    self.assertTrue(view.isVisible())
                    self.assertFalse(view.isMinimized())
                    self.assertFalse(self.window.isVisible())
                    self.assertTrue(all(timer.isActive() for timer in timers))
                    self.start_listener.assert_called_once_with()
                    stop.assert_not_called()
                    self.quit_app.assert_not_called()

            # Release the key held during minimization, then enter another dot.
            listener._emit_key("space", False, 0, morse.time.monotonic())
            listener._emit_key("space", True, 0, morse.time.monotonic())
            listener._emit_key("space", False, 0, morse.time.monotonic())
            self.assertEqual(self.window.currentCharacter, [1, 2, 1])

    def test_exit_action_stops_listener_and_timers_before_quitting(self):
        view, listener = self.start_input()
        timers = self.add_pending_input()
        self.window.showNormal()
        self.window.audioSelector.show()
        self.window.quitAction.trigger()

        self.assertFalse(listener.keep_running)
        self.assertIsNone(self.window.listenerThread)
        self.assertTrue(all(not timer.isActive() for timer in timers))
        for name in ("endCharacterTimer", "fast_morse_mode_timer", "repeat_character_timer"):
            self.assertIsNone(getattr(self.window, name))
        self.assertEqual(self.window.currentCharacter, [])
        self.assertIsNone(self.window.lastKeyDownTime)
        self.assertFalse(self.window.repeaton)
        self.assertIsNone(self.window.codeslayoutview)
        self.assertFalse(view.isVisible())
        self.assertFalse(self.window.trayIcon.isVisible())
        self.assertFalse(self.window.isVisible())
        self.assertFalse(self.window.audioSelector.isVisible())
        self.quit_app.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
