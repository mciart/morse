"""The release probe renders real Qt widgets without activating integrations."""

import json
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

import test_ui_behavior as ui
from frozen_smoke import _assert_navigation_gap_transparent, verify_interface_features
from PyQt5.QtGui import QColor, QImage


class FrozenInterfaceProbeTests(TestCase):
    setUpClass = classmethod(ui.WindowBehaviorTests.setUpClass.__func__)
    setUp = ui.WindowBehaviorTests.setUp
    tearDown = ui.WindowBehaviorTests.tearDown

    def test_gap_sample_ignores_corner_antialiasing_but_requires_zero_gap_alpha(self):
        self.window.hide()
        self.window._start_hidden = True
        self.window.init()
        view = self.window.codeslayoutview
        self.views.append(view)
        view.setCompactMode(True)
        for scale in (0.8, 1.0):
            with self.subTest(scale=scale):
                view.setCompactScale(scale)
                image = QImage(view.size(), QImage.Format_ARGB32_Premultiplied)
                image.fill(ui.morse.Qt.transparent)
                view.render(image)
                # Native 300% DPI produces alpha 50 at this rounded corner.
                image.setPixelColor(0, 0, QColor(0, 0, 0, 50))
                point = _assert_navigation_gap_transparent(view, image)
                self.assertNotEqual(point, ui.morse.QtCore.QPoint(0, 0))
                image.setPixelColor(point, QColor(0, 0, 0, 1))
                with self.assertRaisesRegex(AssertionError, 'gaps are not transparent'):
                    _assert_navigation_gap_transparent(view, image)

    def test_compact_render_and_f22_preset_are_checked_without_native_integration(self):
        window = self.window
        window.hide()
        window._start_hidden = True
        window.init()
        self.views.append(window.codeslayoutview)
        preferences = dict(window.configManager.config)
        message = AssertionError('Probe must not activate a native integration')
        with patch.object(window.guide_hotkey, 'set_sequence', side_effect=message), \
                patch.object(window.guide_key, 'set_key', side_effect=message), \
                patch.object(window.startup_registration, 'set_enabled', side_effect=message), \
                patch.object(ui.morse, 'show_guide_without_activation', side_effect=message), \
                patch('virtual_keyboard.show_guide_without_activation', side_effect=message), \
                patch.object(self.app.desktop(), 'availableGeometry',
                             return_value=ui.morse.QtCore.QRect(0, 0, 2200, 1400)):
            result = verify_interface_features(window)
        self.assertEqual(result['hotkey_preset'], 'F22')
        self.assertEqual(result['pinyin_layer']['actions'], 116)
        self.assertEqual(result['pinyin_layer']['modes'], ['hold', 'toggle'])
        self.assertTrue(result['transparent_gap'] and result['painted_key'] and result['restored'])
        self.assertTrue(result['scale_saved'])
        self.assertEqual(result['reset_scale'], 1.0)
        self.assertLess(result['resize_sizes'][0][0], result['resize_sizes'][1][0])
        saved = json.loads(Path(window.configManager.config_file).read_text(encoding='utf-8'))
        self.assertEqual(saved['guide_compact_scale'], 1.0)
        for key, value in preferences.items():
            if key != 'guide_compact_scale':
                self.assertEqual(saved[key], value, key)
        self.assertIsNone(window.listenerThread)
        self.start_listener.assert_not_called()
        self.assertFalse(window.config['guide_compact'])
        self.assertFalse(window.isVisible() or window.codeslayoutview.isVisible())
