"""Temporary pinyin surfaces preserve their native guide and saved preferences."""

from copy import deepcopy
import json
import os
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtCore import QEvent, QPoint, QPointF, QRectF, QSizeF, Qt
from PyQt5.QtWidgets import QApplication, QLabel

from pinyin_codes import build_pinyin_layout
from virtual_keyboard import KeyCap, KeyLabel, VirtualKeyboardView


class PinyinBoardTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        path = Path(__file__).resolve().parents[1] / 'user_data' / 'layouts.json'
        self.english = json.loads(path.read_text(encoding='utf-8'))['layouts']['desktop']
        for item in self.english['items']:
            if len(item['action']) == 1:
                item['label'] = item['action'].lower()
        self.pinyin = build_pinyin_layout(self.english)
        self.config = {'show_mouse': False, 'guide_auto_fit': True, 'upperchars': True}
        self.view = VirtualKeyboardView(self.english, self.config)
        self.view.show()
        self.drain()

    def tearDown(self):
        self.view.hide()
        self.view.deleteLater()
        self.app.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()

    def drain(self):
        for _ in range(4):
            self.app.processEvents()

    def assert_caps_fit(self):
        view, viewport = self.view, self.view.scroll_area
        clip = viewport.viewport().rect().adjusted(-2, -2, 2, 2)
        for cap in view.crs.values():
            if not cap.isVisible():
                continue
            bounds = QRectF(QPointF(cap.mapTo(view.chart_widget, QPoint())), QSizeF(cap.size()))
            self.assertTrue(clip.contains(viewport.mapFromScene(bounds).boundingRect()), cap.item['action'])
            for label in (cap.character, cap.codeline):
                self.assertGreaterEqual(label.height(), label.sizeHint().height())

    def test_pinyin_labels_groups_codes_and_english_restoration(self):
        view = self.view
        english_board, english_caps = view.chart_widget, dict(view.crs)
        self.assertFalse(view.isPinyinMode())
        self.assertEqual(len(english_caps), 130)
        view.setPinyinMode(True, self.pinyin)
        self.drain()
        self.assertTrue(view.isPinyinMode())
        self.assertEqual(set(view.crs), {item['code'] for item in self.pinyin['items']})
        initials, finals, symbols, controls = [], [], [], []
        for cap in view.crs.values():
            group = cap.item.get('pinyin_group')
            if group in ('initial', 'final'):
                self.assertEqual(cap.character.text(), cap.item['label'])
                self.assertNotEqual(cap.character.text(), cap.character.text().upper())
                if cap.item.get('tooltip'):
                    self.assertIn(cap.item['tooltip'], cap.toolTip())
            top_left = cap.mapTo(view.chart_widget, QPoint())
            if group == 'initial':
                initials.append((top_left, cap.size()))
            elif group == 'final':
                finals.append((top_left, cap.size()))
            elif group == 'symbol':
                symbols.append((top_left, cap.size()))
            elif group == 'control':
                controls.append((top_left, cap.size()))
        self.assertLess(max(point.x() + size.width() for point, size in initials),
                        min(point.x() for point, size in finals))
        self.assertLess(max(point.y() + size.height() for point, size in initials + finals),
                        min(point.y() for point, size in symbols))
        self.assertEqual(len(symbols), 26)
        self.assertEqual(len({point.y() for point, _ in symbols}), 2)
        self.assertLess(max(point.y() + size.height() for point, size in symbols),
                        min(point.y() for point, size in controls))
        self.assert_caps_fit()
        view.setPinyinMode(False)
        self.drain()
        self.assertIs(view.chart_widget, english_board)
        self.assertEqual(view.crs, english_caps)
        self.assertEqual(view.keystroke_crs_map['A'].character.text(), 'A')

    def test_fifty_holds_reuse_two_owned_surfaces_without_native_or_persisted_changes(self):
        view = self.view
        view.setCompactMode(True)
        self.drain()
        view.setPinyinMode(True, self.pinyin)
        view.setPinyinMode(False)
        self.drain()
        view.flushPosition()
        persisted = deepcopy(self.config)
        geometry, native_id, scale = view.geometry(), int(view.winId()), view.compactScale()
        scene_items = set(view.scroll_area.scene().items())
        caps = {cap for state in view._boardStates() for cap in state['crs'].values()}
        events = []
        for signal in (view.guidePositionsChanged, view.compactScaleChanged,
                       view.compactModeChanged, view.autoFitChanged, view.mouseVisibilityChanged):
            signal.connect(lambda value: events.append(value))
        with patch.object(view, 'setWindowFlags', side_effect=AssertionError('native flags changed')), \
                patch.object(view, 'resize', side_effect=AssertionError('held layer resized guide')):
            for _ in range(50):
                for enabled in (True, False):
                    view.setPinyinMode(enabled)
                    self.drain()
                    self.assertEqual(view.geometry(), geometry)
                    self.assertEqual(int(view.winId()), native_id)
                    self.assertEqual(view.compactScale(), scale)
                    self.assert_caps_fit()
        self.assertEqual(set(view.scroll_area.scene().items()), scene_items)
        self.assertEqual({cap for state in view._boardStates() for cap in state['crs'].values()}, caps)
        self.assertEqual(len(view.scroll_area._boards), 2)
        self.assertEqual(self.config, persisted)
        self.assertEqual(events, [])

    def test_prewarming_keeps_english_and_first_hold_reuses_prepared_caps(self):
        view = self.view
        view.setCompactMode(True)
        view.hide()
        self.drain()
        view.flushPosition()
        geometry, state = view.geometry(), view.windowState()
        native_id, config = int(view.winId()), deepcopy(self.config)
        board, proxy, caps = view.chart_widget, view.scroll_area.proxy, dict(view.crs)
        events = []
        view.guidePositionsChanged.connect(events.append)
        view.compactScaleChanged.connect(events.append)
        with patch.object(view, 'setWindowFlags', side_effect=AssertionError('prewarming changed flags')), \
                patch.object(view, 'resize', side_effect=AssertionError('prewarming resized guide')):
            view.setPinyinMode(False, self.pinyin)
            self.drain()
        self.assertFalse(view.isPinyinMode())
        self.assertIs(view.chart_widget, board)
        self.assertIs(view.scroll_area.proxy, proxy)
        self.assertEqual(view.crs, caps)
        self.assertEqual(len(view.crs), 130)
        self.assertTrue(view.isHidden())
        self.assertEqual(view.windowState(), state)
        self.assertEqual(view.geometry(), geometry)
        self.assertEqual(int(view.winId()), native_id)
        self.assertEqual(self.config, config)
        self.assertEqual(events, [])
        pinyin = view._boards['pinyin']
        prepared_caps = dict(pinyin['crs'])
        prepared_proxy = view.scroll_area._boards[pinyin['chart_widget']]
        self.assertFalse(prepared_proxy.isVisible())
        with patch.object(view, '_createPinyinBoard', side_effect=AssertionError('rebuilt pinyin board')), \
                patch.object(KeyCap, '__init__', side_effect=AssertionError('created key on held input')):
            view.setPinyinMode(True)
            self.drain()
            self.assertEqual(view.crs, prepared_caps)
            self.assertIs(view.scroll_area.proxy, prepared_proxy)
            view.setPinyinMode(False, self.pinyin)
            self.drain()
        self.assertEqual(view.crs, caps)
        self.assertEqual(view.geometry(), geometry)
        self.assertTrue(view.isHidden())
        self.assertEqual(self.config, config)
        self.assertEqual(events, [])

    def test_hidden_and_minimized_switches_keep_visibility_and_window_state(self):
        view = self.view
        for compact in (False, True):
            view.setCompactMode(compact)
            view.show()
            self.drain()
            for hidden in (True, False):
                view.hide() if hidden else view.showMinimized()
                self.drain()
                state, visible, geometry = view.windowState(), view.isVisible(), view.geometry()
                for enabled in (True, False):
                    view.setPinyinMode(enabled, self.pinyin)
                    self.drain()
                    self.assertEqual(view.windowState(), state)
                    self.assertEqual(view.isVisible(), visible)
                    self.assertEqual(view.geometry(), geometry)
            view.showNormal()
            self.drain()

    def test_compact_annotations_mouse_theme_and_font_refresh_cover_both_layers(self):
        view = self.view
        view.setPinyinMode(True, self.pinyin)
        view.setCompactMode(True)
        self.drain()
        for show_mouse in (False, True, False):
            view.setMouseVisible(show_mouse)
            self.drain()
            geometry = view.geometry()
            for enabled in (False, True):
                view.setPinyinMode(enabled)
                view.updateTheme()
                self.drain()
                self.assertEqual(view.geometry(), geometry)
                self.assertEqual(view.mouse_panel.isHidden(), not show_mouse)
                self.assertTrue(all(label.isHidden() for label in view._annotations))
                self.assertTrue(all(isinstance(label, KeyLabel) or label.isHidden()
                                    for label in view.chart_widget.findChildren(QLabel)))
                self.assert_caps_fit()
        refreshed = []
        original = KeyCap.refreshMetrics
        with patch.object(KeyCap, 'refreshMetrics',
                          lambda cap: (refreshed.append(cap), original(cap))[-1]):
            view._scheduleScreenRefresh()
            self.drain()
        expected = {cap for state in view._boardStates() for cap in state['crs'].values()}
        self.assertEqual(set(refreshed), expected)
        view.setCompactMode(False)
        self.drain()
        for enabled in (False, True):
            view.setPinyinMode(enabled)
            self.assertTrue(all(not label.isHidden() for label in view._annotations))

    def test_pinyin_fits_small_manual_english_view_and_restores_manual_preference(self):
        view = self.view
        view.setAutoFit(False)
        view.resize(420, 300)
        self.drain()
        self.assertTrue(view.scroll_area.transform().isIdentity())
        view.setPinyinMode(True, self.pinyin)
        self.drain()
        self.assertFalse(self.config['guide_auto_fit'])
        self.assertFalse(view.auto_fit_checkbox.isChecked())
        self.assert_caps_fit()
        view.setPinyinMode(False)
        self.drain()
        self.assertTrue(view.scroll_area.transform().isIdentity())

    def test_current_prefix_and_modifier_state_follow_current_layer(self):
        view = self.view
        view.Dit()
        view.Dah()
        view.setPinyinMode(True, self.pinyin)
        self.assertEqual(view._prefix, '12')
        for code, cap in view.crs.items():
            self.assertEqual(cap.enabled(), code.startswith('12'))
        view.reset()
        self.assertTrue(all(cap.enabled() for cap in view.crs.values()))
        view.setPinyinMode(False)
        self.assertTrue(all(cap.enabled() for cap in view.crs.values()))
