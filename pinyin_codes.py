"""An explicit Pinyin typing layer built from the 37 Zhuyin Morse codes.

The historical codes identify Zhuyin symbols, not Latin letters. This layer
types Pinyin keyboard spelling into the current input method; it does not
convert existing text, compose Chinese characters, or edit an IME preedit.
Complete compound finals avoid incorrect concatenations such as i + eng.
"""

from copy import deepcopy
from itertools import product


# (Zhuyin, keycap, ASCII input-method keys, dot/dash code). The two lists
# preserve Zhuyin order and are deliberately independent of the English table.
ZHUYIN_INITIALS = (
    ('ㄅ', 'b', 'b', '-...'), ('ㄆ', 'p', 'p', '.--..'),
    ('ㄇ', 'm', 'm', '.--.'), ('ㄈ', 'f', 'f', '..-.-'),
    ('ㄉ', 'd', 'd', '.--'), ('ㄊ', 't', 't', '--.-'),
    ('ㄋ', 'n', 'n', '---.'), ('ㄌ', 'l', 'l', '...'),
    ('ㄍ', 'g', 'g', '-..-'), ('ㄎ', 'k', 'k', '--..-'),
    ('ㄏ', 'h', 'h', '..--'), ('ㄐ', 'j', 'j', '-..'),
    ('ㄑ', 'q', 'q', '.-..-'), ('ㄒ', 'x', 'x', '..--.'),
    ('ㄓ', 'zh', 'zh', '....'), ('ㄔ', 'ch', 'ch', '-.-.'),
    ('ㄕ', 'sh', 'sh', '.-.'), ('ㄖ', 'r', 'r', '.---'),
    ('ㄗ', 'z', 'z', '...-'), ('ㄘ', 'c', 'c', '-.-..'),
    ('ㄙ', 's', 's', '-.-'),
)
ZHUYIN_FINALS = (
    ('ㄧ', 'i', 'i', '.'), ('ㄨ', 'u', 'u', '-'),
    ('ㄩ', 'ü', 'v', '..-'), ('ㄚ', 'a', 'a', '---'),
    ('ㄛ', 'o', 'o', '--'), ('ㄜ', 'e', 'e', '-.--'),
    ('ㄝ', 'ê', 'e', '--..'), ('ㄞ', 'ai', 'ai', '.-.-'),
    ('ㄟ', 'ei', 'ei', '..-..'), ('ㄠ', 'ao', 'ao', '.-..'),
    ('ㄡ', 'ou', 'ou', '..-.'), ('ㄢ', 'an', 'an', '.-'),
    ('ㄣ', 'en', 'en', '-.'), ('ㄤ', 'ang', 'ang', '--.'),
    ('ㄥ', 'eng', 'eng', '..'), ('ㄦ', 'er', 'er', '.---.'),
)

# Software extensions, NOT historical Zhuyin or international Morse codes.
# Codes are fixed rather than allocated from whatever the current chart omits.
# Five-element space/enter take priority; remaining common spellings use five
# or six elements. None overlap the original 37 codes or the default mouse.
PINYIN_EXTENSION_CODES = {
    'Y': '12121', 'W': '12122',
    'IA': '12212', 'IE': '21112', 'IAO': '21121', 'IU': '21122',
    'IAN': '21212', 'IN': '21221', 'ING': '21222', 'UA': '22121',
    'UO': '22122', 'ONG': '22212', 'IANG': '111111', 'IONG': '111112',
    'UAI': '111122', 'UI': '111211', 'UAN': '111212', 'UN': '111221',
    'UANG': '111222', 'UE': '112111', 'VE': '112112',
}
CONTROL_EXTENSION_CODES = {
    'SPACE': '11121', 'ENTER': '12111', 'ESCAPE': '112121',
    'END': '112122', 'INSERT': '112211',
}
COMPOUND_FINALS = (
    'ia', 'ie', 'iao', 'iu', 'ian', 'in', 'iang', 'ing', 'iong',
    'ua', 'uo', 'uai', 'ui', 'uan', 'un', 'uang', 'ong', 'ue', 've',
)
CONTROL_ACTIONS = (
    'ONE', 'TWO', 'THREE', 'FOUR', 'FIVE', 'SIX', 'SEVEN', 'EIGHT', 'NINE', 'ZERO',
    'SPACE', 'BACKSPACE', 'ENTER', 'ESCAPE', 'TAB', 'TABLEFT',
    'LEFTARROW', 'RIGHTARROW', 'UPARROW', 'DOWNARROW',
    'PAGEUP', 'PAGEDOWN', 'HOME', 'END', 'INSERT', 'DELETE', 'SOUND',
)
# The same 26 printable symbols as the English keyboard, in reading order.
# Seven collide with existing Pinyin/control codes. Keep those established
# codes and give only the symbols fixed seven-element software extensions.
SYMBOL_ACTIONS = (
    'DOT', 'COMMA', 'QUESTION', 'EXCLAMATION', 'COLON', 'SEMICOLON',
    'SINGLEQUOTE', 'DOUBLEQUOTE', 'OPENBRACKET', 'CLOSEBRACKET',
    'FSLASH', 'BSLASH', 'BACKTICK',
    'AT', 'HASH', 'DOLLAR', 'PERCENT', 'AMPERSAND', 'STAR', 'PLUS',
    'MINUS', 'EQUALS', 'UNDERSCORE', 'LESSTHAN', 'MORETHAN', 'CIRCONFLEX',
)
SYMBOL_CHARACTERS = {
    'DOT': '.', 'COMMA': ',', 'QUESTION': '?', 'EXCLAMATION': '!',
    'COLON': ':', 'SEMICOLON': ';', 'SINGLEQUOTE': "'", 'DOUBLEQUOTE': '"',
    'OPENBRACKET': '(', 'CLOSEBRACKET': ')', 'FSLASH': '/', 'BSLASH': '\\',
    'BACKTICK': '`', 'AT': '@', 'HASH': '#', 'DOLLAR': '$', 'PERCENT': '%',
    'AMPERSAND': '&', 'STAR': '*', 'PLUS': '+', 'MINUS': '-', 'EQUALS': '=',
    'UNDERSCORE': '_', 'LESSTHAN': '<', 'MORETHAN': '>', 'CIRCONFLEX': '^',
}
SYMBOL_EXTENSION_CODES = {
    'QUESTION': '1111112', 'HASH': '1111121', 'AMPERSAND': '1111122',
    'PLUS': '1111211', 'EQUALS': '1111212', 'FSLASH': '1111221',
    'OPENBRACKET': '1111222',
}


def _binary(pattern):
    return pattern.translate(str.maketrans({'.': '1', '-': '2'}))


def _pinyin_item(zhuyin, label, text, code, group, extension=False):
    suffix = 'E_CIRCUMFLEX' if label == 'ê' else text.upper()
    tooltip = '%s → %s' % (zhuyin, label) if zhuyin else '软件扩展码：%s' % label
    if label in ('ü', 'üe'):
        tooltip += '；输入法按键约定：输入 %s（ü 使用 v）' % text
    elif label == 'ê':
        tooltip += '；输入法按键约定：输入 e，不直接输出 ê 字符'
    elif text == 'ue':
        tooltip += '；用于 jue / que / xue / yue；lüe / nüe 使用 üe（ve）'
    elif text in ('y', 'w'):
        tooltip += '；拼音拼写字母，例如 yi / wu'
    item = {'action': 'PINYIN_' + suffix, 'label': label, 'code': code,
            'pinyin_text': text, 'pinyin_group': group, 'tooltip': tooltip}
    if zhuyin:
        item['zhuyin'] = zhuyin
    if extension:
        item['extension'] = True
    return item


def _copy_action_item(item):
    # Runtime action objects own input backends and must retain their identity.
    return {key: value if key == '_action' else deepcopy(value)
            for key, value in item.items()}


def _valid_code(item):
    code = item.get('code')
    if not isinstance(code, str) or not code or set(code) - {'1', '2'}:
        raise ValueError('拼音层继承了无效编码：%s' % item.get('action'))
    return code


def _unused_extension(reserved, length=5):
    # Only custom remaps need this fallback. Fixed shipped mappings
    # never depend on table ordering or this allocator.
    while True:
        for symbols in product('12', repeat=length):
            code = ''.join(symbols)
            if code not in reserved:
                return code
        length += 1


def build_pinyin_layout(english_layout):
    """Return a new, collision-free Pinyin guide and reuse bound OS actions.

    Only Pinyin fragments have ``pinyin_text`` and ``PINYIN_*`` action names.
    The original control/symbol/mouse names and their ``_action`` objects
    survive, so selection, editing, punctuation and optional mouse actions work.
    The caller binds the new fragment actions to ASCII keyboard output.
    No source item or source runtime action is modified.
    """
    items = []
    for group, table in (('initial', ZHUYIN_INITIALS), ('final', ZHUYIN_FINALS)):
        for zhuyin, label, text, pattern in table:
            items.append(_pinyin_item(zhuyin, label, text, _binary(pattern), group))
        extras = ('y', 'w') if group == 'initial' else COMPOUND_FINALS
        for text in extras:
            label = 'üe' if text == 've' else text
            items.append(_pinyin_item(None, label, text,
                PINYIN_EXTENSION_CODES[text.upper()], group, extension=True))

    source_items = english_layout.get('items', [])
    controls = {}
    symbols = {}
    mice = []
    included_actions = set()
    for source in source_items:
        action = source.get('action', '')
        if (action not in CONTROL_ACTIONS and action not in SYMBOL_ACTIONS
                and not action.startswith('MOUSE')):
            continue
        if action in included_actions:
            raise ValueError('拼音层继承了重复动作：%s' % action)
        included_actions.add(action)
        _valid_code(source)
        if action.startswith('MOUSE'):
            mice.append(_copy_action_item(source))
        elif action in CONTROL_ACTIONS:
            controls[action] = _copy_action_item(source)
        else:
            symbols[action] = _copy_action_item(source)

    occupied = {item['code'] for item in items}
    for item in mice:
        code = item['code']
        if code in occupied:
            raise ValueError('拼音层鼠标编码冲突：%s' % item['action'])
        occupied.add(code)
        item['pinyin_group'] = 'mouse'

    # Keep custom unoccupied control codes wherever possible. Reserve all
    # existing controls in advance so a relocated key cannot steal a later one.
    reserved = occupied | {item['code'] for item in controls.values()}
    reserved.update(CONTROL_EXTENSION_CODES.values())
    for action in CONTROL_ACTIONS:
        if action not in controls:
            continue
        item = controls[action]
        original_code = item['code']
        if original_code in occupied:
            replacement = CONTROL_EXTENSION_CODES.get(action)
            if replacement is None or replacement in occupied or any(
                    other['action'] != action and other['code'] == replacement
                    for other in controls.values()):
                replacement = _unused_extension(reserved)
            item['code'] = replacement
            item['extension'] = True
            item['tooltip'] = '拼音层专用软件扩展码；英文层编码保持不变'
        item['pinyin_group'] = 'control'
        occupied.add(item['code'])
        reserved.add(item['code'])
        items.append(item)
    # Symbols have lower priority than all established Pinyin, control and
    # mouse codes. Reserve free original codes before allocating conflicts so
    # custom layouts and reordered source tables yield the same mappings.
    reserved = occupied | {item['code'] for item in symbols.values()}
    reserved.update(SYMBOL_EXTENSION_CODES.values())
    symbol_items = []
    for action in SYMBOL_ACTIONS:
        if action not in symbols:
            continue
        item = symbols[action]
        if item['code'] in occupied:
            replacement = SYMBOL_EXTENSION_CODES.get(action)
            if replacement is None or replacement in occupied or any(
                    other['action'] != action and other['code'] == replacement
                    for other in symbols.values()):
                replacement = _unused_extension(reserved, length=7)
            item['code'] = replacement
            item['extension'] = True
        hint = ('拼音层专用软件扩展码；英文层编码保持不变；'
                if item.get('extension') else '')
        item['tooltip'] = hint + '输入键盘符号；中文标点由当前输入法的标点模式决定'
        item['pinyin_group'] = 'symbol'
        item['pinyin_symbol'] = SYMBOL_CHARACTERS[action]
        occupied.add(item['code'])
        reserved.add(item['code'])
        symbol_items.append(item)
    # Keep reading order identical to the board and generated documentation.
    control_index = next((index for index, item in enumerate(items)
                          if item['pinyin_group'] == 'control'), len(items))
    items[control_index:control_index] = symbol_items
    items.extend(mice)
    return {'display_name': '拼音 · 声母与韵母', 'items': items}
