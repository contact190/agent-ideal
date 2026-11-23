@echo off
chcp 65001 >nul
rem Le script se copie dans le dossier temporaire avant de mettre a jour (il ne doit pas se remplacer pendant qu'il tourne)
if /i not "%~1"=="--copie" (
  copy /y "%~f0" "%TEMP%\agent_ideal_maj.bat" >nul
  "%TEMP%\agent_ideal_maj.bat" --copie "%~dp0"
  exit /b
)
cd /d "%~2"
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
".venv\Scripts\python.exe" creer_raccourci.py
echo.
echo Termine. Arrete l'agent (bouton ⏻ en haut a droite) puis relance-le avec l'icone du Bureau.
pause
