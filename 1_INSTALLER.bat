@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"
title Installation de l'Agent Ideal
echo %~dp0 | findstr /i "\\Temp\\" >nul && (
  echo ERREUR : tu as lance ce fichier depuis l'interieur du ZIP.
  echo Fais un clic droit sur le zip, "Extraire tout...", puis relance depuis le dossier extrait.
  pause & exit /b
)
echo ============================================
echo   Installation de l'Agent Ideal
echo ============================================
echo.
set PY=
where py >nul 2>nul && set PY=py -3
if not defined PY ( where python >nul 2>nul && python -c "import sys" >nul 2>nul && set PY=python )
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set PY="%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PY (
  echo Python n'est pas installe : installation automatique de Python 3.12...
  winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
  if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set PY="%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
)
if not defined PY (
  echo.
  echo ERREUR : impossible d'installer Python automatiquement.
  echo Installe Python 3.12 depuis python.org en cochant "Add python.exe to PATH", puis relance ce fichier.
  start https://www.python.org/downloads/windows/
  pause & exit /b
)
if not exist ".venv\Scripts\python.exe" %PY% -m venv .venv
if not exist ".venv\Scripts\python.exe" (
  echo ERREUR : creation de l'environnement Python impossible.
  pause & exit /b
)
".venv\Scripts\python.exe" --version
".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
for /f "usebackq delims=" %%P in ("requirements.txt") do (
  echo.
  echo ----- %%P
  ".venv\Scripts\python.exe" -m pip install "%%P" --quiet --disable-pip-version-check
)
echo.
echo ===== Verification =====
".venv\Scripts\python.exe" verifier_installation.py
if errorlevel 1 ( pause & exit /b )
echo.
echo Creation du raccourci "Agent Ideal" sur le Bureau...
".venv\Scripts\python.exe" creer_raccourci.py
echo.
echo ============================================
echo   Termine ! Double-clique sur "Agent Ideal"
echo   sur ton Bureau pour lancer l'agent.
echo ============================================
pause
