"""Timing regressions use a virtual clock and cannot produce OS input."""

import unittest

from morse_engine import MorseEngine


def values(events, name, field):
    return [payload[field] for event, payload in events if event == name]


class MorseEngineTests(unittest.TestCase):
    def engine(self, **options):
        config = dict(keylen=2, keyer_mode='manual', wpm=15, minLetterPause=0)
        config.update(options)
        return MorseEngine(config)

    def test_straight_key_tone_starts_at_press_and_classifies_on_release(self):
        engine = self.engine(keylen=1)
        self.assertEqual(values(engine.key(0, True, 10), 'tone', 'on'), [True])
        released = engine.key(0, False, 10.08)
        self.assertEqual(values(released, 'tone', 'on'), [False])
        self.assertEqual(values(released, 'symbol', 'symbol'), [1])
        self.assertFalse(values(engine.tick(10.319), 'commit', 'symbols'))
        self.assertEqual(values(engine.tick(10.32), 'commit', 'symbols'), [(1,)])
        engine.key(0, True, 11)
        self.assertEqual(values(engine.key(0, False, 11.16), 'symbol', 'symbol'), [2])

    def test_next_press_cancels_character_deadline_while_held(self):
        engine = self.engine(keylen=1)
        engine.key(0, True, 0)
        engine.key(0, False, .05)
        engine.key(0, True, .2)
        self.assertFalse(values(engine.tick(1), 'commit', 'symbols'))
        engine.key(0, False, 1.1)
        self.assertEqual(values(engine.tick(1.34), 'commit', 'symbols'), [(1, 2)])

    def test_manual_overlap_records_both_roles_and_waits_for_all_releases(self):
        engine = self.engine()
        self.assertEqual(values(engine.key(0, True, 0), 'symbol', 'symbol'), [1])
        self.assertEqual(values(engine.key(1, True, .01), 'symbol', 'symbol'), [2])
        engine.key(0, False, .02)
        self.assertFalse(values(engine.tick(1), 'commit', 'symbols'))
        engine.key(1, False, 1.1)
        self.assertEqual(values(engine.tick(1.34), 'commit', 'symbols'), [(1, 2)])

    def test_repeated_os_keydowns_and_unmatched_release_do_not_repeat_symbols(self):
        engine = self.engine()
        self.assertFalse(values(engine.key(0, False, 0), 'symbol', 'symbol'))
        engine.key(0, True, .1)
        self.assertFalse(values(engine.key(0, True, .2), 'symbol', 'symbol'))
        engine.key(0, False, .3)
        self.assertEqual(values(engine.tick(.6), 'commit', 'symbols'), [(1,)])

    def test_manual_sound_queue_has_standard_dot_dash_and_inner_space(self):
        engine = self.engine()
        events = engine.key(0, True, 0)
        events += engine.key(0, False, .01)
        events += engine.key(1, True, .02)
        events += engine.key(1, False, .03)
        events += engine.tick(.64)
        tone = [(data['on'], round(data['at'], 3)) for kind, data in events if kind == 'tone']
        self.assertEqual(tone, [(True, 0), (False, .08), (True, .16), (False, .4)])
        self.assertEqual(values(events, 'commit', 'symbols'), [(1, 2)])

    def test_three_key_confirmation_is_immediate_and_not_delayed_by_audio(self):
        engine = self.engine(keylen=3)
        engine.key(0, True, 0)
        engine.key(1, True, .001)
        events = engine.key(2, True, .002)
        self.assertEqual(values(events, 'commit', 'symbols'), [(1, 2)])
        self.assertEqual(values(events, 'tone', 'on'), [False])
        engine.key(2, False, .003)
        engine.key(0, False, .004)
        engine.key(1, False, .005)
        self.assertFalse(values(engine.tick(10), 'commit', 'symbols'))
        self.assertFalse(values(engine.tick(11), 'tone', 'on'))

    def test_three_key_does_not_automatically_commit(self):
        engine = self.engine(keylen=3)
        engine.key(0, True, 0)
        engine.key(0, False, .01)
        self.assertFalse(values(engine.tick(2), 'commit', 'symbols'))
        self.assertEqual(values(engine.key(2, True, 2.1), 'commit', 'symbols'), [(1,)])

    def test_iambic_holding_dot_has_standard_one_unit_marks_and_spaces(self):
        engine = self.engine(keyer_mode='iambic')
        events = engine.key(0, True, 0)
        events += engine.tick(.4)
        tone = [(data['on'], round(data['at'], 3)) for kind, data in events if kind == 'tone']
        self.assertEqual(tone, [(True, 0), (False, .08), (True, .16),
                               (False, .24), (True, .32), (False, .4)])
        self.assertEqual(values(events, 'symbol', 'symbol'), [1, 1, 1])

    def test_iambic_squeeze_alternates_with_dash_three_times_dot(self):
        engine = self.engine(keyer_mode='iambic')
        events = engine.key(0, True, 0)
        events += engine.key(1, True, .01)
        events += engine.tick(.64)
        self.assertEqual(values(events, 'symbol', 'symbol'), [1, 2, 1, 2])
        starts = [round(data['at'], 3) for kind, data in events if kind == 'tone' and data['on']]
        self.assertEqual(starts, [0, .16, .48, .64])

    def test_iambic_remembers_brief_opposite_tap_during_current_mark(self):
        engine = self.engine(keyer_mode='iambic')
        events = engine.key(1, True, 0)
        events += engine.key(1, False, .01)
        events += engine.key(0, True, .04)
        events += engine.key(0, False, .05)
        events += engine.tick(.64)
        self.assertEqual(values(events, 'symbol', 'symbol'), [2, 1])
        self.assertEqual(values(events, 'commit', 'symbols'), [(2, 1)])

    def test_iambic_new_press_during_character_gap_starts_immediately(self):
        engine = self.engine(keyer_mode='iambic')
        engine.key(0, True, 0)
        engine.key(0, False, .01)
        events = engine.key(1, True, .2)
        self.assertEqual(values(events, 'symbol', 'symbol'), [2])
        self.assertEqual(values(events, 'tone', 'on'), [False, True])
        self.assertFalse(values(engine.tick(.4), 'commit', 'symbols'))

    def test_reset_cancels_tone_repeat_memory_and_commit(self):
        for mode in ('manual', 'iambic'):
            with self.subTest(mode=mode):
                engine = self.engine(keyer_mode=mode)
                engine.key(0, True, 0)
                engine.key(1, True, .01)
                self.assertEqual(values(engine.reset(.02), 'tone', 'on'), [False])
                self.assertEqual(values(engine.tick(100), 'symbol', 'symbol'), [])
                self.assertEqual(engine.held, set())
                self.assertEqual(engine.symbols, [])

    def test_wpm_and_existing_timing_preferences_are_preserved(self):
        engine = self.engine(wpm=20, minLetterPause=1000, maxDitTime=350)
        self.assertAlmostEqual(engine.unit, .06)
        self.assertEqual(engine.character_gap, 1)
        self.assertEqual(engine.threshold, .35)
        standard = self.engine(wpm=20, character_gap_ms=0, minLetterPause=1000)
        self.assertAlmostEqual(standard.character_gap, .18)

    def test_straight_duration_uses_observed_time_even_after_delayed_qt_delivery(self):
        engine = self.engine(keylen=1)
        engine.tick(.1)
        engine.key(0, True, 0)
        engine.tick(.3)
        # Both events arrived late; the physical mark was still only 80 ms.
        self.assertEqual(values(engine.key(0, False, .08), 'symbol', 'symbol'), [1])

    def test_feedback_tracks_held_keys_and_character_progress(self):
        engine = self.engine(keylen=1)
        events = engine.key(0, True, 0)
        self.assertEqual(values(events, 'feedback', 'held'), [(0,)])
        self.assertEqual(values(events, 'feedback', 'sounding'), ['straight'])
        engine.key(0, False, .04)
        self.assertAlmostEqual(values(engine.tick(.16), 'feedback', 'progress')[0], .5)

    def test_suspend_does_not_generate_unbounded_repeat_backlog(self):
        engine = self.engine(keyer_mode='iambic')
        engine.key(0, True, 0)
        events = engine.tick(3600)
        self.assertIn('timing_overrun', values(events, 'reset', 'reason'))
        self.assertEqual(values(events, 'symbol', 'symbol'), [])
        self.assertEqual(values(events, 'tone', 'on'), [False])
        self.assertFalse(engine.tone)
        self.assertFalse(engine.held)

    def test_iambic_late_release_discards_potential_extra_element(self):
        engine = self.engine(keyer_mode='iambic')
        engine.key(0, True, 0)
        engine.tick(.165)  # UI timer has already emitted the next dot at .16.
        events = engine.key(0, False, .155)
        self.assertEqual(values(events, 'reset', 'reason'), ['late_input'])
        self.assertFalse(values(engine.tick(.6), 'commit', 'symbols'))
        self.assertFalse(engine.tone)
        self.assertEqual(values(engine.key(1, True, .7), 'symbol', 'symbol'), [2])

    def test_overrun_ignores_os_repeat_until_all_held_paddles_release(self):
        engine = self.engine(keyer_mode='iambic')
        engine.key(0, True, 0)
        engine.key(1, True, .01)
        engine.tick(2)
        self.assertFalse(values(engine.key(0, True, 2.01), 'symbol', 'symbol'))
        engine.key(0, False, 2.02)
        self.assertFalse(values(engine.key(1, True, 2.03), 'tone', 'on'))
        engine.key(1, False, 2.04)
        self.assertEqual(values(engine.key(0, True, 2.05), 'symbol', 'symbol'), [1])

    def test_late_release_retains_other_held_role_until_it_releases(self):
        engine = self.engine(keyer_mode='iambic')
        engine.key(0, True, 0)
        engine.key(1, True, .01)
        engine.tick(.165)
        events = engine.key(1, False, .155)
        self.assertEqual(values(events, 'feedback', 'blocked'), [(0,)])
        self.assertFalse(values(engine.key(0, True, .18), 'symbol', 'symbol'))
        engine.key(0, False, .2)
        self.assertEqual(values(engine.key(0, True, .3), 'symbol', 'symbol'), [1])

    def test_pause_reset_clears_safety_release_gate(self):
        engine = self.engine(keyer_mode='iambic')
        engine.key(0, True, 0)
        engine.tick(2)
        engine.reset(2.1)
        self.assertEqual(values(engine.key(0, True, 2.2), 'symbol', 'symbol'), [1])


if __name__ == '__main__':
    unittest.main()
