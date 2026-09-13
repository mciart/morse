"""The single international-first code table and in-memory legacy migration.

The Morsey character table was checked against commit
dc120423abd6f211548ad5f60eba2f496fa680bf, lib/morsey/morse_code.dart.
Codes are factual mappings; no Morsey implementation is imported or executed.
"""

from copy import deepcopy


MORSEY_REFERENCE_COMMIT = 'dc120423abd6f211548ad5f60eba2f496fa680bf'

# International letters, digits and punctuation plus common ! & ; _ $ codes.
# All characters except $ agree with the 53-entry Morsey reference above.
INTERNATIONAL_CHARACTER_CODES = dict(zip(
    'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789',
    ('.-', '-...', '-.-.', '-..', '.', '..-.', '--.', '....', '..', '.---',
     '-.-', '.-..', '--', '-.', '---', '.--.', '--.-', '.-.', '...', '-',
     '..-', '...-', '.--', '-..-', '-.--', '--..', '-----', '.----', '..---',
     '...--', '....-', '.....', '-....', '--...', '---..', '----.')))
INTERNATIONAL_CHARACTER_CODES.update({
    '.': '.-.-.-', ',': '--..--', '?': '..--..', "'": '.----.',
    '!': '-.-.--', '/': '-..-.', '(': '-.--.', ')': '-.--.-',
    '&': '.-...', ':': '---...', ';': '-.-.-.', '=': '-...-',
    '+': '.-.-.', '-': '-....-', '_': '..--.-', '"': '.-..-.', '@': '.--.-.', '$': '...-..-',
})

_CHARACTER_ACTIONS = dict(zip('ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'))
_CHARACTER_ACTIONS.update(dict(zip('0123456789', (
    'ZERO', 'ONE', 'TWO', 'THREE', 'FOUR', 'FIVE', 'SIX', 'SEVEN', 'EIGHT', 'NINE'))))
_CHARACTER_ACTIONS.update({
    '.': 'DOT', ',': 'COMMA', '?': 'QUESTION', "'": 'SINGLEQUOTE',
    '!': 'EXCLAMATION', '/': 'FSLASH', '(': 'OPENBRACKET', ')': 'CLOSEBRACKET',
    '&': 'AMPERSAND', ':': 'COLON', ';': 'SEMICOLON', '=': 'EQUALS',
    '+': 'PLUS', '-': 'MINUS', '_': 'UNDERSCORE', '"': 'DOUBLEQUOTE', '@': 'AT', '$': 'DOLLAR',
})
INTERNATIONAL_ACTION_CODES = {
    _CHARACTER_ACTIONS[character]: pattern.translate(str.maketrans({'.': '1', '-': '2'}))
    for character, pattern in INTERNATIONAL_CHARACTER_CODES.items()
}

# These six former codes are occupied by standard characters. Stable seven-
# element extensions start with a dot; the mouse's seven-element codes start
# with a dash. Do not accept the old codes as aliases: / must never mean Delete.
COMPUTER_EXTENSION_CODES = {
    'F9': '1122221',
    'DELETE': '1221121',
    'TAB': '1221221',
    'STAR': '1212111',
    'REPEATMODE': '1121121',
    'PERCENT': '1122121',
    'BACKTICK': '1111111',
}


def normalize_layouts(layouts, default_layout=None):
    """Return only the unified layout, without rewriting the user's JSON file.

    ``layouts`` is the inner layouts dictionary from raw JSON, never runtime
    action objects. ``default_layout`` is the bundled desktop template. It
    supplies the unified layout for pre-desktop installations and any missing
    actions in a custom desktop. Existing labels and action parameters survive.
    Retired page-switch and prediction actions never reach runtime dispatch.
    A conflicting custom code fails explicitly instead of aliasing two actions.
    """
    source = layouts.get('desktop', default_layout)
    if not isinstance(source, dict):
        raise ValueError('缺少统一码表，无法迁移旧版布局')
    desktop = deepcopy(source)
    desktop.pop('supports_prediction', None)
    desktop.pop('column_len', None)
    retired_actions = {'CHANGELAYOUT', 'CODESET', 'PREDICTION_SELECT'}
    items = [item for item in desktop.get('items', [])
             if not item.get('emptyspace') and item.get('action') not in retired_actions]
    desktop['items'] = items
    existing_actions = {item.get('action') for item in items}
    if default_layout is not None:
        for item in default_layout.get('items', []):
            action = item.get('action')
            if action not in existing_actions and action not in retired_actions and not item.get('emptyspace'):
                items.append(deepcopy(item))
                existing_actions.add(action)
    replacements = dict(INTERNATIONAL_ACTION_CODES, **COMPUTER_EXTENSION_CODES)
    if 'BACKTICK' not in existing_actions:
        items.append({'action': 'BACKTICK', 'code': COMPUTER_EXTENSION_CODES['BACKTICK']})
    seen = {}
    for item in items:
        action = item.get('action')
        if action in replacements:
            item['code'] = replacements[action]
        code = item.get('code')
        if not isinstance(code, str) or not code or set(code) - {'1', '2'}:
            raise ValueError('统一码表存在无效编码：%s（%s）' % (code, action))
        if code in seen:
            raise ValueError('国际摩斯优先码表存在重复编码：%s（%s / %s）' % (code, seen[code], action))
        seen[code] = action
    return {'desktop': desktop}
