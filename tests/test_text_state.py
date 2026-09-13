"""Retired candidate sequences cannot replace text or block the next input."""

from unittest import TestCase
from unittest.mock import call

import test_mapping_actions as mapping

class RemovedCandidateTests(TestCase):
    setUpClass = classmethod(mapping.MappingActionTests.setUpClass.__func__)
    setUp = mapping.MappingActionTests.setUp
    tearDown = mapping.MappingActionTests.tearDown
    start_input = mapping.MappingActionTests.start_input
    enter_code = mapping.MappingActionTests.enter_code

    def test_former_candidates_emit_nothing_and_next_letter_still_works(self):
        self.enter_code('12')
        self.assertEqual(self.backend.mock_calls, [call.send('a')])
        self.backend.reset_mock()
        for code in ('2211111', '2211112', '2211121', '2211122',
                     '2211211', '2211212', '2211221', '2211222'):
            with self.subTest(code=code):
                self.enter_code(code)
                self.assertEqual(self.backend.mock_calls, [])
                self.assertTrue(self.window.codeslayoutview.input_feedback.result_label._full_text.startswith('无效码：'))
        self.enter_code('2111')
        self.enter_code('1122')
        self.assertEqual(self.backend.mock_calls, [call.send('b'), call.send('space')])
