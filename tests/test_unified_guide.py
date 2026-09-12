"""Verify the unified guide against the real dispatch path, without OS input."""

import json
from PyQt5.QtCore import QPoint, QRect
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
        self.assertEqual(len(items), 137)
        self.assertEqual(set(view.crs), {item['code'] for item in items})
        self.assertFalse(hasattr(view, 'layout_selector'))
        expected = {i['action']: i['code'] for i in self.layout.layouts['main']['items']
                    if i['action'] not in ('CHANGELAYOUT', 'CODESET')}
        actual = {i['action']: i['code'] for i in items if i['action'] in expected}
        self.assertEqual(actual, expected)
        extras = [i for i in items if i['action'].startswith('MOUSE') or i['action'] == 'PREDICTION_SELECT']
        self.assertEqual(len(extras), 39)
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

    def test_painted_caps_keep_theme_modifier_and_candidate_states(self):
        from ui_theme import THEME_COLORS

        self.window.engine_timer.stop()
        view = self.window.codeslayoutview
        candidates = sorted((cap for cap in view.crs.values() if cap.is_prediction),
                            key=lambda cap: cap.item['target'])
        ctrl = view.keystroke_crs_map['CTRL']
        for theme in ('light', 'dark'):
            self.window.themeComboBox.setCurrentIndex(self.window.themeComboBox.findData(theme))
            self.app.processEvents()
            with patch.object(self.window.typestate, 'getpredictions', return_value=['the']) as predictions:
                view.reset()
                view.setOutputState(('ctrl',), True)
                self.assertEqual(ctrl._appearance[0], THEME_COLORS['highlight'])
                self.assertEqual(ctrl.character._foreground, THEME_COLORS['highlight_text'])
                self.assertEqual(candidates[0].character._foreground, THEME_COLORS['text'])
                self.assertEqual(candidates[1].character._foreground, THEME_COLORS['disabled'])
                view.Dit()
                self.assertEqual(candidates[0].character._foreground, THEME_COLORS['disabled'])
                cap_a = view.keystroke_crs_map['A']
                self.assertEqual(cap_a.codeline._prefix_color, THEME_COLORS['success'])
                self.assertEqual(cap_a.codeline._prefix_length, 1)
                predictions.return_value = ['of', 'a']
                view.reset()
                self.assertEqual(candidates[0].character.text(), '1 · of')
                self.assertEqual(candidates[1].character.text(), '2 · a')
                self.assertEqual(candidates[1].character._foreground, THEME_COLORS['text'])

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
        self.assertEqual(len(view.crs), 137)

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

    def test_candidate_slots_keep_numbers_case_and_live_availability(self):
        view = self.window.codeslayoutview
        view.resize(1280, 780)
        self.app.processEvents()
        view.config['upperchars'] = True
        candidates = sorted((cap for cap in view.crs.values() if cap.is_prediction),
                            key=lambda cap: cap.item['target'])
        with patch.object(self.window.typestate, 'getpredictions', return_value=[]) as predictions:
            view.reset()
            self.assertEqual([cap.character.text() for cap in candidates],
                             [str(number) + ' · —' for number in range(1, 9)])
            self.assertTrue(all(not cap.enabled() for cap in candidates))
            self.assertIn('当前不能选择', candidates[5].toolTip())
            predictions.return_value = ['the', 'a']
            view.setOutputState((), False)
            self.assertEqual(candidates[0].character.text(), '1 · the')
            self.assertEqual(candidates[1].character.text(), '2 · a')
            self.assertEqual([cap.enabled() for cap in candidates], [True, True] + [False] * 6)
            view.Dah()
            view.Dah()
            predictions.return_value = ['of']
            view.setOutputState((), False)
            self.assertTrue(candidates[0].enabled())
            self.assertEqual(candidates[0].disabledchars, 2)
            self.assertEqual(candidates[0].character.text(), '1 · of')
            self.assertFalse(candidates[1].enabled())
            predictions.return_value = ['of', 'a']
            view.setOutputState((), False)
            self.assertTrue(candidates[1].enabled())
            self.assertEqual(candidates[1].disabledchars, 2)
            view.reset()
            view.Dit()
            predictions.return_value = ['a']
            view.setOutputState((), False)
            self.assertFalse(candidates[0].enabled())
            view.reset()
            self.assertTrue(candidates[0].enabled())
        self.assertEqual(len(view.crs), 137)

    def test_long_candidates_are_elided_without_expanding_the_guide(self):
        view = self.window.codeslayoutview
        view.resize(1280, 780)
        self.app.processEvents()
        original_width = view.chart_widget.width()
        original_scroll_range = view.scroll_area.horizontalScrollBar().maximum()
        cap = next(cap for cap in view.crs.values() if cap.is_prediction and cap.item['target'] == 0)
        word = 'longcandidate' * 30
        with patch.object(self.window.typestate, 'getpredictions', return_value=[word]):
            view.reset()
            self.app.processEvents()
            self.assertTrue(cap.character.text().startswith('1 · '))
            self.assertTrue(cap.character.text().endswith('…'))
            self.assertIn(word, cap.toolTip())
            self.assertEqual(view.chart_widget.width(), original_width)
            self.assertEqual(view.scroll_area.horizontalScrollBar().maximum(), original_scroll_range)
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
