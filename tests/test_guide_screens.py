"""Screen-change regressions using Qt signals, without changing OS displays."""

from unittest import TestCase
from unittest.mock import patch

from PyQt5.QtCore import QEvent, QObject, QPoint, QPointF, QRect, pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QApplication

import test_unified_guide as guide


class ScreenStub(QObject):
    availableGeometryChanged = pyqtSignal(QRect)
    geometryChanged = pyqtSignal(QRect)
    logicalDotsPerInchChanged = pyqtSignal(float)
    physicalDotsPerInchChanged = pyqtSignal(float)

    def __init__(self, bounds, parent=None):
        super().__init__(parent)
        self._bounds = QRect(bounds)
        self._logical_dpi = 96.0
        self._physical_dpi = 96.0

    def availableGeometry(self):
        return QRect(self._bounds)

    def name(self):
        return 'Test screen'

    def geometry(self):
        return QRect(self._bounds)

    def logicalDotsPerInch(self):
        return self._logical_dpi

    def physicalDotsPerInch(self):
        return self._physical_dpi

    def set_bounds(self, bounds, signal='availableGeometryChanged'):
        self._bounds = QRect(bounds)
        getattr(self, signal).emit(QRect(bounds))

    def set_dpi(self, value, physical=False):
        if physical:
            self._physical_dpi = float(value)
            self.physicalDotsPerInchChanged.emit(float(value))
        else:
            self._logical_dpi = float(value)
            self.logicalDotsPerInchChanged.emit(float(value))


class WindowHandleStub(QObject):
    screenChanged = pyqtSignal(object)

    def __init__(self, screen, parent=None):
        super().__init__(parent)
        self._screen = screen

    def screen(self):
        return self._screen

    def change_screen(self, screen):
        self._screen = screen
        self.screenChanged.emit(screen)


class GuideScreenTests(TestCase):
    setUpClass = classmethod(guide.UnifiedGuideTests.setUpClass.__func__)
    start_input = guide.UnifiedGuideTests.start_input
    select_page = guide.UnifiedGuideTests.select_page
    enter_code = guide.UnifiedGuideTests.enter_code
    tearDown = guide.UnifiedGuideTests.tearDown
    assert_compact_board_fits = guide.UnifiedGuideTests.assert_compact_board_fits
    drag_compact_viewport = guide.UnifiedGuideTests.drag_compact_viewport

    def setUp(self):
        guide.UnifiedGuideTests.setUp(self)
        self.window.engine_timer.stop()
        self.view = self.window.codeslayoutview
        self.screen = ScreenStub(QRect(0, 0, 2200, 1400), self.view)
        self.screens = [self.screen]
        self.handle = WindowHandleStub(self.screen, self.view)
        self.enterContext(patch.object(QApplication, 'screens', side_effect=lambda: self.screens))
        self.enterContext(patch.object(QApplication, 'screenAt', side_effect=lambda position: next(
            (screen for screen in self.screens if screen.geometry().contains(position)), None)))
        self.enterContext(patch.object(self.view, 'windowHandle', side_effect=lambda: self.handle))
        self.enterContext(patch.object(self.view, '_availableGeometry',
                                       side_effect=lambda: self.handle.screen().availableGeometry()))
        self.view._bindWindowScreen()
        self.flush_screen_events()

    def flush_screen_events(self):
        # Screen signals are coalesced through an owned zero-delay Qt timer.
        # Pumping a few turns also completes layouts queued by the refresh.
        for _ in range(4):
            self.app.processEvents()

    def start_compact(self, scale=.95):
        self.view.setCompactMode(True)
        self.view.setCompactScale(scale)
        self.flush_screen_events()

    def test_available_geometry_and_resolution_signals_adapt_visible_compact_view(self):
        self.start_compact()
        view = self.view
        original = view.size()
        changes = []
        view.compactScaleChanged.connect(changes.append)
        for signal in ('availableGeometryChanged', 'geometryChanged'):
            with self.subTest(signal=signal):
                self.screen.set_bounds(QRect(60, 45, 480, 310), signal)
                self.flush_screen_events()
                self.assertTrue(view.isVisible())
                self.assertTrue(self.screen.availableGeometry().contains(view.geometry()))
                self.assertLess(view.width(), original.width())
                self.assertEqual(view.compactScale(), .95)
                self.assert_compact_board_fits(view)
                self.screen.set_bounds(QRect(0, 0, 2200, 1400), signal)
                self.flush_screen_events()
                self.assertEqual(view.size(), original)
                self.assertEqual(view.compactScale(), .95)
        self.assertEqual(changes, [])

    def test_dpi_signals_refresh_key_metrics_both_directions_without_resetting_input(self):
        self.start_compact()
        view = self.view
        # Give the optional mouse panel a real layout before recording sizes;
        # hidden widgets need not have their final geometry until first shown.
        view.setMouseVisible(True)
        self.flush_screen_events()
        view.Dit()
        view.Dah()
        caps = list(view.crs.values())
        original_fonts = {label: QFont(label.font()) for cap in caps for label in (cap.character, cap.codeline)}
        original_sizes = {cap: cap.size() for cap in caps}
        original_scene = view.scroll_area.sceneRect()
        prefix = {cap: (cap.disabledchars, cap._prefix_matches) for cap in caps}
        changes = []
        view.compactScaleChanged.connect(changes.append)

        # Qt updates the fonts before notifying an application about a display
        # DPI change. Simulate those updated metrics, rather than altering the
        # actual Windows scale setting or only checking that a callback ran.
        for label, font in original_fonts.items():
            larger = QFont(font)
            larger.setPixelSize(round(label.fontMetrics().height() * 1.7))
            label.setFont(larger)
        self.screen.set_dpi(168)
        self.flush_screen_events()
        self.assertGreater(view.scroll_area.sceneRect().width(), original_scene.width())
        self.assertGreater(view.scroll_area.sceneRect().height(), original_scene.height())
        for cap in caps:
            self.assertGreater(cap.height(), original_sizes[cap].height())
            if cap.isVisible():
                for label in (cap.character, cap.codeline):
                    self.assertGreaterEqual(label.height(), label.fontMetrics().height())
            self.assertEqual((cap.disabledchars, cap._prefix_matches), prefix[cap])
        self.assertEqual(view._prefix, '12')
        self.assertEqual(view.compactScale(), .95)
        self.assert_compact_board_fits(view)

        for label, font in original_fonts.items():
            label.setFont(font)
        self.screen.set_dpi(96, physical=True)
        self.flush_screen_events()
        self.assertEqual(view.scroll_area.sceneRect(), original_scene)
        for cap in caps:
            self.assertEqual(cap.size(), original_sizes[cap])
            self.assertEqual((cap.disabledchars, cap._prefix_matches), prefix[cap])
        self.assertEqual(view.compactScale(), .95)
        self.assertEqual(changes, [])
        self.assert_compact_board_fits(view)

    def test_screen_refresh_does_not_show_hidden_or_restore_minimized_windows(self):
        view = self.view
        self.start_compact()
        for mode in ('hidden', 'minimized', 'hidden_minimized'):
            with self.subTest(mode=mode):
                view.showNormal()
                if 'minimized' in mode:
                    view.showMinimized()
                if 'hidden' in mode:
                    view.hide()
                self.flush_screen_events()
                visible, minimized = view.isVisible(), view.isMinimized()
                with patch('virtual_keyboard.show_guide_without_activation') as show:
                    self.screen.set_bounds(QRect(0, 0, 510, 320))
                    self.screen.set_dpi(144)
                    self.flush_screen_events()
                    self.assertEqual(view.isVisible(), visible)
                    self.assertEqual(view.isMinimized(), minimized)
                    show.assert_not_called()
                self.assertEqual(view.compactScale(), .95)
        view.showNormal()
        self.flush_screen_events()
        self.assertTrue(self.screen.availableGeometry().contains(view.geometry()))
        self.assert_compact_board_fits(view)

    def test_full_mode_is_kept_on_screen_and_preserves_manual_guide_preference(self):
        view = self.view
        view.setAutoFit(False)
        view.setGeometry(1400, 800, 720, 460)
        self.flush_screen_events()
        available = QRect(20, 30, 600, 420)
        self.screen.set_bounds(available)
        self.flush_screen_events()
        self.assertTrue(view.isVisible())
        self.assertTrue(available.contains(view.frameGeometry()))
        self.assertTrue(view.scroll_area.transform().isIdentity())
        self.assertFalse(view.config['guide_auto_fit'])
        for widget in (view.header_widget, view.settings_button, view.status_bar):
            rectangle = QRect(widget.mapTo(view, QPoint()), widget.size())
            self.assertTrue(view.rect().contains(rectangle))
        view.hide()
        self.screen.set_bounds(QRect(0, 0, 480, 360))
        self.flush_screen_events()
        self.assertTrue(view.isHidden())

    def test_switching_screens_and_native_window_handles_rebinds_observers_once(self):
        self.start_compact()
        old_screen, old_handle = self.screen, self.handle
        second = ScreenStub(QRect(-900, 0, 900, 700), self.view)
        self.screens.append(second)
        self.handle.change_screen(second)
        self.flush_screen_events()
        self.assertTrue(second.availableGeometry().contains(self.view.geometry()))
        self.assertEqual(old_screen.receivers(old_screen.availableGeometryChanged), 0)
        self.assertGreater(second.receivers(second.availableGeometryChanged), 0)

        # Recreating the native HWND changes QWindow. The old handle must no
        # longer switch the active monitor or retain duplicate subscriptions.
        third = ScreenStub(QRect(100, 50, 1600, 1000), self.view)
        self.screens.append(third)
        self.handle = WindowHandleStub(third, self.view)
        self.app.sendEvent(self.view, QEvent(QEvent.WinIdChange))
        self.view._bindWindowScreen()
        self.flush_screen_events()
        self.assertEqual(old_handle.receivers(old_handle.screenChanged), 0)
        self.assertEqual(self.handle.receivers(self.handle.screenChanged), 1)
        self.assertEqual(second.receivers(second.availableGeometryChanged), 0)
        self.assertEqual(third.receivers(third.availableGeometryChanged), 1)
        self.assertTrue(third.availableGeometry().contains(self.view.geometry()))
        self.assertEqual(self.view.compactScale(), .95)
        old_screen.set_bounds(QRect(0, 0, 100, 100))
        old_handle.change_screen(old_screen)
        self.flush_screen_events()
        self.assertTrue(third.availableGeometry().contains(self.view.geometry()))
        self.assertEqual(old_screen.receivers(old_screen.availableGeometryChanged), 0)

    def test_dragging_to_another_monitor_uses_its_bounds_and_refits_on_screen_changed(self):
        view = self.view
        self.start_compact(1.0)
        second = ScreenStub(QRect(-1280, 0, 1280, 720), view)
        self.screens.append(second)
        view.move(100, 100)
        self.flush_screen_events()
        cap = view.keystroke_crs_map['G']
        start = view.scroll_area.mapFromScene(QPointF(cap.mapTo(view.chart_widget, cap.rect().center())))
        target_center = second.availableGeometry().center()
        delta = target_center - view.geometry().center()

        def screen_at(position):
            return second if second.geometry().contains(position) else self.screen

        with patch.object(QApplication, 'screenAt', side_effect=screen_at):
            self.drag_compact_viewport(view, start, delta)
            self.assertLess(view.x(), 0)
            # The window manager reports its new monitor after the move.
            self.handle.change_screen(second)
            self.flush_screen_events()
        self.assertTrue(second.availableGeometry().contains(view.geometry()))
        self.assertEqual(view.compactScale(), 1.0)
        self.assert_compact_board_fits(view)
