@echo off
setlocal
cd /d "%~dp0"
if /i "%~1"=="python" goto select_python
set "PYTHON_ARGS="
set "PYTHON=%GODOT_ENCRYPTION_PYTHON%"
if defined PYTHON goto check_python
if exist "%~dp0.encryption\python.path" set /p "PYTHON="<"%~dp0.encryption\python.path"
if defined PYTHON goto check_python
if exist "%~dp0.venv\Scripts\python.exe" set "PYTHON=%~dp0.venv\Scripts\python.exe"
if defined PYTHON goto check_python
where py >nul 2>nul
if not errorlevel 1 (
  set "PYTHON=py"
  set "PYTHON_ARGS=-3"
  goto check_python
)
where python >nul 2>nul
if not errorlevel 1 (
  set "PYTHON=python"
  goto check_python
)
goto select_python
:check_python
"%PYTHON%" %PYTHON_ARGS% -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" >nul 2>nul
if errorlevel 1 (
  echo Python 3.11 or newer is required. Run EncryptedExports.bat python to select it.
  exit /b 1
)
if not "%~1"=="" (
  "%PYTHON%" %PYTHON_ARGS% "%~dp0misc\encrypted_exports\encrypted_exports.py" %*
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
echo 6. Configure this machine's project and tool paths
echo 7. Import a downloaded release bundle, then configure presets
echo 8. Display the private release download password on this machine
choice /c 12345678 /n /m "Choose: "
if errorlevel 8 goto password
if errorlevel 7 goto import_bundle
if errorlevel 6 goto machine
if errorlevel 5 exit /b 0
if errorlevel 4 goto editor
if errorlevel 3 goto export
if errorlevel 2 goto build
"%PYTHON%" %PYTHON_ARGS% "%~dp0misc\encrypted_exports\encrypted_exports.py" key
goto done
:build
"%PYTHON%" %PYTHON_ARGS% "%~dp0misc\encrypted_exports\encrypted_exports.py" build
if errorlevel 1 goto done
"%PYTHON%" %PYTHON_ARGS% "%~dp0misc\encrypted_exports\encrypted_exports.py" configure
goto done
:export
echo D: Debug export. R: Release export; Quest requires a release keystore.
choice /c DR /n /m "Build type: "
if errorlevel 2 goto release
"%PYTHON%" %PYTHON_ARGS% "%~dp0misc\encrypted_exports\encrypted_exports.py" export --debug
goto done
:release
"%PYTHON%" %PYTHON_ARGS% "%~dp0misc\encrypted_exports\encrypted_exports.py" export
goto done
:editor
"%PYTHON%" %PYTHON_ARGS% "%~dp0misc\encrypted_exports\encrypted_exports.py" editor
goto done
:machine
"%PYTHON%" %PYTHON_ARGS% "%~dp0misc\encrypted_exports\encrypted_exports.py" machine
goto done
:import_bundle
"%PYTHON%" %PYTHON_ARGS% "%~dp0misc\encrypted_exports\encrypted_exports.py" import-bundle
goto done
:password
"%PYTHON%" %PYTHON_ARGS% "%~dp0misc\encrypted_exports\encrypted_exports.py" bundle-password
:done
pause
goto menu
:select_python
echo Choose a Python 3.11+ executable for this machine.
set /p "PYTHON=Full path to python.exe (without quotes): "
if not exist "%PYTHON%" exit /b 1
"%PYTHON%" -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" >nul 2>nul
if errorlevel 1 exit /b 1
if not exist "%~dp0.encryption" mkdir "%~dp0.encryption"
>"%~dp0.encryption\python.path" <nul set /p "=%PYTHON%"
echo Python choice saved for this checkout. Open the launcher again.
exit /b 0
