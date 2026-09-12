"""Theme preferences follow mocked OS settings without changing real settings."""

import os
import sys
import unittest
from unittest.mock import MagicMock, Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtGui import QColor, QPalette
from PyQt5.QtTest import QSignalSpy
from PyQt5.QtWidgets import QApplication

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
        self.manager = None

    def tearDown(self):
        if self.manager is not None:
            self.manager._timer.stop()
            self.manager.deleteLater()
        self.app.setPalette(self.original_palette)
        self.app.setStyleSheet(self.original_style)
        self.app.setProperty("resolvedTheme", self.original_resolved_theme)
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


if __name__ == "__main__":
    unittest.main()
