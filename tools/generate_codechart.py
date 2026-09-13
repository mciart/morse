"""Generate the Chinese code chart from runtime layouts and action labels.

Only the standard library is used. Reading key_data through AST avoids importing
the GUI, registering keyboard hooks, or requiring the application's dependencies.
"""

import argparse
import ast
import html
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from morse_profiles import normalize_layouts, MORSEY_REFERENCE_COMMIT


def read_key_data(source_path):
    tree = ast.parse(Path(source_path).read_text(encoding="utf-8-sig"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "ConfigManager":
            for method in node.body:
                if isinstance(method, ast.FunctionDef) and method.name == "__init__":
                    for statement in ast.walk(method):
                        if not isinstance(statement, ast.Assign):
                            continue
                        for target in statement.targets:
                            if (isinstance(target, ast.Attribute)
                                    and isinstance(target.value, ast.Name)
                                    and target.value.id == "self"
                                    and target.attr == "key_data"):
                                return ast.literal_eval(statement.value)
    raise ValueError("未找到 ConfigManager.key_data 字典")


def markdown_text(value):
    text = html.escape(str(value), quote=False)
    for character in ("\\", "`", "*", "_", "|", "[", "]"):
        text = text.replace(character, "\\" + character)
    return text.replace("\n", "<br>")


def render_chart(layout_data, key_data):
    desktop = normalize_layouts(layout_data["layouts"])['desktop']
    entries = desktop['items']

    lines = [
        "# 摩斯输入完整码表",
        "",
        "<!-- 由 tools/generate_codechart.py 自动生成，请勿手动修改表格。 -->",
        "",
        "编码来自 [软件编码方案](morse_profiles.py) 与 [原始码表配置](user_data/layouts.json)，动作名称来自 "
        "[软件动作定义](MorseCodeGUI.py)。此表与软件使用同一个转换函数。",
        "",
        "`•` 表示点，`—` 表示划。统一码表采用国际摩斯优先规则：已有国际定义的字符优先采用 "
        "[ITU-R M.1677-1](https://www.itu.int/dms_pubrec/itu-r/rec/m/R-REC-M.1677-1-200910-I!!PDF-E.pdf)"
        "的编码，常见标点扩展采用通用约定。包含 A–Z、0–9 和 18 个标点，其中 53 个字符与 "
        f"[Morsey 的实际编码表](https://github.com/dj-on-github/morsey/blob/{MORSEY_REFERENCE_COMMIT}/lib/morsey/morse_code.dart#L7)"
        "一致，并补齐该表没有的美元符号 `$`（`•••—••—`）。参考版本固定，不会随对方项目更新而自动改变。"
        "`!`、`&`、`;`、`_`、`$` 属于常见字符扩展，不冒充 ITU 正式定义；"
        "18 个标点与[中文维基百科的标点表](https://zh.wikipedia.org/zh-cn/摩尔斯电码#标点符号)一致。",
        "",
        "反引号（`）在参考表中没有标准编码，本软件补充为七个点 `•••••••`，显示在美式键盘数字行最左侧。"
        "它属于软件扩展。",
        "",
        "键盘与鼠标统一面板按实体设备的位置排列。"
        "F9、Delete、Tab、星号、百分号和修饰键锁定使用以点开头的独立七位码，避开标准标点；"
        "鼠标保留以划开头的七位码，无需切页。鼠标区默认关闭，可在设置或码表中开启。",
        "",
        "回车、空格、导航键、功能键和鼠标操作是软件扩展，并非 Morsey 的字符表；"
        "暂停不会自动输入空格。升级时会在内存中把原有码表转换为统一编码，保留用户文件，"
        "旧版分页、切页动作和词语候选不再启用。",
        "",
        "组合键：先输入 Ctrl，再输入 V，即执行一次 Ctrl+V，随后自动释放 Ctrl。"
        "需要连续组合键时，先开启“修饰键锁定”，再输入 Ctrl 和 V；"
        "再次输入“修饰键锁定”会关闭锁定并释放修饰键。该开关不自动重复上一个动作。",
        "",
    ]

    lines.extend([
        f"## {desktop.get('display_name', '键盘与鼠标')}",
        "",
        f"共 {len(entries)} 项，均可直接输入。",
        "",
        "| 按键或操作 | 摩斯码 |",
        "| --- | --- |",
    ])
    for item in entries:
        action = item['action']
        if action not in key_data:
            raise ValueError(f"统一码表存在未定义动作：{action}")
        label = item.get('label', key_data[action]['label'])
        morse = item['code'].translate(str.maketrans({'1': '•', '2': '—'}))
        lines.append(f"| {markdown_text(label)} | `{morse}` |")
    lines.append("")

    lines.extend([
        "## 维护与校验",
        "",
        "修改软件编码或动作名称后，运行 `python tools/generate_codechart.py` 更新本文件。"
        "运行 `python tools/generate_codechart.py --check` 可检查文档是否与软件一致。",
        "",
    ])
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="根据软件配置生成中文摩斯码表")
    parser.add_argument("--check", action="store_true", help="检查文档是否最新，不写入文件")
    args = parser.parse_args(argv)
    output = PROJECT_ROOT / "codechart.md"
    try:
        layouts = json.loads((PROJECT_ROOT / "user_data" / "layouts.json").read_text(encoding="utf-8-sig"))
        expected = render_chart(layouts, read_key_data(PROJECT_ROOT / "MorseCodeGUI.py"))
        if args.check:
            if not output.exists() or output.read_text(encoding="utf-8") != expected:
                print("码表文档与软件不一致，请运行 python tools/generate_codechart.py", file=sys.stderr)
                return 1
            print("码表文档与软件一致。")
        else:
            output.write_text(expected, encoding="utf-8", newline="\n")
            print(f"已更新 {output.name}")
    except (OSError, ValueError, KeyError, SyntaxError) as error:
        print(f"码表生成失败：{error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
