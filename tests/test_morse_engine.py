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

    def test_first_mark_opens_audio_before_visual_symbol_in_both_modes(self):
        for mode in ('manual', 'iambic'):
            for role in (0, 1):
                with self.subTest(mode=mode, role=role):
                    engine = self.engine(keyer_mode=mode)
                    events = engine.key(role, True, 0)
                    self.assertEqual([kind for kind, _ in events[:2]], ['tone', 'symbol'])
                    self.assertTrue(events[0][1]['on'])
                    self.assertEqual(events[0][1]['at'], events[1][1]['at'])

    def test_iambic_squeeze_remembers_paddle_held_across_opposite_start(self):
        engine = self.engine(keyer_mode='iambic')
        events = engine.key(0, True, 0)
        events += engine.key(1, True, .01)
        events += engine.tick(.17)  # Dash starts at .16 while dot is still held.
        events += engine.key(0, False, .18)
        events += engine.key(1, False, .19)
        events += engine.tick(.9)
        self.assertEqual(values(events, 'symbol', 'symbol'), [1, 2, 1])
        self.assertEqual(values(events, 'commit', 'symbols'), [(1, 2, 1)])

    def test_iambic_same_paddle_retap_during_mark_does_not_latch_extra_element(self):
        engine = self.engine(keyer_mode='iambic')
        events = engine.key(0, True, 0)
        events += engine.key(0, False, .01)
        events += engine.key(0, True, .02)
        events += engine.key(0, False, .03)
        events += engine.tick(.4)
        self.assertEqual(values(events, 'symbol', 'symbol'), [1])
        self.assertEqual(values(events, 'commit', 'symbols'), [(1,)])

    def test_iambic_release_during_inner_space_keeps_exact_letter_gap(self):
        engine = self.engine(keyer_mode='iambic')
        engine.key(0, True, 0)
        engine.key(0, False, .15)  # Tone ended at .08, next element would start at .16.
        self.assertFalse(values(engine.tick(.319), 'commit', 'symbols'))
        events = engine.tick(.32)
        self.assertEqual(values(events, 'commit', 'symbols'), [(1,)])
        self.assertEqual(values(events, 'commit', 'at'), [.32])

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

    def test_idle_ticks_emit_only_initial_feedback(self):
        engine = self.engine()
        first = engine.tick(0)
        self.assertEqual([kind for kind, _ in first], ['feedback'])
        self.assertEqual(values(first, 'feedback', 'at'), [0])
        for index in range(1, 501):
            self.assertEqual(engine.tick(index * .002), [])

    def test_each_explicit_reset_forces_feedback_even_when_already_idle(self):
        engine = self.engine()
        engine.tick(0)
        for timestamp in (1, 2):
            events = engine.reset(timestamp)
            self.assertEqual([kind for kind, _ in events], ['reset', 'feedback'])
            self.assertEqual(values(events, 'feedback', 'at'), [timestamp])
            self.assertEqual(engine.tick(timestamp + .1), [])

    def test_feedback_changes_with_progress_without_changing_commit_deadline(self):
        engine = self.engine(keylen=1)
        engine.key(0, True, 0)
        self.assertEqual(engine.tick(.02), [])  # Still held and sounding.
        engine.key(0, False, .04)
        self.assertEqual(engine.tick(.04), [])  # Same progress as release.
        events = engine.tick(.16)
        self.assertAlmostEqual(values(events, 'feedback', 'progress')[0], .5)
        self.assertEqual(engine.tick(.16), [])
        self.assertFalse(values(engine.tick(.279), 'commit', 'symbols'))
        committed = engine.tick(.28)
        self.assertEqual(values(committed, 'commit', 'symbols'), [(1,)])
        self.assertAlmostEqual(values(committed, 'commit', 'at')[0], .28)
        self.assertEqual(values(committed, 'feedback', 'symbols'), [()])
        self.assertEqual(engine.tick(.3), [])

    def test_iambic_tone_boundaries_still_emit_feedback_at_exact_times(self):
        engine = self.engine(keyer_mode='iambic')
        events = engine.key(0, True, 0)
        self.assertEqual(engine.tick(.04), [])
        ended = engine.tick(.08)
        self.assertEqual(values(ended, 'feedback', 'tone'), [False])
        self.assertEqual(engine.tick(.1), [])
        started = engine.tick(.16)
        self.assertEqual(values(started, 'feedback', 'tone'), [True])
        self.assertEqual(values(started, 'feedback', 'symbols'), [(1, 1)])
        events += ended + started
        tone = [(data['on'], data['at']) for kind, data in events if kind == 'tone']
        self.assertEqual(tone, [(True, 0), (False, .08), (True, .16)])

    def test_callback_receives_same_events_in_order_without_idle_duplicates(self):
        received = []
        engine = MorseEngine(dict(keylen=1), callback=lambda kind, data: received.append((kind, data)))
        operations = (lambda: engine.tick(0), lambda: engine.tick(.01),
                      lambda: engine.key(0, True, .02), lambda: engine.tick(.03),
                      lambda: engine.key(0, False, .04), lambda: engine.tick(.28),
                      lambda: engine.reset(.3))
        for operation in operations:
            received.clear()
            events = operation()
            self.assertEqual(received, events)
        self.assertEqual([kind for kind, _ in received], ['reset', 'feedback'])

    def test_consumers_cannot_mutate_cached_feedback(self):
        engine = self.engine()
        initial = engine.tick(0)
        initial[0][1]['held'] = (1,)
        initial[0][1]['progress'] = .5
        self.assertEqual(engine.tick(.1), [])

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
