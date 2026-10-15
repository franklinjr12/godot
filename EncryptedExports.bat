@echo off
setlocal
cd /d "%~dp0"
set "PYTHON=%~dp0..\godot-build-tools\python\Scripts\python.exe"
if not exist "%PYTHON%" (
  echo Build Python is missing. See ENCRYPTED_EXPORTS.md for installation.
  pause
  exit /b 1
)
if not "%~1"=="" (
  "%PYTHON%" "%~dp0misc\encrypted_exports\encrypted_exports.py" %*
  exit /b
)
:menu
echo.
echo Godot 4.7.2 - Encrypted exports
echo 1. Enter or generate a new encryption key
echo 2. Build Windows and Quest templates, then configure presets
echo 3. Export an encrypted game build
echo 4. Open the game editor with the saved key
echo 5. Exit
choice /c 12345 /n /m "Choose: "
if errorlevel 5 exit /b 0
if errorlevel 4 goto editor
if errorlevel 3 goto export
if errorlevel 2 goto build
"%PYTHON%" "%~dp0misc\encrypted_exports\encrypted_exports.py" key
goto done
:build
"%PYTHON%" "%~dp0misc\encrypted_exports\encrypted_exports.py" build
if errorlevel 1 goto done
"%PYTHON%" "%~dp0misc\encrypted_exports\encrypted_exports.py" configure
goto done
:export
echo D: Debug export. R: Release export; Quest requires a release keystore.
choice /c DR /n /m "Build type: "
if errorlevel 2 goto release
"%PYTHON%" "%~dp0misc\encrypted_exports\encrypted_exports.py" export --debug
goto done
:release
"%PYTHON%" "%~dp0misc\encrypted_exports\encrypted_exports.py" export
goto done
:editor
"%PYTHON%" "%~dp0misc\encrypted_exports\encrypted_exports.py" editor
:done
pause
goto menu
