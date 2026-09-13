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
        self.window.engine = morse.MorseEngine({'keylen': 3, 'keyer_mode': 'manual'})
        now = morse.time.monotonic()
        for role in (0, 1):
            for down in (True, False):
                self.window.handle_key_event(('space', 'enter')[role], down, role, now)
                now += .005
        self.assertEqual(self.window.engine.symbols, [1, 2])
        self.window.repeaton = True
        return [self.window.engine_timer]

    def test_only_international_guide_remains_and_agrees_with_dispatch(self):
        self.assertFalse(hasattr(self.window, 'codeProfileComboBox'))
        self.assertEqual(set(self.window.layoutManager.layouts), {'desktop'})
        view, _ = self.start_input()
        self.assertEqual(len(view.crs), 130)
        for code, action in (('21121', 'FSLASH'), ('1112112', 'DOLLAR'),
                             ('1111111', 'BACKTICK'), ('1221121', 'DELETE')):
            self.assertEqual(view.crs[code].item['action'], action)
            self.assertIs(view.crs[code].item['_action'], next(
                item['_action'] for item in self.window.layoutManager.get_active_layout()['items']
                if item['code'] == code))
        backtick = view.keystroke_crs_map['BACKTICK']
        self.assertEqual(backtick.character.text(), '`')
        self.assertLess(backtick.x(), view.keystroke_crs_map['ONE'].x())

    def test_settings_close_hides_to_tray_and_restores_without_stopping(self):
        with patch.object(self.window, "stopIt", wraps=self.window.stopIt) as stop:
            self.assertFalse(self.window.close())
            self.app.processEvents()
            self.assertFalse(self.window.isVisible())
            self.assertFalse(self.window.isMinimized())
            self.assertTrue(self.window.trayIcon.isVisible())
            self.assertFalse(self.app.quitOnLastWindowClosed())
            stop.assert_not_called()
            self.quit_app.assert_not_called()

            self.window.trayIcon.activated.emit(morse.QSystemTrayIcon.Trigger)
            self.app.processEvents()
            self.assertTrue(self.window.isVisible())
            self.assertFalse(self.window.isMinimized())
            stop.assert_not_called()
            self.quit_app.assert_not_called()

    def test_old_layout_preferences_are_discarded_without_changing_input_preferences(self):
        settings = dict(morse.DEFAULT_CONFIG, code_profile='legacy', guide_layout='mouse',
                        SoundDit='old.wav', withdebug=True, keyone='F23', theme='dark',
                        guide_positions={'compact': {'x': 80, 'y': 90}})
        path = Path(self.enterContext(TemporaryDirectory())) / 'config.json'
        source = json.dumps(settings)
        path.write_text(source, encoding='utf-8')
        loaded = morse.ConfigManager(str(path)).get_config()
        for key in ('code_profile', 'guide_layout', 'SoundDit', 'withdebug'):
            self.assertNotIn(key, loaded)
        for key in ('keyone', 'theme', 'guide_positions'):
            self.assertEqual(loaded[key], settings[key])
        self.assertEqual(path.read_text(encoding='utf-8'), source)

    def test_conflicting_old_layout_uses_current_guide_and_explains_once(self):
        path = Path(self.enterContext(TemporaryDirectory())) / 'layouts.json'
        data = {'layouts': {'desktop': {'items': [
            {'action': 'A', 'code': '12'}, {'action': 'UNKNOWN', 'code': '12'}]}}}
        source = json.dumps(data)
        path.write_text(source, encoding='utf-8')
        with self.assertLogs(level='WARNING'):
            layout = morse.LayoutManager(str(path))
        self.window.layoutManager = layout
        layout.set_actions(self.window.actions)
        with patch.object(morse.QMessageBox, 'warning') as warning:
            view, _ = self.start_input()
        warning.assert_called_once()
        self.assertEqual(len(view.crs), 130)
        self.assertIsNone(layout.layout_warning)
        self.assertEqual(path.read_text(encoding='utf-8'), source)

    def test_chinese_choices_keep_config_identifiers_when_starting(self):
        for box, label, identifier in (
            (self.window.iconComboBoxKeyOne, "空格", "SPACE"),
            (self.window.iconComboBoxKeyTwo, "回车", "ENTER"),
            (self.window.iconComboBoxKeyThree, "右Ctrl", "RCTRL"),
        ):
            self.assertEqual(box.currentText(), label)
            self.assertEqual(box.currentData(), identifier)
        collected = self.window.collect_config()
        for key in ("keyone", "keytwo", "keythree", "tone_frequency", "tone_volume"):
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

    def test_minimize_keeps_an_independent_window_and_tray_close_hides_it(self):
        self.assertEqual(self.window.windowType(), morse.Qt.Window)
        self.window.showMinimized()
        self.app.processEvents()
        self.assertTrue(self.window.isMinimized())
        self.assertTrue(self.window.isVisible())
        self.window.showCurrentWindow()
        view, listener = self.start_input()
        self.assertIsNone(view.parentWidget())
        self.assertEqual(view.windowType(), morse.Qt.Window)
        self.assertFalse(view.windowFlags() & morse.Qt.Tool == morse.Qt.Tool)
        view.showMinimized()
        self.app.processEvents()
        self.assertTrue(view.isVisible())
        self.assertTrue(view.isMinimized())
        self.window.showWindowAction.trigger()
        self.assertFalse(view.isMinimized())
        view.close()
        self.assertFalse(view.isVisible())
        self.assertIs(self.window.listenerThread, listener)

    def test_standard_preset_preserves_input_bindings_and_restores_standard_timing(self):
        keys = [box.currentData() for box in (self.window.iconComboBoxKeyOne,
                                             self.window.iconComboBoxKeyTwo)]
        self.window.maxDitTimeEdit.setValue(350)
        self.window.minLetterPauseEdit.setValue(1000)
        self.window.customTimingCheck.setChecked(True)
        self.assertEqual(self.window.collect_config()['minLetterPause'], 1000)
        self.window.keySelectionRadioTwoKey.click()
        self.assertIn('确认 1000 毫秒', self.window.timingSummary.text())
        self.window.standardKeyerButton.click()
        config = self.window.collect_config()
        self.assertEqual([config['keyone'], config['keytwo']], keys)
        self.assertEqual(config['keylen'], 2)
        self.assertEqual(config['keyer_mode'], 'iambic')
        self.assertEqual((config['maxDitTime'], config['minLetterPause']), (0, 0))
        self.assertEqual((config['wpm'], config['tone_frequency'], config['tone_volume']), (15, 600, 30))
        self.assertTrue(config['withsound'])
        self.assertFalse(config['confirmation_sound'])
        self.assertFalse(self.window.customTimingPanel.isVisible())

    def test_settings_show_only_relevant_timing_and_manual_scale_controls(self):
        for name in ('withDebug', 'upperCharsCheck', 'guideLayoutComboBox',
                     'keyWinPosXEdit', 'keyWinPosYEdit'):
            self.assertFalse(hasattr(self.window, name), name)
        self.assertFalse(self.window.customTimingCheck.isVisible())  # Three keys.
        self.window.keySelectionRadioOneKey.click()
        self.assertTrue(self.window.customTimingPanel.isVisible())  # Old gap kept.
        self.assertTrue(self.window.maxDitTimeEdit.isVisible())
        self.window.keySelectionRadioTwoKey.click()
        self.assertFalse(self.window.maxDitTimeEdit.isVisible())
        self.assertTrue(self.window.minLetterPauseEdit.isVisible())
        self.window.customTimingCheck.click()
        self.assertFalse(self.window.customTimingPanel.isVisible())
        self.assertEqual(self.window.collect_config()['minLetterPause'], 0)
        self.assertFalse(self.window.fontSizeScaleEdit.isVisible())
        self.window.guideAutoFitCheckBox.click()
        self.assertTrue(self.window.fontSizeScaleEdit.isVisible())
        self.window.fontSizeScaleEdit.setValue(300)
        self.assertEqual(self.window.collect_config()['fontsizescale'], 300)

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
                    self.assertFalse(view.isVisible())
                    self.assertFalse(view.isMinimized())
                    self.assertTrue(self.window.trayIcon.isVisible())
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

            # Input remains active while the window is hidden in the tray.
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
        self.assertEqual(self.window.currentCharacter, [])
        self.assertEqual(self.window.engine.symbols, [])
        self.assertFalse(self.window.repeaton)
        self.assertIsNone(self.window.codeslayoutview)
        self.assertFalse(view.isVisible())
        self.assertFalse(self.window.trayIcon.isVisible())
        self.assertFalse(self.window.isVisible())
        self.assertFalse(self.window.audioSelector.isVisible())
        self.quit_app.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
