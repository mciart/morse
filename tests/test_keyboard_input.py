"""Keyboard regression tests; no system hooks or synthetic key presses are used."""

import unittest
from types import MethodType, SimpleNamespace
from unittest.mock import Mock, call, patch

# Importing the application should not truncate the user's log during tests.
with patch("logging.basicConfig"):
    import MorseCodeGUI as morse


def key_event(name, event_type="down", is_keypad=False):
    return SimpleNamespace(name=name, event_type=event_type, is_keypad=is_keypad)


class KeyboardInputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.object(morse.ConfigManager, "read_config", return_value={}):
            cls.keymap = morse.ConfigManager(config_file="unused.json").keystrokemap

    def setUp(self):
        # The production class still runs, but every operating-system hook is mocked.
        self.hook_key = self.enterContext(patch.object(morse.keyboard, "hook_key"))
        self.unhook_all = self.enterContext(patch.object(morse.keyboard, "unhook_all"))
        self.enterContext(patch.object(morse.platform, "system", return_value="Windows"))

    def tearDown(self):
        self.unhook_all.assert_not_called()

    def test_each_mode_hooks_only_its_active_keys(self):
        for count in (1, 2, 3):
            with self.subTest(mode=count):
                self.hook_key.reset_mock()
                config = dict(morse.DEFAULT_CONFIG, keylen=count)
                # Disabled fields may contain stale or invalid configuration.
                for field in ("keyone", "keytwo", "keythree")[count:]:
                    config[field] = "INVALID_UNUSED_KEY"
                window = SimpleNamespace(config=config, keystrokemap=self.keymap)
                keys = morse.Window.get_configured_keys(window)
                self.assertEqual(keys, ["space", "enter", "right ctrl"][:count])
                listener = morse.KeyListenerThread(keys)
                cleanup = [Mock() for _ in keys]
                self.hook_key.side_effect = cleanup
                with patch.object(morse.time, "sleep", side_effect=lambda _: listener.stop()):
                    listener.run()
                self.assertEqual(
                    [args.args[0] for args in self.hook_key.call_args_list], keys
                )
                self.assertTrue(all(args.kwargs["suppress"] for args in self.hook_key.call_args_list))
                for unhook in cleanup:
                    unhook.assert_called_once_with()

    def test_ctrl_key_codes(self):
        self.assertEqual(self.keymap["CTRL"].key_code, "ctrl")
        self.assertEqual(self.keymap["LCTRL"].key_code, "left ctrl")
        self.assertEqual(self.keymap["RCTRL"].key_code, "right ctrl")

    def test_callbacks_keep_configured_key_and_role_when_event_names_change(self):
        listener = morse.KeyListenerThread(["left shift", "1"])
        emitted = Mock()
        listener.keyEvent.connect(emitted)
        callbacks = {}

        def install(key, callback, suppress):
            callbacks[key] = callback
            return Mock()

        def send_events_then_stop(_):
            # Windows reports left Shift as "shift"; Shift+1 is named "!".
            for key, name in (("left shift", "shift"), ("1", "!")):
                self.assertFalse(callbacks[key](key_event(name)))
                self.assertFalse(callbacks[key](key_event(name, "up")))
            listener.stop()

        self.hook_key.side_effect = install
        with patch.object(morse.time, "sleep", side_effect=send_events_then_stop):
            listener.run()
        self.assertEqual(emitted.call_args_list, [
            call("left shift", True, 0), call("left shift", False, 0),
            call("1", True, 1), call("1", False, 1),
        ])
        self.assertTrue(callbacks["1"](key_event("1")))
        self.assertEqual(emitted.call_count, 4)

    def test_sided_ctrl_does_not_consume_the_other_ctrl_key(self):
        for configured, accepted, rejected in (
            ("right ctrl", ("right ctrl",), ("ctrl", "left ctrl")),
            ("left ctrl", ("ctrl", "left ctrl"), ("right ctrl",)),
        ):
            with self.subTest(key=configured):
                listener = morse.KeyListenerThread([configured])
                emitted = Mock()
                listener.keyEvent.connect(emitted)
                for name in rejected:
                    for event_type in ("down", "up"):
                        self.assertTrue(listener.on_key_event(key_event(name, event_type), configured, 0))
                emitted.assert_not_called()
                for name in accepted:
                    self.assertFalse(listener.on_key_event(key_event(name), configured, 0))
                    self.assertFalse(listener.on_key_event(key_event(name, "up"), configured, 0))
                self.assertEqual(emitted.call_args_list, [
                    call(configured, True, 0), call(configured, False, 0),
                ] * len(accepted))

    def test_numeric_keypad_navigation_is_not_consumed(self):
        for configured, keypad_name in (("1", "end"), ("2", "down")):
            with self.subTest(key=configured):
                listener = morse.KeyListenerThread([configured])
                emitted = Mock()
                listener.keyEvent.connect(emitted)
                for event_type in ("down", "up"):
                    self.assertTrue(listener.on_key_event(
                        key_event(keypad_name, event_type, is_keypad=True), configured, 0
                    ))
                emitted.assert_not_called()
                self.assertFalse(listener.on_key_event(key_event(configured), configured, 0))
                emitted.assert_called_once_with(configured, True, 0)

    def test_partial_registration_failure_removes_already_installed_hooks(self):
        listener = morse.KeyListenerThread(["space", "enter"])
        cleanup = Mock()
        self.hook_key.side_effect = [cleanup, RuntimeError("hook installation failed")]
        with self.assertRaisesRegex(RuntimeError, "hook installation failed"):
            listener.run()
        cleanup.assert_called_once_with()

    def test_stop_during_registration_still_removes_the_returned_hook(self):
        listener = morse.KeyListenerThread(["space"])
        cleanup = Mock()

        def install(key, callback, suppress):
            # Reproduce a stop arriving before registration returns its handle.
            listener.stop()
            self.assertTrue(callback(key_event("space")))
            return cleanup

        self.hook_key.side_effect = install
        with patch.object(morse.time, "sleep") as sleep:
            listener.run()
        sleep.assert_not_called()
        cleanup.assert_called_once_with()


class WindowListenerLifecycleTests(unittest.TestCase):
    def make_window(self):
        window = SimpleNamespace(
            config={"off": False}, listenerThread=Mock(), codeslayoutview=Mock(),
            endCharacterTimer=Mock(), fast_morse_mode_timer=Mock(),
            repeat_character_timer=Mock(), currentCharacter=[1, 2],
            lastKeyDownTime=123, repeaton=True, showNormal=Mock(),
            onOffAction=Mock(),
            get_configured_keys=Mock(return_value=["space"]),
            on_press=Mock(), on_release=Mock(),
        )
        for name in ("stopKeyListener", "startKeyListener", "stopIt", "handle_key_event"):
            setattr(window, name, MethodType(getattr(morse.Window, name), window))
        return window

    def test_onoff_releases_listener_and_pending_timers_then_restarts(self):
        window = self.make_window()
        old_listener = window.listenerThread
        timers = [window.endCharacterTimer, window.fast_morse_mode_timer, window.repeat_character_timer]
        with patch.object(morse, "KeyListenerThread") as listener_class:
            morse.Window.toggleOnOff(window)
            self.assertTrue(window.config["off"])
            self.assertIsNone(window.listenerThread)
            old_listener.stop.assert_called_once_with()
            for timer in timers:
                timer.stop.assert_called_once_with()
            self.assertIsNone(window.endCharacterTimer)
            self.assertIsNone(window.fast_morse_mode_timer)
            self.assertIsNone(window.repeat_character_timer)
            self.assertEqual(window.currentCharacter, [])
            self.assertIsNone(window.lastKeyDownTime)
            self.assertFalse(window.repeaton)
            window.handle_key_event("space", True, 0)
            window.handle_key_event("space", False, 0)
            window.on_press.assert_not_called()
            window.on_release.assert_not_called()
            window.startKeyListener()  # An off configuration must stay paused.
            listener_class.assert_not_called()

            morse.Window.toggleOnOff(window)
            self.assertFalse(window.config["off"])
            listener_class.assert_called_once_with(configured_keys=["space"])
            listener_class.return_value.start.assert_called_once_with()
            listener_class.return_value.keyEvent.connect.assert_called_once_with(window.handle_key_event)
            window.handle_key_event("space", True, 0)
            window.handle_key_event("space", False, 0)
            window.on_press.assert_called_once_with("space", 0)
            window.on_release.assert_called_once_with("space", 0)

    def test_returning_to_settings_ignores_queued_events_and_onoff(self):
        window = self.make_window()
        view = window.codeslayoutview
        morse.Window.backToSettings(window)
        window.showNormal.assert_called_once_with()
        view.hide.assert_called_once_with()
        self.assertIsNone(window.codeslayoutview)
        window.handle_key_event("space", True, 0)
        window.handle_key_event("space", False, 0)
        window.on_press.assert_not_called()
        window.on_release.assert_not_called()
        with patch.object(morse, "KeyListenerThread") as listener_class:
            morse.Window.toggleOnOff(window)
        listener_class.assert_not_called()


if __name__ == "__main__":
    unittest.main()
