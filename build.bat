@echo off
rem ASCII-only on purpose: cmd reads .bat in the OEM codepage, and CJK + "&"
rem gets mis-parsed. Chinese docs live in README.md.
cd /d "%~dp0"

echo [1/3] self-test...
python test_app.py
if errorlevel 1 goto :failed

echo.
echo [2/3] cleaning old artifacts...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo.
echo [3/3] packaging (PyInstaller onefile)...
python -m PyInstaller --noconfirm DevCleaner.spec
if errorlevel 1 goto :failed

copy /y settings.yaml dist\settings.yaml >nul
echo.
echo DONE: dist\DevCleaner.exe
echo Edit dist\settings.yaml to configure; no rebuild needed.
goto :end

:failed
echo.
echo FAILED - see the error above.
:end
pause
