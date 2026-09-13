"""International-first character profiles, independent of Qt and user files.

The Morsey character table was checked against commit
dc120423abd6f211548ad5f60eba2f496fa680bf, lib/morsey/morse_code.dart.
Codes are factual mappings; no Morsey implementation is imported or executed.
"""

from copy import deepcopy


MORSEY_REFERENCE_COMMIT = 'dc120423abd6f211548ad5f60eba2f496fa680bf'
DEFAULT_CODE_PROFILE = 'morsey'
CODE_PROFILE_LABELS = {'morsey': '国际摩斯优先', 'legacy': '旧版专用'}

# International letters, digits and punctuation, plus Morsey's ! & ; _.
# Keep one table for runtime and generated documentation.
MORSEY_CHARACTER_CODES = dict(zip(
    'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789',
    ('.-', '-...', '-.-.', '-..', '.', '..-.', '--.', '....', '..', '.---',
     '-.-', '.-..', '--', '-.', '---', '.--.', '--.-', '.-.', '...', '-',
     '..-', '...-', '.--', '-..-', '-.--', '--..', '-----', '.----', '..---',
     '...--', '....-', '.....', '-....', '--...', '---..', '----.')))
MORSEY_CHARACTER_CODES.update({
    '.': '.-.-.-', ',': '--..--', '?': '..--..', "'": '.----.',
    '!': '-.-.--', '/': '-..-.', '(': '-.--.', ')': '-.--.-',
    '&': '.-...', ':': '---...', ';': '-.-.-.', '=': '-...-',
    '+': '.-.-.', '-': '-....-', '_': '..--.-', '"': '.-..-.', '@': '.--.-.',
})

_CHARACTER_ACTIONS = dict(zip('ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'))
_CHARACTER_ACTIONS.update(dict(zip('0123456789', (
    'ZERO', 'ONE', 'TWO', 'THREE', 'FOUR', 'FIVE', 'SIX', 'SEVEN', 'EIGHT', 'NINE'))))
_CHARACTER_ACTIONS.update({
    '.': 'DOT', ',': 'COMMA', '?': 'QUESTION', "'": 'SINGLEQUOTE',
    '!': 'EXCLAMATION', '/': 'FSLASH', '(': 'OPENBRACKET', ')': 'CLOSEBRACKET',
    '&': 'AMPERSAND', ':': 'COLON', ';': 'SEMICOLON', '=': 'EQUALS',
    '+': 'PLUS', '-': 'MINUS', '_': 'UNDERSCORE', '"': 'DOUBLEQUOTE', '@': 'AT',
})
MORSEY_ACTION_CODES = {
    _CHARACTER_ACTIONS[character]: pattern.translate(str.maketrans({'.': '1', '-': '2'}))
    for character, pattern in MORSEY_CHARACTER_CODES.items()
}

# ITU-R M.1677-1 takes priority for defined printable characters. The user's
# punctuation chart also includes the common dollar/SX extension, which Morsey
# omits. Keep it explicitly separate from the 53-entry Morsey reference.
INTERNATIONAL_CHARACTER_CODES = dict(MORSEY_CHARACTER_CODES, **{'$': '...-..-'})
INTERNATIONAL_ACTION_CODES = dict(MORSEY_ACTION_CODES, DOLLAR='1112112')

# These six former codes are occupied by standard characters. Stable seven-
# element extensions start with a dot; the mouse's seven-element codes start
# with a dash. Do not accept the old codes as aliases: / must never mean Delete.
MORSEY_EXTENSION_CODES = {
    'F9': '1122221',
    'DELETE': '1221121',
    'TAB': '1221221',
    'STAR': '1212111',
    'REPEATMODE': '1121121',
    'PERCENT': '1122121',
}
COMPUTER_EXTRA_CODES = {'BACKTICK': '1111111'}


def normalize_code_profile(value):
    """Unknown or missing preferences use the current default."""
    return 'legacy' if value == 'legacy' else DEFAULT_CODE_PROFILE


def apply_code_profile(layouts, profile=DEFAULT_CODE_PROFILE):
    """Return fresh JSON layouts; change only the unified desktop page.

    Pass raw JSON, never runtime action objects. Legacy pages and the caller's
    data remain intact. A custom action occupying a reserved code is rejected
    explicitly, rather than silently assigning one input to two actions.
    """
    result = deepcopy(layouts)
    if normalize_code_profile(profile) == 'legacy' or 'desktop' not in result:
        return result
    replacements = dict(INTERNATIONAL_ACTION_CODES, **MORSEY_EXTENSION_CODES, **COMPUTER_EXTRA_CODES)
    items = result['desktop'].setdefault('items', [])
    existing_actions = {item.get('action') for item in items}
    for action, code in COMPUTER_EXTRA_CODES.items():
        if action not in existing_actions:
            items.append({'action': action, 'code': code})
    seen = {}
    for item in items:
        if item.get('emptyspace'):
            continue
        action = item.get('action')
        if action in replacements:
            item['code'] = replacements[action]
        code = item.get('code')
        if code in seen:
            raise ValueError('国际摩斯优先码表存在重复编码：%s（%s / %s）' % (code, seen[code], action))
        seen[code] = action
    return result
