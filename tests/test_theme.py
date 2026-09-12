"""Theme preferences follow mocked OS settings without changing real settings."""

import os
import sys
import unittest
from unittest.mock import MagicMock, Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEvent, Qt
from PyQt5.QtGui import QColor, QFont, QPalette
from PyQt5.QtTest import QSignalSpy
from PyQt5.QtWidgets import QApplication, QDialog, QWidget

import ui_theme


class ThemeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()
        if cls.app is None:
            from MorseCodeGUI import CustomApplication
            cls.app = CustomApplication([])

    def setUp(self):
        self.original_palette = QPalette(self.app.palette())
        self.original_style = self.app.styleSheet()
        self.original_colors = dict(ui_theme.THEME_COLORS)
        self.original_resolved_theme = self.app.property("resolvedTheme")
        self.original_font = QFont(self.app.font())
        self.original_ui_font = QFont(self.app._morse_ui_font)
        self.manager = None

    def tearDown(self):
        if self.manager is not None:
            self.manager._timer.stop()
            self.manager.deleteLater()
        self.app.setPalette(self.original_palette)
        self.app.setStyleSheet(self.original_style)
        self.app.setProperty("resolvedTheme", self.original_resolved_theme)
        self.app._morse_ui_font = self.original_ui_font
        self.app.setFont(self.original_font)
        ui_theme.THEME_COLORS.clear()
        ui_theme.THEME_COLORS.update(self.original_colors)

    def test_default_follows_system_and_tracks_changes(self):
        with patch("ui_theme.detect_system_theme", return_value="light") as detect:
            self.manager = ui_theme.ThemeManager(self.app)
            self.assertEqual(self.manager.mode, "system")
            self.assertEqual(self.manager.resolved_theme, "light")
            self.assertTrue(self.manager._timer.isActive())
            self.assertEqual(self.manager._timer.interval(), 1000)
            changed = QSignalSpy(self.manager.themeChanged)
            detect.return_value = "dark"
            self.manager._timer.timeout.emit()
            self.assertEqual(self.manager.resolved_theme, "dark")
            self.assertEqual(list(changed), [["dark"]])
            self.manager.refresh()
            self.assertEqual(len(changed), 1)

    def test_explicit_modes_ignore_system_and_stop_polling(self):
        with patch("ui_theme.detect_system_theme", return_value="dark") as detect:
            self.manager = ui_theme.ThemeManager(self.app, "light")
            self.assertEqual(self.manager.resolved_theme, "light")
            self.assertFalse(self.manager._timer.isActive())
            self.manager.refresh()
            detect.assert_not_called()
            self.manager.set_mode("dark")
            self.assertEqual(self.manager.resolved_theme, "dark")
            self.assertFalse(self.manager._timer.isActive())
            detect.assert_not_called()
            detect.return_value = "light"
            self.manager.set_mode("system")
            self.assertEqual(self.manager.resolved_theme, "light")
            self.assertTrue(self.manager._timer.isActive())

    def test_colors_keep_imported_reference_and_palette_matches(self):
        reference = ui_theme.THEME_COLORS
        for mode in ("light", "dark"):
            with self.subTest(mode=mode):
                self.assertEqual(ui_theme.apply_theme(self.app, mode), mode)
                self.assertIs(reference, ui_theme.THEME_COLORS)
                self.assertEqual(reference, ui_theme.THEMES[mode])
                for role, key in ((QPalette.Window, "background"),
                                  (QPalette.WindowText, "text"),
                                  (QPalette.Highlight, "highlight")):
                    self.assertEqual(self.app.palette().color(role).name(),
                                     reference[key].lower())
                self.assertIn(reference["keycap"], self.app.styleSheet())

    def test_invalid_mode_preserves_current_preference(self):
        self.manager = ui_theme.ThemeManager(self.app, "light")
        with self.assertRaises(ValueError):
            self.manager.set_mode("invalid")
        self.assertEqual(self.manager.mode, "light")
        with self.assertRaises(ValueError):
            ui_theme.apply_theme(self.app, "invalid")
        self.assertEqual(self.manager.resolved_theme, "light")

    def test_windows_reads_application_theme_preference(self):
        registry = MagicMock()
        registry.OpenKey.return_value.__enter__.return_value = "registry-key"
        with patch.object(ui_theme.sys, "platform", "win32"), \
                patch.dict(sys.modules, {"winreg": registry}):
            for value, expected in ((0, "dark"), (1, "light")):
                registry.QueryValueEx.return_value = (value, 4)
                self.assertEqual(ui_theme.detect_system_theme(self.app), expected)
                registry.QueryValueEx.assert_called_with("registry-key", "AppsUseLightTheme")

    def test_registry_failure_uses_original_native_palette(self):
        native = QPalette()
        native.setColor(QPalette.Window, QColor("#FFFFFF"))
        registry = Mock()
        registry.OpenKey.side_effect = OSError("Preference unavailable")
        with patch.object(self.app, "_morse_system_palette", native, create=True), \
                patch.object(ui_theme.sys, "platform", "win32"), \
                patch.dict(sys.modules, {"winreg": registry}):
            ui_theme.apply_dark_theme(self.app)
            self.assertEqual(ui_theme.detect_system_theme(self.app), "light")

    def test_other_platform_uses_native_palette(self):
        native = QPalette()
        native.setColor(QPalette.Window, QColor("#151515"))
        with patch.object(self.app, "_morse_system_palette", native, create=True), \
                patch.object(ui_theme.sys, "platform", "linux"):
            self.assertEqual(ui_theme.detect_system_theme(self.app), "dark")
            self.assertEqual(ui_theme.apply_theme(self.app), "dark")

    def test_windows_font_uses_native_size_instead_of_qt_fallback(self):
        del self.app._morse_ui_font
        self.app.setFont(QFont("SimSun", 18))
        native = QFont("Microsoft YaHei UI", 9)
        with patch.object(ui_theme.sys, "platform", "win32"), \
                patch("ui_theme._windows_ui_font", return_value=native) as read_font:
            ui_theme.apply_theme(self.app, "light")
            self.assertEqual(self.app.font().pointSizeF(), 9.0)
            for mode in ("dark", "light", "dark", "light"):
                # A theme switch cannot turn a changed application font into
                # the next theme's baseline and compound its size.
                self.app.setFont(QFont("SimSun", 18))
                ui_theme.apply_theme(self.app, mode)
                self.assertEqual(self.app.font().pointSizeF(), 9.0)
                self.assertEqual(self.app.font().pixelSize(), -1)
            read_font.assert_called_once_with()

    def test_non_windows_font_keeps_original_point_size(self):
        del self.app._morse_ui_font
        self.app.setFont(QFont("Sans Serif", 11))
        with patch.object(ui_theme.sys, "platform", "linux"):
            ui_theme.apply_theme(self.app, "light")
            ui_theme.apply_theme(self.app, "dark")
            self.assertEqual(self.app.font().pointSizeF(), 11.0)

    def test_native_titlebar_never_creates_an_hwnd_or_uses_deleted_widgets(self):
        from PyQt5 import sip

        widget = QWidget()
        titlebars = self.app._morse_titlebar_theme
        with patch.object(self.app, 'platformName', return_value='windows'), \
                patch.object(ui_theme.sys, 'platform', 'win32'), \
                patch('ui_theme._set_windows_titlebar') as native:
            titlebars.eventFilter(widget, QEvent(QEvent.WinIdChange))
            self.assertFalse(widget.testAttribute(Qt.WA_WState_Created))
            native.assert_not_called()
            sip.delete(widget)
            titlebars.applyWindow(widget)
            native.assert_not_called()

    def test_native_titlebar_tracks_existing_and_new_dialog_theme(self):
        widget = QDialog()
        widget.setAttribute(Qt.WA_DontShowOnScreen)
        widget.show()
        self.app.processEvents()
        titlebars = self.app._morse_titlebar_theme
        with patch.object(self.app, 'platformName', return_value='windows'), \
                patch.object(ui_theme.sys, 'platform', 'win32'), \
                patch('ui_theme._set_windows_titlebar') as native:
            self.app.setProperty('resolvedTheme', 'dark')
            titlebars.eventFilter(widget, QEvent(QEvent.Show))
            native.assert_called_with(int(widget.effectiveWinId()), True)
            self.app.setProperty('resolvedTheme', 'light')
            titlebars.eventFilter(widget, QEvent(QEvent.WinIdChange))
            native.assert_called_with(int(widget.effectiveWinId()), False)
            native.reset_mock()
            widget.setWindowFlag(Qt.FramelessWindowHint)
            titlebars.applyWindow(widget)
            native.assert_not_called()
        widget.hide()
        widget.deleteLater()

    def test_dwm_uses_pointer_sized_handles_and_windows_11_caption_colors(self):
        import ctypes
        from ctypes import wintypes

        library = MagicMock()
        dwm = library.dwmapi.DwmSetWindowAttribute
        dwm.return_value = 0
        handle = 0x100001234
        with patch.object(ctypes, 'windll', library, create=True), \
                patch.object(ui_theme.sys, 'getwindowsversion', return_value=Mock(build=22631), create=True):
            self.assertTrue(ui_theme._set_windows_titlebar(handle, True))
        self.assertEqual(dwm.argtypes[0], wintypes.HWND)
        self.assertEqual(dwm.restype, wintypes.LONG)
        self.assertEqual([args[0][1] for args in dwm.call_args_list], [20, 35, 36])
        self.assertTrue(all(args[0][0] == handle for args in dwm.call_args_list))
        self.assertEqual(dwm.call_args_list[0][0][2]._obj.value, 1)
        color = QColor(ui_theme.THEMES['dark']['background'])
        self.assertEqual(dwm.call_args_list[1][0][2]._obj.value,
                         color.red() | color.green() << 8 | color.blue() << 16)

    def test_dwm_older_version_falls_back_and_failure_is_nonfatal(self):
        import ctypes

        library = MagicMock()
        dwm = library.dwmapi.DwmSetWindowAttribute
        dwm.side_effect = [-1, 0]
        with patch.object(ctypes, 'windll', library, create=True), \
                patch.object(ui_theme.sys, 'getwindowsversion', return_value=Mock(build=18362), create=True):
            self.assertTrue(ui_theme._set_windows_titlebar(1234, False))
            self.assertEqual([args[0][1] for args in dwm.call_args_list], [20, 19])
            dwm.side_effect = OSError('DWM unavailable')
            self.assertFalse(ui_theme._set_windows_titlebar(1234, True))


if __name__ == "__main__":
    unittest.main()
