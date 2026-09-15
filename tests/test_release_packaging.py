"""A release may contain reviewed defaults, never a developer's personal data."""

import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import unittest

from tools import build_release


class ReleaseResourceTests(unittest.TestCase):
    def test_manifest_contains_only_reviewed_defaults_and_original_license(self):
        items = build_release.resources()
        self.assertEqual({str(target) for _, target in items}, {
            'defaults/layouts.json',
            'version', 'LICENSE',
        })
        self.assertTrue(all('*' not in str(source) for source, _ in items))
        self.assertFalse(any(source.name in ('config.json', 'morsewriter-log.log') for source, _ in items))

    def test_version_normalization_and_invalid_version_rejection(self):
        with TemporaryDirectory() as directory:
            source = Path(directory) / 'version'
            for value, expected in (('VersionNumber=3.4', '3.4.0'),
                                    ('APP_VERSION=3.5.0', '3.5.0')):
                source.write_text(value, encoding='utf-8')
                self.assertEqual(build_release.read_version(source), expected)
            for value in ('VersionNumber=3.5.0-beta', 'APP_VERSION=1.2.65536',
                          'VersionNumber=3.5.0\nextra=1', '../3.5.0'):
                source.write_text(value, encoding='utf-8')
                with self.subTest(value=value), self.assertRaises(ValueError):
                    build_release.read_version(source)

    def test_manifest_rejects_personal_files_traversal_and_changed_learning_database(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'config.json').write_text('{}', encoding='utf-8')
            (root / 'private.log').write_text('private', encoding='utf-8')
            (root / 'words.sqlite').write_bytes(b'changed learned data')
            manifest = root / 'manifest.json'
            entries = [
                {'source': 'config.json', 'target': 'defaults/config.json'},
                {'source': 'private.log', 'target': 'private.log'},
                {'source': '../config.json', 'target': 'defaults/config.json'},
                {'source': 'words.sqlite', 'target': 'defaults/words.sqlite'},
                {'source': 'words.sqlite', 'target': 'defaults/words.sqlite', 'sha256': '0' * 64},
                {'source': 'words.sqlite', 'target': 'C:/outside/words.sqlite'},
            ]
            for entry in entries:
                manifest.write_text(json.dumps({'schema_version': 1, 'resources': [entry]}), encoding='utf-8')
                with self.subTest(entry=entry), self.assertRaises(ValueError):
                    build_release.resources(root, manifest)

    def test_bundle_audit_rejects_extra_configuration_logs_and_databases(self):
        with TemporaryDirectory() as directory:
            bundle = Path(directory) / 'MorseWriter'
            bundle.mkdir()
            (bundle / 'MorseWriter.exe').write_bytes(b'fake executable for resource audit')
            for source, target in build_release.resources():
                destination = bundle / '_internal' / target
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
            build_release.check_bundle(bundle)
            for extra in ('config.json', '_internal/private.log', '_internal/learned.db',
                          '_internal/res/extra.txt', '_internal/user_data/config.json'):
                path = bundle / extra
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('private', encoding='utf-8')
                with self.subTest(extra=extra), self.assertRaises(ValueError):
                    build_release.check_bundle(bundle)
                path.unlink()
            # The unexpected user_data directory remains and must still fail.
            with self.assertRaises(ValueError):
                build_release.check_bundle(bundle)


    def test_version_info_identifies_the_publisher(self):
        info = str(build_release.version_info('3.9.5'))
        self.assertIn('mciart', info)
        self.assertIn('摩斯输入', info)


if __name__ == '__main__':
    unittest.main()
