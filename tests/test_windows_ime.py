"""No real window messages, input hooks or input-method changes."""

from dataclasses import FrozenInstanceError, replace
import unittest
from unittest.mock import patch

from windows_ime import (
    IMC_GETCONVERSIONMODE, IMC_GETOPENSTATUS, IMC_SETCONVERSIONMODE,
    IMC_SETOPENSTATUS, ImeState, ImeUnavailable, InputProfile,
    NativeImeBackend, PINYIN_CLSID, PINYIN_PROFILE, classify_pinyin,
)


PINYIN = InputProfile(1, 0x804, PINYIN_CLSID, PINYIN_PROFILE, enabled=True)
OTHER = replace(PINYIN, clsid='other', profile='other')
TARGET = ImeState(101, 102, 103, 104, 0x08040804, 105)


class FakeApi:
    def __init__(self):
        self.current = TARGET
        self.identity = ('', '')
        self.profile_list = (PINYIN,)
        self.opened = 1
        self.conversion = 0
        self.calls = []
        self.error = None
        self.write_error = None
        self.ignore_write = False
        self.after_write = None
        self.closed = False

    def target(self):
        return self.current

    def ime_identity(self, layout):
        return self.identity

    def profiles(self, language):
        return self.profile_list

    def close(self):
        self.closed = True

    def control(self, hwnd, command, value, timeout_ms):
        self.calls.append((hwnd, command, value, timeout_ms))
        if self.error:
            raise ImeUnavailable(self.error)
        if command == IMC_GETOPENSTATUS:
            return self.opened
        if command == IMC_GETCONVERSIONMODE:
            return self.conversion
        if self.write_error:
            raise ImeUnavailable(self.write_error)
        if not self.ignore_write:
            if command == IMC_SETOPENSTATUS:
                self.opened = value
            elif command == IMC_SETCONVERSIONMODE:
                self.conversion = value
        if self.after_write:
            self.after_write()
        return 0

    @property
    def writes(self):
        return [c for c in self.calls if c[1] in (IMC_SETOPENSTATUS, IMC_SETCONVERSIONMODE)]


class ImeIdentityTests(unittest.TestCase):
    def classify(self, profiles=(PINYIN,), layout=0x08040804, description='', filename=''):
        return classify_pinyin(layout, description, filename, profiles)[0]

    def test_generic_language_alone_is_not_enough(self):
        self.assertIsNone(self.classify(()))

    def test_single_enabled_pinyin_is_known(self):
        self.assertIs(self.classify(), True)

    def test_multiple_enabled_tips_remain_unknown(self):
        self.assertIsNone(self.classify((PINYIN, OTHER)))

    def test_disabled_other_tip_does_not_ambiguate(self):
        self.assertIs(self.classify((PINYIN, replace(OTHER, enabled=False))), True)

    def test_enabled_plain_chinese_keyboard_is_ambiguous(self):
        keyboard = InputProfile(2, 0x804, layout=0x08040804, enabled=True)
        self.assertIsNone(self.classify((PINYIN, keyboard)))

    def test_only_other_tip_is_not_pinyin(self):
        self.assertIs(self.classify((OTHER,)), False)

    def test_non_keyboard_tip_is_not_a_candidate(self):
        speech = replace(OTHER, category='speech')
        self.assertIs(self.classify((PINYIN, speech)), True)

    def test_identical_clsid_with_other_profile_is_not_pinyin(self):
        self.assertIs(self.classify((replace(PINYIN, profile='other'),)), False)

    def test_other_language_never_pinyin(self):
        self.assertIs(self.classify(layout=0x04090409), False)

    def test_unknown_chinese_hkl_is_not_generic(self):
        self.assertIsNone(self.classify(layout=0xe0010804))

    def test_unique_exact_substitute_can_identify_ime(self):
        self.assertIs(self.classify((replace(PINYIN, substitute=0xe0010804), OTHER),
                                   layout=0xe0010804), True)

    def test_shared_substitute_is_unknown(self):
        self.assertIsNone(self.classify((replace(PINYIN, substitute=0xe0010804),
                                        replace(OTHER, substitute=0xe0010804)),
                                       layout=0xe0010804))

    def test_legacy_ime_identity_is_not_just_language(self):
        self.assertIs(self.classify((), description='Microsoft Pinyin'), True)
        self.assertIs(self.classify((), filename=r'C:\Windows\System32\unknown.ime'), False)
        self.assertIs(self.classify((), description='Other Pinyin'), False)


class NativeImeBackendTests(unittest.TestCase):
    def setUp(self):
        self.api = FakeApi()
        self.backend = NativeImeBackend(self.api)

    def test_immutable_snapshot(self):
        state = self.backend.snapshot()
        with self.assertRaises(FrozenInstanceError):
            state.chinese = True
        self.assertEqual(state.target_key, TARGET.target_key)

    def test_english_and_chinese_are_open_and_native_combination(self):
        for opened, conversion, expected in ((1, 0, False), (1, 1, True), (0, 1, False),
                                             (0, 0, False), (1, 0x408, False), (1, 0x409, True)):
            self.api.opened, self.api.conversion = opened, conversion
            self.assertIs(self.backend.snapshot().chinese, expected)

    def test_unsupported_platform_has_no_native_calls(self):
        state = NativeImeBackend(platform_name='Linux').snapshot()
        self.assertIsNone(state.chinese)
        self.assertEqual(state.reason, 'unsupported')

    def test_no_focus_is_unknown(self):
        self.api.current = replace(TARGET, focus=0)
        self.assertEqual(self.backend.snapshot().reason, 'no_focus')
        self.assertEqual(self.api.calls, [])

    def test_missing_keyboard_layout_is_unknown(self):
        self.api.current = replace(TARGET, layout=0)
        state = self.backend.snapshot()
        self.assertIsNone(state.is_pinyin)
        self.assertEqual(state.reason, 'no_keyboard_layout')
        self.assertEqual(self.api.calls, [])

    def test_ambiguous_profile_does_not_query_ime(self):
        self.api.profile_list = (PINYIN, OTHER)
        self.assertIsNone(self.backend.snapshot().chinese)
        self.assertEqual(self.api.calls, [])

    def test_no_ime_window_is_unknown(self):
        self.api.current = replace(TARGET, ime_window=0)
        self.assertEqual(self.backend.snapshot().reason, 'no_ime_window')

    def test_timeout_is_unknown_not_english(self):
        self.api.error = 'ime_timeout'
        state = self.backend.snapshot()
        self.assertIsNone(state.chinese)
        self.assertEqual(state.reason, 'ime_timeout')

    def test_focus_change_during_read_invalidates_snapshot(self):
        targets = iter((TARGET, replace(TARGET, focus=999)))
        self.api.target = lambda: next(targets)
        state = self.backend.snapshot()
        self.assertIsNone(state.chinese)
        self.assertEqual(state.reason, 'target_changed')

    def test_invalid_native_results_are_unknown(self):
        self.api.opened = 10
        self.assertEqual(self.backend.snapshot().reason, 'invalid_open_status')
        self.api.opened, self.api.conversion = 1, 0xffffffffffffffff
        self.assertEqual(self.backend.snapshot().reason, 'invalid_conversion')

    def test_write_preserves_unrelated_conversion_flags(self):
        self.api.conversion = 0x408
        result = self.backend.set_chinese(self.backend.snapshot(), True)
        self.assertTrue(result.ok)
        self.assertEqual(self.api.writes, [(105, IMC_SETCONVERSIONMODE, 0x409, 60)])
        result = self.backend.set_chinese(result.state, False)
        self.assertTrue(result.ok)
        self.assertEqual(self.api.conversion, 0x409)
        self.assertFalse(self.api.opened)
        self.assertEqual(self.api.writes[-1], (105, IMC_SETOPENSTATUS, 0, 60))

    def test_exit_closes_composition_instead_of_changing_conversion_under_it(self):
        self.api.conversion = 0x401
        composition = ['nihao']
        committed = []
        control = self.api.control

        def candidate_control(hwnd, command, value, timeout):
            # Model the rejected conversion write reported with open candidates.
            if command == IMC_SETCONVERSIONMODE and composition:
                self.api.calls.append((hwnd, command, value, timeout))
                return 0
            result = control(hwnd, command, value, timeout)
            if command == IMC_SETOPENSTATUS and not value and composition:
                committed.append(composition.pop())
            return result

        self.api.control = candidate_control
        result = self.backend.set_chinese(self.backend.snapshot(), False)
        self.assertTrue(result.ok)
        self.assertFalse(result.state.chinese)
        self.assertEqual(committed, ['nihao'])
        self.assertEqual(composition, [])
        self.assertEqual(self.api.writes, [(105, IMC_SETOPENSTATUS, 0, 60)])

    def test_english_exit_accepts_pinyin_normalizing_open_state(self):
        self.api.conversion = 0x401
        def normalize():
            self.api.opened, self.api.conversion = 1, 0
        self.api.after_write = normalize
        result = self.backend.set_chinese(self.backend.snapshot(), False)
        self.assertTrue(result.ok)
        self.assertTrue(result.state.open_status)
        self.assertFalse(result.state.chinese)

    def test_ignored_english_exit_is_not_reported_as_success(self):
        self.api.conversion, self.api.ignore_write = 1, True
        result = self.backend.set_chinese(self.backend.snapshot(), False)
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, 'mode_not_confirmed')
        self.assertEqual(self.api.writes, [(105, IMC_SETOPENSTATUS, 0, 60)])

    def test_target_change_during_english_exit_never_reports_success(self):
        self.api.conversion = 1
        self.api.after_write = lambda: setattr(self.api, 'current', replace(TARGET, focus=999))
        result = self.backend.set_chinese(self.backend.snapshot(), False)
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, 'target_changed')
        self.assertEqual(self.api.writes, [(105, IMC_SETOPENSTATUS, 0, 60)])

    def test_already_correct_mode_does_not_write(self):
        result = self.backend.set_chinese(self.backend.snapshot(), False)
        self.assertTrue(result.ok)
        self.assertEqual(self.api.writes, [])

    def test_closed_ime_is_opened_before_native_mode(self):
        self.api.opened, self.api.conversion = 0, 0x408
        result = self.backend.set_chinese(self.backend.snapshot(), True)
        self.assertTrue(result.ok)
        self.assertEqual([c[1] for c in self.api.writes], [IMC_SETOPENSTATUS, IMC_SETCONVERSIONMODE])

    def test_closed_ime_is_already_english(self):
        self.api.opened, self.api.conversion = 0, 1
        self.assertTrue(self.backend.set_chinese(self.backend.snapshot(), False).ok)
        self.assertEqual(self.api.writes, [])

    def test_unconfirmed_mode_is_failure(self):
        self.api.ignore_write = True
        result = self.backend.set_chinese(self.backend.snapshot(), True)
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, 'mode_not_confirmed')

    def test_open_ignored_prevents_conversion_write(self):
        self.api.opened, self.api.ignore_write = 0, True
        result = self.backend.set_chinese(self.backend.snapshot(), True)
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, 'open_not_confirmed')
        self.assertEqual([c[1] for c in self.api.writes], [IMC_SETOPENSTATUS])

    def test_foreground_focus_layout_and_process_changes_cancel_write(self):
        for name in ('foreground', 'focus', 'thread_id', 'process_id', 'layout', 'ime_window'):
            with self.subTest(field=name):
                self.api.current = TARGET
                state = self.backend.snapshot()
                self.api.current = replace(TARGET, **{name: getattr(TARGET, name) + 1})
                result = self.backend.set_chinese(state, True)
                self.assertFalse(result.ok)
                self.assertEqual(result.reason, 'target_changed')
                self.assertEqual(self.api.writes, [])

    def test_profile_change_before_write_is_rechecked(self):
        state = self.backend.snapshot()
        self.api.profile_list = (OTHER,)
        result = self.backend.set_chinese(state, True)
        self.assertFalse(result.ok)
        self.assertEqual(self.api.writes, [])

    def test_focus_change_immediately_before_set_prevents_write(self):
        state = self.backend.snapshot()
        targets = iter((TARGET, TARGET, replace(TARGET, focus=999)))
        self.api.target = lambda: next(targets, replace(TARGET, focus=999))
        result = self.backend.set_chinese(state, True)
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, 'target_changed')
        self.assertEqual(self.api.writes, [])

    def test_focus_change_after_open_prevents_second_write(self):
        self.api.opened = 0
        self.api.after_write = lambda: setattr(self.api, 'current', replace(TARGET, focus=999))
        result = self.backend.set_chinese(self.backend.snapshot(), True)
        self.assertFalse(result.ok)
        self.assertEqual([c[1] for c in self.api.writes], [IMC_SETOPENSTATUS])

    def test_access_denied_does_not_report_success(self):
        self.api.write_error = 'access_denied'
        result = self.backend.set_chinese(self.backend.snapshot(), True)
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, 'access_denied')

    def test_timeout_is_bounded(self):
        self.backend.timeout_ms = 42
        self.backend.snapshot()
        self.assertTrue(all(c[-1] == 42 for c in self.api.calls))
        self.assertEqual(NativeImeBackend(self.api, timeout_ms=100000).timeout_ms, 200)

    def test_close_prevents_native_queries(self):
        self.backend.close()
        self.assertTrue(self.api.closed)
        self.assertEqual(self.backend.snapshot().reason, 'closed')
        self.assertEqual(self.api.calls, [])

    def test_target_guard_performs_no_messages_or_com(self):
        with patch('windows_ime.platform.system', return_value='Windows'), \
                patch('windows_ime._WindowsImeApi', return_value=self.api) as factory:
            self.assertTrue(NativeImeBackend.target_matches(TARGET))
            factory.assert_called_once_with(with_profiles=False)
        self.assertEqual(self.api.calls, [])

    def test_capture_target_is_identity_only_without_mode_query(self):
        with patch('windows_ime.platform.system', return_value='Windows'), \
                patch('windows_ime._WindowsImeApi', return_value=self.api) as factory:
            captured = NativeImeBackend.capture_target()
            self.assertEqual(captured.target_key, TARGET.target_key)
            self.assertIsNone(captured.is_pinyin)
            self.assertIsNone(captured.chinese)
            factory.assert_called_once_with(with_profiles=False)
        self.assertEqual(self.api.calls, [])

    def test_capture_without_focus_is_explicit_unknown(self):
        self.api.current = replace(TARGET, focus=0)
        with patch('windows_ime.platform.system', return_value='Windows'), \
                patch('windows_ime._WindowsImeApi', return_value=self.api):
            self.assertEqual(NativeImeBackend.capture_target().reason, 'no_focus')

    def test_capture_native_error_is_explicit_unknown(self):
        with patch('windows_ime.platform.system', return_value='Windows'), \
                patch('windows_ime._WindowsImeApi', side_effect=ImeUnavailable('focus_unavailable')):
            self.assertEqual(NativeImeBackend.capture_target().reason, 'focus_unavailable')

    def test_capture_unsupported_has_no_native_api(self):
        with patch('windows_ime.platform.system', return_value='Linux'), \
                patch('windows_ime._WindowsImeApi') as factory:
            self.assertEqual(NativeImeBackend.capture_target().reason, 'unsupported')
            factory.assert_not_called()

    def test_captured_identity_can_anchor_first_write(self):
        result = self.backend.set_chinese(TARGET, True)
        self.assertTrue(result.ok)
        self.assertIs(result.state.chinese, True)

    def test_captured_identity_rejects_delayed_write_after_focus_change(self):
        self.api.current = replace(TARGET, focus=999)
        result = self.backend.set_chinese(TARGET, True)
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, 'target_changed')
        self.assertEqual(self.api.writes, [])


if __name__ == '__main__':
    unittest.main()
