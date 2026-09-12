"""Windows integration tests use fake registry/native APIs, never real settings."""

import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import unittest
from unittest.mock import MagicMock, Mock, call, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt5.QtCore import QEvent, QObject, Qt, pyqtSignal
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import QApplication

import windows_integration as integration


def fake_registry():
    registry = MagicMock()
    registry.HKEY_CURRENT_USER = 'current-user'
    registry.KEY_READ = 1
    registry.KEY_SET_VALUE = 2
    registry.REG_SZ = 1
    return registry


class StartupRegistrationTests(unittest.TestCase):
    def registration(self, registry=None, **options):
        return integration.StartupRegistration(
            executable=r'C:\Program Files\Morse\MorseWriter.exe', frozen=True,
            platform_name='Windows', registry=registry or fake_registry(), **options)

    def test_frozen_command_quotes_executable_and_has_startup_flag(self):
        registration = self.registration()
        self.assertEqual(registration.command,
                         '"C:\\Program Files\\Morse\\MorseWriter.exe" --startup')

    def test_default_install_path_matches_installers_always_quoted_run_entry(self):
        registry = fake_registry()
        executable = r'C:\Users\Admin\AppData\Local\Programs\MorseWriter\MorseWriter.exe'
        registration = integration.StartupRegistration(executable=executable, frozen=True,
                                                       registry=registry, platform_name='Windows')
        installer_command = '"' + executable + '" --startup'
        registry.QueryValueEx.return_value = (installer_command, registry.REG_SZ)
        self.assertEqual(registration.command, installer_command)
        self.assertTrue(registration.is_enabled())

    def test_source_interpreter_is_quoted_even_without_spaces(self):
        with patch.object(Path, 'is_file', return_value=True):
            command = integration.startup_command(executable=r'C:\Python\python.exe',
                                                    script_path=r'C:\Morse\MorseCodeGUI.py', frozen=False)
        self.assertEqual(command, '"C:\\Python\\pythonw.exe" C:\\Morse\\MorseCodeGUI.py --startup')

    def test_source_command_uses_absolute_pythonw_script_and_quotes_both(self):
        with patch.object(Path, 'is_file', return_value=True):
            command = integration.startup_command(
                executable=r'C:\Code Tools\python.exe',
                script_path=r'C:\用户 项目\MorseCodeGUI.py', frozen=False)
        self.assertEqual(command,
                         '"C:\\Code Tools\\pythonw.exe" "C:\\用户 项目\\MorseCodeGUI.py" --startup')

    def test_constructor_and_status_never_write_registry(self):
        registry = fake_registry()
        registration = self.registration(registry)
        registry.QueryValueEx.return_value = (registration.command, registry.REG_SZ)
        self.assertTrue(registration.is_enabled())
        registry.CreateKeyEx.assert_not_called()
        registry.SetValueEx.assert_not_called()
        registry.DeleteValue.assert_not_called()
        registry.OpenKey.assert_called_once_with('current-user', integration.RUN_KEY, 0, registry.KEY_READ)

    def test_stale_command_and_missing_value_are_not_reported_as_this_app_enabled(self):
        registry = fake_registry()
        registration = self.registration(registry)
        registry.QueryValueEx.return_value = ('different.exe --startup', registry.REG_SZ)
        self.assertFalse(registration.is_enabled())
        registry.QueryValueEx.side_effect = FileNotFoundError()
        self.assertFalse(registration.is_enabled())

    def test_enable_writes_only_current_users_named_run_value(self):
        registry = fake_registry()
        registration = self.registration(registry)
        self.assertTrue(registration.set_enabled(True))
        registry.CreateKeyEx.assert_called_once_with('current-user', integration.RUN_KEY, 0,
                                                      registry.KEY_SET_VALUE)
        key = registry.CreateKeyEx.return_value.__enter__.return_value
        registry.SetValueEx.assert_called_once_with(key, 'MorseWriter', 0, registry.REG_SZ,
                                                    registration.command)
        registry.DeleteValue.assert_not_called()

    def test_disable_deletes_only_named_value_and_missing_value_is_harmless(self):
        registry = fake_registry()
        registration = self.registration(registry)
        self.assertFalse(registration.set_enabled(False))
        registry.DeleteValue.assert_called_once_with(
            registry.OpenKey.return_value.__enter__.return_value, 'MorseWriter')
        registry.DeleteValue.side_effect = FileNotFoundError()
        self.assertFalse(registration.set_enabled(False))
        registry.SetValueEx.assert_not_called()

    def test_access_error_is_visible_and_overlong_command_is_not_written(self):
        registry = fake_registry()
        registration = self.registration(registry)
        registry.CreateKeyEx.side_effect = PermissionError('denied')
        with self.assertRaisesRegex(RuntimeError, '无法修改开机自启设置'):
            registration.set_enabled(True)
        registry.CreateKeyEx.reset_mock(side_effect=True)
        registration.command = 'x' * 261
        with self.assertRaisesRegex(ValueError, '启动路径过长'):
            registration.set_enabled(True)
        registry.CreateKeyEx.assert_not_called()

    def test_unsupported_platform_is_read_only_and_reports_setting_error(self):
        registry = fake_registry()
        registration = integration.StartupRegistration(registry=registry, platform_name='Linux')
        self.assertFalse(registration.supported)
        self.assertFalse(registration.is_enabled())
        with self.assertRaisesRegex(RuntimeError, '当前系统不支持'):
            registration.set_enabled(True)
        self.assertEqual(registry.mock_calls, [])


class HotkeyParsingTests(unittest.TestCase):
    def test_default_and_navigation_are_keyboard_virtual_keys(self):
        self.assertEqual(integration.parse_hotkey('Ctrl+Alt+M'), ('Ctrl+Alt+M', 3, ord('M')))
        self.assertEqual(integration.parse_hotkey('Alt+Left'), ('Alt+Left', 1, 0x25))
        self.assertEqual(integration.parse_hotkey(QKeySequence('Ctrl+Space')), ('Ctrl+Space', 2, 0x20))

    def test_function_keys_include_rare_f23_f24(self):
        self.assertEqual(integration.parse_hotkey('F23'), ('F23', 0, 0x86))
        self.assertEqual(integration.parse_hotkey('Ctrl+Shift+F24'), ('Ctrl+Shift+F24', 6, 0x87))

    def test_every_extended_function_key_can_be_a_standalone_shortcut(self):
        for number in range(13, 25):
            with self.subTest(number=number):
                name = 'F' + str(number)
                self.assertEqual(integration.parse_hotkey(name), (name, 0, 0x70 + number - 1))

    def test_shifted_symbols_have_required_windows_shift_modifier(self):
        self.assertEqual(integration.parse_hotkey('Ctrl+!'), ('Ctrl+!', 6, ord('1')))
        self.assertEqual(integration.parse_hotkey('Ctrl++'), ('Ctrl++', 6, 0xBB))

    def test_bare_typing_debugger_and_multistroke_shortcuts_are_rejected(self):
        for sequence in ('M', 'Shift+M', 'Space', 'F12', 'Ctrl+F12', 'Ctrl+K, Ctrl+C', ''):
            with self.subTest(sequence=sequence), self.assertRaises(ValueError):
                integration.parse_hotkey(sequence)

    def test_gamepad_mouse_and_unknown_input_are_not_accepted_as_vk(self):
        for sequence in ('Gamepad A', 'Mouse X1', 'Ctrl+鼠'):
            with self.subTest(sequence=sequence), self.assertRaises(ValueError):
                integration.parse_hotkey(sequence)


def fake_native(messages=()):
    user32, kernel32 = Mock(), Mock()
    user32.RegisterHotKey.return_value = 1
    user32.UnregisterHotKey.return_value = 1
    user32.PostThreadMessageW.return_value = 1
    kernel32.GetCurrentThreadId.return_value = 12345
    pending = list(messages)
    def peek(address, window, first, last, remove):
        if not remove or not pending:
            return 0
        message, identifier = pending.pop(0)
        result = ctypes.cast(address, ctypes.POINTER(wintypes.MSG)).contents
        result.message, result.wParam = message, identifier
        return 1
    user32.PeekMessageW.side_effect = peek
    return user32, kernel32


class NativeHotkeyTests(unittest.TestCase):
    def loop(self, messages=()):
        user32, kernel32 = fake_native(messages)
        activated, ready = Mock(), Mock()
        loop = integration.WindowsHotkeyLoop('Ctrl+Alt+M', 3, ord('M'), activated, ready,
                                              user32=user32, kernel32=kernel32)
        user32.MsgWaitForMultipleObjects.side_effect = lambda *args: loop.stop() or 0x102
        return loop, user32, kernel32, activated, ready

    def test_registers_one_nonrepeating_shortcut_delivers_it_and_unregisters(self):
        loop, user32, _, activated, ready = self.loop([(integration.WM_HOTKEY, integration.HOTKEY_ID)])
        loop.run()
        user32.RegisterHotKey.assert_called_once_with(None, integration.HOTKEY_ID,
                                                       3 | integration.MOD_NOREPEAT, ord('M'))
        activated.assert_called_once_with()
        ready.assert_called_once_with('Ctrl+Alt+M')
        user32.UnregisterHotKey.assert_called_once_with(None, integration.HOTKEY_ID)
        self.assertIsNone(loop._thread_id)

    def test_f22_registers_its_keyboard_vk_without_gamepad_or_modifier_keys(self):
        user32, kernel32 = fake_native([(integration.WM_HOTKEY, integration.HOTKEY_ID)])
        activated = Mock()
        loop = integration.WindowsHotkeyLoop(*integration.parse_hotkey('F22'), activated,
                                              user32=user32, kernel32=kernel32)
        user32.MsgWaitForMultipleObjects.side_effect = lambda *args: loop.stop() or 0x102
        loop.run()
        user32.RegisterHotKey.assert_called_once_with(None, integration.HOTKEY_ID,
                                                       integration.MOD_NOREPEAT, 0x85)
        activated.assert_called_once_with()
        user32.UnregisterHotKey.assert_called_once_with(None, integration.HOTKEY_ID)

    def test_other_hotkey_ids_do_not_activate_the_guide(self):
        loop, user32, _, activated, _ = self.loop([(integration.WM_HOTKEY, 987), (0x0100, 0)])
        loop.run()
        activated.assert_not_called()
        self.assertEqual(user32.DispatchMessageW.call_count, 2)

    def test_conflict_is_reported_without_unregistering_an_unowned_hotkey(self):
        loop, user32, _, activated, ready = self.loop()
        user32.RegisterHotKey.return_value = 0
        with patch.object(integration.ctypes, 'get_last_error', return_value=1409):
            with self.assertRaisesRegex(RuntimeError, '已被系统或其他程序占用'):
                loop.run()
        ready.assert_not_called()
        user32.UnregisterHotKey.assert_not_called()
        self.assertIsNone(loop._thread_id)

    def test_stop_during_registration_releases_hotkey_without_reporting_ready(self):
        loop, user32, _, _, ready = self.loop()
        user32.RegisterHotKey.side_effect = lambda *args: loop.stop() or 1
        loop.run()
        ready.assert_not_called()
        user32.UnregisterHotKey.assert_called_once_with(None, integration.HOTKEY_ID)
        user32.MsgWaitForMultipleObjects.assert_not_called()

    def test_stop_before_registration_installs_nothing(self):
        loop, user32, _, _, ready = self.loop()
        loop.stop()
        loop.run()
        user32.RegisterHotKey.assert_not_called()
        ready.assert_not_called()
        self.assertIsNone(loop._thread_id)

    def test_failed_wakeup_post_still_ends_on_bounded_wait(self):
        loop, user32, _, _, _ = self.loop()
        user32.PostThreadMessageW.return_value = 0
        loop.run()
        user32.MsgWaitForMultipleObjects.assert_called_once_with(0, None, False, 100, 0x04FF)
        user32.UnregisterHotKey.assert_called_once_with(None, integration.HOTKEY_ID)

    def test_wait_failure_still_releases_the_registered_shortcut(self):
        loop, user32, _, _, _ = self.loop()
        user32.MsgWaitForMultipleObjects.side_effect = None
        user32.MsgWaitForMultipleObjects.return_value = 0xFFFFFFFF
        with self.assertRaisesRegex(RuntimeError, '消息循环失败'):
            loop.run()
        user32.UnregisterHotKey.assert_called_once_with(None, integration.HOTKEY_ID)

    def test_native_message_result_and_parameters_are_pointer_sized(self):
        loop, user32, _, _, _ = self.loop()
        self.assertEqual(ctypes.sizeof(user32.DispatchMessageW.restype), ctypes.sizeof(ctypes.c_void_p))
        self.assertEqual(ctypes.sizeof(user32.PostThreadMessageW.argtypes[2]), ctypes.sizeof(ctypes.c_void_p))
        self.assertEqual(ctypes.sizeof(user32.PostThreadMessageW.argtypes[3]), ctypes.sizeof(ctypes.c_void_p))

    def test_qthread_catches_native_start_failure_instead_of_escaping_run(self):
        thread = integration._HotkeyThread(('Ctrl+Alt+M', 3, ord('M')))
        error = Mock()
        thread.error.connect(error)
        with patch.object(integration, 'WindowsHotkeyLoop', side_effect=RuntimeError('failed')), \
                patch.object(integration.logging, 'exception'):
            thread.run()
        error.assert_called_once_with('failed')


class GuideVisibilityTests(unittest.TestCase):
    def native_window(self):
        window, user32 = Mock(), Mock()
        window.winId.return_value = 0x100001234
        window.isMinimized.return_value = True
        window.testAttribute.return_value = False
        user32.SetWindowPos.return_value = 1
        return window, user32

    def test_native_show_restores_and_raises_without_any_activating_qt_call(self):
        window, user32 = self.native_window()
        operations = Mock()
        operations.attach_mock(window, 'window')
        operations.attach_mock(user32, 'native')
        self.assertTrue(integration.show_guide_without_activation(
            window, user32=user32, platform_name='Windows'))
        self.assertEqual(operations.mock_calls, [
            call.window.setAttribute(Qt.WA_ShowWithoutActivating, True),
            call.window.testAttribute(Qt.WA_DontShowOnScreen),
            call.window.show(), call.window.winId(), call.window.isMinimized(),
            call.native.ShowWindow(0x100001234, 4),
            call.native.SetWindowPos(0x100001234, -1, 0, 0, 0, 0, 0x53),
        ])
        window.showNormal.assert_not_called()
        window.raise_.assert_not_called()
        window.activateWindow.assert_not_called()
        user32.SetForegroundWindow.assert_not_called()

    def test_nonminimized_show_preserves_maximized_native_window_state(self):
        window, user32 = self.native_window()
        window.isMinimized.return_value = False
        integration.show_guide_without_activation(window, user32=user32, platform_name='Windows')
        user32.ShowWindow.assert_called_once_with(0x100001234, 8)
        window.showNormal.assert_not_called()
        window.setWindowState.assert_not_called()

    def test_minimized_frame_change_uses_native_nonactivating_minimize(self):
        window, user32 = self.native_window()
        # Changing Qt window flags has already cleared the old window state.
        window.isMinimized.return_value = False
        self.assertTrue(integration.show_guide_without_activation(
            window, keep_minimized=True, user32=user32, platform_name='Windows'))
        user32.ShowWindow.assert_called_once_with(0x100001234, 7)
        window.activateWindow.assert_not_called()
        window.showNormal.assert_not_called()
        user32.SetForegroundWindow.assert_not_called()

    def test_previous_hidden_showwindow_result_is_not_treated_as_an_error(self):
        window, user32 = self.native_window()
        user32.ShowWindow.return_value = 0
        self.assertTrue(integration.show_guide_without_activation(
            window, user32=user32, platform_name='Windows'))
        user32.SetWindowPos.assert_called_once()

    def test_position_failure_is_logged_without_activating_fallback(self):
        window, user32 = self.native_window()
        user32.SetWindowPos.return_value = 0
        with patch.object(integration.ctypes, 'get_last_error', return_value=5), \
                patch.object(integration.logging, 'warning') as warning:
            self.assertFalse(integration.show_guide_without_activation(
                window, user32=user32, platform_name='Windows'))
        warning.assert_called_once()
        self.assertEqual(warning.call_args.args[-1], 5)
        window.activateWindow.assert_not_called()
        window.showNormal.assert_not_called()
        user32.SetForegroundWindow.assert_not_called()

    def test_recreated_window_uses_its_current_handle(self):
        window, user32 = self.native_window()
        window.winId.side_effect = [0x100001234, 0x100005678]
        for _ in range(2):
            integration.show_guide_without_activation(window, user32=user32, platform_name='Windows')
        self.assertEqual(user32.ShowWindow.call_args_list,
                         [call(0x100001234, 4), call(0x100005678, 4)])
        self.assertEqual(user32.SetWindowPos.call_args.args[0], 0x100005678)

    def test_native_window_handles_are_pointer_sized(self):
        window, user32 = self.native_window()
        integration.show_guide_without_activation(window, user32=user32, platform_name='Windows')
        for function, indices in ((user32.ShowWindow, (0,)), (user32.SetWindowPos, (0, 1))):
            for index in indices:
                self.assertEqual(ctypes.sizeof(function.argtypes[index]), ctypes.sizeof(ctypes.c_void_p))

    def test_other_platform_uses_qt_without_loading_windows_api(self):
        window = Mock()
        with patch.object(integration.ctypes, 'WinDLL') as loader:
            self.assertTrue(integration.show_guide_without_activation(window, platform_name='Linux'))
        loader.assert_not_called()
        window.setAttribute.assert_called_once_with(Qt.WA_ShowWithoutActivating, True)
        window.showNormal.assert_called_once_with()
        window.raise_.assert_called_once_with()
        window.activateWindow.assert_not_called()
        window.winId.assert_not_called()

    def test_offscreen_qt_ids_are_never_passed_to_native_windows_api(self):
        window = Mock()
        window.testAttribute.return_value = False
        with patch.object(integration.QGuiApplication, 'platformName', return_value='offscreen'), \
                patch.object(integration.ctypes, 'WinDLL') as loader:
            self.assertTrue(integration.show_guide_without_activation(window, platform_name='Windows'))
        loader.assert_not_called()
        window.showNormal.assert_called_once_with()
        window.winId.assert_not_called()

    def test_dont_show_on_screen_never_calls_native_display_even_with_windows_backend(self):
        for minimized in (False, True):
            with self.subTest(minimized=minimized):
                window, user32 = self.native_window()
                window.testAttribute.return_value = True
                with patch.object(integration.QGuiApplication, 'platformName', return_value='windows'):
                    self.assertTrue(integration.show_guide_without_activation(
                        window, keep_minimized=minimized, user32=user32, platform_name='Windows'))
                user32.ShowWindow.assert_not_called()
                user32.SetWindowPos.assert_not_called()
                window.winId.assert_not_called()
                (window.showMinimized if minimized else window.showNormal).assert_called_once_with()

    def test_minimized_frame_change_without_native_backend_stays_minimized(self):
        window = Mock()
        self.assertTrue(integration.show_guide_without_activation(
            window, keep_minimized=True, platform_name='Linux'))
        window.showMinimized.assert_called_once_with()
        window.showNormal.assert_not_called()
        window.raise_.assert_not_called()


class FakeHotkeyThread(QObject):
    activated = pyqtSignal()
    ready = pyqtSignal(str)
    error = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, parsed):
        super().__init__()
        self.parsed = parsed
        self.start = Mock()
        self.stop = Mock()


class GlobalHotkeyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.threads = []
        def factory(parsed):
            thread = FakeHotkeyThread(parsed)
            self.threads.append(thread)
            return thread
        self.controller = integration.GlobalHotkey(thread_factory=factory, platform_name='Windows')

    def tearDown(self):
        self.controller.stop()
        self.controller.deleteLater()
        self.app.sendPostedEvents(None, QEvent.DeferredDelete)

    def test_ready_and_activation_are_forwarded_only_from_current_thread(self):
        ready, activated = Mock(), Mock()
        self.controller.ready.connect(ready)
        self.controller.activated.connect(activated)
        self.assertTrue(self.controller.set_sequence('Ctrl+Alt+M'))
        first = self.threads[0]
        first.start.assert_called_once_with()
        first.ready.emit('Ctrl+Alt+M')
        first.activated.emit()
        ready.assert_called_once_with('Ctrl+Alt+M')
        activated.assert_called_once_with()
        self.assertEqual(self.controller.active_sequence, 'Ctrl+Alt+M')

    def test_rebind_stops_old_registration_before_starting_new_and_ignores_old_signals(self):
        self.controller.set_sequence('Ctrl+Alt+M')
        first = self.threads[0]
        activated = Mock()
        self.controller.activated.connect(activated)
        self.assertTrue(self.controller.set_sequence('Ctrl+Alt+N'))
        first.stop.assert_called_once_with()
        self.threads[1].start.assert_called_once_with()
        first.activated.emit()
        first.ready.emit('Ctrl+Alt+M')
        activated.assert_not_called()
        self.assertEqual(self.controller.active_sequence, '')

    def test_invalid_rebind_keeps_existing_registration(self):
        self.controller.set_sequence('Ctrl+Alt+M')
        first = self.threads[0]
        first.ready.emit('Ctrl+Alt+M')
        error = Mock()
        self.controller.error.connect(error)
        self.assertFalse(self.controller.set_sequence('M'))
        first.stop.assert_not_called()
        self.assertEqual(self.controller.active_sequence, 'Ctrl+Alt+M')
        error.assert_called_once()

    def test_reapplying_working_shortcut_reports_ready_after_validation_error(self):
        self.controller.set_sequence('Ctrl+Alt+M')
        first = self.threads[0]
        first.ready.emit('Ctrl+Alt+M')
        self.assertFalse(self.controller.set_sequence('M'))
        ready = Mock()
        self.controller.ready.connect(ready)
        self.assertTrue(self.controller.set_sequence('Ctrl+Alt+M'))
        ready.assert_called_once_with('Ctrl+Alt+M')
        first.stop.assert_not_called()
        first.start.assert_called_once_with()
        self.assertEqual(len(self.threads), 1)

    def test_reapplying_pending_shortcut_does_not_report_ready_early(self):
        ready = Mock()
        self.controller.ready.connect(ready)
        self.controller.set_sequence('Ctrl+Alt+M')
        self.assertTrue(self.controller.set_sequence('Ctrl+Alt+M'))
        ready.assert_not_called()
        self.assertEqual(self.controller.active_sequence, '')
        self.assertEqual(len(self.threads), 1)
        self.threads[0].start.assert_called_once_with()

    def test_empty_sequence_stops_without_installing_a_replacement(self):
        self.controller.set_sequence()
        self.assertTrue(self.controller.set_sequence(''))
        self.assertEqual(len(self.threads), 1)
        self.threads[0].stop.assert_called_once_with()
        self.assertEqual(self.controller.active_sequence, '')
        self.assertEqual(self.controller.sequence, '')

    def test_native_error_is_visible_and_finished_thread_can_be_retried(self):
        self.controller.set_sequence()
        error = Mock()
        self.controller.error.connect(error)
        self.threads[0].error.emit('快捷键已被占用')
        self.threads[0].finished.emit()
        error.assert_called_once_with('快捷键已被占用')
        self.assertEqual(self.controller.active_sequence, '')
        self.assertTrue(self.controller.set_sequence())
        self.assertEqual(len(self.threads), 2)

    def test_unsupported_platform_never_creates_worker(self):
        self.controller.supported = False
        error = Mock()
        self.controller.error.connect(error)
        self.assertFalse(self.controller.set_sequence())
        self.assertEqual(self.threads, [])
        error.assert_called_once()


if __name__ == '__main__':
    unittest.main()
