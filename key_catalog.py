"""Action labels and output mapping for the unified Morse guide.

This module is stdlib-only so the code-chart generator can load labels without
importing the Qt GUI or installing keyboard hooks.
"""


def _entry(label, key_code=None, character=None, arg=None, toggle=False):
    data = {'label': label, 'key_code': key_code, 'character': character, 'arg': arg}
    if toggle:
        data['toggle_action'] = True
    return data


def build_key_data():
    data = {}
    for letter in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ':
        lower = letter.lower()
        data[letter] = _entry(lower, lower, lower)
    for name, digit in zip(
            'ONE TWO THREE FOUR FIVE SIX SEVEN EIGHT NINE ZERO'.split(),
            '1234567890'):
        data[name] = _entry(digit, digit, digit)
    for name, label, key_code, character in (
        ('BACKTICK', '`', '`', '`'),
        ('DOT', '.', '.', '.'),
        ('COMMA', ',', ',', ','),
        ('QUESTION', '?', 'shift+/', '?'),
        ('EXCLAMATION', '!', 'shift+1', '!'),
        ('COLON', ':', 'shift+;', ':'),
        ('SEMICOLON', ';', ';', ';'),
        ('AT', '@', 'shift+2', '@'),
        ('HASH', '#', 'shift+3', '#'),
        ('DOLLAR', '$', 'shift+4', '$'),
        ('PERCENT', '%', 'shift+5', '%'),
        ('AMPERSAND', '&', 'shift+7', '&'),
        ('STAR', '*', 'shift+8', '*'),
        ('PLUS', '+', 'shift+=', '+'),
        ('MINUS', '-', '-', '-'),
        ('EQUALS', '=', '=', '='),
        ('FSLASH', '/', '/', '/'),
        ('BSLASH', '\\', '\\', '\\'),
        ('SINGLEQUOTE', "'", "'", "'"),
        ('DOUBLEQUOTE', '"', "shift+'", '"'),
        ('OPENBRACKET', '(', 'shift+9', '('),
        ('CLOSEBRACKET', ')', 'shift+0', ')'),
        ('LESSTHAN', '<', 'shift+,', '<'),
        ('MORETHAN', '>', 'shift+.', '>'),
        ('CIRCONFLEX', '^', 'shift+6', '^'),
        ('ENTER', '回车', 'enter', '\n'),
        ('SPACE', '空格', 'space', ' '),
        ('BACKSPACE', '退格', 'backspace', '\x08'),
        ('TAB', 'tab', 'tab', '\t'),
        ('TABLEFT', '左向Tab', 'shift+tab', None),
        ('UNDERSCORE', '_', 'shift+-', '_'),
        ('PAGEUP', '上一页', 'page_up', None),
        ('PAGEDOWN', '下一页', 'page_down', None),
        ('LEFTARROW', '左', 'left', None),
        ('RIGHTARROW', '右', 'right', None),
        ('UPARROW', '上', 'up', None),
        ('DOWNARROW', '下', 'down', None),
        ('ESCAPE', 'esc', 'esc', None),
        ('HOME', '行首', 'home', None),
        ('END', '行尾', 'end', None),
        ('DELETE', '删除', 'delete', None),
        ('INSERT', '插入', 'insert', None),
        ('STARTMENU', '开始菜单', 'windows', None),
        ('APPLICATION', '应用菜单', 'menu', None),
        ('CAPSLOCK', '大写锁定', 'caps lock', None),
    ):
        data[name] = _entry(label, key_code, character)
    for name, label, key_code in (
        ('SHIFT', 'shift', 'shift'),
        ('RSHIFT', '右Shift', 'right shift'),
        ('LSHIFT', '左Shift', 'left shift'),
        ('CTRL', 'ctrl', 'ctrl'),
        ('RCTRL', '右Ctrl', 'right ctrl'),
        ('LCTRL', '左Ctrl', 'left ctrl'),
        ('ALT', 'alt', 'alt'),
        ('WINDOWS', 'win', 'windows'),
    ):
        data[name] = _entry(label, key_code, toggle=True)
    for number in range(1, 13):
        name = 'F%d' % number
        data[name] = _entry(name, name.lower())
    data['REPEATMODE'] = _entry('修饰键锁定', 'REPEATMODE', arg=0)
    data['SOUND'] = _entry('提示音', 'unknown', arg=8)
    for name, label, arg in (
        ('MOUSERIGHT5', '右移5', 2),
        ('MOUSEUP5', '上移5', 3),
        ('MOUSECLICKLEFT', '左键单击', 4),
        ('MOUSEDBLCLICKLEFT', '左键双击', 5),
        ('MOUSECLKHLDLEFT', '按住左键', 6),
        ('MOUSEUPLEFT5', '左上5', 7),
        ('MOUSEDOWNLEFT5', '左下5', 8),
        ('MOUSERELEASEHOLD', '松开鼠标', 9),
        ('MOUSELEFT5', '左移5', 0),
        ('MOUSEDOWN5', '下移5', 1),
        ('MOUSECLICKRIGHT', '右键单击', 2),
        ('MOUSEDBLCLICKRIGHT', '右键双击', 3),
        ('MOUSECLKHLDRIGHT', '按住右键', 4),
        ('MOUSEUPRIGHT5', '右上5', 5),
        ('MOUSEDOWNRIGHT5', '右下5', 6),
        ('MOUSENORMALMODE', '普通模式', 7),
        ('MOUSEUP40', '上移40', 8),
        ('MOUSEUP250', '上移250', 9),
        ('MOUSEDOWN40', '下移40', 0),
        ('MOUSEDOWN250', '下移250', 1),
        ('MOUSELEFT40', '左移40', 2),
        ('MOUSELEFT250', '左移250', 3),
        ('MOUSERIGHT40', '右移40', 4),
        ('MOUSERIGHT250', '右移250', 5),
        ('MOUSEUPLEFT40', '左上40', 6),
        ('MOUSEUPLEFT250', '左上250', 7),
        ('MOUSEDOWNLEFT40', '左下40', 8),
        ('MOUSEDOWNLEFT250', '左下250', 9),
        ('MOUSEUPRIGHT40', '右上40', 0),
        ('MOUSEUPRIGHT250', '右上250', 1),
        ('MOUSEDOWNRIGHT40', '右下40', 2),
        ('MOUSEDOWNRIGHT250', '右下250', 3),
    ):
        key_code = 'NORMALMODE' if name == 'MOUSENORMALMODE' else name
        data[name] = _entry(label, key_code, arg=arg)
    return data


KEY_DATA = build_key_data()
