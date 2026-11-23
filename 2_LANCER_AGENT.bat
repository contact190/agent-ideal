@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo L'agent n'est pas installe : lance d'abord 1_INSTALLER.bat
  pause & exit /b
)
start "" ".venv\Scripts\pythonw.exe" "%~dp0app.py"
