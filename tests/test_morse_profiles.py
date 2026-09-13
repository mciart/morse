"""Fixed Morsey character examples and safe profile/action transitions."""

from copy import deepcopy
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, call

from morse_engine import MorseEngine
from morse_profiles import apply_code_profile, normalize_code_profile
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
        desktop = apply_code_profile(self.raw)['desktop']['items']
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

    def test_legacy_and_other_pages_remain_exact_and_input_is_never_mutated(self):
        original = deepcopy(self.raw)
        self.assertEqual(apply_code_profile(self.raw, 'legacy'), original)
        transformed = apply_code_profile(self.raw, 'morsey')
        self.assertEqual(self.raw, original)
        for name in self.raw:
            if name != 'desktop':
                self.assertEqual(transformed[name], original[name])
        for old, new in zip(original['desktop']['items'], transformed['desktop']['items']):
            if old['action'].startswith('MOUSE'):
                self.assertEqual(new, old)
        transformed['desktop']['items'][0]['label'] = 'runtime only'
        self.assertEqual(self.raw, original)

    def test_old_conflicting_codes_are_not_aliases_for_dangerous_extensions(self):
        items = apply_code_profile(self.raw)['desktop']['items']
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
            apply_code_profile(custom)
        self.assertEqual(custom, before)
        self.assertEqual(apply_code_profile(custom, 'legacy'), before)

    def test_missing_desktop_and_unknown_profile_have_predictable_defaults(self):
        self.assertEqual(normalize_code_profile('legacy'), 'legacy')
        for value in (None, '', 'obsolete'):
            self.assertEqual(normalize_code_profile(value), 'morsey')
        self.assertEqual(apply_code_profile({'typing': self.raw['typing']}),
                         {'typing': self.raw['typing']})

    def test_backtick_is_a_single_nonstandard_extension_and_legacy_has_no_new_item(self):
        transformed = apply_code_profile(self.raw)
        backticks = [item for item in transformed['desktop']['items'] if item['action'] == 'BACKTICK']
        self.assertEqual(backticks, [{'action': 'BACKTICK', 'code': '1111111'}])
        self.assertEqual(apply_code_profile(transformed), transformed)
        self.assertFalse(any(item['action'] == 'BACKTICK'
                             for item in apply_code_profile(self.raw, 'legacy')['desktop']['items']))


class ProfileActionTests(unittest.TestCase):
    """Use actual timing and action dispatch, with a mock OS output boundary."""

    setUpClass = classmethod(MorseProfileTests.setUpClass.__func__)

    def setUp(self):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        import MorseCodeGUI as morse
        from keyboard_output import KeyboardOutput
        self.morse = morse
        self.backend = Mock(spec=['press', 'release', 'send', 'write'])
        self.layout = morse.LayoutManager(str(PROJECT / 'user_data/layouts.json'))
        self.window = SimpleNamespace(key_output=KeyboardOutput(backend=self.backend), typestate=None,
            layoutManager=self.layout, enableRepeatMode=Mock(), changeLayout=Mock(),
            toggleSound=Mock(), cycleLayout=Mock())
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

    def test_switching_profiles_rebinds_actions_without_copying_live_objects(self):
        class UncopyableAction:
            def __deepcopy__(self, memo):
                raise AssertionError('Runtime action copied')

        raw_bytes = Path(self.layout.layout_file).read_bytes()
        self.layout.layouts['desktop']['items'][0]['_action'] = UncopyableAction()
        self.assertTrue(self.layout.set_code_profile('legacy'))
        legacy = self.layout.layouts['desktop']['items']
        self.assertEqual(next(item['code'] for item in legacy if item['action'] == 'DELETE'), '21121')
        self.assertTrue(all('_action' in item for item in legacy))
        self.assertTrue(self.layout.set_code_profile('morsey'))
        current = self.layout.layouts['desktop']['items']
        action = current[0]['_action']
        self.assertFalse(self.layout.set_code_profile('morsey'))
        self.assertIs(self.layout.layouts['desktop']['items'][0]['_action'], action)
        self.assertEqual(Path(self.layout.layout_file).read_bytes(), raw_bytes)
        self.assertTrue(all('_action' not in item for item in self.layout._raw_layouts['desktop']['items']))

    def test_custom_profile_collision_falls_back_and_rejected_switch_is_atomic(self):
        custom = deepcopy(self.raw)
        custom['desktop']['items'].append({'action': 'CUSTOM', 'code': EXTENSIONS['TAB']})
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'layouts.json'
            raw_bytes = json.dumps({'layouts': custom, 'mainlayout': 'desktop'}).encode('utf-8')
            path.write_bytes(raw_bytes)
            with self.assertLogs(level='WARNING'):
                layout = self.morse.LayoutManager(str(path))
            self.assertEqual(layout.code_profile, 'legacy')
            self.assertIn('重复编码', layout.profile_error)
            old_layouts = layout.layouts
            with self.assertRaisesRegex(ValueError, '重复编码'):
                layout.set_code_profile('morsey')
            self.assertIs(layout.layouts, old_layouts)
            self.assertEqual(layout.code_profile, 'legacy')
            self.assertEqual(path.read_bytes(), raw_bytes)


if __name__ == '__main__':
    unittest.main()
