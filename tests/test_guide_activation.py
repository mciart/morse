"""Guide activation guards, without global input or other application windows."""

import ctypes
from ctypes import wintypes
import os
import unittest
from unittest.mock import Mock, call, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt5.QtGui import QMouseEvent
from PyQt5.QtWidgets import QApplication

import windows_integration as integration


class GuideActivationTests(unittest.TestCase):
    def native_window(self, style=0x00080008):
        window, api = Mock(), Mock()
        window.testAttribute.side_effect = lambda attribute: attribute == Qt.WA_WState_Created
        window.effectiveWinId.return_value = 0x100001234
        window.find.return_value = window
        api.GetWindowLongPtrW.return_value = style
        api.SetWindowLongPtrW.return_value = style
        api.SetWindowPos.return_value = 1
        return window, api

    def protect(self, window, api, **kwargs):
        return integration.protect_guide_window(window, user32=api,
                                                 platform_name='Windows', **kwargs)

    def test_mouse_press_and_hover_decline_activation_without_eating_input(self):
        for mouse_message in (0, 0x0201, 0x0204):
            message = wintypes.MSG()
            message.hWnd = 0x100001234
            message.message = integration.WM_MOUSEACTIVATE
            message.lParam = (mouse_message << 16) | 1
            self.assertEqual(integration.guide_mouse_activation_event(
                b'windows_generic_MSG', ctypes.addressof(message)), (True, 3))

    def test_other_native_messages_are_not_consumed(self):
        message = wintypes.MSG()
        for kind in (0x0200, 0x0201, 0x0202, 0x0006, 0x0010):
            message.message = kind
            self.assertIsNone(integration.guide_mouse_activation_event(
                b'windows_generic_MSG', ctypes.addressof(message)))
        self.assertIsNone(integration.guide_mouse_activation_event(b'xcb_generic_event_t', 0))
        self.assertIsNone(integration.guide_mouse_activation_event(b'windows_generic_MSG', 0))

    def test_native_style_preserves_transparency_topmost_and_taskbar(self):
        window, api = self.native_window()
        self.assertTrue(self.protect(window, api))
        api.SetWindowLongPtrW.assert_called_once_with(0x100001234, -20, 0x080C0008)
        api.SetWindowPos.assert_called_once_with(0x100001234, None, 0, 0, 0, 0, 0x237)
        for method in ('SetForegroundWindow', 'SetActiveWindow', 'SetFocus', 'ShowWindow'):
            getattr(api, method).assert_not_called()
        window.winId.assert_not_called()
        window.activateWindow.assert_not_called()

    def test_menu_protection_removes_taskbar_entry_and_preserves_other_bits(self):
        window, api = self.native_window(0x00040088)
        self.assertTrue(self.protect(window, api, keep_taskbar=False))
        api.SetWindowLongPtrW.assert_called_once_with(0x100001234, -20, 0x08000088)

    def test_already_protected_window_does_not_reapply_native_styles(self):
        window, api = self.native_window(0x080C0008)
        self.assertTrue(self.protect(window, api))
        api.SetWindowLongPtrW.assert_not_called()
        api.SetWindowPos.assert_not_called()

    def test_recreated_window_uses_fresh_existing_handle_without_forcing_creation(self):
        window, api = self.native_window()
        window.effectiveWinId.side_effect = [0x100001234, 0x100005678]
        self.protect(window, api)
        self.protect(window, api)
        self.assertEqual(api.GetWindowLongPtrW.call_args_list,
                         [call(0x100001234, -20), call(0x100005678, -20)])
        window.winId.assert_not_called()

    def test_window_handles_and_longptr_values_are_pointer_sized(self):
        window, api = self.native_window()
        self.protect(window, api)
        pointer_size = ctypes.sizeof(ctypes.c_void_p)
        self.assertEqual(ctypes.sizeof(api.GetWindowLongPtrW.restype), pointer_size)
        self.assertEqual(ctypes.sizeof(api.SetWindowLongPtrW.argtypes[2]), pointer_size)
        self.assertEqual(ctypes.sizeof(api.SetWindowLongPtrW.argtypes[0]), pointer_size)

    def test_detaching_popup_cannot_apply_menu_styles_to_its_ancestor(self):
        window, api = self.native_window()
        window.find.return_value = Mock()  # effectiveWinId fell back to parent.
        self.assertTrue(self.protect(window, api, keep_taskbar=False))
        self.assertFalse(api.mock_calls)
        window.winId.assert_not_called()

    def test_uncreated_offscreen_and_destroyed_windows_never_receive_native_calls(self):
        for state in ('uncreated', 'offscreen', 'destroyed'):
            window, api = self.native_window()
            if state == 'uncreated':
                window.testAttribute.side_effect = lambda attribute: False
            elif state == 'offscreen':
                window.testAttribute.side_effect = lambda attribute: True
            else:
                window.effectiveWinId.return_value = 0
            self.assertTrue(self.protect(window, api))
            self.assertFalse(api.mock_calls)
            window.winId.assert_not_called()

    def test_non_native_backends_do_not_load_user32(self):
        window, _ = self.native_window()
        with patch.object(integration.QGuiApplication, 'platformName', return_value='offscreen'), \
                patch.object(integration.ctypes, 'WinDLL') as loader:
            self.assertTrue(integration.protect_guide_window(window, platform_name='Windows'))
            self.assertTrue(integration.protect_guide_window(window, platform_name='Linux'))
        loader.assert_not_called()
        window.effectiveWinId.assert_not_called()

    def test_native_failures_report_failure_without_an_activating_fallback(self):
        for operation in ('read', 'write', 'refresh'):
            window, api = self.native_window()
            getattr(api, {'read': 'GetWindowLongPtrW', 'write': 'SetWindowLongPtrW',
                          'refresh': 'SetWindowPos'}[operation]).return_value = 0
            with patch.object(integration.ctypes, 'get_last_error', return_value=5), \
                    patch.object(integration.logging, 'warning') as warning:
                self.assertFalse(self.protect(window, api))
            warning.assert_called_once()
            api.SetForegroundWindow.assert_not_called()
            window.activateWindow.assert_not_called()


class GuideMenuActivationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self):
        for widget in self.app.topLevelWidgets():
            if isinstance(widget, integration.NonActivatingMenu):
                widget.hide()
                widget.deleteLater()
        self.app.sendPostedEvents(None, QEvent.DeferredDelete)

    def test_submenus_retain_popup_behavior_and_mouse_activation_protection(self):
        menu = integration.NonActivatingMenu()
        submenu = menu.addMenu('调整大小')
        submenu.addAction('放大')
        for popup in (menu, submenu):
            self.assertIsInstance(popup, integration.NonActivatingMenu)
            self.assertEqual(popup.windowType(), Qt.Popup)
            self.assertTrue(popup.windowFlags() & Qt.WindowDoesNotAcceptFocus)
            self.assertTrue(popup.testAttribute(Qt.WA_ShowWithoutActivating))
            self.assertEqual(popup.focusPolicy(), Qt.NoFocus)
            message = wintypes.MSG()
            message.message = integration.WM_MOUSEACTIVATE
            self.assertEqual(popup.nativeEvent(b'windows_generic_MSG', ctypes.addressof(message)), (True, 3))

    def test_mouse_menu_action_remains_operable_and_closes_the_popup(self):
        menu = integration.NonActivatingMenu()
        action = menu.addAction('隐藏码表')
        callback = Mock()
        action.triggered.connect(callback)
        menu.popup(QPoint(20, 20))
        self.app.processEvents()
        point = menu.actionGeometry(action).center()
        # Qt delivery only: never move the system cursor or inject an OS click.
        for kind, buttons in ((QEvent.MouseButtonPress, Qt.LeftButton),
                              (QEvent.MouseButtonRelease, Qt.NoButton)):
            self.app.sendEvent(menu, QMouseEvent(kind, QPointF(point),
                               Qt.LeftButton, buttons, Qt.NoModifier))
        callback.assert_called_once_with(False)
        self.assertFalse(menu.isVisible())


if __name__ == '__main__':
    unittest.main()
