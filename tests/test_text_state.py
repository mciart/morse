"""Retired candidate codes cannot revive prediction or replace typed text."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

import test_mapping_actions as mapping

morse = mapping.morse


class TextStateTests(TestCase):
    def test_text_buffer_and_abbreviations_need_no_database_or_files(self):
        with patch('builtins.open', side_effect=AssertionError('Unexpected resource access')):
            state = morse.TypeState({'hi': 'Hello'})
            state.pushchar('h')
            state.pushstr('ix')
            state.popchar()
            self.assertEqual(state.text, 'hi')
            self.assertEqual(state.get_abbreviation(), ('Hello', 2))

    def test_old_layout_candidates_are_ignored_without_overwriting_custom_keys(self):
        original = json.dumps({'mainlayout': 'desktop', 'layouts': {'desktop': {
            'supports_prediction': True,
            'items': [{'action': 'A', 'code': '12', 'label': 'Custom key'},
                      {'action': 'PREDICTION_SELECT', 'code': '2211111', 'target': 0}],
        }}})
        with TemporaryDirectory() as directory:
            source = Path(directory) / 'layouts.json'
            source.write_text(original, encoding='utf-8')
            manager = morse.LayoutManager(str(source))
            self.assertEqual(manager.get_active_layout()['items'],
                             [{'action': 'A', 'code': '12', 'label': 'Custom key'}])
            self.assertEqual(source.read_text(encoding='utf-8'), original)


class RemovedCandidateTests(TestCase):
    setUpClass = classmethod(mapping.MappingActionTests.setUpClass.__func__)
    setUp = mapping.MappingActionTests.setUp
    tearDown = mapping.MappingActionTests.tearDown
    start_input = mapping.MappingActionTests.start_input
    enter_code = mapping.MappingActionTests.enter_code

    def test_former_candidates_send_nothing_and_preserve_typed_text(self):
        self.window.changeLayout('desktop')
        self.views.append(self.window.codeslayoutview)
        self.enter_code('12')
        self.backend.reset_mock()
        for code in ('2211111', '2211112', '2211121', '2211122',
                     '2211211', '2211212', '2211221', '2211222'):
            with self.subTest(code=code):
                self.enter_code(code)
                self.assertEqual(self.backend.mock_calls, [])
                self.assertEqual(self.window.typestate.text, 'a')
        for layout in self.layout.layouts.values():
            self.assertTrue(all(item.get('action') != 'PREDICTION_SELECT'
                                for item in layout['items']))
