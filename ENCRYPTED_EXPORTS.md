# Encrypted Windows and Quest exports

This fork pins **Godot 4.7.2 stable**, upstream commit
`ed1daf0bf001b61586d9930840f2f1394092c079`. It uses Godot's existing AES-256 PCK
encryption without changing gameplay or the engine's encryption algorithm.

## Set up another Windows machine without rebuilding

1. Download and extract the small **export-launcher ZIP** from Releases, or clone
   this fork's default branch wherever you prefer. Install **Python 3.11+
   for Windows x64**, the **Godot 4.7.2 stable editor**, **JDK 17**, and Android
   SDK tools for the Quest workflow. No C++ compiler or SCons is needed when
   importing these prebuilt templates.
2. Open `EncryptedExports.bat` in your chosen checkout. Choose **6** and enter
   this machine's game folder, editor executable, Android SDK, and JDK paths.
   The optional separate Android source checkout is only needed when rebuilding.
3. Download the `.gdtbundle` asset from this fork's
   [Releases](https://github.com/franklinjr12/godot/releases), together with its
   SHA-256 checksum. The bundle includes both Windows x86_64 templates, Quest
   ARM64 APK templates, the matching Android Gradle/AAR source bundle, and licenses.
4. Obtain the private transfer password from the original build machine: open
   its launcher and choose **8**. Save it in your password manager and transfer
   it privately. Do not post it on GitHub or in chat.
5. On the new machine choose **7**, enter the downloaded file path, and paste
   the transfer password into the hidden prompt. Import validates the files,
   protects the matching game key for the new Windows account, installs the
   templates, and configures the game's encrypted presets. No native rebuild runs.
6. Choose **3**, select Debug or Release, then select the game preset.
   Quest store release exports still require your release signing keystore;
   Debug exports use debug signing.

The fork is public, so its prebuilt templates are distributed in a
**password-protected download**, not as exposed binaries containing the active
game key. The download uses AES-256-GCM with an Argon2id-derived key and includes
authenticated file checksums. The randomly generated transfer password stays
DPAPI-protected on the originating machine. It is different from the game key.
The import/export commands install `cryptography==50.0.2` and its dependencies
under the ignored `.encryption/python-deps` folder when first needed; this requires
internet access once. They do not install packages globally.

## Paths belong to each machine

There is no required checkout location or drive letter.

- Menu **6** / `EncryptedExports.bat machine` saves project, editor, Java, SDK,
  optional Android engine checkout, and build parallelism in the ignored
  `.encryption/settings.json`. Updating these paths never changes the game key.
  Portable Godot editor layouts are detected; `machine --editor-settings` can
  override the editor settings file for other custom layouts.
- Python is selected with `EncryptedExports.bat python`, saved in the ignored
  `.encryption/python.path`. Alternatively set `GODOT_ENCRYPTION_PYTHON` to the
  full executable path. The launcher also detects a checkout-local `.venv`,
  `py -3`, or `python` on PATH. Python must be at least 3.11.
- The game's tracked encrypted presets use only project-relative template paths:
  `res://.encrypted-exports/templates/...`. Configuration copies the matching
  templates there, and installs Gradle sources under `res://android/encrypted/build`.
  Both locations are ignored by Git and excluded from resource import.
  Local state/template directories also create their own `.gitignore` files, so
  fresh game checkouts and launcher downloads inside another repository stay safe
  even before the game's root ignore rules are committed.
- Each clone regenerates its local template identifier and preserves the original
  presets, features, XR settings, and signing-credential mapping. A clone containing
  existing managed encrypted presets can adopt them without duplicating entries.
- After moving a checkout or game folder, run menu **6**, then `configure`.
  Existing imported templates can be reused without rebuilding.

The game also includes `scripts/encrypted_exports.ps1`. Run it with `-Configure`
to choose the fork checkout for that machine and configure its tools. It remembers
the fork location in the game's ignored `.encrypted-exports/machine.json`.
Run it again without arguments to open the launcher.

## Everyday use and rebuilding

- **1:** Enter a new 64-character hexadecimal game key, or generate one with
  blank input. Back up a key you provide in your password manager.
- **2:** Compile Windows and Quest debug/release templates, then configure the
  game. Required after changing the game key unless importing a matching bundle.
- **3:** Export and check an encrypted game package.
- **4:** Open the editor with the saved export key. Close other editor instances
  for the same project first.
- **5:** Exit. **6:** Machine paths. **7:** Import release. **8:** Private transfer password.

Original game presets are preserved. Additional presets end in ` (Encrypted)`
and cover all Windows presets and the three Quest presets. Outputs use an
`encrypted` subfolder under the original export folder. Debug outputs add `-debug`
to their filename. Demo features and existing OpenXR configuration are inherited.
Linux, WebXR, Pico and other headset targets are outside this setup.

The stock editor's key field may appear empty: the launcher supplies
`GODOT_SCRIPT_ENCRYPTION_KEY` to the export process. Prefer menu **3** for verified
exports and signing-credential mapping. Signing credentials are read privately
from the corresponding original preset, without copying them into tracked files.
Persistent Gradle daemons are disabled for child exports so the Windows console
wrapper exits cleanly after Android builds.

```bat
EncryptedExports.bat machine
EncryptedExports.bat import-bundle --file "PATH_TO_DOWNLOADED_FILE.gdtbundle"
EncryptedExports.bat configure
EncryptedExports.bat export --preset "Windows SteamVR Release (Encrypted)"
EncryptedExports.bat export --preset "Android Quest Release (Encrypted)" --debug
EncryptedExports.bat verify
```

For rebuilding, use Visual Studio 2022 C++ Build Tools / Windows SDK, SCons 4.10.1
in your chosen Python environment, JDK 17, Android SDK platform 36, build tools
36.1.0, and NDK 29.0.14206865. Install additional SDK versions required by your
game's presets. Install Godot's official D3D12 and Swappy dependencies using the
upstream `misc/scripts` installers. Windows excludes optional AccessKit and ANGLE;
native OpenGL, Vulkan, OpenXR and D3D12 remain available. Builds use
`production=yes lto=none debug_symbols=no`; debug uses SCU with eight files per unit.
`--jobs` on the `machine` command sets build parallelism.
The official Agility SDK location follows the current Windows user's LocalAppData;
`machine --d3d12-sdk` can override its location when rebuilding. Release bundles
include the Godot/third-party notices and Microsoft's original Agility SDK notices.
Rebuilding requires the full source clone; the small launcher ZIP supports prebuilt
import and export without downloading the engine sources.

```bat
EncryptedExports.bat build
EncryptedExports.bat verify
EncryptedExports.bat configure
EncryptedExports.bat bundle
```

`bundle` creates only a password-protected release asset plus a public checksum.
It includes the matching game key inside the encrypted payload so another Windows
account can protect its own copy. Never upload the `.encryption` directory,
unprotected templates, generated C++ key source, build caches, DPAPI files,
machine settings, transfer passwords, or signing credentials.

## Protection limits and validation

The saved game key uses Windows DPAPI CurrentUser. Source/build checkouts and
local template directories are restricted to the current account and SYSTEM.
A DPAPI file alone cannot migrate the key to another account or installation;
use the protected release import or enter the original key privately.
DPAPI does not protect against software already running as your Windows user.

All packaged resources and the PCK directory are encrypted; scripts use compressed
binary tokens. Native extensions remain native binaries. A determined reverse
engineer can still recover a key from shipped runtime binaries. Embedding the
PCK changes packaging and adds no cryptographic strength.

`verify` runs both Windows templates with an encrypted fixture and rejects a pack
made with a different key. Reports remain under ignored `.encryption` files.
Headless and desktop checks do not establish Quest tracking, rendering, gameplay,
or performance; test those on a Quest 3 before shipping.

## References

- [Godot encryption](https://docs.godotengine.org/en/4.7/engine_details/development/compiling/compiling_with_script_encryption_key.html)
- [Android compilation](https://docs.godotengine.org/en/4.7/engine_details/development/compiling/compiling_for_android.html)
- [Windows compilation](https://docs.godotengine.org/en/4.7/engine_details/development/compiling/compiling_for_windows.html)
- [Cryptography authenticated encryption](https://cryptography.io/en/latest/hazmat/primitives/aead/)
