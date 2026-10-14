@echo off
rem GlowLabStudio.exe in this folder, next to library\, projects\ and settings.json, which it uses.
cd /d "%~dp0"
python -m PyInstaller --noconfirm --clean --onefile --windowed --name GlowLabStudio --icon "%~dp0ui\icon.ico" ^
  --add-data "%~dp0ui;ui" --add-data "%~dp0metrics.json;." --collect-data playwright ^
  --distpath "%~dp0." --workpath build --specpath build app.py || exit /b 1
echo Done: %~dp0GlowLabStudio.exe
