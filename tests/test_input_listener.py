"""Input hooks are fully mocked: these tests never install a system hook."""

import ctypes
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch, call

import input_listener as listener


def fake_apis():
    user32, kernel32 = Mock(), Mock()
    user32.SetWindowsHookExW.return_value = 0x123456789
    user32.CallNextHookEx.return_value = 47
    user32.GetMessageW.return_value = 0
    kernel32.GetCurrentThreadId.return_value = 123
    return user32, kernel32


class WindowsMouseHookTests(unittest.TestCase):
    def hook(self, selected=None, active=lambda: True):
        user32, kernel32 = fake_apis()
        callback = Mock()
        hook = listener.WindowsMouseHook(selected or {'mouse:x1': 0}, callback,
                                         active=active, user32=user32, kernel32=kernel32)
        return hook, callback, user32, kernel32

    def test_only_selected_side_button_is_consumed_even_when_injected(self):
        hook, callback, user32, _ = self.hook()
        data = listener.MSLLHOOKSTRUCT()
        data.mouseData = 1 << 16
        data.flags = 1  # LLMHF_INJECTED: reWASD must remain usable.
        with patch.object(listener.time, 'monotonic', return_value=8.25):
            self.assertEqual(hook._handle_native(0, listener.WM_XBUTTONDOWN, ctypes.addressof(data)), 1)
            self.assertEqual(hook._handle_native(0, listener.WM_XBUTTONUP, ctypes.addressof(data)), 1)
        self.assertEqual(callback.call_args_list, [call('mouse:x1', True, 0, 8.25),
                                                  call('mouse:x1', False, 0, 8.25)])
        data.mouseData = 2 << 16
        self.assertEqual(hook._handle_native(0, listener.WM_XBUTTONDOWN, ctypes.addressof(data)), 47)
        self.assertEqual(callback.call_count, 2)

    def test_unrelated_or_negative_messages_do_not_dereference_pointer(self):
        hook, callback, user32, _ = self.hook()
        self.assertEqual(hook._handle_native(-1, listener.WM_XBUTTONDOWN, 0), 47)
        self.assertEqual(hook._handle_native(0, 0x0200, 0), 47)
        callback.assert_not_called()

    def test_hook_handle_and_callback_results_are_pointer_sized(self):
        hook, _, user32, _ = self.hook()
        self.assertEqual(ctypes.sizeof(user32.SetWindowsHookExW.restype), ctypes.sizeof(ctypes.c_void_p))
        self.assertEqual(ctypes.sizeof(user32.CallNextHookEx.restype), ctypes.sizeof(ctypes.c_void_p))
        self.assertEqual(ctypes.sizeof(listener.MSLLHOOKSTRUCT), 32 if ctypes.sizeof(ctypes.c_void_p) == 8 else 24)

    def test_successful_loop_unhooks_exact_handle_and_reports_ready(self):
        hook, _, user32, _ = self.hook()
        ready = Mock()
        hook.run(ready)
        ready.assert_called_once_with()
        user32.UnhookWindowsHookEx.assert_called_once_with(0x123456789)
        self.assertIsNone(hook._thread_id)
        self.assertIsNotNone(hook._native_callback)

    def test_stop_during_registration_unhooks_and_never_enters_loop(self):
        hook, _, user32, _ = self.hook()
        def install(*args):
            hook.stop()
            return 0x123456789
        user32.SetWindowsHookExW.side_effect = install
        ready = Mock()
        hook.run(ready)
        ready.assert_not_called()
        user32.GetMessageW.assert_not_called()
        user32.UnhookWindowsHookEx.assert_called_once_with(0x123456789)
        user32.PostThreadMessageW.assert_called_once_with(123, listener.WM_QUIT, 0, 0)

    def test_registration_error_is_reported_without_unhooking_invalid_handle(self):
        hook, _, user32, _ = self.hook()
        user32.SetWindowsHookExW.return_value = 0
        with self.assertRaisesRegex(OSError, '无法安装鼠标侧键监听'):
            hook.run()
        user32.UnhookWindowsHookEx.assert_not_called()

    def test_stop_before_registration_does_not_publish_stale_thread_id(self):
        hook, _, user32, _ = self.hook()
        hook.stop()
        hook.run()
        self.assertIsNone(hook._thread_id)
        user32.SetWindowsHookExW.assert_not_called()
        user32.PostThreadMessageW.assert_not_called()

    def test_failed_unhook_retains_callback_but_passes_all_input_through(self):
        hook, callback, user32, _ = self.hook()
        user32.UnhookWindowsHookEx.return_value = 0
        with patch.object(listener, '_retained_failed_hooks', []) as retained, \
                patch.object(listener.logging, 'error'):
            hook.run()
            self.assertEqual(retained, [hook])
            self.assertEqual(hook._handle_native(0, listener.WM_XBUTTONDOWN, 0), 47)
            callback.assert_not_called()

    def test_message_loop_failure_still_unhooks(self):
        hook, _, user32, _ = self.hook()
        user32.GetMessageW.return_value = -1
        with self.assertRaisesRegex(OSError, '鼠标监听消息循环失败'):
            hook.run()
        user32.UnhookWindowsHookEx.assert_called_once_with(0x123456789)

    def test_stopped_callback_passes_through(self):
        hook, callback, _, _ = self.hook()
        hook.stop()
        self.assertEqual(hook._handle_native(0, listener.WM_XBUTTONDOWN, 0), 47)
        callback.assert_not_called()


class InputListenerTests(unittest.TestCase):
    def test_snapshot_precedes_signal_and_consumes_each_equal_time_event_once(self):
        thread = listener.KeyListenerThread(['f23', 'f24'])
        wakeups = []
        thread.timedKeyEvent.connect(lambda *args: wakeups.append(thread.snapshot_events()))
        with patch.object(listener.time, 'monotonic', return_value=5):
            thread._emit_key('f23', True, 0, 4.9)
            thread._emit_key('f24', True, 1, 4.9)
            self.assertEqual(wakeups, [(5, [('f23', True, 0, 4.9)]),
                                       (5, [('f24', True, 1, 4.9)])])
            self.assertEqual(thread.snapshot_events(), (5, []))

    def test_snapshot_orders_observed_events_and_pairs_them_with_cutoff(self):
        thread = listener.KeyListenerThread(['f23', 'mouse:x1'])
        thread._emit_key('f23', True, 0, 9.2)
        thread._emit_key('mouse:x1', True, 1, 9.1)
        with patch.object(listener.time, 'monotonic', return_value=9.3):
            cutoff, events = thread.snapshot_events()
        self.assertEqual(cutoff, 9.3)
        self.assertEqual(events, [('mouse:x1', True, 1, 9.1), ('f23', True, 0, 9.2)])
        self.assertEqual(thread.snapshot_events()[1], [])

    def test_snapshot_racing_producer_never_loses_or_duplicates_events(self):
        thread = listener.KeyListenerThread(['f23'])
        ready = threading.Event()
        def produce():
            ready.wait()
            for index in range(200):
                thread._emit_key('f23', index % 2 == 0, 0, float(index))
        producer = threading.Thread(target=produce)
        producer.start()
        ready.set()
        received = []
        while producer.is_alive():
            received.extend(thread.snapshot_events()[1])
        producer.join()
        received.extend(thread.snapshot_events()[1])
        self.assertEqual([event[3] for event in received], list(map(float, range(200))))

    def test_stop_discards_queued_events_and_later_callbacks(self):
        thread = listener.KeyListenerThread(['f23'])
        thread._emit_key('f23', True, 0, 1)
        thread.stop()
        thread._emit_key('f23', False, 0, 2)
        self.assertEqual(thread.snapshot_events()[1], [])

    def test_f23_f24_and_mouse_roles_are_kept_in_mixed_binding(self):
        thread = listener.KeyListenerThread(['f23', 'mouse:x2', 'f24'])
        cleanups = [Mock(), Mock()]
        with patch.object(listener.keyboard, 'hook_key', side_effect=cleanups) as keyboard_hook, \
                patch.object(listener, 'WindowsMouseHook') as mouse_hook:
            thread.run()
        self.assertEqual([entry.args[0] for entry in keyboard_hook.call_args_list], ['f23', 'f24'])
        self.assertEqual(mouse_hook.call_args.args[0], {'mouse:x2': 1})
        for cleanup in cleanups:
            cleanup.assert_called_once_with()

    def test_keyboard_emits_original_monotonic_timestamp_and_accepts_rewasd(self):
        thread = listener.KeyListenerThread(['f24'])
        received = Mock()
        thread.timedKeyEvent.connect(received)
        event = SimpleNamespace(name='f24', event_type='down', is_keypad=False, injected=True)
        with patch.object(listener.time, 'monotonic', return_value=42.25):
            self.assertFalse(thread.on_key_event(event, 'f24', 0))
        received.assert_called_once_with('f24', True, 0, 42.25)

    def test_own_keyboard_replay_is_not_fed_back(self):
        thread = listener.KeyListenerThread(['space'])
        received = Mock()
        thread.timedKeyEvent.connect(received)
        event = SimpleNamespace(name='space', event_type='down', is_keypad=False)
        with patch.object(listener.keyboard._listener, 'is_replaying', True, create=True):
            self.assertTrue(thread.on_key_event(event, 'space', 0))
        received.assert_not_called()

    def test_start_failure_emits_error_and_releases_prior_hooks(self):
        thread = listener.KeyListenerThread(['f23', 'mouse:x1'])
        error, cleanup = Mock(), Mock()
        thread.listenerError.connect(error)
        with patch.object(listener.keyboard, 'hook_key', return_value=cleanup), \
                patch.object(listener, 'WindowsMouseHook', side_effect=RuntimeError('failed mouse hook')):
            with self.assertRaisesRegex(RuntimeError, 'failed mouse hook'):
                thread.run()
        error.assert_called_once_with('failed mouse hook')
        cleanup.assert_called_once_with()
        self.assertFalse(thread.keep_running)

    def test_real_qthread_start_failure_does_not_escape_run(self):
        thread = listener.KeyListenerThread(['f23'])
        with patch.object(listener.keyboard, 'hook_key', side_effect=RuntimeError('failed hook')), \
                patch.object(thread, 'isRunning', return_value=True), \
                patch.object(listener.logging, 'exception'):
            thread.run()
        self.assertEqual(thread.error, 'failed hook')


if __name__ == '__main__':
    unittest.main()
