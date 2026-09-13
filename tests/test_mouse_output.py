"""Owned mouse output tests; no real mouse events are generated."""

import unittest
from unittest.mock import Mock, call

from mouse_output import MouseOutput


class MouseOutputTests(unittest.TestCase):
    def setUp(self):
        self.backend = Mock(spec=["press", "release", "click", "double_click", "move"])
        self.output = MouseOutput(self.backend)

    def test_reset_and_release_do_not_touch_unowned_physical_buttons(self):
        self.output.reset()
        self.output.release("left")
        self.output.release("right")
        self.assertEqual(self.backend.mock_calls, [])

    def test_holds_are_idempotent_and_reset_releases_each_once(self):
        self.output.press("left")
        self.output.press("right")
        self.output.press("left")
        snapshot = self.output.held_buttons
        self.output.reset()
        self.output.reset()
        self.assertEqual(snapshot, ("left", "right"))
        self.assertEqual(self.output.held_buttons, ())
        self.assertEqual(self.backend.mock_calls, [
            call.press("left"), call.press("right"),
            call.release("right"), call.release("left"),
        ])

    def test_reset_continues_after_a_failure_and_retries_only_failed_buttons(self):
        self.output.press("left")
        self.output.press("right")
        error = OSError("right button release failed")
        self.backend.release.side_effect = [error, None, None]
        with self.assertRaises(OSError) as raised:
            self.output.reset()
        self.assertIs(raised.exception, error)
        self.assertEqual(self.output.held_buttons, ("right",))
        self.output.reset()
        self.assertEqual(self.output.held_buttons, ())
        self.assertEqual(self.backend.release.call_args_list, [
            call("right"), call("left"), call("right"),
        ])

    def test_direct_release_failure_retains_ownership(self):
        self.output.press("left")
        self.backend.release.side_effect = OSError("release failed")
        with self.assertRaises(OSError):
            self.output.release("left")
        self.assertEqual(self.output.held_buttons, ("left",))
        self.backend.release.side_effect = None
        self.output.reset()
        self.assertEqual(self.output.held_buttons, ())

    def test_partial_press_failure_is_released_without_releasing_another_hold(self):
        self.output.press("right")
        error = OSError("press partly failed")
        self.backend.press.side_effect = error
        with self.assertRaises(OSError) as raised:
            self.output.press("left")
        self.assertIs(raised.exception, error)
        self.assertEqual(self.backend.release.call_args_list, [call("left")])
        self.assertEqual(self.output.held_buttons, ("right",))

    def test_failed_press_and_failed_cleanup_can_be_retried(self):
        error = OSError("press partly failed")
        self.backend.press.side_effect = error
        self.backend.release.side_effect = OSError("release failed")
        with self.assertRaises(OSError) as raised:
            self.output.press("left")
        self.assertIs(raised.exception, error)
        self.assertEqual(self.output.held_buttons, ("left",))
        self.backend.release.side_effect = None
        self.output.reset()
        self.assertEqual(self.output.held_buttons, ())

    def test_clicks_finish_an_owned_drag_and_leave_no_stale_ownership(self):
        for operation in ("click", "double_click"):
            with self.subTest(operation=operation):
                self.backend.reset_mock()
                self.output.press("right")
                self.output.press("left")
                getattr(self.output, operation)("left")
                self.assertEqual(self.output.held_buttons, ("right",))
                self.output.reset()
                self.assertEqual(self.backend.mock_calls, [
                    call.press("right"), call.press("left"), call.release("left"),
                    getattr(call, operation)(button="left"), call.release("right"),
                ])

    def test_ordinary_clicks_need_no_extra_release_on_reset(self):
        self.output.click("left")
        self.output.double_click("right")
        self.output.reset()
        self.assertEqual(self.output.held_buttons, ())
        self.assertEqual(self.backend.mock_calls, [
            call.click(button="left"), call.double_click(button="right"),
        ])

    def test_click_does_not_start_if_finishing_the_drag_fails(self):
        for operation in ("click", "double_click"):
            with self.subTest(operation=operation):
                self.backend.reset_mock(side_effect=True)
                self.output.press("left")
                self.backend.release.side_effect = OSError("release failed")
                with self.assertRaises(OSError):
                    getattr(self.output, operation)("left")
                getattr(self.backend, operation).assert_not_called()
                self.assertEqual(self.output.held_buttons, ("left",))
                self.backend.release.side_effect = None
                self.output.reset()

    def test_partial_click_failures_release_the_button_and_preserve_the_error(self):
        for operation in ("click", "double_click"):
            with self.subTest(operation=operation):
                self.backend.reset_mock(side_effect=True)
                error = OSError("click partly failed")
                getattr(self.backend, operation).side_effect = error
                with self.assertRaises(OSError) as raised:
                    getattr(self.output, operation)("left")
                self.assertIs(raised.exception, error)
                self.backend.release.assert_called_once_with("left")
                self.assertEqual(self.output.held_buttons, ())

    def test_failed_click_cleanup_keeps_ownership_for_reset(self):
        self.backend.double_click.side_effect = OSError("click partly failed")
        self.backend.release.side_effect = OSError("release failed")
        with self.assertRaisesRegex(OSError, "click partly failed"):
            self.output.double_click("right")
        self.assertEqual(self.output.held_buttons, ("right",))
        self.backend.release.side_effect = None
        self.output.reset()
        self.assertEqual(self.output.held_buttons, ())

    def test_move_preserves_drag_ownership_and_forwards_relative_coordinates(self):
        self.output.press("left")
        self.output.move(-5, 40)
        self.output.move(100, 200, True)
        self.assertEqual(self.output.held_buttons, ("left",))
        self.assertEqual(self.backend.move.call_args_list,
                         [call(-5, 40, False), call(100, 200, True)])

    def test_unknown_buttons_are_rejected_before_backend_access(self):
        for operation in ("press", "release", "click", "double_click"):
            with self.subTest(operation=operation):
                with self.assertRaises(ValueError):
                    getattr(self.output, operation)("middle")
        self.assertEqual(self.backend.mock_calls, [])


if __name__ == "__main__":
    unittest.main()
