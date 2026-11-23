@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Mise a jour de l'Agent Ideal depuis GitHub...
echo (tes reglages, ta cle et tes taches ne sont pas touches)
echo.
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop';" ^
  "$z=Join-Path $env:TEMP 'agent-ideal-maj.zip'; $d=Join-Path $env:TEMP 'agent-ideal-maj';" ^
  "Invoke-WebRequest 'https://github.com/contact190/agent-ideal/archive/refs/heads/main.zip' -OutFile $z;" ^
  "if (Test-Path $d) { Remove-Item $d -Recurse -Force }; Expand-Archive $z $d;" ^
  "$src=Get-ChildItem $d -Directory | Select-Object -First 1;" ^
  "Copy-Item (Join-Path $src.FullName '*') -Destination '.' -Recurse -Force;" ^
  "Write-Host 'Fichiers mis a jour.'"
if errorlevel 1 ( echo ERREUR : telechargement impossible. Verifie la connexion Internet. & pause & exit /b )
echo.
echo Mise a jour des bibliotheques...
for /f "usebackq delims=" %%P in ("requirements.txt") do ".venv\Scripts\python.exe" -m pip install "%%P" --quiet --disable-pip-version-check
".venv\Scripts\python.exe" verifier_installation.py
echo.
echo Termine. Ferme l'agent (bouton ⏻) et relance-le pour utiliser la nouvelle version.
pause
