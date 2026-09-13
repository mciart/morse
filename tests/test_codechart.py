"""Keep the published reference aligned with runtime mappings without GUI imports."""

from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tools.generate_codechart import read_key_data, render_chart


PROJECT = Path(__file__).resolve().parents[1]


class CodeChartTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.layouts = json.loads((PROJECT / "user_data" / "layouts.json").read_text(encoding="utf-8"))
        cls.key_data = read_key_data(PROJECT / "MorseCodeGUI.py")

    def test_committed_chart_matches_all_runtime_pages(self):
        expected = render_chart(self.layouts, self.key_data)
        self.assertEqual((PROJECT / "codechart.md").read_text(encoding="utf-8"), expected)
        self.assertIn("## 键盘与鼠标（默认）", expected)
        for page in ("主键盘", "字母", "鼠标", "数字"):
            self.assertIn(f"## {page}\n", expected)
        self.assertNotIn("候选", expected)
        self.assertIn("本页共 129 项", expected)
        self.assertIn("本页共 130 项", expected)
        self.assertIn("## 统一面板：旧版专用", expected)
        self.assertIn("dc120423abd6f211548ad5f60eba2f496fa680bf", expected)

    def test_standard_and_legacy_sections_use_their_actual_distinct_codes(self):
        chart = render_chart(self.layouts, self.key_data)
        standard, rest = chart.split('## 统一面板：旧版专用', 1)
        legacy = rest.split('## ', 1)[0]
        self.assertIn('| / | `—••—•` |', standard)
        self.assertIn('| 删除 | `•——••—•` |', standard)
        self.assertIn('| $ | `•••—••—` |', standard)
        self.assertIn('| \\` | `•••••••` |', standard)
        self.assertIn('| / | `——••—` |', legacy)
        self.assertIn('| 删除 | `—••—•` |', legacy)
        self.assertIn('| $ | `—•••—•` |', legacy)

    def test_layout_specific_codes_and_source_labels_are_preserved(self):
        layouts = deepcopy(self.layouts)
        key_data = deepcopy(self.key_data)
        key_data["A"]["label"] = "测试字母"
        chart = render_chart(layouts, key_data)
        self.assertIn("| 测试字母 | `•—` |", chart)
        self.assertIn("| 1 | `•————` |", chart)
        self.assertIn("| 1 | `•` |", chart)
        self.assertIn("| 左向Tab | `——•—••` |", chart)
        self.assertIn("| 开始菜单 | `——••••` |", chart)
        self.assertIn("| 应用菜单 | `—•••——` |", chart)

    def test_conflicting_codes_and_missing_actions_fail_generation(self):
        layouts = deepcopy(self.layouts)
        entries = layouts["layouts"]["main"]["items"]
        entries.append(dict(entries[0]))
        with self.assertRaisesRegex(ValueError, "重复编码"):
            render_chart(layouts, self.key_data)
        entries.pop()
        entries[0]["action"] = "UNDEFINED_ACTION"
        with self.assertRaisesRegex(ValueError, "未定义动作"):
            render_chart(layouts, self.key_data)

    def test_extracting_labels_never_executes_application_source(self):
        with TemporaryDirectory() as directory:
            source = Path(directory) / "app.py"
            source.write_text(
                "raise RuntimeError('must not execute')\n"
                "class ConfigManager:\n"
                "    def __init__(self):\n"
                "        self.key_data = {'A': {'label': '字母'}}\n",
                encoding="utf-8",
            )
            self.assertEqual(read_key_data(source), {"A": {"label": "字母"}})


if __name__ == "__main__":
    unittest.main()
