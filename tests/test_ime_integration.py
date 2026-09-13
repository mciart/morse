"""IME state/layer/output ordering with real Morse engine and simulated OS IO."""

from dataclasses import replace
from unittest.mock import Mock, call, patch

import test_pinyin_integration as pinyin
from guide_gesture import HoldTapGesture
from windows_ime import ImeState, ImeSetResult


class ImeIntegrationTests(pinyin.PinyinIntegrationTests):
    # Only collect the IME scenarios here; the base cases run in their own file.
    __unittest_skip__ = False

    def setUp(self):
        super().setUp()
        self.state = ImeState(foreground=10, focus=11, thread_id=12, process_id=13,
                              layout=0x08040804, ime_window=14, is_pinyin=True,
                              chinese=False, open_status=True, conversion=0)
        self.service = Mock(enabled=True, latest=self.state)
        self.service.target_matches.return_value = True
        self.service.request.side_effect = range(1, 100)
        self.window.ime_sync = self.service
        self.window.config['pinyin_ime_sync'] = True

    def external(self, chinese):
        self.service.latest = replace(self.state, chinese=chinese, conversion=int(chinese))
        self.window.imeStateChanged(self.service.latest)

    def complete_request(self, chinese, *, ok=True):
        self.service.latest = replace(self.state, chinese=chinese, conversion=int(chinese))
        self.window.imeRequestFinished(self.window._ime_request,
            ImeSetResult(ok, self.service.latest, '' if ok else 'mode_not_confirmed'))

    def hold(self):
        self.window.processGuideKey(True, self.now)
        self.now += .18
        self.window.processGestureEvents(self.window.layer_gesture.tick(self.now))

    def test_external_state_syncs_board_and_toggle_latch_without_a_write(self):
        self.window.layer_gesture = HoldTapGesture(mode='toggle')
        self.external(True)
        self.assertTrue(self.view.isPinyinMode())
        self.assertTrue(self.window.layer_gesture.layer_active)
        self.service.request.assert_not_called()
        self.external(False)
        self.assertFalse(self.view.isPinyinMode())
        self.assertFalse(self.window.layer_gesture.layer_active)
        self.service.request.assert_not_called()

    def test_hold_mode_double_tap_has_no_layer_or_ime_write(self):
        for down, offset in ((True, 0), (False, .04), (True, .1), (False, .14)):
            self.window.processGuideKey(down, self.now + offset)
            self.assertFalse(self.view.isPinyinMode())
        self.assertFalse(self.view.isVisible())
        self.service.request.assert_not_called()
        self.assertEqual(self.backend.mock_calls, [])

    def test_toggle_double_click_requests_ime_once_without_changing_guide_bounds(self):
        self.window.layer_gesture = HoldTapGesture(mode='toggle')
        self.window.config['pinyin_layer_mode'] = 'toggle'
        geometry, visible = self.view.geometry(), self.view.isVisible()
        for expected in (True, False):
            previous_calls = self.service.request.call_count
            for down, offset in ((True, 0), (False, .04), (True, .1)):
                self.window.processGuideKey(down, self.now + offset)
                self.assertEqual(self.service.request.call_count, previous_calls)
            self.window.processGuideKey(False, self.now + .14)
            self.assertEqual(self.service.request.call_count, previous_calls + 1)
            self.assertEqual(self.service.request.call_args.args[0], expected)
            self.assertEqual(self.view.isVisible(), visible)
            self.assertEqual(self.view.geometry(), geometry)
            self.complete_request(expected)
            self.assertEqual(self.view.isPinyinMode(), expected)
            self.assertEqual(self.window.layer_gesture.layer_active, expected)
            self.assertEqual(self.view.isVisible(), visible)
            self.assertEqual(self.view.geometry(), geometry)
            self.window.processGestureEvents(self.window.layer_gesture.tick(self.now + .6))
            self.assertEqual(self.service.request.call_count, previous_calls + 1)
            self.now += 1
        self.assertEqual(self.backend.mock_calls, [])

    def test_toggle_single_click_only_hides_guide_without_ime_request(self):
        self.window.layer_gesture = HoldTapGesture(mode='toggle')
        self.window.config['pinyin_layer_mode'] = 'toggle'
        self.external(True)
        geometry = self.view.geometry()
        self.window.processGuideKey(True, self.now)
        self.window.processGuideKey(False, self.now + .04)
        self.assertTrue(self.view.isVisible())
        self.window.processGestureEvents(self.window.layer_gesture.tick(self.now + .4))
        self.assertFalse(self.view.isVisible())
        self.assertTrue(self.view.isPinyinMode())
        self.assertTrue(self.window.layer_gesture.layer_active)
        self.assertEqual(self.view.geometry(), geometry)
        self.service.request.assert_not_called()
        self.assertEqual(self.backend.mock_calls, [])

    def test_toggle_single_then_morse_confirms_visibility_and_uses_current_ime_layer(self):
        self.window.config['pinyin_layer_mode'] = 'toggle'
        for chinese, text in ((False, 'o'), (True, 'a')):
            with self.subTest(chinese=chinese):
                self.window.layer_gesture = HoldTapGesture(mode='toggle')
                self.external(chinese)
                self.backend.reset_mock()
                visible, geometry = self.view.isVisible(), self.view.geometry()
                self.window.processGuideKey(True, self.now)
                self.window.processGuideKey(False, self.now + .04)
                self.assertEqual(self.view.isVisible(), visible)
                self.now += .08
                self.code('222')
                self.assertNotEqual(self.view.isVisible(), visible)
                self.assertEqual(self.view.isPinyinMode(), chinese)
                self.assertEqual(self.view.geometry(), geometry)
                self.assertEqual(self.backend.mock_calls, [call.send(text)])
                self.service.request.assert_not_called()
                self.now += 1

    def test_hold_requests_chinese_and_release_requests_english_once(self):
        self.hold()
        self.complete_request(True)
        self.window.processGuideKey(False, self.now + .1)
        self.complete_request(False)
        self.assertEqual([c.args[0] for c in self.service.request.call_args_list], [True, False])
        self.assertFalse(self.view.isPinyinMode())

    def test_release_supersedes_unconfirmed_enter_even_if_old_snapshot_was_english(self):
        self.hold()
        old_serial = self.window._ime_request
        self.window.processGuideKey(False, self.now + .01)
        new_serial = self.window._ime_request
        self.assertNotEqual(old_serial, new_serial)
        self.assertEqual([c.args[0] for c in self.service.request.call_args_list], [True, False])
        self.window.imeRequestFinished(old_serial, ImeSetResult(True, replace(self.state, chinese=True)))
        self.assertEqual(self.window._ime_request, new_serial)
        self.complete_request(False)
        self.assertFalse(self.view.isPinyinMode())

    def test_early_morse_is_queued_until_chinese_is_confirmed_then_release_exits(self):
        self.window.processGuideKey(True, self.now)
        self.code('222')
        self.assertEqual(self.backend.mock_calls, [])
        self.assertEqual(len(self.window._ime_pending_codes), 1)
        self.window.processGuideKey(False, self.now)
        self.assertEqual(self.service.request.call_count, 1)
        self.complete_request(True)
        self.assertEqual(self.backend.mock_calls, [call.send('a')])
        self.assertEqual([c.args[0] for c in self.service.request.call_args_list], [True, False])
        self.complete_request(False)
        self.assertFalse(self.view.isPinyinMode())

    def test_unconfirmed_last_code_is_sent_before_exiting_ime_mode(self):
        self.hold()
        self.complete_request(True)
        for _ in range(3):
            self.window.processMorseKey(1, True, self.now)
            self.window.processMorseKey(1, False, self.now + .01)
            self.now += .03
        self.window.processGuideKey(False, self.now)
        self.assertEqual(self.service.request.call_count, 1)
        self.window.processMorseKey(2, True, self.now + .01)
        self.assertEqual(self.backend.mock_calls, [call.send('a')])
        self.assertEqual([c.args[0] for c in self.service.request.call_args_list], [True, False])

    def test_release_changes_next_code_layer_while_old_pinyin_waits_for_sync(self):
        self.window.processGuideKey(True, self.now)
        self.code('222')
        self.window.processGuideKey(False, self.now)
        self.assertFalse(self.view.isPinyinMode())
        self.code('222')
        self.assertEqual(self.backend.mock_calls, [])
        self.assertEqual([layer for _code, layer in self.window._ime_pending_codes], [True, False])
        self.complete_request(True)
        self.assertEqual(self.backend.mock_calls, [call.send('a')])
        self.complete_request(False)
        self.assertEqual(self.backend.mock_calls, [call.send('a'), call.send('o')])
        self.assertFalse(self.view.isPinyinMode())

    def test_stale_snapshot_uses_fresh_identity_at_request_time(self):
        self.service.target_matches.return_value = False
        self.hold()
        self.service.request.assert_called_once_with(True, None)

    def test_old_mode_readback_during_next_code_keeps_new_code_for_its_mode(self):
        self.window.processGuideKey(True, self.now)
        self.code('222')
        self.window.processGuideKey(False, self.now)
        self.window.processMorseKey(0, True, self.now + .01)
        self.window.processMorseKey(0, False, self.now + .02)
        self.complete_request(True)
        self.assertEqual(self.backend.mock_calls, [call.send('a')])
        self.window.processMorseKey(2, True, self.now + .03)
        self.assertIsNotNone(self.window._ime_request)
        self.complete_request(False)
        self.assertEqual(self.backend.mock_calls, [call.send('a'), call.send('e')])

    def test_settings_window_mode_is_not_mistaken_for_target_mode(self):
        import os
        self.window.imeStateChanged(replace(self.state, process_id=os.getpid(), chinese=True))
        self.assertFalse(self.view.isPinyinMode())
        self.service.request.assert_not_called()

    def test_engine_reset_finishes_deferred_english_mode_after_release(self):
        self.hold()
        self.complete_request(True)
        self.window.processMorseKey(0, True, self.now + .01)
        self.window.processGuideKey(False, self.now + .02)
        self.window.processEngineEvents([('reset', {'reason': 'timing_overrun'})])
        self.assertEqual([c.args[0] for c in self.service.request.call_args_list], [True, False])
        self.assertEqual(self.backend.mock_calls, [])

    def test_failed_sync_discards_buffer_without_sending_wrong_mode_text(self):
        self.window.processGuideKey(True, self.now)
        self.code('222')
        with patch.object(self.view, 'showMessage', wraps=self.view.showMessage) as message:
            self.complete_request(False, ok=False)
            self.assertIn('本次电码未发送', message.call_args.args[0])
        self.assertEqual(self.backend.mock_calls, [])
        self.assertEqual(self.window._ime_pending_codes, [])
        self.assertFalse(self.view.isPinyinMode())
        self.assertIn('同步失败', self.window.imeSyncStatus.text())

    def test_toggle_exit_rejected_with_pending_ime_candidates_restores_state_without_retry(self):
        # The native adapter reports that candidate composition prevented a
        # confirmed switch. There is no unfinished Morse character here.
        self.window.layer_gesture = HoldTapGesture(mode='toggle')
        self.window.config['pinyin_layer_mode'] = 'toggle'
        self.window.engine = pinyin.MorseEngine(dict(keylen=2, keyer_mode='manual', minLetterPause=0))
        self.external(True)
        listener = self.window.listenerThread
        geometry, visible = self.view.geometry(), self.view.isVisible()
        with patch.object(self.window.guide_key, 'snapshot_events', return_value=(
                self.now + .4, [(True, self.now), (False, self.now + .04),
                                (True, self.now + .1), (False, self.now + .14)])), \
             patch.object(listener, 'snapshot_events', return_value=(self.now + .4, [])):
            self.window.drainInput()
        self.assertFalse(self.view.isPinyinMode())
        self.assertEqual(self.view.isVisible(), visible)
        self.assertEqual(self.view.geometry(), geometry)
        self.assertIsNone(self.window._sequence_pinyin)
        self.assertEqual(self.window._ime_pending_codes, [])
        self.service.request.assert_called_once_with(False, self.service.latest)
        with self.assertLogs(level='WARNING') as logs, \
             patch.object(self.view, 'showMessage', wraps=self.view.showMessage) as message:
            self.window.imeRequestFinished(self.window._ime_request,
                ImeSetResult(False, self.service.latest, 'mode_not_confirmed'))
        self.assertTrue(self.view.isPinyinMode())
        self.assertTrue(self.window.layer_gesture.layer_active)
        self.assertEqual(self.view.isVisible(), visible)
        self.assertEqual(self.view.geometry(), geometry)
        self.assertIsNone(self.window._ime_request)
        self.assertIn('切换尚未确认', self.window.imeSyncStatus.text())
        self.assertNotIn('未发送', message.call_args.args[0])
        self.assertIn('reason=mode_not_confirmed', logs.output[0])
        self.assertIn('same_target=True', logs.output[0])
        self.assertIn('queued_codes=0', logs.output[0])
        self.window.processGestureEvents(self.window.layer_gesture.tick(self.now + 1))
        self.assertEqual(self.service.request.call_count, 1)
        # After the rejected double-click exit, a single click only hides the
        # guide and cannot retry the rejected input-method transition.
        with patch.object(self.window.guide_key, 'snapshot_events', return_value=(self.now + 2.5,
                [(True, self.now + 2), (False, self.now + 2.04)])), \
             patch.object(listener, 'snapshot_events', return_value=(self.now + 2.5, [])):
            self.window.drainInput()
        self.assertNotEqual(self.view.isVisible(), visible)
        self.assertTrue(self.window.layer_gesture.layer_active)
        self.assertEqual(self.view.geometry(), geometry)
        self.assertEqual(self.service.request.call_count, 1)
        self.assertEqual(self.backend.mock_calls, [])

    def test_sync_failure_feedback_distinguishes_target_permission_and_timeout(self):
        for reason, same_target, expected in (
                ('target_changed', False, '输入窗口已改变'),
                ('access_denied', True, '权限一致'),
                ('ime_timeout', True, '响应超时')):
            with self.subTest(reason=reason):
                self.service.target_matches.return_value = same_target
                self.window._ime_request = 1
                with self.assertLogs(level='WARNING') as logs, \
                     patch.object(self.view, 'showMessage', wraps=self.view.showMessage) as message:
                    self.window.imeRequestFinished(1, ImeSetResult(False, self.state, reason))
                self.assertIn(expected, self.window.imeSyncStatus.text())
                self.assertNotIn('未发送', message.call_args.args[0])
                self.assertIn('reason=' + reason, logs.output[0])
                self.assertIn('same_target=' + str(same_target), logs.output[0])

    def test_focus_change_before_readback_does_not_send_buffer_to_new_window(self):
        self.window.processGuideKey(True, self.now)
        self.code('222')
        self.service.target_matches.return_value = False
        self.complete_request(True)
        self.assertEqual(self.backend.mock_calls, [])
        self.assertEqual(self.window._ime_pending_codes, [])

    def test_external_mode_change_during_code_cannot_send_pinyin_as_english(self):
        self.external(True)
        self.window.processMorseKey(0, True, self.now)
        self.window.processMorseKey(0, False, self.now + .01)
        self.external(False)
        self.window.processMorseKey(2, True, self.now + .03)
        self.assertEqual(self.backend.mock_calls, [])
        self.assertFalse(self.view.isPinyinMode())


# Reuse fixture/helpers without running the base class's non-IME expectations.
for _name in dir(pinyin.PinyinIntegrationTests):
    if _name.startswith('test_') and _name not in ImeIntegrationTests.__dict__:
        setattr(ImeIntegrationTests, _name, None)
