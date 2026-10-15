"""Portable, key-aware export templates for Godot 4.7.2 on Windows."""
import argparse
import configparser
import ctypes
from ctypes import wintypes
import getpass
import hashlib
import io
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import zipfile

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / '.encryption'
PIN = 'ed1daf0bf001b61586d9930840f2f1394092c079'
SUFFIX = ' (Encrypted)'
TEMPLATE_FILES = [
    'windows_debug_x86_64.exe', 'windows_release_x86_64.exe',
    'windows_debug_x86_64.console.exe', 'windows_release_x86_64.console.exe',
    'D3D12Core.dll', 'd3d12SDKLayers.dll', 'windows-debug.json', 'windows-release.json',
    'android_debug.apk', 'android_release.apk', 'android_source.zip',
    'android-debug.json', 'android-release.json', 'android-ready.json',
]
BUNDLE_MAGIC = b'GODOT-TEMPLATES\x01'
LICENSE_FILES = ['LICENSE.txt', 'COPYRIGHT.txt', 'D3D12-LICENSE.txt', 'D3D12-LICENSE-CODE.txt']


def run(args, cwd=ROOT, env=None):
    subprocess.run([str(a) for a in args], cwd=cwd, env=env, check=True)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
    temp.replace(path)


def dpapi(data, decrypt=False):
    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]
    buf = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
    result = Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    if decrypt:
        ok = crypt.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result))
    else:
        ok = crypt.CryptProtectData(ctypes.byref(source), 'Godot export key', None, None, None, 1, ctypes.byref(result))
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(result.data, result.size)
    finally:
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree(result.data)


def read_key():
    key = dpapi((STATE / 'key.dpapi').read_bytes(), True).decode('ascii')
    if not re.fullmatch('[0-9a-f]{64}', key):
        raise RuntimeError('Saved key is invalid.')
    return key


def fingerprint(key):
    return hashlib.sha256(bytes.fromhex(key)).hexdigest()[:16]


def load_settings():
    if not (STATE / 'settings.json').is_file():
        raise RuntimeError('Configure this machine first: menu 6 or the machine command.')
    return json.loads((STATE / 'settings.json').read_text(encoding='utf-8'))


def environment(settings, key):
    env = os.environ.copy()
    env['SCRIPT_AES256_ENCRYPTION_KEY'] = key
    env['GODOT_SCRIPT_ENCRYPTION_KEY'] = key
    env['ANDROID_HOME'] = settings['android_sdk']
    env['JAVA_HOME'] = settings['java_home']
    env['PATH'] = os.pathsep.join([str(Path(sys.executable).parent), str(Path(settings['java_home']) / 'bin'), env['PATH']])
    # A persistent Gradle daemon can inherit the Windows console wrapper's pipes
    # and keep it alive after Godot exits. Use a single-use daemon for exports.
    env['GRADLE_OPTS'] = (env.get('GRADLE_OPTS', '') + ' -Dorg.gradle.daemon=false').strip()
    return env


def check_pin():
    if not (ROOT / 'version.py').is_file() or not (ROOT / '.git').exists():
        raise RuntimeError('Rebuilding requires a full Godot fork clone. The release launcher supports import/export without engine sources.')
    sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    # Setup commits may be descendants of the pinned release; never build another engine version.
    version = (ROOT / 'version.py').read_text()
    if not all(re.search(rf'^{name} = {value}$', version, re.M) for name, value in [('major', '4'), ('minor', '7'), ('patch', '2')]):
        raise RuntimeError('This setup requires Godot 4.7.2.')
    run(['git', 'merge-base', '--is-ancestor', PIN, sha])


def protect_local(*directories):
    STATE.mkdir(exist_ok=True)
    sid = subprocess.check_output(['whoami', '/user', '/fo', 'csv', '/nh'], text=True).strip().split(',')[-1].strip('"')
    for directory in directories:
        run(['icacls', directory, '/inheritance:r', '/grant:r', f'*{sid}:(OI)(CI)F', '*S-1-5-18:(OI)(CI)F'])


def machine(args):
    """Change only this machine's paths; never rotate its encryption key."""
    previous = load_settings() if (STATE / 'settings.json').is_file() else {}
    detected = {'java_home': os.environ.get('JAVA_HOME', ''),
                'android_sdk': os.environ.get('ANDROID_HOME', os.environ.get('ANDROID_SDK_ROOT', '')),
                'godot': shutil.which('godot') or ''}
    labels = {'project': 'Game project folder', 'godot': 'Godot 4.7.2 executable',
              'android_sdk': 'Android SDK folder', 'java_home': 'JDK 17 folder',
              'android_source': 'Optional separate Android engine checkout (blank uses this checkout)'}
    settings = dict(previous)
    for field, label in labels.items():
        value = getattr(args, field, None)
        if value is None:
            default = previous.get(field, detected.get(field, ''))
            value = input(f'{label}' + (f' [{default}]' if default else '') + ': ').strip().strip('"') or default
        if not value and field != 'android_source':
            raise RuntimeError(f'{label} is required.')
        if value:
            settings[field] = str(Path(os.path.expandvars(value)).expanduser().resolve())
        else:
            settings.pop(field, None)
    jobs = getattr(args, 'jobs', None)
    settings['jobs'] = jobs if jobs is not None else previous.get('jobs', 3)
    editor_settings = getattr(args, 'editor_settings', None)
    if editor_settings:
        settings['editor_settings'] = str(Path(os.path.expandvars(editor_settings)).expanduser().resolve())
    elif any((Path(settings['godot']).parent / name).is_file() for name in ['_sc_', '._sc_']):
        settings['editor_settings'] = str(Path(settings['godot']).parent / 'editor_data/editor_settings-4.7.tres')
    if getattr(args, 'd3d12_sdk', None):
        settings['d3d12_sdk'] = str(Path(os.path.expandvars(args.d3d12_sdk)).expanduser().resolve())
    if settings['jobs'] < 1:
        raise RuntimeError('Build jobs must be at least 1.')
    if not (Path(settings['project']) / 'project.godot').is_file():
        raise RuntimeError('Project not found.')
    if not Path(settings['android_sdk']).is_dir() or not (Path(settings['java_home']) / 'bin/java.exe').is_file():
        raise RuntimeError('Android SDK and JDK paths must exist on this machine.')
    if settings.get('android_source') and not (Path(settings['android_source']) / 'version.py').is_file():
        raise RuntimeError('Separate Android source checkout not found.')
    actual = subprocess.check_output([settings['godot'], '--version'], text=True).strip()
    if not actual.startswith('4.7.2.stable.'):
        raise RuntimeError('The editor must be Godot 4.7.2 stable.')
    protect_local(ROOT, STATE)
    if settings.get('android_source'):
        protect_local(Path(settings['android_source']))
    write_json(STATE / 'settings.json', settings)
    print('Machine paths saved locally. The encryption key was not changed.')
    return settings


def save_key(key):
    if not re.fullmatch('[0-9a-f]{64}', key):
        raise RuntimeError('Key must contain exactly 64 hexadecimal characters.')
    STATE.mkdir(exist_ok=True)
    protected = dpapi(key.encode('ascii'))
    (STATE / 'keys').mkdir(exist_ok=True)
    if (STATE / 'key.dpapi').is_file():
        previous_id = fingerprint(read_key())
        shutil.copy2(STATE / 'key.dpapi', STATE / 'keys' / (previous_id + '.dpapi'))
    (STATE / 'keys' / (fingerprint(key) + '.dpapi')).write_bytes(protected)
    (STATE / 'key.dpapi').write_bytes(protected)


def setup(args):
    machine(args)
    change_key(args)


def change_key(args):
    load_settings()
    protect_local(ROOT, STATE)
    if getattr(args, 'generate', False):
        key = secrets.token_hex(32)
    else:
        key = getpass.getpass('Paste 64 hexadecimal characters (hidden); Enter generates a new key: ').strip().lower()
        key = key or secrets.token_hex(32)
    save_key(key)
    print('Key saved with Windows account encryption. Key values are never printed.')
    print('Run build to compile templates, then configure to add encrypted presets.')


def build(args):
    check_pin()
    settings, key = load_settings(), read_key()
    env = environment(settings, key)
    dest = STATE / 'templates' / fingerprint(key)
    dest.mkdir(parents=True, exist_ok=True)
    platforms = ['windows', 'android'] if args.platform == 'all' else [args.platform]
    for platform in platforms:
        source_root = Path(settings.get('android_source', str(ROOT))) if platform == 'android' else ROOT
        if platform == 'android' and source_root != ROOT:
            actual = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=source_root, text=True).strip()
            if actual != PIN:
                raise RuntimeError('The Android source checkout must match the pinned release exactly.')
        for mode in ['release', 'debug']:
            print(f'Building {platform} {mode} with encrypted-pack support...', flush=True)
            options = [sys.executable, '-m', 'SCons', f'-j{settings["jobs"]}', f'platform={platform}',
                       f'target=template_{mode}', 'debug_symbols=no', 'production=yes', 'lto=none']
            options += ['arch=x86_64', 'accesskit=no', 'angle=no'] if platform == 'windows' else ['arch=arm64', 'swappy=yes']
            if mode == 'debug':
                options += ['scu_build=yes', 'scu_limit=8']
            run(options, cwd=source_root, env=env)
            if platform == 'windows':
                source = ROOT / 'bin' / f'godot.windows.template_{mode}.x86_64.exe'
                shutil.copy2(source, dest / f'windows_{mode}_x86_64.exe')
                wrapper = source.with_name(source.stem + '.console.exe')
                if wrapper.exists():
                    shutil.copy2(wrapper, dest / f'windows_{mode}_x86_64.console.exe')
                for name in ['D3D12Core.dll', 'd3d12SDKLayers.dll']:
                    if (ROOT / 'bin' / name).is_file():
                        shutil.copy2(ROOT / 'bin' / name, dest / name)
                sdk = Path(settings.get('d3d12_sdk', str(Path(os.environ['LOCALAPPDATA']) / 'Godot/build_deps/agility_sdk')))
                for name in ['LICENSE.txt', 'LICENSE-CODE.txt']:
                    if (sdk / name).is_file():
                        shutil.copy2(sdk / name, dest / ('D3D12-' + name))
            else:
                source = source_root / 'platform/android/java/lib/libs' / mode / 'arm64-v8a/libgodot_android.so'
            # Marker is written only after successful compilation with this key.
            write_json(dest / f'{platform}-{mode}.json', {'engine': PIN, 'key_id': fingerprint(key), 'binary_sha256': hashlib.file_digest(source.open('rb'), 'sha256').hexdigest()})
        if platform == 'android':
            # Call Gradle explicitly: upstream's SCons wrapper does not propagate Gradle failures.
            run(['cmd', '/d', '/c', 'gradlew.bat', 'generateGodotTemplates', '--no-daemon', '--max-workers=2'], source_root / 'platform/android/java', env)
            for name in ['android_debug.apk', 'android_release.apk', 'android_source.zip']:
                shutil.copy2(source_root / 'bin' / name, dest / name)
            verify_android_templates(dest, key)
            write_json(dest / 'android-ready.json', {'engine': PIN, 'key_id': fingerprint(key)})
    print('Requested templates built successfully.', flush=True)


def verify_android_templates(dest, key):
    with zipfile.ZipFile(dest / 'android_source.zip') as source:
        for mode in ['debug', 'release']:
            candidates = [name for name in source.namelist() if name.startswith(f'libs/{mode}/') and name.endswith('.aar')]
            if len(candidates) != 1:
                raise RuntimeError(f'Expected one {mode} engine AAR in the Android source template.')
            with zipfile.ZipFile(io.BytesIO(source.read(candidates[0]))) as aar:
                engine = aar.read('jni/arm64-v8a/libgodot_android.so')
                if bytes.fromhex(key) not in engine:
                    raise RuntimeError('Android source AAR does not contain the compiled encryption key.')
            with zipfile.ZipFile(dest / f'android_{mode}.apk') as apk:
                if bytes.fromhex(key) not in apk.read('lib/arm64-v8a/libgodot_android.so'):
                    raise RuntimeError('Android APK template does not contain the compiled encryption key.')
    print('PASS: both Android APKs and Gradle AARs contain the matching key.')


def configure_editor(settings):
    path = Path(settings.get('editor_settings', str(Path(os.environ['APPDATA']) / 'Godot/editor_settings-4.7.tres')))
    if not path.is_file():
        run([settings['godot'], '--headless', '--xr-mode', 'off', '--editor', '--path', settings['project'], '--quit'])
    text = path.read_text(encoding='utf-8-sig')
    for field, setting in [('java_sdk_path', 'java_home'), ('android_sdk_path', 'android_sdk')]:
        pattern = rf'^export/android/{field} = .*$'
        if not re.search(pattern, text, re.M):
            raise RuntimeError(f'Editor setting missing: {field}')
        text = re.sub(pattern, lambda _: f'export/android/{field} = ' + json.dumps(Path(settings[setting]).as_posix()), text, flags=re.M)
    path.write_text(text, encoding='utf-8')


def set_value(section, key, value):
    pattern = rf'^{re.escape(key)}=.*$'
    if re.search(pattern, section, re.M):
        return re.sub(pattern, lambda _: f'{key}={value}', section, flags=re.M)
    return section.rstrip() + f'\n{key}={value}\n\n'


def split_presets(text):
    return list(re.finditer(r'^\[preset\.(\d+)\]\s*\n(.*?)(?=^\[preset\.\d+\]\s*$|\Z)', text, re.M | re.S))


def prop(text, key):
    match = re.search(rf'^{re.escape(key)}="(.*)"$', text, re.M)
    return match.group(1) if match else ''


def configure(args):
    settings, key = load_settings(), read_key()
    dest = STATE / 'templates' / fingerprint(key)
    for name in ['windows-release.json', 'windows-debug.json', 'android-ready.json']:
        if not (dest / name).is_file():
            raise RuntimeError('Build all templates with the saved key before configuring.')
    for mode in ['release', 'debug']:
        if not (dest / f'windows_{mode}_x86_64.exe').is_file():
            raise RuntimeError('Windows template is missing; run build.')
    verify_android_templates(dest, key)
    project = Path(settings['project'])
    local = project / '.encrypted-exports'
    local.mkdir(exist_ok=True)
    protect_local(local)
    (local / '.gdignore').touch()
    installed = local / 'templates'
    installed.mkdir(exist_ok=True)
    for name in TEMPLATE_FILES:
        if (dest / name).is_file():
            shutil.copy2(dest / name, installed / name)
    cfg = project / 'export_presets.cfg'
    original = cfg.read_text(encoding='utf-8-sig')
    entries = split_presets(original)
    # Back up each distinct original before writing; keep credentials out of this file.
    backup = STATE / 'backups' / f'export_presets-{time.time_ns()}.cfg'
    backup.parent.mkdir(exist_ok=True)
    backup.write_text(original, encoding='utf-8')
    android_parent = project / 'android' / 'encrypted'
    android_build = android_parent / 'build'
    source_zip = dest / 'android_source.zip'
    android_build.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(source_zip) as archive:
        archive.extractall(android_build)
    (android_build / '.gdignore').touch()
    source_ref = 'res://.encrypted-exports/templates/android_source.zip'
    identifier = source_ref + ' [' + hashlib.md5(source_zip.read_bytes()).hexdigest() + ']\n'
    (android_parent / '.build_version').write_text(identifier, encoding='utf-8')
    # Adopt only previously generated encrypted presets, including after a fresh clone.
    managed = {prop(e.group(2), 'name') for e in entries
               if prop(e.group(2), 'name').endswith(SUFFIX)
               and re.search(r'^custom_template/(?:debug|release)="(?:res://\.encrypted-exports/templates/|[^"\n]*/\.encryption/templates/)', e.group(2), re.M)}
    if (STATE / 'configured.json').is_file():
        managed.update(json.loads((STATE / 'configured.json').read_text())['presets'])
    kept = [e for e in entries if prop(e.group(2), 'name') not in managed]
    next_id = max(int(e.group(1)) for e in entries) + 1
    # Regenerate previous managed presets without renumbering or changing original presets.
    old_ids = {prop(e.group(2), 'name'): int(e.group(1)) for e in entries if prop(e.group(2), 'name') in managed}
    result = original[:entries[0].start()] + ''.join(e.group(0) for e in kept)
    names = []
    for entry in kept:
        text = entry.group(2)
        name, platform = prop(text, 'name'), prop(text, 'platform')
        if name.endswith(SUFFIX):
            continue
        if platform != 'Windows Desktop' and not (platform == 'Android' and 'Quest' in name):
            continue
        encrypted_name = name + SUFFIX
        if encrypted_name not in managed and any(prop(e.group(2), 'name') == encrypted_name for e in kept):
            raise RuntimeError(f'An unmanaged preset already uses the name {encrypted_name}. Rename it before configuring.')
        index = old_ids.get(encrypted_name, next_id)
        if encrypted_name not in old_ids:
            next_id += 1
        text = re.sub(r'^\[preset\.\d+\.options\]', f'[preset.{index}.options]', text, flags=re.M)
        text = set_value(text, 'name', json.dumps(encrypted_name))
        text = set_value(text, 'encrypt_pck', 'true')
        text = set_value(text, 'encrypt_directory', 'true')
        text = set_value(text, 'encryption_include_filters', '"*"')
        text = set_value(text, 'encryption_exclude_filters', '""')
        text = set_value(text, 'script_export_mode', '2')
        path = Path(prop(text, 'export_path'))
        text = set_value(text, 'export_path', json.dumps((path.parent / 'encrypted' / path.name).as_posix()))
        for mode in ['debug', 'release']:
            filename = f'windows_{mode}_x86_64.exe' if platform == 'Windows Desktop' else f'android_{mode}.apk'
            text = set_value(text, f'custom_template/{mode}', json.dumps('res://.encrypted-exports/templates/' + filename))
        if platform == 'Android':
            text = set_value(text, 'gradle_build/gradle_build_directory', json.dumps('res://android/' + android_parent.name))
            text = set_value(text, 'gradle_build/android_source_template', json.dumps(source_ref))
        result += f'\n[preset.{index}]\n\n' + text.rstrip() + '\n'
        names.append(encrypted_name)
    temp = cfg.with_suffix('.tmp')
    temp.write_text(result, encoding='utf-8')
    temp.replace(cfg)
    write_json(STATE / 'configured.json', {'key_id': fingerprint(key), 'presets': names})
    configure_editor(settings)
    print('Configured encrypted presets:\n  ' + '\n  '.join(names))
    print('Use this launcher for exports so the editor receives the matching key.')


def ready():
    settings, key = load_settings(), read_key()
    config = json.loads((STATE / 'configured.json').read_text())
    if config['key_id'] != fingerprint(key):
        raise RuntimeError('Key changed: build all templates and configure before exporting.')
    return settings, key, config


def inherit_signing(project, preset, text, env):
    """Read existing private signing credentials; never copy them into tracked presets."""
    original_name = preset.removesuffix(SUFFIX)
    source = next(e for e in split_presets(text) if prop(e.group(2), 'name') == original_name)
    credentials = project / '.godot/export_credentials.cfg'
    if not credentials.is_file():
        return
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.read(credentials, encoding='utf-8-sig')
    section = f'preset.{source.group(1)}.options'
    if not parser.has_section(section):
        return
    for mode in ['debug', 'release']:
        for field, env_field in [('', 'PATH'), ('_user', 'USER'), ('_password', 'PASSWORD')]:
            value = parser.get(section, f'keystore/{mode}{field}', fallback='""')
            decoded = json.loads(value)
            if decoded:
                if field == '' and decoded.startswith('res://'):
                    decoded = str(project / decoded[6:])
                env[f'GODOT_ANDROID_KEYSTORE_{mode.upper()}_{env_field}'] = decoded


def check_export(output, key):
    if output.suffix.lower() == '.apk':
        with zipfile.ZipFile(output) as apk:
            indexes = [name for name in apk.namelist() if name.endswith('/assets.sparsepck')]
            if len(indexes) != 1:
                raise RuntimeError('Encrypted Android sparse pack index is missing.')
            header = apk.read(indexes[0])[:24]
            if bytes.fromhex(key) not in apk.read('lib/arm64-v8a/libgodot_android.so'):
                raise RuntimeError('Exported APK contains a different engine encryption key.')
    else:
        pack = output.with_suffix('.pck')
        if pack.exists():
            with pack.open('rb') as source:
                header = source.read(24)
        else:
            with output.open('rb') as source:
                source.seek(-12, 2)
                size, magic = struct.unpack('<QI', source.read(12))
                if magic != 0x43504447:
                    raise RuntimeError('Embedded encrypted PCK footer is missing.')
                source.seek(-12 - size, 2)
                header = source.read(24)
    fields = struct.unpack('<6I', header)
    if fields[0] != 0x43504447 or not fields[5] & 1:
        raise RuntimeError('Exported PCK directory is not encrypted.')
    print('PASS: exported package has an encrypted PCK directory.')


def launch(args):
    settings, key, config = ready()
    env = environment(settings, key)
    if args.command == 'editor':
        run([settings['godot'], '--editor', '--path', settings['project']], env=env)
        return
    preset = args.preset
    if not preset:
        for index, name in enumerate(config['presets'], 1):
            print(f'{index}. {name}')
        preset = config['presets'][int(input('Preset number: ')) - 1]
    if preset not in config['presets']:
        raise RuntimeError('Select an encrypted preset created by configure.')
    text = (Path(settings['project']) / 'export_presets.cfg').read_text()
    entry = next(e.group(2) for e in split_presets(text) if prop(e.group(2), 'name') == preset)
    if prop(entry, 'platform') == 'Android':
        inherit_signing(Path(settings['project']), preset, text, env)
    # Recheck flags and templates; reject accidental GUI changes before exporting.
    for field, expected in [('encrypt_pck', 'true'), ('encrypt_directory', 'true'), ('encryption_include_filters', '"*"'), ('encryption_exclude_filters', '""'), ('script_export_mode', '2')]:
        if not re.search(rf'^{field}={re.escape(expected)}$', entry, re.M):
            raise RuntimeError(f'Encrypted preset changed ({field}); run configure again.')
    for mode in ['release', 'debug']:
        reference = prop(entry, f'custom_template/{mode}')
        path = Path(settings['project']) / reference[6:] if reference.startswith('res://') else Path(reference)
        if not path.is_file():
            raise RuntimeError('Template is missing or belongs to a different key.')
        if prop(entry, 'platform') == 'Windows Desktop':
            manifest = json.loads((path.parent / f'windows-{mode}.json').read_text())
            if manifest['key_id'] != fingerprint(key):
                raise RuntimeError('Installed template belongs to a different key; run configure.')
            with path.open('rb') as binary:
                if hashlib.file_digest(binary, 'sha256').hexdigest() != manifest['binary_sha256']:
                    raise RuntimeError('Template differs from the successful build; rebuild before exporting.')
    output = Path(args.output) if args.output else Path(settings['project']) / prop(entry, 'export_path')
    if args.debug and not args.output:
        output = output.with_name(output.stem + '-debug' + output.suffix)
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    run([settings['godot'], '--headless', '--xr-mode', 'off', '--path', settings['project'], '--import'], env=env)
    run([settings['godot'], '--headless', '--xr-mode', 'off', '--path', settings['project'],
         '--export-debug' if args.debug else '--export-release', preset, output], env=env)
    if not output.is_file():
        raise RuntimeError('Export did not produce the requested output.')
    check_export(output, key)
    print(f'Export complete: {output}')


def verify(args):
    """Export a tiny fixture, execute matching templates, and reject a different key."""
    settings, key = load_settings(), read_key()
    dest = STATE / 'templates' / fingerprint(key)
    probe = STATE / 'verification'
    probe.mkdir(exist_ok=True)
    marker = 'GODOT_ENCRYPTION_PROBE_RESOURCE_8da63e'
    (probe / 'project.godot').write_text('config_version=5\n[application]\nconfig/name="Encryption probe"\nrun/main_scene="res://main.tscn"\n[rendering]\nrenderer/rendering_method="gl_compatibility"\n', encoding='utf-8')
    (probe / 'main.tscn').write_text('[gd_scene load_steps=2 format=3]\n[ext_resource type="Script" path="res://main.gd" id="1"]\n[node name="Probe" type="Node"]\nscript = ExtResource("1")\n', encoding='utf-8')
    (probe / 'main.gd').write_text('extends Node\nfunc _ready():\n\tvar args = OS.get_cmdline_user_args()\n\tif not args.is_empty():\n\t\tif ProjectSettings.load_resource_pack(args[0]):\n\t\t\tget_tree().quit(1)\n\t\t\treturn\n\t\tprint("WRONG_KEY_REJECTED")\n\t\tget_tree().quit()\n\t\treturn\n\tif FileAccess.get_file_as_string("res://payload.txt") != "' + marker + '":\n\t\tget_tree().quit(1)\n\t\treturn\n\tprint("ENCRYPTED_PROBE_OK")\n\tget_tree().quit()\n', encoding='utf-8')
    (probe / 'payload.txt').write_text(marker, encoding='utf-8')
    (probe / 'export_presets.cfg').write_text('[preset.0]\nname="Probe"\nplatform="Windows Desktop"\nexport_filter="all_resources"\ninclude_filter="*.txt"\nexclude_filter=""\nencrypt_pck=true\nencrypt_directory=true\nencryption_include_filters="*"\nencryption_exclude_filters=""\nscript_export_mode=2\n[preset.0.options]\ncustom_template/release=' + json.dumps((dest / 'windows_release_x86_64.exe').as_posix()) + '\ncustom_template/debug=' + json.dumps((dest / 'windows_debug_x86_64.exe').as_posix()) + '\nbinary_format/embed_pck=false\n', encoding='utf-8')
    env = environment(settings, key)
    base = [settings['godot'], '--headless', '--xr-mode', 'off', '--path', probe]
    run(base + ['--import'], env=env)
    results = {}
    modes = ['release', 'debug'] if args.mode == 'all' else [args.mode]
    for mode in modes:
        folder = probe / mode
        folder.mkdir(exist_ok=True)
        output = folder / 'probe.exe'
        run(base + [f'--export-{mode}', 'Probe', output], env=env)
        pck = output.with_suffix('.pck').read_bytes()
        header = struct.unpack_from('<6I', pck)
        if header[0] != 0x43504447 or not (header[5] & 1) or marker.encode() in pck:
            raise RuntimeError('PCK directory encryption or resource confidentiality check failed.')
        result = subprocess.run([str(output), '--headless', '--xr-mode', 'off'], capture_output=True, text=True, timeout=60)
        if result.returncode != 0 or 'ENCRYPTED_PROBE_OK' not in result.stdout:
            raise RuntimeError('Matching-key runtime probe failed: ' + result.stdout + result.stderr)
        results[mode] = 'matching key launches and reads encrypted resource; encrypted directory flag set'
    # A different export key must fail against the same template.
    bad_env = env.copy()
    bad_env['GODOT_SCRIPT_ENCRYPTION_KEY'] = secrets.token_hex(32)
    wrong = probe / 'wrong-key'
    wrong.mkdir(exist_ok=True)
    run(base + ['--export-release', 'Probe', wrong / 'probe.exe'], env=bad_env)
    check_export(wrong / 'probe.exe', key)
    # Load the wrong pack from an already running valid project, avoiding the
    # OS startup error dialog shown when the primary project pack cannot open.
    good = probe / modes[0] / 'probe.exe'
    failed = subprocess.run([str(good), '--headless', '--xr-mode', 'off', '--', str(wrong / 'probe.pck')], capture_output=True, text=True, timeout=60)
    if failed.returncode != 0 or 'WRONG_KEY_REJECTED' not in failed.stdout:
        raise RuntimeError('Wrong-key negative control failed: ' + failed.stdout + failed.stderr)
    results['wrong_key'] = 'runtime rejected mismatched encryption key'
    write_json(STATE / 'verification.json', results)
    print('PASS: ' + '/'.join(modes) + ' runtime, encrypted directory/resources, and wrong-key rejection.')


def crypto_types():
    dependencies = STATE / 'python-deps'
    sys.path.insert(0, str(dependencies))
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.hazmat.primitives.kdf.argon2 import Argon2id
    except ImportError:
        print('Installing the release-bundle dependency into this checkout only...')
        run([sys.executable, '-m', 'pip', 'install', '--target', dependencies, 'cryptography==50.0.2'])
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.hazmat.primitives.kdf.argon2 import Argon2id
    return AESGCM, Argon2id


def crypt_bundle(data, password, decrypt=False):
    AESGCM, Argon2id = crypto_types()
    if decrypt:
        if not data.startswith(BUNDLE_MAGIC) or len(data) < len(BUNDLE_MAGIC) + 44:
            raise RuntimeError('Not a supported encrypted template bundle.')
        salt = data[len(BUNDLE_MAGIC):len(BUNDLE_MAGIC) + 16]
        nonce = data[len(BUNDLE_MAGIC) + 16:len(BUNDLE_MAGIC) + 28]
    else:
        salt, nonce = secrets.token_bytes(16), secrets.token_bytes(12)
    header = BUNDLE_MAGIC + salt + nonce
    derived = Argon2id(salt=salt, length=32, iterations=3, lanes=4, memory_cost=65536).derive(password.encode('utf-8'))
    cipher = AESGCM(derived)
    if decrypt:
        try:
            return cipher.decrypt(nonce, data[len(header):], header)
        except Exception:
            raise RuntimeError('Bundle password is incorrect, or the download is damaged.') from None
    return header + cipher.encrypt(nonce, data, header)


def validate_templates(dest, key):
    for name in TEMPLATE_FILES:
        if not (dest / name).is_file():
            raise RuntimeError(f'Template bundle is incomplete: {name}')
    for mode in ['release', 'debug']:
        manifest = json.loads((dest / f'windows-{mode}.json').read_text())
        if manifest.get('engine') != PIN or manifest.get('key_id') != fingerprint(key):
            raise RuntimeError('Windows template manifest does not match this key/version.')
        with (dest / f'windows_{mode}_x86_64.exe').open('rb') as source:
            if hashlib.file_digest(source, 'sha256').hexdigest() != manifest['binary_sha256']:
                raise RuntimeError('Windows template checksum does not match.')
    verify_android_templates(dest, key)


def bundle_export(args):
    key = read_key()
    dest = STATE / 'templates' / fingerprint(key)
    validate_templates(dest, key)
    passwords = STATE / 'transfer-passwords'
    passwords.mkdir(exist_ok=True)
    password_path = passwords / (fingerprint(key) + '.dpapi')
    if password_path.is_file():
        password = dpapi(password_path.read_bytes(), True).decode('ascii')
    else:
        password = secrets.token_urlsafe(32)
        password_path.write_bytes(dpapi(password.encode('ascii')))
    manifest = {'format': 1, 'engine': PIN, 'key_id': fingerprint(key), 'key': key, 'sha256': {}}
    memory = io.BytesIO()
    with zipfile.ZipFile(memory, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name in TEMPLATE_FILES + LICENSE_FILES:
            source = ROOT / name if name in ['LICENSE.txt', 'COPYRIGHT.txt'] else dest / name
            content = source.read_bytes()
            manifest['sha256'][name] = hashlib.sha256(content).hexdigest()
            archive.writestr(name, content)
        archive.writestr('bundle.json', json.dumps(manifest))
    output = Path(args.output).resolve() if args.output else STATE / 'releases' / f'godot-4.7.2-windows-x86_64-quest-arm64-{fingerprint(key)}.gdtbundle'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(crypt_bundle(memory.getvalue(), password))
    with output.open('rb') as source:
        digest = hashlib.file_digest(source, 'sha256').hexdigest()
    output.with_name(output.name + '.sha256').write_text(digest + '  ' + output.name + '\n', encoding='ascii')
    print(f'Encrypted release bundle ready: {output}')
    print('Retrieve its private transfer password locally using menu 8. Do not upload that password.')


def restore_bundle(path, password):
    """Authenticate and validate everything before changing the machine's active key."""
    payload = crypt_bundle(Path(path).read_bytes(), password, decrypt=True)
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        expected = set(TEMPLATE_FILES + LICENSE_FILES + ['bundle.json'])
        if set(archive.namelist()) != expected or len(archive.namelist()) != len(expected):
            raise RuntimeError('Unexpected or missing files in the bundle.')
        manifest = json.loads(archive.read('bundle.json'))
        key = manifest.get('key', '')
        if manifest.get('format') != 1 or manifest.get('engine') != PIN or not re.fullmatch('[0-9a-f]{64}', key):
            raise RuntimeError('Bundle version or key is invalid.')
        if manifest.get('key_id') != fingerprint(key) or set(manifest.get('sha256', {})) != expected - {'bundle.json'}:
            raise RuntimeError('Bundle manifest is invalid.')
        with tempfile.TemporaryDirectory(prefix='bundle-', dir=STATE) as staging:
            stage = Path(staging)
            for name in expected - {'bundle.json'}:
                content = archive.read(name)
                if hashlib.sha256(content).hexdigest() != manifest['sha256'][name]:
                    raise RuntimeError('Bundle checksum mismatch.')
                (stage / name).write_bytes(content)
            validate_templates(stage, key)
            dest = STATE / 'templates' / fingerprint(key)
            dest.mkdir(parents=True, exist_ok=True)
            for name in expected - {'bundle.json'}:
                shutil.copy2(stage / name, dest / name)
            save_key(key)
    print('Templates imported; the matching game key is protected for this Windows account.')


def bundle_import(args):
    load_settings()
    protect_local(ROOT, STATE)
    path = args.file or input('Downloaded .gdtbundle file: ').strip().strip('"')
    password = getpass.getpass('Private transfer password (hidden): ')
    restore_bundle(path, password)
    configure(argparse.Namespace())


def bundle_password(args):
    path = STATE / 'transfer-passwords' / (fingerprint(read_key()) + '.dpapi')
    if not path.is_file():
        raise RuntimeError('This machine has no saved transfer password for the current key.')
    input('Press Enter to display the PRIVATE download password on this console only...')
    print(dpapi(path.read_bytes(), True).decode('ascii'))
    print('Save it in your password manager. Do not publish it or paste it into chat.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    setup_parser = sub.add_parser('setup')
    machine_parser = sub.add_parser('machine', help='Configure this machine without changing its key')
    for target in [setup_parser, machine_parser]:
        for field in ['project', 'godot', 'android-sdk', 'java-home', 'android-source']:
            target.add_argument('--' + field)
        target.add_argument('--jobs', type=int)
        target.add_argument('--editor-settings', help='Optional editor settings file for custom/portable editor layouts')
        target.add_argument('--d3d12-sdk', help='Optional custom Agility SDK path for rebuild license notices')
    setup_parser.add_argument('--generate', action='store_true')
    build_parser = sub.add_parser('build')
    build_parser.add_argument('--platform', choices=['all', 'windows', 'android'], default='all')
    sub.add_parser('configure')
    sub.add_parser('editor')
    export_parser = sub.add_parser('export')
    export_parser.add_argument('--preset')
    export_parser.add_argument('--output')
    export_parser.add_argument('--debug', action='store_true')
    sub.add_parser('key')
    bundle_parser = sub.add_parser('bundle', help='Create a password-protected release download')
    bundle_parser.add_argument('--output')
    import_parser = sub.add_parser('import-bundle', help='Import a release download without rebuilding')
    import_parser.add_argument('--file')
    sub.add_parser('bundle-password', help='Display the private transfer password locally')
    verify_parser = sub.add_parser('verify')
    verify_parser.add_argument('--mode', choices=['all', 'release', 'debug'], default='all')
    args = parser.parse_args()
    if args.command == 'setup':
        setup(args)
    elif args.command == 'machine':
        machine(args)
    elif args.command == 'bundle':
        bundle_export(args)
    elif args.command == 'import-bundle':
        bundle_import(args)
    elif args.command == 'bundle-password':
        bundle_password(args)
    elif args.command == 'build':
        build(args)
    elif args.command == 'configure':
        configure(args)
    elif args.command == 'verify':
        verify(args)
    elif args.command == 'key':
        change_key(args)
    else:
        launch(args)


if __name__ == '__main__':
    try:
        main()
    except (Exception, KeyboardInterrupt) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        sys.exit(1)
