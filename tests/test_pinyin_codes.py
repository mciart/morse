"""Independent historical-code and actual keyboard-spelling examples."""

from copy import deepcopy
import json
from pathlib import Path
import unittest

from pinyin_codes import build_pinyin_layout


PROJECT = Path(__file__).resolve().parents[1]
# Transcribed from the user's supplied Zhuyin table, not our production data.
EXPECTED = {
    'ㄅ': ('b', '-...'), 'ㄆ': ('p', '.--..'), 'ㄇ': ('m', '.--.'),
    'ㄈ': ('f', '..-.-'), 'ㄉ': ('d', '.--'), 'ㄊ': ('t', '--.-'),
    'ㄋ': ('n', '---.'), 'ㄌ': ('l', '...'), 'ㄍ': ('g', '-..-'),
    'ㄎ': ('k', '--..-'), 'ㄏ': ('h', '..--'), 'ㄐ': ('j', '-..'),
    'ㄑ': ('q', '.-..-'), 'ㄒ': ('x', '..--.'), 'ㄓ': ('zh', '....'),
    'ㄔ': ('ch', '-.-.'), 'ㄕ': ('sh', '.-.'), 'ㄖ': ('r', '.---'),
    'ㄗ': ('z', '...-'), 'ㄘ': ('c', '-.-..'), 'ㄙ': ('s', '-.-'),
    'ㄧ': ('i', '.'), 'ㄨ': ('u', '-'), 'ㄩ': ('v', '..-'),
    'ㄚ': ('a', '---'), 'ㄛ': ('o', '--'), 'ㄜ': ('e', '-.--'),
    'ㄝ': ('e', '--..'), 'ㄞ': ('ai', '.-.-'), 'ㄟ': ('ei', '..-..'),
    'ㄠ': ('ao', '.-..'), 'ㄡ': ('ou', '..-.'), 'ㄢ': ('an', '.-'),
    'ㄣ': ('en', '-.'), 'ㄤ': ('ang', '--.'), 'ㄥ': ('eng', '..'),
    'ㄦ': ('er', '.---.'),
}


def binary(pattern):
    return pattern.translate(str.maketrans({'.': '1', '-': '2'}))


class PinyinCodeTests(unittest.TestCase):
    def setUp(self):
        self.english = json.loads((PROJECT / 'user_data/layouts.json').read_text(
            encoding='utf-8-sig'))['layouts']['desktop']
        self.layout = build_pinyin_layout(self.english)
        self.items = self.layout['items']
        self.by_action = {item['action']: item for item in self.items}

    def test_all_37_original_codes_emit_the_expected_pinyin_keys(self):
        actual = {item['zhuyin']: item for item in self.items if 'zhuyin' in item}
        self.assertEqual(len(EXPECTED), 37)
        self.assertEqual(actual.keys(), EXPECTED.keys())
        for zhuyin, (text, pattern) in EXPECTED.items():
            with self.subTest(zhuyin=zhuyin):
                self.assertEqual(actual[zhuyin]['code'], binary(pattern))
                self.assertEqual(actual[zhuyin]['pinyin_text'], text)
                self.assertNotIn('extension', actual[zhuyin])

    def test_every_action_and_code_is_unique_with_mouse_enabled(self):
        self.assertEqual(len(self.items), 116)
        self.assertEqual(len(self.by_action), len(self.items))
        self.assertEqual(len({item['code'] for item in self.items}), len(self.items))
        for item in self.items:
            self.assertTrue(item['code'])
            self.assertLessEqual(set(item['code']), {'1', '2'})
        self.assertEqual(sum(item['pinyin_group'] == 'initial' for item in self.items), 23)
        self.assertEqual(sum(item['pinyin_group'] == 'final' for item in self.items), 35)

    def test_complete_spelling_examples_without_ime_backtracking(self):
        cases = {
            'zhang': ('ZH', 'ANG'), 'ni': ('N', 'I'), 'hao': ('H', 'AO'),
            'zhong': ('ZH', 'ONG'), 'ying': ('Y', 'ING'), 'juan': ('J', 'UAN'),
            'lve': ('L', 'VE'), 'jue': ('J', 'UE'), 'xue': ('X', 'UE'),
            'yue': ('Y', 'UE'), 'liu': ('L', 'IU'), 'gui': ('G', 'UI'),
            'lun': ('L', 'UN'), 'zhuang': ('ZH', 'UANG'), 'xiong': ('X', 'IONG'),
            'wu': ('W', 'U'), 'yi': ('Y', 'I'), 'lv': ('L', 'V'),
        }
        for expected, actions in cases.items():
            with self.subTest(expected=expected):
                actual = ''.join(self.by_action['PINYIN_' + action]['pinyin_text']
                                 for action in actions)
                self.assertEqual(actual, expected)

    def test_umlaut_and_e_circumflex_explain_ascii_ime_convention(self):
        for action, label, text in (('V', 'ü', 'v'), ('VE', 'üe', 've'),
                                    ('E_CIRCUMFLEX', 'ê', 'e')):
            item = self.by_action['PINYIN_' + action]
            self.assertEqual(item['label'], label)
            self.assertEqual(item['pinyin_text'], text)
            self.assertIn('输入法按键约定', item['tooltip'])
        for item in self.items:
            if 'pinyin_text' in item:
                self.assertTrue(item['pinyin_text'].isascii())
                self.assertTrue(item['pinyin_text'].islower())

    def test_extensions_are_short_marked_and_not_historical_codes(self):
        original_codes = {binary(pattern) for _, pattern in EXPECTED.values()}
        for item in self.items:
            if item.get('extension'):
                self.assertNotIn(item['code'], original_codes)
                self.assertLessEqual(len(item['code']), 6)
        self.assertTrue(self.by_action['PINYIN_Y']['extension'])
        self.assertTrue(self.by_action['PINYIN_ING']['extension'])

    def test_conflicting_editing_codes_move_and_old_aliases_never_survive(self):
        expected = {'SPACE': '11121', 'ENTER': '12111', 'ESCAPE': '112121',
                    'END': '112122', 'INSERT': '112211'}
        codes = {item['code']: item for item in self.items}
        originals = {item['action']: item for item in self.english['items']}
        for action, replacement in expected.items():
            self.assertEqual(self.by_action[action]['code'], replacement)
            self.assertTrue(self.by_action[action]['extension'])
            self.assertTrue(codes[originals[action]['code']]['action'].startswith('PINYIN_'))
        for action in ('ONE', 'ZERO', 'BACKSPACE', 'TAB', 'TABLEFT', 'DELETE',
                       'HOME', 'PAGEUP', 'PAGEDOWN', 'LEFTARROW', 'RIGHTARROW',
                       'UPARROW', 'DOWNARROW', 'SOUND'):
            self.assertEqual(self.by_action[action]['code'], originals[action]['code'])

    def test_mouse_retains_all_31_codes_and_bound_action_identity(self):
        for item in self.english['items']:
            item['_action'] = object()
        source_snapshot = deepcopy({key: value for key, value in self.english.items()
                                    if key != 'items'})
        expected = {item['action']: item for item in self.english['items']}
        result = build_pinyin_layout(self.english)
        actual_mice = [item for item in result['items'] if item['pinyin_group'] == 'mouse']
        self.assertEqual(len(actual_mice), 31)
        for item in result['items']:
            if item['pinyin_group'] not in ('mouse', 'control'):
                continue
            original = expected[item['action']]
            self.assertIs(item['_action'], original['_action'])
            self.assertNotIn('pinyin_text', item)
            if item['pinyin_group'] == 'mouse':
                self.assertEqual(item['code'], original['code'])
        self.assertEqual({key: value for key, value in self.english.items()
                          if key != 'items'}, source_snapshot)

    def test_source_is_unchanged_and_output_metadata_is_independent(self):
        self.english['items'][26]['custom'] = {'value': [1, 2]}
        before = deepcopy(self.english)
        result = build_pinyin_layout(self.english)
        self.assertEqual(self.english, before)
        one = next(item for item in result['items'] if item['action'] == 'ONE')
        one['custom']['value'].append(3)
        one['label'] = '新标签'
        self.assertEqual(self.english, before)

    def test_custom_controls_keep_free_codes_and_relocate_conflicts_deterministically(self):
        for item in self.english['items']:
            if item['action'] == 'SPACE':
                item['code'] = '1222222'
            elif item['action'] == 'TAB':
                item['code'] = binary('---')  # Conflicts with a.
        original = deepcopy(self.english)
        first = build_pinyin_layout(self.english)
        reordered = deepcopy(self.english)
        reordered['items'].reverse()
        second = build_pinyin_layout(reordered)
        first_controls = {item['action']: item['code'] for item in first['items']
                          if item['pinyin_group'] == 'control'}
        second_controls = {item['action']: item['code'] for item in second['items']
                           if item['pinyin_group'] == 'control'}
        self.assertEqual(first_controls, second_controls)
        self.assertEqual(first_controls['SPACE'], '1222222')
        self.assertNotEqual(first_controls['TAB'], binary('---'))
        self.assertEqual(len({item['code'] for item in first['items']}), len(first['items']))
        self.assertEqual(self.english, original)

    def test_mouse_collision_is_reported_without_changing_its_code(self):
        mouse = next(item for item in self.english['items'] if item['action'].startswith('MOUSE'))
        mouse['code'] = binary('---')
        before = deepcopy(self.english)
        with self.assertRaisesRegex(ValueError, '鼠标编码冲突'):
            build_pinyin_layout(self.english)
        self.assertEqual(self.english, before)

    def test_duplicate_actions_and_invalid_inherited_codes_fail_clearly(self):
        self.english['items'].append(dict(self.english['items'][26]))
        with self.assertRaisesRegex(ValueError, '重复动作'):
            build_pinyin_layout(self.english)
        self.english['items'].pop()
        self.english['items'][26]['code'] = 'abc'
        with self.assertRaisesRegex(ValueError, '无效编码'):
            build_pinyin_layout(self.english)


if __name__ == '__main__':
    unittest.main()
