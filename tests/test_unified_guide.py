"""Verify the unified guide against the real dispatch path, without OS input."""

import json
from PyQt5.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PyQt5.QtGui import QMouseEvent
from unittest import TestCase
from unittest.mock import call, patch

import test_mapping_actions as mapping

morse = mapping.morse


class UnifiedGuideTests(TestCase):
    setUpClass = classmethod(mapping.MappingActionTests.setUpClass.__func__)
    start_input = mapping.MappingActionTests.start_input
    enter_code = mapping.MappingActionTests.enter_code
    select_page = mapping.MappingActionTests.select_page
    tearDown = mapping.MappingActionTests.tearDown

    def setUp(self):
        mapping.MappingActionTests.setUp(self)
        self.select_page('desktop')
        self.app.processEvents()

    def test_every_action_is_registered_and_keyboard_codes_are_preserved(self):
        items = self.layout.get_active_layout()['items']
        view = self.window.codeslayoutview
        self.assertEqual(len(items), 129)
        self.assertEqual(set(view.crs), {item['code'] for item in items})
        self.assertFalse(hasattr(view, 'layout_selector'))
        expected = {i['action']: i['code'] for i in self.layout.layouts['main']['items']
                    if i['action'] not in ('CHANGELAYOUT', 'CODESET')}
        actual = {i['action']: i['code'] for i in items if i['action'] in expected}
        self.assertEqual(actual, expected)
        extras = [i for i in items if i['action'].startswith('MOUSE')]
        self.assertEqual(len(extras), 31)
        self.assertTrue(all(len(i['code']) == 7 for i in extras))

    def test_minimize_keeps_independent_window_and_close_hides_without_stopping_input(self):
        view = self.window.codeslayoutview
        listener = self.window.listenerThread
        self.assertEqual(view.windowType(), morse.Qt.Window)
        self.assertIsNone(view.parentWidget())
        self.assertTrue(view.windowFlags() & morse.Qt.WindowMinimizeButtonHint)
        view.showMinimized()
        self.app.processEvents()
        self.assertTrue(view.isMinimized())
        self.assertTrue(view.isVisible())
        view.showNormal()
        view.close()
        self.app.processEvents()
        self.assertTrue(view.isHidden())
        self.assertIs(self.window.listenerThread, listener)
        self.assertTrue(self.window.engine_timer.isActive())
        self.assertFalse(view.config.get('off', False))

    def test_prefix_highlighting_does_not_restyle_or_relayout_key_text(self):
        from virtual_keyboard import KeyCap, KeyLabel

        self.window.engine_timer.stop()
        view = self.window.codeslayoutview
        view.reset()
        self.app.processEvents()
        bounds = {code: cap.geometry() for code, cap in view.crs.items()}
        with patch.object(KeyCap, 'setStyleSheet', side_effect=AssertionError('restyling on input')), \
                patch.object(KeyLabel, 'setText', side_effect=AssertionError('relayout on input')):
            view.Dit()
            view.Dah()
        self.app.processEvents()
        for code, cap in view.crs.items():
            self.assertEqual(cap.geometry(), bounds[code])
            self.assertEqual(cap.enabled(), code.startswith('12') and cap.is_available)
            self.assertEqual(cap.codeline.text(), cap.code)
        self.assertEqual(view.keystroke_crs_map['A'].codeline._prefix_length, 2)

    def test_painted_caps_keep_theme_modifier_and_prefix_states(self):
        from ui_theme import THEME_COLORS

        self.window.engine_timer.stop()
        view = self.window.codeslayoutview
        ctrl = view.keystroke_crs_map['CTRL']
        for theme in ('light', 'dark'):
            self.window.themeComboBox.setCurrentIndex(self.window.themeComboBox.findData(theme))
            self.app.processEvents()
            view.reset()
            view.setOutputState(('ctrl',), True)
            self.assertEqual(ctrl._appearance[0], THEME_COLORS['highlight'])
            self.assertEqual(ctrl.character._foreground, THEME_COLORS['highlight_text'])
            view.Dit()
            self.assertEqual(view.keystroke_crs_map['B'].character._foreground, THEME_COLORS['disabled'])
            cap_a = view.keystroke_crs_map['A']
            self.assertEqual(cap_a.codeline._prefix_color, THEME_COLORS['success'])
            self.assertEqual(cap_a.codeline._prefix_length, 1)
            view.reset()
            self.assertEqual(view.keystroke_crs_map['B'].character._foreground, THEME_COLORS['text'])

    def test_keyboard_legends_match_us_keys_and_keep_standard_capitalization(self):
        view = self.window.codeslayoutview
        expected = {
            'ESCAPE': 'Esc', 'TAB': 'Tab', 'BACKSPACE': 'Backspace', 'CAPSLOCK': 'Caps Lock',
            'ENTER': 'Enter', 'SHIFT': 'Shift', 'CTRL': 'Ctrl', 'ALT': 'Alt', 'WINDOWS': 'Win',
            'SPACE': 'Space', 'APPLICATION': 'Menu', 'HOME': 'Home', 'END': 'End',
            'INSERT': 'Insert', 'DELETE': 'Delete', 'PAGEUP': 'PgUp', 'PAGEDOWN': 'PgDn',
            'TABLEFT': 'Shift+Tab', 'STARTMENU': 'Start Menu',
        }
        caps = {cap.item['action']: cap for cap in view.crs.values()}
        for uppercase in (True, False):
            view.config['upperchars'] = uppercase
            for action, label in expected.items():
                caps[action].updateView()
                self.assertEqual(caps[action].character.text(), label)
            caps['A'].updateView()
            self.assertEqual(caps['A'].character.text(), 'A' if uppercase else 'a')
        self.assertEqual(caps['MOUSECLICKLEFT'].character.text(), '单击')

    def test_small_window_keeps_return_button_visible_and_scrolls_only_the_guide(self):
        view = self.window.codeslayoutview
        view.setAutoFit(False)
        view.resize(360, 280)
        self.app.processEvents()
        self.assertEqual((view.width(), view.height()), (360, 280))
        button = view.settings_button
        self.assertTrue(button.isVisible())
        button_rectangle = QRect(button.mapTo(view, QPoint(0, 0)), button.size())
        self.assertTrue(view.rect().contains(button_rectangle))
        self.assertGreater(view.scroll_area.horizontalScrollBar().maximum(), 0)
        self.assertGreater(view.scroll_area.verticalScrollBar().maximum(), 0)
        view.scroll_area.verticalScrollBar().setValue(view.scroll_area.verticalScrollBar().maximum())
        self.app.processEvents()
        self.assertEqual(button.mapTo(view, QPoint(0, 0)), button_rectangle.topLeft())
        self.assertTrue(button.isVisible())

    def test_auto_fit_shows_the_whole_board_with_mouse_optional(self):
        view = self.window.codeslayoutview
        self.assertFalse(view.mouse_checkbox.isChecked())
        self.assertTrue(view.mouse_panel.isHidden())
        self.assertTrue(view.auto_fit_checkbox.isChecked())
        caps = {cap.item['action']: cap for cap in view.crs.values()}
        for action in ('STARTMENU', 'REPEATMODE', 'SOUND'):
            self.assertTrue(caps[action].isVisible())
        for show_mouse in (False, True):
            view.setMouseVisible(show_mouse)
            for size in ((1280, 780), (720, 460), (360, 280)):
                view.resize(*size)
                self.app.processEvents()
                viewport = view.scroll_area
                scene_bounds = viewport.mapFromScene(viewport.sceneRect()).boundingRect()
                self.assertTrue(viewport.viewport().rect().contains(scene_bounds), (size, scene_bounds))
                self.assertEqual(viewport.horizontalScrollBar().maximum(), 0)
                self.assertEqual(viewport.verticalScrollBar().maximum(), 0)
                self.assertTrue(view.settings_button.isVisible())
            self.assertEqual(view.mouse_panel.isHidden(), not show_mouse)
        self.assertEqual(len(view.crs), 129)

    def test_view_options_emit_once_and_manual_size_uses_no_transform(self):
        view = self.window.codeslayoutview
        mouse_changes, fit_changes = [], []
        view.mouseVisibilityChanged.connect(mouse_changes.append)
        view.mouseVisibilityChanged.connect(view.setMouseVisible)
        view.autoFitChanged.connect(fit_changes.append)
        view.autoFitChanged.connect(view.setAutoFit)
        view.mouse_checkbox.setChecked(True)
        view.auto_fit_checkbox.setChecked(False)
        self.app.processEvents()
        self.assertEqual(mouse_changes, [True])
        self.assertEqual(fit_changes, [False])
        self.assertTrue(view.scroll_area.transform().isIdentity())
        self.assertTrue(view.config['show_mouse'])
        self.assertFalse(view.config['guide_auto_fit'])

    def test_mouse_text_has_vertical_room_for_native_font_metrics(self):
        view = self.window.codeslayoutview
        view.setMouseVisible(True)
        self.app.processEvents()
        for cap in view.crs.values():
            if cap.item['action'].startswith('MOUSE'):
                for label in (cap.character, cap.codeline):
                    self.assertGreaterEqual(label.height(), label.fontMetrics().height() + 4)
                    self.assertGreaterEqual(label.height(), label.sizeHint().height())
        headings = [label for label in view.mouse_panel.findChildren(morse.QLabel)
                    if label.text().startswith(('↖', '↑', '↗', '←', '→', '↙', '↓', '↘'))]
        self.assertEqual(len(headings), 8)
        for heading in headings:
            self.assertGreaterEqual(heading.height(), heading.fontMetrics().height() + 4)

    def test_feedback_updates_do_not_refresh_keycaps_and_result_survives_reset(self):
        view = self.window.codeslayoutview
        first_cap = next(iter(view.crs.values()))
        with patch.object(first_cap, 'updateView', wraps=first_cap.updateView) as redraw:
            for tick in range(101):
                view.setInputFeedback(('dot', 'dash'), tick / 100, sounding='dash')
            redraw.assert_not_called()
        panel = view.input_feedback
        self.assertEqual(panel._roles, frozenset(('dot', 'dash')))
        self.assertEqual(panel.progress.value(), 1000)
        view.showResult('A')
        view.reset()
        view.Dit()
        self.assertEqual(panel.result_label._full_text, '已输入：A')
        self.assertEqual(view.input_label._full_text, '•')
        self.assertEqual(panel.progress.value(), 0)
        view.showResult('••••••••', False)
        self.assertIn('无效码', panel.result_label._full_text)
        self.assertTrue(panel.result_timer.isActive())
        panel.result_timer.timeout.emit()
        self.assertEqual(panel.result_label._full_text, '最近输入将显示在这里')

    def test_feedback_and_return_controls_fit_small_window_with_long_results(self):
        # This checks geometry for a supplied state, not the live keyer tick.
        self.window.engine_timer.stop()
        view = self.window.codeslayoutview
        view.resize(360, 280)
        view.setInputFeedback(('straight',), .42, sounding='straight')
        view.showResult('a long candidate ' * 40)
        self.app.processEvents()
        self.assertEqual((view.width(), view.height()), (360, 280))
        for widget in (view.input_feedback, view.settings_button, view.view_options, view.status_bar):
            rectangle = QRect(widget.mapTo(view, QPoint(0, 0)), widget.size())
            self.assertTrue(view.rect().contains(rectangle), (widget, rectangle))
        self.assertGreater(view.scroll_area.height(), 10)
        panel = view.input_feedback
        self.assertEqual(panel.dot_label.text(), '• 按住')
        self.assertEqual(panel.progress.value(), 420)
        self.assertIn('long candidate', panel.result_label.toolTip())
        self.assertTrue(panel.result_label.text().endswith('…'))

    def test_feedback_messages_keep_complete_error_text_without_morse_prefix(self):
        view = self.window.codeslayoutview
        panel = view.input_feedback
        for message in ('无效码：••••••••', '音频不可用：请检查输出设备'):
            view.showMessage(message, success=False)
            self.assertEqual(panel.result_label._full_text, message)
            self.assertFalse(panel._result_success)
            self.assertTrue(panel.result_timer.isActive())
        view.showMessage('已暂停')
        self.assertEqual(panel.result_label._full_text, '已暂停')
        self.assertTrue(panel._result_success)
        view.showResult('Enter')
        self.assertEqual(panel.result_label._full_text, '已输入：Enter')

    def test_candidates_are_absent_even_from_legacy_user_layouts(self):
        from virtual_keyboard import VirtualKeyboardView

        layout = dict(self.layout.get_active_layout())
        layout['items'] = list(layout['items']) + [
            dict(action='PREDICTION_SELECT', code='22211111', target=0, label='旧候选')]
        view = VirtualKeyboardView(layout, dict(self.window.config))
        self.views.append(view)
        self.assertNotIn('22211111', view.crs)
        self.assertNotIn('PREDICTION_SELECT', view.keystroke_crs_map)
        self.assertFalse(any(label.text() == '词语候选' for label in view.findChildren(morse.QLabel)))

    def test_compact_mode_is_tight_transparent_and_preserves_full_geometry_and_session(self):
        view = self.window.codeslayoutview
        listener = self.window.listenerThread
        view.setGeometry(30, 40, 720, 460)
        self.app.processEvents()
        full_geometry = QRect(view.geometry())
        full_scale = view.scroll_area.transform().m11()
        proxy, caps = view.scroll_area.proxy, dict(view.crs)
        changes = []
        view.compactModeChanged.connect(changes.append)
        view.compactModeChanged.connect(view.setCompactMode)
        view.compact_checkbox.setChecked(True)
        self.app.processEvents()
        self.assertEqual(changes, [True])
        self.assertTrue(view.config['guide_compact'])
        self.assertTrue(view.isCompactMode())
        self.assertTrue(view.isVisible())
        self.assertTrue(view.windowFlags() & Qt.FramelessWindowHint)
        self.assertTrue(view.windowFlags() & Qt.WindowStaysOnTopHint)
        self.assertTrue(view.windowFlags() & Qt.WindowDoesNotAcceptFocus)
        self.assertTrue(view.testAttribute(Qt.WA_TranslucentBackground))
        self.assertTrue(view.testAttribute(Qt.WA_ShowWithoutActivating))
        for widget in (view.header_widget, view.input_feedback, view.status_bar):
            self.assertTrue(widget.isHidden())
        self.assertTrue(all(label.isHidden() for label in view._annotations))
        self.assertTrue(all(cap.character.isVisible() and cap.codeline.isVisible()
                            for cap in view.crs.values() if not cap.item['action'].startswith('MOUSE')))
        self.assertEqual(view.scroll_area.geometry(), view.rect())
        board = view.scroll_area.mapFromScene(view.scroll_area.sceneRect()).boundingRect()
        self.assertLessEqual(abs(board.width() - view.width()), 2)
        self.assertLessEqual(abs(board.height() - view.height()), 2)
        self.assertLess(view.height(), full_geometry.height())
        self.assertAlmostEqual(view.scroll_area.transform().m11(), full_scale, delta=.002)
        self.assertIs(view.scroll_area.proxy, proxy)
        self.assertEqual(view.crs, caps)
        self.assertIs(self.window.listenerThread, listener)

        # The right-click escape route is always available without a toolbar.
        menu = view.createViewMenu()
        self.assertEqual(menu.actions()[0].text(), '完整显示')
        menu.actions()[0].trigger()
        menu.deleteLater()
        self.app.processEvents()
        self.assertEqual(changes, [True, False])
        self.assertFalse(view.isCompactMode())
        self.assertEqual(view.geometry(), full_geometry)
        self.assertFalse(view.windowFlags() & Qt.FramelessWindowHint)
        self.assertFalse(view.testAttribute(Qt.WA_TranslucentBackground))
        self.assertTrue(view.header_widget.isVisible())
        self.assertTrue(view.input_feedback.isVisible())
        self.assertTrue(all(not label.isHidden() for label in view._annotations))

    def test_compact_mode_respects_mouse_and_retains_manual_zoom_preference(self):
        view = self.window.codeslayoutview
        view.setAutoFit(False)
        view.setCompactMode(True)
        for show_mouse in (True, False):
            view.setMouseVisible(show_mouse)
            self.app.processEvents()
            self.assertEqual(view.mouse_panel.isHidden(), not show_mouse)
            self.assertEqual(view.config['show_mouse'], show_mouse)
            self.assertFalse(view.config['guide_auto_fit'])
            self.assertTrue(view.scroll_area.auto_fit)
            board = view.scroll_area.mapFromScene(view.scroll_area.sceneRect()).boundingRect()
            self.assertLessEqual(abs(board.width() - view.width()), 2)
            self.assertLessEqual(abs(board.height() - view.height()), 2)
            self.assertEqual(view.scroll_area.horizontalScrollBar().maximum(), 0)
            self.assertEqual(view.scroll_area.verticalScrollBar().maximum(), 0)
        view.setCompactMode(False)
        self.app.processEvents()
        self.assertTrue(view.scroll_area.transform().isIdentity())
        self.assertFalse(view.auto_fit_checkbox.isChecked())

    def test_compact_gap_pixels_are_transparent_but_keys_remain_opaque_in_both_themes(self):
        view = self.window.codeslayoutview
        view.resize(720, 460)
        view.setCompactMode(True)
        for theme in ('dark', 'light'):
            self.window.themeComboBox.setCurrentIndex(self.window.themeComboBox.findData(theme))
            self.app.processEvents()
            viewport = view.scroll_area
            frame = view.grab()
            image = frame.toImage()
            esc, f1 = (view.keystroke_crs_map[key].geometry() for key in ('ESCAPE', 'F1'))
            left = view.keystroke_crs_map['LEFTARROW'].geometry()
            up = view.keystroke_crs_map['UPARROW'].geometry()
            points = ((QPointF(left.center().x(), up.center().y()), 0),
                      (QPointF(esc.center()), 255))
            for scene_point, expected_alpha in points:
                point = viewport.viewport().mapTo(view, viewport.mapFromScene(scene_point))
                self.assertEqual(image.pixelColor(round(point.x() * frame.devicePixelRatio()),
                                                  round(point.y() * frame.devicePixelRatio())).alpha(), expected_alpha)

    def test_bottom_commands_share_symbol_space_beside_navigation(self):
        view = self.window.codeslayoutview
        view.setCompactMode(True)
        self.app.processEvents()
        keys = view.keystroke_crs_map
        for action in ('STARTMENU', 'REPEATMODE', 'SOUND'):
            bounds = keys[action].geometry()
            self.assertGreater(bounds.top(), keys['UNDERSCORE'].geometry().bottom())
            self.assertLess(bounds.bottom(), keys['DOWNARROW'].geometry().bottom())
            self.assertLess(bounds.right(), keys['LEFTARROW'].geometry().left())

    def test_compact_drag_stays_on_screen_and_hidden_mode_changes_stay_hidden(self):
        view = self.window.codeslayoutview
        view.setCompactMode(True)
        self.app.processEvents()
        target = view.scroll_area.viewport()
        start = QPointF(target.mapToGlobal(QPoint(20, 20)))
        events = (
            QMouseEvent(QEvent.MouseButtonPress, QPointF(20, 20), start, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier),
            QMouseEvent(QEvent.MouseMove, QPointF(20, 20), start - QPointF(10000, 10000), Qt.NoButton, Qt.LeftButton, Qt.NoModifier),
            QMouseEvent(QEvent.MouseButtonRelease, QPointF(20, 20), start, Qt.LeftButton, Qt.NoButton, Qt.NoModifier),
        )
        for event in events:
            self.app.sendEvent(target, event)
        available = self.app.desktop().availableGeometry(view)
        self.assertEqual(view.pos(), available.topLeft())
        self.assertIsNone(view._drag_offset)
        view.hide()
        for compact in (False, True, False):
            view.setCompactMode(compact)
            self.assertTrue(view.isHidden())

    def test_saved_compact_mode_is_applied_before_initial_show(self):
        from virtual_keyboard import VirtualKeyboardView

        view = VirtualKeyboardView(self.layout.get_active_layout(), dict(self.window.config, guide_compact=True))
        self.views.append(view)
        self.assertTrue(view.isCompactMode())
        self.assertTrue(view.isHidden())
        self.assertTrue(view.header_widget.isHidden())
        self.assertTrue(view.compact_checkbox.isChecked())

    def test_compact_switch_preserves_minimization(self):
        view = self.window.codeslayoutview
        view.showMinimized()
        self.app.processEvents()
        for compact in (True, False):
            view.setCompactMode(compact)
            self.app.processEvents()
            self.assertTrue(view.isMinimized())
            self.assertTrue(view.isVisible())

    def test_keyboard_and_mouse_execute_without_switching_layout(self):
        listener = self.window.listenerThread
        actions = {item['action']: item['code'] for item in self.layout.get_active_layout()['items']}
        with patch.object(morse.mouse, 'move') as move, patch.object(morse.mouse, 'double_click') as double_click:
            self.enter_code(actions['A'])
            self.enter_code(actions['MOUSERIGHT5'])
            self.enter_code(actions['MOUSEDBLCLICKLEFT'])
            self.enter_code(actions['CTRL'])
            self.enter_code(actions['V'])
        move.assert_called_once_with(5, 0, False)
        double_click.assert_called_once_with(button=morse.mouse.LEFT)
        self.assertEqual(self.backend.mock_calls, [call.send('a'), call.press('ctrl'),
                                                   call.send('v'), call.release('ctrl')])
        self.assertEqual(self.layout.active_layout_name, 'desktop')
        self.assertIs(self.window.listenerThread, listener)

    def test_theme_choice_is_saved_and_refreshes_the_open_guide(self):
        view = self.window.codeslayoutview
        with patch.object(view, 'updateTheme', wraps=view.updateTheme) as refresh:
            for choice in ('light', 'dark', 'system'):
                index = self.window.themeComboBox.findData(choice)
                self.window.themeComboBox.setCurrentIndex(index)
                self.app.processEvents()
                self.assertEqual(self.app.theme_manager.mode, choice)
                with open(self.window.configManager.config_file, encoding='utf-8') as stream:
                    self.assertEqual(json.load(stream)['theme'], choice)
            self.assertGreaterEqual(refresh.call_count, 2)
        self.assertIs(self.window.codeslayoutview, view)

    def test_unified_guide_has_no_conflicting_codes_or_page_switch_actions(self):
        items = self.layout.get_active_layout()['items']
        self.assertEqual(len({i['code'] for i in items}), len(items))
        self.assertFalse(any(i['action'] in ('CHANGELAYOUT', 'CODESET') for i in items))
        self.assertTrue(self.window.codeslayoutview.testAttribute(morse.Qt.WA_ShowWithoutActivating))

    def test_changing_theme_preserves_previously_saved_settings(self):
        # Legacy mappings remain available to internal dispatch, while saved
        # settings and subsequent starts use the unified keyboard guide.
        self.window.changeLayout('mouse')
        self.assertEqual(self.layout.active_layout_name, 'mouse')
        self.window.minLetterPauseEdit.setValue(1234)
        self.window.saveSettings()
        for choice in ('light', 'dark'):
            self.window.themeComboBox.setCurrentIndex(self.window.themeComboBox.findData(choice))
        with open(self.window.configManager.config_file, encoding='utf-8') as stream:
            config = json.load(stream)
        self.assertEqual(config['theme'], 'dark')
        self.assertEqual(config['guide_layout'], 'desktop')
        self.assertEqual(config['minLetterPause'], 1234)
        self.window.GOButton.click()
        self.app.processEvents()
        self.views.append(self.window.codeslayoutview)
        self.assertEqual(self.layout.active_layout_name, 'desktop')
