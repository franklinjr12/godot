"""Regression checks for configuration preservation and Windows key storage."""
import argparse
import importlib.util
import json
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
            with patch.object(ee, 'STATE', state), patch.object(ee, 'read_key', return_value=key), patch.object(ee, 'load_settings', return_value={'project': str(project)}), patch.object(ee, 'verify_android_templates'), patch.object(ee, 'configure_editor'):
                ee.configure(argparse.Namespace())
                first = cfg.read_text()
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
            self.assertTrue((project / 'android' / ('encrypted-' + ee.fingerprint(key)) / 'build/.gdignore').is_file())

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


if __name__ == '__main__':
    unittest.main()
