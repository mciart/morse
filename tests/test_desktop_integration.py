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

    def test_default_theme_is_system_and_first_launch_does_not_register_startup(self):
        self.assertEqual(morse.DEFAULT_CONFIG['theme'], 'system')
        self.assertEqual(self.window.themeComboBox.currentData(), 'system')
        with patch.object(self.window.startup_registration, 'set_enabled') as register:
            self.window.presentAtLaunch(startup=True)
            register.assert_not_called()
