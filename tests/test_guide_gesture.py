"""Gesture and hook ownership checks without registering any system hook."""

from types import SimpleNamespace
import unittest
from unittest.mock import Mock, call, patch

from guide_gesture import GuideKeyListener, HoldTapGesture, normalize_guide_key


class HoldTapGestureTests(unittest.TestCase):
    def setUp(self):
        self.gesture = HoldTapGesture()

    def tap(self, down, up):
        self.assertEqual(self.gesture.key(True, down), [('held', True)])
        return self.gesture.key(False, up)

    def test_hold_is_immediate_and_long_release_does_not_toggle(self):
        self.assertEqual(self.gesture.key(True, 1), [('held', True)])
        self.assertTrue(self.gesture.held)
        self.assertEqual(self.gesture.key(False, 2), [('held', False)])
        self.assertFalse(self.gesture.held)

    def test_two_short_taps_toggle_only_on_second_release(self):
        self.assertEqual(self.tap(1, 1.1), [('held', False)])
        self.assertEqual(self.gesture.key(True, 1.2), [('held', True)])
        self.assertEqual(self.gesture.key(False, 1.3),
                         [('held', False), ('toggle', None)])

    def test_morse_input_during_either_tap_cancels_toggle(self):
        for input_on in (1, 2):
            with self.subTest(input_on=input_on):
                gesture = HoldTapGesture()
                for index, down in ((1, 1), (2, 1.2)):
                    gesture.key(True, down)
                    if index == input_on:
                        gesture.note_input()
                    self.assertEqual(gesture.key(False, down + 0.05), [('held', False)])

    def test_input_between_taps_cancels_previous_tap(self):
        self.tap(1, 1.05)
        self.gesture.note_input()
        self.assertEqual(self.tap(1.2, 1.25), [('held', False)])

    def test_long_tap_breaks_pair(self):
        self.tap(1, 1.1)
        self.assertEqual(self.tap(1.2, 2), [('held', False)])
        self.assertEqual(self.tap(2.1, 2.2), [('held', False)])

    def test_slow_taps_do_not_toggle(self):
        self.tap(1, 1.05)
        self.assertEqual(self.tap(1.5, 1.6), [('held', False)])

    def test_gap_measured_to_second_press(self):
        self.tap(1, 1.1)
        self.assertEqual(self.tap(1.35, 1.59), [('held', False), ('toggle', None)])

    def test_auto_repeat_does_not_shorten_long_hold(self):
        self.gesture.key(True, 1)
        self.assertEqual(self.gesture.key(True, 2), [])
        self.assertEqual(self.gesture.key(False, 2.1), [('held', False)])
        self.assertEqual(self.tap(2.2, 2.3), [('held', False)])

    def test_orphan_release_and_duplicate_release_do_nothing(self):
        self.assertEqual(self.gesture.key(False, 0), [])
        self.tap(1, 1.1)
        self.assertEqual(self.gesture.key(False, 1.15), [])
        self.assertEqual(self.tap(1.2, 1.3), [('held', False), ('toggle', None)])

    def test_four_taps_are_two_pairs_and_three_taps_only_one(self):
        toggles = []
        for down in (1, 1.2, 1.4, 1.6):
            toggles.append(('toggle', None) in self.tap(down, down + 0.05))
        self.assertEqual(toggles, [False, True, False, True])

    def test_reset_releases_layer_and_clears_double_tap(self):
        self.tap(1, 1.1)
        self.gesture.key(True, 1.2)
        self.assertEqual(self.gesture.reset(), [('held', False)])
        self.assertFalse(self.gesture.held)
        self.assertEqual(self.gesture.reset(), [])
        self.assertEqual(self.tap(1.3, 1.4), [('held', False)])

    def test_negative_duration_is_not_a_short_tap(self):
        self.tap(2, 1)
        self.assertEqual(self.tap(1.1, 1.2), [('held', False)])


class ToggleLayerGestureTests(unittest.TestCase):
    def setUp(self):
        self.gesture = HoldTapGesture(mode='toggle')

    def tap(self, down, up):
        self.assertEqual(self.gesture.key(True, down), [])
        return self.gesture.key(False, up)

    def test_single_tap_keeps_layer_unchanged_until_deadline(self):
        self.assertEqual(self.tap(0, 0.1), [])
        self.assertFalse(self.gesture.held)
        self.assertFalse(self.gesture.layer_active)
        self.assertEqual(self.gesture.tick(0.399999), [])
        self.assertEqual(self.gesture.tick(0.4), [('layer', True)])
        self.assertTrue(self.gesture.layer_active)
        self.assertEqual(self.gesture.tick(10), [])

    def test_second_single_tap_switches_back_and_stays_latched(self):
        self.tap(0, 0.1)
        self.gesture.tick(0.4)
        self.assertEqual(self.tap(1, 1.1), [])
        self.assertTrue(self.gesture.layer_active)
        self.assertEqual(self.gesture.tick(1.41), [('layer', False)])
        self.assertFalse(self.gesture.layer_active)

    def test_double_tap_changes_visibility_without_any_layer_event(self):
        events = self.tap(0, 0.1) + self.tap(0.2, 0.3)
        self.assertEqual(events, [('toggle', None)])
        self.assertFalse(self.gesture.layer_active)
        self.assertEqual(self.gesture.tick(1), [])

    def test_double_tap_preserves_already_active_layer(self):
        self.tap(0, 0.1)
        self.gesture.tick(0.4)
        self.assertEqual(self.tap(1, 1.1) + self.tap(1.2, 1.3), [('toggle', None)])
        self.assertTrue(self.gesture.layer_active)
        self.assertEqual(self.gesture.tick(2), [])

    def test_release_just_before_deadline_is_double_tap(self):
        self.tap(0, 0.1)
        self.assertEqual(self.tap(0.2, 0.399999), [('toggle', None)])
        self.assertEqual(self.gesture.tick(0.4), [])

    def test_release_at_deadline_is_two_single_taps(self):
        self.tap(0, 0.1)
        self.gesture.key(True, 0.2)
        self.assertEqual(self.gesture.key(False, 0.4), [('layer', True)])
        self.assertEqual(self.gesture.tick(0.7), [('layer', False)])

    def test_timer_before_release_matches_release_before_timer_at_deadline(self):
        first = HoldTapGesture(mode='toggle')
        second = HoldTapGesture(mode='toggle')
        for gesture in (first, second):
            gesture.key(True, 0)
            gesture.key(False, 0.1)
            gesture.key(True, 0.2)
        first_events = first.tick(0.4) + first.key(False, 0.4)
        second_events = second.key(False, 0.4) + second.tick(0.4)
        self.assertEqual(first_events, [('layer', True)])
        self.assertEqual(first_events, second_events)
        self.assertEqual(first.tick(1), second.tick(1))

    def test_input_after_first_tap_immediately_commits_pending_single(self):
        self.tap(0, 0.1)
        self.assertEqual(self.gesture.note_input(), [('layer', True)])
        self.assertTrue(self.gesture.layer_active)
        self.assertEqual(self.gesture.note_input(), [])
        self.assertEqual(self.gesture.tick(0.4), [])
        self.assertEqual(self.tap(0.2, 0.3), [])
        self.assertEqual(self.gesture.tick(0.6), [('layer', False)])

    def test_input_during_second_press_commits_first_without_later_toggle(self):
        self.tap(0, 0.1)
        self.gesture.key(True, 0.2)
        self.assertEqual(self.gesture.note_input(), [('layer', True)])
        self.assertEqual(self.gesture.key(False, 0.3), [])
        self.assertEqual(self.gesture.tick(1), [])
        self.assertTrue(self.gesture.layer_active)

    def test_long_press_switches_once_on_release_without_waiting(self):
        self.assertEqual(self.gesture.key(True, 0), [])
        self.assertTrue(self.gesture.held)
        self.assertEqual(self.gesture.tick(1), [])
        self.assertEqual(self.gesture.key(False, 1), [('layer', True)])
        self.assertFalse(self.gesture.held)
        self.assertEqual(self.gesture.tick(2), [])
        self.assertEqual(self.tap(3, 4), [('layer', False)])

    def test_auto_repeat_does_not_create_taps_or_shorten_long_press(self):
        self.gesture.key(True, 0)
        self.assertEqual(self.gesture.key(True, 1), [])
        self.assertEqual(self.gesture.key(True, 1.1), [])
        self.assertEqual(self.gesture.key(False, 1.2), [('layer', True)])
        self.assertEqual(self.gesture.key(False, 1.3), [])
        self.assertEqual(self.gesture.tick(2), [])

    def test_new_key_event_also_resolves_expired_pending_single(self):
        self.tap(0, 0.1)
        self.assertEqual(self.gesture.key(True, 1), [('layer', True)])
        self.assertEqual(self.gesture.key(False, 1.1), [])
        self.assertEqual(self.gesture.tick(1.5), [('layer', False)])

    def test_reset_discards_pending_single_and_physical_press(self):
        self.tap(0, 0.1)
        self.gesture.key(True, 0.2)
        self.assertEqual(self.gesture.reset(), [])
        self.assertFalse(self.gesture.held)
        self.assertFalse(self.gesture.layer_active)
        self.assertEqual(self.gesture.tick(1), [])
        self.assertEqual(self.gesture.key(False, 1.1), [])

    def test_reset_active_layer_reports_release_and_clears_pending_flip(self):
        self.tap(0, 0.1)
        self.gesture.tick(0.4)
        self.tap(1, 1.1)
        self.assertEqual(self.gesture.reset(), [('layer', False)])
        self.assertEqual(self.gesture.reset(), [])
        self.assertEqual(self.gesture.tick(2), [])
        self.assertFalse(self.gesture.layer_active)

    def test_repeated_double_taps_never_change_layer(self):
        for first_down in (0, 1, 2):
            self.tap(first_down, first_down + 0.1)
            self.assertEqual(self.tap(first_down + 0.2, first_down + 0.3), [('toggle', None)])
        self.assertFalse(self.gesture.layer_active)
        self.assertEqual(self.gesture.tick(3), [])

    def test_input_during_hold_cancels_late_unintended_layer_change(self):
        self.gesture.key(True, 0)
        self.assertEqual(self.gesture.note_input(), [])
        self.assertEqual(self.gesture.key(False, 1), [])
        self.assertFalse(self.gesture.layer_active)

    def test_hold_mode_tick_is_noop_and_note_input_returns_empty_events(self):
        gesture = HoldTapGesture()
        self.assertEqual(gesture.key(True, 0), [('held', True)])
        self.assertEqual(gesture.tick(10), [])
        self.assertEqual(gesture.note_input(), [])
        self.assertEqual(gesture.key(False, 11), [('held', False)])

    def test_invalid_mode_is_rejected(self):
        with self.assertRaises(ValueError):
            HoldTapGesture(mode='unknown')


class GuideKeyListenerTests(unittest.TestCase):
    def setUp(self):
        self.hook = self.enterContext(patch('guide_gesture.keyboard.hook_key'))
        self.unhook_all = self.enterContext(patch('guide_gesture.keyboard.unhook_all'))
        self.enterContext(patch('guide_gesture.keyboard._listener', SimpleNamespace(is_replaying=False)))
        self.now = 1.0
        self.callbacks = {}
        self.cleanups = {}

        def install(key, callback, suppress):
            self.assertTrue(suppress)
            self.callbacks[key] = callback
            cleanup = self.cleanups[key] = Mock()
            return cleanup

        self.hook.side_effect = install
        self.listener = GuideKeyListener(platform_name='Windows', clock=lambda: self.now)
        self.available = Mock()
        self.ready = Mock()
        self.error = Mock()
        self.listener.available.connect(self.available)
        self.listener.ready.connect(self.ready)
        self.listener.error.connect(self.error)
        self.addCleanup(self.listener.stop)

    def tearDown(self):
        self.unhook_all.assert_not_called()

    def event(self, key='f22', event_type='down', **kwargs):
        return self.callbacks[key](SimpleNamespace(event_type=event_type, **kwargs))

    def test_only_single_function_keys_are_valid(self):
        self.assertEqual(normalize_guide_key(' f22 '), 'F22')
        self.assertEqual(normalize_guide_key(''), '')
        for number in range(1, 25):
            if number != 12:
                self.assertEqual(normalize_guide_key('F%d' % number), 'F%d' % number)
        for value in ('F0', 'F25', 'F12', 'Ctrl+F22', 'a', 'F022'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_guide_key(value)

    def test_edges_use_monotonic_queue_and_drain_exactly_once(self):
        self.assertTrue(self.listener.set_key())
        self.ready.assert_called_once_with('F22')
        self.assertFalse(self.event())
        self.now = 1.2
        self.assertFalse(self.event(event_type='up'))
        self.now = 1.3
        self.assertEqual(self.listener.snapshot_events(), (1.3, [(True, 1.0), (False, 1.2)]))
        self.assertEqual(self.listener.snapshot_events(), (1.3, []))
        self.assertEqual(self.available.call_count, 2)

    def test_auto_repeat_and_orphan_up_are_not_queued(self):
        self.listener.set_key()
        self.assertTrue(self.event(event_type='up'))
        self.assertFalse(self.event())
        self.now = 2
        self.assertFalse(self.event())
        self.assertEqual(self.listener.snapshot_events()[1], [(True, 1.0)])
        self.available.assert_called_once_with()

    def test_own_output_and_other_event_types_pass_through(self):
        self.listener.set_key()
        with patch('guide_gesture.keyboard._listener.is_replaying', True):
            self.assertTrue(self.event())
        self.assertTrue(self.event(event_type='unknown'))
        self.assertTrue(self.event(is_keypad=True))
        self.assertEqual(self.listener.snapshot_events()[1], [])

    def test_rewasd_injected_events_are_accepted(self):
        self.listener.set_key()
        self.assertFalse(self.event(is_injected=True))
        self.assertEqual(self.listener.snapshot_events()[1], [(True, 1.0)])

    def test_reapplying_same_key_does_not_duplicate_hooks(self):
        self.listener.set_key()
        self.listener.set_key('f22')
        self.hook.assert_called_once()
        self.assertEqual(self.ready.call_args_list, [call('F22'), call('F22')])

    def test_invalid_rebind_preserves_current_key(self):
        self.listener.set_key()
        self.assertFalse(self.listener.set_key('Ctrl+F22'))
        self.assertEqual(self.listener.key, 'F22')
        self.cleanups['f22'].assert_not_called()
        self.error.assert_called_once()

    def test_rebind_removes_only_owned_unheld_hook(self):
        self.listener.set_key()
        old = self.callbacks['f22']
        self.assertTrue(self.listener.set_key('F23'))
        self.cleanups['f22'].assert_called_once_with()
        self.assertTrue(old(SimpleNamespace(event_type='down')))
        self.assertFalse(self.event(key='f23'))
        self.assertEqual(self.listener.snapshot_events()[1], [(True, 1.0)])

    def test_stop_clears_events_and_stale_callbacks_cannot_enqueue(self):
        self.listener.set_key()
        callback = self.callbacks['f22']
        self.listener.stop()
        self.listener.stop()
        self.cleanups['f22'].assert_called_once_with()
        self.assertTrue(callback(SimpleNamespace(event_type='down')))
        self.assertEqual(self.listener.snapshot_events()[1], [])

    def test_stop_while_held_consumes_owned_release_then_unhooks(self):
        self.listener.set_key()
        self.event()
        self.listener.stop()
        self.cleanups['f22'].assert_not_called()
        self.assertFalse(self.event())
        self.assertFalse(self.event(event_type='up'))
        self.cleanups['f22'].assert_called_once_with()
        self.assertEqual(self.listener.snapshot_events()[1], [])
        self.assertTrue(self.event())
        self.available.assert_called_once_with()

    def test_rebinding_while_held_does_not_leak_old_up(self):
        self.listener.set_key()
        self.event()
        self.listener.set_key('F23')
        self.assertFalse(self.event(event_type='up'))
        self.cleanups['f22'].assert_called_once_with()
        self.assertEqual(self.listener.snapshot_events()[1], [])
        self.assertFalse(self.event(key='f23'))
        self.assertEqual(self.listener.snapshot_events()[1], [(True, 1.0)])

    def test_reactivate_held_key_reuses_its_hook_and_reports_current_hold(self):
        self.listener.set_key()
        self.event()
        self.listener.stop()
        self.now = 2
        self.assertTrue(self.listener.set_key())
        self.hook.assert_called_once()
        self.assertEqual(self.listener.snapshot_events()[1], [(True, 2)])
        self.assertFalse(self.event(event_type='up'))
        self.assertEqual(self.listener.snapshot_events()[1], [(False, 2)])

    def test_empty_key_disables_and_reports_ready(self):
        self.listener.set_key()
        self.assertTrue(self.listener.set_key(''))
        self.assertEqual(self.listener.key, '')
        self.ready.assert_called_with('')
        self.cleanups['f22'].assert_called_once_with()

    def test_unsupported_platform_does_not_install(self):
        listener = GuideKeyListener(platform_name='Linux')
        self.assertFalse(listener.supported)
        self.assertFalse(listener.set_key())
        self.hook.assert_not_called()
        self.assertTrue(listener.set_key(''))

    def test_registration_failure_reports_error_without_active_binding(self):
        self.hook.side_effect = RuntimeError('registration failed')
        self.assertFalse(self.listener.set_key())
        self.assertEqual(self.listener.key, '')
        self.assertEqual(self.listener.snapshot_events()[1], [])
        self.error.assert_called_once()
        self.assertIn('registration failed', self.error.call_args.args[0])
        self.ready.assert_not_called()

    def test_stop_during_registration_removes_late_returned_hook(self):
        cleanup = Mock()

        def install(key, callback, suppress):
            self.listener.stop()
            self.assertTrue(callback(SimpleNamespace(event_type='down')))
            return cleanup

        self.hook.side_effect = install
        self.assertFalse(self.listener.set_key())
        cleanup.assert_called_once_with()
        self.assertEqual(self.listener.key, '')
        self.ready.assert_not_called()

    def test_cleanup_failure_leaves_callback_inactive(self):
        self.listener.set_key()
        self.cleanups['f22'].side_effect = RuntimeError('cleanup failed')
        with self.assertLogs(level='ERROR'):
            self.listener.stop()
        self.assertTrue(self.event())
        self.assertEqual(self.listener.snapshot_events()[1], [])


if __name__ == '__main__':
    unittest.main()
