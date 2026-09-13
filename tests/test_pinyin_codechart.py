"""Check the generated Pinyin reference, including both-document CLI checks."""

from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from morse_profiles import normalize_layouts
from pinyin_codes import build_pinyin_layout
from tools import generate_codechart as charts


PROJECT = Path(__file__).resolve().parents[1]


class PinyinCodeChartTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.layouts = json.loads((PROJECT / 'user_data/layouts.json').read_text(encoding='utf-8-sig'))
        cls.key_data = charts.read_key_data(PROJECT / 'MorseCodeGUI.py')
        cls.display_names = charts.read_guide_display_names(PROJECT / 'virtual_keyboard.py')

    def render(self):
        return charts.render_pinyin_chart(self.layouts, self.key_data, self.display_names)

    def test_committed_chart_matches_all_142_actual_runtime_entries(self):
        text = self.render()
        self.assertEqual(text, (PROJECT / 'docs/pinyin-code-chart.md').read_text(encoding='utf-8'))
        items = build_pinyin_layout(normalize_layouts(self.layouts['layouts'])['desktop'])['items']
        rows = [line.split(' | ') for line in text.splitlines()
                if line.startswith('| ') and '`' in line]
        actual_codes = [row[2].strip('`').translate(str.maketrans({'•': '1', '—': '2'})) for row in rows]
        self.assertEqual(len(rows), 142)
        self.assertEqual(len(set(actual_codes)), 142)
        self.assertEqual(actual_codes, [item['code'] for item in items])
        for row, item in zip(rows, items):
            if 'pinyin_text' in item:
                self.assertEqual(row[0][2:], item['label'])
                self.assertEqual(row[1], item['pinyin_text'])
            if 'zhuyin' in item:
                self.assertIn('注音原码：' + item['zhuyin'], row[3])
            elif 'pinyin_text' in item:
                self.assertIn('软件扩展', row[3])
        for count in (23, 35, 26, 27, 31):
            self.assertIn(f'共 {count} 项。', text)

    def test_pinyin_spelling_and_relocated_controls_are_explicit(self):
        text = self.render()
        self.assertIn('| ü | v | `••—` | 注音原码：ㄩ |', text)
        self.assertIn('| ê | e | `——••` | 注音原码：ㄝ |', text)
        self.assertIn('| üe | ve |', text)
        self.assertIn('| Space | 执行：空格 | `•••—•` | 软件扩展（拼音层重分配） |', text)
        self.assertIn('| 1 | 1 | `•————` | 国际数字码（沿用英文层） |', text)
        for example in ('y + ing → ying', 'j + uan → juan', 'l + üe → lve'):
            self.assertIn(example, text)
        self.assertIn('松开恢复', text)
        self.assertIn('默认采用“按住”方式', text)
        self.assertIn('单击切换中英文层，松开后保留当前层', text)
        self.assertIn('双击只显示或隐藏码表，不改变已选择的层', text)
        self.assertIn('可在设置中开启微软拼音状态同步', text)

    def test_symbols_explain_ime_punctuation_and_show_actual_codes(self):
        text = self.render()
        self.assertIn('全部 26 个可打印符号', text)
        self.assertIn('由当前输入法的标点模式决定', text)
        self.assertIn('| . | 键盘符号：. | `•—•—•—` | 沿用英文层符号码 |', text)
        self.assertIn('| ? | 键盘符号：? | `••••••—` | 软件扩展（拼音层重分配） |', text)
        self.assertIn('| \\` | 键盘符号：\\` | `•••••••` | 沿用英文层符号码 |', text)

    def test_invalid_pinyin_builder_results_fail_generation(self):
        layout = build_pinyin_layout(normalize_layouts(self.layouts['layouts'])['desktop'])
        for field, message in (('code', '重复编码'), ('action', '重复动作')):
            malformed = deepcopy(layout)
            malformed['items'][1][field] = malformed['items'][0][field]
            with patch.object(charts, 'build_pinyin_layout', return_value=malformed):
                with self.assertRaisesRegex(ValueError, message):
                    self.render()

    def test_symbol_documentation_rejects_output_metadata_that_disagrees_with_action(self):
        layout = build_pinyin_layout(normalize_layouts(self.layouts['layouts'])['desktop'])
        symbol = next(item for item in layout['items'] if item['action'] == 'QUESTION')
        symbol['pinyin_symbol'] = '!'
        with patch.object(charts, 'build_pinyin_layout', return_value=layout):
            with self.assertRaisesRegex(ValueError, '拼音符号输出与英文动作不一致'):
                self.render()

    def test_keycap_ast_reader_does_not_execute_ui_source(self):
        with TemporaryDirectory() as directory:
            source = Path(directory) / 'guide.py'
            source.write_text("raise RuntimeError('must not execute')\n"
                              "class VirtualKeyboardView:\n"
                              "    DISPLAY_NAMES = {'SPACE': 'Space'}\n", encoding='utf-8')
            self.assertEqual(charts.read_guide_display_names(source), {'SPACE': 'Space'})

    def test_one_check_validates_both_documents_and_never_writes(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'user_data').mkdir()
            (root / 'user_data/layouts.json').write_text(json.dumps(self.layouts), encoding='utf-8')
            for source in ('MorseCodeGUI.py', 'virtual_keyboard.py'):
                (root / source).write_text((PROJECT / source).read_text(encoding='utf-8'), encoding='utf-8')
            with patch.object(charts, 'PROJECT_ROOT', root), redirect_stdout(StringIO()):
                self.assertEqual(charts.main([]), 0)
                self.assertEqual(charts.main(['--check']), 0)
                for relative in ('codechart.md', 'docs/pinyin-code-chart.md'):
                    with self.subTest(document=relative):
                        target = root / relative
                        expected = target.read_text(encoding='utf-8')
                        target.write_text('outdated', encoding='utf-8')
                        error = StringIO()
                        with redirect_stderr(error):
                            self.assertEqual(charts.main(['--check']), 1)
                        self.assertIn(target.name, error.getvalue())
                        self.assertEqual(target.read_text(encoding='utf-8'), 'outdated')
                        target.unlink()
                        with redirect_stderr(StringIO()):
                            self.assertEqual(charts.main(['--check']), 1)
                        target.write_text(expected, encoding='utf-8')
                self.assertEqual(charts.main(['--check']), 0)


if __name__ == '__main__':
    unittest.main()
