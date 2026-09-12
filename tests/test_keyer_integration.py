"""Trace actual listener signals through decoding, feedback and mock output."""

import json
from pathlib import Path
import time
import unittest
from unittest.mock import Mock, call, patch

import test_mapping_actions as mapping
from morse_engine import MorseEngine

morse = mapping.morse


class KeyerIntegrationTests(unittest.TestCase):
    setUpClass = classmethod(mapping.MappingActionTests.setUpClass.__func__)
    tearDown = mapping.MappingActionTests.tearDown
    start_input = mapping.MappingActionTests.start_input

    def setUp(self):
        mapping.MappingActionTests.setUp(self)
        self.window.engine_timer.stop()
        self.window.changeLayout('desktop')
        self.views.append(self.window.codeslayoutview)
        self.now = time.monotonic() + .1
        self.window.audio.configure(enabled=True)

    def engine(self, count, mode='manual'):
        self.window.engine = MorseEngine(dict(keylen=count, keyer_mode=mode,
                                             wpm=15, minLetterPause=0, maxDitTime=0))

    def key(self, role, down, offset):
        self.window.listenerThread._emit_key(
            ('f23', 'mouse:x2', 'right ctrl')[role], down, role, self.now + offset)

    def tick(self, offset):
        self.window.processEngineEvents(self.window.engine.tick(self.now + offset))

    def test_overlapping_buttons_reach_output_and_share_audio_visual_timing(self):
        self.engine(2)
        self.key(0, True, 0)
        self.key(1, True, .02)
        panel = self.window.codeslayoutview.input_feedback
        self.assertEqual(panel._roles, frozenset(('dot', 'dash')))
        self.assertEqual(panel._sounding, 'dot')
        self.assertTrue(self.window.audio.renderer.tone)
        self.key(0, False, .04)
        self.key(1, False, .06)
        self.assertEqual(self.window.currentCharacter, [1, 2])
        self.tick(.16)
        self.assertEqual(panel._sounding, 'dash')
        self.tick(.40)
        self.assertFalse(self.window.audio.renderer.tone)
        self.tick(.60)
        self.assertGreater(panel.progress.value(), 700)
        self.tick(.65)
        self.assertEqual(self.backend.mock_calls, [call.send('a')])
        self.assertIn('a', panel.result_label._full_text)
        self.assertEqual(self.window.currentCharacter, [])
        self.tick(20)
        self.assertEqual(len(self.backend.mock_calls), 1)  # No implicit Space.

    def test_new_straight_press_can_commit_previous_letter_and_start_tone(self):
        self.engine(1)
        self.key(0, True, 0)
        self.assertTrue(self.window.audio.renderer.tone)
        self.key(0, False, .06)
        self.assertFalse(self.window.audio.renderer.tone)
        # No timer tick in between: this press both commits E and starts T.
        self.key(0, True, .31)
        self.assertEqual(self.backend.mock_calls, [call.send('e')])
        self.assertTrue(self.window.audio.renderer.tone)
        self.assertEqual(self.window.codeslayoutview.input_feedback._sounding, 'straight')
        self.key(0, False, .55)
        self.tick(.80)
        self.assertEqual(self.backend.mock_calls,
                         [call.send('e'), call.send('t')])

    def test_explicit_commit_stops_queued_audio_and_invalid_code_is_visible(self):
        self.engine(3)
        for index in range(8):
            self.key(0, True, index * .002)
            self.key(0, False, index * .002 + .001)
        self.key(2, True, .02)
        self.assertFalse(self.window.audio.renderer.tone)
        self.assertEqual(self.window.currentCharacter, [])
        self.assertEqual(self.backend.mock_calls, [])
        result = self.window.codeslayoutview.input_feedback.result_label._full_text
        self.assertTrue(result.startswith('无效码：'))
        self.assertEqual(result.count('无效码'), 1)
        self.tick(.5)
        self.assertFalse(self.window.audio.renderer.tone)

    def test_rare_keyboard_and_mouse_bindings_round_trip_as_input_only(self):
        first, second = self.window.iconComboBoxKeyOne, self.window.iconComboBoxKeyTwo
        self.window.keySelectionRadioTwoKey.setChecked(True)
        for number in range(13, 25):
            self.assertGreaterEqual(first.findData(f'F{number}'), 0)
        for a, b, expected in (('F23', 'F24', ['f23', 'f24']),
                                ('MOUSE_X1', 'MOUSE_X2', ['mouse:x1', 'mouse:x2'])):
            first.setCurrentIndex(first.findData(a))
            second.setCurrentIndex(second.findData(b))
            self.window.saveSettings()
            self.assertEqual(self.window.get_configured_keys(), expected)
            saved = json.loads(Path(self.window.configManager.config_file).read_text())
            self.assertEqual((saved['keyone'], saved['keytwo']), (a, b))
        self.assertEqual(len(self.window.codeslayoutview.crs), 137)

    def test_pause_releases_sound_and_queued_previous_session_input_is_ignored(self):
        self.engine(1)
        self.key(0, True, 0)
        old_time = self.window.input_started_at
        self.window.stopKeyListener()
        self.assertFalse(self.window.audio.renderer.tone)
        self.assertEqual(self.window.currentCharacter, [])
        self.window.startKeyListener()
        self.window.engine_timer.stop()
        self.window.handle_key_event('f23', True, 0, old_time - 1)
        self.assertEqual(self.window.engine.held, set())
        self.assertFalse(self.window.audio.renderer.tone)

    def test_audio_settings_keep_native_output_and_errors_are_visible_in_settings(self):
        output = Mock()
        self.window.audio._output = output
        self.window.toneFrequencyEdit.setValue(720)
        self.window.toneVolumeEdit.setValue(42)
        self.assertIs(self.window.audio._output, output)
        output.stop.assert_not_called()
        self.assertEqual(self.window.audio.renderer.frequency, 720)
        self.assertEqual(self.window.audio.renderer.volume, .42)
        self.window.audio.error.emit('测试设备已断开')
        self.assertEqual(self.window.audioSelector.status_label.text(), '测试设备已断开')
        self.assertEqual(self.window.codeslayoutview.input_feedback.result_label._full_text,
                         '音频不可用：测试设备已断开')

    def test_registration_error_returns_to_settings_without_a_live_listener(self):
        with patch.object(morse.QMessageBox, 'warning') as warning:
            self.window.listenerThread.listenerError.emit('侧键监听不可用')
        warning.assert_called_once()
        self.assertIsNone(self.window.listenerThread)
        self.assertFalse(self.window.engine_timer.isActive())
        self.assertFalse(self.window.audio.renderer.tone)
        self.assertTrue(self.window.isVisible())

    def test_timer_consumes_queued_release_before_starting_another_automatic_dot(self):
        self.engine(2, 'iambic')
        self.key(0, True, 0)
        listener = self.window.listenerThread
        # Simulate a native release whose Qt notification has not run yet.
        listener.blockSignals(True)
        listener._emit_key('f23', False, 0, self.now + .155)
        listener.blockSignals(False)
        with patch('input_listener.time.monotonic', return_value=self.now + .165):
            self.window.advanceEngine()
        self.assertEqual(self.window.currentCharacter, [1])
        self.tick(.5)
        self.assertEqual(self.backend.mock_calls, [call.send('e')])

    def test_failed_modifier_release_does_not_interrupt_application_cleanup(self):
        self.window.key_output.send('ctrl', modifier=True)
        self.backend.release.side_effect = OSError('device release failed')
        with self.assertLogs(level='ERROR'):
            self.window.shutdown()
        self.assertIsNone(self.window.listenerThread)
        self.assertIsNone(self.window.typestate)
        self.assertIsNone(self.window.codeslayoutview)
        self.assertFalse(self.window.engine_timer.isActive())
        self.assertTrue(self.window.audio._closed)


if __name__ == '__main__':
    unittest.main()
