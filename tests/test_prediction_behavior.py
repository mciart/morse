"""Prediction count and replacement follow the displayed, actual word boundary."""

import configparser
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import call, patch

import test_mapping_actions as mapping

morse = mapping.morse


class PredictionConfigurationTests(TestCase):
    def test_real_predictor_has_eight_slots_and_completes_the_typed_prefix(self):
        project = Path(__file__).resolve().parents[1]
        config = configparser.ConfigParser()
        config.read(project / 'res/morsewriter_pressagio.ini')
        data = json.loads((project / 'user_data/layouts.json').read_text(encoding='utf-8'))
        targets = [i['target'] for i in data['layouts']['desktop']['items'] if i['action'] == 'PREDICTION_SELECT']
        self.assertEqual(config.getint('Selector', 'suggestions'), len(targets))
        with TemporaryDirectory() as temporary:
            database = Path(temporary) / 'predictions.sqlite'
            shutil.copyfile(project / 'res/morsewriter.sqlite', database)
            config.set('Database', 'database', str(database))
            config.set('DefaultSmoothedNgramPredictor', 'learn', 'False')
            state = morse.TypeState.__new__(morse.TypeState)
            state.text = ''
            state.predictions = None
            state.presage = morse.pressagio.Pressagio(state, config)
            try:
                self.assertEqual(len(state.getpredictions()), 8)
                state.pushstr('hel')
                words = state.getpredictions()
                self.assertTrue(words)
                self.assertTrue(all(word.casefold().startswith('hel') for word in words))
                self.assertEqual(state.past_stream(), 'hel')
                self.assertEqual(state.future_stream(), '')
                state.text = '(hel'
                state.predictions = None
                self.assertTrue(state.getpredictions())
                self.assertEqual(state.past_stream(), 'hel')
                self.assertEqual(state.text, '(hel')
            finally:
                state.presage.close_database()


class PredictionSelectionTests(TestCase):
    setUpClass = classmethod(mapping.MappingActionTests.setUpClass.__func__)
    setUp = mapping.MappingActionTests.setUp
    tearDown = mapping.MappingActionTests.tearDown
    start_input = mapping.MappingActionTests.start_input
    enter_code = mapping.MappingActionTests.enter_code
    select_page = mapping.MappingActionTests.select_page

    def test_selecting_prediction_preserves_punctuation_before_current_word(self):
        self.select_page('desktop')
        for prefix, expected_text, backspaces in (
            ('hello,wo', 'hello,world ', 2),
            ('hello,', 'hello,world ', 0),
            ('(wo', '(world ', 2),
        ):
            with self.subTest(prefix=prefix):
                self.window.typestate.text = prefix
                self.backend.reset_mock()
                with patch.object(self.window.typestate, 'getpredictions', return_value=['world']):
                    self.enter_code('2211111')
                self.assertEqual(self.window.typestate.text, expected_text)
                self.assertEqual(self.backend.mock_calls,
                                 [call.send('backspace')] * backspaces + [call.write('world ', exact=True)])

    def test_single_letter_prediction_keeps_its_case_and_empty_slot_sends_nothing(self):
        self.select_page('desktop')
        self.window.config['upperchars'] = True
        with patch.object(self.window.typestate, 'getpredictions', return_value=['a']):
            self.enter_code('2211111')
            self.assertEqual(self.backend.mock_calls, [call.write('a ', exact=True)])
            self.backend.reset_mock()
            self.enter_code('2211112')
            self.backend.assert_not_called()
            self.assertEqual(self.backend.mock_calls, [])
