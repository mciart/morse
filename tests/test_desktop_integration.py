"""Settings/tray integration; registration and global hotkeys stay mocked."""

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
            self.assertIn('按住拼音／双击显隐', self.window.hotkeyStatus.text())
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
        self.window.pinyinModeComboBox.setCurrentIndex(self.window.pinyinModeComboBox.findData('toggle'))
        self.window.pinyinKeyComboBox.setCurrentIndex(self.window.pinyinKeyComboBox.findData('F21'))
        with patch.object(self.window.guide_hotkey, 'set_sequence'):
            self.window.startDesktopIntegration()
            self.window.pinyinApplyButton.click()
        self.layer_hook.assert_called_with('F21')
        self.assertEqual(self.window.layer_gesture.mode, 'toggle')
        self.assertEqual(self.window.configManager.config['pinyin_layer_key'], 'F21')
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
        self.assertEqual(self.window.themeComboBox.currentData(), 'system')
        with patch.object(self.window.startup_registration, 'set_enabled') as register:
            self.window.presentAtLaunch(startup=True)
            register.assert_not_called()
