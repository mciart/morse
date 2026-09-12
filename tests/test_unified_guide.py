"""Verify the unified guide against the real dispatch path, without OS input."""

import json
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

    def test_every_action_is_visible_and_keyboard_codes_are_preserved(self):
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
        self.window.guideLayoutComboBox.setCurrentIndex(self.window.guideLayoutComboBox.findData('mouse'))
        self.window.minLetterPauseEdit.setText('1234')
        self.window.saveSettings()
        for choice in ('light', 'dark'):
            self.window.themeComboBox.setCurrentIndex(self.window.themeComboBox.findData(choice))
        with open(self.window.configManager.config_file, encoding='utf-8') as stream:
            config = json.load(stream)
        self.assertEqual(config['theme'], 'dark')
        self.assertEqual(config['guide_layout'], 'mouse')
        self.assertEqual(config['minLetterPause'], 1234)
