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
from pinyin_codes import build_pinyin_layout


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


def read_guide_display_names(source_path):
    """Read actual US keycap names without importing Qt or constructing UI."""
    tree = ast.parse(Path(source_path).read_text(encoding="utf-8-sig"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "VirtualKeyboardView":
            for statement in node.body:
                if isinstance(statement, ast.Assign) and any(
                        isinstance(target, ast.Name) and target.id == "DISPLAY_NAMES"
                        for target in statement.targets):
                    return ast.literal_eval(statement.value)
    raise ValueError("未找到 VirtualKeyboardView.DISPLAY_NAMES 字典")


def render_chart(layout_data, key_data):
    desktop = normalize_layouts(layout_data["layouts"])['desktop']
    entries = desktop['items']

    lines = [
        "# 摩斯输入完整码表",
        "",
        "<!-- 由 tools/generate_codechart.py 自动生成，请勿手动修改表格。 -->",
        "",
        "启用拼音层输入时，请使用[拼音层码表](docs/pinyin-code-chart.md)。",
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


def render_pinyin_chart(layout_data, key_data, display_names):
    """Render all temporary-layer items from the same builder as the app."""
    english = normalize_layouts(layout_data['layouts'])['desktop']
    items = build_pinyin_layout(english)['items']
    if len({item['code'] for item in items}) != len(items):
        raise ValueError('拼音码表存在重复编码')
    if len({item['action'] for item in items}) != len(items):
        raise ValueError('拼音码表存在重复动作')
    lines = [
        '# 拼音层完整码表',
        '',
        '<!-- 由 tools/generate_codechart.py 自动生成，请勿手动修改表格。 -->',
        '',
        '本表直接由软件使用的 [build_pinyin_layout](../pinyin_codes.py) 生成。'
        '37 个注音符号使用[国音电码的注音编码](https://zh.wikipedia.org/zh-cn/摩尔斯电码#中文注音)，'
        '键帽显示对应的拼音拼写；新增拼写及编辑操作明确标为软件扩展。',
        '',
        '启用拼音层时使用本表，未启用时使用[英文键盘码表](../codechart.md)。'
        '默认采用“按住”方式：按住码表快捷键进入拼音层，松开恢复英文。'
        '也可在设置中选择“单击切换”：单击切换中英文层，松开后保留当前层；'
        '双击只显示或隐藏码表，不改变已选择的层。'
        '当前电码以第一个点划确定所属层，切换层不会改变尚未确认电码的解释。'
        '软件输入拼音字母，由当前系统拼音输入法选字；不会自动切换系统输入法或改写之前输入的文字。',
        '',
        '`•` 表示点，`—` 表示划。左侧是声母，右侧是韵母；底部保留数字、选字与编辑操作。'
        '鼠标区沿用英文层的 31 个动作及编码，可单独开启，默认隐藏。',
        '',
        '拼音按输入法键盘约定输出：`ü` 输入 `v`，`üe` 输入 `ve`，`ê` 输入 `e`。'
        '这里不会直接输入 `ü` 或 `ê` 字符。`jue / que / xue / yue` 使用 `ue`，'
        '`lüe / nüe` 使用 `üe`（输出 `ve`）。',
        '',
        '复合韵母一次输出完整拼写，例如 `ing`、`uang`、`iu`、`ui`、`un`；'
        '不要把 `i` 和 `eng` 拼成 `ieng`。`y / w` 是补充的拼写字母，供零声母拼写使用：'
        '`y + ing → ying`、`w + u → wu`。其它例子：`zh + ang → zhang`、'
        '`j + uan → juan`、`l + üe → lve`。这些是直接输出的拼音片段，不做自动音节改写。',
        '',
        '部分编辑键的英文码与注音原码重叠，因此 Space、Enter、Esc、End、Insert '
        '在拼音层使用独立扩展码。更改只在拼音层生效，英文层仍保留原码；'
        '数字及未冲突的编辑键继续沿用英文码。',
        '',
        f'共 {len(items)} 项，各项编码唯一。',
        '',
    ]
    for group, title in (('initial', '声母与拼写字母（左侧）'),
                         ('final', '韵母（右侧）'),
                         ('control', '数字、选字与编辑'), ('mouse', '鼠标（可选）')):
        grouped = [item for item in items if item['pinyin_group'] == group]
        lines.extend([
            f'## {title}', '', f'共 {len(grouped)} 项。', '',
            '| 键帽或操作 | 实际输入或动作 | 摩斯码 | 编码来源 |',
            '| --- | --- | --- | --- |',
        ])
        for item in grouped:
            action = item['action']
            if 'pinyin_text' in item:
                label = item['label']
                output = item['pinyin_text']
                origin = '注音原码：' + item['zhuyin'] if 'zhuyin' in item else '软件扩展'
            else:
                if action not in key_data:
                    raise ValueError(f'拼音码表存在未定义动作：{action}')
                definition = key_data[action]
                label = display_names.get(action, item.get('label', definition['label']))
                character = definition.get('character')
                if character is not None and character.isdigit():
                    output = character
                    origin = '国际数字码（沿用英文层）'
                else:
                    output = '执行：' + str(definition['label'])
                    origin = ('软件扩展（拼音层重分配）' if item.get('extension') else
                              '软件操作码（沿用英文层）')
            code = item['code'].translate(str.maketrans({'1': '•', '2': '—'}))
            lines.append(f'| {markdown_text(label)} | {markdown_text(output)} | `{code}` | {origin} |')
        lines.append('')
    lines.extend([
        '## 维护与校验', '',
        '运行 `python tools/generate_codechart.py` 同时更新英文与拼音码表。'
        '运行 `python tools/generate_codechart.py --check` 会检查两份文档是否与软件一致，'
        '任何一份缺失或过期都会返回失败。', '',
    ])
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="根据软件配置生成中文摩斯码表")
    parser.add_argument("--check", action="store_true", help="检查文档是否最新，不写入文件")
    args = parser.parse_args(argv)
    try:
        layouts = json.loads((PROJECT_ROOT / "user_data" / "layouts.json").read_text(encoding="utf-8-sig"))
        key_data = read_key_data(PROJECT_ROOT / "MorseCodeGUI.py")
        display_names = read_guide_display_names(PROJECT_ROOT / "virtual_keyboard.py")
        outputs = {
            PROJECT_ROOT / 'codechart.md': render_chart(layouts, key_data),
            PROJECT_ROOT / 'docs' / 'pinyin-code-chart.md': render_pinyin_chart(layouts, key_data, display_names),
        }
        if args.check:
            outdated = [str(output.relative_to(PROJECT_ROOT)) for output, expected in outputs.items()
                        if not output.exists() or output.read_text(encoding='utf-8') != expected]
            if outdated:
                print("码表文档与软件不一致：%s。请运行 python tools/generate_codechart.py" %
                      '、'.join(outdated), file=sys.stderr)
                return 1
            print("英文与拼音码表文档均与软件一致。")
        else:
            for output, expected in outputs.items():
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(expected, encoding="utf-8", newline="\n")
                print(f"已更新 {output.relative_to(PROJECT_ROOT)}")
    except (OSError, ValueError, KeyError, SyntaxError) as error:
        print(f"码表生成失败：{error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
