"""Mouse output that releases only buttons pressed by this instance."""

from __future__ import annotations


class MouseOutput:
    def __init__(self, backend=None):
        if backend is None:
            import mouse
            backend = mouse
        self.backend = backend
        self._held_buttons = {}

    @property
    def held_buttons(self):
        """A snapshot of our held buttons, including failed release attempts."""
        return tuple(self._held_buttons)

    @staticmethod
    def _validate_button(button):
        if button not in ("left", "right"):
            raise ValueError(f"Unsupported mouse button: {button}")

    def release(self, button):
        """Leave buttons untouched unless this instance attempted their press."""
        self._validate_button(button)
        if button in self._held_buttons:
            self.backend.release(button)
            del self._held_buttons[button]

    def reset(self):
        """Try every owned button; retain failures so a later reset can retry."""
        error = None
        for button in reversed(self.held_buttons):
            try:
                self.release(button)
            except Exception as exc:
                if error is None:
                    error = exc
        if error is not None:
            raise error

    def _recover_button(self, button):
        try:
            self.release(button)
        except Exception:
            # Keep ownership and the original output error. Pause/exit can retry.
            pass

    def press(self, button):
        self._validate_button(button)
        if button in self._held_buttons:
            return
        # A backend can emit the down event and then fail before returning.
        self._held_buttons[button] = None
        try:
            self.backend.press(button)
        except Exception:
            self._recover_button(button)
            raise

    def _click(self, button, operation):
        self._validate_button(button)
        # Finish an existing drag before generating a fresh click sequence.
        self.release(button)
        self._held_buttons[button] = None
        try:
            getattr(self.backend, operation)(button=button)
        except Exception:
            self._recover_button(button)
            raise
        else:
            # Both backend click operations end with a button-up event.
            del self._held_buttons[button]

    def click(self, button):
        self._click(button, "click")

    def double_click(self, button):
        self._click(button, "double_click")

    def move(self, x, y, absolute=False):
        self.backend.move(x, y, absolute)
