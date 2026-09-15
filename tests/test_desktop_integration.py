"""Settings/tray integration; registration and global hotkeys stay mocked."""

import json
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock, patch

import test_ui_behavior as ui

morse = ui.morse


class DesktopIntegrationTests(TestCase):
    setUpClass = classmethod(ui.WindowBehaviorTests.setUpClass.__func__)
    setUp = ui.WindowBehaviorTests.setUp
    tearDown = ui.WindowBehaviorTests.tearDown
    start_input = ui.WindowBehaviorTests.start_input

    def test_launch_at_login_hides_settings_and_normal_launch_shows_it(self):
        self.window.hide()
        self.window.presentAtLaunch(startup=True)
        self.assertFalse(self.window.isVisible())
        self.assertIsNone(self.window.listenerThread)
        self.assertTrue(self.window.trayIcon.isVisible())
        self.window.presentAtLaunch(startup=False)
        self.assertTrue(self.window.isVisible())

    def test_start_in_tray_hides_settings_on_normal_launch(self):
        self.window.hide()
        self.window.config['start_in_tray'] = True
        self.window.presentAtLaunch(startup=False)
        self.assertFalse(self.window.isVisible())
        self.assertIsNone(self.window.listenerThread)
        self.assertTrue(self.window.trayIcon.isVisible())
        self.window.presentAtLaunch(startup=False)
        self.assertFalse(self.window.isVisible())

    def test_start_in_tray_auto_input_starts_without_showing_settings_or_guide(self):
        self.window.hide()
        self.window.config.update(start_in_tray=True, autostart=True)
        with patch.object(morse.VirtualKeyboardView, 'show') as show:
            self.window.presentAtLaunch(startup=False)
        show.assert_not_called()
        view = self.window.codeslayoutview
        self.views.append(view)
        self.assertFalse(view.isVisible())
        self.assertFalse(self.window.isVisible())
        self.assertIsNotNone(self.window.listenerThread)
        self.assertTrue(self.window.onOffAction.isChecked())

    def test_login_auto_input_starts_without_flashing_guide(self):
        self.window.hide()
        self.window.config['autostart'] = True
        with patch.object(morse.VirtualKeyboardView, 'show') as show:
            self.window.presentAtLaunch(startup=True)
        show.assert_not_called()
        view = self.window.codeslayoutview
        self.views.append(view)
        self.assertFalse(view.isVisible())
        self.assertFalse(self.window.isVisible())
        self.assertIsNotNone(self.window.listenerThread)
        self.assertTrue(self.window.onOffAction.isChecked())
        self.window.guide_hotkey.activated.emit()
        self.assertTrue(view.isVisible())

    def test_tray_check_tracks_start_pause_resume_and_return_to_settings(self):
        action = self.window.onOffAction
        self.assertTrue(action.isCheckable())
        self.assertFalse(action.isChecked())
        action.trigger()  # Enable input directly from a tray-only launch.
        self.views.append(self.window.codeslayoutview)
        self.assertTrue(action.isChecked())
        self.assertIsNotNone(self.window.listenerThread)
        action.trigger()
        self.assertFalse(action.isChecked())
        self.assertIsNone(self.window.listenerThread)
        action.trigger()
        self.assertTrue(action.isChecked())
        self.assertIsNotNone(self.window.listenerThread)
        self.window.backToSettings()
        self.assertFalse(action.isChecked())
        self.assertIn('输入已暂停', self.window.trayIcon.toolTip())

    def test_hotkey_toggles_hidden_and_minimized_guide_without_stopping_input(self):
        view, listener = self.start_input()
        self.window.guide_hotkey.activated.emit()
        self.assertFalse(view.isVisible())
        self.assertIs(self.window.listenerThread, listener)
        self.window.guide_hotkey.activated.emit()
        self.assertTrue(view.isVisible())
        view.showMinimized()
        self.window.guide_hotkey.activated.emit()
        self.assertFalse(view.isMinimized())
        self.assertIs(self.window.listenerThread, listener)

    def test_hotkey_choice_is_applied_persisted_and_can_be_disabled(self):
        with patch.object(self.window.guide_hotkey, 'set_sequence') as register:
            self.window.startDesktopIntegration()
            register.assert_called_with('Ctrl+Alt+Shift+M')
            self.window.hotkeyEdit.setKeySequence(morse.QKeySequence('Ctrl+Shift+F10'))
            self.window.hotkeyApplyButton.click()
            register.assert_called_with('Ctrl+Shift+F10')
            self.assertEqual(self.window.configManager.config['guide_hotkey'], 'Ctrl+Shift+F10')
            self.window.hotkeyEnabledCheck.setChecked(False)
            self.window.hotkeyApplyButton.click()
            register.assert_called_with('')
        self.assertEqual(self.window.config['guide_hotkey'], '')

    def test_startup_option_is_the_first_settings_group(self):
        first = self.window.iconGroupBox.layout().itemAt(0).widget()
        self.assertEqual(first.title(), '启动与快捷键')
        self.assertIn('开机自启', self.window.startupCheckbox.text())
        self.assertEqual(self.window.startupCheckbox.isEnabled(),
                         self.window.startup_registration.supported)

    def test_startup_checkbox_writes_only_after_user_action_and_reports_failure(self):
        registration = Mock(supported=True)
        registration.is_enabled.return_value = False
        self.window.startup_registration = registration
        registration.set_enabled.assert_not_called()
        self.window.startupCheckbox.click()
        registration.set_enabled.assert_called_once_with(True)
        registration.set_enabled.side_effect = OSError('注册表不可写')
        with patch.object(morse.QMessageBox, 'warning') as warning:
            self.window.startupCheckbox.click()
        warning.assert_called_once()
        self.assertTrue(self.window.startupCheckbox.isChecked())  # Failed disable rolls back.

    def test_f22_can_be_selected_without_a_physical_function_key(self):
        selector = self.window.hotkeyPresetComboBox
        for number in range(13, 25):
            self.assertGreaterEqual(selector.findData(f'F{number}'), 0)
        selector.setCurrentIndex(selector.findData('F22'))
        self.assertEqual(self.window.selectedGuideHotkey(), 'F22')
        self.assertTrue(self.window.hotkeyEdit.isHidden())
        with patch.object(self.window.guide_hotkey, 'set_sequence') as register:
            self.window.startDesktopIntegration()
            self.window.hotkeyApplyButton.click()
            register.assert_called_with('')  # The same key belongs to the two-gesture listener.
            self.assertIn('单击显隐／双击切换中英文', self.window.hotkeyStatus.text())
        self.assertEqual(self.window.configManager.config['guide_hotkey'], 'F22')
        selector.setCurrentIndex(selector.findData(None))
        self.assertFalse(self.window.hotkeyEdit.isHidden())
        self.window.hotkeyEdit.setKeySequence(morse.QKeySequence('Ctrl+Shift+F10'))
        self.assertEqual(self.window.selectedGuideHotkey(), 'Ctrl+Shift+F10')

    def test_hotkey_rejects_a_key_already_used_for_morse_input(self):
        selector = self.window.hotkeyPresetComboBox
        selector.setCurrentIndex(selector.findData('F22'))
        box = self.window.iconComboBoxKeyOne
        box.setCurrentIndex(box.findData('F22'))
        self.window.hotkeyApplyButton.click()
        self.assertIn('不能与摩斯输入键相同', self.window.hotkeyStatus.text())
        self.assertNotEqual(self.window.config.get('guide_hotkey'), 'F22')
        self.window.hotkeyPresetComboBox.setCurrentIndex(selector.findData(None))
        self.window.hotkeyEdit.setKeySequence(morse.QKeySequence('Ctrl+F22'))
        self.window.hotkeyApplyButton.click()
        self.assertIn('不能与摩斯输入键相同', self.window.hotkeyStatus.text())
        self.assertNotEqual(self.window.config.get('guide_hotkey'), 'Ctrl+F22')

    def test_pinyin_mode_and_key_are_configurable_and_persisted(self):
        self.assertEqual(self.window.selectedPinyinMode(), 'toggle')
        self.assertEqual(self.window.layer_gesture.mode, 'toggle')
        self.assertEqual(self.window.pinyinToggleRadio.text(), '双击切换')
        self.assertIn('单击显示／隐藏码表，双击切换中／英文', self.window.pinyinKeyStatus.text())
        self.window.pinyinHoldRadio.setChecked(True)
        self.window.pinyinKeyComboBox.setCurrentIndex(self.window.pinyinKeyComboBox.findData('F21'))
        with patch.object(self.window.guide_hotkey, 'set_sequence'):
            self.window.startDesktopIntegration()
            self.window.pinyinApplyButton.click()
        self.layer_hook.assert_called_with('F21')
        self.assertEqual(self.window.layer_gesture.mode, 'hold')
        self.assertEqual(self.window.configManager.config['pinyin_layer_key'], 'F21')
        self.assertEqual(self.window.configManager.config['pinyin_layer_mode'], 'hold')
        self.window.pinyinToggleRadio.setChecked(True)
        with patch.object(self.window.guide_hotkey, 'set_sequence'):
            self.window.pinyinApplyButton.click()
        self.assertEqual(self.window.layer_gesture.mode, 'toggle')
        self.assertEqual(self.window.configManager.config['pinyin_layer_mode'], 'toggle')

    def test_disabling_pinyin_restores_same_key_single_hotkey(self):
        self.window.hotkeyPresetComboBox.setCurrentIndex(self.window.hotkeyPresetComboBox.findData('F22'))
        with patch.object(self.window.guide_hotkey, 'set_sequence') as register:
            self.window.startDesktopIntegration()
            self.window.hotkeyApplyButton.click()
            register.assert_called_with('')
            self.window.pinyinLayerCheck.setChecked(False)
            self.window.pinyinApplyButton.click()
            register.assert_called_with('F22')
        self.layer_hook.assert_called_with('')
        self.assertEqual(self.window.config.get('guide_hotkey'), 'F22')

    def test_pinyin_switch_mode_and_ime_sync_option_survive_settings_reload(self):
        self.window.pinyinHoldRadio.setChecked(True)
        self.window.imeSyncCheck.setChecked(True)
        self.window.pinyinApplyButton.click()
        restored = morse.ConfigManager(self.window.configManager.config_file)
        self.assertEqual(restored.config['pinyin_layer_mode'], 'hold')
        self.assertTrue(restored.config['pinyin_ime_sync'])
        self.assertFalse(self.window.ime_sync.enabled)  # Settings alone do not write to the IME.

    def test_autostart_input_choice_persists_without_a_save_button(self):
        self.assertFalse(hasattr(self.window, 'SaveButton'))
        self.window.autostartCheckbox.setChecked(True)
        saved = json.loads(Path(self.window.configManager.config_file).read_text(encoding='utf-8'))
        self.assertTrue(saved['autostart'])
        self.window.autostartCheckbox.setChecked(False)
        saved = json.loads(Path(self.window.configManager.config_file).read_text(encoding='utf-8'))
        self.assertFalse(saved['autostart'])
        self.window.startInTrayCheckbox.setChecked(True)
        saved = json.loads(Path(self.window.configManager.config_file).read_text(encoding='utf-8'))
        self.assertTrue(saved['start_in_tray'])
        self.window.startInTrayCheckbox.setChecked(False)
        saved = json.loads(Path(self.window.configManager.config_file).read_text(encoding='utf-8'))
        self.assertFalse(saved['start_in_tray'])

    def test_invalid_saved_pinyin_binding_remains_visible_as_an_error(self):
        self.window.config.update(pinyin_layer_key='F23', keyone='F23')
        with patch.object(self.window.guide_hotkey, 'set_sequence'), \
             patch.object(self.window.guide_key, 'set_key',
                          side_effect=lambda key: self.window.pinyinKeyReady(key)):
            self.window.startDesktopIntegration()
        self.assertIn('冲突', self.window.pinyinKeyStatus.text())
        self.assertFalse(self.window.guide_key_timer.isActive())
        self.assertEqual(self.window.config['pinyin_layer_key'], 'F23')

    def test_guide_restore_uses_no_activation_helper(self):
        view, _listener = self.start_input()
        view.hide()
        with patch.object(morse, 'show_guide_without_activation') as restore:
            self.window.showCurrentWindow()
        restore.assert_called_once_with(view)

    def test_conflicting_legacy_hotkey_is_reported_at_startup_without_overwriting_it(self):
        self.window.config.update(keyone='F22', guide_hotkey='Ctrl+F22')
        with patch.object(self.window.guide_hotkey, 'set_sequence') as register:
            self.window.startDesktopIntegration()
        register.assert_not_called()
        self.assertIn('不能与摩斯输入键相同', self.window.hotkeyStatus.text())
        self.assertEqual(self.window.config['guide_hotkey'], 'Ctrl+F22')

    def test_compact_choice_syncs_between_guide_tray_and_settings(self):
        self.window.goForIt()
        view = self.window.codeslayoutview
        self.views.append(view)
        self.window.compactGuideAction.trigger()
        self.assertTrue(view.isCompactMode())
        self.assertTrue(self.window.guideCompactCheckBox.isChecked())
        self.assertTrue(self.window.configManager.config['guide_compact'])
        view.setCompactMode(False)
        self.assertFalse(self.window.compactGuideAction.isChecked())
        self.assertFalse(self.window.guideCompactCheckBox.isChecked())
        self.assertFalse(self.window.configManager.config['guide_compact'])

    def test_compact_resize_is_saved_and_reused_when_input_restarts(self):
        self.window.goForIt()
        view = self.window.codeslayoutview
        self.views.append(view)
        view.setCompactMode(True)
        listener = self.window.listenerThread
        view.setCompactScale(0.9)
        self.assertEqual(self.window.configManager.config['guide_compact_scale'], 0.9)
        self.assertIs(self.window.listenerThread, listener)
        self.assertEqual(self.window.collect_config()['guide_compact_scale'], 0.9)
        self.window.backToSettings()
        self.views.remove(view)  # stopIt already scheduled this guide for deletion.
        self.window.goForIt()
        restarted = self.window.codeslayoutview
        self.views.append(restarted)
        self.assertTrue(restarted.isCompactMode())
        self.assertEqual(restarted.compactScale(), 0.9)

    def test_default_theme_is_system_and_first_launch_does_not_register_startup(self):
        self.assertEqual(morse.DEFAULT_CONFIG['theme'], 'system')
        self.assertFalse(morse.DEFAULT_CONFIG['start_in_tray'])
        self.assertFalse(self.window.startInTrayCheckbox.isChecked())
        self.assertEqual(self.window.themeComboBox.currentData(), 'system')
        with patch.object(self.window.startup_registration, 'set_enabled') as register:
            self.window.presentAtLaunch(startup=True)
            register.assert_not_called()

    def test_audio_selector_stays_off_screen_until_opened(self):
        selector = self.window.audioSelector
        self.assertFalse(selector.isVisible())
        self.assertTrue(selector.testAttribute(morse.Qt.WA_DontShowOnScreen))
        selector.show()
        self.assertFalse(selector.testAttribute(morse.Qt.WA_DontShowOnScreen))

    def test_session_end_quits_so_installer_can_replace_files(self):
        with patch.object(self.window, 'quitApplication') as quit:
            self.window.startDesktopIntegration()
            self.window._commitSessionData(None)
            quit.assert_called_once_with()
        self.window.startDesktopIntegration()
        self.assertTrue(self.window.trayIcon.isVisible())

    def test_tray_retry_timer_runs_on_windows_platform(self):
        with patch.object(morse.QApplication, 'platformName', return_value='windows'):
            self.window.startDesktopIntegration()
        self.assertTrue(self.window._tray_retry_timer.isActive())
        self.window._tray_retry_timer.stop()

    def test_second_launch_activation_restores_hidden_window_and_tray(self):
        self.window.hide()
        self.window.activateRunningInstance()
        self.assertTrue(self.window.isVisible())
        self.assertTrue(self.window.trayIcon.isVisible())

    def test_installer_launch_announces_tray(self):
        with patch.object(self.window.trayIcon, 'showMessage') as balloon:
            self.window._announceInstallerTray()
        self.assertEqual(balloon.call_args[0][0], '摩斯输入')
        self.assertIn('系统托盘', balloon.call_args[0][1])

    def test_hidden_launch_clears_off_screen_flag_so_tray_can_appear(self):
        self.window.hide()
        self.window.setAttribute(morse.Qt.WA_DontShowOnScreen, True)
        self.window.presentAtLaunch(startup=True)
        self.assertFalse(self.window.isVisible())
        self.assertFalse(self.window.testAttribute(morse.Qt.WA_DontShowOnScreen))
        self.assertTrue(self.window.trayIcon.isVisible())
        self.assertIs(self.window.trayIcon.parent(), self.app)

    def test_start_in_tray_does_not_mark_settings_off_screen(self):
        self.window.hide()
        self.window.setAttribute(morse.Qt.WA_DontShowOnScreen, True)
        self.window.config['start_in_tray'] = True
        self.window.presentAtLaunch(startup=False)
        self.assertFalse(self.window.isVisible())
        self.assertFalse(self.window.testAttribute(morse.Qt.WA_DontShowOnScreen))
        self.assertTrue(self.window.trayIcon.isVisible())
