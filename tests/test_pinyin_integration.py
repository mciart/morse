"""Real engine/view/output integration; all keyboard and audio IO is isolated."""

import time
import unittest
from unittest.mock import call, patch

import test_mapping_actions as mapping
from guide_gesture import HoldTapGesture
from morse_engine import MorseEngine

morse = mapping.morse


class PinyinIntegrationTests(unittest.TestCase):
    setUpClass = classmethod(mapping.MappingActionTests.setUpClass.__func__)
    tearDown = mapping.MappingActionTests.tearDown
    start_input = mapping.MappingActionTests.start_input

    def setUp(self):
        # These existing engine cases exercise temporary holds explicitly;
        # the application's first-run default is the separate toggle mode.
        with patch.dict(morse.DEFAULT_CONFIG, pinyin_layer_mode='hold'):
            mapping.MappingActionTests.setUp(self)
        self.window.engine_timer.stop()
        self.window.engine = MorseEngine(dict(keylen=3, keyer_mode='manual'))
        self.now = time.monotonic() + 1
        self.view = self.window.codeslayoutview

    def code(self, pattern):
        for symbol in pattern:
            role = int(symbol) - 1
            self.window.processMorseKey(role, True, self.now)
            self.window.processMorseKey(role, False, self.now + .01)
            self.now += .04
        self.window.processMorseKey(2, True, self.now)
        self.window.processMorseKey(2, False, self.now + .01)
        self.now += .04

    def test_same_code_outputs_english_then_pinyin_then_english(self):
        self.code('222')
        self.window.processGuideKey(True, self.now)
        self.window.processGestureEvents(self.window.layer_gesture.tick(self.now + .18))
        self.now += .18
        self.assertTrue(self.view.isPinyinMode())
        self.code('222')
        self.window.processGuideKey(False, self.now)
        self.assertFalse(self.view.isPinyinMode())
        self.code('222')
        self.assertEqual(self.backend.mock_calls, [call.send('o'), call.send('a'), call.send('o')])

    def test_complete_initial_and_final_reach_ime_as_latin_keys(self):
        self.window.processGuideKey(True, self.now)
        self.code('1111')  # ㄓ / zh
        self.code('221')   # ㄤ / ang
        self.assertEqual(self.backend.mock_calls, [call.send(c) for c in 'zhang'])
        self.assertIn('ang', self.view.input_feedback.result_label._full_text)

    def test_release_before_delayed_confirmation_keeps_sequence_layer(self):
        self.window.processGuideKey(True, self.now)
        for _ in range(3):
            self.window.processMorseKey(1, True, self.now)
            self.window.processMorseKey(1, False, self.now + .01)
            self.now += .04
        self.window.processGuideKey(False, self.now)
        self.assertFalse(self.view.isPinyinMode())
        self.window.processMorseKey(2, True, self.now + .01)
        self.assertEqual(self.backend.mock_calls, [call.send('a')])

    def test_straight_key_latches_layer_at_press_before_symbol_exists(self):
        self.window.engine = MorseEngine(dict(keylen=1, keyer_mode='manual'))
        self.window.processGuideKey(True, self.now)
        self.window.processMorseKey(0, True, self.now + .01)
        self.assertEqual(self.window.currentCharacter, [])
        self.window.processGuideKey(False, self.now + .03)
        self.window.processMorseKey(0, False, self.now + .07)
        self.window.processEngineEvents(self.window.engine.tick(self.now + .4))
        self.assertEqual(self.backend.mock_calls, [call.send('i')])  # ㄧ is dot, English is e.

    def test_double_tap_toggles_visibility_without_text_and_hold_input_cancels_it(self):
        original = self.view.geometry()
        for pressed, offset in ((True, 0), (False, .05), (True, .15), (False, .2)):
            self.window.processGuideKey(pressed, self.now + offset)
        self.assertFalse(self.view.isVisible())
        self.assertEqual(self.view.geometry(), original)
        self.assertEqual(self.backend.mock_calls, [])
        self.now += 1
        self.window.processGuideKey(True, self.now)
        self.code('222')
        self.window.processGuideKey(False, self.now)
        self.assertFalse(self.view.isVisible())
        self.assertEqual(self.backend.mock_calls, [call.send('a')])

    def test_batched_queues_use_timestamp_order_not_qt_delivery_order(self):
        listener = self.window.listenerThread
        events = [('x', down, role, self.now + offset) for offset, role, down in (
            (.02, 1, True), (.03, 1, False), (.06, 1, True), (.07, 1, False),
            (.10, 1, True), (.11, 1, False), (.20, 2, True), (.21, 2, False))]
        with patch.object(self.window.guide_key, 'snapshot_events',
                          return_value=(self.now + .3, [(True, self.now), (False, self.now + .15)])), \
             patch.object(listener, 'snapshot_events', return_value=(self.now + .3, events)):
            self.window.drainInput()
        self.assertEqual(self.backend.mock_calls, [call.send('a')])
        self.assertFalse(self.view.isPinyinMode())

    def test_cross_queue_cutoff_keeps_later_morse_until_layer_edge_arrives(self):
        listener = self.window.listenerThread
        with patch.object(self.window.guide_key, 'snapshot_events', side_effect=[
                (self.now + .05, []), (self.now + .15, [(True, self.now + .07)])]), \
             patch.object(listener, 'snapshot_events', side_effect=[
                (self.now + .10, [('x', True, 0, self.now + .08)]),
                (self.now + .15, [('x', False, 0, self.now + .12)])]):
            self.window.drainInput()
            self.assertEqual(self.window.currentCharacter, [])
            self.window.drainInput()
        self.window.processMorseKey(2, True, self.now + .2)
        self.assertEqual(self.backend.mock_calls, [call.send('i')])

    def test_toggle_single_confirms_visibility_before_morse_without_changing_layer(self):
        self.window.layer_gesture = HoldTapGesture(mode='toggle')
        self.window.config['pinyin_layer_mode'] = 'toggle'
        self.window.processGuideKey(True, self.now)
        self.window.processGuideKey(False, self.now + .04)
        self.assertFalse(self.view.isPinyinMode())
        self.assertTrue(self.view.isVisible())
        self.now += .08
        self.code('222')
        self.assertFalse(self.view.isVisible())
        self.assertFalse(self.view.isPinyinMode())
        self.assertEqual(self.backend.mock_calls, [call.send('o')])
        # A later double click changes the layer but leaves the guide hidden.
        self.now += 1
        for down, offset in ((True, 0), (False, .04), (True, .1), (False, .15)):
            self.window.processGuideKey(down, self.now + offset)
        self.assertFalse(self.view.isVisible())
        self.assertTrue(self.view.isPinyinMode())

    def test_toggle_double_click_changes_layer_without_visibility_or_geometry_change(self):
        self.window.layer_gesture = HoldTapGesture(mode='toggle')
        self.window.config['pinyin_layer_mode'] = 'toggle'
        original = self.view.geometry()
        visible = self.view.isVisible()
        for expected in (True, False):
            for down, offset in ((True, 0), (False, .04), (True, .1), (False, .14)):
                self.window.processGuideKey(down, self.now + offset)
                self.assertEqual(self.view.isVisible(), visible)
                self.assertEqual(self.view.geometry(), original)
            self.assertEqual(self.view.isPinyinMode(), expected)
            self.now += 1
        self.assertEqual(self.backend.mock_calls, [])

    def test_toggle_single_only_changes_visibility_after_double_click_window(self):
        self.window.layer_gesture = HoldTapGesture(mode='toggle')
        self.window.config['pinyin_layer_mode'] = 'toggle'
        original = self.view.geometry()
        self.window.processGuideKey(True, self.now)
        self.window.processGuideKey(False, self.now + .04)
        self.assertTrue(self.view.isVisible())
        self.window.processGestureEvents(self.window.layer_gesture.tick(self.now + .4))
        self.assertFalse(self.view.isVisible())
        self.assertFalse(self.view.isPinyinMode())
        self.assertFalse(self.window.layer_gesture.layer_active)
        self.assertEqual(self.view.geometry(), original)
        self.assertEqual(self.backend.mock_calls, [])

    def test_pause_clears_layer_and_blocks_held_key_until_release(self):
        self.window.processGuideKey(True, self.now)
        self.window.stopKeyListener()
        self.assertFalse(self.view.isPinyinMode())
        self.window.processGuideKey(True, self.now + .1)
        self.assertFalse(self.view.isPinyinMode())
        self.window.processGuideKey(False, self.now + .2)
        self.window.startKeyListener()
        self.window.engine_timer.stop()
        self.window.processGuideKey(True, self.now + .3)
        self.window.processGestureEvents(self.window.layer_gesture.tick(self.now + .5))
        self.assertTrue(self.view.isPinyinMode())

    def test_conflicting_control_code_is_specific_to_pinyin_layer(self):
        self.window.processGuideKey(True, self.now)
        self.code('1122')   # Old English Space; phonetic h.
        self.code('11121')  # Pinyin Space.
        self.assertEqual(self.backend.mock_calls, [call.send('h'), call.send('space')])

    def test_resume_clears_toggle_selected_while_paused(self):
        self.window.layer_gesture = HoldTapGesture(mode='toggle')
        self.window.config['pinyin_layer_mode'] = 'toggle'
        self.window.stopKeyListener()
        for down, offset in ((True, 0), (False, .04), (True, .1), (False, .14)):
            self.window.processGuideKey(down, self.now + offset)
        self.assertTrue(self.window.layer_gesture.layer_active)
        self.assertFalse(self.view.isPinyinMode())
        self.window.startKeyListener()
        self.window.engine_timer.stop()
        self.assertFalse(self.window.layer_gesture.layer_active)
        for down, offset in ((True, .5), (False, .54), (True, .6), (False, .64)):
            self.window.processGuideKey(down, self.now + offset)
        self.assertTrue(self.view.isPinyinMode())

    def test_rebinding_held_key_does_not_block_first_press_of_new_key(self):
        self.window.guide_key.key = 'F22'
        self.window.processGuideKey(True, self.now)
        self.window.config['pinyin_layer_key'] = 'F21'
        self.window._desktop_integration_started = True
        with patch.object(self.window.guide_key, 'set_key'), \
             patch.object(self.window.guide_hotkey, 'set_sequence'):
            self.window.applyGuideHotkey()
        self.assertFalse(self.window._layer_blocked)
        self.window.processGuideKey(True, self.now + .1)
        self.window.processGestureEvents(self.window.layer_gesture.tick(self.now + .3))
        self.assertTrue(self.view.isPinyinMode())


if __name__ == '__main__':
    unittest.main()
