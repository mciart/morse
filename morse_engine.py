"""Deterministic Morse timing, independent of Qt, hooks and sound devices.

All timestamps are monotonic seconds. Events carry their scheduled timestamp so
the caller can keep sound and visual feedback on the same timeline. The engine
never produces word spaces or operating-system input.
"""

from collections import deque
import math
import time


class MorseEngine:
    def __init__(self, config=None, callback=None):
        config = config or {}
        self.callback = callback
        self.key_count = max(1, min(3, int(config.get('keylen', 1))))
        requested = config.get('keyer_mode', config.get('input_mode'))
        if requested is None:
            requested = 'iambic' if config.get('fastMorseMode', False) else 'manual'
        if requested not in ('manual', 'iambic', 'straight'):
            raise ValueError('Unknown Morse input mode: %s' % requested)
        self.mode = 'straight' if self.key_count == 1 else requested
        if self.mode == 'straight' and self.key_count != 1:
            self.mode = 'manual'
        self.wpm = max(5.0, min(60.0, float(config.get('wpm', 15))))
        self.unit = 1.2 / self.wpm
        gap = float(config.get('character_gap_ms', config.get('minLetterPause', 0))) / 1000
        threshold = float(config.get('maxDitTime', 0)) / 1000
        self.character_gap = max(3 * self.unit, gap)
        self.threshold = threshold if threshold > 0 else 2 * self.unit
        self._events = []
        self._now = None
        self._blocked_roles = set()
        self._clear()

    def _clear(self):
        self.held = set()
        self.symbols = []
        self.tone = False
        self._pressed_at = None
        self._deadline = None
        self._phase = None
        self._last_symbol = None
        self._last_mark_started_at = None
        self._last_mark_ended_at = None
        self._queue = deque()
        self._memory = set()
        self._gap_started = None
        self._commit_at = None

    def _emit(self, event, **payload):
        payload.setdefault('at', self._now)
        self._events.append((event, payload))

    def _finish(self):
        events, self._events = self._events, []
        if self.callback:
            for event, payload in events:
                self.callback(event, payload)
        return events

    def _time(self, timestamp):
        timestamp = time.monotonic() if timestamp is None else float(timestamp)
        if not math.isfinite(timestamp):
            raise ValueError('Morse timestamps must be finite')
        # A queued OS event can arrive just after a UI timer. Never rewind the
        # state machine or use wall-clock time to measure a held key.
        return timestamp if self._now is None else max(timestamp, self._now)

    def _set_tone(self, on):
        if self.tone != on:
            self.tone = on
            self._emit('tone', on=on)

    def _append(self, symbol):
        self.symbols.append(symbol)
        self._emit('symbol', symbol=symbol)
        self._gap_started = self._commit_at = None

    def _begin_mark(self, symbol, append):
        self._gap_started = self._commit_at = None
        self._last_symbol = symbol
        self._last_mark_started_at = self._now
        self._phase = 'mark'
        self._deadline = self._now + self.unit * (1 if symbol == 1 else 3)
        if self.mode == 'iambic':
            # Squeeze memory includes the opposite paddle already held when
            # this element begins, even if it is released before the next tick.
            self._memory.update(role + 1 for role in self.held
                                if role < 2 and role + 1 != symbol)
        # Open the sidetone before the caller updates the potentially expensive
        # guide. Its visual callbacks must not delay the first audible frame.
        self._set_tone(True)
        if append:
            self._append(symbol)

    def _next_iambic(self):
        available = {role + 1 for role in self.held if role < 2} | self._memory
        if not available:
            return None
        opposite = 2 if self._last_symbol == 1 else 1
        symbol = opposite if opposite in available else min(available)
        self._memory.discard(symbol)
        return symbol

    def _schedule_commit(self, timestamp):
        if self.symbols and not self.held and self.key_count < 3:
            self._gap_started = timestamp
            self._commit_at = timestamp + self.character_gap

    def _commit(self):
        if self.symbols:
            completed = tuple(self.symbols)
            self.symbols.clear()
            self._emit('commit', symbols=completed)
        self._gap_started = self._commit_at = None

    def _safety_reset(self, reason, target, released_role=None):
        blocked = self.held | self._blocked_roles
        if released_role is not None:
            blocked.discard(released_role)
        self._events.clear()
        self._now = target
        self._set_tone(False)
        self._clear()
        self._blocked_roles = blocked
        self._emit('reset', reason=reason)

    def _advance(self, target):
        if (self.mode == 'iambic' and self._phase is not None and
                self._now is not None and target - self._now > 1.0):
            # After a suspended or blocked GUI, stop immediately instead of
            # delivering a burst of obsolete tone and symbol transitions.
            self._safety_reset('timing_overrun', target)
            return
        # A delayed Qt tick still respects mark/gap ordering and exact lengths.
        # Bound catch-up after suspend; do not emit minutes of held-key repeats.
        transitions = 0
        while self._deadline is not None and self._deadline <= target + 1e-9:
            self._now = self._deadline
            transitions += 1
            if transitions > 128:
                self._safety_reset('timing_overrun', target)
                break
            if self._phase == 'mark':
                self._set_tone(False)
                self._last_mark_ended_at = self._now
                self._phase = 'space'
                self._deadline = self._now + self.unit
                self._schedule_commit(self._now)
            else:
                self._deadline = self._phase = None
                if self.mode == 'iambic':
                    symbol = self._next_iambic()
                    if symbol is not None:
                        self._begin_mark(symbol, True)
                elif self._queue:
                    self._begin_mark(self._queue.popleft(), False)
        self._now = target
        if self._commit_at is not None and target + 1e-9 >= self._commit_at:
            # Explicit confirmation is independent of audio; automatic commit
            # waits until the complete manual audio queue has finished.
            if not self.held and not self.tone and not self._queue:
                self._now = self._commit_at
                self._commit()
                self._now = target

    def _feedback(self):
        remaining = (max(0.0, self._commit_at - self._now)
                     if self._commit_at is not None else None)
        progress = 0.0 if remaining is None else max(0.0, min(1.0, 1 - remaining / self.character_gap))
        self._emit('feedback', held=tuple(sorted(self.held)), symbols=tuple(self.symbols),
                   tone=self.tone, progress=progress,
                   remaining_ms=None if remaining is None else remaining * 1000,
                   sounding=(None if not self.tone else 'straight' if self.mode == 'straight'
                             else 'dot' if self._last_symbol == 1 else 'dash'),
                   blocked=tuple(sorted(self._blocked_roles)),
                   mode=self.mode)

    def key(self, role, pressed, timestamp=None):
        role = int(role)
        observed = time.monotonic() if timestamp is None else float(timestamp)
        target = self._time(observed)
        if (self.mode == 'iambic' and not pressed and role in self.held and
                self._last_mark_started_at is not None and
                observed + 1e-9 < self._last_mark_started_at):
            # A late release says a generated element may not have been held
            # at its start. Do not submit a potentially incorrect character.
            self._safety_reset('late_input', target, released_role=role)
            self._feedback()
            return self._finish()
        self._advance(target)
        if self._blocked_roles:
            # An OS repeat down after suspend is not a new physical press.
            # All affected paddles must first be released before keying resumes.
            if 0 <= role < self.key_count:
                if pressed:
                    self._blocked_roles.add(role)
                else:
                    self._blocked_roles.discard(role)
            self._feedback()
            return self._finish()
        if role < 0 or role >= self.key_count or bool(pressed) == (role in self.held):
            return self._finish()
        if pressed:
            self.held.add(role)
            self._commit_at = self._gap_started = None
            if role == 2:
                # Explicit confirmation ends this character, including any
                # sounds queued by faster manual key presses.
                self._set_tone(False)
                self._queue.clear()
                self._memory.clear()
                self._phase = self._deadline = None
                self._commit()
            elif self.mode == 'straight':
                self._pressed_at = observed
                self._set_tone(True)
            elif self.mode == 'manual':
                symbol = role + 1
                if self._phase is None:
                    self._begin_mark(symbol, True)
                else:
                    self._append(symbol)
                    self._queue.append(symbol)
            else:
                if self._phase is None:
                    self._memory.add(role + 1)
                    self._begin_mark(self._next_iambic(), True)
                elif role + 1 != self._last_symbol:
                    # Only the opposite paddle has element memory. Re-tapping
                    # the currently sounding paddle is not an extra element
                    # unless it remains held at the next element boundary.
                    self._memory.add(role + 1)
        else:
            self.held.discard(role)
            if self.mode == 'straight' and role == 0:
                self._set_tone(False)
                duration = max(0.0, observed - self._pressed_at)
                self._pressed_at = None
                self._append(1 if duration + 1e-9 < self.threshold else 2)
            if not self.held:
                # In automatic mode the last mark can outlive a quick tap.
                if self._phase != 'mark' and not self._queue:
                    # An automatic mark's silence begins at tone-off, even if
                    # the paddle is released partway through its inner space.
                    # Measuring from release would add up to an extra dit to
                    # the standard three-dit character gap.
                    gap_start = (self._last_mark_ended_at
                                 if self.mode == 'iambic' and self._last_mark_ended_at is not None
                                 else target)
                    self._schedule_commit(gap_start)
        self._feedback()
        return self._finish()

    def tick(self, now=None):
        self._advance(self._time(now))
        self._feedback()
        return self._finish()

    def reset(self, now=None):
        self._now = self._time(now)
        self._set_tone(False)
        self._clear()
        self._blocked_roles.clear()
        self._emit('reset', reason='stopped')
        self._feedback()
        return self._finish()
