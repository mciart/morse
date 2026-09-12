"""Bundled defaults and writable preferences are isolated using temp trees."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import app_paths


class ApplicationPathTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.bundle = self.root / "installed read only assets"
        self.data = self.root / "local writable user data"
        self.legacy = self.root / "public legacy user data"
        self.defaults = dict(theme="system", withsound=True, keyer_mode="manual", keyone="SPACE")
        self.seeds = {
            "layouts.json": '{"layouts": [{"name": "desktop"}]}',
            "abbreviations_en.txt": "u\tyou\n",
        }
        (self.bundle / "defaults").mkdir(parents=True)
        for name, text in self.seeds.items():
            (self.bundle / "defaults" / name).write_text(text, encoding="utf-8")

    def bootstrap(self):
        return app_paths.bootstrap_assets(self.defaults, data_dir=self.data,
                                          resource_dir=self.bundle, legacy_dir=self.legacy)

    def test_source_and_frozen_paths_do_not_depend_on_current_working_directory(self):
        with patch.object(app_paths, "_SOURCE_ROOT", self.bundle), \
                patch.object(app_paths.sys, "frozen", False, create=True):
            self.assertEqual(app_paths.source_resource("res", "x.ini"), self.bundle / "res" / "x.ini")
            self.assertEqual(app_paths.user_data_dir(), self.bundle / "user_data")
        with patch.object(app_paths.sys, "frozen", True, create=True), \
                patch.object(app_paths.sys, "_MEIPASS", str(self.bundle), create=True), \
                patch.object(app_paths.sys, "platform", "win32"), \
                patch.dict(os.environ, {"LOCALAPPDATA": str(self.root / "local appdata")}):
            self.assertEqual(app_paths.source_resource("res/x.ini"), self.bundle / "res" / "x.ini")
            self.assertEqual(app_paths.user_data_dir(), self.root / "local appdata" / "MorseWriter" / "user_data")

    def test_first_run_uses_system_theme_defaults_without_a_word_database(self):
        # Personal files next to the build source must never seed preferences.
        (self.bundle / "user_data").mkdir()
        (self.bundle / "user_data" / "config.json").write_text('{"theme": "dark"}', encoding="utf-8")
        result = self.bootstrap()
        self.assertEqual(result, self.data)
        self.assertEqual(json.loads((self.data / "config.json").read_text(encoding="utf-8")), self.defaults)
        self.assertFalse((self.data / "morsewriter.sqlite").exists())
        self.assertEqual({path.name for path in self.data.iterdir()},
                         {'config.json', 'layouts.json', 'abbreviations_en.txt', app_paths.BOOTSTRAP_MARKER})

    def test_existing_preferences_and_custom_data_are_never_overwritten(self):
        self.data.mkdir()
        self.legacy.mkdir()
        originals = {
            "config.json": '{"theme": "dark", "withsound": false}',
            "layouts.json": "personal layout",
            "abbreviations_en.txt": "me\tmy phrase\n",
            "morsewriter.sqlite": "personal learned database",
        }
        for name, content in originals.items():
            (self.data / name).write_text(content, encoding="utf-8")
        (self.legacy / "config.json").write_text('{"theme": "light"}', encoding="utf-8")
        self.bootstrap()
        self.bootstrap()
        for name, content in originals.items():
            self.assertEqual((self.data / name).read_text(encoding="utf-8"), content)

    def test_legacy_migration_copies_only_small_preferences_and_abbreviations_once(self):
        self.legacy.mkdir()
        (self.legacy / "config.json").write_text(json.dumps({
            "theme": "dark", "fastMorseMode": True, "unrelated_secret": "never migrate",
        }), encoding="utf-8")
        (self.legacy / "abbreviations_en.txt").write_text("hi\t你好\n", encoding="utf-8")
        for name in ("layouts.json", "morsewriter.sqlite", "old.log", "other.txt"):
            (self.legacy / name).write_text("old personal file", encoding="utf-8")
        self.bootstrap()
        self.assertEqual(json.loads((self.data / "config.json").read_text(encoding="utf-8")),
                         {"theme": "dark", "fastMorseMode": True})
        self.assertEqual((self.data / "abbreviations_en.txt").read_text(encoding="utf-8"), "hi\t你好\n")
        self.assertFalse((self.data / "morsewriter.sqlite").exists())
        self.assertEqual((self.data / "layouts.json").read_text(encoding="utf-8"), self.seeds["layouts.json"])
        self.assertFalse((self.data / "old.log").exists())
        self.assertFalse((self.data / "other.txt").exists())
        (self.data / "config.json").unlink()
        self.bootstrap()
        self.assertEqual(json.loads((self.data / "config.json").read_text(encoding="utf-8")), self.defaults)

    def test_invalid_legacy_config_uses_defaults_and_does_not_import_abbreviations(self):
        self.legacy.mkdir()
        (self.legacy / "config.json").write_text("invalid JSON", encoding="utf-8")
        (self.legacy / "abbreviations_en.txt").write_text("u\told word\n", encoding="utf-8")
        with self.assertLogs(level="WARNING"):
            self.bootstrap()
        self.assertEqual(json.loads((self.data / "config.json").read_text(encoding="utf-8")), self.defaults)
        self.assertEqual((self.data / "abbreviations_en.txt").read_text(encoding="utf-8"), self.seeds["abbreviations_en.txt"])

    def test_source_seed_layout_is_supported_without_release_defaults_directory(self):
        source = self.root / "checkout"
        for name, relative in app_paths._SOURCE_SEEDS.items():
            target = source / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(self.seeds[name], encoding="utf-8")
        app_paths.bootstrap_assets(self.defaults, data_dir=self.data, resource_dir=source)
        self.assertEqual((self.data / "layouts.json").read_text(encoding="utf-8"), self.seeds["layouts.json"])
        self.assertFalse((self.data / "morsewriter.sqlite").exists())

    def test_missing_bundle_asset_does_not_publish_an_incomplete_first_run(self):
        (self.bundle / "defaults/abbreviations_en.txt").unlink()
        with self.assertRaises(FileNotFoundError):
            self.bootstrap()
        self.assertFalse((self.data / "config.json").exists())
        self.assertFalse((self.data / app_paths.BOOTSTRAP_MARKER).exists())
        self.assertFalse((self.data / "abbreviations_en.txt").exists())


if __name__ == "__main__":
    unittest.main()
