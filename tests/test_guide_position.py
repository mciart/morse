"""Guide positions survive real UI lifecycles using only temporary settings."""

from copy import deepcopy
import json
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from PyQt5.QtCore import QEvent, QPoint, QRect
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QWidget

import test_ui_behavior as ui
from test_guide_screens import ScreenStub

morse = ui.morse


class NamedScreen(ScreenStub):
    def __init__(self, name, bounds):
        super().__init__(bounds)
        self._name = name

    def name(self):
        return self._name


class GuidePositionTests(TestCase):
    setUpClass = classmethod(ui.WindowBehaviorTests.setUpClass.__func__)

    def setUp(self):
        ui.WindowBehaviorTests.setUp(self)
        self.extra_windows = []
        self.primary = NamedScreen('Primary test screen', QRect(0, 0, 2200, 1400))
        self.screens = [self.primary]
        self.enterContext(patch.object(QApplication, 'screens', side_effect=lambda: self.screens))
        self.enterContext(patch.object(QApplication, 'primaryScreen', side_effect=lambda: self.primary))
        self.enterContext(patch.object(QApplication, 'screenAt', side_effect=self.screen_at))
        self.enterContext(patch.object(self.app.desktop(), 'availableGeometry',
                                       side_effect=self.available_geometry))

    def tearDown(self):
        windows = self.extra_windows + [self.window]
        for window in windows:
            window.shutdown()
            window.trayIcon.hide()
        widgets = self.views + [widget for window in windows for widget in (window.audioSelector, window)]
        for widget in widgets:
            try:
                widget.hide()
                widget.deleteLater()
            except RuntimeError:
                # Returning to settings already deletes the previous guide.
                pass
        self.app.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()

    def screen_at(self, point):
        return next((screen for screen in self.screens if screen.geometry().contains(point)), None)

    def available_geometry(self, widget=None):
        if isinstance(widget, QWidget):
            screen = self.screen_at(widget.frameGeometry().center()) or self.primary
        elif isinstance(widget, int) and 0 <= widget < len(self.screens):
            screen = self.screens[widget]
        else:
            screen = self.primary
        return screen.availableGeometry()

    def drain(self):
        for _ in range(4):
            self.app.processEvents()
        QTest.qWait(10)

    def start_input(self):
        self.window.GOButton.click()
        self.drain()
        view = self.window.codeslayoutview
        self.assertIsNotNone(view)
        self.assertIsNotNone(self.window.listenerThread)
        self.views.append(view)
        return view

    def saved_positions(self, window=None):
        window = window or self.window
        values = json.loads(Path(window.configManager.config_file).read_text(encoding='utf-8'))
        return values.get('guide_positions', {})

    def assert_saved_at(self, mode, point):
        saved = self.saved_positions()[mode]
        self.assertEqual((saved['x'], saved['y']), (point.x(), point.y()))
        self.assertIs(type(saved['x']), int)
        self.assertIs(type(saved['y']), int)
        self.assertIsInstance(saved['screen'], str)
        self.assertEqual(len(saved['available']), 4)
        self.assertTrue(all(type(value) is int for value in saved['available']))
        self.assertEqual(self.window.config['guide_positions'], self.saved_positions())
        self.assertEqual(self.window.configManager.config['guide_positions'], self.saved_positions())

    def open_saved_window(self):
        manager = morse.ConfigManager(self.window.configManager.config_file)
        project = Path(__file__).resolve().parents[1]
        layouts = morse.LayoutManager(str(project / 'user_data/layouts.json'))
        window = morse.Window(layoutManager=layouts, configManager=manager)
        self.extra_windows.append(window)
        layouts.set_actions(manager.initActions(window))
        window.postInit()
        window._start_hidden = True
        window.init()
        self.views.append(window.codeslayoutview)
        self.drain()
        return window

    def new_hidden_view(self, positions, compact=False):
        layout = self.window.layoutManager.layouts['desktop']
        config = dict(self.window.config, guide_positions=deepcopy(positions), guide_compact=compact)
        with patch('virtual_keyboard.show_guide_without_activation',
                   side_effect=AssertionError('Position restoration must not show a window')):
            view = morse.VirtualKeyboardView(layout, config)
            self.views.append(view)
            self.drain()
        self.assertTrue(view.isHidden())
        return view

    def test_return_to_settings_and_restart_input_keep_the_guide_position(self):
        view = self.start_input()
        view.move(310, 220)
        position = QPoint(view.pos())
        # Leave immediately, before the movement debounce has elapsed.
        self.window.backToSettings()
        self.assert_saved_at('full', position)
        self.window.wpmEdit.setValue(18)
        self.window.saveSettings()
        restored = self.start_input()
        self.assertEqual(restored.pos(), position)
        self.assertEqual(self.window.config['wpm'], 18)

    def test_new_window_restores_full_and_compact_positions_from_disk(self):
        view = self.start_input()
        view.move(260, 170)
        full = QPoint(view.pos())
        view.flushPosition()
        view.setCompactMode(True)
        view.move(650, 450)
        compact = QPoint(view.pos())
        view.flushPosition()
        self.window.stopIt()

        restored = self.open_saved_window()
        self.assertTrue(restored.codeslayoutview.isCompactMode())
        self.assertEqual(restored.codeslayoutview.pos(), compact)
        self.assertIsNone(restored.listenerThread)
        restored.codeslayoutview.setCompactMode(False)
        self.assertEqual(restored.codeslayoutview.pos(), full)
        self.assertTrue(restored.codeslayoutview.isHidden())

    def test_full_and_compact_moves_are_saved_independently(self):
        view = self.start_input()
        view.move(250, 180)
        full = QPoint(view.pos())
        view.flushPosition()
        view.setCompactMode(True)
        view.move(640, 430)
        compact = QPoint(view.pos())
        view.flushPosition()
        self.assert_saved_at('full', full)
        self.assert_saved_at('compact', compact)
        for mode, expected in ((False, full), (True, compact), (False, full)):
            view.setCompactMode(mode)
            self.drain()
            self.assertEqual(view.pos(), expected)

    def test_moves_are_debounced_into_one_saved_position(self):
        view = self.start_input()
        view.flushPosition()
        manager = self.window.configManager
        with patch.object(manager, 'save_config', wraps=manager.save_config) as save:
            for x in (210, 230, 260):
                view.move(x, 180)
            save.assert_not_called()
            QTest.qWait(380)
            self.assertEqual(save.call_count, 1)
        self.assert_saved_at('full', view.pos())

    def test_immediate_exit_and_hide_flush_the_last_move(self):
        view = self.start_input()
        view.move(280, 210)
        hidden_position = QPoint(view.pos())
        view.hide()
        self.assert_saved_at('full', hidden_position)
        view.show()
        self.drain()
        view.move(350, 250)
        final_position = QPoint(view.pos())
        self.window.quitAction.trigger()
        self.assert_saved_at('full', final_position)
        self.assertIsNone(self.window.listenerThread)
        self.quit_app.assert_called_once_with()

    def test_minimized_and_maximized_geometry_do_not_replace_normal_position(self):
        view = self.start_input()
        view.move(270, 190)
        view.flushPosition()
        expected = deepcopy(self.saved_positions())
        for change in (view.showMinimized, view.showMaximized):
            change()
            self.drain()
            view.flushPosition()
            self.assertEqual(self.saved_positions(), expected)
            view.showNormal()
            self.drain()

    def test_negative_coordinates_restore_on_the_named_connected_screen(self):
        left = NamedScreen('Left test screen', QRect(-1600, 0, 1600, 1100))
        self.screens.append(left)
        position = {'x': -1300, 'y': 170, 'screen': left.name(), 'available': [-1600, 0, 1600, 1100]}
        view = self.new_hidden_view({'full': position})
        self.assertEqual(view.pos(), QPoint(-1300, 170))
        self.assertTrue(left.availableGeometry().contains(view.frameGeometry()))

    def test_invalid_saved_data_falls_back_to_a_visible_hidden_window(self):
        for value in (None, [], {'full': 'invalid'},
                      {'full': {'x': 'left', 'y': None, 'screen': [], 'available': [0]}},
                      {'full': {'x': 10**40, 'y': -(10**40), 'screen': 'missing',
                                'available': [0, 0, 0, -1]}}):
            with self.subTest(positions=value):
                view = self.new_hidden_view(value)
                self.assertTrue(self.primary.availableGeometry().contains(view.frameGeometry()))

    def test_disconnected_screen_restores_on_screen_without_revealing_the_guide(self):
        position = {'x': -1200, 'y': 180, 'screen': 'Disconnected screen',
                    'available': [-1600, 0, 1600, 1100]}
        for compact in (False, True):
            with self.subTest(compact=compact):
                view = self.new_hidden_view({'compact' if compact else 'full': position}, compact)
                self.assertTrue(self.primary.availableGeometry().contains(view.frameGeometry()))
                self.assertTrue(view.isHidden())
