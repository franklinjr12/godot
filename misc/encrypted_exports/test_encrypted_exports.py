"""Regression checks for configuration preservation and Windows key storage."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import secrets
import tempfile
import unittest
from unittest.mock import patch
import zipfile

spec = importlib.util.spec_from_file_location('encrypted_exports', Path(__file__).with_name('encrypted_exports.py'))
ee = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ee)


class EncryptionSetupTests(unittest.TestCase):
    def test_child_environment_keeps_key_local_and_disables_persistent_gradle(self):
        key = secrets.token_hex(32)
        settings = {'java_home': 'C:/fixture/jdk', 'android_sdk': 'C:/fixture/sdk'}
        with patch.dict(os.environ, {'GRADLE_OPTS': '-Xmx64m'}):
            before = os.environ.copy()
            env = ee.environment(settings, key)
            self.assertEqual(env['SCRIPT_AES256_ENCRYPTION_KEY'], key)
            self.assertEqual(env['GODOT_SCRIPT_ENCRYPTION_KEY'], key)
            self.assertEqual(env['GRADLE_OPTS'], '-Xmx64m -Dorg.gradle.daemon=false')
            self.assertEqual(dict(os.environ), before)

    def test_dpapi_round_trip(self):
        key = secrets.token_bytes(32)
        protected = ee.dpapi(key)
        self.assertNotIn(key, protected)
        self.assertEqual(ee.dpapi(protected, True), key)

    def test_preserves_originals_and_regenerates_encrypted_presets(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            project = root / 'game'
            project.mkdir()
            state = root / '.encryption'
            state.mkdir()
            key = secrets.token_hex(32)
            dest = state / 'templates' / ee.fingerprint(key)
            dest.mkdir(parents=True)
            for name in ['windows-release.json', 'windows-debug.json', 'android-ready.json']:
                (dest / name).write_text('{}')
            for mode in ['release', 'debug']:
                (dest / f'windows_{mode}_x86_64.exe').touch()
            with zipfile.ZipFile(dest / 'android_source.zip', 'w') as archive:
                archive.writestr('libs/release/godot.aar', b'test fixture')
            fixture = ''
            for index, (name, platform) in enumerate([('Windows SteamVR Demo', 'Windows Desktop'), ('Android Quest Release', 'Android'), ('Linux', 'Linux')]):
                fixture += f'''[preset.{index}]
name="{name}"
platform="{platform}"
custom_features="demo,pcvr"
export_path="build/game.exe"
encrypt_pck=false
encrypt_directory=false
encryption_include_filters=""
encryption_exclude_filters=""
script_export_mode=2
[preset.{index}.options]
custom_template/debug=""
custom_template/release=""
gradle_build/gradle_build_directory=""
gradle_build/android_source_template=""
package/unique_name="unchanged.package"
'''
            cfg = project / 'export_presets.cfg'
            cfg.write_text(fixture)
            with patch.object(ee, 'STATE', state), patch.object(ee, 'read_key', return_value=key), patch.object(ee, 'load_settings', return_value={'project': str(project)}), patch.object(ee, 'verify_android_templates'), patch.object(ee, 'configure_editor'), patch.object(ee, 'protect_local'):
                ee.configure(argparse.Namespace())
                first = cfg.read_text()
                # A second machine has the tracked presets but no configured.json.
                (state / 'configured.json').unlink()
                ee.configure(argparse.Namespace())
                second = cfg.read_text()
            original_entries = [m.group(0).strip() for m in ee.split_presets(fixture)]
            resulting = ee.split_presets(second)
            self.assertEqual(len(resulting), 5)
            self.assertEqual([m.group(0).strip() for m in resulting[:3]], original_entries)
            self.assertEqual([m.group(1) for m in ee.split_presets(first)], [m.group(1) for m in resulting])
            self.assertNotIn(key, second)
            for entry in resulting[3:]:
                header, options = entry.group(2).split('[preset.', 1)
                self.assertIn('encrypt_pck=true', header)
                self.assertIn('encrypt_directory=true', header)
                self.assertIn('encryption_include_filters="*"', header)
                self.assertIn('custom_features="demo,pcvr"', header)
                self.assertIn('package/unique_name="unchanged.package"', options)
                self.assertNotIn('encrypt_pck=', options)
                self.assertIn('custom_template/debug="res://.encrypted-exports/templates/', options)
                self.assertNotIn(root.as_posix(), entry.group(2))
            self.assertTrue((project / 'android/encrypted/build/.gdignore').is_file())
            self.assertTrue((project / '.encrypted-exports/.gdignore').is_file())
            identifier = (project / 'android/encrypted/.build_version').read_text()
            self.assertTrue(identifier.startswith('res://.encrypted-exports/templates/android_source.zip ['))

    def test_machine_changes_paths_without_changing_key_or_configuration(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            state = root / '.encryption'
            state.mkdir()
            (state / 'key.dpapi').write_bytes(b'protected-original-key')
            project = root / 'Different machine game'
            project.mkdir()
            (project / 'project.godot').touch()
            sdk, java = root / 'SDK', root / 'Java'
            sdk.mkdir()
            (java / 'bin').mkdir(parents=True)
            (java / 'bin/java.exe').touch()
            settings = {'project': str(project), 'godot': str(root / 'Godot.exe'),
                        'android_sdk': str(sdk), 'java_home': str(java), 'jobs': 2}
            args = argparse.Namespace(**settings, android_source='')
            with patch.object(ee, 'STATE', state), patch.object(ee, 'protect_local'), patch.object(ee.subprocess, 'check_output', return_value='4.7.2.stable.official.test'):
                ee.machine(args)
            self.assertEqual((state / 'key.dpapi').read_bytes(), b'protected-original-key')
            self.assertEqual(json.loads((state / 'settings.json').read_text()), settings)

    def test_bundle_authentication_rejects_wrong_password_and_tampering(self):
        with tempfile.TemporaryDirectory() as folder:
            # Use installed dependencies, while keeping all cryptographic test data disposable.
            source_dependencies = ee.STATE / 'python-deps'
            import sys
            sys.path.insert(0, str(source_dependencies))
            with patch.object(ee, 'STATE', Path(folder)):
                payload = b'private binary fixture and game key'
                password = secrets.token_urlsafe(32)
                encrypted = ee.crypt_bundle(payload, password)
                self.assertNotIn(payload, encrypted)
                self.assertEqual(ee.crypt_bundle(encrypted, password, True), payload)
                with self.assertRaisesRegex(RuntimeError, 'password is incorrect'):
                    ee.crypt_bundle(encrypted, 'wrong password', True)
                damaged = encrypted[:-1] + bytes([encrypted[-1] ^ 1])
                with self.assertRaisesRegex(RuntimeError, 'password is incorrect'):
                    ee.crypt_bundle(damaged, password, True)

    def test_inherits_private_signing_from_original_preset(self):
        with tempfile.TemporaryDirectory() as folder:
            project = Path(folder)
            (project / '.godot').mkdir()
            (project / '.godot/export_credentials.cfg').write_text('[preset.7.options]\nkeystore/release="res://signing/test.keystore"\nkeystore/release_user="fixture-user"\nkeystore/release_password="fixture-password"\n')
            text = '[preset.7]\nname="Android Quest Release"\n[preset.7.options]\n\n[preset.12]\nname="Android Quest Release (Encrypted)"\n[preset.12.options]\n'
            env = {}
            ee.inherit_signing(project, 'Android Quest Release (Encrypted)', text, env)
            self.assertEqual(env['GODOT_ANDROID_KEYSTORE_RELEASE_PATH'], str(project / 'signing/test.keystore'))
            self.assertEqual(env['GODOT_ANDROID_KEYSTORE_RELEASE_USER'], 'fixture-user')
            self.assertEqual(env['GODOT_ANDROID_KEYSTORE_RELEASE_PASSWORD'], 'fixture-password')

    def test_bundle_rejects_unexpected_files_without_changing_active_key(self):
        with tempfile.TemporaryDirectory() as folder:
            state = Path(folder)
            original = b'protected-existing-key'
            (state / 'key.dpapi').write_bytes(original)
            import io
            archive_bytes = io.BytesIO()
            with zipfile.ZipFile(archive_bytes, 'w') as archive:
                archive.writestr('../escape', b'unexpected')
            with patch.object(ee, 'STATE', state):
                password = secrets.token_urlsafe(32)
                bundle = state / 'invalid.gdtbundle'
                bundle.write_bytes(ee.crypt_bundle(archive_bytes.getvalue(), password))
                with self.assertRaisesRegex(RuntimeError, 'Unexpected or missing'):
                    ee.restore_bundle(bundle, password)
            self.assertEqual((state / 'key.dpapi').read_bytes(), original)
            self.assertFalse((state.parent / 'escape').exists())


if __name__ == '__main__':
    unittest.main()
