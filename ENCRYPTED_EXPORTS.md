# Encrypted exports for Beach Volleyball VR

This fork uses **Godot 4.7.2 stable**, upstream commit
`ed1daf0bf001b61586d9930840f2f1394092c079`, matching the game's installed editor.
The engine's existing AES-256 PCK encryption is used without changes to gameplay
or the engine's encryption algorithm.

## Everyday use

Double-click **`C:\Repos\godot\EncryptedExports.bat`**.

1. Choose **3** to export with the current local key. Pick the preset by number.
2. Choose **4** to open the editor with that key available to its export process.
   Close other editor instances for this project before launching this way.
3. To supply your own key, choose **1** and paste **64 hexadecimal characters**
   into the hidden prompt. Blank input generates a random 256-bit key.
4. After changing a key, choose **2**. This rebuilds both Windows x86_64 and Quest
   ARM64 debug/release templates and configures the game. Compilation takes time;
   subsequent builds reuse SCons' compilation cache.

The game gets additional presets ending in **` (Encrypted)`**, covering all its
Windows presets and its three Quest presets (standard, full release, demo).
The original presets remain available. Outputs use an `encrypted` subfolder
under each original export folder; debug exports from the launcher add `-debug`
to the file name. Demo features and XR settings are inherited.
Linux, WebXR and other standalone headsets are outside this setup.

The key field in the stock editor can appear empty and show a validation message.
The launcher supplies `GODOT_SCRIPT_ENCRYPTION_KEY`, which Godot 4.7.2 uses in
preference to that field. For a checked export, use menu **3**. Exporting an
encrypted preset from an editor started normally will not receive this key.
Do not enter the key into a tracked configuration file.

## Command line

From this repository:

```bat
EncryptedExports.bat build
EncryptedExports.bat configure
EncryptedExports.bat verify
EncryptedExports.bat export --preset "Windows SteamVR Release (Encrypted)"
EncryptedExports.bat export --preset "Android Quest Release (Encrypted)" --debug
```

`export` defaults to a release export; Android release signing still requires
your release keystore and its credentials. `--debug` uses debug signing and the
debug template. Encryption keys and signing keys have different purposes.
The launcher does not invent or replace a store signing identity.
For Quest exports through menu **3**, existing signing credentials are read
privately from the matching original preset and passed to Godot in the export
process environment. They are never copied into the tracked preset file.
Use menu **3** for Android exports to retain this signing-credential mapping.

## Key storage and limits

The key is stored in `.encryption/key.dpapi` using Windows DPAPI CurrentUser.
The key directory and both engine source/build folders have access restricted
to the current Windows account and SYSTEM, including inherited build files.
It is ignored by Git. Previous protected keys are retained in `.encryption/keys`;
templates are grouped by a non-secret key fingerprint. Back up the key you
provide using a password manager. A DPAPI file alone is not a portable backup
for a different Windows installation or account. The generated initial key can
be replaced with one you have backed up, using menu **1**, then **2**.

No key is placed in this repository's tracked files, shell arguments, global
environment variables, or GitHub Actions. The launcher sets process-local
environment variables only for compilation/export and editor launch.
Godot's generated C++ key source, object files, SCons signature database and
compiled templates necessarily contain key material; keep this build checkout
private on disk and never share build intermediates. Git ignores these files.
DPAPI protects the saved key at rest; it does not protect it from software
already running under your Windows account.

Encryption makes extraction harder; it cannot prevent a determined reverse
engineer from recovering the key from a shipped executable or Android library.
Embedding a PCK changes packaging and does not add cryptographic protection.
All packaged resources (`*`) and the PCK directory are encrypted here; scripts
use compressed binary tokens. Native extensions remain native binaries.

## How Quest Gradle exports work

Android templates include the engine compiled with the same key for ARM64.
The build generates `android_debug.apk`, `android_release.apk` and
`android_source.zip`, including the matching AAR files. Configuration installs
that source ZIP under the game's ignored `android/encrypted-<key-id>/build`
directory and writes Godot's required `.build_version` identifier. This prevents
the Gradle build from quietly using an ordinary, unencrypted engine AAR.
No default templates are overwritten.

Machine-specific settings live in `.encryption/settings.json`. After moving the
checkout, update these settings, run `build`, then `configure`. Configuration
backs up `export_presets.cfg` before adding/updating the managed presets.
Changing key invalidates the launcher's old configuration until rebuilding and
configuring are complete. Never rotate keys while a build or export is running.
This machine also uses a matching Android source checkout at
`C:\Repos\godot-build-tools\android-source` to keep its native build cache
separate from Windows. Its location is saved as `android_source` in the local
settings; it shares the same pinned engine source and contains no engine edits.

## Build prerequisites

This computer was set up with Git, Python 3.14, an isolated environment at
`C:\Repos\godot-build-tools\python` with SCons 4.10.1, Visual Studio 2022 C++
Build Tools and Windows SDK, Temurin JDK 17, Android command-line tools, Android
SDK platform 36, build tools 36.1.0, and NDK 29.0.14206865. The game may also need
platform/build-tools versions specified in its Android presets.
Godot's official D3D12 build dependencies and Swappy frame pacing dependency
are installed. Vulkan, OpenGL, OpenXR and D3D12 support are retained.
The Windows templates exclude the optional AccessKit screen-reader integration
and ANGLE translation layer (`accesskit=no angle=no`); native OpenGL is included.
Debug templates use Godot's single compilation unit build option with a limit
of eight source files per unit to reduce compilation overhead.

Initial setup is reproducible with the installed tools:

```bat
EncryptedExports.bat setup --godot "%USERPROFILE%\Documents\Godot\Godot_console.exe" --android-sdk "C:\Repos\godot-build-tools\android-sdk" --java-home "PATH_TO_JDK_17" --project "C:\Repos\BeachVolleyballVr" --jobs 3
EncryptedExports.bat build
EncryptedExports.bat verify
EncryptedExports.bat configure
```

`verify` exports a tiny test project with encrypted resources, runs both Windows
templates, checks the encrypted directory flag and confirms a different key is
rejected. Its report is `.encryption/verification.json`.

## Sources

- [Godot PCK encryption](https://docs.godotengine.org/en/4.7/engine_details/development/compiling/compiling_with_script_encryption_key.html)
- [Building Android templates](https://docs.godotengine.org/en/4.7/engine_details/development/compiling/compiling_for_android.html)
- [Building Windows templates](https://docs.godotengine.org/en/4.7/engine_details/development/compiling/compiling_for_windows.html)
- Exact behavior was also checked against this checkout's
  `editor/export/editor_export_platform.cpp`,
  `editor/export/export_template_manager.cpp` and
  `platform/android/export/export_plugin.cpp`.
