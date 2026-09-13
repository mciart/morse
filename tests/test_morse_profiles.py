"""International character examples and safe migration to the unified layout."""

from copy import deepcopy
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, call

from morse_engine import MorseEngine
from morse_profiles import normalize_layouts
from tools.generate_codechart import read_key_data


PROJECT = Path(__file__).resolve().parents[1]
# Independent transcription from Morsey dc120423, not generated from our table.
EXPECTED = dict(zip('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789', (
    '.-', '-...', '-.-.', '-..', '.', '..-.', '--.', '....', '..', '.---',
    '-.-', '.-..', '--', '-.', '---', '.--.', '--.-', '.-.', '...', '-',
    '..-', '...-', '.--', '-..-', '-.--', '--..', '-----', '.----', '..---',
    '...--', '....-', '.....', '-....', '--...', '---..', '----.')))
EXPECTED.update({
    '.': '.-.-.-', ',': '--..--', '?': '..--..', "'": '.----.', '!': '-.-.--',
    '/': '-..-.', '(': '-.--.', ')': '-.--.-', '&': '.-...', ':': '---...',
    ';': '-.-.-.', '=': '-...-', '+': '.-.-.', '-': '-....-', '_': '..--.-',
    '"': '.-..-.', '@': '.--.-.', '$': '...-..-',
})
EXTENSIONS = {'F9': '1122221', 'DELETE': '1221121', 'TAB': '1221221',
              'STAR': '1212111', 'REPEATMODE': '1121121', 'PERCENT': '1122121'}


def binary(pattern):
    return pattern.translate(str.maketrans({'.': '1', '-': '2'}))


class MorseProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = json.loads((PROJECT / 'user_data/layouts.json').read_text(encoding='utf-8-sig'))['layouts']
        cls.key_data = read_key_data(PROJECT / 'MorseCodeGUI.py')

    def test_all_54_characters_and_six_extensions_are_unique(self):
        desktop = normalize_layouts(self.raw)['desktop']['items']
        codes = {item['code']: item for item in desktop}
        self.assertEqual(len(desktop), 130)
        self.assertEqual(len(codes), 130)
        self.assertEqual(len(EXPECTED), 54)
        for character, pattern in EXPECTED.items():
            with self.subTest(character=character):
                item = codes[binary(pattern)]
                self.assertEqual(self.key_data[item['action']]['character'].upper(), character)
        for action, code in EXTENSIONS.items():
            self.assertEqual(codes[code]['action'], action)
            self.assertEqual(len(code), 7)
            self.assertTrue(code.startswith('1'))

    def test_old_pages_and_commands_retire_without_mutating_user_data(self):
        old = deepcopy(self.raw)
        old['typing'] = {'items': [{'action': 'ONE', 'code': '1'}]}
        old['desktop']['supports_prediction'] = True
        old['desktop']['column_len'] = 15
        old['desktop']['items'] += [
            {'action': 'PREDICTION_SELECT', 'code': '1', 'index': 0},
            {'action': 'CHANGELAYOUT', 'code': '1', 'target': 'typing'},
            {'action': 'CODESET', 'code': '1'}, {'emptyspace': True},
        ]
        old['desktop']['items'][0]['label'] = '自定义标签'
        original = deepcopy(old)
        transformed = normalize_layouts(old)
        self.assertEqual(old, original)
        self.assertEqual(list(transformed), ['desktop'])
        self.assertEqual(len(transformed['desktop']['items']), 130)
        self.assertEqual(transformed['desktop']['items'][0]['label'], '自定义标签')
        self.assertNotIn('supports_prediction', transformed['desktop'])
        self.assertNotIn('column_len', transformed['desktop'])
        transformed['desktop']['items'][0]['label'] = 'runtime only'
        self.assertEqual(old, original)

    def test_old_desktop_codes_upgrade_in_one_pass_and_remain_idempotent(self):
        old_codes = {'F9': '122221', 'DELETE': '21121', 'TAB': '21221',
                     'STAR': '12111', 'REPEATMODE': '121121', 'PERCENT': '122121',
                     'SINGLEQUOTE': '121221', 'EXCLAMATION': '121122', 'FSLASH': '22112',
                     'OPENBRACKET': '111221', 'CLOSEBRACKET': '211221', 'AMPERSAND': '21122',
                     'COLON': '212121', 'SEMICOLON': '11121', 'EQUALS': '12212',
                     'PLUS': '12211', 'MINUS': '2221', 'UNDERSCORE': '11221',
                     'DOUBLEQUOTE': '22122', 'AT': '12221', 'DOLLAR': '211121'}
        old = deepcopy(self.raw)
        old['desktop']['items'] = [item for item in old['desktop']['items'] if item['action'] != 'BACKTICK']
        for item in old['desktop']['items']:
            item['code'] = old_codes.get(item['action'], item['code'])
        original = deepcopy(old)
        transformed = normalize_layouts(old)
        self.assertEqual(transformed, normalize_layouts(self.raw))
        self.assertEqual(normalize_layouts(transformed), transformed)
        self.assertEqual(old, original)

    def test_old_conflicting_codes_are_not_aliases_for_dangerous_extensions(self):
        items = normalize_layouts(self.raw)['desktop']['items']
        actual = {item['code']: item['action'] for item in items}
        for pattern, action in (('-..-.', 'FSLASH'), ('.-..-.', 'DOUBLEQUOTE'),
                                ('-.--.', 'OPENBRACKET'), ('.----.', 'SINGLEQUOTE'),
                                ('.-...', 'AMPERSAND'), ('.--.-.', 'AT')):
            self.assertEqual(actual[binary(pattern)], action)
        self.assertEqual(sum(item['action'] == 'DELETE' for item in items), 1)
        self.assertEqual(sum(item['action'] == 'REPEATMODE' for item in items), 1)

    def test_custom_layout_conflict_is_rejected_without_modifying_source(self):
        custom = deepcopy(self.raw)
        custom['desktop']['items'].append({'action': 'CUSTOM', 'code': EXTENSIONS['TAB']})
        before = deepcopy(custom)
        with self.assertRaisesRegex(ValueError, '重复编码'):
            normalize_layouts(custom)
        self.assertEqual(custom, before)

    def test_pre_desktop_file_uses_bundled_template_without_retired_pages(self):
        old = {'typing': {'items': [{'action': 'ONE', 'code': '1'}]}}
        original = deepcopy(old)
        self.assertEqual(normalize_layouts(old, self.raw['desktop']), self.raw)
        self.assertEqual(old, original)
        with self.assertRaisesRegex(ValueError, '缺少统一码表'):
            normalize_layouts(old)

    def test_backtick_is_a_single_nonstandard_extension(self):
        transformed = normalize_layouts(self.raw)
        backticks = [item for item in transformed['desktop']['items'] if item['action'] == 'BACKTICK']
        self.assertEqual(backticks, [{'action': 'BACKTICK', 'code': '1111111'}])
        self.assertEqual(normalize_layouts(transformed), transformed)

    def test_missing_actions_are_filled_without_replacing_custom_parameters(self):
        partial = {'desktop': {'items': [{'action': 'A', 'code': '12', 'label': '我的 A'}]}}
        transformed = normalize_layouts(partial, self.raw['desktop'])['desktop']['items']
        self.assertEqual(len(transformed), 130)
        self.assertEqual(transformed[0], partial['desktop']['items'][0])
        self.assertEqual(len(partial['desktop']['items']), 1)

    def test_invalid_codes_are_rejected(self):
        for invalid in ('', 'dot', 123, None):
            with self.subTest(code=invalid):
                custom = deepcopy(self.raw)
                custom['desktop']['items'].append({'action': 'CUSTOM', 'code': invalid})
                with self.assertRaisesRegex(ValueError, '无效编码'):
                    normalize_layouts(custom)


class UnifiedActionTests(unittest.TestCase):
    """Use actual timing and action dispatch, with a mock OS output boundary."""

    setUpClass = classmethod(MorseProfileTests.setUpClass.__func__)

    def setUp(self):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        import MorseCodeGUI as morse
        from keyboard_output import KeyboardOutput
        self.morse = morse
        self.backend = Mock(spec=['press', 'release', 'send', 'write'])
        self.layout = morse.LayoutManager(str(PROJECT / 'user_data/layouts.json'))
        self.window = SimpleNamespace(key_output=KeyboardOutput(backend=self.backend),
            layoutManager=self.layout, enableRepeatMode=Mock(), toggleSound=Mock())
        manager = morse.ConfigManager.__new__(morse.ConfigManager)
        manager.key_data = self.key_data
        self.actions = manager.initActions(self.window)
        self.layout.set_actions(self.actions)

    def perform_code(self, code):
        engine = MorseEngine({'keylen': 3, 'keyer_mode': 'manual'})
        events, now = [], 0.0
        for symbol in code:
            role = int(symbol) - 1
            events += engine.key(role, True, now)
            events += engine.key(role, False, now + .005)
            now += .01
        events += engine.key(2, True, now)
        committed = [payload for kind, payload in events if kind == 'commit']
        self.assertEqual(len(committed), 1)
        decoded = ''.join(str(symbol) for symbol in committed[0]['symbols'])
        self.assertEqual(decoded, code)
        item = next(item for item in self.layout.get_active_layout()['items'] if item['code'] == decoded)
        item['_action'].perform()

    def test_all_characters_emit_expected_keyboard_or_literal_output(self):
        for character, pattern in EXPECTED.items():
            with self.subTest(character=character):
                self.backend.reset_mock()
                self.perform_code(binary(pattern))
                expected = (call.send(character.lower()) if character.isalnum()
                            else call.write(character, exact=True))
                self.assertEqual(self.backend.mock_calls, [expected])
                self.window.enableRepeatMode.assert_not_called()

    def test_six_new_extension_codes_execute_their_intended_actions(self):
        for action, code in EXTENSIONS.items():
            with self.subTest(action=action):
                self.backend.reset_mock()
                self.window.enableRepeatMode.reset_mock()
                self.perform_code(code)
                if action == 'REPEATMODE':
                    self.window.enableRepeatMode.assert_called_once_with()
                    self.backend.assert_not_called()
                    self.assertEqual(self.backend.mock_calls, [])
                else:
                    self.window.enableRepeatMode.assert_not_called()
                    expected = (call.write('*' if action == 'STAR' else '%', exact=True)
                                if action in ('STAR', 'PERCENT') else
                                call.send({'F9': 'f9', 'DELETE': 'delete', 'TAB': 'tab'}[action]))
                    self.assertEqual(self.backend.mock_calls, [expected])

    def test_backtick_emits_exact_character(self):
        self.perform_code('1111111')
        self.assertEqual(self.backend.mock_calls, [call.write('`', exact=True)])

    def test_old_file_loads_as_unified_desktop_without_rewriting_it(self):
        old = deepcopy(self.raw)
        old['typing'] = {'items': [{'action': 'ONE', 'code': '1'}]}
        old['desktop']['items'] = [item for item in old['desktop']['items'] if item['action'] != 'BACKTICK']
        for item in old['desktop']['items']:
            if item['action'] == 'DELETE':
                item['code'] = '21121'
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'layouts.json'
            raw_bytes = json.dumps({'layouts': old, 'mainlayout': 'typing'}).encode('utf-8')
            path.write_bytes(raw_bytes)
            layout = self.morse.LayoutManager(str(path))
            layout.set_actions(self.actions)
            self.assertEqual(list(layout.layouts), ['desktop'])
            items = layout.get_active_layout()['items']
            self.assertEqual(len(items), 130)
            self.assertEqual(next(item['code'] for item in items if item['action'] == 'DELETE'), EXTENSIONS['DELETE'])
            self.assertTrue(all(item.get('_action') is not None for item in items))
            self.assertEqual(path.read_bytes(), raw_bytes)


if __name__ == '__main__':
    unittest.main()
