"""The release probe renders real Qt widgets without activating integrations."""

from unittest import TestCase
from unittest.mock import patch

import test_ui_behavior as ui
from frozen_smoke import verify_interface_features


class FrozenInterfaceProbeTests(TestCase):
    setUpClass = classmethod(ui.WindowBehaviorTests.setUpClass.__func__)
    setUp = ui.WindowBehaviorTests.setUp
    tearDown = ui.WindowBehaviorTests.tearDown

    def test_compact_render_and_f22_preset_are_checked_without_native_integration(self):
        window = self.window
        window.hide()
        window._start_hidden = True
        window.init()
        self.views.append(window.codeslayoutview)
        message = AssertionError('Probe must not activate a native integration')
        with patch.object(window.guide_hotkey, 'set_sequence', side_effect=message), \
                patch.object(window.startup_registration, 'set_enabled', side_effect=message), \
                patch.object(ui.morse, 'show_guide_without_activation', side_effect=message), \
                patch('virtual_keyboard.show_guide_without_activation', side_effect=message):
            result = verify_interface_features(window)
        self.assertEqual(result['hotkey_preset'], 'F22')
        self.assertTrue(result['transparent_gap'] and result['painted_key'] and result['restored'])
        self.assertIsNone(window.listenerThread)
        self.start_listener.assert_not_called()
        self.assertFalse(window.config['guide_compact'])
        self.assertFalse(window.isVisible() or window.codeslayoutview.isVisible())
