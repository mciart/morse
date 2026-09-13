"""Morse keyboard output with owned, sticky modifier state.

No hooks or global key-state queries are installed here. Returned text describes
the generated action; external Caps Lock changes, keyboard
layouts and input methods can still change what the receiving application sees.
"""

from __future__ import annotations


_ALIASES = {
    "control": "ctrl", "left control": "left ctrl", "right control": "right ctrl",
    "win": "windows", "cmd": "windows", "command": "windows",
    "left win": "left windows", "right win": "right windows",
    "option": "alt", "capslock": "caps lock", "return": "enter",
}
_MODIFIERS = {"shift", "ctrl", "alt", "windows"}
_SHIFTED_DIGITS = dict(zip("1234567890", "!@#$%^&*()"))
_LITERAL_KEYS = {" ": "space", "\t": "tab", "\n": "enter", "\r": "enter", "\b": "backspace"}


def _normalize(key):
    if key in _LITERAL_KEYS:
        return _LITERAL_KEYS[key]
    key = key.lower().replace("_", " ").strip()
    return _ALIASES.get(key, key)


def _modifier_family(key):
    key = _normalize(key)
    if key.startswith(("left ", "right ")):
        key = key.split(" ", 1)[1]
    return key if key in _MODIFIERS else None


class KeyboardOutput:
    def __init__(self, backend=None):
        if backend is None:
            import keyboard
            backend = keyboard
        self.backend = backend
        self._held_modifiers = {}
        self.lock_mode = False
        self._caps_lock = False

    @property
    def held_modifiers(self):
        """A snapshot of modifiers pressed by this output instance."""
        return tuple(self._held_modifiers)

    def _release_modifiers(self):
        error = None
        for key in reversed(self.held_modifiers):
            try:
                self.backend.release(key)
            except Exception as exc:
                # Keep failed releases owned so a later reset can retry them.
                if error is None:
                    error = exc
            else:
                del self._held_modifiers[key]
        if error is not None:
            raise error

    def reset(self):
        """Release only our modifiers, even if one release fails."""
        self.lock_mode = False
        self._release_modifiers()

    def toggle_lock_mode(self) -> bool:
        """Toggle modifier retention; turning it off releases held modifiers."""
        if self.lock_mode:
            self.reset()
        else:
            self.lock_mode = True
        return self.lock_mode

    def _toggle_modifier(self, key):
        key = _normalize(key)
        if _modifier_family(key) is None:
            raise ValueError(f"Not a modifier key: {key}")
        if key in self._held_modifiers:
            self.backend.release(key)
            del self._held_modifiers[key]
        else:
            # Own the attempted press so reset can also recover a partial failure.
            self._held_modifiers[key] = None
            try:
                self.backend.press(key)
            except Exception:
                self._release_modifiers()
                raise

    def _send_key(self, parts):
        held_families = {_modifier_family(key) for key in self.held_modifiers}
        # keyboard.send releases modifiers in its chord. Exclude those we already
        # hold so a locked Shift survives an explicit Shift+Tab action.
        temporary_parts = [part for part in parts
                           if _modifier_family(part) not in held_families]
        if not temporary_parts:
            return
        # A comma inside a string hotkey is a step separator in keyboard. Its
        # list form represents one chord and can safely contain a comma key.
        key = (temporary_parts if len(temporary_parts) > 1 and "," in temporary_parts
               else "+".join(temporary_parts))
        try:
            self.backend.send(key)
        except Exception:
            # keyboard.send has no finally block for a partially sent chord.
            self.backend.release(key)
            raise

    def _write_character(self, character):
        modifiers = self.held_modifiers
        # Injected modifier presses are not necessarily in keyboard's own state
        # cache. Explicitly suspend them around its Unicode text operation.
        try:
            for key in reversed(modifiers):
                self.backend.release(key)
            self.backend.write(character, exact=True)
        finally:
            for key in modifiers:
                self.backend.press(key)

    def send_pinyin(self, text):
        """Send Latin key strokes through the target IME, not Unicode text."""
        if not isinstance(text, str) or not text or any(character not in 'abcdefghijklmnopqrstuvwxyz' for character in text):
            raise ValueError('拼音输出必须是小写英文字母')
        self.reset()
        for character in text:
            self._send_key([character])
        return text

    def send(self, key, character=None, modifier=False) -> str | None:
        """Send an action, consuming one-shot modifiers after a normal key.

        Modifier actions toggle a held key. Lock mode retains them across normal
        keys, and does not repeat a previous action. Character metadata is used
        for exact punctuation output and to describe the generated character.
        """
        if modifier:
            self._toggle_modifier(key)
            return None

        try:
            parts = [_normalize(part) for part in key.split("+")]
            families = {_modifier_family(part) for part in parts}
            families.update(_modifier_family(part) for part in self.held_modifiers)
            shortcut = bool(families & {"ctrl", "alt", "windows"})
            punctuation = (isinstance(character, str) and len(character) == 1
                           and not character.isalnum() and not character.isspace()
                           and character != "\b")
            if punctuation and not shortcut:
                self._write_character(character)
                return character

            self._send_key(parts)
            if shortcut:
                return None
            if parts[-1] == "caps lock":
                self._caps_lock = not self._caps_lock
                return None
            if parts[-1] == "tab" and "shift" in families:
                return None
            if parts[-1] == "backspace":
                return "\b"
            if character is None:
                return None
            if character.isalpha():
                return character.upper() if ("shift" in families) ^ self._caps_lock else character.lower()
            if "shift" in families and character in _SHIFTED_DIGITS:
                return _SHIFTED_DIGITS[character]
            return character
        finally:
            if not self.lock_mode:
                self._release_modifiers()
