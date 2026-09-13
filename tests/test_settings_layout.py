"""Responsive settings checks using isolated Qt widgets and virtual screens."""

import os
import unittest
from unittest.mock import patch

os.environ['QT_QPA_PLATFORM'] = 'offscreen'

from PyQt5.QtCore import QRect, QSize, Qt
from PyQt5.QtWidgets import (QApplication, QCheckBox, QComboBox, QHBoxLayout,
                             QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget)

from settings_layout import (ResponsiveSettingsForm, ResponsiveSettingsRow,
                             SettingsWindowSizer, fit_settings_frame,
                             settings_client_size, wrap_checkbox_text)


class SettingsSizingTests(unittest.TestCase):
    def test_initial_size_uses_content_height_and_screen_capacity(self):
        size = settings_client_size(QSize(510, 1200), QSize(280, 32), QRect(0, 0, 1920, 1080))
        self.assertEqual(size.width(), 560)
        self.assertEqual(size.height(), 1016)

    def test_large_text_wraps_instead_of_requiring_full_desktop_width(self):
        size = settings_client_size(QSize(2000, 800), QSize(280, 32), QRect(0, 0, 1920, 1080))
        self.assertEqual(size.width(), 760)

    def test_high_dpi_logical_screen_caps_size_without_second_scaling(self):
        size = settings_client_size(QSize(600, 1000), QSize(280, 32), QRect(0, 0, 640, 360))
        self.assertEqual(size, QSize(600, 296))

    def test_unscaled_qt_coordinates_follow_native_font_dpi(self):
        size = settings_client_size(QSize(1100, 3000), QSize(600, 60),
                                    QRect(0, 0, 3840, 2016),
                                    frame=QSize(6, 88), scale=3)
        self.assertEqual(size, QSize(1680, 1856))

    def test_tiny_screen_never_produces_negative_dimensions(self):
        size = settings_client_size(QSize(500, 1000), QSize(300, 32), QRect(0, 0, 20, 20))
        self.assertEqual(size, QSize(1, 1))

    def test_valid_user_geometry_is_unchanged(self):
        frame = QRect(80, 90, 600, 700)
        self.assertEqual(fit_settings_frame(frame, QRect(0, 0, 1920, 1080)), frame)

    def test_new_smaller_screen_shrinks_and_keeps_frame_inside_negative_coordinates(self):
        available = QRect(-800, -600, 800, 600)
        fitted = fit_settings_frame(QRect(900, 700, 1200, 1000), available)
        self.assertEqual(fitted, QRect(-788, -588, 776, 576))
        self.assertTrue(available.contains(fitted))


class SettingsWidgetLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def pump(self):
        for _ in range(4):
            self.app.processEvents()

    def own(self, widget):
        self.addCleanup(widget.close)
        self.addCleanup(widget.deleteLater)
        return widget

    def test_checkbox_text_wraps_and_restores_full_caption(self):
        checkbox = self.own(QCheckBox('与微软拼音中／英文状态双向同步'))
        original = checkbox.text()
        wrap_checkbox_text(checkbox, 120)
        self.assertIn('\n', checkbox.text())
        self.assertEqual(checkbox.text().replace('\n', ''), original)
        wrap_checkbox_text(checkbox, 800)
        self.assertEqual(checkbox.text(), original)

    def test_responsive_row_stacks_controls_and_restores_horizontal_layout(self):
        window = self.own(QWidget())
        layout = ResponsiveSettingsRow(window)
        for caption in ('切换方式：', '按住使用', '双击切换'):
            label = QLabel(caption)
            label.setMinimumWidth(110)
            layout.addWidget(label)
        window.resize(500, 160)
        window.show()
        self.pump()
        self.assertEqual(layout.direction(), layout.LeftToRight)
        window.resize(180, 160)
        self.pump()
        self.assertEqual(layout.direction(), layout.TopToBottom)
        window.resize(500, 160)
        self.pump()
        self.assertEqual(layout.direction(), layout.LeftToRight)

    def test_responsive_form_moves_field_below_label(self):
        window = self.own(QWidget())
        layout = ResponsiveSettingsForm(window)
        label = QLabel('较长的字段标签：')
        label.setMinimumWidth(150)
        field = QComboBox()
        field.addItem('默认选项')
        field.setMinimumWidth(150)
        layout.addRow(label, field)
        window.resize(200, 160)
        window.show()
        self.pump()
        self.assertGreater(field.y(), label.y())
        self.assertLessEqual(field.geometry().right(), window.width())

    def make_settings(self):
        window = self.own(QWidget())
        layout = QVBoxLayout(window)
        scroll = QScrollArea()
        content = QWidget()
        content_layout = QVBoxLayout(content)
        for _ in range(20):
            content_layout.addWidget(QCheckBox('与微软拼音中／英文状态双向同步'))
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)
        actions = QWidget()
        action_layout = QHBoxLayout(actions)
        for caption in ('音频设备', '保存设置', '开始输入'):
            action_layout.addWidget(QPushButton(caption))
        layout.addWidget(actions)
        self.available = QRect(0, 0, 1200, 900)
        sizer = SettingsWindowSizer(window, scroll, actions,
                                    screen_provider=lambda: self.available)
        window.show()
        self.pump()
        return window, scroll, actions, sizer

    def test_first_show_uses_screen_space_and_only_vertical_scrolling(self):
        window, scroll, actions, sizer = self.make_settings()
        self.assertGreaterEqual(window.width(), 560)
        self.assertTrue(self.available.contains(window.frameGeometry()))
        window.resize(340, 300)
        self.pump()
        self.assertEqual(scroll.horizontalScrollBarPolicy(), Qt.ScrollBarAlwaysOff)
        self.assertEqual(scroll.horizontalScrollBar().maximum(), 0)
        self.assertGreater(scroll.verticalScrollBar().maximum(), 0)
        self.assertLessEqual(scroll.widget().width(), scroll.viewport().width())
        self.assertTrue(window.rect().contains(actions.geometry()))
        self.assertFalse(scroll.isAncestorOf(actions))

    def test_normal_resize_and_metrics_refresh_preserve_valid_user_size(self):
        window, scroll, actions, sizer = self.make_settings()
        window.resize(620, 500)
        self.pump()
        wanted = window.geometry()
        sizer._screen_metrics_changed()
        self.pump()
        self.assertEqual(window.geometry(), wanted)

    def test_settled_settings_do_not_schedule_idle_relayout_loop(self):
        window, scroll, actions, sizer = self.make_settings()
        window.resize(340, 300)
        # Let the resize, caption wrapping, and scroll viewport adjustment
        # settle before observing a period with no user or screen changes.
        for _ in range(20):
            self.app.processEvents()
        with patch.object(sizer, 'reflow', wraps=sizer.reflow) as reflow:
            for _ in range(100):
                self.app.processEvents()
            self.assertEqual(reflow.call_count, 0)
            self.assertFalse(sizer._timer.isActive())

    def test_smaller_virtual_screen_constrains_existing_geometry(self):
        window, scroll, actions, sizer = self.make_settings()
        window.resize(900, 800)
        self.available = QRect(-640, 0, 640, 480)
        sizer._screen_metrics_changed()
        self.pump()
        self.assertTrue(self.available.contains(window.frameGeometry()))
        self.assertTrue(window.rect().contains(actions.geometry()))


if __name__ == '__main__':
    unittest.main()
