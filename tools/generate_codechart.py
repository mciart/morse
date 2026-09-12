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
    layouts = layout_data["layouts"]
    default_layout = layout_data["mainlayout"]
    if default_layout not in layouts:
        raise ValueError("默认码表不存在")

    # Page names also come from the runtime layout navigation labels.
    page_names = {}
    for layout in layouts.values():
        for item in layout["items"]:
            if item.get("action") == "CHANGELAYOUT":
                if item["target"] not in layouts:
                    raise ValueError(f"切换目标码表不存在：{item['target']}")
                page_names[item["target"]] = item["label"]

    lines = [
        "# 摩斯输入完整码表",
        "",
        "<!-- 由 tools/generate_codechart.py 自动生成，请勿手动修改表格。 -->",
        "",
        "编码和页面来自 [软件码表配置](user_data/layouts.json)，动作名称来自 "
        "[软件动作定义](MorseCodeGUI.py)。此表包含所有页面的可用编码。",
        "",
        "`•` 表示点，`—` 表示划。编码按当前页面解释；切换页面后，同一编码可能执行不同动作。"
        "标点和控制键使用本软件约定的编码。",
        "",
        f"默认显示“{page_names.get(default_layout, default_layout)}”完整页面。"
        "可在码表窗口的页面选择器中切页，也可输入各页列出的切换编码。"
        "字母页的候选项会根据输入动态更新，仅有候选词时可用。"
        "缩写仅在字母页输入空格完成单词后展开；主键盘和数字页保持原字符输出。",
        "",
        "组合键：先输入 Ctrl，再输入 V，即执行一次 Ctrl+V，随后自动释放 Ctrl。"
        "需要连续组合键时，先开启“修饰键锁定”，再输入 Ctrl 和 V；"
        "再次输入“修饰键锁定”会关闭锁定并释放修饰键。该开关不自动重复上一个动作。",
        "",
    ]

    page_order = [default_layout] + [name for name in layouts if name != default_layout]
    for page in page_order:
        entries = [item for item in layouts[page]["items"] if not item.get("emptyspace")]
        page_name = page_names.get(page, page)
        lines.extend([
            f"## {page_name}{'（默认）' if page == default_layout else ''}",
            "",
            f"本页共 {len(entries)} 项。以下编码仅在“{page_name}”页生效。",
            "",
            "| 按键或操作 | 摩斯码 |",
            "| --- | --- |",
        ])
        seen_codes = set()
        for item in entries:
            code = item["code"]
            if not code or set(code) - {"1", "2"}:
                raise ValueError(f"{page} 页存在无效编码：{code}")
            if code in seen_codes:
                raise ValueError(f"{page} 页存在重复编码：{code}")
            seen_codes.add(code)
            action = item["action"]
            if action == "CHANGELAYOUT":
                label = f"切换至{page_names[item['target']]}页"
            elif action == "PREDICTION_SELECT":
                label = f"候选{item['target'] + 1}"
            else:
                if action not in key_data:
                    raise ValueError(f"{page} 页存在未定义动作：{action}")
                label = item.get("label", key_data[action]["label"])
            morse = code.translate(str.maketrans({"1": "•", "2": "—"}))
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
