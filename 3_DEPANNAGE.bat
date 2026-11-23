@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Lancement de l'agent en mode depannage (les erreurs s'affichent ici).
echo Ferme cette fenetre pour arreter l'agent.
echo.
".venv\Scripts\python.exe" app.py
pause
