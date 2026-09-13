"""Isolated configuration recovery and failed-write regressions."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import config_store
from MorseCodeGUI import ConfigManager, DEFAULT_CONFIG


class ConfigStoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(TemporaryDirectory()))
        self.path = self.directory / 'config.json'
        self.original = json.dumps(dict(DEFAULT_CONFIG, theme='dark')).encode('utf-8')
        self.path.write_bytes(self.original)

    def test_non_object_json_recovers_without_rewriting(self):
        for data in (None, [], 'text', 123, False):
            with self.subTest(data=data):
                content = json.dumps(data)
                self.path.write_text(content, encoding='utf-8')
                with self.assertLogs(level='WARNING'):
                    config = ConfigManager(str(self.path)).config
                self.assertEqual(config, DEFAULT_CONFIG)
                self.assertEqual(self.path.read_text(encoding='utf-8'), content)

    def test_invalid_fields_recover_individually_and_keep_valid_preferences(self):
        values = dict(DEFAULT_CONFIG, theme='dark', keyone='F23', fontsizescale=None,
                      minLetterPause='bad', tone_volume=float('nan'), keylen=[],
                      show_mouse='false', pinyin_layer_mode={}, guide_positions=[],
                      guide_compact_scale=float('inf'), audio_device=None)
        self.path.write_text(json.dumps(values), encoding='utf-8')
        original = self.path.read_bytes()
        with self.assertLogs(level='WARNING'):
            config = ConfigManager(str(self.path)).config
        self.assertEqual(config['theme'], 'dark')
        self.assertEqual(config['keyone'], 'F23')
        for key in ('fontsizescale', 'minLetterPause', 'tone_volume', 'keylen',
                    'show_mouse', 'pinyin_layer_mode', 'guide_positions',
                    'guide_compact_scale', 'audio_device'):
            self.assertEqual(config[key], DEFAULT_CONFIG[key], key)
        self.assertEqual(self.path.read_bytes(), original)

    def test_out_of_range_and_boolean_numbers_are_rejected(self):
        values = dict(keylen=7, wpm=0, maxDitTime=-1, fontsizescale=True,
                      tone_frequency=1e100, tone_volume=-1, winposx=float('inf'))
        with self.assertLogs(level='WARNING'):
            config = config_store.normalize_config(values, DEFAULT_CONFIG)
        for key in values:
            self.assertEqual(config[key], DEFAULT_CONFIG[key], key)

    def test_valid_legacy_numbers_keys_and_mode_migrate(self):
        values = dict(fontsizescale='125', maxDitTime='350.5', keylen='2',
                      minLetterPause='1000', fastMorseMode=True, keyone='f23',
                      keytwo='MOUSE_X2', pinyin_layer_mode='hold')
        self.path.write_text(json.dumps(values), encoding='utf-8')
        config = ConfigManager(str(self.path)).config
        self.assertEqual(config['fontsizescale'], 125)
        self.assertEqual(config['maxDitTime'], 350.5)
        self.assertEqual(config['keylen'], 2)
        self.assertEqual(config['keyone'], 'F23')
        self.assertEqual(config['keytwo'], 'MOUSE_X2')
        self.assertEqual(config['keyer_mode'], 'iambic')
        self.assertEqual(config['pinyin_layer_mode'], 'hold')

    def test_unknown_input_key_uses_only_its_own_default(self):
        self.path.write_text(json.dumps(dict(keyone='missing', keytwo='F24', theme='dark')),
                             encoding='utf-8')
        with self.assertLogs(level='WARNING'):
            config = ConfigManager(str(self.path)).config
        self.assertEqual(config['keyone'], 'SPACE')
        self.assertEqual(config['keytwo'], 'F24')
        self.assertEqual(config['theme'], 'dark')

    def test_saved_positions_are_retained_and_defaults_are_not_shared(self):
        positions = {'compact': {'x': -1200, 'y': 40, 'screen': '屏幕二'}}
        config = config_store.normalize_config(dict(guide_positions=positions), DEFAULT_CONFIG)
        self.assertEqual(config['guide_positions'], positions)
        config['guide_positions']['compact']['x'] = 10
        self.assertEqual(positions['compact']['x'], -1200)

    def test_utf8_bom_and_chinese_device_names_are_supported(self):
        values = dict(DEFAULT_CONFIG, audio_device='扬声器（高清音频）')
        self.path.write_text(json.dumps(values, ensure_ascii=False), encoding='utf-8-sig')
        self.assertEqual(ConfigManager(str(self.path)).config, values)

    def test_invalid_nested_positions_and_legacy_values_cannot_block_saving(self):
        full = {'x': 20, 'y': 30, 'screen': '屏幕一', 'available': [0, 0, 1920, 1080]}
        values = dict(DEFAULT_CONFIG, guide_positions={
            'full': full, 'compact': {'x': float('nan'), 'y': 40}},
            old_extra={'bad': [float('inf')]})
        self.path.write_text(json.dumps(values), encoding='utf-8')
        with self.assertLogs(level='WARNING'):
            manager = ConfigManager(str(self.path))
        self.assertEqual(manager.config['guide_positions'], {'full': full})
        self.assertNotIn('old_extra', manager.config)
        self.assertTrue(manager.save_config(manager.config))

    def test_invalid_optional_screen_metadata_keeps_valid_coordinates(self):
        values = {'guide_positions': {'compact': {'x': 80, 'y': -20,
                  'screen': [], 'available': [0, 0, float('nan'), 100]}}}
        loaded = config_store.normalize_config(values, DEFAULT_CONFIG)
        self.assertEqual(loaded['guide_positions'], {'compact': {'x': 80, 'y': -20}})

    def test_missing_corrupt_and_unreadable_files_use_defaults(self):
        for content in ('{', '\xff'):
            self.path.write_bytes(content.encode('latin1'))
            with self.assertLogs(level='WARNING'):
                self.assertEqual(ConfigManager(str(self.path)).config, DEFAULT_CONFIG)
        with patch.object(config_store.Path, 'open', side_effect=PermissionError('denied')):
            with self.assertLogs(level='WARNING'):
                self.assertEqual(ConfigManager(str(self.path)).config, DEFAULT_CONFIG)
        self.path.unlink()
        self.assertEqual(ConfigManager(str(self.path)).config, DEFAULT_CONFIG)

    def test_successful_save_replaces_complete_utf8_and_updates_memory(self):
        manager = ConfigManager(str(self.path))
        values = dict(manager.config, audio_device='耳机', show_mouse=True)
        self.assertTrue(manager.save_config(values))
        self.assertEqual(json.loads(self.path.read_text(encoding='utf-8')), values)
        self.assertEqual(manager.config, values)
        self.assertIsNone(manager.last_save_error)
        self.assertEqual(list(self.directory.iterdir()), [self.path])

    def assert_failed_save_preserves_original(self, manager, values):
        before = dict(manager.config)
        with self.assertLogs(level='ERROR'):
            self.assertFalse(manager.save_config(values))
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertEqual(manager.config, before)
        self.assertTrue(manager.last_save_error)
        self.assertEqual(list(self.directory.iterdir()), [self.path])

    def test_serialization_failure_does_not_touch_the_original(self):
        manager = ConfigManager(str(self.path))
        for value in (object(), float('nan')):
            self.assert_failed_save_preserves_original(manager, dict(manager.config, extra=value))

    def test_flush_failure_preserves_original_and_removes_temporary_file(self):
        manager = ConfigManager(str(self.path))
        with patch.object(config_store.os, 'fsync', side_effect=OSError('disk full')):
            self.assert_failed_save_preserves_original(manager, dict(manager.config, theme='light'))

    def test_replace_failure_is_retryable_without_losing_preferences(self):
        manager = ConfigManager(str(self.path))
        values = dict(manager.config, theme='light')
        with patch.object(config_store.os, 'replace', side_effect=PermissionError('locked')):
            self.assert_failed_save_preserves_original(manager, values)
        self.assertTrue(manager.save_config(values))
        self.assertIsNone(manager.last_save_error)
        self.assertEqual(json.loads(self.path.read_text(encoding='utf-8')), values)


if __name__ == '__main__':
    unittest.main()
