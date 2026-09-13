"""One owned function-key hook and a deterministic hold / double-tap gesture.

The hook only queues timestamped edges. The GUI merges them with Morse input
before feeding HoldTapGesture, so Qt signal delivery cannot change their order.
"""

from collections import deque
from dataclasses import dataclass
import logging
import platform
import re
import threading
import time

import keyboard
from PyQt5.QtCore import QCoreApplication, QObject, pyqtSignal


DEFAULT_GUIDE_LAYER_KEY = 'F22'


def normalize_guide_key(key):
    """Accept one function key; F12 is reserved by Windows debuggers."""
    key = str(key or '').strip().upper()
    if not key:
        return ''
    if not re.fullmatch(r'F(?:[1-9]|1[0-9]|2[0-4])', key) or key == 'F12':
        raise ValueError('拼音层按键请选择 F1～F24（F12 除外），或留空关闭。')
    return key


class HoldTapGesture:
    """Interpret one key as a temporary or latched layer plus guide double-tap.

    ``held`` always describes the physical key. Hold mode emits ``held`` layer
    events. Toggle mode emits ``layer`` events and exposes ``layer_active``;
    its short single tap waits for the double-tap deadline before changing it.
    ``toggle`` always means guide visibility, never the input layer.
    """

    def __init__(self, *, mode='hold', tap_seconds=0.250, gap_seconds=0.300):
        if mode not in ('hold', 'toggle'):
            raise ValueError('拼音层方式只能是按住或切换。')
        self.mode = mode
        self.tap_seconds = tap_seconds
        self.gap_seconds = gap_seconds
        self.held = False
        self.layer_active = False
        self._pressed_at = None
        self._last_tap_at = None
        self._pending_single = None
        self._used = False

    def key(self, pressed, at):
        if self.mode == 'toggle':
            return self._toggle_key(pressed, at)
        if bool(pressed) == self.held:
            return []
        self.held = bool(pressed)
        if self.held:
            if (self._last_tap_at is not None and
                    not 0 <= at - self._last_tap_at <= self.gap_seconds):
                self._last_tap_at = None
            self._pressed_at = at
            self._used = False
            return [('held', True)]

        events = [('held', False)]
        short = not self._used and 0 <= at - self._pressed_at <= self.tap_seconds
        if short and self._last_tap_at is not None:
            events.append(('toggle', None))
            self._last_tap_at = None
        else:
            self._last_tap_at = at if short else None
        self._pressed_at = None
        self._used = False
        return events

    def _switch_layer(self):
        self.layer_active = not self.layer_active
        return [('layer', self.layer_active)]

    def _toggle_key(self, pressed, at):
        # Callers may also tick before each merged input event. A deadline is
        # consumed once, so calling both remains deterministic and harmless.
        events = self.tick(at)
        if bool(pressed) == self.held:
            return events
        self.held = bool(pressed)
        if self.held:
            self._pressed_at = at
            self._used = False
            return events

        duration = at - self._pressed_at
        self._pressed_at = None
        if self._used or duration < 0:
            self._used = False
            return events
        if duration <= self.tap_seconds:
            if self._pending_single is not None:
                self._pending_single = None
                events.append(('toggle', None))
            else:
                self._pending_single = at + self.gap_seconds
        else:
            self._pending_single = None
            events.extend(self._switch_layer())
        return events

    def tick(self, at):
        """Resolve a toggle-mode single tap at its deadline, without sleeping.

        The double-tap release must be strictly before that deadline. At the
        deadline the single is already final, including when Qt delivers the
        timer and the second release in the same GUI turn.
        """
        if (self.mode == 'toggle' and self._pending_single is not None and
                at >= self._pending_single):
            self._pending_single = None
            return self._switch_layer()
        return []

    def note_input(self):
        """Morse input between or during taps cannot also toggle the guide."""
        events = []
        if self.mode == 'toggle' and self._pending_single is not None:
            self._pending_single = None
            events = self._switch_layer()
        self._last_tap_at = None
        if self.held:
            self._used = True
        return events

    def reset(self):
        if self.mode == 'hold':
            events = [('held', False)] if self.held else []
        else:
            events = [('layer', False)] if self.layer_active else []
        self.held = False
        self.layer_active = False
        self._pressed_at = None
        self._last_tap_at = None
        self._pending_single = None
        self._used = False
        return events


@dataclass
class _Registration:
    key: str
    active: bool = True
    pressed: bool = False
    unhook: object = None


class GuideKeyListener(QObject):
    available = pyqtSignal()
    ready = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, parent=None, *, platform_name=None, clock=None):
        super().__init__(parent)
        self.supported = (platform_name or platform.system()) == 'Windows'
        self.key = ''
        self._clock = clock or time.monotonic
        self._lock = threading.RLock()
        self._pending = deque()
        self._registrations = {}
        app = QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.stop)
        # QObject destruction must deactivate callbacks that keyboard still owns.
        self.destroyed.connect(lambda: self.stop())

    def set_key(self, key=DEFAULT_GUIDE_LAYER_KEY):
        try:
            key = normalize_guide_key(key)
        except ValueError as error:
            self.error.emit(str(error))
            return False
        if not key:
            self.stop()
            self.ready.emit('')
            return True
        if not self.supported:
            self.error.emit('拼音层按键目前仅支持 Windows。')
            return False
        with self._lock:
            if self.key == key:
                self.ready.emit(key)
                return True
        self.stop()
        with self._lock:
            # A previous binding may still own a DOWN waiting for its UP. Reuse
            # it instead of registering the same scan code twice in keyboard.
            registration = self._registrations.get(key)
            if registration is not None:
                registration.active = True
                self.key = key
                if registration.pressed:
                    self._pending.append((True, self._clock()))
                reused = True
            else:
                registration = _Registration(key)
                self._registrations[key] = registration
                self.key = key
                reused = False
        if reused:
            self.ready.emit(key)
            self.available.emit()
            return True
        try:
            unhook = keyboard.hook_key(
                key.lower(), lambda event: self._on_key(registration, event), suppress=True)
        except Exception as error:
            with self._lock:
                registration.active = False
                self._registrations.pop(key, None)
                if self.key == key:
                    self.key = ''
                self._pending.clear()
            self.error.emit('无法监听拼音层按键：' + str(error))
            return False
        with self._lock:
            registration.unhook = unhook
            active = registration.active
            if not active and not registration.pressed:
                self._remove_registration(registration)
        if active:
            self.ready.emit(key)
        return active

    def _remove_registration(self, registration):
        """Called under the lock; remove only this controller's registration."""
        if registration.unhook is None:
            return  # set_key may still be inside keyboard.hook_key.
        unhook, registration.unhook = registration.unhook, None
        if self._registrations.get(registration.key) is registration:
            self._registrations.pop(registration.key)
        try:
            unhook()
        except Exception:
            # The inactive callback passes future events through even if the
            # library refuses to remove it. Never unhook another input owner.
            logging.exception('释放拼音层按键监听失败')

    def _on_key(self, registration, event):
        if (getattr(event, 'is_keypad', False) or
                getattr(getattr(keyboard, '_listener', None), 'is_replaying', False) or
                event.event_type not in (keyboard.KEY_DOWN, keyboard.KEY_UP)):
            return True
        pressed = event.event_type == keyboard.KEY_DOWN
        notify = False
        with self._lock:
            if not registration.active:
                if not registration.pressed:
                    return True
                if not pressed:
                    registration.pressed = False
                    self._remove_registration(registration)
                # After stop/rebind, consume repeats and the UP belonging to
                # the DOWN already intercepted, but never enqueue stale input.
                return False
            if pressed == registration.pressed:
                return not pressed  # Consume auto-repeat; ignore an orphan UP.
            registration.pressed = pressed
            self._pending.append((pressed, self._clock()))
            notify = True
        if notify:
            self.available.emit()
        return False

    def snapshot_events(self):
        """Return (monotonic cutoff, [(pressed, timestamp), ...]) exactly once."""
        with self._lock:
            cutoff = self._clock()
            events = list(self._pending)
            self._pending.clear()
        return cutoff, events

    def stop(self):
        with self._lock:
            self.key = ''
            self._pending.clear()
            for registration in list(self._registrations.values()):
                registration.active = False
                if not registration.pressed:
                    self._remove_registration(registration)
