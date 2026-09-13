"""Validate persisted preferences and replace them without truncating the original."""

from copy import deepcopy
import json
import logging
import math
import os
from pathlib import Path
import tempfile


_OBSOLETE = {'guide_layout', 'code_profile', 'SoundDit', 'SoundDah',
             'SoundTyping', 'withdebug', 'debug'}
_NUMBERS = {
    'keylen': (1, 3, int), 'wpm': (5, 60, int),
    'maxDitTime': (0, 5000, float), 'minLetterPause': (0, 60000, float),
    'fontsizescale': (10, 10000, int), 'tone_frequency': (200, 1200, int),
    'tone_volume': (0, 100, int),
    'winposx': (-10000000, 10000000, int), 'winposy': (-10000000, 10000000, int),
}
_CHOICES = {
    'theme': {'system', 'light', 'dark'},
    'keyer_mode': {'manual', 'iambic', 'straight'},
    'pinyin_layer_mode': {'hold', 'toggle'},
    'winxaxis': {'left', 'right'}, 'winyaxis': {'top', 'bottom'},
}


def _positions(value):
    result = {}
    for mode, position in value.items():
        if not isinstance(position, dict) or any(
                type(position.get(axis)) is not int or abs(position[axis]) > 10000000
                for axis in ('x', 'y')):
            continue
        cleaned = {'x': position['x'], 'y': position['y']}
        if isinstance(position.get('screen'), str):
            cleaned['screen'] = position['screen']
        available = position.get('available')
        if isinstance(available, list) and len(available) == 4 and all(
                type(part) is int and abs(part) <= 10000000 for part in available):
            cleaned['available'] = list(available)
        result[mode] = cleaned
    return result


def normalize_config(data, defaults, *, valid_keys=()):
    """Restore only invalid fields; loading never rewrites the user's file."""
    result = deepcopy(defaults)
    if not isinstance(data, dict):
        logging.warning('配置应为 JSON 对象，已使用默认设置')
        return result
    invalid = []
    for key, value in data.items():
        if key in _OBSOLETE:
            continue
        try:
            if key in _NUMBERS:
                low, high, convert = _NUMBERS[key]
                if isinstance(value, bool):
                    raise ValueError
                number = float(value)
                if (not math.isfinite(number) or not low <= number <= high or
                        (convert is int and not number.is_integer())):
                    raise ValueError
                value = convert(number)
            elif key in _CHOICES:
                if not isinstance(value, str) or value not in _CHOICES[key]:
                    raise ValueError
            elif key in ('keyone', 'keytwo', 'keythree'):
                if not isinstance(value, str):
                    raise ValueError
                value = value.strip().upper()
                if valid_keys and value not in valid_keys:
                    raise ValueError
            elif isinstance(defaults.get(key), bool) or key == 'fastMorseMode':
                if type(value) is not bool:
                    raise ValueError
            elif key == 'guide_compact_scale':
                if value is not None:
                    if isinstance(value, bool):
                        raise ValueError
                    value = float(value)
                    if not math.isfinite(value) or not 0 < value <= 10000:
                        raise ValueError
            elif key == 'guide_positions':
                if value is not None and not isinstance(value, dict):
                    raise ValueError
                if value is not None:
                    value = _positions(value)
            elif isinstance(defaults.get(key), str) and not isinstance(value, str):
                raise ValueError
            # Unknown legacy fields must not make every future save fail.
            json.dumps(value, allow_nan=False)
            result[key] = deepcopy(value)
        except (ValueError, TypeError, OverflowError):
            invalid.append(key)
    if 'keyer_mode' not in data:
        result['keyer_mode'] = 'iambic' if result.get('fastMorseMode', False) else 'manual'
    if invalid:
        logging.warning('以下配置字段无效，已分别恢复默认值：%s', ', '.join(invalid))
    return result


def read_config(path, defaults, *, valid_keys=()):
    try:
        with Path(path).open('r', encoding='utf-8-sig') as stream:
            data = json.load(stream)
    except FileNotFoundError:
        return deepcopy(defaults)
    except (OSError, UnicodeError, ValueError):
        logging.warning('无法读取配置文件，已使用默认设置：%s', path, exc_info=True)
        return deepcopy(defaults)
    return normalize_config(data, defaults, valid_keys=valid_keys)


def write_config(path, config):
    """Serialize first, flush a sibling temporary file, then atomically replace."""
    content = json.dumps(config, ensure_ascii=False, indent=4, allow_nan=False) + '\n'
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n',
                                         dir=path.parent, prefix='.' + path.name + '.',
                                         suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
